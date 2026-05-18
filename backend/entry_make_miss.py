"""
xShot — make/miss entry scoring (blue chord + confirmation gate).

Shared by production (cv_pipeline) and offline diagnostic batch.
Implements v3 shot-window trajectory rescue + rim-relevant trim + entry rule.

Constants and rules: see DIAGNOSTIC_RULES_SPEC.txt in the diagnostic output folder.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

import cv2

import cv_pipeline

BLUE_CHORD_FRAC_OF_HW = 0.94
BBOX_INSET_PX = 1.0
BLUE_TOUCH_EPS_PX = 1.0
RIM_EXIT_BELOW_MARGIN_PX = 8.0
CAP_HALF_WIDTH_FRAC_HW = 0.70
CAP_Y_TOP_FRAC_HH = 1.30
CAP_Y_BOT_FRAC_HH = 0.90
CONFIRM_HALF_WIDTH_FRAC_HW = 0.35
CONFIRM_TOP_OFFSET_FRAC_HH = 0.175
CONFIRM_HEIGHT_FRAC_HH = 0.35

TAIL_AFTER_DOWN = 50
MAX_SPAN_AFTER_UP = 180

# Diagnostic-only YOLO ball sampling
INFERENCE_CONF_FLOOR = 0.025
RESCUE_CONF_005 = 0.05
RESCUE_CONF_0025 = 0.025
RESCUE_SIZE_MIN_FRAC = 0.35
RESCUE_SIZE_MAX_FRAC = 2.5
MOTION_TOL_MIN_PX = 36.0
MOTION_TOL_FRAC_HW = 0.38

MIN_HOOP_BOX_PX = 8.0
WEAK_RIM_HCX_FRAC = 0.12
RIM_BALL_CX_FRAC = 0.35

STATUS_COLORS_BGR = {
    "PROD": (0, 140, 255),
    "REGULAR": (0, 165, 255),
    "DENSE": (255, 255, 0),
    "RESCUE_005": (0, 255, 255),
    "RESCUE_0025": (255, 0, 255),
}


def _clip_folder_name(video_stem: str) -> str:
    try:
        return f"clip_{int(video_stem):03d}"
    except ValueError:
        return f"clip_{video_stem}"


def _sort_videos(paths: list[Path]) -> list[Path]:
    def key(p: Path) -> tuple:
        try:
            return (0, int(p.stem))
        except ValueError:
            return (1, p.stem)

    return sorted(paths, key=key)


def shot_frame_end(
    up_frame: int,
    down_frame: int,
    next_up_frame: Optional[int],
    total_frames: int,
) -> int:
    ends = [down_frame + TAIL_AFTER_DOWN, up_frame + MAX_SPAN_AFTER_UP, total_frames - 1]
    if next_up_frame is not None:
        ends.append(next_up_frame - 1)
    return max(up_frame, min(ends))


def _align_shots(shot_events: list, shot_points: list) -> tuple[list[tuple], list[str]]:
    warnings: list[str] = []
    ne, ns = len(shot_events), len(shot_points)
    if ne != ns:
        warnings.append(f"ALIGNMENT_WARNING: shot_events ({ne}) != shot_points ({ns})")
    pairs = []
    for i in range(min(ne, ns)):
        aw = "paired_by_index_despite_count_mismatch" if ne != ns else None
        pairs.append((i + 1, shot_events[i], shot_points[i], aw))
    for i in range(min(ne, ns), ne):
        warnings.append(f"ALIGNMENT_WARNING: unmatched shot_events index {i}")
    for i in range(min(ne, ns), ns):
        warnings.append(f"ALIGNMENT_WARNING: unmatched shot_points index {i}")
    return pairs, warnings


def _alignment_invalid(warn: Optional[str]) -> bool:
    return bool(warn) and (
        "count_mismatch" in warn
        or "paired_by_index_despite" in warn
        or "ALIGNMENT_WARNING" in warn
    )


def _hoop_tuple_from_stable_bbox_tl(bbox: Any) -> Optional[tuple[float, float, int, float, float, float]]:
    if bbox is None:
        return None
    try:
        x, y, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    except (IndexError, TypeError, ValueError):
        return None
    if bw <= 0 or bh <= 0:
        return None
    hcx = float(x) + float(bw) / 2.0
    hcy = float(y) + float(bh) / 2.0
    return (hcx, hcy, 0, float(bw), float(bh), 1.0)


def _hoop_edges(hoop_tuple: tuple) -> tuple[float, float, float, float]:
    hcx, hcy, _fi, hw, hh, _conf = hoop_tuple
    return (hcx - hw / 2.0, hcx + hw / 2.0, hcy - hh / 2.0, hcy + hh / 2.0)


def blue_rim_chord(
    hoop_tuple: tuple,
    chord_frac: Optional[float] = None,
) -> tuple[float, float, float]:
    hcx, hcy, _fi, hw, hh, _conf = hoop_tuple
    xL, xR, _yt, _yb = _hoop_edges(hoop_tuple)
    y_blue = hcy - 0.5 * hh
    frac = BLUE_CHORD_FRAC_OF_HW if chord_frac is None else float(chord_frac)
    half = (frac * float(hw)) / 2.0
    xa = hcx - half
    xb = hcx + half
    eps = BBOX_INSET_PX
    xa = max(xL + eps, min(xa, xR - eps))
    xb = min(xR - eps, max(xb, xL + eps))
    if xb <= xa:
        xa, xb = xL + eps, xR - eps
    return float(y_blue), float(xa), float(xb)


def capture_zone_rect(hoop_tuple: tuple) -> tuple[float, float, float, float]:
    hcx, hcy, _fi, hw, hh, _conf = hoop_tuple
    half = CAP_HALF_WIDTH_FRAC_HW * float(hw)
    return (
        float(hcx - half),
        float(hcy - CAP_Y_TOP_FRAC_HH * float(hh)),
        float(hcx + half),
        float(hcy + CAP_Y_BOT_FRAC_HH * float(hh)),
    )


def confirmation_zone_rect(hoop_tuple: tuple, y_blue: float) -> tuple[float, float, float, float]:
    hcx, hcy, _fi, hw, hh, _conf = hoop_tuple
    xL, xR, _yt, _yb = _hoop_edges(hoop_tuple)
    half_w = CONFIRM_HALF_WIDTH_FRAC_HW * float(hw)
    x1 = hcx - half_w
    x2 = hcx + half_w
    eps = BBOX_INSET_PX
    x1 = max(xL + eps, min(x1, xR - eps))
    x2 = min(xR - eps, max(x2, xL + eps))
    if x2 <= x1:
        x1, x2 = xL + eps, xR - eps
    y1 = y_blue + CONFIRM_TOP_OFFSET_FRAC_HH * float(hh)
    y2 = y1 + CONFIRM_HEIGHT_FRAC_HH * float(hh)
    return float(x1), float(y1), float(x2), float(y2)


def _point_in_rect(cx: float, cy: float, rect: tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = rect
    return x1 <= cx <= x2 and y1 <= cy <= y2


def _hoop_list(hoop_tuple: tuple) -> list:
    hcx, hcy, _fi, hw, hh, conf = hoop_tuple
    return [(hcx, hcy, 0, hw, hh, conf)]


def _seed_production_points(ev: dict, up_frame: int, down_frame: int) -> dict[int, dict[str, Any]]:
    raw: list[tuple] = list(ev.get("ball_points_window") or [])
    if not raw:
        snap = ev.get("ball_pos_snapshot") or []
        raw = [p for p in snap if up_frame <= int(p[2]) <= down_frame]
    by_frame: dict[int, dict[str, Any]] = {}
    for p in raw:
        if len(p) < 3:
            continue
        fi = int(p[2])
        if fi < up_frame or fi > down_frame:
            continue
        cx, cy = float(p[0]), float(p[1])
        w = float(p[3]) if len(p) > 3 else 10.0
        h = float(p[4]) if len(p) > 4 else 10.0
        conf = float(p[5]) if len(p) > 5 else 1.0
        cand = {
            "frame": fi, "cx": cx, "cy": cy, "w": w, "h": h, "conf": conf,
            "status": "PROD", "selection_reason": "production_ball_points_window",
        }
        prev = by_frame.get(fi)
        if prev is None or conf >= prev["conf"]:
            by_frame[fi] = cand
    return by_frame


def _diag_raw_ball_detections(frame_bgr: Any, model: Any, hoop_tuple: tuple) -> list[dict[str, Any]]:
    hoop_list = _hoop_list(hoop_tuple)
    results = model(frame_bgr, verbose=False, conf=INFERENCE_CONF_FLOOR)
    out: list[dict[str, Any]] = []
    for r in results:
        for box in r.boxes:
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


def _motion_accept(
    cx: float, cy: float, frame_idx: int,
    recent: list[dict[str, Any]], hw: float,
) -> bool:
    tol = max(MOTION_TOL_MIN_PX, MOTION_TOL_FRAC_HW * float(hw))
    if not recent:
        return False
    if len(recent) == 1:
        p = recent[-1]
        return math.hypot(cx - p["cx"], cy - p["cy"]) <= tol
    p0, p1 = recent[-2], recent[-1]
    f0, f1 = int(p0["frame"]), int(p1["frame"])
    if f1 <= f0 or frame_idx <= f1:
        return math.hypot(cx - p1["cx"], cy - p1["cy"]) <= tol
    vx = (p1["cx"] - p0["cx"]) / float(f1 - f0)
    vy = (p1["cy"] - p0["cy"]) / float(f1 - f0)
    dt = float(frame_idx - f1)
    px = p1["cx"] + vx * dt
    py = p1["cy"] + vy * dt
    return math.hypot(cx - px, cy - py) <= tol


def _size_ok(c: dict[str, Any], recent: list[dict[str, Any]]) -> bool:
    if not recent:
        return False
    r = (float(c["w"]) + float(c["h"])) / 4.0
    radii = [(float(p["w"]) + float(p["h"])) / 4.0 for p in recent[-5:]]
    med = sorted(radii)[len(radii) // 2]
    if med < 2.0:
        return True
    return RESCUE_SIZE_MIN_FRAC * med <= r <= RESCUE_SIZE_MAX_FRAC * med


def _pick_best(cands: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not cands:
        return None
    return max(cands, key=lambda d: (d["conf"], -d["cy"]))


def _select_diagnostic_point(
    raw: list[dict[str, Any]],
    frame_idx: int,
    recent: list[dict[str, Any]],
    hw: float,
    *,
    in_capture: bool,
) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    regulars = [c for c in raw if c["conf"] >= c["prod_th"]]
    if regulars:
        c = _pick_best(regulars)
        st = "REGULAR" if in_capture else "PROD"
        return {
            "frame": frame_idx, "cx": c["cx"], "cy": c["cy"],
            "w": c["w"], "h": c["h"], "conf": c["conf"],
            "status": st, "selection_reason": "production_threshold",
        }
    if not recent:
        return None
    for label, floor in (("RESCUE_005", RESCUE_CONF_005), ("RESCUE_0025", RESCUE_CONF_0025)):
        pool = [c for c in raw if c["conf"] >= floor]
        ok = [
            c for c in pool
            if _motion_accept(c["cx"], c["cy"], frame_idx, recent, hw)
            and _size_ok(c, recent)
        ]
        if not ok:
            continue
        c = _pick_best(ok)
        return {
            "frame": frame_idx, "cx": c["cx"], "cy": c["cy"],
            "w": c["w"], "h": c["h"], "conf": c["conf"],
            "status": label, "selection_reason": f"rescue_conf>={floor}",
        }
    return None


def build_continuous_trajectory(
    video_path: Path,
    model: Any,
    ev: dict,
    up_frame: int,
    down_frame: int,
    f_end: int,
    hoop_tuple: tuple,
    cap_rect: tuple[float, float, float, float],
) -> tuple[list[tuple[int, float, float]], list[dict[str, Any]], Optional[int], dict[str, int]]:
    by_frame = _seed_production_points(ev, up_frame, down_frame)
    capture_trigger: Optional[int] = None
    for fi in sorted(by_frame):
        if _point_in_rect(by_frame[fi]["cx"], by_frame[fi]["cy"], cap_rect):
            capture_trigger = fi
            break

    _hcx, _hcy, _fi, hw, _hh, _conf = hoop_tuple
    stride = cv_pipeline.FRAME_STRIDE
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        selected = sorted(by_frame.values(), key=lambda d: d["frame"])
        pts = [(int(d["frame"]), float(d["cx"]), float(d["cy"])) for d in selected if d["frame"] >= up_frame]
        return pts, selected, capture_trigger, _count_statuses(selected)

    def _recent_sorted() -> list[dict[str, Any]]:
        return sorted(by_frame.values(), key=lambda d: d["frame"])

    def _apply_pick(f: int, pick: dict[str, Any], in_dense: bool) -> None:
        nonlocal capture_trigger
        if in_dense and pick.get("status") == "REGULAR":
            pick = {**pick, "status": "DENSE"}
        if capture_trigger is None and _point_in_rect(pick["cx"], pick["cy"], cap_rect):
            capture_trigger = f
        by_frame[f] = pick

    try:
        f = up_frame
        while f <= f_end:
            in_dense = capture_trigger is not None and f >= capture_trigger
            step = 1 if in_dense else stride

            if f in by_frame and not in_dense:
                if capture_trigger is None and _point_in_rect(by_frame[f]["cx"], by_frame[f]["cy"], cap_rect):
                    capture_trigger = f
                f += step
                continue

            cap.set(cv2.CAP_PROP_POS_FRAMES, f)
            ok, frame = cap.read()
            if not ok or frame is None:
                f += step
                continue

            recent = _recent_sorted()
            pick: Optional[dict[str, Any]] = None
            raw = _diag_raw_ball_detections(frame, model, hoop_tuple)

            pick = _select_diagnostic_point(
                raw, f, recent, float(hw), in_capture=in_dense,
            )

            if pick is not None:
                _apply_pick(f, pick, in_dense)

            f += step
    finally:
        cap.release()

    selected = sorted(by_frame.values(), key=lambda d: d["frame"])
    pts = [(int(d["frame"]), float(d["cx"]), float(d["cy"])) for d in selected if d["frame"] >= up_frame]
    return pts, selected, capture_trigger, _count_statuses(selected)


def _count_statuses(selected: list[dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for d in selected:
        st = str(d.get("status", "?"))
        c[st] = c.get(st, 0) + 1
    return c


def _point_touches_blue_chord(
    cx: float, cy: float, y_blue: float, xb1: float, xb2: float,
) -> bool:
    xmin, xmax = (xb1, xb2) if xb1 <= xb2 else (xb2, xb1)
    return abs(cy - y_blue) <= BLUE_TOUCH_EPS_PX and xmin <= cx <= xmax


def _segment_hits_blue_chord(
    x0: float, y0: float, x1: float, y1: float,
    y_blue: float, xb1: float, xb2: float,
) -> bool:
    xmin, xmax = (xb1, xb2) if xb1 <= xb2 else (xb2, xb1)
    return _segments_intersect(x0, y0, x1, y1, xmin, y_blue, xmax, y_blue)


def _finite_blue_crossings(
    pts: list[tuple[int, float, float]],
    y_blue: float,
    xb1: float,
    xb2: float,
) -> list[dict[str, Any]]:
    """Blue hit = segment intersects chord or vertex on chord (strict touch, no near-miss)."""
    if len(pts) < 1:
        return []
    xs = sorted(pts, key=lambda p: p[0])
    xmin, xmax = (xb1, xb2) if xb1 <= xb2 else (xb2, xb1)
    out: list[dict[str, Any]] = []
    seen_frames: set[float] = set()

    def _add(frame: float, cx: float, kind: str, pair_index: int) -> None:
        key = round(frame, 4)
        if key in seen_frames:
            return
        seen_frames.add(key)
        out.append({
            "crossing_x": float(cx),
            "cross_frame": float(frame),
            "pair_index": pair_index,
            "hit_kind": kind,
        })

    for i, (f0, x0, y0) in enumerate(xs):
        if _point_touches_blue_chord(x0, y0, y_blue, xb1, xb2):
            _add(float(f0), x0, "vertex_touch", i)

    for i, (p0, p1) in enumerate(zip(xs[:-1], xs[1:])):
        f0, x0, y0 = p0
        f1, x1, y1 = p1
        if not _segment_hits_blue_chord(x0, y0, x1, y1, y_blue, xb1, xb2):
            continue
        if y1 == y0:
            if abs(y0 - y_blue) <= BLUE_TOUCH_EPS_PX:
                mid_x = (x0 + x1) / 2.0
                if xmin <= mid_x <= xmax:
                    _add((float(f0) + float(f1)) / 2.0, mid_x, "segment_on_chord", i)
            continue
        t = (y_blue - y0) / (y1 - y0)
        if not (0.0 <= t <= 1.0):
            continue
        cx = x0 + t * (x1 - x0)
        if not (xmin <= cx <= xmax):
            continue
        cross_frame = float(f0) + t * float(f1 - f0)
        _add(cross_frame, cx, "cross", i)

    out.sort(key=lambda d: d["cross_frame"])
    return out


def _segment_rim_involved(
    x0: float, y0: float, x1: float, y1: float,
    y_blue: float, xb1: float, xb2: float,
    cap_rect: tuple[float, float, float, float],
    confirm_rect: tuple[float, float, float, float],
) -> bool:
    if _point_in_rect(x0, y0, cap_rect) or _point_in_rect(x1, y1, cap_rect):
        return True
    if _point_in_rect(x0, y0, confirm_rect) or _point_in_rect(x1, y1, confirm_rect):
        return True
    if _point_touches_blue_chord(x0, y0, y_blue, xb1, xb2):
        return True
    if _point_touches_blue_chord(x1, y1, y_blue, xb1, xb2):
        return True
    if _segment_hits_blue_chord(x0, y0, x1, y1, y_blue, xb1, xb2):
        return True
    if _segment_hits_rect(x0, y0, x1, y1, cap_rect):
        return True
    if _segment_hits_rect(x0, y0, x1, y1, confirm_rect):
        return True
    return False


def trim_rim_relevant_trajectory(
    pts: list[tuple[int, float, float]],
    y_blue: float,
    xb1: float,
    xb2: float,
    cap_rect: tuple[float, float, float, float],
    confirm_rect: tuple[float, float, float, float],
) -> tuple[list[tuple[int, float, float]], dict[str, Any]]:
    xs = sorted(pts, key=lambda p: p[0])
    meta: dict[str, Any] = {
        "trimmed": 0,
        "late_points_dropped": 0,
        "rim_relevant_end_frame": xs[-1][0] if xs else None,
        "rim_involved_start_frame": None,
    }
    if len(xs) < 2:
        return xs, meta

    _, _cy1, _, cap_y2 = cap_rect
    _, _qy1, _, conf_y2 = confirm_rect
    rim_bottom = max(float(cap_y2), float(conf_y2))

    involved_at: Optional[int] = None
    for i in range(len(xs)):
        fi, cx, cy = xs[i]
        if _point_in_rect(cx, cy, cap_rect) or _point_in_rect(cx, cy, confirm_rect):
            involved_at = i
            break
        if _point_touches_blue_chord(cx, cy, y_blue, xb1, xb2):
            involved_at = i
            break
        if i > 0:
            p0 = xs[i - 1]
            if _segment_rim_involved(
                p0[1], p0[2], cx, cy, y_blue, xb1, xb2, cap_rect, confirm_rect,
            ):
                involved_at = i
                break

    if involved_at is None:
        return xs, meta

    meta["rim_involved_start_frame"] = xs[involved_at][0]

    exit_at: Optional[int] = None
    for j in range(involved_at, len(xs)):
        fi, cx, cy = xs[j]
        if cy > rim_bottom + RIM_EXIT_BELOW_MARGIN_PX:
            exit_at = j
            break

    if exit_at is None:
        return xs, meta

    trimmed = xs[: exit_at + 1]
    dropped = len(xs) - len(trimmed)
    if dropped > 0:
        meta["trimmed"] = 1
        meta["late_points_dropped"] = dropped
        meta["rim_relevant_end_frame"] = trimmed[-1][0]
    return trimmed, meta


def _segments_intersect(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> bool:
    def orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qy - py) * (rx - qx) - (qx - px) * (ry - qy)

    def on_seg(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> bool:
        return min(px, qx) <= rx <= max(px, qx) and min(py, qy) <= ry <= max(py, qy)

    o1 = orient(ax, ay, bx, by, cx, cy)
    o2 = orient(ax, ay, bx, by, dx, dy)
    o3 = orient(cx, cy, dx, dy, ax, ay)
    o4 = orient(cx, cy, dx, dy, bx, by)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    eps = 1e-9
    if abs(o1) < eps and on_seg(ax, ay, bx, by, cx, cy):
        return True
    if abs(o2) < eps and on_seg(ax, ay, bx, by, dx, dy):
        return True
    if abs(o3) < eps and on_seg(cx, cy, dx, dy, ax, ay):
        return True
    if abs(o4) < eps and on_seg(cx, cy, dx, dy, bx, by):
        return True
    return False


def _segment_hits_rect(
    x0: float, y0: float, x1: float, y1: float,
    rect: tuple[float, float, float, float],
) -> bool:
    rx1, ry1, rx2, ry2 = rect
    if _point_in_rect(x0, y0, rect) or _point_in_rect(x1, y1, rect):
        return True
    edges = [
        ((rx1, ry1), (rx2, ry1)), ((rx2, ry1), (rx2, ry2)),
        ((rx2, ry2), (rx1, ry2)), ((rx1, ry2), (rx1, ry1)),
    ]
    for (ex0, ey0), (ex1, ey1) in edges:
        if _segments_intersect(x0, y0, x1, y1, ex0, ey0, ex1, ey1):
            return True
    return False


def _confirmation_after_cross(
    pts: list[tuple[int, float, float]],
    cross_frame: float,
    confirm_rect: tuple[float, float, float, float],
) -> tuple[Optional[int], Optional[str]]:
    xs = sorted(pts, key=lambda p: p[0])
    for fi, cx, cy in xs:
        if float(fi) <= cross_frame:
            continue
        if _point_in_rect(cx, cy, confirm_rect):
            return int(fi), "vertex"
    for p0, p1 in zip(xs[:-1], xs[1:]):
        f0, x0, y0 = p0
        f1, x1, y1 = p1
        if float(max(f0, f1)) <= cross_frame:
            continue
        if float(min(f0, f1)) > cross_frame:
            if _segment_hits_rect(x0, y0, x1, y1, confirm_rect):
                return int(min(f0, f1)), "segment"
        elif _segment_hits_rect(x0, y0, x1, y1, confirm_rect):
            return int(max(f0, f1)), "segment"
    return None, None


def evaluate_entry_rule(
    pts: list[tuple[int, float, float]],
    y_blue: float,
    xb1: float,
    xb2: float,
    confirm_rect: tuple[float, float, float, float],
) -> dict[str, Any]:
    if len(pts) < 2:
        return {
            "diagnostic_result": "MISS",
            "reason": "insufficient_points",
            "blue_cross_frame": None,
            "confirmation_frame": None,
            "confirmation_hit_kind": None,
        }
    crossings = _finite_blue_crossings(pts, y_blue, xb1, xb2)
    if not crossings:
        early, early_kind = _confirmation_after_cross(pts, -1.0, confirm_rect)
        r = "no_blue_cross_confirm_only" if early is not None else "no_blue_cross"
        return {
            "diagnostic_result": "MISS",
            "reason": r,
            "blue_cross_frame": None,
            "confirmation_frame": early,
            "confirmation_hit_kind": early_kind,
        }
    first_cf = float(crossings[0]["cross_frame"])
    for c in crossings:
        cross_f = float(c["cross_frame"])
        hit, kind = _confirmation_after_cross(pts, cross_f, confirm_rect)
        if hit is not None:
            return {
                "diagnostic_result": "MAKE",
                "reason": "blue_cross_then_confirmation",
                "blue_cross_frame": cross_f,
                "confirmation_frame": hit,
                "confirmation_hit_kind": kind,
            }
    return {
        "diagnostic_result": "MISS",
        "reason": "blue_cross_no_confirm",
        "blue_cross_frame": first_cf,
        "confirmation_frame": None,
        "confirmation_hit_kind": None,
    }


def check_geometry(
    hoop_tuple: Optional[tuple],
    trajectory: list[tuple[int, float, float]],
    frame_w: int,
    hoop_accepted_count: int,
) -> tuple[bool, str, str]:
    if hoop_tuple is None:
        return False, "INVALID_GEOMETRY", "missing_hoop_geometry"
    hcx, hcy, _fi, hw, hh, _conf = hoop_tuple
    if hw < MIN_HOOP_BOX_PX or hh < MIN_HOOP_BOX_PX:
        return False, "INVALID_GEOMETRY", "degenerate_hoop_box"
    if (
        hoop_accepted_count < cv_pipeline.HOOP_FALLBACK_REGULAR_MIN
        and hcx < WEAK_RIM_HCX_FRAC * float(frame_w)
    ):
        return False, "INVALID_GEOMETRY", "weak_fallback_rim_left_edge"
    if len(trajectory) >= 2:
        ball_xs = sorted(cx for _, cx, _ in trajectory)
        mid = ball_xs[len(ball_xs) // 2]
        if abs(mid - hcx) > RIM_BALL_CX_FRAC * float(frame_w):
            return False, "INVALID_GEOMETRY", "rim_ball_horizontal_mismatch"
    return True, "OK", ""



def _ball_pos_to_ev(ball_pos: list, up_frame: int, down_frame: int) -> dict[str, Any]:
    window = [p for p in ball_pos if up_frame <= int(p[2]) <= down_frame]
    snap = [p for p in ball_pos if int(p[2]) >= up_frame]
    return {
        "ball_points_window": window,
        "ball_pos_snapshot": snap,
        "up_frame": up_frame,
        "down_frame": down_frame,
    }


def score_shot(
    video_path: str | Path,
    model: Any,
    ball_pos: list,
    hoop_pos: list,
    up_frame: int,
    down_frame: int,
    frame_count: int,
    frame_w: int,
    hoop_accepted_count: int,
    next_up_frame: Optional[int] = None,
) -> tuple[bool, str]:
    """Production make/miss via entry rule. Returns (is_made, score_detail)."""
    if not hoop_pos:
        return False, "entry:no_hoop"
    hoop_tuple = tuple(hoop_pos[-1])
    f_end = shot_frame_end(up_frame, down_frame, next_up_frame, frame_count)
    ev = _ball_pos_to_ev(ball_pos, up_frame, down_frame)
    y_blue, xb1, xb2 = blue_rim_chord(hoop_tuple)
    cap_rect = capture_zone_rect(hoop_tuple)
    confirm_rect = confirmation_zone_rect(hoop_tuple, y_blue)
    trajectory, _sel, _ct, _sc = build_continuous_trajectory(
        Path(video_path), model, ev, up_frame, down_frame, f_end, hoop_tuple, cap_rect,
    )
    rim_pts, trim_meta = trim_rim_relevant_trajectory(
        trajectory, y_blue, xb1, xb2, cap_rect, confirm_rect,
    )
    geom_ok, _gs, geom_reason = check_geometry(
        hoop_tuple, rim_pts, frame_w, hoop_accepted_count,
    )
    if not geom_ok:
        return False, f"entry_geom:{geom_reason}"
    if len(rim_pts) < 2:
        return False, "entry:insufficient_points"
    ev_out = evaluate_entry_rule(rim_pts, y_blue, xb1, xb2, confirm_rect)
    is_made = ev_out.get("diagnostic_result") == "MAKE"
    detail = (
        f"entry:{ev_out.get('reason')} "
        f"blue={ev_out.get('blue_cross_frame')} "
        f"confirm={ev_out.get('confirmation_frame')} "
        f"trim_drop={trim_meta.get('late_points_dropped', 0)} "
        f"traj={len(trajectory)} rim={len(rim_pts)}"
    )
    return is_made, detail
