"""Cross-project connection finding.

The Verifier (Phase 3) will own contradiction-against-evidence. This module is
the cheaper, already-justified half of that idea: widen the embedding query
from one project to every project the user owns, and write `connects_to` edges
when the match is strong enough to be a pattern rather than a coincidence.

In-memory cosine over the owner's full node set is the same trade-off already
documented for intra-project retrieval. It is correct at hundreds of nodes.
It is not correct at tens of thousands — that is a Vector Search migration,
not a rewrite of this file.
"""

from __future__ import annotations

from app import config
from app.graph import repo
from app.logging_setup import agent_log
from app.schemas import EchoOut, EdgeOut, NodeOut
from app.services.embeddings import cosine


async def link_new_nodes(
    project_id: str,
    new_nodes: list[NodeOut],
    vectors: dict[str, list[float]],
) -> list[EchoOut]:
    """Compare newly embedded nodes against the rest of the owner's corpus."""
    if not new_nodes or not vectors or not config.ENABLE_EMBEDDINGS:
        return []

    corpus = await repo.load_owner_embedded_nodes(config.DEMO_UID)
    if not corpus:
        return []

    candidates: list[EdgeOut] = []
    echoes: list[EchoOut] = []

    for node in new_nodes:
        vec = vectors.get(node.id)
        if not vec:
            continue
        scored: list[tuple[float, dict]] = []
        for remote in corpus:
            if remote["project_id"] == project_id:
                continue
            # Same text hashes to the same id across projects — that is a
            # genuine echo, not a self-match, because the project differs.
            score = cosine(vec, remote["embedding"])
            if score < config.CROSS_PROJECT_MIN_COSINE:
                continue
            scored.append((score, remote))
        scored.sort(key=lambda pair: -pair[0])
        for score, remote in scored[: config.CROSS_PROJECT_MAX_PER_NODE]:
            edge = EdgeOut(
                id=repo.edge_id(
                    node.id, remote["node_id"], "connects_to", remote["project_id"]
                ),
                from_id=node.id,
                to_id=remote["node_id"],
                relation="connects_to",
                weight=round(score, 4),
                created_by_agent="echo",
                remote_project_id=remote["project_id"],
                remote_project_title=remote["project_title"],
                remote_text=remote["text"],
            )
            candidates.append(edge)
            echoes.append(
                EchoOut(
                    node_id=remote["node_id"],
                    text=remote["text"],
                    project_id=remote["project_id"],
                    project_title=remote["project_title"],
                    similarity=round(score, 4),
                )
            )
            agent_log(
                "ECHO",
                f"{node.id} \u2192 connects_to {remote['node_id']} in "
                f"[{remote['project_title']}] ({score:.2f})",
            )

    written = await repo.write_echo_edges(project_id, candidates)
    if not written:
        return []

    echo_by_edge = {edge.id: echo for edge, echo in zip(candidates, echoes)}
    kept = [echo_by_edge[edge.id] for edge in written if edge.id in echo_by_edge]
    by_from: dict[str, list[EchoOut]] = {}
    for edge in written:
        echo = echo_by_edge.get(edge.id)
        if echo:
            by_from.setdefault(edge.from_id, []).append(echo)
    for node in new_nodes:
        node.echoes.extend(by_from.get(node.id, []))
    return kept
