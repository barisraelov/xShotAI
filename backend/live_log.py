"""Structured Live diagnostic logs keyed by LIVE-XX trace codes."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("xshot.live")


def live_log(trace_code: str, event: str, **fields: Any) -> None:
    payload = {"trace_code": trace_code, "event": event, **fields}
    logger.info("%s", json.dumps(payload, ensure_ascii=False, default=str))
