"""What the instrument found while you were away.

Pure derivation over state that already exists: node `created_at` /
`verified_at`, edge `created_at`, and `created_by_agent`. The only thing
persisted for this feature is a single `last_seen_at` watermark per project on
the user document — the briefing itself is never stored, so it can never go
stale or disagree with the graph.

Every item carries the full text of both sides. A briefing that says
"2 tensions" without showing them is a statistic; showing them is the product.
"""

from __future__ import annotations

from app.graph.repo import GraphSnapshot

# Echo edges are written without a timestamp (see services/echoes.py), so their
# recency is inferred from the local node they hang off.
_MAX_PER_SECTION = 6


def _fresh(stamp: str, since: str) -> bool:
    """String compare is correct here: every timestamp is ISO-8601 UTC."""
    return bool(stamp) and (not since or stamp > since)


def build(snapshot: GraphSnapshot, since: str) -> dict:
    nodes = snapshot.nodes

    verified: list[dict] = []
    ingested: list[dict] = []
    for node in nodes.values():
        if node.type == "claim" and node.status == "verified" and _fresh(node.verified_at, since):
            evidence = [
                nodes[e.from_id].text
                for e in snapshot.edges
                if e.to_id == node.id
                and e.created_by_agent == "verifier"
                and e.from_id in nodes
            ]
            verified.append(
                {
                    "node_id": node.id,
                    "text": node.text,
                    "at": node.verified_at,
                    "evidence": evidence[:2],
                }
            )
        if node.source == "ingestion" and _fresh(node.created_at, since):
            ingested.append(
                {
                    "node_id": node.id,
                    "text": node.text,
                    "provenance": node.provenance,
                    "at": node.created_at,
                }
            )

    tensions: list[dict] = []
    echoes: list[dict] = []
    for edge in snapshot.edges:
        a, b = nodes.get(edge.from_id), nodes.get(edge.to_id)
        if edge.relation == "contradicts":
            if not a or not b or not _fresh(edge.created_at, since):
                continue
            tensions.append(
                {
                    "edge_id": edge.id,
                    "at": edge.created_at,
                    "by": edge.created_by_agent,
                    "a": {"node_id": a.id, "text": a.text, "source": a.source,
                          "provenance": a.provenance},
                    "b": {"node_id": b.id, "text": b.text, "source": b.source,
                          "provenance": b.provenance},
                }
            )
        elif edge.relation == "connects_to" and a:
            stamp = edge.created_at or a.created_at
            if not _fresh(stamp, since):
                continue
            echoes.append(
                {
                    "edge_id": edge.id,
                    "at": stamp,
                    "similarity": edge.weight,
                    "local": {"node_id": a.id, "text": a.text},
                    "remote": {
                        "text": edge.remote_text,
                        "project_id": edge.remote_project_id,
                        "project_title": edge.remote_project_title,
                    },
                }
            )

    for bucket in (verified, ingested, tensions, echoes):
        bucket.sort(key=lambda row: row.get("at") or "", reverse=True)

    evidence_n = sum(len(row["evidence"]) for row in verified)
    return {
        "since": since,
        "empty": not (verified or tensions or echoes or ingested),
        "counts": {
            "verified": len(verified),
            "evidence": evidence_n,
            "tensions": len(tensions),
            "echoes": len(echoes),
            "ingested": len(ingested),
        },
        "tensions": tensions[:_MAX_PER_SECTION],
        "echoes": echoes[:_MAX_PER_SECTION],
        "verified": verified[:_MAX_PER_SECTION],
        "ingested": ingested[:_MAX_PER_SECTION],
    }
