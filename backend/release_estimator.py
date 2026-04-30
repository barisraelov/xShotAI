"""
xShot AI — ReleaseEstimator (production integration, bounded per-shot inference)

Implements the validated Clip-1 release-step logic:
  1) Start at up_frame.
  2) Backward in steps of 25 until first ball-in/overlap-shooter-bbox contact.
  3) From that frame, forward in steps of 5.
  4) First forward frame (j>0) with no contact is release frame.

This estimator is designed to be injected into OriginEstimator and returns:
  {"u": int, "v": int, "frame_index": int}
or None when unresolved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2


class ReleaseEstimator:
    def __init__(
        self,
        ball_model_path: str | Path = "best.pt",
        person_model_path: str | Path = "yolov8n.pt",
        ball_conf_min: float = 0.30,
        person_conf_min: float = 0.25,
        backward_step: int = 25,
        forward_step: int = 5,
        backward_max_delta: int = 200,
        forward_post_up_cap: int = 5,
    ) -> None:
        self._ball_model_path = Path(ball_model_path)
        self._person_model_path = Path(person_model_path)
        self._ball_conf_min = float(ball_conf_min)
        self._person_conf_min = float(person_conf_min)
        self._backward_step = int(backward_step)
        self._forward_step = int(forward_step)
        self._backward_max_delta = int(backward_max_delta)
        self._forward_post_up_cap = int(forward_post_up_cap)
        self._ball_model = None
        self._person_model = None

    def _ensure_models(self):
        if self._ball_model is not None and self._person_model is not None:
            return
        from ultralytics import YOLO

        if not self._ball_model_path.exists():
            raise RuntimeError(f"Ball model not found: {self._ball_model_path}")
        if not self._person_model_path.exists():
            raise RuntimeError(f"Person model not found: {self._person_model_path}")
        self._ball_model = YOLO(str(self._ball_model_path))
        self._person_model = YOLO(str(self._person_model_path))

    @staticmethod
    def _bbox_center(box: list[float]) -> tuple[float, float]:
        x1, y1, x2, y2 = box
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @staticmethod
    def _point_in_box(pt: tuple[float, float], box: list[float]) -> bool:
        x, y = pt
        x1, y1, x2, y2 = box
        return x1 <= x <= x2 and y1 <= y <= y2

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        bb = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        den = aa + bb - inter
        return inter / den if den > 0 else 0.0

    @staticmethod
    def _dist_point_to_rect(pt: tuple[float, float], box: list[float]) -> float:
        x, y = pt
        x1, y1, x2, y2 = box
        dx = max(x1 - x, 0.0, x - x2)
        dy = max(y1 - y, 0.0, y - y2)
        return float((dx * dx + dy * dy) ** 0.5)

    def _detect_ball_and_person(self, frame):
        ball_boxes = []
        bres = self._ball_model(frame, verbose=False)
        if bres and bres[0].boxes is not None:
            boxes = bres[0].boxes
            xyxy = boxes.xyxy.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            conf = boxes.conf.cpu().numpy()
            for bb, c, cf in zip(xyxy, cls, conf):
                if c == 0 and float(cf) >= self._ball_conf_min:
                    ball_boxes.append(([float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])], float(cf)))

        person_boxes = []
        pres = self._person_model(frame, verbose=False)
        if pres and pres[0].boxes is not None:
            boxes = pres[0].boxes
            xyxy = boxes.xyxy.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            conf = boxes.conf.cpu().numpy()
            for pb, c, cf in zip(xyxy, cls, conf):
                if c == 0 and float(cf) >= self._person_conf_min:
                    person_boxes.append(([float(pb[0]), float(pb[1]), float(pb[2]), float(pb[3])], float(cf)))
        return ball_boxes, person_boxes

    def _is_contact(self, frame) -> tuple[bool, Optional[list[float]]]:
        balls, persons = self._detect_ball_and_person(frame)
        if not balls or not persons:
            return False, None

        best = None
        for bb, _ in balls:
            bc = self._bbox_center(bb)
            for pb, _ in persons:
                d = self._dist_point_to_rect(bc, pb)
                if best is None or d < best[0]:
                    best = (d, bb, pb)

        _, bb, pb = best
        bc = self._bbox_center(bb)
        inside = self._point_in_box(bc, pb)
        overlap = self._iou(bb, pb) > 0.0
        return bool(inside or overlap), bb

    def estimate(self, shot_event: dict) -> dict | None:
        video_path = shot_event.get("_video_path")
        up_frame = int(shot_event.get("up_frame", -1))
        if not video_path or up_frame < 0:
            return None

        self._ensure_models()
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        backward_cap = max(0, up_frame - self._backward_max_delta)
        contact_frame = None

        k = 0
        while True:
            fi = up_frame - (k * self._backward_step)
            if fi < 0:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if not ok:
                break
            contact, _ = self._is_contact(frame)
            if contact:
                contact_frame = int(fi)
                break
            if fi <= backward_cap:
                break
            k += 1

        if contact_frame is None:
            cap.release()
            return None

        forward_cap = min(total_frames - 1, up_frame + self._forward_post_up_cap)
        release_frame = None
        release_ball_box = None
        j = 0
        while True:
            fi = contact_frame + (j * self._forward_step)
            if fi > forward_cap:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if not ok:
                break
            contact, bb = self._is_contact(frame)
            if j > 0 and not contact:
                release_frame = int(fi)
                release_ball_box = bb
                break
            j += 1

        cap.release()
        if release_frame is None:
            return None

        # Use detected ball center on release frame when available.
        if release_ball_box is not None:
            cx, cy = self._bbox_center(release_ball_box)
            return {"u": int(cx), "v": int(cy), "frame_index": int(release_frame)}

        # Conservative fallback: use earliest ball point in shot window nearest to release frame.
        points = shot_event.get("ball_points_window", []) or []
        if points:
            nearest = min(points, key=lambda p: abs(int(p[2]) - release_frame))
            return {"u": int(nearest[0]), "v": int(nearest[1]), "frame_index": int(release_frame)}
        return None

