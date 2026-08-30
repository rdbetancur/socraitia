"""Hierarchical graph summarization for the context window.

The Socratic agent must reason about a graph that will outgrow any prompt. So it
never sees the graph — it sees a summary built here: the top-k nodes by degree
centrality, grouped by type, with each node's typed relations inlined. Degree
centrality is the right cheap proxy at this scale because a node that many
arguments hang off is exactly the node a thinking partner should keep in view.
"""

from __future__ import annotations

from app.graph.repo import GraphSnapshot

_TYPE_ORDER = ["claim", "question", "gap", "concept", "evidence", "note"]
_ARROW = {
    "supports": "supports",
    "contradicts": "CONTRADICTS",
    "refines": "refines",
    "questions": "questions",
    "answers": "answers",
    "connects_to": "CONNECTS TO",
}


def summarize(snapshot: GraphSnapshot, top_k: int) -> str:
    if not snapshot.nodes:
        return "(the graph is empty; this is the first exchange of the project)"

    degree = snapshot.degree()
    ranked = sorted(
        snapshot.nodes.values(),
        key=lambda n: (-degree.get(n.id, 0), n.created_at),
    )[:top_k]
    kept = {n.id for n in ranked}

    outgoing: dict[str, list[str]] = {}
    for e in snapshot.edges:
        if e.from_id not in kept:
            continue
        if e.relation != "connects_to" and e.to_id not in snapshot.nodes:
            continue
        if e.relation == "connects_to":
            target = e.remote_text or e.to_id
            label = f'{_ARROW[e.relation]} [{e.remote_project_title}] \u2192 "{target}"'
        else:
            target = snapshot.nodes[e.to_id].text
            label = f'{_ARROW[e.relation]} \u2192 "{target}"'
        outgoing.setdefault(e.from_id, []).append(label)

    lines: list[str] = []
    for node_type in _TYPE_ORDER:
        group = [n for n in ranked if n.type == node_type]
        if not group:
            continue
        lines.append(f"{node_type.upper()}S:")
        for n in group:
            marker = " [unverified]" if n.status == "verification_pending" else ""
            lines.append(f"  - ({n.id}) \"{n.text}\"{marker}")
            for rel in outgoing.get(n.id, [])[:4]:
                lines.append(f"      {rel}")

    hidden = len(snapshot.nodes) - len(ranked)
    if hidden > 0:
        lines.append(f"({hidden} lower-centrality nodes omitted from this view)")
    return "\n".join(lines)


def tension_pairs(snapshot: GraphSnapshot) -> list[tuple[str, str]]:
    """Contradiction edges, as (text, text). The Socratic agent surfaces these."""
    out: list[tuple[str, str]] = []
    for e in snapshot.edges:
        if e.relation != "contradicts":
            continue
        a, b = snapshot.nodes.get(e.from_id), snapshot.nodes.get(e.to_id)
        if a and b:
            out.append((a.text, b.text))
    return out


def echo_pairs(snapshot: GraphSnapshot) -> list[tuple[str, str, str]]:
    """(local text, remote project title, remote text) for Socratic surfacing."""
    out: list[tuple[str, str, str]] = []
    for e in snapshot.edges:
        if e.relation != "connects_to":
            continue
        a = snapshot.nodes.get(e.from_id)
        if a:
            out.append((a.text, e.remote_project_title or e.remote_project_id, e.remote_text))
    return out
