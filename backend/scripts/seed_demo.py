"""Seed the demo state for Phase 6.

Idempotent: wipes and rebuilds the two demo projects, hides test projects,
writes a deliberate learner model, and embeds every seeded node so echoes and
contradiction detection work before the demo starts.

  cd backend && .venv/bin/python scripts/seed_demo.py

What it sets up:
- "AI in Education" (3 seeded sessions, research track) — contains the claim
  "Immediate feedback is always more effective than delayed feedback" which a
  live demo claim ("delayed feedback produces better long-term retention")
  will contradict across sessions.
- "EdTech Product Strategy" (2 seeded sessions, applied track) — contains
  "User engagement is the strongest predictor of retention", which echoes the
  research project's "Student engagement is the strongest predictor of
  learning outcomes" via a connects_to edge.
- One ingested-literature node with provenance, so conversation and literature
  coexist in the graph before the demo starts.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.graph import repo  # noqa: E402
from app.schemas import ExtractedEdge, ExtractedNode, GraphDiff  # noqa: E402
from app.services.embeddings import embed_many  # noqa: E402

RESEARCH = "ai-in-education"
PRODUCT = "edtech-product-strategy"
HIDE = ["phase-2-cloud-e2e", "phase-4-learner-loop", "mastery-learning-notes"]

# The claim a live demo turn will contradict (cross-session contradiction).
CONTRADICTION_SEED = (
    "Immediate feedback is always more effective than delayed feedback "
    "for learning"
)
# Echo pair (>0.78 cosine, distinct enough to feel like insight).
ECHO_RESEARCH = "Student engagement is the strongest predictor of learning outcomes"
ECHO_PRODUCT = "User engagement is the strongest predictor of retention"

RESEARCH_SESSIONS: list[tuple[str, list[ExtractedNode], list[ExtractedEdge]]] = [
    (
        "s_seed_r1",
        [
            ExtractedNode(type="claim", text="Adaptive tutoring systems improve learning outcomes primarily by personalizing pacing to each student"),
            ExtractedNode(type="claim", text=CONTRADICTION_SEED),
            ExtractedNode(type="concept", text="Adaptive learning"),
            ExtractedNode(type="claim", text="Most adaptive platforms personalize content selection but not the pedagogy itself"),
            ExtractedNode(type="gap", text="No evidence yet that pacing personalization, not content quality, drives the outcome gains"),
        ],
        [
            ExtractedEdge(from_text="Adaptive tutoring systems improve learning outcomes primarily by personalizing pacing to each student", to_text="Adaptive learning", relation="refines"),
            ExtractedEdge(from_text="Most adaptive platforms personalize content selection but not the pedagogy itself", to_text="Adaptive tutoring systems improve learning outcomes primarily by personalizing pacing to each student", relation="questions"),
        ],
    ),
    (
        "s_seed_r2",
        [
            ExtractedNode(type="claim", text="Mastery learning requires students to demonstrate proficiency before advancing to the next unit"),
            ExtractedNode(type="claim", text="Mastery learning's effect size shrinks when students self-pace without tutor support"),
            ExtractedNode(type="concept", text="Mastery learning"),
            ExtractedNode(type="question", text="Does mastery learning scale to classrooms without one tutor per student?"),
        ],
        [
            ExtractedEdge(from_text="Mastery learning's effect size shrinks when students self-pace without tutor support", to_text="Does mastery learning scale to classrooms without one tutor per student?", relation="questions"),
        ],
    ),
    (
        "s_seed_r3",
        [
            ExtractedNode(type="claim", text=ECHO_RESEARCH),
            ExtractedNode(type="claim", text="Engagement metrics from platforms measure behavioral activity, not cognitive engagement"),
            ExtractedNode(type="gap", text="The engagement-to-learning link may be confounded by prior motivation"),
        ],
        [
            ExtractedEdge(from_text="Engagement metrics from platforms measure behavioral activity, not cognitive engagement", to_text=ECHO_RESEARCH, relation="questions"),
        ],
    ),
]

PRODUCT_SESSIONS: list[tuple[str, list[ExtractedNode], list[ExtractedEdge]]] = [
    (
        "s_seed_p1",
        [
            ExtractedNode(type="claim", text=ECHO_PRODUCT),
            ExtractedNode(type="claim", text="Churn in the first two weeks is driven by onboarding friction, not content quality"),
            ExtractedNode(type="concept", text="Retention"),
        ],
        [
            ExtractedEdge(from_text="Churn in the first two weeks is driven by onboarding friction, not content quality", to_text="Retention", relation="refines"),
        ],
    ),
    (
        "s_seed_p2",
        [
            ExtractedNode(type="claim", text="Streak mechanics increase daily active use but crowd out deep study sessions"),
            ExtractedNode(type="question", text="Should the product optimize for session frequency or session depth?"),
        ],
        [
            ExtractedEdge(from_text="Streak mechanics increase daily active use but crowd out deep study sessions", to_text="Should the product optimize for session frequency or session depth?", relation="questions"),
        ],
    ),
]

# One literature node so conversation and literature coexist pre-demo.
INGESTED = ExtractedNode(
    type="claim",
    text="Bloom's 2-sigma finding showed one-on-one tutoring outperforms conventional classroom instruction by two standard deviations",
    provenance="Bloom (1984), The 2 Sigma Problem — Results",
)

LEARNER_MODEL = {
    "reasoning_style": "Systems thinker — builds arguments from mechanism claims, comfortable with abstraction, tends to generalize from single studies",
    "blind_spots": [
        "Overgeneralizes from single studies to broad claims",
        "Rarely states the boundary conditions of a claim",
    ],
    "effective_question_types": ["boundary-probing", "counterexample-seeking"],
    "scaffolding_level": "medium",
    "session_count": 5,
    "evolved_at": "",
}


async def wipe(project_id: str) -> None:
    try:
        await repo.delete_project(project_id)
        print(f"  wiped {project_id}")
    except Exception as exc:
        print(f"  wipe {project_id}: {exc}")


async def seed_project(
    project_id: str,
    title: str,
    domain: str,
    sessions: list[tuple[str, list[ExtractedNode], list[ExtractedEdge]]],
    *,
    ingested: bool = False,
) -> None:
    await repo.ensure_project(project_id, title=title, domain=domain)
    for session_id, nodes, edges in sessions:
        snapshot = await repo.load_graph(project_id)
        applied = await repo.apply_diff(
            project_id, session_id, GraphDiff(nodes=nodes, edges=edges),
            snapshot, source="user", agent="seed",
        )
        print(f"  {project_id}/{session_id}: {applied.summary()}")
    if ingested:
        snapshot = await repo.load_graph(project_id)
        applied = await repo.apply_diff(
            project_id, "s_seed_ingest", GraphDiff(nodes=[INGESTED]),
            snapshot, source="ingestion", agent="ingestion",
        )
        print(f"  {project_id}/ingested: {applied.summary()}")

    # Embed everything so echoes + contradiction detection work pre-demo.
    snapshot = await repo.load_graph(project_id)
    vectors = await embed_many({n.id: n.text for n in snapshot.nodes.values()})
    await repo.set_node_embeddings(project_id, vectors)
    print(f"  {project_id}: embedded {len(vectors)} nodes")

    # Seeded claims are prior, already-processed sessions — mark verified so
    # the pending count reads clean instead of looking like a stuck queue.
    for n in snapshot.nodes.values():
        if n.type == "claim":
            await repo.set_node_status(project_id, n.id, "verified")


async def write_echo() -> None:
    """Write the cross-project connects_to edge for the engagement pair."""
    research_snap = await repo.load_graph(RESEARCH)
    product_snap = await repo.load_graph(PRODUCT)
    r = next((n for n in research_snap.nodes.values() if n.text == ECHO_RESEARCH), None)
    p = next((n for n in product_snap.nodes.values() if n.text == ECHO_PRODUCT), None)
    if not r or not p:
        print("  echo pair missing — skipped")
        return
    rv = await repo.load_node_embedding(RESEARCH, r.id)
    pv = await repo.load_node_embedding(PRODUCT, p.id)
    score = 0.0
    if rv and pv:
        from app.services.embeddings import cosine
        score = cosine(rv, pv)
    from app.schemas import EdgeOut
    edge = EdgeOut(
        id=repo.edge_id(p.id, r.id, "connects_to", RESEARCH),
        from_id=p.id, to_id=r.id, relation="connects_to",
        weight=round(score, 4), created_by_agent="echo",
        remote_project_id=RESEARCH, remote_project_title="AI in Education",
        remote_text=r.text,
    )
    written = await repo.write_echo_edges(PRODUCT, [edge])
    print(f"  echo edge: {ECHO_PRODUCT[:50]}… ↔ {ECHO_RESEARCH[:40]}… (cosine {score:.3f}) written={bool(written)}")


async def main() -> None:
    print("==> hiding test projects")
    for pid in HIDE:
        await repo.set_project_hidden(pid, True)
        print(f"  hidden {pid}")

    print("==> reseeding demo projects")
    await wipe(RESEARCH)
    await wipe(PRODUCT)
    await seed_project(RESEARCH, "AI in Education", "learning science / policy",
                       RESEARCH_SESSIONS, ingested=True)
    await seed_project(PRODUCT, "EdTech Product Strategy", "product / retention",
                       PRODUCT_SESSIONS)

    print("==> cross-project echo")
    await write_echo()

    print("==> learner model")
    from app.graph.repo import _now
    LEARNER_MODEL["evolved_at"] = _now()
    await repo.save_learner_model(config.DEMO_UID, dict(LEARNER_MODEL))
    print(f"  learner_model: scaffolding={LEARNER_MODEL['scaffolding_level']}, "
          f"{len(LEARNER_MODEL['blind_spots'])} blind spots")

    # A freshly seeded project has never been visited, so the briefing must be
    # armed. Without this a re-seed inherits the watermark from the last demo
    # and the arrival state stays silent.
    print("==> arming the briefing")
    await repo.db().collection("users").document(config.DEMO_UID).set(
        {"last_seen_at": {}}, merge=True
    )
    await repo.db().collection("users").document(config.DEMO_UID).update(
        {"last_seen_at": {}}
    )
    print("  last_seen_at cleared")

    print("done.")


if __name__ == "__main__":
    asyncio.run(main())
