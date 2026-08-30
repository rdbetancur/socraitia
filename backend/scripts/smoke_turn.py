"""End-to-end smoke test: real turns against Vertex AI and Firestore.

Run from backend/:  .venv/bin/python scripts/smoke_turn.py

Three turns, each asserting a different property of the core loop:

  1. the Cartographer creates structure from a fresh claim
  2. a contradicting statement accumulates onto the SAME graph rather than
     resetting it, which is what cross-session memory rests on
  3. re-applying an identical diff is a no-op, and no two nodes in the graph
     share normalized text — the deterministic-id merge property, which is also
     the Pub/Sub idempotency guarantee the async agents rely on in Phase 3

Property 3 is checked by replaying a diff directly rather than by replaying a
user message, because an LLM given a larger graph will legitimately extract
different structure the second time. Replaying the message tests the model;
replaying the diff tests the invariant.

Uses a throwaway project id and deletes it afterwards, so it is safe to run
against the live database as often as you like.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.graph import repo  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.schemas import ExtractedEdge, ExtractedNode, GraphDiff  # noqa: E402
from app.services import turn  # noqa: E402

CLAIM = (
    "I think AI tutors will replace human teachers within five years, because "
    "they scale infinitely and never get tired."
)
COUNTER = (
    "Actually the bottleneck isn't tutoring quality at all, it's that schools "
    "are social institutions before they are instructional ones."
)


async def play(project_id: str, session_id: str, message: str, label: str) -> dict:
    print(f"\n>>> {label}: {message}\n" + "-" * 78)
    result = {"question": "", "nodes": 0, "edges": 0}
    async for event in turn.run(project_id, session_id, message):
        kind = event["type"]
        if kind == "token":
            sys.stdout.write(event["text"])
            sys.stdout.flush()
        elif kind == "graph_diff":
            result["nodes"] += len(event["nodes"])
            result["edges"] += len(event["edges"])
            print(f"\n  GRAPH DIFF: +{len(event['nodes'])} nodes, +{len(event['edges'])} edges")
            for n in event["nodes"]:
                print(f"    + [{n['type']:<8}] {n['id']}  {n['text'][:66]}")
            for e in event["edges"]:
                print(f"    + {e['source']} --{e['relation']}--> {e['target']}")
        elif kind == "done":
            result["question"] = event["question"]
            print(f"\n  DONE in {event['elapsed_ms']}ms")
        elif kind == "error":
            print(f"\n  ERROR: {event['message']}")
    return result


async def main() -> None:
    config.configure_genai_env()
    setup_logging()

    project_id = f"smoke-{uuid.uuid4().hex[:8]}"
    session_id = turn.new_session_id()
    await repo.ensure_project(project_id, title="Smoke Test", domain="testing")
    print(f"\nproject={project_id} session={session_id}\n" + "=" * 78)

    failures: list[str] = []
    try:
        first = await play(project_id, session_id, CLAIM, "TURN 1 (create)")
        if not first["question"]:
            failures.append("turn 1: socratic produced no question")
        if first["nodes"] == 0:
            failures.append("turn 1: cartographer produced no nodes")

        second = await play(project_id, session_id, COUNTER, "TURN 2 (accumulate)")
        if not second["question"]:
            failures.append("turn 2: socratic produced no question")

        after_two = await repo.load_graph(project_id)
        if len(after_two.nodes) <= first["nodes"]:
            failures.append("turn 2: graph did not grow across turns")

        # --- property 3: replaying a diff must be a no-op --------------------
        print("\n>>> IDEMPOTENCY CHECK (replay a diff already applied)\n" + "-" * 78)
        snapshot = await repo.load_graph(project_id)
        existing = list(snapshot.nodes.values())[:3]
        replay = GraphDiff(
            nodes=[ExtractedNode(type=n.type, text=n.text) for n in existing],
            edges=[
                ExtractedEdge(
                    from_text=snapshot.nodes[e.from_id].text,
                    to_text=snapshot.nodes[e.to_id].text,
                    relation=e.relation,
                )
                for e in snapshot.edges[:3]
                if e.from_id in snapshot.nodes and e.to_id in snapshot.nodes
            ],
        )
        applied = await repo.apply_diff(project_id, session_id, replay, snapshot)
        print(
            f"  replayed {len(replay.nodes)} nodes / {len(replay.edges)} edges "
            f"-> created {len(applied.new_nodes)} nodes, {len(applied.new_edges)} edges, "
            f"merged {len(applied.merged_node_ids)}"
        )
        if applied.new_nodes or applied.new_edges:
            failures.append(
                f"replaying an applied diff created {len(applied.new_nodes)} nodes / "
                f"{len(applied.new_edges)} edges; ids are not deterministic"
            )
        if len(applied.merged_node_ids) != len(replay.nodes):
            failures.append("replayed nodes were not all recognized as merges")

        snapshot = await repo.load_graph(project_id)
        seen: dict[str, str] = {}
        for n in snapshot.nodes.values():
            key = repo.normalize(n.text)
            if key in seen:
                failures.append(f"duplicate node text: {n.id} and {seen[key]}")
            seen[key] = n.id

        degree = snapshot.degree()
        print("\n" + "=" * 78)
        print(f"FINAL GRAPH: {len(snapshot.nodes)} nodes, {len(snapshot.edges)} edges")
        for n in sorted(snapshot.nodes.values(), key=lambda x: -degree.get(x.id, 0)):
            print(f"  [{n.type:<8}] deg={degree.get(n.id, 0)}  {n.id}  {n.text[:58]}")
        for e in snapshot.edges:
            flag = "  <-- TENSION" if e.relation == "contradicts" else ""
            print(f"  {e.from_id} --{e.relation}--> {e.to_id}{flag}")

        if not any(e.relation == "contradicts" for e in snapshot.edges):
            print("\n  NOTE: no contradiction edge this run (model-dependent, not a failure)")
    finally:
        await repo.delete_project(project_id)
        print(f"\ncleaned up {project_id}")

    print("\n" + "=" * 78)
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        sys.exit(1)
    print("PASS  create / accumulate / idempotent-merge all verified")


asyncio.run(main())
