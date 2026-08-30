"""Run one Verifier job for one claim.

Called from the Pub/Sub push handler. Never raises into the HTTP layer in a
way that would nack forever without a log: failures leave the claim in
`verification_pending` and the graph stays usable.
"""

from __future__ import annotations

import logging

from app import config
from app.agents import verifier
from app.agents.runtime import AgentCallError
from app.graph import repo
from app.logging_setup import agent_log
from app.schemas import ExtractedEdge, GraphDiff
from app.services.embeddings import cosine


async def verify_claim(project_id: str, node_id: str, text: str, user_id: str) -> dict:  # noqa: ARG001
    snapshot = await repo.load_graph(project_id)
    claim = snapshot.nodes.get(node_id)
    if claim is None:
        agent_log("VERIFIER:async", f"{node_id} gone \u2014 drop", level=logging.WARNING)
        return {"status": "dropped"}

    if await repo.is_claim_verified(project_id, node_id):
        agent_log("VERIFIER:async", f"{node_id} already verified \u2014 idempotent skip")
        return {"status": "duplicate"}

    # A redelivered message that already wrote evidence must not write it again.
    # Polarity + status still run if verified_at was never stamped (crash mid-job).
    skip_grounding = repo.already_verified(snapshot, node_id)
    try:
        findings = (
            verifier.Findings()
            if skip_grounding
            else await verifier.gather_evidence(text)
        )
    except AgentCallError as exc:
        agent_log(
            "VERIFIER:async",
            f"{node_id} grounding failed ({exc}) \u2014 left pending",
            level=logging.WARNING,
        )
        return {"status": "failed"}
    evidence_n = 0
    if findings.findings:
        applied = await repo.apply_diff(
            project_id,
            claim.session_id,
            verifier.findings_to_diff(claim.text, findings),
            snapshot,
            source="verifier",
            agent="verifier",
        )
        evidence_n = len(applied.new_nodes)
        snapshot = await repo.load_graph(project_id)

    tensions = 0
    vec = await repo.load_node_embedding(project_id, node_id)
    if vec:
        others = [
            n
            for n in snapshot.nodes.values()
            if n.id != node_id and n.type == "claim"
        ]
        scored: list[tuple[float, str, str]] = []
        for other in others:
            other_vec = await repo.load_node_embedding(project_id, other.id)
            if not other_vec:
                continue
            score = cosine(vec, other_vec)
            if score >= config.INTRA_CLAIM_MIN_COSINE:
                scored.append((score, other.id, other.text))
        scored.sort(key=lambda row: -row[0])
        snapshot = await repo.load_graph(project_id)
        for score, _oid, other_text in scored[:2]:
            relation = await verifier.polarity(claim.text, other_text)
            if relation != "contradicts":
                continue
            diff = GraphDiff(
                edges=[
                    ExtractedEdge(
                        from_text=claim.text,
                        to_text=other_text,
                        relation="contradicts",
                    )
                ]
            )
            applied = await repo.apply_diff(
                project_id,
                claim.session_id,
                diff,
                snapshot,
                source="verifier",
                agent="verifier",
            )
            tensions += len(applied.new_edges)
            snapshot = await repo.load_graph(project_id)

    await repo.set_node_status(project_id, node_id, "verified")
    vs = f"{node_id} \u2192 {evidence_n} sources"
    if tensions:
        vs += f", {tensions} TENSION"
    else:
        vs += ", no intra-project tension"
    line = agent_log("VERIFIER:async", vs)
    await repo.append_feed(project_id, "VERIFIER:async", line)
    return {"status": "ok", "evidence": evidence_n, "tensions": tensions}
