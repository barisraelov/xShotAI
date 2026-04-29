"""
xShot AI — CV pipeline (Demo v1)

Architecture: rolling-window state machine adapted from
  avishah3/AI-Basketball-Shot-Detection-Tracker (2023).

Responsibilities:
  - Detect the hoop and basketball with a YOLO model trained on both classes.
  - Detect shot attempts via a zone state machine (up-zone → down-zone).
  - Classify each attempt as make or miss via parabolic (or validated linear)
    extrapolation of the ball trajectory across the rim height line.

Contract:
  - process_video(path) → list of ShotPoint dicts matching AnalyzeResult.shot_points.
  - origin.court and zone are always None — court mapping requires automatic lane
    detection (next_steps.md step 6), which is not yet implemented.
  - Returns an empty list if the video is valid but no shots were detected.
  - Raises RuntimeError on unrecoverable errors (corrupt file, model not found).

Model requirement:
  - best.pt (YOLOv8n, ~6 MB) must be present in the backend/ directory.
  - Download from: https://github.com/avishah3/AI-Basketball-Shot-Detection-Tracker
  - Classes: 0 = Basketball, 1 = Basketball Hoop.

Algorithm credit:
  - Core detection logic adapted from avishah3/AI-Basketball-Shot-Detection-Tracker.
  - Make/miss scoring upgraded to multi-point parabolic extrapolation with
    validated-linear and insufficient-data fallbacks (Session 4).
  - Original linear cross-check corroborated by
    arturchichorro/bballvision (2024).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from origin_estimator import OriginEstimator

# Module-level singleton — lightweight, no model loading.
# To upgrade to release+pose estimation (Phase 6), pass a ReleaseEstimator:
#   _origin_estimator = OriginEstimator(release_estimator=MyReleaseEstimator())
# See origin_estimator.py for the full plug-in contract.
_origin_estimator = OriginEstimator()

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────────

# Model file, resolved relative to this module's directory.
# Classes: 0 = Basketball, 1 = Basketball Hoop.
YOLO_MODEL_PATH = "best.pt"

# Analyse every Nth frame (speed/accuracy trade-off on CPU).
FRAME_STRIDE = 2

# Minimum YOLO confidence for a ball detection (general).
BALL_CONF_THRESHOLD = 0.30

# Minimum YOLO confidence for a ball detection when near the hoop.
# Prevents losing the ball at the critical make/miss crossing moment.
BALL_CONF_NEAR_HOOP = 0.15

# Minimum YOLO confidence for a hoop detection.
HOOP_CONF_THRESHOLD = 0.50

# Max number of accepted ball detections in the rolling window.
BALL_WINDOW = 30

# Max number of accepted hoop detections in the rolling window.
HOOP_WINDOW = 25

# Ball cleaning: reject if ball moves more than this × its diameter in < 5 frames.
BALL_CLEAN_JUMP_FACTOR = 4.0

# Ball cleaning: reject non-square bounding boxes (w/h or h/w exceeds this).
BALL_CLEAN_WH_RATIO = 1.4

# Hoop cleaning: reject if hoop center jumps > this fraction of its diameter in < 5 frames.
HOOP_CLEAN_JUMP_FACTOR = 0.5

# Hoop cleaning: reject non-square hoop bounding boxes.
HOOP_CLEAN_WH_RATIO = 1.3

# detect_up zone — horizontal half-width = UP_ZONE_X_FACTOR × hoop bbox width.
# Tunable: may need lowering for elevated/diagonal cameras if wide dribbles trigger false ups.
UP_ZONE_X_FACTOR = 4.0

# detect_up zone — vertical depth above hoop = UP_ZONE_Y_FACTOR × hoop bbox height.
# Tunable: may need adjustment if shots originate from a very different vertical angle.
UP_ZONE_Y_FACTOR = 2.0

# Poll the attempt-confirmation check every this many real frames (debounce interval).
ATTEMPT_CONFIRM_EVERY = 10

# Maximum frame gap between detect_up and detect_down to constitute a valid attempt.
ATTEMPT_MAX_FRAME_GAP = 120  # ~4 s at 30 fps — generous for slow or high-arc shots

# Make/miss: interpolated x must land within ±SCORE_RIM_X_FRACTION × (hoop_width/2).
SCORE_RIM_X_FRACTION = 0.40

# Make/miss: extra pixel buffer beyond the rim edge (catches rebounds that drop in).
SCORE_REBOUND_PX = 10

# Max frame gap for a valid 2-point linear crossing pair (Tier 2 fallback).
SCORE_MAX_CROSSING_GAP = FRAME_STRIDE * 3  # 6 frames at stride 2

# Min descent-phase above-rim detections for the parabolic fit (Tier 1).
SCORE_MIN_PARABOLIC_POINTS = 3

# Ignore shot attempts whose up_frame is before this frame index.
# Prevents false triggers when the video starts mid-shot.
# Set low (5 frames ≈ 0.17s) — only rejects truly instant triggers.
MIN_FIRST_SHOT_FRAME = 5

# ── Two-gate presence check (supplementary MISS→MAKE cue) ────────────────────
#
# When _score() returns False (MISS), _check_two_gate_presence() looks for
# production-accepted ball detections in two gates anchored to hoop_pos[-1]:
#
#   hoop_top    = hcy - 0.5 * hh
#   hoop_bottom = hcy + 0.5 * hh
#
#   UPPER gate: x ∈ [hcx - 0.5*hw, hcx + 0.5*hw],  y ∈ [hoop_top - hh, hoop_top]
#   LOWER gate: same x-range,  y ∈ [hoop_bottom, hoop_bottom + hh]
#
# Time window (real frame indices, matches two-gate diagnostic):
#   fi ∈ [up_frame, down_frame + BELOW_RIM_FRAME_WINDOW]
#
# Upgrade MISS→MAKE iff there is at least one upper hit and one lower hit with
# min(upper_hit.frame) < lower_hit.frame for some qualifying lower hit.
#
# Uses only ball_pos entries already accepted by the pipeline (same as _score).
# NEVER called when _score() returned True — may only upgrade MISS→MAKE.

# Tail past down_frame for two-gate scan (must match _diag_below_rim_gate.py).
BELOW_RIM_FRAME_WINDOW = 15

# ── Weak-hoop fallback (Session 8) ───────────────────────────────────────────
#
# When regular hoop signal is too sparse to sustain the state machine, the
# pipeline attempts a second pass: it collects all hoop boxes at the lower
# HOOP_FALLBACK_CONF_MIN confidence (captured in the same YOLO inference pass),
# deduplicates by frame, and tests whether they share a common intersection
# region.  If they do — indicating the model repeatedly finds the same
# approximate rim area across many frames — the intersection centre is used as
# a stable synthetic hoop for a state-machine replay (no extra YOLO inference).
#
# Static-camera assumption: the hoop never moves, so its position is the same
# in every frame.  Per-clip visual confirmation of the consensus centre is
# recommended before treating the result as ground truth.
#
# To disable completely:  set HOOP_FALLBACK_REGULAR_MIN = 0
# To require more evidence: raise HOOP_FALLBACK_MIN_FRAMES

# Min YOLO confidence for collecting weak hoop candidates.
# NOTE: the effective floor is ultralytics' inference threshold, controlled
# by the conf= argument passed to model().  We pass this value directly so
# detections down to HOOP_FALLBACK_CONF_MIN are visible inside the loop.
HOOP_FALLBACK_CONF_MIN    = 0.20

# Min number of unique-frame weak boxes required to declare a valid consensus.
HOOP_FALLBACK_MIN_FRAMES  = 5

# Fallback is attempted only when regular accepted hoop frames are below this.
# Clips with strong regular detection (e.g. clip 1: 228 frames) are never
# affected.
HOOP_FALLBACK_REGULAR_MIN = 10


# ── Rolling-window helpers ────────────────────────────────────────────────────
#
# Ball and hoop position entries are tuples:
#   (cx, cy, frame_index, w, h, conf)
# where (cx, cy) is the bounding-box centre and (w, h) is its size.


def _in_hoop_region(cx: float, cy: float, hoop_pos: list) -> bool:
    """Return True if (cx, cy) is within a 1-box region around the hoop centre."""
    if not hoop_pos:
        return False
    hcx, hcy, _, hw, hh, _ = hoop_pos[-1]
    return (hcx - hw < cx < hcx + hw) and (hcy - hh < cy < hcy + 0.5 * hh)


def _clean_ball_pos(ball_pos: list, frame_idx: int) -> list:
    """
    Remove the most recently appended ball detection if it fails sanity checks.
    Evict entries older than BALL_WINDOW frames from the front of the list.
    """
    if len(ball_pos) > 1:
        cx1, cy1, fi1, w1, h1, _ = ball_pos[-2]
        cx2, cy2, fi2, w2, h2, _ = ball_pos[-1]
        f_dif = fi2 - fi1
        dist = math.hypot(cx2 - cx1, cy2 - cy1)
        max_dist = BALL_CLEAN_JUMP_FACTOR * math.hypot(w1, h1)
        if dist > max_dist and f_dif < 5:
            ball_pos.pop()
        elif (w2 * BALL_CLEAN_WH_RATIO < h2) or (h2 * BALL_CLEAN_WH_RATIO < w2):
            ball_pos.pop()
    if ball_pos and frame_idx - ball_pos[0][2] > BALL_WINDOW:
        ball_pos.pop(0)
    return ball_pos


def _clean_hoop_pos(hoop_pos: list) -> list:
    """
    Remove the most recently appended hoop detection if it represents an impossible
    jump or a non-square box. Evict entries beyond HOOP_WINDOW from the front.
    """
    if len(hoop_pos) > 1:
        cx1, cy1, fi1, w1, h1, _ = hoop_pos[-2]
        cx2, cy2, fi2, w2, h2, _ = hoop_pos[-1]
        f_dif = fi2 - fi1
        dist = math.hypot(cx2 - cx1, cy2 - cy1)
        max_dist = HOOP_CLEAN_JUMP_FACTOR * math.hypot(w1, h1)
        if dist > max_dist and f_dif < 5:
            hoop_pos.pop()
        elif (w2 * HOOP_CLEAN_WH_RATIO < h2) or (h2 * HOOP_CLEAN_WH_RATIO < w2):
            hoop_pos.pop()
    if len(hoop_pos) > HOOP_WINDOW:
        hoop_pos.pop(0)
    return hoop_pos


# ── Shot state-machine helpers ────────────────────────────────────────────────

def _detect_up(ball_pos: list, hoop_pos: list) -> bool:
    """
    Return True when the most recent ball detection enters the backboard zone:
    horizontally within ±UP_ZONE_X_FACTOR hoop-widths of hoop centre,
    vertically between UP_ZONE_Y_FACTOR hoop-heights above centre and the hoop
    top edge (cy - 0.5 * h).
    """
    if not hoop_pos or not ball_pos:
        return False
    hcx, hcy, _, hw, hh, _ = hoop_pos[-1]
    bcx, bcy = ball_pos[-1][0], ball_pos[-1][1]
    x1 = hcx - UP_ZONE_X_FACTOR * hw
    x2 = hcx + UP_ZONE_X_FACTOR * hw
    y1 = hcy - UP_ZONE_Y_FACTOR * hh
    y2 = hcy - 0.5 * hh  # top edge of hoop bounding box
    return x1 < bcx < x2 and y1 < bcy < y2


def _detect_down(ball_pos: list, hoop_pos: list) -> bool:
    """Return True when the ball centre drops below the bottom edge of the hoop box."""
    if not hoop_pos or not ball_pos:
        return False
    hcy = hoop_pos[-1][1]
    hh  = hoop_pos[-1][4]
    bcy = ball_pos[-1][1]
    return bcy > hcy + 0.5 * hh


def _extract_rim_approach_points(
    ball_pos: list, hoop_pos: list, up_frame: int,
) -> tuple[list[tuple[int, float, float]], float]:
    """
    Collect ball detections above the rim from this shot's time window.
    Returns (points, rim_y) where each point is (frame_index, cx, cy).

    Uses all above-rim detections (ascending + descending) from up_frame
    onward.  Both phases follow the same parabola, so including ascending
    points gives a better fit when descent-phase near-rim detections are
    sparse (which is common — YOLO often loses the ball as it overlaps
    the hoop).

    Per-frame deduplication (Most Novel Position rule):
    When YOLO fires on two objects in the same inference frame (real ball
    + stationary false positive), both land in ball_pos.  A ghost repeats
    at nearly the same pixel position across many frames, so its nearest
    neighbour in the set is another ghost copy — distance ≈ 0.  A real
    ball in flight occupies a different position every frame — its nearest
    neighbour is the ball at an adjacent frame of the arc.  For each frame
    with multiple candidates, we keep the detection that is most spatially
    distant from its nearest same-position neighbour at any other frame,
    i.e. the most novel position.  Tiebreaker: prefer lower cy (higher in
    image = farther above rim).

    For bank shots the pre-contact and post-contact segments are different
    parabolas.  This is a known limitation; the combined fit is still a
    reasonable approximation for Demo v1 where bank shots are rare.
    """
    hcx, hcy, _, hw, hh, _ = hoop_pos[-1]
    rim_y = hcy - 0.5 * hh

    # Collect all above-rim candidates, grouped by frame index.
    from collections import defaultdict
    by_frame: dict = defaultdict(list)
    for p in ball_pos:
        if p[2] >= up_frame and p[1] < rim_y:
            by_frame[p[2]].append((p[2], p[0], p[1]))  # (frame, cx, cy)

    if not by_frame:
        return [], rim_y

    all_candidates: list = [p for pts in by_frame.values() for p in pts]

    # For frames with a single detection, accept directly.
    # For frames with multiple detections, apply Most Novel Position.
    result = []
    for fi in sorted(by_frame.keys()):
        candidates = by_frame[fi]
        if len(candidates) == 1:
            result.append(candidates[0])
            continue

        # Positions at OTHER frames (already-accepted + remaining candidates).
        other_positions = [
            (p[1], p[2]) for p in all_candidates if p[0] != fi
        ]

        best = None
        best_dist = -1.0
        for cand in candidates:
            if other_positions:
                min_d = min(
                    math.hypot(cand[1] - ox, cand[2] - oy)
                    for ox, oy in other_positions
                )
            else:
                min_d = float("inf")
            # Tiebreak by lower cy (farthest above rim).
            if min_d > best_dist or (min_d == best_dist and best is not None and cand[2] < best[2]):
                best_dist = min_d
                best = cand

        if best is not None:
            result.append(best)

    return result, rim_y


def _fit_rim_crossing(
    points: list[tuple[int, float, float]],
    rim_y: float,
    hoop_pos: list,
) -> tuple[Optional[float], str]:
    """
    Predict the ball's x-coordinate at the rim crossing using the best
    available method.

    Returns (predicted_cx, tier_label).  predicted_cx is None when there
    is insufficient data.

    Tier 1 — Parabolic (>= SCORE_MIN_PARABOLIC_POINTS):
        cy(t) = a*t^2 + b*t + c   (quadratic — gravity)
        cx(t) = d*t + e            (linear — constant horiz. velocity)
        Solve cy(t_rim) = rim_y, predict cx(t_rim).
        Sanity-checked: predicted_cx must be within a reasonable range
        of the hoop centre; t_rim must be near the data range.

    Tier 2 — Validated linear (2 closest-to-rim points):
        Straight-line extrapolation, but only when the pair is close in
        time and slopes correctly (ball falling).

    Tier 3 — Insufficient data:
        Return None (caller defaults to miss).
    """
    n = len(points)
    hcx = hoop_pos[-1][0]
    hw  = hoop_pos[-1][3]
    sanity_margin = max(hw * 6, 100)  # generous bound for plausible cx

    # ── Tier 1: parabolic ────────────────────────────────────────────
    if n >= SCORE_MIN_PARABOLIC_POINTS:
        ts  = np.array([p[0] for p in points], dtype=float)
        cxs = np.array([p[1] for p in points], dtype=float)
        cys = np.array([p[2] for p in points], dtype=float)

        cy_coeffs = np.polyfit(ts, cys, 2)  # a, b, c
        a, b, c = cy_coeffs

        if abs(a) < 1e-12:
            pass  # degenerate quadratic — fall through
        else:
            disc = b * b - 4.0 * a * (c - rim_y)
            if disc >= 0:
                sqrt_disc = math.sqrt(disc)
                t1 = (-b + sqrt_disc) / (2.0 * a)
                t2 = (-b - sqrt_disc) / (2.0 * a)
                t_rim = max(t1, t2)

                t_max_data = float(ts[-1])
                t_min_data = float(ts[0])
                if t_rim < t_min_data or t_rim > t_max_data + (t_max_data - t_min_data + 10):
                    logger.debug("Parabolic t_rim=%.1f outside data range [%.0f..%.0f], rejecting",
                                 t_rim, t_min_data, t_max_data)
                else:
                    cx_coeffs = np.polyfit(ts, cxs, 1)
                    predicted_cx = float(np.polyval(cx_coeffs, t_rim))
                    if abs(predicted_cx - hcx) <= sanity_margin:
                        return predicted_cx, f"parabolic({n}pts)"
                    logger.debug("Parabolic pred_cx=%.1f too far from hoop cx=%.1f, rejecting",
                                 predicted_cx, hcx)

    # ── Tier 2: validated linear (2 closest-to-rim points) ───────────
    if n >= 2:
        p_a = points[-2]
        p_b = points[-1]
        frame_gap = abs(p_b[0] - p_a[0])
        dy = p_b[2] - p_a[2]

        if frame_gap <= SCORE_MAX_CROSSING_GAP and dy > 0:
            dt = float(p_b[0] - p_a[0])
            if dt != 0:
                slope_cy = (p_b[2] - p_a[2]) / dt
                slope_cx = (p_b[1] - p_a[1]) / dt
                dt_rim = (rim_y - p_b[2]) / slope_cy
                predicted_cx = p_b[1] + slope_cx * dt_rim
                if abs(predicted_cx - hcx) <= sanity_margin:
                    return float(predicted_cx), f"linear({frame_gap}f)"

    # ── Tier 3 ───────────────────────────────────────────────────────
    return None, f"no_crossing({n}pts)"


def _check_rim_crossing(predicted_cx: float, hoop_pos: list) -> bool:
    """Return True if predicted_cx falls inside the rim opening."""
    hcx = hoop_pos[-1][0]
    hw  = hoop_pos[-1][3]
    rim_x1 = hcx - SCORE_RIM_X_FRACTION * hw - SCORE_REBOUND_PX
    rim_x2 = hcx + SCORE_RIM_X_FRACTION * hw + SCORE_REBOUND_PX
    return rim_x1 < predicted_cx < rim_x2


def _two_gate_rectangles(hcx: float, hcy: float, hw: float, hh: float):
    """Return (upper_rect, lower_rect) as (x1,y1,x2,y2), diagnostic geometry."""
    hoop_top = hcy - 0.5 * hh
    hoop_bottom = hcy + 0.5 * hh
    x1 = hcx - 0.5 * hw
    x2 = hcx + 0.5 * hw
    upper = (x1, hoop_top - hh, x2, hoop_top)
    lower = (x1, hoop_bottom, x2, hoop_bottom + hh)
    return upper, lower


def _point_in_gate(cx: float, cy: float, gate: tuple) -> bool:
    x1, y1, x2, y2 = gate
    return x1 < cx < x2 and y1 < cy < y2


def _check_two_gate_presence(
    ball_pos: list, hoop_pos: list, up_frame: int, down_frame: int
) -> tuple[bool, str]:
    """
    Supplementary two-gate presence check.  Called only when _score() returned
    False (MISS).  Uses production ball_pos only.

    Returns (upgraded: bool, detail: str) suitable for appending to score_detail.

    Never downgrades MAKE → MISS (callers must only invoke when _score() False).
    """
    if not hoop_pos:
        return False, "no_hoop"

    hcx, hcy, _, hw, hh, _ = hoop_pos[-1]
    upper_g, lower_g = _two_gate_rectangles(hcx, hcy, hw, hh)
    t_hi = down_frame + BELOW_RIM_FRAME_WINDOW

    upper_hits: list[tuple[int, float, float]] = []
    lower_hits: list[tuple[int, float, float]] = []

    for p in ball_pos:
        cx, cy, fi = p[0], p[1], p[2]
        if not (up_frame <= fi <= t_hi):
            continue
        if _point_in_gate(cx, cy, upper_g):
            upper_hits.append((fi, cx, cy))
        if _point_in_gate(cx, cy, lower_g):
            lower_hits.append((fi, cx, cy))

    gates_desc = (
        f"upper_y=[{upper_g[1]:.0f}..{upper_g[3]:.0f}]"
        f" lower_y=[{lower_g[1]:.0f}..{lower_g[3]:.0f}]"
        f" win=[{up_frame}..{t_hi}]"
    )

    if not upper_hits and not lower_hits:
        return False, f"no_hits  {gates_desc}"

    if upper_hits and not lower_hits:
        fs_u = sorted({h[0] for h in upper_hits})
        return False, f"upper_only  frames_upper={fs_u}  {gates_desc}"

    if lower_hits and not upper_hits:
        fs_l = sorted({h[0] for h in lower_hits})
        return False, f"lower_only  frames_lower={fs_l}  {gates_desc}"

    min_upper_fi = min(h[0] for h in upper_hits)
    lowers_after = [h for h in lower_hits if h[0] > min_upper_fi]
    if not lowers_after:
        fs_u = sorted({h[0] for h in upper_hits})
        fs_l = sorted({h[0] for h in lower_hits})
        return (
            False,
            f"bad_order  frames_upper={fs_u} frames_lower={fs_l}"
            f"  {gates_desc}",
        )

    first_lower_after = min(lowers_after, key=lambda h: h[0])
    return (
        True,
        f"seq  upper_min_f={min_upper_fi}"
        f"  lower_f={first_lower_after[0]}  {gates_desc}",
    )


def _score(ball_pos: list, hoop_pos: list, up_frame: int) -> tuple[bool, str]:
    """
    Make/miss classification via multi-point trajectory extrapolation.

    Uses descent-phase ball detections near the rim to predict where the
    ball crosses the rim plane, then checks whether that x-coordinate
    falls inside the rim opening.

    Returns (is_made, score_detail) where score_detail is a human-readable
    string describing which tier was used and key values (for debug logging).
    """
    if not hoop_pos or len(ball_pos) < 2:
        return False, "no_data"

    points, rim_y = _extract_rim_approach_points(ball_pos, hoop_pos, up_frame)
    predicted_cx, tier = _fit_rim_crossing(points, rim_y, hoop_pos)

    if predicted_cx is None:
        return False, tier

    is_made = _check_rim_crossing(predicted_cx, hoop_pos)

    hcx = hoop_pos[-1][0]
    hw  = hoop_pos[-1][3]
    rim_x1 = hcx - SCORE_RIM_X_FRACTION * hw - SCORE_REBOUND_PX
    rim_x2 = hcx + SCORE_RIM_X_FRACTION * hw + SCORE_REBOUND_PX
    detail = (
        f"{tier}  pred_cx={predicted_cx:.1f}  "
        f"rim=[{rim_x1:.1f}..{rim_x2:.1f}]"
    )
    return is_made, detail


def _find_apex(ball_pos: list, up_frame: int, down_frame: int) -> Optional[tuple]:
    """
    Return the ball detection with minimum cy (highest image point) in the
    frame range [up_frame, down_frame]. Falls back to the last detection
    if no entries fall in that range (window expired).
    """
    candidates = [p for p in ball_pos if up_frame <= p[2] <= down_frame]
    if candidates:
        return min(candidates, key=lambda p: p[1])
    return ball_pos[-1] if ball_pos else None


# ── Weak-hoop fallback helpers ────────────────────────────────────────────────

def _compute_hoop_fallback_consensus(
    weak_hoop_raw: list,
    min_frames: int,
) -> Optional[tuple]:
    """
    Given a list of weak hoop detections collected during the main YOLO pass
    (cx, cy, frame_idx, w, h, conf), deduplicate by frame (keep highest-conf
    box per frame) and compute the axis-aligned intersection of all remaining
    bounding boxes.

    Returns a synthetic hoop tuple suitable for injection into hoop_pos:
        (cx, cy, 0, side, side, HOOP_FALLBACK_CONF_MIN)
    where (cx, cy) is the intersection centre and `side` is the average of the
    intersection width and height, making the box square so it passes the
    _clean_hoop_pos aspect-ratio check.

    Returns None if fewer than `min_frames` unique-frame boxes exist or if the
    intersection is empty (boxes spread across different positions in frame).
    """
    if not weak_hoop_raw:
        return None

    # Deduplicate: keep highest-confidence detection per frame index.
    by_frame: dict = {}
    for det in weak_hoop_raw:
        cx, cy, fi, w, h, conf = det
        if fi not in by_frame or conf > by_frame[fi][5]:
            by_frame[fi] = det

    deduped = list(by_frame.values())
    if len(deduped) < min_frames:
        logger.debug(
            "Weak-hoop fallback: only %d unique-frame boxes (need >= %d)",
            len(deduped), min_frames,
        )
        return None

    # Compute full axis-aligned intersection of all deduplicated boxes.
    ix1 = max(d[0] - d[3] / 2.0 for d in deduped)
    iy1 = max(d[1] - d[4] / 2.0 for d in deduped)
    ix2 = min(d[0] + d[3] / 2.0 for d in deduped)
    iy2 = min(d[1] + d[4] / 2.0 for d in deduped)

    if ix2 <= ix1 or iy2 <= iy1:
        logger.debug(
            "Weak-hoop fallback: intersection empty across %d boxes — "
            "detections do not share a common overlap region",
            len(deduped),
        )
        return None

    fb_cx = (ix1 + ix2) / 2.0
    fb_cy = (iy1 + iy2) / 2.0
    # Synthesize a square box: average of intersection w and h so that the
    # aspect-ratio check in _clean_hoop_pos (w/h <= HOOP_CLEAN_WH_RATIO) passes.
    side = max(((ix2 - ix1) + (iy2 - iy1)) / 2.0, 4.0)  # floor at 4 px

    logger.debug(
        "Weak-hoop fallback: consensus at (%.1f, %.1f)  side=%.1f px  "
        "from %d unique-frame boxes",
        fb_cx, fb_cy, side, len(deduped),
    )
    return (fb_cx, fb_cy, 0, side, side, HOOP_FALLBACK_CONF_MIN)


def _run_state_machine_with_fallback(
    all_ball_raw: list,
    fallback_hoop_tuple: tuple,
    frame_count: int,
) -> list[dict]:
    """
    Re-run the shot state machine over the stored ball detections from the main
    pass, using a stable synthetic hoop position (the weak-hoop fallback
    consensus).  No YOLO inference is performed — this is a pure state-machine
    replay.

    `all_ball_raw`: full chronological list of accepted ball detections from
    the main pass: [(cx, cy, frame_idx, w, h, conf), ...].

    The fallback hoop is held constant for the entire clip (static-camera
    assumption).  It is fed to hoop_pos as a fresh entry at each YOLO-stride
    frame so rolling-window eviction in the helpers never fires.

    Returns shot_event dicts in the same format as the main pass.
    """
    from collections import defaultdict

    ball_by_frame: dict = defaultdict(list)
    for det in all_ball_raw:
        ball_by_frame[det[2]].append(det)

    fb_cx, fb_cy, _, fb_w, fb_h, fb_conf = fallback_hoop_tuple
    # Stable single-entry hoop list — never passed through _clean_hoop_pos.
    hoop_pos = [(fb_cx, fb_cy, 0, fb_w, fb_h, fb_conf)]

    ball_pos: list      = []
    shot_events: list   = []
    up                  = False
    down                = False
    up_frame: int       = 0
    down_frame: int     = 0

    for frame_idx in range(frame_count + 1):
        if frame_idx % FRAME_STRIDE == 0:
            for det in ball_by_frame.get(frame_idx, []):
                ball_pos.append(det)
                ball_pos = _clean_ball_pos(ball_pos, frame_idx)

            if ball_pos:
                if not up and _detect_up(ball_pos, hoop_pos):
                    up       = True
                    up_frame = ball_pos[-1][2]
                if up and not down and _detect_down(ball_pos, hoop_pos):
                    down       = True
                    down_frame = ball_pos[-1][2]

        if frame_idx % ATTEMPT_CONFIRM_EVERY == 0:
            if up and down and up_frame < down_frame:
                if up_frame < MIN_FIRST_SHOT_FRAME:
                    logger.info(
                        "[fallback] Ignoring early attempt (up_frame=%d < %d)",
                        up_frame, MIN_FIRST_SHOT_FRAME,
                    )
                elif down_frame - up_frame <= ATTEMPT_MAX_FRAME_GAP:
                    is_made, score_detail = _score(ball_pos, hoop_pos, up_frame)
                    if not is_made:
                        tg_ok, tg_detail = _check_two_gate_presence(
                            ball_pos, hoop_pos, up_frame, down_frame
                        )
                        if tg_ok:
                            is_made = True
                            score_detail += "  +two_gate:" + tg_detail
                        else:
                            score_detail += "  two_gate:" + tg_detail
                    apex = _find_apex(ball_pos, up_frame, down_frame)
                    if apex is not None:
                        ball_window = [
                            p for p in ball_pos if up_frame <= p[2] <= down_frame
                        ]
                        shot_events.append({
                            "frame_index": apex[2],
                            "u":           int(apex[0]),
                            "v":           int(apex[1]),
                            "result":      "made" if is_made else "missed",
                            "ball_points_window": ball_window,
                            "ball_pos_snapshot":  list(ball_pos),
                            "up_frame":           up_frame,
                            "down_frame":         down_frame,
                            "hoop_stable":        list(hoop_pos[-1]),
                        })
                        logger.info(
                            "[fallback] Shot at frame %d: %s  [%s]  "
                            "(up=%d  down=%d  ball_window=%d pts)",
                            apex[2], "made" if is_made else "missed",
                            score_detail, up_frame, down_frame, len(ball_window),
                        )
                up   = False
                down = False

    return shot_events


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _run_pipeline_inner(video_path: str) -> tuple[list[dict], dict]:
    """
    Single-pass pipeline: process video frame by frame, maintaining rolling
    state for hoop and ball positions, running the shot state machine, and
    collecting diagnostic data.

    Returns (shot_points, diagnostic_data).
    """
    path = Path(video_path)
    if not path.exists():
        raise RuntimeError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV cannot open video: {video_path}")

    fps          = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    logger.info(
        "Processing video: %s  fps=%.1f  frames=%d  h=%d",
        path.name, fps, frame_count, frame_height,
    )

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is not installed. Run: pip install ultralytics"
        ) from exc

    model_path = Path(__file__).parent / YOLO_MODEL_PATH
    if not model_path.exists():
        raise RuntimeError(
            f"YOLO model not found: {model_path}\n"
            "Download best.pt from "
            "https://github.com/avishah3/AI-Basketball-Shot-Detection-Tracker"
        )
    model = YOLO(str(model_path))

    # Rolling state (entries: (cx, cy, frame_index, w, h, conf))
    ball_pos: list = []
    hoop_pos: list = []
    all_hoop_pos: list = []  # every accepted hoop detection — for median/diagnostics

    # Weak-hoop fallback accumulators (Session 8).
    # weak_hoop_raw: hoop boxes at HOOP_FALLBACK_CONF_MIN ≤ conf < HOOP_CONF_THRESHOLD.
    # all_ball_raw:  every accepted ball detection; used for fallback state-machine replay.
    weak_hoop_raw: list = []
    all_ball_raw:  list = []

    # Shot state machine
    up: bool       = False
    down: bool     = False
    up_frame: int  = 0
    down_frame: int = 0

    # Diagnostic counters
    hoop_raw_count        = 0
    hoop_accepted_count   = 0
    ball_raw_count        = 0
    ball_accepted_count   = 0
    ball_near_hoop_count  = 0

    shot_events: list[dict] = []
    frame_idx = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx % FRAME_STRIDE == 0:
            # Run at HOOP_FALLBACK_CONF_MIN so weak hoop candidates are visible
            # for the fallback consensus.  Per-class thresholds are applied below.
            results = model(frame, verbose=False, conf=HOOP_FALLBACK_CONF_MIN)

            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    w    = x2 - x1
                    h    = y2 - y1
                    cx   = (x1 + x2) / 2.0
                    cy   = (y1 + y2) / 2.0
                    conf = float(box.conf[0])
                    cls  = int(box.cls[0])

                    if cls == 0:  # Basketball
                        ball_raw_count += 1
                        near = _in_hoop_region(cx, cy, hoop_pos)
                        threshold = BALL_CONF_NEAR_HOOP if near else BALL_CONF_THRESHOLD
                        if conf >= threshold:
                            ball_accepted_count += 1
                            if near:
                                ball_near_hoop_count += 1
                            ball_pos.append((cx, cy, frame_idx, w, h, conf))
                            all_ball_raw.append((cx, cy, frame_idx, w, h, conf))
                            ball_pos = _clean_ball_pos(ball_pos, frame_idx)

                    elif cls == 1:  # Basketball Hoop
                        hoop_raw_count += 1
                        if conf >= HOOP_CONF_THRESHOLD:
                            hoop_accepted_count += 1
                            hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                            hoop_pos = _clean_hoop_pos(hoop_pos)
                            all_hoop_pos.append((cx, cy, frame_idx, w, h, conf))
                        elif conf >= HOOP_FALLBACK_CONF_MIN:
                            # Below production threshold but above fallback minimum —
                            # collect for consensus computation after the loop.
                            weak_hoop_raw.append((cx, cy, frame_idx, w, h, conf))

            # State machine — only runs when both hoop and ball are known
            if hoop_pos and ball_pos:
                if not up:
                    if _detect_up(ball_pos, hoop_pos):
                        up = True
                        up_frame = ball_pos[-1][2]

                if up and not down:
                    if _detect_down(ball_pos, hoop_pos):
                        down = True
                        down_frame = ball_pos[-1][2]

        # Attempt confirmation poll — every ATTEMPT_CONFIRM_EVERY real frames
        if frame_idx % ATTEMPT_CONFIRM_EVERY == 0:
            if up and down and up_frame < down_frame:
                if up_frame < MIN_FIRST_SHOT_FRAME:
                    logger.info(
                        "Ignoring early attempt (up_frame=%d < %d)",
                        up_frame, MIN_FIRST_SHOT_FRAME,
                    )
                elif down_frame - up_frame <= ATTEMPT_MAX_FRAME_GAP:
                    is_made, score_detail = _score(ball_pos, hoop_pos, up_frame)
                    if not is_made:
                        tg_ok, tg_detail = _check_two_gate_presence(
                            ball_pos, hoop_pos, up_frame, down_frame
                        )
                        if tg_ok:
                            is_made = True
                            score_detail += "  +two_gate:" + tg_detail
                        else:
                            score_detail += "  two_gate:" + tg_detail
                    apex = _find_apex(ball_pos, up_frame, down_frame)
                    if apex is not None:
                        # Phase 1: capture raw trajectory data for OriginEstimator.
                        # ball_pos at this point still contains the rolling window,
                        # including pre-up_frame detections (ball at shooter level).
                        # We snapshot it now before the window rolls further.
                        ball_window = [
                            p for p in ball_pos
                            if up_frame <= p[2] <= down_frame
                        ]
                        shot_events.append({
                            # ── Legacy fields (apex) ──────────────────────────
                            # Used ONLY by test_cv.py debug video and per-shot
                            # table.  NOT written to AnalyzeResult.shot_points.
                            # origin.pixel in the contract is computed by
                            # OriginEstimator below (trajectory-anchor, Phase 2).
                            "frame_index": apex[2],
                            "u":           int(apex[0]),
                            "v":           int(apex[1]),
                            # ── Result (shared) ───────────────────────────────
                            "result": "made" if is_made else "missed",
                            # ── Raw data for OriginEstimator (internal only) ───
                            # Never propagated to the AnalyzeResult contract.
                            # Enables trajectory-anchor origin now and the future
                            # release+pose estimator (Phase 6) without re-running
                            # the pipeline.
                            "ball_points_window": ball_window,
                            "ball_pos_snapshot":  list(ball_pos),
                            "up_frame":           up_frame,
                            "down_frame":         down_frame,
                            "hoop_stable": list(hoop_pos[-1]) if hoop_pos else None,
                        })
                        logger.info(
                            "Shot at frame %d: %s  [%s]  "
                            "(up=%d  down=%d  ball_window=%d pts)",
                            apex[2], "made" if is_made else "missed",
                            score_detail, up_frame, down_frame, len(ball_window),
                        )
                up = False
                down = False

        frame_idx += 1

    cap.release()

    # ── Weak-hoop fallback ────────────────────────────────────────────────────
    # Triggered only when regular hoop detection was insufficient AND the normal
    # pass produced no confirmed shots.  Clips with strong regular hoop signal
    # (e.g. clip 1: 228 accepted) are never affected.
    hoop_fallback_used = False
    if hoop_accepted_count < HOOP_FALLBACK_REGULAR_MIN and not shot_events:
        fb_tuple = _compute_hoop_fallback_consensus(
            weak_hoop_raw, HOOP_FALLBACK_MIN_FRAMES
        )
        if fb_tuple is not None:
            logger.info(
                "Weak-hoop fallback activated: consensus at (%.0f, %.0f)  "
                "size=%.0f×%.0f px  weak_frames=%d — re-running state machine",
                fb_tuple[0], fb_tuple[1], fb_tuple[2], fb_tuple[3],
                len({d[2] for d in weak_hoop_raw}),
            )
            shot_events = _run_state_machine_with_fallback(
                all_ball_raw, fb_tuple, frame_count
            )
            hoop_fallback_used = True
            # Populate all_hoop_pos from the fallback so stable_hoop and the
            # debug video reflect the consensus hoop position.
            if not all_hoop_pos:
                fb_cx, fb_cy, _, fb_w, fb_h, _ = fb_tuple
                all_hoop_pos = [(fb_cx, fb_cy, 0, fb_w, fb_h, HOOP_FALLBACK_CONF_MIN)]
            logger.info(
                "Weak-hoop fallback: %d shot(s) confirmed via consensus hoop",
                len(shot_events),
            )
        else:
            logger.info(
                "Weak-hoop fallback: not triggered — consensus could not be computed "
                "(%d unique-frame weak boxes, need >= %d with overlapping bboxes)",
                len({d[2] for d in weak_hoop_raw}),
                HOOP_FALLBACK_MIN_FRAMES,
            )

    logger.info(
        "Pipeline complete.  Ball %d/%d accepted  "
        "Hoop %d/%d accepted  Shots detected: %d%s",
        ball_accepted_count, ball_raw_count,
        hoop_accepted_count, hoop_raw_count,
        len(shot_events),
        "  [fallback hoop]" if hoop_fallback_used else "",
    )

    # Canonical hoop position — median of all accepted detections.
    # Stable for a static camera; used by test_cv.py debug video.
    stable_hoop: Optional[tuple[int, int, int, int]] = None
    if all_hoop_pos:
        med_cx = float(np.median([p[0] for p in all_hoop_pos]))
        med_cy = float(np.median([p[1] for p in all_hoop_pos]))
        med_w  = float(np.median([p[3] for p in all_hoop_pos]))
        med_h  = float(np.median([p[4] for p in all_hoop_pos]))
        # (x, y, w, h) top-left format — same as old hoop_roi for debug video compat
        stable_hoop = (
            int(med_cx - med_w / 2),
            int(med_cy - med_h / 2),
            int(med_w),
            int(med_h),
        )

    # Format as ShotPoint list per the frozen AnalyzeResult contract.
    #
    # Phase 2: origin.pixel is now computed by OriginEstimator (trajectory-
    # anchor baseline) instead of _find_apex.  Semantically: the apex is the
    # ball's highest mid-air point — irrelevant for court position.  The
    # trajectory anchor finds the ball near the shot start (before/at up_frame,
    # below the hoop line), which is geometrically closest to where the shooter
    # was standing on the court.
    #
    # _find_apex is still used to drive the debug-video markers in test_cv.py
    # (stored as legacy ev["u"]/ev["v"]/ev["frame_index"]).  It is NOT used here.
    shot_points: list[dict] = []
    for i, ev in enumerate(shot_events, start=1):
        origin_pixel = _origin_estimator.estimate(ev)
        shot_points.append({
            "shot_id": f"s{i:03d}",
            "result":  ev["result"],
            "origin": {
                "pixel": origin_pixel,   # trajectory-anchor (Phase 2)
                "court": None,           # populated by CourtMapper (Phase 3)
            },
            "zone": None,               # populated by ZoneClassifier (Phase 4)
        })

    diag: dict = {
        "hoop_raw_count":       hoop_raw_count,
        "hoop_accepted_count":  hoop_accepted_count,
        "hoop_stable_bbox":     stable_hoop,       # (x, y, w, h) top-left
        "hoop_detections_all":  all_hoop_pos,      # every accepted detection
        "ball_raw_count":       ball_raw_count,
        "ball_accepted_count":  ball_accepted_count,
        "ball_near_hoop_count": ball_near_hoop_count,
        "shot_events":          shot_events,
        "fps":                  fps,
        "frame_count":          frame_count,
        "frame_height":         frame_height,
    }

    return shot_points, diag


# ── Public API ────────────────────────────────────────────────────────────────

def process_video(video_path: str) -> list[dict]:
    """
    Analyse a basketball training video and return a list of ShotPoint dicts
    conforming to the frozen AnalyzeResult contract:

        {
            "shot_id":  "s001",
            "result":   "made" | "missed",
            "origin": {
                "pixel":  {"u": int, "v": int, "frame_index": int},
                "court":  None,   # not computed — requires court detection (step 6)
            },
            "zone": None,         # not computed — requires origin.court
        }

    Raises RuntimeError on unrecoverable errors (missing model, corrupt file).
    Returns an empty list if the video is valid but no shots were detected.
    """
    shot_points, _ = _run_pipeline_inner(video_path)
    return shot_points


def _run_pipeline_verbose(video_path: str) -> dict:
    """
    Run the full pipeline and return detailed diagnostic data.
    Used by test_cv.py. Not part of the public API contract.

    Returned dict keys:
      hoop_raw_count, hoop_accepted_count, hoop_stable_bbox,
      hoop_detections_all, ball_raw_count, ball_accepted_count,
      ball_near_hoop_count, shot_events, fps, frame_count,
      frame_height, shot_points
    """
    shot_points, diag = _run_pipeline_inner(video_path)
    return {**diag, "shot_points": shot_points}
