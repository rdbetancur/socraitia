"""Single source of truth for model IDs, regions and agent tunables.

Every Google model identifier and region in Socraitia lives in this file. Model
names on Vertex rotate often enough that having them scattered across modules is
a liability, and the region split below is not a preference — it is forced:

  * Gemini 3.x is served ONLY from the `global` endpoint. A call to
    us-central1 returns HTTP 404 (verified 2026-08-29).
  * Veo is served ONLY from us-central1.
  * Firestore `socraitia` lives in us-central1.

`scripts/verify_stack.sh` re-checks every identifier here against the live API.
"""

from __future__ import annotations

import os

VERIFIED_ON = "2026-08-29"

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "socraitia")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "socraitia")

# --- regions (see module docstring: these differ on purpose) -----------------
GEMINI_LOCATION = os.getenv("GEMINI_LOCATION", "global")
VEO_LOCATION = os.getenv("VEO_LOCATION", "us-central1")

# --- models -----------------------------------------------------------------
MODEL_SOCRATIC = os.getenv("MODEL_SOCRATIC", "gemini-3.5-flash")
MODEL_CARTOGRAPHER = os.getenv("MODEL_CARTOGRAPHER", "gemini-3.5-flash")
MODEL_VERIFIER = os.getenv("MODEL_VERIFIER", "gemini-3.5-flash")
MODEL_MODELER = os.getenv("MODEL_MODELER", "gemini-3.5-flash")

# gemini-embedding-2 is multimodal and only reachable on the global endpoint.
MODEL_EMBEDDING = os.getenv("MODEL_EMBEDDING", "gemini-embedding-2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))

MODEL_VEO = os.getenv("MODEL_VEO", "veo-3.1-fast-generate-001")

# --- identity ---------------------------------------------------------------
# Phase 1 ships a fixed demo identity. The seed script writes prior sessions
# under this same uid so cross-session contradictions exist before the demo
# starts, without anyone having to log in on camera.
DEMO_UID = os.getenv("DEMO_UID", "demo-researcher")
DEMO_PROJECT_ID = os.getenv("DEMO_PROJECT_ID", "ai-in-education")

# --- failure tolerance ------------------------------------------------------
AGENT_TIMEOUT_S = float(os.getenv("AGENT_TIMEOUT_S", "60"))
AGENT_RETRY_ATTEMPTS = int(os.getenv("AGENT_RETRY_ATTEMPTS", "2"))
AGENT_RETRY_BASE_DELAY_S = float(os.getenv("AGENT_RETRY_BASE_DELAY_S", "0.8"))

# --- context window strategy (documented in README, explicitly judged) ------
# We never replay full history. Per turn we inject a hierarchical graph summary
# (top-k by degree centrality), the last N exchanges, and the learner model.
CONTEXT_RECENT_EXCHANGES = int(os.getenv("CONTEXT_RECENT_EXCHANGES", "6"))
CONTEXT_GRAPH_TOP_K = int(os.getenv("CONTEXT_GRAPH_TOP_K", "18"))

# Modeler runs after every N dialogue exchanges AND on explicit session end.
# Session-end is the demo gesture (close → new session → adapted question).
# N=3 is the safety net: a closed tab still writes a model if they did 3 turns,
# and a live demo sees [MODELER] without requiring the extra click.
MODELER_EVERY_N = int(os.getenv("MODELER_EVERY_N", "3"))

# --- feature flags ----------------------------------------------------------
# Embeddings are written on node creation so Phase 3 contradiction detection has
# vectors ready. Guarded because a Phase 1 demo must not die if embeddings fail.
ENABLE_EMBEDDINGS = os.getenv("ENABLE_EMBEDDINGS", "true").lower() == "true"

# Cross-project echoes: in-memory cosine over the owner's full node set.
# High on purpose — a weak match is noise, a strong one is the demo moment.
# This stays valid only at low node counts (see README).
CROSS_PROJECT_MIN_COSINE = float(os.getenv("CROSS_PROJECT_MIN_COSINE", "0.78"))
CROSS_PROJECT_MAX_PER_NODE = int(os.getenv("CROSS_PROJECT_MAX_PER_NODE", "2"))

# --- async verifier (Phase 3) ----------------------------------------------
PUBSUB_CLAIMS_TOPIC = os.getenv("PUBSUB_CLAIMS_TOPIC", "claims-to-verify")
PUBSUB_PUSH_TOKEN = os.getenv("PUBSUB_PUSH_TOKEN", "")
VERIFIER_TIMEOUT_S = float(os.getenv("VERIFIER_TIMEOUT_S", "45"))
VERIFIER_RETRY_ATTEMPTS = int(os.getenv("VERIFIER_RETRY_ATTEMPTS", "2"))
INTRA_CLAIM_MIN_COSINE = float(os.getenv("INTRA_CLAIM_MIN_COSINE", "0.82"))
ENABLE_VERIFIER = os.getenv("ENABLE_VERIFIER", "true").lower() == "true"

# --- ingestion (Phase 5) ----------------------------------------------------
PUBSUB_INGEST_TOPIC = os.getenv("PUBSUB_INGEST_TOPIC", "documents-to-ingest")
GCS_INGEST_BUCKET = os.getenv("GCS_INGEST_BUCKET", "socraitia-ingest")
# Bucket name must be globally unique; default derives from the project.
GCS_INGEST_BUCKET = os.getenv("GCS_INGEST_BUCKET") or f"{PROJECT_ID}-ingest"
INGEST_MAX_CLAIMS = int(os.getenv("INGEST_MAX_CLAIMS", "10"))
INGEST_MAX_SECTION_CHARS = int(os.getenv("INGEST_MAX_SECTION_CHARS", "12000"))
INGEST_CONTRADICTION_MIN_COSINE = float(os.getenv("INGEST_CONTRADICTION_MIN_COSINE", "0.80"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]


def configure_genai_env() -> None:
    """Point the ADK / google-genai clients at Vertex AI.

    Must run before any agent is constructed. ADK reads these at client build
    time, so setting them in code keeps local runs and Cloud Run identical
    instead of depending on a shell that only exists on one of them.
    """
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", GEMINI_LOCATION)
