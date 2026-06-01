"""Ball-person contact checks every N frames during main loop (no video reopen)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import cv_pipeline
from inference_reuse import record_contact_yolo
from runtime_config import CONTACT_CHECK_EVERY


class ContactSampler:
    def __init__(self, backend_dir: Path) -> None:
        self._ball_model: Any = None
        self._person_model: Any = None
        self._ball_path = backend_dir / cv_pipeline.YOLO_MODEL_PATH
        self._person_path = backend_dir / "yolov8n.pt"
        self.last_contact_frame: Optional[int] = None
        self.check_count: int = 0
        self.check_sec: float = 0.0
        self._ball_by_frame: dict[int, tuple[float, float, float, float, float, float]] = {}
        self._re_logic: Any = None

    def _ensure_models(self) -> None:
        if self._ball_model is not None:
            return
        from release_estimator import ReleaseEstimator

        self._re_logic = ReleaseEstimator(
            ball_model_path=self._ball_path,
            person_model_path=self._person_path,
        )
        self._re_logic._ensure_models()
        self._ball_model = self._re_logic._ball_model
        self._person_model = self._re_logic._person_model

    def should_check(self, frame_idx: int, in_cooldown: bool) -> bool:
        return not in_cooldown and frame_idx % CONTACT_CHECK_EVERY == 0

    def check_frame(self, frame_idx: int, frame_bgr: Any) -> bool:
        self._ensure_models()
        t0 = time.perf_counter()
        contact, ball_box = self._re_logic._is_contact(frame_bgr)
        record_contact_yolo(2)
        self.check_sec += time.perf_counter() - t0
        self.check_count += 1
        if contact:
            self.last_contact_frame = frame_idx
        if ball_box is not None:
            cx, cy = self._re_logic._bbox_center(ball_box)
            w = ball_box[2] - ball_box[0]
            h = ball_box[3] - ball_box[1]
            self._ball_by_frame[frame_idx] = (cx, cy, frame_idx, w, h, 1.0)
        return contact

    def store_ball_detection(
        self, frame_idx: int, cx: float, cy: float, w: float, h: float, conf: float,
    ) -> None:
        self._ball_by_frame[frame_idx] = (cx, cy, frame_idx, w, h, conf)

    def ball_at_frame(self, frame_idx: int) -> Optional[tuple]:
        if frame_idx in self._ball_by_frame:
            return self._ball_by_frame[frame_idx]
        candidates = [f for f in self._ball_by_frame if f <= frame_idx]
        if not candidates:
            return None
        nearest = max(candidates)
        return self._ball_by_frame[nearest]
