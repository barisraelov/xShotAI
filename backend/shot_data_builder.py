"""
xShot AI — ShotData builder

Builds a shared data structure for each confirmed shot so that both the
make/miss scorer (entry_make_miss.score_shot) and the origin/zone estimator
(OriginEstimator + CourtMapper) share a single YOLO pass instead of running
separate inference passes on the same video frames.

Usage in cv_pipeline._run_pipeline_inner():
    shot_data = build_shot_data(
        video_path, model, ev, up_frame, down_frame, frame_count,
        frame_w, hoop_accepted_count,
    )
    is_made, detail = entry_make_miss.score_shot_from_data(shot_data)
    origin_pixel   = _origin_estimator.estimate_from_data(ev, shot_data)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2

import entry_make_miss


@dataclass
class ShotData:
    # Ball trajectory from up_frame to down_frame+50, built by entry_make_miss.
    trajectory: list[tuple[int, float, float]] = field(default_factory=list)
    # Raw selected diagnostic points (internal detail, same frame range).
    sel_points: list[dict] = field(default_factory=list)
    # Frame where the ball first entered the capture zone (hoop area).
    capture_trigger: Optional[int] = None
    # Status counts from trajectory building (REGULAR, RESCUE_005, etc.).
    status_counts: dict = field(default_factory=dict)
    # Geometry / entry-rule ingredients (cached for score_shot_from_data).
    hoop_tuple: Optional[tuple] = None
    f_end: int = 0
    y_blue: float = 0.0
    xb1: float = 0.0
    xb2: float = 0.0
    cap_rect: tuple = ()
    confirm_rect: tuple = ()
    # Person detection: (feet_u, feet_v) of largest detected person in
    # [up_frame-30, up_frame-3].  None when no person found or model absent.
    person_feet: Optional[tuple[int, int]] = None


def build_shot_data(
    video_path: str | Path,
    model: Any,
    ev: dict,
    up_frame: int,
    down_frame: int,
    frame_count: int,
    frame_w: int,
    hoop_accepted_count: int,
    person_model: Optional[Any] = None,
    next_up_frame: Optional[int] = None,
) -> ShotData:
    """
    Single-pass data builder for one confirmed shot.

    Runs build_continuous_trajectory (ball trajectory for make/miss) and
    optionally scans pre-shot frames for player feet detection.  Both results
    are packaged into a ShotData that can be consumed by score_shot_from_data()
    and by OriginEstimator without any additional YOLO inference.

    person_model: if provided (COCO yolov8n), scans [up_frame-30, up_frame-3]
                  for the largest person bounding box and stores feet pixel.
    """
    from entry_make_miss import (
        blue_rim_chord, capture_zone_rect, confirmation_zone_rect,
        shot_frame_end, build_continuous_trajectory,
    )

    sd = ShotData()

    if not ev.get("hoop_stable"):
        return sd

    hoop_tuple = tuple(ev["hoop_stable"])
    sd.hoop_tuple   = hoop_tuple
    sd.f_end        = shot_frame_end(up_frame, down_frame, next_up_frame, frame_count)
    sd.y_blue, sd.xb1, sd.xb2 = blue_rim_chord(hoop_tuple)
    sd.cap_rect     = capture_zone_rect(hoop_tuple)
    sd.confirm_rect = confirmation_zone_rect(hoop_tuple, sd.y_blue)

    traj, sel, ct, sc = build_continuous_trajectory(
        Path(video_path), model, ev,
        up_frame, down_frame, sd.f_end,
        hoop_tuple, sd.cap_rect,
    )
    sd.trajectory     = traj
    sd.sel_points     = sel
    sd.capture_trigger = ct
    sd.status_counts  = sc

    if person_model is not None:
        sd.person_feet = _scan_person_feet(video_path, up_frame, person_model)

    return sd


def _scan_person_feet(
    video_path: str | Path,
    up_frame: int,
    person_model: Any,
) -> Optional[tuple[int, int]]:
    """
    Scan frames [up_frame-30, up_frame-3] for the largest person bounding box.
    Returns (foot_u, foot_v) = bottom-centre of the largest box, or None.
    Replaces _detect_player_feet in cv_pipeline when ShotData is used.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    best_area = 0
    foot_u: Optional[int] = None
    foot_v: Optional[int] = None
    start = max(0, up_frame - 30)
    end   = max(0, up_frame - 3)

    for seek in range(start, end + 1, 3):
        cap.set(cv2.CAP_PROP_POS_FRAMES, seek)
        ok, frame = cap.read()
        if not ok:
            continue
        results = person_model(frame, verbose=False, conf=0.30, classes=[0])
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                area = (x2 - x1) * (y2 - y1)
                if area > best_area:
                    best_area = area
                    foot_u = int((x1 + x2) / 2)
                    foot_v = int(y2)

    cap.release()
    return (foot_u, foot_v) if foot_u is not None else None


def build_shot_data_from_accumulator(
    acc: Any,
    ev: dict,
    up_frame: int,
    down_frame: int,
    frame_count: int,
    hoop_accepted_count: int,
    person_model: Optional[Any] = None,
    video_path: str | Path | None = None,
    next_up_frame: Optional[int] = None,
) -> ShotData:
    """Package ShotData from TrajectoryAccumulator.finalize output (no video reopen)."""
    from entry_make_miss import blue_rim_chord, capture_zone_rect, confirmation_zone_rect, shot_frame_end

    sd = ShotData()
    if not ev.get("hoop_stable"):
        return sd

    hoop_tuple = tuple(ev["hoop_stable"])
    f_end = shot_frame_end(up_frame, down_frame, next_up_frame, frame_count)
    traj, sel, ct, sc = acc.finalize(ev, down_frame, f_end)

    sd.hoop_tuple = hoop_tuple
    sd.f_end = f_end
    sd.y_blue, sd.xb1, sd.xb2 = blue_rim_chord(hoop_tuple)
    sd.cap_rect = capture_zone_rect(hoop_tuple)
    sd.confirm_rect = confirmation_zone_rect(hoop_tuple, sd.y_blue)
    sd.trajectory = traj
    sd.sel_points = sel
    sd.capture_trigger = ct
    sd.status_counts = sc

    if person_model is not None and video_path is not None:
        sd.person_feet = _scan_person_feet(video_path, up_frame, person_model)

    return sd
