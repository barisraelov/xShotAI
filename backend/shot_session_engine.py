"""
Stateful per-frame CV engine extracted from the single-pass Upload loop.

Does not open VideoCapture. Callers feed (frame_bgr, frame_id) serially.
Upload supplies real total_frames / video_path / person_model and collects
weak-hoop detections; Live will omit those without changing the state machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv_pipeline
import entry_make_miss
from contact_sampler import ContactSampler
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


@dataclass(frozen=True)
class ShotDecided:
    shot_id: str
    result: str
    decision_frame: int


@dataclass
class OpenShot:
    acc: TrajectoryAccumulator
    up_frame: int
    down_frame: Optional[int] = None
    f_end: Optional[int] = None
    ready_to_score: bool = False
    origin_pixel_adaptive: Optional[dict] = None
    ball_snapshot_at_up: list = None


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


def _session_frame_end(
    up_frame: int,
    down_frame: int,
    next_up_frame: Optional[int],
    total_frames: Optional[int],
) -> int:
    if total_frames is not None:
        return entry_make_miss.shot_frame_end(
            up_frame, down_frame, next_up_frame, total_frames,
        )
    ends = [
        down_frame + entry_make_miss.TAIL_AFTER_DOWN,
        up_frame + entry_make_miss.MAX_SPAN_AFTER_UP,
    ]
    if next_up_frame is not None:
        ends.append(next_up_frame - 1)
    return max(up_frame, min(ends))


class ShotSessionEngine:
    def start(
        self,
        *,
        model: Any,
        frame_width: int,
        total_frames: Optional[int] = None,
        video_path: Optional[str] = None,
        person_model: Any = None,
        collect_weak_detections: bool = True,
        backend_dir: Optional[Path] = None,
    ) -> None:
        self._model = model
        self._frame_width = frame_width
        self._total_frames = total_frames
        self._video_path = video_path
        self._person_model = person_model
        self._collect_weak_detections = collect_weak_detections
        self._backend_dir = backend_dir or Path(__file__).parent

        self.ball_pos: list = []
        self.hoop_pos: list = []
        self.all_hoop_pos: list = []
        self.weak_hoop_raw: list = []
        self.all_ball_raw: list = []

        self.global_mode = PipelineMode.IDLE
        self.up = False
        self.down = False
        self.up_frame = 0
        self.down_frame = 0
        self.cooldown_until = -1

        self.hoop_raw_count = 0
        self.hoop_accepted_count = 0
        self.ball_raw_count = 0
        self.ball_accepted_count = 0
        self.ball_near_hoop_count = 0

        self.shot_events: list[dict] = []
        self.open_shots: list[OpenShot] = []
        self.contact_sampler = ContactSampler(self._backend_dir)
        self.idle_cadence = _IdleCadenceState()
        self._next_shot_index = 1
        reset_yolo_counters()

    def process_frame(self, frame_bgr: Any, frame_id: int) -> list[ShotDecided]:
        decided: list[ShotDecided] = []
        frame_idx = frame_id
        in_cooldown = frame_idx < self.cooldown_until
        if in_cooldown:
            self.global_mode = PipelineMode.COOLDOWN

        sm_mode = PipelineMode.NEAR_HOOP if self.global_mode == PipelineMode.NEAR_HOOP else (
            PipelineMode.SHOT if self.open_shots else self.global_mode
        )

        if self.contact_sampler.should_check(frame_idx, in_cooldown):
            self.contact_sampler.check_frame(frame_idx, frame_bgr)

        traj_due = [
            s for s in self.open_shots
            if s.acc.active and s.acc.should_process_frame(frame_idx)
        ] if not in_cooldown else []
        run_sm = _run_yolo_for_sm(frame_idx, sm_mode, in_cooldown, self.idle_cadence)

        if run_sm or traj_due:
            infer_conf = (
                TRAJECTORY_INFERENCE_CONF
                if traj_due or sm_mode in (PipelineMode.SHOT, PipelineMode.NEAR_HOOP)
                else HOOP_INFERENCE_CONF
            )
            results = self._model(frame_bgr, verbose=False, conf=infer_conf)
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
                        self.ball_raw_count += 1
                        if run_sm and not in_cooldown:
                            near = cv_pipeline._in_hoop_region(cx, cy, self.hoop_pos)
                            th = (
                                cv_pipeline.BALL_CONF_NEAR_HOOP
                                if near
                                else ball_accept
                            )
                            if conf >= th:
                                self.ball_accepted_count += 1
                                if near:
                                    self.ball_near_hoop_count += 1
                                det = (cx, cy, frame_idx, w, h, conf)
                                self.ball_pos.append(det)
                                if self._collect_weak_detections:
                                    self.all_ball_raw.append(det)
                                self.ball_pos = cv_pipeline._clean_ball_pos(
                                    self.ball_pos, frame_idx,
                                )
                                self.contact_sampler.store_ball_detection(
                                    frame_idx, cx, cy, w, h, conf,
                                )
                    elif cls == 1:
                        self.hoop_raw_count += 1
                        if conf >= cv_pipeline.HOOP_CONF_THRESHOLD:
                            self.hoop_accepted_count += 1
                            self.hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                            self.hoop_pos = cv_pipeline._clean_hoop_pos(self.hoop_pos)
                            self.all_hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                        elif (
                            self._collect_weak_detections
                            and conf >= cv_pipeline.HOOP_FALLBACK_CONF_MIN
                        ):
                            self.weak_hoop_raw.append((cx, cy, frame_idx, w, h, conf))

            raw_parse_cache: dict[int, list] = {}
            for shot in traj_due:
                shot.acc.on_frame(
                    frame_idx,
                    frame_bgr,
                    self._model,
                    inference_results=results,
                    raw_parse_cache=raw_parse_cache,
                )

        if not in_cooldown and self.hoop_pos and self.ball_pos:
            if not self.up:
                if cv_pipeline._detect_up(self.ball_pos, self.hoop_pos):
                    self.up = True
                    self.up_frame = int(self.ball_pos[-1][2])
                    self.global_mode = PipelineMode.SHOT
                    hoop_tuple = tuple(self.hoop_pos[-1])
                    from entry_make_miss import capture_zone_rect

                    cap_rect = capture_zone_rect(hoop_tuple)
                    acc = TrajectoryAccumulator()
                    acc.start(
                        self.up_frame,
                        {
                            "ball_points_window": [],
                            "ball_pos_snapshot": list(self.ball_pos),
                        },
                        hoop_tuple,
                        cap_rect,
                        _session_frame_end(
                            self.up_frame, self.up_frame, None, self._total_frames,
                        ),
                        self.up_frame,
                    )
                    rel = compute_release_pixel(self.up_frame, self.contact_sampler)
                    self.open_shots.append(OpenShot(
                        acc=acc,
                        up_frame=self.up_frame,
                        origin_pixel_adaptive=rel,
                        ball_snapshot_at_up=list(self.ball_pos),
                    ))

            if self.up and not self.down:
                if cv_pipeline._detect_down(self.ball_pos, self.hoop_pos):
                    self.down = True
                    self.down_frame = int(self.ball_pos[-1][2])
                    for shot in reversed(self.open_shots):
                        if shot.down_frame is None:
                            shot.down_frame = self.down_frame
                            shot.f_end = _session_frame_end(
                                shot.up_frame, self.down_frame, None, self._total_frames,
                            )
                            shot.acc.update_down(self.down_frame, {
                                "ball_points_window": [
                                    p for p in self.ball_pos
                                    if shot.up_frame <= p[2] <= self.down_frame
                                ],
                                "ball_pos_snapshot": list(self.ball_pos),
                            })
                            shot.acc.set_f_end(shot.f_end)
                            break

            if self.up and self.hoop_pos and self.ball_pos:
                from entry_make_miss import capture_zone_rect
                cap_rect = capture_zone_rect(tuple(self.hoop_pos[-1]))
                bcx, bcy = self.ball_pos[-1][0], self.ball_pos[-1][1]
                if cv_pipeline._in_hoop_region(bcx, bcy, self.hoop_pos) or entry_make_miss._point_in_rect(
                    bcx, bcy, cap_rect,
                ):
                    self.global_mode = PipelineMode.NEAR_HOOP

        if frame_idx % cv_pipeline.ATTEMPT_CONFIRM_EVERY == 0:
            if self.up and self.down and self.up_frame < self.down_frame and not in_cooldown:
                if self.up_frame >= cv_pipeline.MIN_FIRST_SHOT_FRAME and (
                    self.down_frame - self.up_frame <= cv_pipeline.ATTEMPT_MAX_FRAME_GAP
                ):
                    for shot in reversed(self.open_shots):
                        if (
                            shot.down_frame == self.down_frame
                            and shot.up_frame == self.up_frame
                            and not shot.ready_to_score
                        ):
                            shot.ready_to_score = True
                            break
                    self.up = False
                    self.down = False
                    self.global_mode = (
                        PipelineMode.IDLE if not self.open_shots else PipelineMode.SHOT
                    )

        finished: list[OpenShot] = []
        for shot in self.open_shots:
            if (
                shot.ready_to_score
                and shot.f_end is not None
                and frame_idx >= shot.f_end
            ):
                uf, df = shot.up_frame, int(shot.down_frame)
                ev_dict: dict = {
                    "ball_points_window": [p for p in self.ball_pos if uf <= p[2] <= df],
                    "ball_pos_snapshot": shot.ball_snapshot_at_up or list(self.ball_pos),
                    "up_frame": uf,
                    "down_frame": df,
                    "hoop_stable": list(self.hoop_pos[-1]) if self.hoop_pos else None,
                }
                if self._video_path is not None:
                    ev_dict["_video_path"] = self._video_path
                if shot.origin_pixel_adaptive:
                    ev_dict["origin_pixel_adaptive"] = shot.origin_pixel_adaptive

                frame_count_for_sd = (
                    self._total_frames
                    if self._total_frames is not None
                    else shot.f_end + 1
                )
                shot_data = build_shot_data_from_accumulator(
                    shot.acc, ev_dict, uf, df, frame_count_for_sd,
                    self.hoop_accepted_count,
                    person_model=self._person_model,
                    video_path=self._video_path,
                )
                is_made, score_detail = entry_make_miss.score_shot_from_data(
                    shot_data, self._frame_width, self.hoop_accepted_count,
                )
                apex = cv_pipeline._find_apex_for_shot(
                    shot_data, ev_dict, uf, df, self.ball_pos,
                )
                if apex is not None:
                    shot_id = f"s{self._next_shot_index:03d}"
                    self._next_shot_index += 1
                    ev_dict["shot_id"] = shot_id
                    ev_dict["frame_index"] = apex[2]
                    ev_dict["u"] = int(apex[0])
                    ev_dict["v"] = int(apex[1])
                    ev_dict["result"] = "made" if is_made else "missed"
                    ev_dict["_shot_data"] = shot_data
                    self.shot_events.append(ev_dict)
                    decided.append(ShotDecided(
                        shot_id=shot_id,
                        result=ev_dict["result"],
                        decision_frame=frame_idx,
                    ))
                    logger.info(
                        "Shot at frame %d: %s [%s]",
                        apex[2], ev_dict["result"], score_detail,
                    )
                shot.acc.clear()
                finished.append(shot)
                self.cooldown_until = max(
                    self.cooldown_until, frame_idx + POST_SHOT_COOLDOWN_FRAMES,
                )
                self.global_mode = PipelineMode.COOLDOWN

        for shot in finished:
            self.open_shots.remove(shot)

        if self.global_mode == PipelineMode.COOLDOWN and frame_idx >= self.cooldown_until:
            self.global_mode = PipelineMode.IDLE

        return decided

    def has_open_shot(self) -> bool:
        return bool(self.open_shots)

    def abort_open_shot(self) -> None:
        """LIVE-17 / LIVE-19: drop open trajectories without scoring.

        Decided `shot_events` and the next `shot_id` index are unchanged.
        """
        for shot in self.open_shots:
            shot.acc.clear()
        self.open_shots.clear()
        self.up = False
        self.down = False
        self.up_frame = 0
        self.down_frame = 0
        self.cooldown_until = -1
        self.global_mode = PipelineMode.IDLE

    def reset_open_tracking(self) -> None:
        """LIVE-17: drop open shot plus ball trail so a long gap cannot resume it."""
        self.abort_open_shot()
        self.ball_pos = []

    def next_shot_index(self) -> int:
        """1-based index that will be used for the next `sNNN` shot_id."""
        return int(getattr(self, "_next_shot_index", 1) or 1)

    def seed_next_shot_index(self, next_index: int) -> None:
        """Continue the sNNN sequence after restored shots. Does not change scoring."""
        n = int(next_index)
        if n < 1:
            n = 1
        self._next_shot_index = n

    def finalize(self) -> tuple[list[dict], dict]:
        diag = {
            "hoop_raw_count": self.hoop_raw_count,
            "hoop_accepted_count": self.hoop_accepted_count,
            "ball_raw_count": self.ball_raw_count,
            "ball_accepted_count": self.ball_accepted_count,
            "ball_near_hoop_count": self.ball_near_hoop_count,
            "shot_events": self.shot_events,
            "contact_check_count": self.contact_sampler.check_count,
            "contact_check_sec": self.contact_sampler.check_sec,
            "post_shot_cooldown_frames": POST_SHOT_COOLDOWN_FRAMES,
            **counters_snapshot(),
        }
        return self.shot_events, diag
