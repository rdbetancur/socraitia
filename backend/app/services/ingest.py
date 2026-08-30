"""Document ingestion — GCS → Gemini document understanding → Cartographer.

One async job per uploaded file, delivered by Pub/Sub push. The pipeline:

  1. Gemini reads the PDF natively (no parsing library) and returns sections
     with claims. Section-aware, not token-windowed: a paper's claims live in
     abstract/results/discussion; references and boilerplate are skipped.
  2. Claims become nodes via the same schema as the Cartographer, tagged
     source=ingestion with provenance (document + section).
  3. Every node is embedded, so an ingested claim participates in
     contradiction detection and cross-project echoes exactly like a spoken
     one. A paper claim that contradicts the user's own prior claim writes a
     `contradicts` edge across the source boundary.

Idempotency: node ids are SHA-1 of normalized text, so re-uploading the same
document merges instead of duplicating.
"""

from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from google.cloud import storage
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app import config
from app.agents import verifier
from app.graph import repo
from app.logging_setup import agent_log
from app.schemas import ExtractedEdge, ExtractedNode, GraphDiff
from app.services.embeddings import cosine, embed_many

_client: genai.Client | None = None
_storage: storage.Client | None = None


def _genai() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.GEMINI_LOCATION
        )
    return _client


def _gcs() -> storage.Client:
    global _storage
    if _storage is None:
        _storage = storage.Client(project=config.PROJECT_ID)
    return _storage


class DocClaim(BaseModel):
    text: str
    type: str = "claim"
    section: str = ""


class DocSection(BaseModel):
    section: str = ""
    claims: list[DocClaim] = Field(default_factory=list)


class DocExtraction(BaseModel):
    title: str = ""
    sections: list[DocSection] = Field(default_factory=list)


EXTRACT_PROMPT = """\
Read this academic PDF. Extract the claims that carry the argument.

Rules:
- Work by SECTION, not by page. Name each section (Abstract, Introduction,
  Results, Discussion, …). Skip references, acknowledgments, author bios,
  and boilerplate.
- Each claim is a self-contained proposition, understandable with no
  surrounding text. Never "the results show" — say what they show.
- Prefer claims from Abstract, Results and Discussion. At most {max_claims}
  claims total, strongest first.
- `type` is claim for an asserted finding, concept for a named construct the
  argument depends on, question for an open problem the authors raise.
- `section` is the section the claim came from.

Return ONLY JSON:
{{"title": "...", "sections": [{{"section": "...", "claims": [{{"text": "...", "type": "claim", "section": "..."}}]}}]}}
"""


async def extract_document(gcs_uri: str, filename: str) -> DocExtraction:
    """Gemini native document understanding on the raw PDF bytes."""
    bucket_name, blob_name = gcs_uri.removeprefix("gs://").split("/", 1)
    blob = _gcs().bucket(bucket_name).blob(blob_name)
    data = await asyncio.to_thread(blob.download_as_bytes)
    agent_log("INGESTION", f"{filename} → {len(data) // 1024} KiB from GCS")

    response = await _genai().aio.models.generate_content(
        model=config.MODEL_CARTOGRAPHER,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=data, mime_type="application/pdf"),
                    types.Part(
                        text=EXTRACT_PROMPT.format(max_claims=config.INGEST_MAX_CLAIMS)
                    ),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=8192,
            response_mime_type="application/json",
        ),
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].removeprefix("json").strip()
    try:
        return DocExtraction.model_validate_json(raw)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        agent_log(
            "INGESTION",
            f"{filename} parse failed ({type(exc).__name__}) — no claims",
            level=logging.WARNING,
        )
        return DocExtraction()


async def ingest_document(
    project_id: str, doc_id: str, filename: str, gcs_uri: str, user_id: str
) -> dict:
    """One Pub/Sub job. Never raises — a failed document is a feed line, not a 500."""
    # Idempotency at the document level: a re-upload of the same bytes lands on
    # the same doc_id and is skipped before Gemini is called. Claim-level SHA-1
    # merging alone is not enough because two runs of the extractor can phrase
    # the same finding differently, which would fork the graph.
    if await repo.document_ingested(project_id, doc_id):
        await repo.append_feed(
            project_id, "INGESTION", f"{filename} → already ingested, skipped"
        )
        return {"status": "duplicate", "doc_id": doc_id}
    await repo.append_feed(project_id, "INGESTION", f"{filename} → reading document")
    try:
        doc = await extract_document(gcs_uri, filename)
    except Exception as exc:  # noqa: BLE001
        line = agent_log(
            "INGESTION", f"{filename} FAILED ({type(exc).__name__}: {exc})", level=logging.ERROR
        )
        await repo.append_feed(project_id, "INGESTION", line)
        return {"status": "failed", "doc_id": doc_id}

    section_n = len(doc.sections)
    claims = [c for s in doc.sections for c in s.claims if c.text.strip()]
    await repo.append_feed(
        project_id,
        "INGESTION",
        f"{filename} → {section_n} sections → {len(claims)} claims extracted",
    )
    if not claims:
        return {"status": "empty", "doc_id": doc_id, "sections": section_n}

    snapshot = await repo.load_graph(project_id)
    nodes = [
        ExtractedNode(
            type=c.type if c.type in ("claim", "concept", "question") else "claim",
            text=c.text.strip(),
            provenance=f"{doc.title or filename} — {c.section or s.section or 'body'}",
        )
        for s in doc.sections
        for c in s.claims
        if c.text.strip()
    ]
    applied = await repo.apply_diff(
        project_id,
        session_id=f"ingest_{doc_id}",
        diff=GraphDiff(nodes=nodes),
        snapshot=snapshot,
        source="ingestion",
        agent="ingestion",
    )
    # Ingested claims are literature, not user claims awaiting the Verifier —
    # leaving them in verification_pending would read as a stuck queue.
    for node in applied.new_nodes:
        if node.type == "claim":
            await repo.set_node_status(project_id, node.id, "active")
    await repo.append_feed(
        project_id,
        "INGESTION",
        f"{filename} → {applied.summary()} (provenance: {doc.title or filename})",
    )

    # Embed so ingested claims join contradiction detection + echoes.
    vectors = await embed_many({n.id: n.text for n in applied.new_nodes})
    if vectors:
        await repo.set_node_embeddings(project_id, vectors)
        await repo.append_feed(
            project_id, "EMBED", f"{len(vectors)} ingested node(s) → {config.MODEL_EMBEDDING}"
        )

    # Cross-source contradiction: an ingested claim against the user's own claims.
    tensions = 0
    snapshot = await repo.load_graph(project_id)
    user_claims = [
        n for n in snapshot.nodes.values() if n.type == "claim" and n.source != "ingestion"
    ]
    for node in applied.new_nodes:
        if node.type != "claim":
            continue
        vec = vectors.get(node.id) or await repo.load_node_embedding(project_id, node.id)
        if not vec:
            continue
        scored: list[tuple[float, str]] = []
        for other in user_claims:
            other_vec = await repo.load_node_embedding(project_id, other.id)
            if not other_vec:
                continue
            score = cosine(vec, other_vec)
            if score >= config.INGEST_CONTRADICTION_MIN_COSINE:
                scored.append((score, other.text))
        scored.sort(key=lambda row: -row[0])
        for score, other_text in scored[:1]:
            relation = await verifier.polarity(node.text, other_text)
            if relation != "contradicts":
                continue
            snapshot = await repo.load_graph(project_id)
            result = await repo.apply_diff(
                project_id,
                session_id=f"ingest_{doc_id}",
                diff=GraphDiff(
                    edges=[
                        ExtractedEdge(
                            from_text=node.text, to_text=other_text, relation="contradicts"
                        )
                    ]
                ),
                snapshot=snapshot,
                source="ingestion",
                agent="ingestion",
            )
            if result.new_edges:
                tensions += len(result.new_edges)
                await repo.append_feed(
                    project_id,
                    "INGESTION",
                    f"{filename} → TENSION: paper claim contradicts your earlier claim "
                    f"({score:.2f})",
                )

    await repo.mark_document_ingested(project_id, doc_id, filename)
    await repo.append_feed(
        project_id,
        "INGESTION",
        f"{filename} → done: {len(applied.new_nodes)} new nodes, "
        f"{len(applied.merged_node_ids)} merged, {tensions} cross-source tension(s)",
    )
    return {
        "status": "ok",
        "doc_id": doc_id,
        "sections": section_n,
        "claims": len(claims),
        "new_nodes": len(applied.new_nodes),
        "merged": len(applied.merged_node_ids),
        "tensions": tensions,
    }
