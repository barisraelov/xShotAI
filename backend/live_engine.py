"""Shared YOLO + ShotSessionEngine factory for Live (LIVE-01 / LIVE-03)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Optional

import cv_pipeline
from shot_session_engine import ShotSessionEngine

_model_lock = threading.Lock()
_shared_model: Any = None


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
    frame_width: int = 1280,
) -> ShotSessionEngine:
    engine = ShotSessionEngine()
    engine.start(
        model=model if model is not None else get_shared_yolo_model(),
        frame_width=frame_width,
        total_frames=None,
        video_path=None,
        person_model=None,
        collect_weak_detections=False,
    )
    return engine


EngineFactory = Callable[[], Any]


def default_engine_factory() -> ShotSessionEngine:
    return make_live_engine()
