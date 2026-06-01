"""
Incremental build_continuous_trajectory — same entry_make_miss helpers, no VideoCapture.
"""

from __future__ import annotations

from typing import Any, Optional

import entry_make_miss as emm
from inference_reuse import (
    raw_for_hoop_from_results,
    record_trajectory_fallback_yolo,
)
from runtime_config import NEAR_HOOP_STRIDE, SHOT_STRIDE


def _in_dense_phase(
    frame_idx: int,
    capture_trigger: Optional[int],
) -> bool:
    return capture_trigger is not None and frame_idx >= capture_trigger


def _merge_frame_pick(
    frame_idx: int,
    seed_pt: Optional[dict],
    acc_pt: Optional[dict],
    capture_trigger: Optional[int],
) -> Optional[dict]:
    if seed_pt is None:
        return acc_pt
    if acc_pt is None:
        return seed_pt
    if _in_dense_phase(frame_idx, capture_trigger):
        return acc_pt
    if str(seed_pt.get("status")) == "PROD":
        return seed_pt
    if str(acc_pt.get("status")) == "PROD":
        return seed_pt
    return (
        acc_pt
        if float(acc_pt.get("conf", 0)) >= float(seed_pt.get("conf", 0))
        else seed_pt
    )


def _merge_seed_into_by_frame(
    by_frame: dict[int, dict],
    seed: dict[int, dict],
    capture_trigger: Optional[int],
) -> None:
    for fi, pt in seed.items():
        by_frame[fi] = _merge_frame_pick(
            fi, pt, by_frame.get(fi), capture_trigger,
        )


def _refresh_capture_trigger(
    by_frame: dict[int, dict],
    cap_rect: tuple,
    capture_trigger: Optional[int],
) -> Optional[int]:
    if capture_trigger is not None:
        return capture_trigger
    for fi in sorted(by_frame):
        pt = by_frame[fi]
        if emm._point_in_rect(pt["cx"], pt["cy"], cap_rect):
            return fi
    return None


class TrajectoryAccumulator:
    def __init__(self) -> None:
        self.up_frame: int = 0
        self.down_frame: int = 0
        self.f_end: int = 0
        self.hoop_tuple: Optional[tuple] = None
        self.cap_rect: tuple = ()
        self.by_frame: dict[int, dict] = {}
        self.capture_trigger: Optional[int] = None
        self.next_f: int = 0
        self.active: bool = False
        self.hw: float = 0.0

    def start(
        self,
        up_frame: int,
        ev: dict,
        hoop_tuple: tuple,
        cap_rect: tuple,
        f_end: int,
        down_frame: int,
    ) -> None:
        self.up_frame = up_frame
        self.down_frame = down_frame
        self.f_end = f_end
        self.hoop_tuple = hoop_tuple
        self.cap_rect = cap_rect
        self.hw = float(hoop_tuple[3])
        self.by_frame = emm._seed_production_points(ev, up_frame, down_frame)
        self.capture_trigger = _refresh_capture_trigger(
            self.by_frame, cap_rect, None,
        )
        self.next_f = up_frame
        self.active = True

    def update_down(self, down_frame: int, ev: dict) -> None:
        self.down_frame = down_frame
        seed = emm._seed_production_points(ev, self.up_frame, down_frame)
        _merge_seed_into_by_frame(self.by_frame, seed, self.capture_trigger)
        self.capture_trigger = _refresh_capture_trigger(
            self.by_frame, self.cap_rect, self.capture_trigger,
        )

    def set_f_end(self, f_end: int) -> None:
        self.f_end = max(self.up_frame, f_end)

    def should_process_frame(self, frame_idx: int) -> bool:
        if not self.active or frame_idx < self.next_f or frame_idx > self.f_end:
            return False
        return frame_idx == self.next_f

    def _advance(self, step: int) -> None:
        self.next_f += step

    def on_frame(
        self,
        frame_idx: int,
        frame_bgr: Any,
        model: Any,
        precomputed_raw: Optional[list] = None,
        inference_results: Any = None,
        raw_parse_cache: Optional[dict[int, list]] = None,
    ) -> None:
        if not self.active or frame_idx != self.next_f or frame_idx > self.f_end:
            return

        in_dense = _in_dense_phase(frame_idx, self.capture_trigger)
        step = NEAR_HOOP_STRIDE if in_dense else SHOT_STRIDE

        if frame_idx in self.by_frame and not in_dense:
            if self.capture_trigger is None and emm._point_in_rect(
                self.by_frame[frame_idx]["cx"],
                self.by_frame[frame_idx]["cy"],
                self.cap_rect,
            ):
                self.capture_trigger = frame_idx
            self._advance(step)
            return

        recent = sorted(self.by_frame.values(), key=lambda d: d["frame"])
        if precomputed_raw is not None:
            raw = precomputed_raw
        elif inference_results is not None and self.hoop_tuple is not None:
            cache = raw_parse_cache if raw_parse_cache is not None else {}
            raw = raw_for_hoop_from_results(
                inference_results, self.hoop_tuple, cache,
            )
        else:
            record_trajectory_fallback_yolo()
            raw = emm._diag_raw_ball_detections(frame_bgr, model, self.hoop_tuple)
        pick = emm._select_diagnostic_point(
            raw, frame_idx, recent, self.hw, in_capture=in_dense,
        )
        if pick is not None:
            if in_dense and pick.get("status") == "REGULAR":
                pick = {**pick, "status": "DENSE"}
            if self.capture_trigger is None and emm._point_in_rect(
                pick["cx"], pick["cy"], self.cap_rect,
            ):
                self.capture_trigger = frame_idx
            self.by_frame[frame_idx] = pick

        self._advance(step)

    def catch_up_to(self, frame_idx: int, frame_bgr: Any, model: Any) -> None:
        while self.active and self.next_f <= frame_idx and self.next_f <= self.f_end:
            self.on_frame(self.next_f, frame_bgr, model)
            if self.next_f > frame_idx:
                break

    def finalize(self, ev: dict, down_frame: int, f_end: int) -> tuple:
        self.down_frame = down_frame
        self.f_end = f_end
        accumulated = dict(self.by_frame)
        seed = emm._seed_production_points(ev, self.up_frame, down_frame)
        merged: dict[int, dict] = {}
        for f in range(self.up_frame, f_end + 1):
            pt = _merge_frame_pick(
                f,
                seed.get(f),
                accumulated.get(f),
                self.capture_trigger,
            )
            if pt is not None:
                merged[f] = pt
        self.by_frame = merged
        self.capture_trigger = _refresh_capture_trigger(
            merged, self.cap_rect, self.capture_trigger,
        )
        selected = sorted(self.by_frame.values(), key=lambda d: d["frame"])
        pts = [
            (int(d["frame"]), float(d["cx"]), float(d["cy"]))
            for d in selected
            if d["frame"] >= self.up_frame
        ]
        return (
            pts,
            selected,
            self.capture_trigger,
            emm._count_statuses(selected),
        )

    def clear(self) -> None:
        self.active = False
        self.by_frame = {}
        self.capture_trigger = None
