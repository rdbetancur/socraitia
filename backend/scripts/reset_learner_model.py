"""One-off: wipe users/demo-researcher learner state before Phase 6 seeding.

Deletes `learner_model` and `feedback_tally` on the demo uid. Does not touch
projects, sessions, or the graph.

  cd backend && .venv/bin/python scripts/reset_learner_model.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.cloud import firestore  # noqa: E402

from app import config  # noqa: E402
from app.graph import repo  # noqa: E402


async def main() -> None:
    uid = config.DEMO_UID
    ref = repo.db().collection("users").document(uid)
    snap = await ref.get()
    before = snap.to_dict() if snap.exists else None
    print(f"uid={uid} exists={snap.exists}")
    print("before:", json.dumps(before, default=str, ensure_ascii=False, indent=2))

    if not snap.exists:
        print("nothing to reset")
        return

    await ref.update(
        {
            "learner_model": firestore.DELETE_FIELD,
            "feedback_tally": firestore.DELETE_FIELD,
        }
    )
    after_snap = await ref.get()
    after = after_snap.to_dict() if after_snap.exists else None
    model = await repo.load_learner_model(uid)
    print("after:", json.dumps(after, default=str, ensure_ascii=False, indent=2))
    print("load_learner_model:", model or "(empty)")


if __name__ == "__main__":
    asyncio.run(main())
