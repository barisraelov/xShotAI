"""Shared YOLO + ShotSessionEngine factory for Live (LIVE-01 / LIVE-03 / LIVE-04)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import cv_pipeline
from shot_session_engine import ShotSessionEngine

_model_lock = threading.Lock()
_shared_model: Any = None

EngineFactory = Callable[[int], Any]


def get_shared_yolo_model() -> Any:
    global _shared_model
    with _model_lock:
        if _shared_model is None:
            from ultralytics import YOLO

            path = Path(__file__).parent / cv_pipeline.YOLO_MODEL_PATH
            _shared_model = YOLO(str(path))
        return _shared_model


def make_live_engine(
    *,
    model: Any = None,
    frame_width: int,
) -> ShotSessionEngine:
    """Start a Live engine with the decoded frame width — never a hard-coded 1280."""
    if int(frame_width) <= 0:
        raise ValueError("frame_width must be a positive pixel width")
    engine = ShotSessionEngine()
    engine.start(
        model=model if model is not None else get_shared_yolo_model(),
        frame_width=int(frame_width),
        total_frames=None,
        video_path=None,
        person_model=None,
        collect_weak_detections=False,
    )
    return engine


def default_engine_factory() -> EngineFactory:
    """Warm the shared YOLO weights; return a width→engine factory (LIVE-04)."""
    model = get_shared_yolo_model()

    def make(frame_width: int) -> ShotSessionEngine:
        return make_live_engine(model=model, frame_width=frame_width)

    return make
