"""Modeler — one structured Gemini call that evolves the learner model.

Not a new agent architecture. Same ADK output_schema pattern as the
Cartographer. Triggered after every N dialogue exchanges and on explicit
session end. Merges into users/{uid}.learner_model; it never resets it.
"""

from __future__ import annotations

import json
import logging

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import ValidationError

from app import config
from app.agents.runtime import complete_text
from app.logging_setup import agent_log
from app.schemas import LearnerModel

INSTRUCTION = """\
You maintain a compact model of HOW this person thinks, not what they believe.
You never address the user. Emit only the schema.

Rules:
- Evolve the current model. Do not wipe it and start over.
- reasoning_style: one or two sentences about how they construct arguments.
- blind_spots: recurring patterns, not one-off gaps. Max 4. Keep ones still
  visible; drop ones they have clearly corrected.
- effective_question_types: types that actually land. MUST reflect the
  feedback tally — a type with more "missed" than "helped" must not appear
  here. Prefer types with helped > missed.
- scaffolding_level:
    low    = they handle blunt, concrete probes; stop padding
    medium = short setup clause is useful
    high   = they need a foothold / restatement before the question
  If they mark abstract questions missed and concrete ones helped, go low.
  The reverse, go high.
"""

PROMPT = """\
=== CURRENT LEARNER MODEL (evolve this, do not reset) ===
{current}

=== FEEDBACK TALLY ACROSS SESSIONS (real signal — obey it) ===
{tally}

=== THIS SESSION TRANSCRIPT ===
{transcript}

=== STRUCTURE THIS SESSION ADDED ===
{diffs}

=== FEEDBACK ON THIS SESSION'S QUESTIONS ===
{feedback}

Emit the evolved learner model.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="modeler",
        model=config.MODEL_MODELER,
        description="Evolves the cross-session learner model from transcript and feedback.",
        instruction=INSTRUCTION,
        output_schema=LearnerModel,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=2048,
        ),
    )


_TYPE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "tension_choice",
        ("which do you", "which of these", "cuál", "cuts against", "two sessions"),
    ),
    (
        "assumption_probe",
        ("assum", "supuest", "taken for granted", "implied", "imply"),
    ),
    (
        "evidence_challenge",
        ("evidence", "evidencia", "how do you know", "cómo sabes", "what would count"),
    ),
    ("term_clarification", ("mean by", "define", "término", "what is ", "qué es ")),
    ("hypothetical", ("what if", "suppose", "if that", "si eso", "si la ")),
]


def classify_question(text: str) -> str:
    low = text.lower()
    for name, needles in _TYPE_HINTS:
        if any(n in low for n in needles):
            return name
    return "elaboration"


def _parse(raw: str) -> LearnerModel:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return LearnerModel.model_validate_json(text)


def merge_models(existing: dict, proposed: LearnerModel, tally: dict) -> dict:
    """Code-side merge so a sloppy modeler call cannot wipe real feedback signal."""
    missed_heavy = {
        qtype
        for qtype, counts in tally.items()
        if (counts.get("missed") or 0) > (counts.get("helped") or 0)
    }
    from_tally = [
        qtype
        for qtype, counts in tally.items()
        if (counts.get("helped") or 0) > (counts.get("missed") or 0)
    ]
    types: list[str] = []
    for qtype in (
        list(proposed.effective_question_types)
        + from_tally
        + list(existing.get("effective_question_types") or [])
    ):
        key = (qtype or "").strip()
        if not key or key in missed_heavy or key in types:
            continue
        types.append(key)

    blinds: list[str] = []
    for spot in list(proposed.blind_spots) + list(existing.get("blind_spots") or []):
        key = (spot or "").strip()
        if not key or key in blinds:
            continue
        blinds.append(key)

    style = (proposed.reasoning_style or "").strip() or existing.get("reasoning_style") or ""
    return {
        "reasoning_style": style,
        "blind_spots": blinds[:4],
        "effective_question_types": types[:6],
        "scaffolding_level": proposed.scaffolding_level or existing.get("scaffolding_level") or "medium",
        "session_count": int(existing.get("session_count") or 0) + 1,
    }


def _fmt_tally(tally: dict) -> str:
    if not tally:
        return "(no feedback yet)"
    lines = []
    for qtype, counts in sorted(tally.items()):
        lines.append(
            f"- {qtype}: {counts.get('helped', 0)} helped / {counts.get('missed', 0)} missed"
        )
    return "\n".join(lines)


def _fmt_transcript(entries: list[dict]) -> str:
    if not entries:
        return "(empty session)"
    lines = []
    for i, entry in enumerate(entries[-16:], 1):
        if entry.get("kind") == "note":
            lines.append(f"{i}. NOTE: {entry.get('user', '')}")
            continue
        lines.append(f"{i}. USER: {entry.get('user', '')}")
        if entry.get("partner"):
            lines.append(f"   YOU: {entry.get('partner')}")
    return "\n".join(lines)


def _fmt_diffs(entries: list[dict]) -> str:
    nodes, edges = 0, 0
    for entry in entries:
        diff = entry.get("diff") or {}
        nodes += len(diff.get("nodes") or [])
        edges += len(diff.get("edges") or [])
    return f"{nodes} nodes, {edges} edges added this session"


def _fmt_feedback(rows: list[dict]) -> str:
    if not rows:
        return "(no question feedback this session)"
    return "\n".join(
        f"- [{r.get('verdict')}] ({r.get('question_type', '?')}) {r.get('question', '')[:160]}"
        for r in rows
    )


def describe_change(before: dict, after: dict) -> str:
    bits = [
        f"scaffolding={after.get('scaffolding_level', '?')}",
        f"style={(after.get('reasoning_style') or '—')[:48]}",
    ]
    new_blinds = [
        b for b in (after.get("blind_spots") or []) if b not in (before.get("blind_spots") or [])
    ]
    if new_blinds:
        bits.append(f"+blind_spot={new_blinds[0][:40]}")
    types = after.get("effective_question_types") or []
    if types:
        bits.append(f"types={','.join(types[:3])}")
    return ", ".join(bits)


async def evolve(
    *,
    existing: dict,
    tally: dict,
    transcript: list[dict],
    feedback: list[dict],
) -> LearnerModel:
    current = json.dumps(existing, ensure_ascii=False) if existing else "(none — first model)"
    raw = await complete_text(
        build_agent(),
        PROMPT.format(
            current=current,
            tally=_fmt_tally(tally),
            transcript=_fmt_transcript(transcript),
            diffs=_fmt_diffs(transcript),
            feedback=_fmt_feedback(feedback),
        ),
    )
    try:
        return _parse(raw)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        agent_log(
            "MODELER",
            f"malformed output ({type(exc).__name__}) \u2014 keeping prior model",
            level=logging.WARNING,
        )
        return LearnerModel(
            reasoning_style=existing.get("reasoning_style") or "",
            blind_spots=list(existing.get("blind_spots") or []),
            effective_question_types=list(existing.get("effective_question_types") or []),
            scaffolding_level=existing.get("scaffolding_level") or "medium",
        )
