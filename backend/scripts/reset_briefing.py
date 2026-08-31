"""Rewind the briefing watermark so the arrival state can be shown again.

The briefing advances `last_seen_at` only when the user dismisses it, which is
correct behaviour and inconvenient for a demo: once you have entered the map,
the honest answer to "what happened while you were away" is "nothing". This
clears the watermark for the demo user so the next project entry briefs again.

    python -m scripts.reset_briefing            # every project
    python -m scripts.reset_briefing ai-in-education
"""

from __future__ import annotations

import asyncio
import sys

from app import config
from app.graph.repo import db


async def main(project_ids: list[str]) -> None:
    ref = db().collection("users").document(config.DEMO_UID)
    snap = await ref.get()
    if not snap.exists:
        print("no user doc — nothing to clear")
        return

    seen = (snap.to_dict() or {}).get("last_seen_at") or {}
    if project_ids:
        for pid in project_ids:
            seen.pop(pid, None)
    else:
        seen = {}

    # `update` replaces the map wholesale; a merged `set` would resurrect the
    # keys we just removed.
    await ref.update({"last_seen_at": seen})
    print(f"cleared: {', '.join(project_ids) or 'every project'}")
    print(f"remaining watermarks: {seen}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
