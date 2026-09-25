"""'[AI-GARMENT] ...' logging.

Messages go to the standard ``logging`` logger ``ai_garment`` (printed to the
Blender system console / stdout) and, when a Result is passed, into
``result.logs`` so Claude sees them in structured output.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Optional

PREFIX = "[AI-GARMENT]"
LOGGER = logging.getLogger("ai_garment")

if not LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def format_event(label: str, value: Any = None) -> str:
    return f"{PREFIX} {label}: {value}" if value is not None else f"{PREFIX} {label}"


def log_event(label: str, value: Any = None, result: Optional[Any] = None, level: int = logging.INFO) -> str:
    msg = format_event(label, value)
    LOGGER.log(level, msg)
    if result is not None:
        result.log(msg)
    return msg


def set_verbose(enabled: bool) -> None:
    LOGGER.setLevel(logging.INFO if enabled else logging.WARNING)
