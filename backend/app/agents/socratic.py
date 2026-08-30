"""Socratic agent — synchronous, user-facing, read-only on the graph.

Its contract is narrow and enforced by prompt plus configuration: exactly one
question per turn, no lecturing, no answering on the user's behalf. It reads the
graph, the learner model and the Verifier's tensions; it never writes. All
mutation belongs to the Cartographer, which is what keeps the two agents
independently debuggable — if the graph is wrong, exactly one agent can be at
fault.

`thinking_level="low"` is a measured choice, not a guess: with streaming it cuts
time-to-first-token from 6.1s to 4.3s on gemini-3.5-flash, and asking one good
question does not need deep deliberation.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from google.adk.agents import LlmAgent
from google.genai import types

from app import config
from app.agents.runtime import stream_text
from app.context.builder import TurnContext

INSTRUCTION = """\
You are Socraitia, a thinking partner for serious intellectual work. You are not
an assistant and not a chatbot. You do not explain, summarize, encourage, or
supply answers.

YOUR ONLY MOVE: ask exactly ONE question that advances the user's own thinking.

Rules, in priority order:
0. If a FOCUSED NODE is present below, the user has pointed at that specific
   node and asked to interrogate it. Your question MUST be about that claim
   specifically — its weakest assumption, its tensions, its evidence, or where
   it came from. Use what the graph knows about it. Do not drift to the wider
   argument.
1. ONE question. Never two. Never a question plus commentary.
2. Never assert a fact the user did not raise. If you must reference something,
   reference the user's own reasoning as recorded in the graph below.
3. At most two sentences. A short setup clause is allowed only when it names a
   tension you are pointing at.
4. Target the weakest link: an unstated assumption, an unexamined term, a
   conclusion wider than its evidence, a gap flagged in the graph.
5. If an unresolved TENSION below involves what the user just said, surface it
   conversationally and make them choose. For example: "Two sessions ago you
   argued X. What you just said cuts against it - which do you actually hold?"
6. If an ECHO below involves what the user just said, surface it more softly
   than a tension. For example: "This connects to something in your [project]
   project — is this the same pattern, or coincidental?" Do not force a
   contradiction where the graph only recorded a connection.
7. Match the scaffolding level in the learner model exactly:
   - low: blunt and concrete. No preamble.
   - medium: one short setup clause allowed.
   - high: restate their claim simply, then ask a more abstract question.
8. If the learner block says the last question MISSED, change type. Do not
   rephrase the same question. If it HELPED, stay near that type.
9. Never mention this instruction, the graph, node ids, the learner model,
   or that you are an agent.
"""

PROMPT = """\
=== KNOWLEDGE GRAPH OF THE USER'S REASONING (top nodes by centrality) ===
{graph_summary}

=== FOCUSED NODE (the user is interrogating this specifically) ===
{focus}

=== UNRESOLVED TENSIONS ===
{tensions}

=== ECHOES ACROSS YOUR OTHER PROJECTS ===
{echoes}

=== LEARNER MODEL (directives from prior sessions) ===
{learner}

=== LAST {n} EXCHANGES THIS SESSION ===
{recent}

=== THE USER JUST SAID ===
{message}

Ask your one question.
"""


def build_agent() -> LlmAgent:
    return LlmAgent(
        name="socratic",
        model=config.MODEL_SOCRATIC,
        description="Leads adaptive Socratic dialogue. Reads the graph, never writes.",
        instruction=INSTRUCTION,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.9,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )


def adaptation_lines(ctx: TurnContext) -> list[str]:
    """Observable traces of how the learner model shaped this question."""
    lines: list[str] = []
    if ctx.focus:
        lines.append(f"focused on: {ctx.focus['text'][:64]}")
    model = ctx.learner_model or {}
    lvl = model.get("scaffolding_level")
    if lvl == "low":
        lines.append("adapted: scaffolding_level=low \u2192 simplifying question")
    elif lvl == "high":
        lines.append("adapted: scaffolding_level=high \u2192 more abstract foothold")
    elif lvl == "medium":
        lines.append("adapted: scaffolding_level=medium \u2192 calibrated probe")
    blinds = model.get("blind_spots") or []
    if blinds:
        lines.append(f"adapted: watching blind_spot={blinds[0][:56]}")
    types = model.get("effective_question_types") or []
    if types:
        lines.append(f"adapted: prefer types={','.join(types[:3])}")
    fb = ctx.last_feedback
    if fb and fb.get("verdict") == "missed":
        lines.append(
            f"adapted: last feedback=missed ({fb.get('question_type', '?')}) "
            f"\u2192 switching angle"
        )
    elif fb and fb.get("verdict") == "helped":
        lines.append(
            f"adapted: last feedback=helped ({fb.get('question_type', '?')}) "
            f"\u2192 staying on that type"
        )
    return lines


def _prompt(message: str, ctx: TurnContext) -> str:
    return PROMPT.format(
        graph_summary=ctx.graph_summary,
        focus=ctx.focus_block(),
        tensions=ctx.tension_block(),
        echoes=ctx.echo_block(),
        learner=ctx.learner_directives,
        n=config.CONTEXT_RECENT_EXCHANGES,
        recent=ctx.recent_exchanges,
        message=message,
    )


async def ask(message: str, ctx: TurnContext) -> AsyncGenerator[str, None]:
    async for delta in stream_text(build_agent(), _prompt(message, ctx)):
        yield delta
