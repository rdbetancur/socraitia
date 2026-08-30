"""Shared ADK runtime: timeouts, backoff, and streaming.

Every agent call in Socraitia goes through here, which is what makes the failure
tolerance claim in the README true of the whole system rather than of whichever
call site remembered to handle it.

One design note worth reading: each invocation gets a fresh in-memory ADK
session. That looks wasteful and is intentional — we never let ADK accumulate
conversation history, because our context strategy is to construct the prompt
ourselves from a graph summary plus the last N exchanges plus the learner model.
Letting ADK also replay history would double-feed the model and make the context
window grow without bound, which is precisely what we claim not to do.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app import config
from app.logging_setup import agent_log

APP_NAME = "socraitia"


class AgentCallError(RuntimeError):
    pass


async def _events(
    agent: LlmAgent, prompt: str, *, streaming: bool
) -> AsyncGenerator[types.Content, None]:
    service = InMemorySessionService()
    session = await service.create_session(app_name=APP_NAME, user_id=config.DEMO_UID)
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=service)
    run_config = RunConfig(
        streaming_mode=StreamingMode.SSE if streaming else StreamingMode.NONE
    )
    try:
        async for event in runner.run_async(
            user_id=config.DEMO_UID,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
            run_config=run_config,
        ):
            yield event
    finally:
        close = getattr(runner, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001 - teardown must not mask a real error
                pass


def _text_of(event) -> str:
    content = getattr(event, "content", None)
    if not content or not getattr(content, "parts", None):
        return ""
    # Skip thought parts: they are the model's reasoning, not its answer.
    return "".join(
        p.text for p in content.parts if getattr(p, "text", None) and not getattr(p, "thought", False)
    )


async def stream_text(
    agent: LlmAgent, prompt: str, *, timeout: float | None = None
) -> AsyncGenerator[str, None]:
    """Yield response deltas as they arrive.

    ADK emits incremental `partial` events followed by one aggregated final
    event. Yielding both would duplicate the whole answer, so the final event is
    only used when nothing was streamed (which happens when the model returns
    the response in a single chunk).
    """
    timeout = timeout or config.AGENT_TIMEOUT_S
    streamed = False
    try:
        async with asyncio.timeout(timeout):
            async for event in _events(agent, prompt, streaming=True):
                text = _text_of(event)
                if not text:
                    continue
                if getattr(event, "partial", False):
                    streamed = True
                    yield text
                elif not streamed:
                    yield text
                    streamed = True
    except TimeoutError as exc:
        agent_log(
            agent.name.upper(),
            f"timed out after {timeout:.0f}s",
            level=logging.ERROR,
        )
        if not streamed:
            raise AgentCallError(f"{agent.name} timed out after {timeout:.0f}s") from exc


async def complete_text(
    agent: LlmAgent,
    prompt: str,
    *,
    timeout: float | None = None,
    attempts: int | None = None,
) -> str:
    """Run an agent to completion with exponential backoff between attempts."""
    timeout = timeout or config.AGENT_TIMEOUT_S
    attempts = attempts or config.AGENT_RETRY_ATTEMPTS
    last: Exception | None = None

    for attempt in range(attempts):
        try:
            async with asyncio.timeout(timeout):
                chunks = [
                    _text_of(event) async for event in _events(agent, prompt, streaming=False)
                ]
            text = "".join(chunks).strip()
            if text:
                return text
            last = AgentCallError(f"{agent.name} returned empty output")
        except Exception as exc:  # noqa: BLE001 - includes TimeoutError
            last = exc

        if attempt < attempts - 1:
            delay = config.AGENT_RETRY_BASE_DELAY_S * (2**attempt)
            agent_log(
                agent.name.upper(),
                f"attempt {attempt + 1}/{attempts} failed ({type(last).__name__}) "
                f"\u2192 retrying in {delay:.1f}s",
                level=logging.WARNING,
            )
            await asyncio.sleep(delay)

    raise AgentCallError(f"{agent.name} failed after {attempts} attempts: {last}")
