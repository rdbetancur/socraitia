# Verification log

Google model identifiers and their regional availability rotate on the order of
weeks. Every claim below was checked against the live API from project
`socraitia`, not taken from documentation or from model memory.
`scripts/verify_stack.sh` re-runs the whole check in about 15 seconds.

## 2026-08-29 — Phase 1

### Models

| Model | Identifier | Endpoint | Result |
| --- | --- | --- | --- |
| Gemini 3.5 Flash | `gemini-3.5-flash` | `global` | HTTP 200 |
| Gemini 3.5 Flash | `gemini-3.5-flash` | `us-central1` | **HTTP 404** |
| Gemini 3.7 Flash | `gemini-3.7-flash` | `global` | HTTP 200 |
| Gemini 3.1 Pro preview | `gemini-3.1-pro-preview` | `global` | HTTP 200 |
| Multimodal embeddings | `gemini-embedding-2` | `global` | HTTP 200, 3072-d, truncatable |
| Multimodal embeddings | `gemini-embedding-2` | `us-central1` | **HTTP 404** |
| Text embeddings | `gemini-embedding-001` | `us-central1` | HTTP 200 |
| Veo | `veo-3.1-fast-generate-001` | `us-central1` | HTTP 200, 4s video produced in ~30s |
| Google Search grounding | `tools:[{googleSearch:{}}]` | `global` | HTTP 200 with real citations |
| Gemma 3 | `publishers/google/models/gemma3` | `us-central1` | HTTP 200, default version `gemma-3-1b-it` |

**The region split is forced, not chosen.** Gemini 3.x exists only on the
`global` endpoint and the `us`/`eu` multi-regions. Veo exists only on
`us-central1`. Firestore `socraitia` is in `us-central1`. Every identifier and
region therefore lives in `backend/app/config.py` and nowhere else.

Note: Vertex AI has been renamed "Gemini Enterprise Agent Platform" in Google's
documentation. The API hosts and surfaces are unchanged
(`aiplatform.googleapis.com`), so this affects docs links only.

### SDKs

Verified by installing into a clean virtualenv on **Python 3.14.7** and
importing, not from PyPI metadata:

| Package | Version |
| --- | --- |
| `google-adk` | 2.8.0 |
| `google-genai` | 2.20.0 |
| `google-cloud-firestore` | 2.29.0 |
| `google-cloud-pubsub` | 2.39.2 |
| `google-cloud-storage` | 3.13.1 |

Python 3.14 works; no downgrade to 3.12 is needed. `cryptography` and `watchdog`
compile wheels from source on macOS on first install (~4 minutes, then cached).

ADK 2.8 API surface, read from the installed package because the public docs
still show the 1.x signatures, which no longer run:

```python
Runner(app_name=..., agent=..., session_service=...)      # keyword-only
Runner.run_async(*, user_id, session_id, new_message)     # keyword-only
await InMemorySessionService().create_session(...)        # async
RunConfig(streaming_mode=StreamingMode.SSE)               # for token streaming
LlmAgent.DEFAULT_MODEL == "gemini-3.5-flash"
```

### Latency, measured

| Configuration | Time to first token | Total |
| --- | --- | --- |
| `gemini-3.5-flash`, non-streaming | — | 6.2s |
| streaming, `thinking_level: high` | 6.06s | 6.24s |
| streaming, `thinking_level: low` | **4.31s** | 4.55s |

`thinking_level` makes no difference without streaming (6.2s vs 6.3s), so the
Socratic agent uses `low` **plus** streaming, which is where the gain is.

Observed full-turn latency in the running system: 11–29s, with the question
readable at 5–7s and the graph diff landing at 10–17s. The Cartographer is the
tail, which is why it runs concurrently with the Socratic agent rather than
after it.
