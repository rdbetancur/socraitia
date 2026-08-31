"""FastAPI surface.

One SSE endpoint carries everything a turn produces — response tokens, agent
activity lines, and graph diffs — on a single ordered stream. That keeps the
frontend's live graph and its agent feed inherently in sync, and SSE is
supported natively by Cloud Run, so what works locally works deployed with no
transport rewrite in Phase 2.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import config
from app.graph import repo
from app.logging_setup import agent_log, setup_logging
from app.agents import modeler
from app.schemas import FeedbackRequest, ProjectCreate, SessionEndRequest, TurnRequest
from app.services import briefing, bus, ingest
from app.services import model as modeler_svc
from app.services import turn, verify

config.configure_genai_env()
setup_logging()

@asynccontextmanager
async def lifespan(_: FastAPI):
    agent_log(
        "SYSTEM",
        f"socraitia up \u2192 project={config.PROJECT_ID} db={config.FIRESTORE_DATABASE} "
        f"socratic={config.MODEL_SOCRATIC}@{config.GEMINI_LOCATION}",
    )
    # Bounded and non-fatal: a slow or unreachable Firestore must not stop the
    # container from becoming ready, or Cloud Run's startup probe kills the
    # revision and the deploy fails for a reason that has nothing to do with
    # serving traffic. The project is also ensured lazily on first use.
    try:
        async with asyncio.timeout(10):
            await repo.ensure_project(
                config.DEMO_PROJECT_ID,
                title="AI in Education",
                domain="learning science / policy",
            )
    except Exception as exc:  # noqa: BLE001
        agent_log(
            "SYSTEM",
            f"demo project not ensured at startup ({type(exc).__name__}) \u2014 continuing",
            level=logging.WARNING,
        )
    yield


_CORS_STAR = config.CORS_ORIGINS == ["*"]
app = FastAPI(title="Socraitia", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _CORS_STAR else config.CORS_ORIGINS,
    allow_credentials=not _CORS_STAR,
    allow_methods=["*"],
    allow_headers=["*"],
)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Cloud Run's proxy buffers responses unless told not to, which would batch
    # the whole stream into one chunk and kill the live-graph effect.
    "X-Accel-Buffering": "no",
}


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "project": config.PROJECT_ID,
        "database": config.FIRESTORE_DATABASE,
        "models": {
            "socratic": f"{config.MODEL_SOCRATIC}@{config.GEMINI_LOCATION}",
            "cartographer": f"{config.MODEL_CARTOGRAPHER}@{config.GEMINI_LOCATION}",
            "embedding": f"{config.MODEL_EMBEDDING}@{config.GEMINI_LOCATION}",
        },
        "verified_on": config.VERIFIED_ON,
    }


def _graph_payload(snapshot) -> dict:
    degree = snapshot.degree()
    return {
        "nodes": [
            {**n.model_dump(), "degree": degree.get(n.id, 0)} for n in snapshot.nodes.values()
        ],
        "edges": [e.to_api() for e in snapshot.edges if e.relation != "connects_to"],
    }


@app.get("/api/bootstrap")
async def bootstrap(project_id: str | None = Query(default=None)) -> dict:
    """Everything the console needs on first paint, or after a project switch."""
    await repo.ensure_project(
        config.DEMO_PROJECT_ID,
        title="AI in Education",
        domain="learning science / policy",
    )
    projects = await repo.list_projects(config.DEMO_UID)
    known = {p["id"] for p in projects}
    if project_id and project_id in known:
        chosen = project_id
    elif config.DEMO_PROJECT_ID in known:
        chosen = config.DEMO_PROJECT_ID
    else:
        chosen = projects[0]["id"] if projects else config.DEMO_PROJECT_ID
    meta = await repo.get_project(chosen)
    if meta is None:
        raise HTTPException(status_code=404, detail="project not found")
    snapshot = await repo.load_graph(chosen)
    return {
        "project_id": chosen,
        "project_title": meta["title"],
        "project_domain": meta.get("domain", ""),
        "session_id": turn.new_session_id(),
        "uid": config.DEMO_UID,
        "projects": projects,
        "learner_model": await repo.load_learner_model(config.DEMO_UID),
        "models": {
            "socratic": config.MODEL_SOCRATIC,
            "cartographer": config.MODEL_CARTOGRAPHER,
            "location": config.GEMINI_LOCATION,
        },
        **_graph_payload(snapshot),
    }


@app.get("/api/briefing/{project_id}")
async def get_briefing(
    project_id: str, full: bool = Query(default=False)
) -> dict:
    """Derived on read from node/edge timestamps.

    Default: only what landed since last_seen_at (arrival + unread badge).
    `full=true`: the current instrument state, independent of the watermark —
    so the overlay can be reopened after dismiss without a reset script.
    """
    snapshot = await repo.load_graph(project_id)
    seen = await repo.load_last_seen(config.DEMO_UID, project_id)
    payload = briefing.build(snapshot, "" if full else seen)
    if full:
        unseen = briefing.build(snapshot, seen)
        payload["unseen"] = unseen["counts"]
        payload["unseen_empty"] = unseen["empty"]
    return payload


@app.post("/api/briefing/{project_id}/seen")
async def mark_briefing_seen(project_id: str) -> dict:
    return {"last_seen_at": await repo.mark_seen(config.DEMO_UID, project_id)}


@app.get("/api/projects")
async def list_projects() -> dict:
    return {"projects": await repo.list_projects(config.DEMO_UID)}


@app.post("/api/projects")
async def create_project(req: ProjectCreate) -> dict:
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    created = await repo.create_project(title, req.domain)
    agent_log("SYSTEM", f"project created {created['id']} \u2014 {created['title']}")
    return created


@app.get("/api/graph/{project_id}")
async def graph(project_id: str) -> dict:
    snapshot = await repo.load_graph(project_id)
    return {"project_id": project_id, **_graph_payload(snapshot)}


@app.get("/api/node/{project_id}/{node_id}")
async def node_dossier(project_id: str, node_id: str) -> dict:
    """Provenance for one node: where it came from and what argues with it."""
    snapshot = await repo.load_graph(project_id)
    node = snapshot.nodes.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")

    incoming, outgoing = [], []
    for e in snapshot.edges:
        if e.relation == "connects_to":
            continue
        if e.to_id == node_id and e.from_id in snapshot.nodes:
            incoming.append({"relation": e.relation, "node": snapshot.nodes[e.from_id].model_dump()})
        elif e.from_id == node_id and e.to_id in snapshot.nodes:
            outgoing.append({"relation": e.relation, "node": snapshot.nodes[e.to_id].model_dump()})

    return {
        "node": node.model_dump(),
        "incoming": incoming,
        "outgoing": outgoing,
        "echoes": [e.model_dump() for e in node.echoes],
    }


@app.post("/api/feedback")
async def post_feedback(req: FeedbackRequest) -> dict:
    """Tag a Socratic question. Updates the tally the next Modeler run obeys."""
    if req.exchange < 1:
        raise HTTPException(status_code=400, detail="exchange is required")
    qtype = modeler.classify_question(req.question)
    entry = {
        "exchange": req.exchange,
        "question": req.question,
        "verdict": req.verdict,
        "question_type": qtype,
        "at": repo._now(),
    }
    await repo.write_feedback(req.project_id, req.session_id, req.exchange, entry)
    await repo.increment_feedback_tally(config.DEMO_UID, qtype, req.verdict)
    line = agent_log(
        "MODELER",
        f"feedback {req.verdict} on exchange#{req.exchange} ({qtype})",
    )
    await repo.append_feed(req.project_id, "MODELER", line)
    return {"status": "ok", "entry": entry, "line": line}


@app.post("/api/session/end")
async def end_session(req: SessionEndRequest) -> dict:
    """Demo gesture: persist the learner model before a new session starts."""
    try:
        result = await modeler_svc.checkpoint(
            req.project_id, req.session_id, reason="session_end"
        )
    except Exception as exc:  # noqa: BLE001
        agent_log("MODELER", f"session end failed: {type(exc).__name__}: {exc}", level=logging.ERROR)
        result = {
            "status": "failed",
            "learner_model": await repo.load_learner_model(config.DEMO_UID),
        }
    return result


@app.post("/api/turn")
async def post_turn(req: TurnRequest) -> StreamingResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    session_id = req.session_id or turn.new_session_id()

    async def stream() -> AsyncGenerator[str, None]:
        try:
            async for event in turn.run(
                req.project_id, session_id, message, mode=req.mode,
                focus_node_id=req.focus_node_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001 - never leave the client hanging
            agent_log("SYSTEM", f"turn crashed: {type(exc).__name__}: {exc}", level=logging.ERROR)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/watch/{project_id}")
async def watch(project_id: str, after: str = "") -> StreamingResponse:
    """Long-lived SSE of verifier feed lines and graph mutations.

    Pub/Sub lands asynchronously, so the turn stream is already closed when
    evidence arrives. This watch is how the engine-room ticker stays live
    without a second websocket protocol.
    """

    async def stream() -> AsyncGenerator[str, None]:
        cursor = after
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()
        last_status: dict[str, str] = {}
        snapshot = await repo.load_graph(project_id)
        seen_nodes.update(snapshot.nodes)
        seen_edges.update(e.id for e in snapshot.edges)
        last_status = {n.id: n.status for n in snapshot.nodes.values()}
        try:
            while True:
                for entry in await repo.load_feed(project_id, cursor):
                    cursor = entry.get("at") or cursor
                    yield f"data: {json.dumps({'type': 'agent', 'at': entry.get('at', ''), 'agent': entry.get('agent', ''), 'line': entry.get('line', '')})}\n\n"
                snapshot = await repo.load_graph(project_id)
                fresh_nodes = [
                    n.model_dump()
                    for n in snapshot.nodes.values()
                    if n.id not in seen_nodes
                ]
                fresh_edges = [
                    e.to_api()
                    for e in snapshot.edges
                    if e.id not in seen_edges and e.relation != "connects_to"
                ]
                status_updates = [
                    n.model_dump()
                    for n in snapshot.nodes.values()
                    if last_status.get(n.id) != n.status
                ]
                last_status = {n.id: n.status for n in snapshot.nodes.values()}
                if fresh_nodes or fresh_edges:
                    seen_nodes.update(n["id"] for n in fresh_nodes)
                    seen_edges.update(e["id"] for e in fresh_edges)
                    yield f"data: {json.dumps({'type': 'graph_diff', 'at': '', 'nodes': fresh_nodes, 'edges': fresh_edges})}\n\n"
                if status_updates:
                    yield f"data: {json.dumps({'type': 'node_status', 'at': '', 'nodes': status_updates})}\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/ingest")
async def upload_documents(
    project_id: str = Query(...),
    files: list[UploadFile] = File(...),
) -> dict:
    """Accept one or more PDFs, store them in GCS, queue async ingestion."""
    from google.cloud import storage as gcs_storage
    import hashlib

    results = []
    client = gcs_storage.Client(project=config.PROJECT_ID)
    bucket = client.bucket(config.GCS_INGEST_BUCKET)
    for f in files:
        data = await f.read()
        if not data:
            continue
        doc_id = "d_" + hashlib.sha1(data).hexdigest()[:12]
        blob = bucket.blob(f"{config.DEMO_UID}/{project_id}/{doc_id}/{f.filename}")
        await asyncio.to_thread(blob.upload_from_string, data, content_type="application/pdf")
        gcs_uri = f"gs://{config.GCS_INGEST_BUCKET}/{blob.name}"
        await asyncio.to_thread(
            bus.publish_ingest,
            project_id=project_id,
            doc_id=doc_id,
            filename=f.filename or doc_id,
            gcs_uri=gcs_uri,
            user_id=config.DEMO_UID,
        )
        await repo.append_feed(
            project_id, "INGESTION", f"{f.filename} → uploaded, queued for extraction"
        )
        results.append({"doc_id": doc_id, "filename": f.filename, "status": "queued"})
    return {"results": results}


@app.post("/internal/pubsub/ingest")
async def pubsub_ingest(request: Request, token: str = "") -> dict:
    """Pub/Sub push target for document ingestion. Same service as the API."""
    if config.PUBSUB_PUSH_TOKEN and token != config.PUBSUB_PUSH_TOKEN:
        raise HTTPException(status_code=403, detail="bad push token")
    envelope = await request.json()
    raw = (envelope.get("message") or {}).get("data")
    if not raw:
        return {"status": "ignored"}
    import base64

    payload = json.loads(base64.b64decode(raw).decode("utf-8"))
    try:
        result = await ingest.ingest_document(
            payload["project_id"],
            payload["doc_id"],
            payload["filename"],
            payload["gcs_uri"],
            payload.get("user_id", config.DEMO_UID),
        )
    except Exception as exc:  # noqa: BLE001 — ack; a failed doc must not break the graph
        agent_log(
            "INGESTION",
            f"job crashed ({type(exc).__name__}: {exc})",
            level=logging.ERROR,
        )
        return {"status": "failed"}
    return result


@app.post("/internal/pubsub/claims")
async def pubsub_claims(request: Request, token: str = "") -> dict:
    """Pub/Sub push target. Same Cloud Run service as the API — one image,
    one IAM identity, one deploy. The push token is the only gate: the
    service is public because the frontend is.
    """
    if config.PUBSUB_PUSH_TOKEN and token != config.PUBSUB_PUSH_TOKEN:
        raise HTTPException(status_code=403, detail="bad push token")
    envelope = await request.json()
    message = envelope.get("message") or {}
    raw = message.get("data")
    if not raw:
        return {"status": "ignored"}
    import base64

    payload = json.loads(base64.b64decode(raw).decode("utf-8"))
    try:
        result = await verify.verify_claim(
            payload["project_id"],
            payload["node_id"],
            payload["text"],
            payload.get("user_id", config.DEMO_UID),
        )
    except Exception as exc:  # noqa: BLE001 — ack the push; leave the claim pending
        agent_log(
            "VERIFIER:async",
            f"job crashed ({type(exc).__name__}: {exc}) \u2014 left pending",
            level=logging.ERROR,
        )
        return {"status": "failed"}
    return result
