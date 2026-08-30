"""Context assembly — the context-window strategy, in one place.

Socraitia never replays full history. Every turn is built from four bounded
pieces, and the bound on each is what keeps the prompt flat as a project grows
across sessions:

  1. a hierarchical graph summary, top-k by degree centrality
  2. the last N exchanges verbatim
  3. the learner model (Phase 4) as explicit directives
  4. open tensions the Verifier has recorded (Phase 3)

The graph is what carries long-term memory here, not the transcript. That is the
whole point: the artifact remembers, so the conversation does not have to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import config
from app.graph import centrality, repo
from app.graph.repo import GraphSnapshot


@dataclass
class TurnContext:
    snapshot: GraphSnapshot
    graph_summary: str
    recent_exchanges: str
    learner_directives: str
    learner_model: dict = field(default_factory=dict)
    last_feedback: dict | None = None
    tensions: list[tuple[str, str]] = field(default_factory=list)
    echoes: list[tuple[str, str, str]] = field(default_factory=list)
    last_partner_question: str = ""
    exchange_number: int = 1
    focus: dict | None = None

    def focus_block(self) -> str:
        """The node the user is interrogating, with its local neighborhood.

        Truncation order is deliberate: tensions first (most valuable), then
        evidence, then the rest — a high-degree node must not blow the budget.
        """
        f = self.focus
        if not f:
            return "(no focused node — open dialogue)"
        lines = [
            f'FOCUSED {f["type"].upper()} (source: {f["source"]}): "{f["text"]}"',
        ]
        if f.get("provenance"):
            lines.append(f'provenance: {f["provenance"]}')
        for rel in f.get("relations", []):
            lines.append(f'- {rel["relation"]}: "{rel["text"]}"')
        for echo in f.get("echoes", []):
            lines.append(f'- connects_to [{echo["project"]}]: "{echo["text"]}"')
        return "\n".join(lines)

    def tension_block(self) -> str:
        if not self.tensions:
            return "(no unresolved tensions recorded)"
        return "\n".join(
            f'- "{a}"\n  CONTRADICTS "{b}"' for a, b in self.tensions[:3]
        )

    def echo_block(self) -> str:
        if not self.echoes:
            return "(no cross-project echoes recorded)"
        return "\n".join(
            f'- "{local}"\n  CONNECTS TO [{project}]: "{remote}"'
            for local, project, remote in self.echoes[:3]
        )


def _format_learner_model(model: dict, last_feedback: dict | None) -> str:
    if not model and not last_feedback:
        return (
            "(no learner model yet \u2014 this is an early session. Calibrate "
            "scaffolding to medium and observe how the user reasons.)"
        )
    parts = []
    if style := (model or {}).get("reasoning_style"):
        parts.append(f"reasoning_style: {style}")
    if blind := (model or {}).get("blind_spots"):
        parts.append(f"blind_spots: {', '.join(blind)}")
        parts.append(
            f"Stay alert to the first blind spot. If the user's last move "
            f"shows it, name it in the question."
        )
    if eff := (model or {}).get("effective_question_types"):
        parts.append(f"question types that work on this user: {', '.join(eff)}")
    lvl = (model or {}).get("scaffolding_level")
    if lvl == "low":
        parts.append(
            "scaffolding_level: low — ask a blunt, concrete question. "
            "No preamble. Name the weak point in their words."
        )
    elif lvl == "high":
        parts.append(
            "scaffolding_level: high — restate their claim in simpler terms, "
            "then ask a more abstract question that opens a new frame."
        )
    elif lvl:
        parts.append("scaffolding_level: medium — one short setup clause is allowed.")
    if last_feedback:
        verdict = last_feedback.get("verdict")
        qtype = last_feedback.get("question_type", "elaboration")
        if verdict == "missed":
            parts.append(
                f"LAST QUESTION was marked MISSED (type={qtype}). "
                f"Do not repeat that angle. Switch type."
            )
        elif verdict == "helped":
            parts.append(
                f"LAST QUESTION was marked HELPED (type={qtype}). "
                f"That type is working — stay near it."
            )
    return "\n".join(f"- {p}" for p in parts) or "(learner model empty)"


def _format_exchanges(transcript: list[dict]) -> str:
    if not transcript:
        return "(no prior exchanges in this session)"
    lines = []
    for entry in transcript:
        if entry.get("kind") == "note":
            lines.append(f"NOTE: {entry.get('user', '')}")
            continue
        lines.append(f"USER: {entry.get('user', '')}")
        partner = entry.get("partner", "")
        if partner:
            lines.append(f"YOU: {partner}")
    return "\n".join(lines)


async def build(
    project_id: str, session_id: str, focus_node_id: str | None = None
) -> TurnContext:
    snapshot = await repo.load_graph(project_id)
    transcript = await repo.load_transcript(
        project_id, session_id, config.CONTEXT_RECENT_EXCHANGES
    )
    learner_model = await repo.load_learner_model(config.DEMO_UID)
    last_feedback = await repo.load_last_feedback(project_id, session_id)

    focus: dict | None = None
    if focus_node_id and focus_node_id in snapshot.nodes:
        node = snapshot.nodes[focus_node_id]
        relations: list[dict] = []
        for e in snapshot.edges:
            if e.relation == "connects_to":
                continue
            other = None
            if e.from_id == node.id:
                other = snapshot.nodes.get(e.to_id)
            elif e.to_id == node.id:
                other = snapshot.nodes.get(e.from_id)
            if other:
                relations.append({"relation": e.relation, "text": other.text})
        rank = {"contradicts": 0, "supports": 1, "refines": 2}
        relations.sort(key=lambda r: rank.get(r["relation"], 3))
        focus = {
            "text": node.text,
            "type": node.type,
            "source": node.source,
            "provenance": node.provenance,
            "relations": relations[:6],
            "echoes": [
                {"project": ec.project_title, "text": ec.text}
                for ec in node.echoes[:2]
            ],
        }

    return TurnContext(
        snapshot=snapshot,
        graph_summary=centrality.summarize(snapshot, config.CONTEXT_GRAPH_TOP_K),
        recent_exchanges=_format_exchanges(transcript),
        learner_directives=_format_learner_model(learner_model, last_feedback),
        learner_model=learner_model,
        last_feedback=last_feedback,
        tensions=centrality.tension_pairs(snapshot),
        echoes=centrality.echo_pairs(snapshot),
        last_partner_question=next(
            (
                e.get("partner", "")
                for e in reversed(transcript)
                if e.get("kind") != "note" and e.get("partner")
            ),
            "",
        ),
        exchange_number=len(transcript) + 1,
        focus=focus,
    )
