"""
Single-pass video pipeline — one VideoCapture, YOLO reuse, TrajectoryAccumulator scoring.

Make/miss: score_shot_from_data via build_shot_data_from_accumulator (no build_continuous_trajectory hot path).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2

import cv_pipeline
import entry_make_miss
from contact_sampler import ContactSampler
from court_mapper import CourtMapper
from inference_reuse import (
    counters_snapshot,
    record_main_loop_yolo,
    reset_yolo_counters,
)
from release_from_contact import compute_release_pixel
from runtime_config import (
    HOOP_INFERENCE_CONF,
    IDLE_BALL_ACCEPT,
    IDLE_CADENCE,
    POST_SHOT_COOLDOWN_FRAMES,
    PipelineMode,
    SHOT_BALL_ACCEPT,
    SHOT_STRIDE,
    TRAJECTORY_INFERENCE_CONF,
)
from shot_data_builder import build_shot_data_from_accumulator
from trajectory_accumulator import TrajectoryAccumulator

logger = logging.getLogger(__name__)


@dataclass
class OpenShot:
    acc: TrajectoryAccumulator
    up_frame: int
    down_frame: Optional[int] = None
    f_end: Optional[int] = None
    ready_to_score: bool = False
    origin_pixel_adaptive: Optional[dict] = None


@dataclass
class _IdleCadenceState:
    pattern_idx: int = 0
    next_yolo: int = 0
    prev_sm: Optional[PipelineMode] = None
    prev_in_cooldown: bool = False

    def on_idle_entry(self, frame_idx: int) -> None:
        self.pattern_idx = 0
        self.next_yolo = frame_idx


def _mode_stride(mode: PipelineMode) -> int:
    if mode == PipelineMode.NEAR_HOOP:
        return 1
    return SHOT_STRIDE


def _mode_ball_accept(mode: PipelineMode) -> float:
    if mode == PipelineMode.IDLE:
        return IDLE_BALL_ACCEPT
    return SHOT_BALL_ACCEPT


def _run_yolo_for_sm(
    frame_idx: int,
    mode: PipelineMode,
    in_cooldown: bool,
    idle_cadence: _IdleCadenceState,
) -> bool:
    if in_cooldown or mode == PipelineMode.COOLDOWN:
        idle_cadence.prev_in_cooldown = True
        idle_cadence.prev_sm = mode
        return False

    if mode != PipelineMode.IDLE:
        idle_cadence.prev_sm = mode
        idle_cadence.prev_in_cooldown = False
        return frame_idx % _mode_stride(mode) == 0

    idle_entry = (
        idle_cadence.prev_sm != PipelineMode.IDLE
        or (idle_cadence.prev_in_cooldown and not in_cooldown)
    )
    if idle_entry:
        idle_cadence.on_idle_entry(frame_idx)
    idle_cadence.prev_sm = PipelineMode.IDLE
    idle_cadence.prev_in_cooldown = False

    if frame_idx >= idle_cadence.next_yolo:
        gap = IDLE_CADENCE[idle_cadence.pattern_idx]
        idle_cadence.pattern_idx = (idle_cadence.pattern_idx + 1) % len(IDLE_CADENCE)
        idle_cadence.next_yolo = frame_idx + gap
        return True
    return False


def _origin_from_event(ev: dict) -> dict:
    if ev.get("origin_pixel_adaptive"):
        return ev["origin_pixel_adaptive"]
    return cv_pipeline._origin_estimator._trajectory_anchor(ev)


def run(
    video_path: str,
    court_mapper: Optional[CourtMapper] = None,
) -> tuple[list[dict], dict]:
    path = Path(video_path)
    if not path.exists():
        raise RuntimeError(f"Video file not found: {video_path}")

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

    ball_pos: list = []
    hoop_pos: list = []
    all_hoop_pos: list = []
    weak_hoop_raw: list = []
    all_ball_raw: list = []

    global_mode = PipelineMode.IDLE
    up = False
    down = False
    up_frame = 0
    down_frame = 0
    cooldown_until = -1

    hoop_raw_count = hoop_accepted_count = 0
    ball_raw_count = ball_accepted_count = ball_near_hoop_count = 0

    shot_events: list[dict] = []
    open_shots: list[OpenShot] = []
    contact_sampler = ContactSampler(backend_dir)
    reset_yolo_counters()
    idle_cadence = _IdleCadenceState()

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        in_cooldown = frame_idx < cooldown_until
        if in_cooldown:
            global_mode = PipelineMode.COOLDOWN

        sm_mode = PipelineMode.NEAR_HOOP if global_mode == PipelineMode.NEAR_HOOP else (
            PipelineMode.SHOT if open_shots else global_mode
        )

        if contact_sampler.should_check(frame_idx, in_cooldown):
            contact_sampler.check_frame(frame_idx, frame)

        traj_due = [
            s for s in open_shots
            if s.acc.active and s.acc.should_process_frame(frame_idx)
        ] if not in_cooldown else []
        run_sm = _run_yolo_for_sm(frame_idx, sm_mode, in_cooldown, idle_cadence)

        if run_sm or traj_due:
            infer_conf = (
                TRAJECTORY_INFERENCE_CONF
                if traj_due or sm_mode in (PipelineMode.SHOT, PipelineMode.NEAR_HOOP)
                else HOOP_INFERENCE_CONF
            )
            results = model(frame, verbose=False, conf=infer_conf)
            record_main_loop_yolo()
            ball_accept = _mode_ball_accept(
                PipelineMode.IDLE if in_cooldown else sm_mode,
            )

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    w, h = x2 - x1, y2 - y1
                    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                    conf = float(box.conf[0])
                    cls = int(box.cls[0])

                    if cls == 0:
                        ball_raw_count += 1
                        if run_sm and not in_cooldown:
                            near = cv_pipeline._in_hoop_region(cx, cy, hoop_pos)
                            th = (
                                cv_pipeline.BALL_CONF_NEAR_HOOP
                                if near
                                else ball_accept
                            )
                            if conf >= th:
                                ball_accepted_count += 1
                                if near:
                                    ball_near_hoop_count += 1
                                det = (cx, cy, frame_idx, w, h, conf)
                                ball_pos.append(det)
                                all_ball_raw.append(det)
                                ball_pos = cv_pipeline._clean_ball_pos(ball_pos, frame_idx)
                                contact_sampler.store_ball_detection(
                                    frame_idx, cx, cy, w, h, conf,
                                )
                    elif cls == 1:
                        hoop_raw_count += 1
                        if conf >= cv_pipeline.HOOP_CONF_THRESHOLD:
                            hoop_accepted_count += 1
                            hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                            hoop_pos = cv_pipeline._clean_hoop_pos(hoop_pos)
                            all_hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                        elif conf >= cv_pipeline.HOOP_FALLBACK_CONF_MIN:
                            weak_hoop_raw.append((cx, cy, frame_idx, w, h, conf))

            raw_parse_cache: dict[int, list] = {}
            for shot in traj_due:
                shot.acc.on_frame(
                    frame_idx,
                    frame,
                    model,
                    inference_results=results,
                    raw_parse_cache=raw_parse_cache,
                )

        if not in_cooldown and hoop_pos and ball_pos:
            if not up:
                if cv_pipeline._detect_up(ball_pos, hoop_pos):
                    up = True
                    up_frame = int(ball_pos[-1][2])
                    global_mode = PipelineMode.SHOT
                    hoop_tuple = tuple(hoop_pos[-1])
                    from entry_make_miss import capture_zone_rect, shot_frame_end

                    cap_rect = capture_zone_rect(hoop_tuple)
                    acc = TrajectoryAccumulator()
                    acc.start(
                        up_frame,
                        {
                            "ball_points_window": [],
                            "ball_pos_snapshot": list(ball_pos),
                        },
                        hoop_tuple,
                        cap_rect,
                        shot_frame_end(up_frame, up_frame, None, frame_count),
                        up_frame,
                    )
                    rel = compute_release_pixel(up_frame, contact_sampler)
                    open_shots.append(OpenShot(
                        acc=acc,
                        up_frame=up_frame,
                        origin_pixel_adaptive=rel,
                    ))

            if up and not down:
                if cv_pipeline._detect_down(ball_pos, hoop_pos):
                    down = True
                    down_frame = int(ball_pos[-1][2])
                    for shot in reversed(open_shots):
                        if shot.down_frame is None:
                            shot.down_frame = down_frame
                            from entry_make_miss import shot_frame_end
                            shot.f_end = shot_frame_end(
                                shot.up_frame, down_frame, None, frame_count,
                            )
                            shot.acc.update_down(down_frame, {
                                "ball_points_window": [
                                    p for p in ball_pos
                                    if shot.up_frame <= p[2] <= down_frame
                                ],
                                "ball_pos_snapshot": list(ball_pos),
                            })
                            shot.acc.set_f_end(shot.f_end)
                            break

            if up and hoop_pos and ball_pos:
                from entry_make_miss import capture_zone_rect
                cap_rect = capture_zone_rect(tuple(hoop_pos[-1]))
                bcx, bcy = ball_pos[-1][0], ball_pos[-1][1]
                if cv_pipeline._in_hoop_region(bcx, bcy, hoop_pos) or entry_make_miss._point_in_rect(
                    bcx, bcy, cap_rect,
                ):
                    global_mode = PipelineMode.NEAR_HOOP

        if frame_idx % cv_pipeline.ATTEMPT_CONFIRM_EVERY == 0:
            if up and down and up_frame < down_frame and not in_cooldown:
                if up_frame >= cv_pipeline.MIN_FIRST_SHOT_FRAME and (
                    down_frame - up_frame <= cv_pipeline.ATTEMPT_MAX_FRAME_GAP
                ):
                    for shot in reversed(open_shots):
                        if (
                            shot.down_frame == down_frame
                            and shot.up_frame == up_frame
                            and not shot.ready_to_score
                        ):
                            shot.ready_to_score = True
                            break
                    up = False
                    down = False
                    global_mode = PipelineMode.IDLE if not open_shots else PipelineMode.SHOT

        finished: list[OpenShot] = []
        for shot in open_shots:
            if (
                shot.ready_to_score
                and shot.f_end is not None
                and frame_idx >= shot.f_end
            ):
                uf, df = shot.up_frame, int(shot.down_frame)
                ev_dict = {
                    "ball_points_window": [p for p in ball_pos if uf <= p[2] <= df],
                    "ball_pos_snapshot": list(ball_pos),
                    "up_frame": uf,
                    "down_frame": df,
                    "hoop_stable": list(hoop_pos[-1]) if hoop_pos else None,
                    "_video_path": str(path),
                }
                if shot.origin_pixel_adaptive:
                    ev_dict["origin_pixel_adaptive"] = shot.origin_pixel_adaptive

                shot_data = build_shot_data_from_accumulator(
                    shot.acc, ev_dict, uf, df, frame_count,
                    hoop_accepted_count, video_path=str(path),
                )
                is_made, score_detail = entry_make_miss.score_shot_from_data(
                    shot_data, frame_width, hoop_accepted_count,
                )
                apex = cv_pipeline._find_apex_for_shot(
                    shot_data, ev_dict, uf, df, ball_pos,
                )
                if apex is not None:
                    ev_dict["frame_index"] = apex[2]
                    ev_dict["u"] = int(apex[0])
                    ev_dict["v"] = int(apex[1])
                    ev_dict["result"] = "made" if is_made else "missed"
                    ev_dict["_shot_data"] = shot_data
                    shot_events.append(ev_dict)
                    logger.info(
                        "Shot at frame %d: %s [%s]",
                        apex[2], ev_dict["result"], score_detail,
                    )
                shot.acc.clear()
                finished.append(shot)
                cooldown_until = max(
                    cooldown_until, frame_idx + POST_SHOT_COOLDOWN_FRAMES,
                )
                global_mode = PipelineMode.COOLDOWN

        for shot in finished:
            open_shots.remove(shot)

        if global_mode == PipelineMode.COOLDOWN and frame_idx >= cooldown_until:
            global_mode = PipelineMode.IDLE

        frame_idx += 1

    cap.release()

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

    shot_points: list[dict] = []
    for i, ev in enumerate(shot_events, start=1):
        origin_pixel = _origin_from_event(ev)
        court = zone = None
        if court_mapper is not None and origin_pixel:
            sd = ev.get("_shot_data")
            floor_u: Optional[int] = None
            floor_v: Optional[int] = None
            using_ball_pixel = False
            if sd is not None and sd.person_feet is not None:
                floor_u, floor_v = sd.person_feet
            else:
                floor_u = origin_pixel.get("u")
                floor_v = origin_pixel.get("v")
                using_ball_pixel = True

            if floor_u is not None and floor_v is not None:
                hoop = ev.get("hoop_stable")
                hoop_cx = int(hoop[0]) if hoop else None
                pixel_side_ref = (floor_u, hoop_cx) if using_ball_pixel and hoop_cx is not None else None
                court, zone = court_mapper.map_shot(floor_u, floor_v, pixel_side_ref=pixel_side_ref)

        hs = ev.get("hoop_stable")
        apex_v = ev.get("v")
        arc_px = cv_pipeline._arc_height_from_hoop_and_apex(hs, apex_v)

        shot_points.append({
            "shot_id": f"s{i:03d}",
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
