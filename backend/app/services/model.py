"""Run one Modeler checkpoint and persist the merged learner model."""

from __future__ import annotations

from app import config
from app.agents import modeler
from app.graph import repo
from app.logging_setup import agent_log


async def checkpoint(project_id: str, session_id: str, *, reason: str) -> dict:
    session = await repo.load_session(project_id, session_id)
    transcript = session.get("transcript") or []
    dialogue_n = sum(1 for e in transcript if e.get("kind") != "note")
    already = int(session.get("modeled_through") or 0)
    existing = await repo.load_learner_model(config.DEMO_UID)
    if dialogue_n == 0:
        return {"status": "empty", "learner_model": existing}
    if dialogue_n <= already:
        return {"status": "noop", "learner_model": existing}

    tally = await repo.load_feedback_tally(config.DEMO_UID)
    proposed = await modeler.evolve(
        existing=existing,
        tally=tally,
        transcript=transcript,
        feedback=repo.feedback_rows(session),
    )
    merged = modeler.merge_models(existing, proposed, tally)
    saved = await repo.save_learner_model(config.DEMO_UID, merged)
    await repo.mark_modeled(project_id, session_id, dialogue_n)
    change = modeler.describe_change(existing, saved)
    line = agent_log("MODELER", f"{reason} \u2192 {change}")
    await repo.append_feed(project_id, "MODELER", line)
    return {
        "status": "ok",
        "learner_model": saved,
        "change": change,
        "line": line,
        "reason": reason,
    }
