"""Skip-Location-shaped shot_points for Live (LIVE-03 / LIVE-24)."""

from __future__ import annotations

from typing import Any, Optional

import cv_pipeline
from single_pass_pipeline import _origin_from_event


def shot_point_from_event(ev: dict, *, degraded: bool = False) -> dict:
    origin_pixel = _origin_from_event(ev)
    hs = ev.get("hoop_stable")
    apex_v = ev.get("v")
    arc_px = cv_pipeline._arc_height_from_hoop_and_apex(hs, apex_v)
    point = {
        "shot_id": ev["shot_id"],
        "result": ev["result"],
        "origin": {"pixel": origin_pixel, "court": None},
        "zone": None,
        "trajectory": {
            "arc_height_px": arc_px,
            "apex_pixel": {
                "u": ev.get("u"),
                "v": ev.get("v"),
                "frame_index": ev.get("frame_index"),
            },
            "up_frame": ev.get("up_frame"),
            "down_frame": ev.get("down_frame"),
        },
    }
    if degraded:
        point["degraded"] = True
    return point


def shot_point_from_decided(engine: Any, shot: Any, *, degraded: bool = False) -> dict:
    shot_id = getattr(shot, "shot_id", None)
    events = getattr(engine, "shot_events", None) or []
    ev: Optional[dict] = next((e for e in events if e.get("shot_id") == shot_id), None)
    if ev is not None:
        return shot_point_from_event(ev, degraded=degraded)
    point = {
        "shot_id": shot_id,
        "result": getattr(shot, "result", None),
        "origin": {"pixel": None, "court": None},
        "zone": None,
        "trajectory": {
            "arc_height_px": None,
            "apex_pixel": {
                "u": None,
                "v": None,
                "frame_index": getattr(shot, "decision_frame", None),
            },
            "up_frame": None,
            "down_frame": None,
        },
    }
    if degraded:
        point["degraded"] = True
    return point
