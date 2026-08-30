"""Agent logging.

The logs are part of the demo: judges reward unedited live execution, so every
agent action prints one dense, aligned, human-readable line that reads well on
camera and still lands in Cloud Logging as-is.

    21:04:07  [CARTOGRAPHER]     exchange#7 -> +3 nodes (2 claim, 1 gap), +2 edges
    21:04:09  [VERIFIER:async]   claim#a41 -> 2 sources, 1 TENSION vs claim#b12
"""

from __future__ import annotations

import logging
import sys

_LABEL_WIDTH = 18

_logger = logging.getLogger("socraitia")


# Libraries that log one or more INFO lines per model call. Left at INFO they
# emit ~6 lines of SDK chatter per turn, which makes the agent lines unreadable
# on camera. Warnings and errors still come through.
_MUTED = (
    "google",
    "google_adk",
    "google_genai",
    "grpc",
    "urllib3",
    "uvicorn.access",
)

# google-genai warns on every streamed call that automatic function calling is
# better used via AsyncChat. It does not apply to us — ADK drives the model
# directly and our agents declare their tools explicitly — and it fires once per
# turn, so it is dropped by substring rather than by muting real warnings.
_DROP_SUBSTRINGS = ("automatic function calling",)


class _NoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(s in message for s in _DROP_SUBSTRINGS)


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    handler.addFilter(_NoiseFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in _MUTED:
        logging.getLogger(name).setLevel(logging.WARNING)


def agent_log(agent: str, message: str, *, level: int = logging.INFO) -> str:
    """Emit one agent line and return it, so callers can also stream it to the UI."""
    label = f"[{agent}]".ljust(_LABEL_WIDTH)
    _logger.log(level, "%s %s", label, message)
    return f"[{agent}] {message}"
