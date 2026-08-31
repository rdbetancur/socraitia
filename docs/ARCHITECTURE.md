# Architecture

Socraitia is two Cloud Run services in front of Firestore, Vertex AI, and
Pub/Sub. The conversation is a side rail. The product is a graph that agents
mutate.

Public URLs (2026-08-30):

- https://socraitia-web-424012738412.us-central1.run.app
- https://socraitia-api-424012738412.us-central1.run.app

```
browser ──► socraitia-web (Cloud Run, Next.js)
                 │
                 │ NEXT_PUBLIC_API_URL (baked at image build)
                 ▼
            socraitia-api (Cloud Run, FastAPI + ADK)
                 │
     ┌───────────┼────────────┬──────────────┐
     ▼           ▼            ▼              ▼
 Firestore   Vertex AI     Pub/Sub      (later) GCS
  us-c1      Gemini @        claims-     Veo @
             global          to-verify   us-c1
```

## Two-region reality

This is not a preference. It is what the live API returned on 2026-08-29
(see `docs/verification-log.md` and `scripts/verify_stack.sh`):

| Surface | Identifier | Endpoint that works | Endpoint that 404s |
| --- | --- | --- | --- |
| Gemini 3.5 Flash | `gemini-3.5-flash` | `global` | `us-central1` |
| Embeddings | `gemini-embedding-2` | `global` | `us-central1` |
| Veo 3.1 | `veo-3.1-fast-generate-001` | `us-central1` | n/a |
| Firestore `socraitia` | — | `us-central1` | — |

`backend/app/config.py` is the only file that names a model or a region.
Agents inherit `GEMINI_LOCATION=global`. Veo is listed there as a reserved
identifier; this build does not call it. Mixing those on one
`genai.Client` is how you get a 404 that looks like an IAM bug.

## Agents

| Agent | Sync? | Writes graph? | Transport |
| --- | --- | --- | --- |
| Socratic | yes | no | SSE on `/api/turn` |
| Cartographer | yes (overlaps Socratic) | yes | same request |
| Verifier | **async** | evidence + tensions | Pub/Sub → `/internal/pubsub/claims` |
| Modeler | after 3 exchanges + session end | no (writes `users/{uid}`) | same request / `POST /api/session/end` |
| Echo | sync after embed | `connects_to` | same request |

The backend Cloud Run service runs at 2 CPU / 2Gi with `min-instances=1` so a
Verifier call and an incoming turn do not share a cold 1-CPU box.

The Verifier shares the backend Cloud Run service. A second service would
double IAM, cold starts, and deploys for no isolation we need at this scale.
Push subscription `claims-to-verify-push` is the proof that verification is
not a chat-loop afterthought.

## Context window

Never replay full history. Each turn injects: top-k nodes by degree
centrality, last 6 exchanges, learner model, open tensions, cross-project
echoes. Cosine similarity is in-memory over the owner's node set — correct
at hundreds of nodes, a Vector Search migration at tens of thousands.

## IAM

Runtime identity: `socraitia-backend@PROJECT.iam.gserviceaccount.com`.
Roles and rationale live in `infra/iam_setup.sh`. Reproduce them from that
script, do not grant them by hand and forget.
