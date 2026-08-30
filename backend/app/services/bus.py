"""Pub/Sub publish path for new claims.

A publish failure must never fail the user-facing turn: the claim stays in
`verification_pending` and the graph remains usable. That is the degradation
the README documents.
"""

from __future__ import annotations

import json
import logging

from google.cloud import pubsub_v1

from app import config
from app.logging_setup import agent_log

_publisher: pubsub_v1.PublisherClient | None = None


def _client() -> pubsub_v1.PublisherClient:
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def topic_path() -> str:
    return _client().topic_path(config.PROJECT_ID, config.PUBSUB_CLAIMS_TOPIC)


def ingest_topic_path() -> str:
    return _client().topic_path(config.PROJECT_ID, config.PUBSUB_INGEST_TOPIC)


def publish_claim(*, project_id: str, node_id: str, text: str, user_id: str) -> None:
    payload = {
        "project_id": project_id,
        "node_id": node_id,
        "text": text,
        "user_id": user_id,
    }
    try:
        future = _client().publish(topic_path(), json.dumps(payload).encode("utf-8"))
        future.result(timeout=8)
        agent_log("VERIFIER:async", f"{node_id} \u2192 queued on {config.PUBSUB_CLAIMS_TOPIC}")
    except Exception as exc:  # noqa: BLE001
        agent_log(
            "VERIFIER:async",
            f"{node_id} publish failed ({type(exc).__name__}) \u2014 left pending",
            level=logging.WARNING,
        )


def publish_ingest(
    *, project_id: str, doc_id: str, filename: str, gcs_uri: str, user_id: str
) -> None:
    """Queue a document for async ingestion. Never raises into the upload path."""
    payload = {
        "project_id": project_id,
        "doc_id": doc_id,
        "filename": filename,
        "gcs_uri": gcs_uri,
        "user_id": user_id,
    }
    try:
        future = _client().publish(ingest_topic_path(), json.dumps(payload).encode("utf-8"))
        future.result(timeout=8)
        agent_log("INGESTION", f"{filename} \u2192 queued on {config.PUBSUB_INGEST_TOPIC}")
    except Exception as exc:  # noqa: BLE001
        agent_log(
            "INGESTION",
            f"{filename} publish failed ({type(exc).__name__})",
            level=logging.WARNING,
        )
