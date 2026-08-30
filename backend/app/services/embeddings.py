"""Vertex AI embeddings.

Written on node creation so Phase 3 contradiction detection has vectors ready
without a backfill pass. Everything here is best-effort by design: a Phase 1
turn must still complete if the embedding call fails, so callers get an empty
dict rather than an exception.

Note the client location — gemini-embedding-2 is only reachable on the `global`
endpoint, the same constraint that applies to Gemini 3.x.
"""

from __future__ import annotations

import asyncio
import logging

from google import genai
from google.genai import types

from app import config
from app.logging_setup import agent_log

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True, project=config.PROJECT_ID, location=config.GEMINI_LOCATION
        )
    return _client


async def embed(text: str) -> list[float] | None:
    try:
        resp = await client().aio.models.embed_content(
            model=config.MODEL_EMBEDDING,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=config.EMBEDDING_DIM),
        )
        if resp.embeddings and resp.embeddings[0].values:
            return list(resp.embeddings[0].values)
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the turn
        agent_log("EMBED", f"failed ({type(exc).__name__}: {exc})", level=logging.WARNING)
    return None


async def embed_many(texts: dict[str, str]) -> dict[str, list[float]]:
    """Embed several node texts concurrently. Keys are node ids."""
    if not texts or not config.ENABLE_EMBEDDINGS:
        return {}
    ids = list(texts)
    results = await asyncio.gather(*(embed(texts[i]) for i in ids))
    return {nid: vec for nid, vec in zip(ids, results) if vec}


def cosine(a: list[float], b: list[float]) -> float:
    """In-memory cosine similarity.

    A deliberate trade-off documented in the README: at hundreds of nodes this
    is microseconds and needs no extra infrastructure, so Vector Search would
    be architecture for its own sake. The migration point is tens of thousands
    of nodes, not a rewrite.
    """
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
