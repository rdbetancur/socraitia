"""Turn orchestration.

The important decision in this file is that the Socratic and Cartographer agents
run CONCURRENTLY, not in sequence. Measured against Vertex, the Socratic call
takes ~4.3s to first token and the Cartographer ~8.5s; run one after the other a
turn costs ~13s, which is unusable on camera. They can overlap because the
Cartographer does not need the question the Socratic agent is about to ask — it
maps the user's message against the partner's PREVIOUS question, which is
already known.

Quick notes skip the Socratic agent entirely. They still hit the Cartographer
and the embedder, which is what lets a fragment participate in cross-project
echo detection without pretending it was a dialogue turn.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from app import config
from app.agents import cartographer, socratic
from app.context import builder
from app.graph import repo
from app.logging_setup import agent_log
from app.schemas import AppliedDiff
from app.services import bus, echoes, embeddings, model as modeler_svc


def new_session_id() -> str:
    return f"s_{uuid.uuid4().hex[:10]}"


def _event(kind: str, **payload) -> dict:
    return {"type": kind, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}


def _agent_event(agent: str, message: str, *, level: int = logging.INFO) -> dict:
    return _event("agent", agent=agent, line=agent_log(agent, message, level=level))


def _node_payload(n) -> dict:
    return n.model_dump()


def _filter_layout_edges(edges) -> list[dict]:
    """connects_to targets live in another project — do not hand them to the force graph."""
    return [e.to_api() for e in edges if e.relation != "connects_to"]


async def _embed_and_echo(project_id: str, applied: AppliedDiff) -> AsyncGenerator[dict, None]:
    if not (config.ENABLE_EMBEDDINGS and applied.new_nodes):
        return
    vectors = await embeddings.embed_many({n.id: n.text for n in applied.new_nodes})
    if not vectors:
        return
    await repo.set_node_embeddings(project_id, vectors)
    yield _agent_event(
        "EMBED",
        f"{len(vectors)} node(s) \u2192 {config.MODEL_EMBEDDING} "
        f"@{config.EMBEDDING_DIM}d (ready for cross-project search)",
    )
    found = await echoes.link_new_nodes(project_id, applied.new_nodes, vectors)
    if found:
        yield _agent_event(
            "ECHO",
            f"{len(found)} cross-project connection(s) above "
            f"{config.CROSS_PROJECT_MIN_COSINE:.2f}",
        )
        yield _event(
            "echoes",
            echoes=[e.model_dump() for e in found],
            nodes=[_node_payload(n) for n in applied.new_nodes if n.echoes],
        )


async def run(
    project_id: str,
    session_id: str,
    message: str,
    *,
    mode: str = "dialogue",
    focus_node_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    started = time.time()
    ctx = await builder.build(project_id, session_id, focus_node_id)
    n_nodes, n_edges = len(ctx.snapshot.nodes), len(ctx.snapshot.edges)
    learner_bit = ""
    if ctx.learner_model.get("scaffolding_level"):
        learner_bit = f", learner scaffolding={ctx.learner_model['scaffolding_level']}"
    yield _agent_event(
        "CONTEXT",
        f"{'note' if mode == 'note' else 'exchange'}#{ctx.exchange_number} \u2190 "
        f"graph {n_nodes} nodes/{n_edges} edges, "
        f"{len(ctx.tensions)} tension(s), {len(ctx.echoes)} echo(s)"
        f"{learner_bit}",
    )

    if mode == "note":
        yield _agent_event("CARTOGRAPHER", "note \u2192 extracting (socratic skipped)")
        try:
            diff = await cartographer.extract(message, ctx, mode="note")
        except Exception as exc:  # noqa: BLE001
            yield _agent_event("CARTOGRAPHER", f"FAILED: {type(exc).__name__}: {exc}", level=logging.ERROR)
            diff = None
        question = ""
    else:
        carto_task = asyncio.create_task(cartographer.extract(message, ctx))
        yield _agent_event("CARTOGRAPHER", f"exchange#{ctx.exchange_number} \u2192 extracting (async)")
        for line in socratic.adaptation_lines(ctx):
            yield _agent_event("SOCRATIC", line)
        yield _agent_event("SOCRATIC", f"exchange#{ctx.exchange_number} \u2192 composing question")

        question_parts: list[str] = []
        try:
            async for delta in socratic.ask(message, ctx):
                question_parts.append(delta)
                yield _event("token", text=delta)
        except Exception as exc:  # noqa: BLE001
            carto_task.cancel()
            yield _agent_event("SOCRATIC", f"FAILED: {type(exc).__name__}: {exc}", level=logging.ERROR)
            yield _event("error", message="The Socratic agent could not respond. Try again.")
            return

        question = "".join(question_parts).strip()
        yield _agent_event(
            "SOCRATIC",
            f"exchange#{ctx.exchange_number} \u2192 question delivered ({len(question)} chars)",
        )
        try:
            diff = await carto_task
        except Exception as exc:  # noqa: BLE001
            yield _agent_event("CARTOGRAPHER", f"FAILED: {type(exc).__name__}: {exc}", level=logging.ERROR)
            diff = None

    applied = None
    if diff is not None:
        source = "note" if mode == "note" else "user"
        applied = await repo.apply_diff(
            project_id, session_id, diff, ctx.snapshot, source=source
        )
        yield _agent_event(
            "CARTOGRAPHER",
            f"{'note' if mode == 'note' else f'exchange#{ctx.exchange_number}'} \u2192 {applied.summary()}",
        )
        layout_edges = _filter_layout_edges(applied.new_edges)
        if applied.new_nodes or layout_edges:
            yield _event(
                "graph_diff",
                nodes=[_node_payload(n) for n in applied.new_nodes],
                edges=layout_edges,
            )
        async for event in _embed_and_echo(project_id, applied):
            yield event
        if config.ENABLE_VERIFIER:
            for node in applied.new_nodes:
                if node.type != "claim":
                    continue
                await asyncio.to_thread(
                    bus.publish_claim,
                    project_id=project_id,
                    node_id=node.id,
                    text=node.text,
                    user_id=config.DEMO_UID,
                )
                yield _agent_event(
                    "VERIFIER:async",
                    f"{node.id} \u2192 queued (verification pending)",
                )

    await repo.append_exchange(
        project_id,
        session_id,
        user_text=message,
        partner_text=question,
        graph_diff=applied or AppliedDiff(),
        kind=mode,
    )

    if mode == "dialogue" and ctx.exchange_number % config.MODELER_EVERY_N == 0:
        yield _agent_event(
            "MODELER",
            f"checkpoint after {ctx.exchange_number} exchanges \u2192 evolving learner model",
        )
        try:
            result = await modeler_svc.checkpoint(
                project_id, session_id, reason=f"exchange#{ctx.exchange_number}"
            )
            if result.get("line"):
                yield _agent_event("MODELER", result["change"])
            if result.get("learner_model"):
                yield _event("learner", learner_model=result["learner_model"])
        except Exception as exc:  # noqa: BLE001 — modeler must never fail the turn
            yield _agent_event(
                "MODELER",
                f"FAILED: {type(exc).__name__}: {exc}",
                level=logging.ERROR,
            )

    yield _event(
        "done",
        session_id=session_id,
        exchange=ctx.exchange_number,
        question=question,
        mode=mode,
        elapsed_ms=int((time.time() - started) * 1000),
    )
