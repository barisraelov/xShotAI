"""
Reuse main-loop YOLO results for trajectory selection (no second model() per frame).

Parse logic mirrors entry_make_miss._diag_raw_ball_detections without a second inference call.
"""

from __future__ import annotations

from typing import Any, Optional

import cv_pipeline
import entry_make_miss as emm

yolo_main_loop: int = 0
yolo_trajectory_fallback: int = 0
yolo_contact: int = 0


def reset_yolo_counters() -> None:
    global yolo_main_loop, yolo_trajectory_fallback, yolo_contact
    yolo_main_loop = 0
    yolo_trajectory_fallback = 0
    yolo_contact = 0


def counters_snapshot() -> dict[str, int]:
    return {
        "yolo_main_loop": yolo_main_loop,
        "yolo_trajectory_fallback": yolo_trajectory_fallback,
        "yolo_contact": yolo_contact,
    }


def record_main_loop_yolo() -> None:
    global yolo_main_loop
    yolo_main_loop += 1


def record_trajectory_fallback_yolo() -> None:
    global yolo_trajectory_fallback
    yolo_trajectory_fallback += 1


def record_contact_yolo(n: int = 2) -> None:
    global yolo_contact
    yolo_contact += n


def ball_candidates_from_results(
    results: Any,
    hoop_tuple: tuple,
) -> list[dict[str, Any]]:
    hoop_list = emm._hoop_list(hoop_tuple)
    out: list[dict[str, Any]] = []
    if results is None:
        return out
    for r in results:
        boxes = getattr(r, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            if int(box.cls[0]) != 0:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            bw = float(x2 - x1)
            bh = float(y2 - y1)
            cx = float((x1 + x2) / 2.0)
            cy = float((y1 + y2) / 2.0)
            conf = float(box.conf[0])
            near = bool(cv_pipeline._in_hoop_region(cx, cy, hoop_list))  # noqa: SLF001
            prod_th = float(
                cv_pipeline.BALL_CONF_NEAR_HOOP if near else cv_pipeline.BALL_CONF_THRESHOLD
            )
            out.append({
                "cx": cx, "cy": cy, "w": bw, "h": bh, "conf": conf,
                "near_hoop": near, "prod_th": prod_th,
            })
    out.sort(key=lambda d: (-d["conf"], d["cy"]))
    return out


def raw_for_hoop_from_results(
    results: Any,
    hoop_tuple: tuple,
    cache: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    key = id(hoop_tuple)
    if key not in cache:
        cache[key] = ball_candidates_from_results(results, hoop_tuple)
    return cache[key]
