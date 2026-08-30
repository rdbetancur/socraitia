"""Verifier agent — async, writes evidence and intra-project tensions.

Two jobs, deliberately split into two model calls because ADK will not let
`output_schema` coexist with tools:

  1. Gemini + Google Search grounding, free-form then parsed
  2. a schema-constrained polarity check against a similar prior claim
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.tools import google_search
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app import config
from app.agents.runtime import complete_text
from app.logging_setup import agent_log
from app.schemas import ExtractedEdge, ExtractedNode, GraphDiff

GROUND_INSTRUCTION = """\
You verify a single claim against the external world using Google Search.
You are not in the conversation. You never address the user.

Return ONLY a JSON object of this shape:
{"findings":[{"text":"...","relation":"supports|contradicts"}]}

Rules:
- 0 to 2 findings. Prefer one strong source over three weak ones.
- `text` is a self-contained evidence statement, not a URL dump. Name the
  source in the sentence when you can ("A 2014 meta-analysis of ITS...").
- `relation` is supports if the source backs the claim, contradicts if it
  cuts against it.
- If search finds nothing usable, return {"findings":[]}. Do not invent studies.
"""

GROUND_PROMPT = """\
CLAIM TO VERIFY:
{claim}

Search, then emit the JSON object.
"""


class Finding(BaseModel):
    text: str
    relation: Literal["supports", "contradicts"]


class Findings(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class Polarity(BaseModel):
    relation: Literal["same", "refines", "contradicts", "unrelated"]


def _ground_agent() -> LlmAgent:
    return LlmAgent(
        name="verifier",
        model=config.MODEL_VERIFIER,
        description="Grounds a claim in external search evidence.",
        instruction=GROUND_INSTRUCTION,
        tools=[google_search],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=4096,
        ),
    )


def _polarity_agent() -> LlmAgent:
    return LlmAgent(
        name="verifier",
        model=config.MODEL_VERIFIER,
        description="Judges whether two claims contradict.",
        instruction=(
            "You compare two claims from the same thinker. "
            "Emit whether B contradicts A, refines it, restates it, or is unrelated. "
            "Contradicts only if they cannot both be held."
        ),
        output_schema=Polarity,
        generate_content_config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=1024),
    )


def _parse_findings(raw: str) -> Findings:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return Findings.model_validate_json(text)


async def gather_evidence(claim: str) -> Findings:
    raw = await complete_text(
        _ground_agent(),
        GROUND_PROMPT.format(claim=claim),
        timeout=config.VERIFIER_TIMEOUT_S,
        attempts=config.VERIFIER_RETRY_ATTEMPTS,
    )
    try:
        return _parse_findings(raw)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        agent_log(
            "VERIFIER:async",
            f"grounding parse failed ({type(exc).__name__}) \u2014 no evidence this pass",
            level=logging.WARNING,
        )
        return Findings()


async def polarity(a: str, b: str) -> str:
    raw = await complete_text(
        _polarity_agent(),
        f"CLAIM A: {a}\nCLAIM B: {b}\nDo they contradict?",
        timeout=20,
        attempts=1,
    )
    try:
        return Polarity.model_validate_json(raw.strip()).relation
    except Exception:  # noqa: BLE001
        return "unrelated"


def findings_to_diff(claim_text: str, findings: Findings) -> GraphDiff:
    nodes = [
        ExtractedNode(type="evidence", text=f.text)
        for f in findings.findings
        if f.text.strip()
    ]
    edges = [
        ExtractedEdge(from_text=f.text, to_text=claim_text, relation=f.relation)
        for f in findings.findings
        if f.text.strip()
    ]
    return GraphDiff(nodes=nodes, edges=edges)
