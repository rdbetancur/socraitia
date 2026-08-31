"""Firestore graph mutation.

Node ids are a SHA-1 of the normalized node text rather than random uuids. That
one choice buys three properties the architecture needs:

  * merging — the same claim stated twice in different sessions lands on the
    same document, so the graph converges instead of growing duplicates;
  * idempotency — a Pub/Sub message redelivered to the Verifier or the
    ingestion worker writes the same document twice with no effect, which is
    the dedupe strategy the async agents rely on;
  * resolvability — the Cartographer emits edges by text, and we can derive the
    endpoint id without a second LLM call or a lookup round-trip.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app import config
from app.schemas import AppliedDiff, EchoOut, EdgeOut, GraphDiff, NodeOut, NodeSource

_client: firestore.AsyncClient | None = None

_PUNCT_TAIL = re.compile(r"[\s.,;:!?\u2014\-]+$")
_WHITESPACE = re.compile(r"\s+")


def db() -> firestore.AsyncClient:
    global _client
    if _client is None:
        _client = firestore.AsyncClient(
            project=config.PROJECT_ID, database=config.FIRESTORE_DATABASE
        )
    return _client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(text: str) -> str:
    """Collapse the cosmetic differences that would otherwise fork a node."""
    return _PUNCT_TAIL.sub("", _WHITESPACE.sub(" ", text.strip().lower()))


def node_id(text: str) -> str:
    return "n_" + hashlib.sha1(normalize(text).encode()).hexdigest()[:12]


def edge_id(from_id: str, to_id: str, relation: str, remote_project_id: str = "") -> str:
    key = f"{from_id}>{relation}>{remote_project_id}:{to_id}" if remote_project_id else f"{from_id}>{relation}>{to_id}"
    return "e_" + hashlib.sha1(key.encode()).hexdigest()[:12]


_SLUG = re.compile(r"[^a-z0-9]+")


def project_id_from_title(title: str) -> str:
    slug = _SLUG.sub("-", title.lower()).strip("-")[:36]
    return slug or "project"


@dataclass
class GraphSnapshot:
    """The whole project graph in memory.

    At demo scale (hundreds of nodes) a full read per turn costs a few
    milliseconds and removes an entire class of consistency bug. This is a
    deliberate trade-off, documented rather than hidden: the point at which it
    stops being correct is a Firestore composite index plus paging, not a
    rewrite.
    """

    nodes: dict[str, NodeOut] = field(default_factory=dict)
    edges: list[EdgeOut] = field(default_factory=list)

    def id_for_text(self, text: str) -> str | None:
        nid = node_id(text)
        return nid if nid in self.nodes else None

    def degree(self) -> dict[str, int]:
        counts = {nid: 0 for nid in self.nodes}
        for e in self.edges:
            if e.from_id in counts:
                counts[e.from_id] += 1
            if e.to_id in counts:
                counts[e.to_id] += 1
        return counts


async def ensure_project(project_id: str, *, title: str, domain: str) -> None:
    ref = db().collection("projects").document(project_id)
    snap = await ref.get()
    if not snap.exists:
        await ref.set(
            {
                "title": title,
                "domain": domain,
                "owner": config.DEMO_UID,
                "created_at": _now(),
            }
        )


def _node_from_doc(doc_id: str, d: dict) -> NodeOut:
    raw_type = d.get("type", "claim")
    if raw_type not in ("claim", "concept", "question", "evidence", "gap", "note"):
        raw_type = "claim"
    raw_source = d.get("source", "user")
    if raw_source not in ("user", "verifier", "ingestion", "note"):
        raw_source = "user"
    raw_status = d.get("status", "active")
    if raw_status not in ("active", "verification_pending", "verified"):
        raw_status = "active"
    return NodeOut(
        id=doc_id,
        type=raw_type,
        text=d.get("text", ""),
        source=raw_source,
        status=raw_status,
        session_id=d.get("session_id", ""),
        degree=d.get("degree", 0),
        created_at=d.get("created_at", ""),
        verified_at=d.get("verified_at", ""),
        provenance=d.get("provenance", ""),
    )


def _edge_from_doc(doc_id: str, d: dict) -> EdgeOut:
    raw_rel = d.get("relation", "supports")
    if raw_rel not in (
        "supports",
        "contradicts",
        "refines",
        "questions",
        "answers",
        "connects_to",
    ):
        raw_rel = "supports"
    return EdgeOut(
        id=doc_id,
        from_id=d.get("from", ""),
        to_id=d.get("to", ""),
        relation=raw_rel,
        weight=d.get("weight", 1.0),
        created_by_agent=d.get("created_by_agent", "cartographer"),
        created_at=d.get("created_at", ""),
        remote_project_id=d.get("remote_project_id", ""),
        remote_project_title=d.get("remote_project_title", ""),
        remote_text=d.get("remote_text", ""),
    )


async def document_ingested(project_id: str, doc_id: str) -> bool:
    snap = await (
        db().collection("projects").document(project_id)
        .collection("documents").document(doc_id).get()
    )
    return snap.exists


async def mark_document_ingested(project_id: str, doc_id: str, filename: str) -> None:
    await (
        db().collection("projects").document(project_id)
        .collection("documents").document(doc_id)
        .set({"filename": filename, "ingested_at": _now()})
    )


async def load_graph(project_id: str) -> GraphSnapshot:
    proj = db().collection("projects").document(project_id)
    snapshot = GraphSnapshot()

    async for doc in proj.collection("nodes").stream():
        snapshot.nodes[doc.id] = _node_from_doc(doc.id, doc.to_dict() or {})

    async for doc in proj.collection("edges").stream():
        edge = _edge_from_doc(doc.id, doc.to_dict() or {})
        snapshot.edges.append(edge)
        if edge.relation == "connects_to" and edge.from_id in snapshot.nodes:
            snapshot.nodes[edge.from_id].echoes.append(
                EchoOut(
                    node_id=edge.to_id,
                    text=edge.remote_text,
                    project_id=edge.remote_project_id,
                    project_title=edge.remote_project_title,
                    similarity=edge.weight,
                )
            )

    return snapshot


async def list_projects(uid: str) -> list[dict]:
    rows: list[dict] = []
    try:
        query = db().collection("projects").where(filter=FieldFilter("owner", "==", uid))
        stream = query.stream()
    except Exception:
        stream = db().collection("projects").stream()
    async for doc in stream:
        d = doc.to_dict() or {}
        if d.get("owner") and d.get("owner") != uid:
            continue
        if d.get("hidden"):
            continue
        rows.append(
            {
                "id": doc.id,
                "title": d.get("title") or doc.id,
                "domain": d.get("domain", ""),
                "created_at": d.get("created_at", ""),
            }
        )
    rows.sort(key=lambda r: r.get("created_at") or r["id"])
    return rows


async def set_project_hidden(project_id: str, hidden: bool = True) -> None:
    await db().collection("projects").document(project_id).set(
        {"hidden": hidden}, merge=True
    )


async def get_project(project_id: str) -> dict | None:
    snap = await db().collection("projects").document(project_id).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    return {
        "id": snap.id,
        "title": d.get("title") or snap.id,
        "domain": d.get("domain", ""),
        "owner": d.get("owner", ""),
        "created_at": d.get("created_at", ""),
    }


async def create_project(title: str, domain: str = "") -> dict:
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    pid = project_id_from_title(title)
    existing = await db().collection("projects").document(pid).get()
    if existing.exists:
        pid = f"{pid}-{hashlib.sha1(f'{title}{_now()}'.encode()).hexdigest()[:4]}"
    await db().collection("projects").document(pid).set(
        {
            "title": title,
            "domain": domain.strip(),
            "owner": config.DEMO_UID,
            "created_at": _now(),
        }
    )
    return {"id": pid, "title": title, "domain": domain.strip(), "created_at": _now()}


async def load_owner_embedded_nodes(uid: str) -> list[dict]:
    """Every embedded node the user owns, across projects.

    Collection-group queries would need a composite index. At hackathon scale
    listing the owner's projects and streaming each node collection is cheaper
    to reason about and needs no extra Firestore setup.
    """
    out: list[dict] = []
    for project in await list_projects(uid):
        proj = db().collection("projects").document(project["id"])
        async for doc in proj.collection("nodes").stream():
            d = doc.to_dict() or {}
            vec = d.get("embedding")
            if not vec:
                continue
            out.append(
                {
                    "project_id": project["id"],
                    "project_title": project["title"],
                    "node_id": doc.id,
                    "text": d.get("text", ""),
                    "embedding": list(vec),
                }
            )
    return out


async def write_echo_edges(project_id: str, edges: list[EdgeOut]) -> list[EdgeOut]:
    if not edges:
        return []
    proj = db().collection("projects").document(project_id)
    existing = {eid async for eid in _edge_ids(proj)}
    batch = db().batch()
    written: list[EdgeOut] = []
    for edge in edges:
        if edge.id in existing:
            continue
        batch.set(proj.collection("edges").document(edge.id), edge.to_firestore(), merge=True)
        batch.update(
            proj.collection("nodes").document(edge.from_id),
            {"degree": firestore.Increment(1)},
        )
        written.append(edge)
        existing.add(edge.id)
    if written:
        await batch.commit()
    return written


async def _edge_ids(proj):
    async for doc in proj.collection("edges").stream():
        yield doc.id


async def apply_diff(
    project_id: str,
    session_id: str,
    diff: GraphDiff,
    snapshot: GraphSnapshot,
    *,
    source: NodeSource = "user",
    agent: str = "cartographer",
) -> AppliedDiff:
    """Write a Cartographer diff into Firestore and report what actually changed.

    Runs as one batched write so a turn either lands or does not. Edges whose
    endpoints cannot be resolved to a node are dropped and counted rather than
    silently creating phantom nodes — a hallucinated edge should shrink the
    diff, never corrupt the graph.
    """
    proj = db().collection("projects").document(project_id)
    batch = db().batch()
    applied = AppliedDiff()
    now = _now()

    # Nodes first, so edges emitted in the same diff can resolve against them.
    proposed_ids: dict[str, str] = {}
    for node in diff.nodes:
        text = node.text.strip()
        if not text:
            continue
        nid = node_id(text)
        proposed_ids[normalize(text)] = nid

        if nid in snapshot.nodes:
            applied.merged_node_ids.append(nid)
            continue
        if any(n.id == nid for n in applied.new_nodes):
            continue

        status = "verification_pending" if node.type == "claim" else "active"
        out = NodeOut(
            id=nid,
            type=node.type,
            text=text,
            source=source,
            status=status,
            session_id=session_id,
            degree=0,
            created_at=now,
            provenance=node.provenance,
        )
        applied.new_nodes.append(out)
        batch.set(
            proj.collection("nodes").document(nid),
            {
                "type": out.type,
                "text": out.text,
                "source": out.source,
                "status": out.status,
                "session_id": session_id,
                "degree": 0,
                "created_at": now,
                "provenance": out.provenance,
                "embedding": None,
            },
            merge=True,
        )

    def resolve(text: str) -> str | None:
        key = normalize(text)
        return proposed_ids.get(key) or snapshot.id_for_text(text)

    existing_edge_ids = {e.id for e in snapshot.edges}
    for edge in diff.edges:
        a, b = resolve(edge.from_text), resolve(edge.to_text)
        if not a or not b or a == b:
            applied.dropped_edges += 1
            continue
        eid = edge_id(a, b, edge.relation)
        if eid in existing_edge_ids or any(e.id == eid for e in applied.new_edges):
            continue

        out = EdgeOut(
            id=eid,
            from_id=a,
            to_id=b,
            relation=edge.relation,
            created_by_agent=agent,
            created_at=now,
        )
        applied.new_edges.append(out)
        batch.set(proj.collection("edges").document(eid), out.to_firestore(), merge=True)

        # Degree is denormalized onto the node so the context builder can rank by
        # centrality without loading the edge list twice.
        for endpoint in (a, b):
            batch.update(
                proj.collection("nodes").document(endpoint),
                {"degree": firestore.Increment(1)},
            )

    if applied.new_nodes or applied.new_edges:
        await batch.commit()

    return applied


async def set_node_embeddings(project_id: str, vectors: dict[str, list[float]]) -> None:
    proj = db().collection("projects").document(project_id)
    batch = db().batch()
    for nid, vec in vectors.items():
        batch.update(proj.collection("nodes").document(nid), {"embedding": vec})
    if vectors:
        await batch.commit()


# --- sessions ---------------------------------------------------------------


async def append_exchange(
    project_id: str,
    session_id: str,
    *,
    user_text: str,
    partner_text: str,
    graph_diff: AppliedDiff,
    kind: str = "dialogue",
) -> None:
    ref = (
        db()
        .collection("projects")
        .document(project_id)
        .collection("sessions")
        .document(session_id)
    )
    entry = {
        "user": user_text,
        "partner": partner_text,
        "kind": kind,
        "at": _now(),
        "diff": {
            "nodes": [n.id for n in graph_diff.new_nodes],
            "edges": [e.id for e in graph_diff.new_edges],
        },
    }
    snap = await ref.get()
    if snap.exists:
        await ref.update(
            {
                "transcript": firestore.ArrayUnion([entry]),
                "graph_diff": firestore.ArrayUnion(
                    [{"nodes": entry["diff"]["nodes"], "edges": entry["diff"]["edges"]}]
                ),
                "updated_at": _now(),
            }
        )
    else:
        await ref.set(
            {
                "transcript": [entry],
                "graph_diff": [entry["diff"]],
                "summary": "",
                "started_at": _now(),
                "updated_at": _now(),
            }
        )


async def load_transcript(project_id: str, session_id: str, limit: int) -> list[dict]:
    ref = (
        db()
        .collection("projects")
        .document(project_id)
        .collection("sessions")
        .document(session_id)
    )
    snap = await ref.get()
    if not snap.exists:
        return []
    transcript = (snap.to_dict() or {}).get("transcript", [])
    return transcript[-limit:]


async def delete_project(project_id: str) -> None:
    """Used by the smoke test so throwaway runs do not accumulate in Firestore."""
    proj = db().collection("projects").document(project_id)
    for sub in ("nodes", "edges", "sessions", "feed"):
        async for doc in proj.collection(sub).stream():
            await doc.reference.delete()
    await proj.delete()


async def set_node_status(project_id: str, nid: str, status: str) -> None:
    payload: dict = {"status": status}
    if status in ("active", "verified"):
        payload["verified_at"] = _now()
    await (
        db()
        .collection("projects")
        .document(project_id)
        .collection("nodes")
        .document(nid)
        .update(payload)
    )


async def is_claim_verified(project_id: str, nid: str) -> bool:
    snap = await (
        db().collection("projects").document(project_id).collection("nodes").document(nid).get()
    )
    if not snap.exists:
        return False
    d = snap.to_dict() or {}
    if d.get("verified_at"):
        return True
    return False


async def load_node_embedding(project_id: str, nid: str) -> list[float] | None:
    snap = await (
        db().collection("projects").document(project_id).collection("nodes").document(nid).get()
    )
    if not snap.exists:
        return None
    vec = (snap.to_dict() or {}).get("embedding")
    return list(vec) if vec else None


def already_verified(snapshot: GraphSnapshot, claim_id: str) -> bool:
    """Idempotency for Pub/Sub redelivery: one verifier pass per claim."""
    return any(
        e.created_by_agent == "verifier"
        and (e.from_id == claim_id or e.to_id == claim_id)
        for e in snapshot.edges
    )


async def append_feed(project_id: str, agent: str, line: str) -> dict:
    entry = {"agent": agent, "line": line, "at": _now()}
    await (
        db()
        .collection("projects")
        .document(project_id)
        .collection("feed")
        .add(entry)
    )
    return entry


async def load_feed(project_id: str, after: str = "") -> list[dict]:
    rows: list[dict] = []
    async for doc in (
        db().collection("projects").document(project_id).collection("feed").stream()
    ):
        d = doc.to_dict() or {}
        d["id"] = doc.id
        rows.append(d)
    rows.sort(key=lambda r: r.get("at") or "")
    if after:
        rows = [r for r in rows if (r.get("at") or "") > after]
    return rows


async def load_learner_model(uid: str) -> dict:
    snap = await db().collection("users").document(uid).get()
    if not snap.exists:
        return {}
    return (snap.to_dict() or {}).get("learner_model", {}) or {}


async def load_last_seen(uid: str, project_id: str) -> str:
    """When this user last acknowledged a briefing for this project.

    One field on the user doc, keyed by project. Everything the briefing shows
    is derived from node/edge timestamps already in Firestore; this is only the
    watermark that says "you have seen up to here".
    """
    snap = await db().collection("users").document(uid).get()
    if not snap.exists:
        return ""
    seen = (snap.to_dict() or {}).get("last_seen_at") or {}
    return seen.get(project_id, "") if isinstance(seen, dict) else ""


async def mark_seen(uid: str, project_id: str) -> str:
    now = _now()
    await db().collection("users").document(uid).set(
        {"last_seen_at": {project_id: now}}, merge=True
    )
    return now


async def load_feedback_tally(uid: str) -> dict:
    snap = await db().collection("users").document(uid).get()
    if not snap.exists:
        return {}
    return (snap.to_dict() or {}).get("feedback_tally", {}) or {}


async def save_learner_model(uid: str, model: dict) -> dict:
    payload = {**model, "updated_at": _now()}
    await db().collection("users").document(uid).set(
        {"learner_model": payload, "updated_at": _now()},
        merge=True,
    )
    return payload


async def increment_feedback_tally(uid: str, question_type: str, verdict: str) -> None:
    await db().collection("users").document(uid).set(
        {"feedback_tally": {question_type: {verdict: firestore.Increment(1)}}},
        merge=True,
    )


async def write_feedback(
    project_id: str,
    session_id: str,
    exchange: int,
    entry: dict,
) -> dict:
    ref = (
        db()
        .collection("projects")
        .document(project_id)
        .collection("sessions")
        .document(session_id)
    )
    await ref.set(
        {"feedback_by_exchange": {str(exchange): entry}, "updated_at": _now()},
        merge=True,
    )
    return entry


async def load_session(project_id: str, session_id: str) -> dict:
    snap = await (
        db()
        .collection("projects")
        .document(project_id)
        .collection("sessions")
        .document(session_id)
        .get()
    )
    if not snap.exists:
        return {}
    return snap.to_dict() or {}


def feedback_rows(session: dict) -> list[dict]:
    raw = session.get("feedback_by_exchange") or {}
    rows = []
    for key, value in raw.items():
        if isinstance(value, dict):
            rows.append({**value, "exchange": value.get("exchange", int(key) if str(key).isdigit() else 0)})
    rows.sort(key=lambda r: r.get("exchange") or 0)
    return rows


async def load_last_feedback(project_id: str, session_id: str) -> dict | None:
    rows = feedback_rows(await load_session(project_id, session_id))
    return rows[-1] if rows else None


async def mark_modeled(project_id: str, session_id: str, through: int) -> None:
    await (
        db()
        .collection("projects")
        .document(project_id)
        .collection("sessions")
        .document(session_id)
        .set({"modeled_through": through, "updated_at": _now()}, merge=True)
    )
