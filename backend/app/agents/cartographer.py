"""Cartographer agent — synchronous, writes the graph.

This is the agent that makes Socraitia an agent rather than a chat loop: it does
not answer the user, it mutates a persistent artifact. It runs on every exchange,
extracts claims / concepts / questions / gaps and typed relations, and hands a
validated diff to the Firestore layer.

Two robustness details matter here. First, output is constrained by an ADK
`output_schema`, so the model returns a Vertex-enforced JSON shape rather than
prose we have to scrape. Second, when validation still fails, we retry exactly
once with the parse error fed back to the model, then give up and return an empty
diff — a bad extraction must cost one turn's worth of structure, never the turn
itself.
"""

from __future__ import annotations

import json
import logging

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import ValidationError

from app import config
from app.agents.runtime import complete_text
from app.context.builder import TurnContext
from app.logging_setup import agent_log
from app.schemas import GraphDiff

INSTRUCTION = """\
You are the Cartographer. You map the STRUCTURE of a person's reasoning. You are
not in the conversation and you never address the user.

Given an exchange, emit the graph diff it justifies.

Node types:
- claim: an assertion the user treats as true or is arguing for
- concept: a term or construct whose meaning is doing work in the argument
- question: an open question the user or partner has raised
- gap: a step the argument needs but does not supply (a missing warrant, an
  unstated assumption, a conclusion wider than its support)
- note: a fragmentary capture — a reminder, a pointer, a half-formed thought.
  Dialogue mode almost never emits this type.

Relation types: supports, contradicts, refines, questions, answers.

Hard rules:
1. Extract only what the exchange supports. Inventing structure is worse than
   extracting none. Zero to five nodes per exchange is normal.
2. Node text must be a self-contained proposition, understandable a month later
   with no surrounding conversation. Never "it", "this", "that approach".
3. Reuse the EXACT text of an existing node when the exchange restates it, so it
   merges instead of forking. Restating an existing node with new support means
   emitting the edge only.
4. Edge endpoints must be the exact text of a node that exists in the graph
   below or appears in your own `nodes` list. Edges to anything else are dropped.
5. Flag a `gap` whenever the user's conclusion outruns their stated reasoning.
   This is the most valuable thing you produce.
6. Do not create a node for the partner's question unless it opens a genuinely
   new line of inquiry.
"""

PROMPT = """\
=== EXISTING GRAPH (reuse this exact text to merge, do not restate it) ===
{graph_summary}

=== THE EXCHANGE TO MAP ===
USER: {message}
PARTNER'S PREVIOUS QUESTION: {previous_question}

Emit the graph diff.
"""

NOTE_INSTRUCTION = """\
You are the Cartographer in NOTE MODE. The user is pinning a fragment, not
advancing an argument. You never address the user.

Default type is `note`. That is the whole point of this path: a capture stays
a capture unless the text is already a self-contained proposition they are
endorsing as true.

Use `claim` only if the text asserts something as true in a complete sentence
(subject + predicate, no "remember to", no "possible:", no "check the").
Use `concept` only if the text is nothing but a named construct, with no
reminder or hedge around it.
Use `note` for reminders, pointers, hedges, half-formed thoughts, and
anything you would have to rewrite to make it a claim.

One node. Zero edges unless the note clearly names an existing graph node.
Do not invent a cleaner proposition than what they wrote.

Examples:
- "recordar revisar el paper de Bloom sobre mastery learning"
  → type=note, text kept as a reminder
- "posible riesgo: el engagement inicial no predice retención"
  → type=note (hedged, not asserted)
- "Bloom's 2-sigma finding: one-to-one tutoring outperforms classroom instruction"
  → type=claim (complete endorsed assertion)
- "mastery learning"
  → type=concept (bare construct)
"""

NOTE_PROMPT = """\
=== EXISTING GRAPH (reuse only if the note clearly refers to one of these) ===
{graph_summary}

=== QUICK NOTE ===
{message}

Emit one node. Default type is note.
"""

REPAIR = """\

Your previous response was rejected: {error}
Emit ONLY a JSON object matching the required schema. No prose, no code fences.
"""


def build_agent(*, mode: str = "dialogue") -> LlmAgent:
    return LlmAgent(
        name="cartographer",
        model=config.MODEL_CARTOGRAPHER,
        description="Extracts reasoning structure and mutates the knowledge graph.",
        instruction=NOTE_INSTRUCTION if mode == "note" else INSTRUCTION,
        output_schema=GraphDiff,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1 if mode == "note" else 0.2,
            max_output_tokens=4096,
        ),
    )


def _parse(raw: str) -> GraphDiff:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    return GraphDiff.model_validate_json(text)


async def extract(message: str, ctx: TurnContext, *, mode: str = "dialogue") -> GraphDiff:
    """Return a validated diff, or an empty diff if the model cannot produce one."""
    agent = build_agent(mode=mode)
    if mode == "note":
        prompt = NOTE_PROMPT.format(graph_summary=ctx.graph_summary, message=message)
    else:
        prompt = PROMPT.format(
            graph_summary=ctx.graph_summary,
            message=message,
            previous_question=ctx.last_partner_question or "(none, this opens the session)",
        )

    raw = await complete_text(agent, prompt)
    try:
        return _parse(raw)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        agent_log(
            "CARTOGRAPHER",
            f"malformed output \u2192 single repair retry ({type(exc).__name__})",
            level=logging.WARNING,
        )

    try:
        raw = await complete_text(agent, prompt + REPAIR.format(error="schema validation failed"))
        return _parse(raw)
    except Exception as exc:  # noqa: BLE001 - degrade to no structure, keep the turn
        agent_log(
            "CARTOGRAPHER",
            f"repair failed, emitting empty diff ({type(exc).__name__})",
            level=logging.ERROR,
        )
        return GraphDiff()
