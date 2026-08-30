# Socraitia — an AI thinking partner, not an answer machine

**Live demo:** https://socraitia-web-424012738412.us-central1.run.app
**Stack proof:** `./scripts/verify_stack.sh` — 7/7 checks against the live
Vertex API, ~15s. Run it before believing anything this README claims.

---

## The problem

Deep intellectual work dies in dead notes. A researcher reads forty papers,
argues with themselves in a notebook, changes their mind three times — and
none of it accumulates into anything they can see. The notes app stores the
words and forgets the reasoning. Six weeks later the contradiction between
what they believed in March and what they believe now is invisible, because
nothing was keeping score.

Chatbots made this worse, not better. They answer instead of making you
think. Every conversation starts from zero, flatters your premise, and
evaporates when the tab closes. The tooling we have either stores text
without structure (notes) or produces text without memory (chat). Neither
treats your reasoning as an artifact worth building.

Socraitia is built on a different bet: **the graph is the product, not the
conversation.** You talk; it maps. Every claim, concept, question and
argument gap you produce becomes a typed node in a persistent knowledge
graph with typed relations between them. The system never answers your
question — it asks you one, and it remembers how you think across sessions,
well enough to confront you with the paper you uploaded last week that
disagrees with what you just said.

## What Socraitia does

- **Adaptive Socratic dialogue** — exactly one question per turn, calibrated
  to a persisted model of how you reason. Never lectures, never answers.
- **Autonomous graph construction** — a Cartographer agent extracts the
  structure of your argument from every exchange and mutates a live,
  force-directed graph in front of you.
- **Async verification** — every claim you make is queued to a Verifier that
  grounds it against Google Search and checks it against your own prior
  claims. Contradictions surface as glowing red edges — and as questions.
- **Document ingestion** — drop a PDF onto the canvas and it falls into the
  map: Gemini reads the paper natively, extracts its claims by section with
  full provenance, embeds them, and flags where the literature contradicts
  *you*.
- **Cross-project echoes** — a claim in your research project that rhymes
  with one in your product project writes a `connects_to` edge across the
  boundary. Serendipity, instrumented.
- **A learner model** — the system models *how* you think (reasoning style,
  blind spots, which question types land), evolves it every few exchanges,
  and adapts its questioning. Feedback buttons close the loop.
- **Node-anchored dialogue** — click any node, hit *Interrogate this*, and
  the dialogue focuses on that specific claim: its tensions, its evidence,
  its provenance.

## Architecture

![Architecture](docs/architecture.png)

```mermaid
flowchart LR
  U[User] -->|HTTPS + SSE| WEB["Cloud Run: socraitia-web<br/>(Next.js console)"]
  WEB -->|REST / SSE| API["Cloud Run: socraitia-api<br/>(FastAPI + ADK)"]
  WEB -->|PDF upload| API
  API --> GCS[(Cloud Storage<br/>ingest bucket)]

  subgraph AGENTS["ADK agents (one Cloud Run service)"]
    SOC["Socratic<br/>sync · read-only"]
    CAR["Cartographer<br/>sync · writes graph"]
    MOD["Modeler<br/>checkpoint · learner model"]
    VER["Verifier<br/>async · evidence + tensions"]
    ING["Ingestion<br/>async · document → claims"]
  end

  API --> SOC & CAR
  SOC & CAR & MOD & VER & ING -->|Vertex AI| GEM["Gemini 3.5 Flash<br/>@ global endpoint"]
  CAR & ING --> EMB["gemini-embedding-2<br/>@ global endpoint"]
  CAR & MOD & VER & ING --> FS[("Firestore 'socraitia'<br/>us-central1")]
  CAR -->|publish claim| PS["Pub/Sub<br/>claims-to-verify"]
  API -->|publish doc| PSI["Pub/Sub<br/>documents-to-ingest"]
  PS -->|push| VER
  PSI -->|push| ING
  VER -->|googleSearch grounding| GEM
  FS -->|/api/watch SSE| WEB
```

One backend service serves the API **and** the two Pub/Sub push endpoints.
One image, one IAM identity, one deploy — a second worker service would
double cold starts for no isolation we need at this scale.

### Agent roster

| Agent | Runs | Reads | Writes |
| --- | --- | --- | --- |
| **Socratic** | sync, every dialogue turn | graph summary, last 6 exchanges, learner model, tensions, echoes, focused node | nothing — it only asks |
| **Cartographer** | sync (concurrent with Socratic) | the exchange + graph context | nodes/edges diff, schema-constrained |
| **Verifier** | async, per claim (Pub/Sub push) | claim text, its embedding, the project's other claims, Google Search | evidence nodes, supports/contradicts edges, `verified` status |
| **Modeler** | every 3 exchanges + on session end | transcript, graph diffs, feedback tally | `users/{uid}.learner_model` (merge, never reset) |
| **Ingestion** | async, per document (Pub/Sub push) | raw PDF from GCS, via Gemini native document understanding | claims with provenance, cross-source contradicts edges |

The Socratic and Cartographer run **concurrently**, not in sequence — a
measured decision: ~4.3s to first token + ~8.5s extraction would cost ~13s
serialized, which is unusable live. They can overlap because the
Cartographer maps the user's message against the partner's *previous*
question, which is already known.

## Architecture decisions (the ones that matter)

**SHA-1 node identity.** A node's id is the SHA-1 of its normalized text.
One decision buys three properties: restatements merge instead of
duplicating (dedupe), Pub/Sub redelivery is a no-op (idempotency), and the
Cartographer can reference nodes by text while the store resolves them by
hash (edge resolution). The graph converges as it grows because identity is
content.

**Document-level ingestion idempotency.** Claim-level hashing is not enough
for re-uploads: two runs of the extractor can phrase the same finding
differently, which would fork the graph. So the SHA-1 of the file *bytes* is
the document id, and a re-upload is skipped before Gemini is called. Found
by testing, not by foresight — see Findings.

**Two-region reality, one config file.** Gemini 3.x is served **only** from
Vertex's `global` endpoint (us-central1 returns 404 — verified, and
`verify_stack.sh` re-asserts it). Firestore lives in us-central1. Every
model id and region lives in exactly one file, `backend/app/config.py`,
because model names rotate on the order of weeks and scattered identifiers
are a liability.

**Context strategy: the graph is the memory.** We never replay full
history. Each turn injects four bounded pieces: a hierarchical graph summary
(top-k by degree centrality), the last 6 exchanges verbatim, the learner
model as explicit directives, and open tensions. The artifact carries
long-term memory, so the prompt stays flat as a project grows across
sessions.

**In-memory cosine, with a stated boundary.** Similarity search (echoes,
contradiction candidates) runs as in-memory cosine over the owner's node
set. At hundreds of nodes that is microseconds and zero infrastructure; the
migration point to Vector Search is tens of thousands of nodes. A deliberate
trade-off, documented rather than hidden.

**Verification is for user claims, not literature.** Ingested paper claims
are born `active`; only the *user's* claims go through the Verifier. This is
an epistemic distinction, not a shortcut: the system verifies what you
assert, not what Bloom asserted in 1984. It also keeps the pending queue
honest — a pile of unverifiable literature would read as a stuck pipeline.

**Contradiction detection scales across two mechanisms.** Empirically
observed in testing: in small graphs the Cartographer catches
contradictions via context (the conflicting claim is in the top-k summary);
in larger graphs the async Verifier catches them via embedding retrieval,
long after the original claim fell out of the context window. The demo
exercises both.

## Failure tolerance

| Path | Timeout | Retries | If it fails |
| --- | --- | --- | --- |
| Socratic / Cartographer | 60s | 2 | turn stays up; empty diff or error event |
| Embeddings | inherited | 1 | node exists without a vector; no echo |
| Pub/Sub publish | 8s | none | claim stays `verification_pending` |
| Verifier (search + polarity) | 45s | 2 | claim stays pending; graph remains usable |
| Ingestion (Gemini on PDF) | ack deadline 300s | platform redelivery | failed doc is a feed line, never a 500 |
| Pub/Sub redelivery | — | platform | SHA-1 ids + `verified_at` make it a no-op |

A claim without evidence is never a broken UI: the node draws a dashed ring
and the status bar counts `pending` until the Verifier stamps `verified` —
or never does. That is the degradation the demo is allowed to show.

## Security posture (hackathon scope, stated honestly)

- The backend is public because the frontend is; the Pub/Sub push endpoints
  are gated by a shared token in the URL query string. This is
  hackathon-scope: it stops casual abuse, not a motivated attacker.
- CORS is open (`*`) for the same reason.
- Identity is a fixed demo uid — there is no auth.
- Production hardening, enumerated as known next steps: OIDC-verified push
  subscriptions (Pub/Sub → Cloud Run service account) instead of a URL
  token, per-user auth with Firestore security rules, CORS restricted to the
  web origin, secret management via Secret Manager, and rate limiting at the
  API edge.
- IAM is least-privilege where it counts: the Cloud Run service account
  holds exactly `datastore.user`, `aiplatform.user`, `pubsub.publisher`,
  `pubsub.subscriber`, `storage.objectAdmin` — see `infra/iam_setup.sh`.

## Findings & learnings

- **ADK 2.x drifted from its own docs.** Constructor and streaming
  signatures in `google-adk` 2.8 do not match the published examples; we
  pinned the exact version and isolated every ADK touchpoint behind
  `agents/runtime.py` so the next signature change is a one-file fix.
- **Gemini 3.x region availability is real and enforced.** `global` only;
  us-central1 is a hard 404. The architecture is built around this, and
  `verify_stack.sh` asserts the 404 on purpose — if Google backfills the
  region, the check going green is the signal to revisit.
- **Latency forced concurrency.** A serialized Socratic→Cartographer turn
  measured ~13s. Running them concurrently against the *previous* question
  cut perceived latency to ~7s end-to-end. The dependency analysis (the
  Cartographer does not need the question being composed) was the real work.
- **The ingestion dedup bug.** Re-uploading the same PDF produced *new*
  nodes, because two extractor runs phrase the same finding differently and
  content-hash identity only merges identical text. Fixed with
  document-level idempotency (hash of bytes, skip before extraction). Found
  by explicitly testing the re-upload case; would have been a silent demo
  bug.
- **Native document understanding beat a parsing library.** Gemini reading
  the raw PDF handled two-column academic layout, figures and references
  without a single parsing dependency, and made section-aware chunking
  trivial — the model names the section each claim came from, which became
  our provenance.
- **Small graphs and large graphs contradict differently.** Same-session
  contradictions are caught by the Cartographer through context; delayed
  ones (3+ turns later, outside the window) are only caught by the async
  Verifier's embedding retrieval. Both were proven in testing before we
  believed either.

## Reproducible spin-up

Requires: Google Cloud SDK, Python 3.10+, Node 24, a GCP project with
billing.

```bash
git clone https://github.com/rdbetancur/socraitia.git && cd socraitia

gcloud auth application-default login
gcloud config set project <your-project>

# 0. Prove the model identifiers are real in YOUR project (7 checks, ~15s)
./scripts/verify_stack.sh

# 1. IAM: dedicated service account + least-privilege roles + API enablement
./infra/iam_setup.sh

# 2. Deploy both services (api first; its URL is baked into the web build)
./infra/deploy.sh

# 3. Seed the demo state (2 projects, learner model, echo pair, idempotent)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/seed_demo.py
```

Local development:

```bash
cd backend  && .venv/bin/python -m uvicorn app.main:app --port 8080
cd frontend && npm install && npm run dev        # http://localhost:3000
```

Useful scripts (`backend/scripts/`): `smoke_turn.py` (core loop, throwaway
project), `cloud_e2e.py` (deployed end-to-end), `seed_demo.py` (demo state),
`reset_learner_model.py` (wipe learner state).

## Stack

Gemini 3.5 Flash (Vertex AI, global endpoint) · Google ADK 2.8 ·
gemini-embedding-2 · Firestore (us-central1) · Cloud Run · Pub/Sub · Cloud
Storage · Next.js. No non-Google infrastructure.

---

*Architecture deep-dive: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Region measurements: [docs/verification-log.md](docs/verification-log.md)*
