"""Atomic JPEG + JSON header packing for Live WebSocket frames (LIVE-05 / LIVE-09)."""

from __future__ import annotations

import json
import struct
from typing import Any

from live_constants import FRAME_MAGIC, PROTOCOL_VERSION

HEADER_FIELDS = (
    "protocol_version",
    "live_session_id",
    "frame_id",
    "capture_timestamp_monotonic_ms",
    "width",
    "height",
    "jpeg_quality",
)


class FrameProtocolError(ValueError):
    pass


def pack_frame(header: dict[str, Any], jpeg: bytes) -> bytes:
    body = json.dumps(header, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(body) > 0xFFFF:
        raise FrameProtocolError("header too large")
    return FRAME_MAGIC + struct.pack(">H", len(body)) + body + jpeg


def unpack_frame(message: bytes) -> tuple[dict[str, Any], bytes]:
    if len(message) < 6:
        raise FrameProtocolError("frame too short")
    if message[:4] != FRAME_MAGIC:
        raise FrameProtocolError("bad magic")
    header_len = struct.unpack(">H", message[4:6])[0]
    start = 6
    end = start + header_len
    if end > len(message):
        raise FrameProtocolError("truncated header")
    try:
        header = json.loads(message[start:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameProtocolError("invalid header json") from exc
    if not isinstance(header, dict):
        raise FrameProtocolError("header must be an object")
    jpeg = message[end:]
    return header, jpeg


def validate_header(header: dict[str, Any]) -> None:
    for key in HEADER_FIELDS:
        if key not in header:
            raise FrameProtocolError(f"missing {key}")
    if int(header["protocol_version"]) != PROTOCOL_VERSION:
        raise FrameProtocolError("unsupported protocol_version")
    if int(header["frame_id"]) < 0:
        raise FrameProtocolError("frame_id must be >= 0")
