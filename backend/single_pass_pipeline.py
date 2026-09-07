"""
Single-pass video pipeline — one VideoCapture feeding ShotSessionEngine.

Make/miss: score_shot_from_data via build_shot_data_from_accumulator (no build_continuous_trajectory hot path).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import cv2

import cv_pipeline
from court_mapper import CourtMapper
from inference_reuse import counters_snapshot
from runtime_config import POST_SHOT_COOLDOWN_FRAMES
from shot_session_engine import ShotSessionEngine

logger = logging.getLogger(__name__)


def _origin_from_event(ev: dict) -> dict:
    if ev.get("origin_pixel_adaptive"):
        return ev["origin_pixel_adaptive"]
    return cv_pipeline._origin_estimator.estimate(ev)


def _stamp_fallback_shot_ids(shot_events: list[dict]) -> None:
    """Weak-hoop replay replaces engine events; assign ids at that moment."""
    for i, ev in enumerate(shot_events, start=1):
        ev["shot_id"] = f"s{i:03d}"


def run(
    video_path: str,
    court_mapper: Optional[CourtMapper] = None,
) -> tuple[list[dict], dict]:
    path = Path(video_path)
    if not path.exists():
        raise RuntimeError(f"Video file not found: {video_path}")

    # Load person model for player-feet floor detection when court mapping is active.
    # Mirrors the legacy pipeline: needed to get accurate floor-plane origin.
    _person_model = None
    if court_mapper is not None:
        try:
            from ultralytics import YOLO
            _person_model = YOLO(str(Path(__file__).parent / "yolov8n.pt"))
        except Exception:
            pass

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    logger.info("Single-pass pipeline: %s  frames=%d", path.name, frame_count)

    from ultralytics import YOLO

    model = YOLO(str(Path(__file__).parent / cv_pipeline.YOLO_MODEL_PATH))
    backend_dir = Path(__file__).parent

    engine = ShotSessionEngine()
    engine.start(
        model=model,
        frame_width=frame_width,
        total_frames=frame_count,
        video_path=str(path),
        person_model=_person_model,
        collect_weak_detections=True,
        backend_dir=backend_dir,
    )

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        engine.process_frame(frame, frame_idx)
        frame_idx += 1

    cap.release()

    shot_events, _eng_diag = engine.finalize()
    weak_hoop_raw = engine.weak_hoop_raw
    all_ball_raw = engine.all_ball_raw
    all_hoop_pos = list(engine.all_hoop_pos)
    hoop_accepted_count = engine.hoop_accepted_count
    hoop_raw_count = engine.hoop_raw_count
    ball_raw_count = engine.ball_raw_count
    ball_accepted_count = engine.ball_accepted_count
    ball_near_hoop_count = engine.ball_near_hoop_count
    contact_sampler = engine.contact_sampler

    hoop_fallback_used = False
    if hoop_accepted_count < cv_pipeline.HOOP_FALLBACK_REGULAR_MIN and not shot_events:
        fb_tuple = cv_pipeline._compute_hoop_fallback_consensus(
            weak_hoop_raw, cv_pipeline.HOOP_FALLBACK_MIN_FRAMES,
        )
        if fb_tuple is not None:
            logger.info(
                "Weak-hoop fallback activated: consensus at (%.0f, %.0f)",
                fb_tuple[0], fb_tuple[1],
            )
            shot_events = cv_pipeline._run_state_machine_with_fallback(
                all_ball_raw,
                fb_tuple,
                frame_count,
                str(path),
                model,
                frame_width,
                hoop_accepted_count,
            )
            _stamp_fallback_shot_ids(shot_events)
            hoop_fallback_used = True
            if not all_hoop_pos:
                fb_cx, fb_cy, _, fb_w, fb_h, _ = fb_tuple
                all_hoop_pos = [(fb_cx, fb_cy, 0, fb_w, fb_h, cv_pipeline.HOOP_FALLBACK_CONF_MIN)]

    stable_hoop = None
    if all_hoop_pos:
        import numpy as np
        stable_hoop = (
            int(float(np.median([p[0] for p in all_hoop_pos])) - float(np.median([p[3] for p in all_hoop_pos])) / 2),
            int(float(np.median([p[1] for p in all_hoop_pos])) - float(np.median([p[4] for p in all_hoop_pos])) / 2),
            int(float(np.median([p[3] for p in all_hoop_pos]))),
            int(float(np.median([p[4] for p in all_hoop_pos]))),
        )

    # Load person model and scan feet positions for court mapping.
    # person_feet gives a floor-level pixel so the floor-plane homography
    # produces accurate court coordinates — unlike the aerial ball pixel.
    _person_model = None
    if court_mapper is not None:
        from ultralytics import YOLO as _YOLO
        person_model_path = Path(__file__).parent / "yolov8n.pt"
        if person_model_path.exists():
            _person_model = _YOLO(str(person_model_path))
        else:
            logger.warning("yolov8n.pt not found — falling back to ball pixel for court mapping")

    if court_mapper is not None and _person_model is not None:
        from shot_data_builder import _scan_person_feet
        for ev in shot_events:
            sd = ev.get("_shot_data")
            if sd is not None and sd.person_feet is None:
                sd.person_feet = _scan_person_feet(str(path), ev["up_frame"], _person_model)

    shot_points: list[dict] = []
    for ev in shot_events:
        shot_id = ev["shot_id"]
        origin_pixel = _origin_from_event(ev)
        court = zone = None
        if court_mapper is not None:
            sd = ev.get("_shot_data")
            floor_u: Optional[int] = None
            floor_v: Optional[int] = None
            using_ball_pixel = False

            if sd is not None and sd.person_feet is not None:
                floor_u, floor_v = sd.person_feet
                logger.info("Shot %s feet pixel = (%d, %d)", shot_id, floor_u, floor_v)
            elif origin_pixel is not None:
                floor_u = origin_pixel.get("u")
                floor_v = origin_pixel.get("v")
                using_ball_pixel = True
                logger.info("Shot %s no person found — using ball pixel (%s, %s)", shot_id, floor_u, floor_v)

            if floor_u is not None and floor_v is not None:
                hoop = ev.get("hoop_stable")
                hoop_cx = int(hoop[0]) if hoop else None
                pixel_side_ref = (floor_u, hoop_cx) if using_ball_pixel and hoop_cx is not None else None
                court, zone = court_mapper.map_shot(floor_u, floor_v, pixel_side_ref=pixel_side_ref)
                logger.info("Shot %s court = %s  zone = %s", shot_id, court, zone)

        hs = ev.get("hoop_stable")
        apex_v = ev.get("v")
        arc_px = cv_pipeline._arc_height_from_hoop_and_apex(hs, apex_v)

        shot_points.append({
            "shot_id": shot_id,
            "result": ev["result"],
            "origin": {"pixel": origin_pixel, "court": court},
            "zone": zone,
            "trajectory": {
                "arc_height_px": arc_px,
                "apex_pixel": {
                    "u": ev["u"], "v": ev["v"],
                    "frame_index": ev["frame_index"],
                },
                "up_frame": ev["up_frame"],
                "down_frame": ev["down_frame"],
            },
        })

    diag = {
        "hoop_fallback_used": hoop_fallback_used,
        "hoop_raw_count": hoop_raw_count,
        "hoop_accepted_count": hoop_accepted_count,
        "hoop_stable_bbox": stable_hoop,
        "ball_raw_count": ball_raw_count,
        "ball_accepted_count": ball_accepted_count,
        "ball_near_hoop_count": ball_near_hoop_count,
        "shot_events": shot_events,
        "fps": fps,
        "frame_count": frame_count,
        "frame_height": frame_height,
        "contact_check_count": contact_sampler.check_count,
        "contact_check_sec": contact_sampler.check_sec,
        "post_shot_cooldown_frames": POST_SHOT_COOLDOWN_FRAMES,
        **counters_snapshot(),
    }
    return shot_points, diag
