"""
xShot AI — CV pipeline (Demo v1)

Architecture: rolling-window state machine adapted from
  avishah3/AI-Basketball-Shot-Detection-Tracker (2023).

Responsibilities:
  - Detect the hoop and basketball with a YOLO model trained on both classes.
  - Detect shot attempts via a zone state machine (up-zone → down-zone).
  - Classify each attempt as make or miss via entry_make_miss.score_shot()
    (blue rim chord 94% + confirmation zone + shot-window trajectory rescue).

Contract:
  - process_video(path) → list of ShotPoint dicts matching AnalyzeResult.shot_points.
  - When court_mapper is provided, origin.court and zone are populated per shot.
  - Returns an empty list if the video is valid but no shots were detected.
  - Raises RuntimeError on unrecoverable errors (corrupt file, model not found).

Model requirement:
  - best.pt (YOLOv8n, ~6 MB) must be present in the backend/ directory.
  - Download from: https://github.com/avishah3/AI-Basketball-Shot-Detection-Tracker
  - Classes: 0 = Basketball, 1 = Basketball Hoop.

Algorithm credit:
  - Core detection logic adapted from avishah3/AI-Basketball-Shot-Detection-Tracker.
  - Make/miss: entry rule in entry_make_miss.py (blue chord + confirmation gate).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from origin_estimator import OriginEstimator
from release_estimator import ReleaseEstimator
from court_mapper import CourtMapper

import entry_make_miss
from shot_data_builder import build_shot_data, ShotData

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

# Make/miss classification: entry_make_miss.score_shot() — see entry_make_miss.py and
# xshot_make_miss_entry_diagnostic_all/DIAGNOSTIC_RULES_SPEC.txt

# Ignore shot attempts whose up_frame is before this frame index.
# Prevents false triggers when the video starts mid-shot.
# Set low (5 frames ≈ 0.17s) — only rejects truly instant triggers.
MIN_FIRST_SHOT_FRAME = 5

# Module-level singleton.
# ReleaseEstimator runs bounded per-shot frame checks only after shot confirmation.
_origin_estimator = OriginEstimator(
    release_estimator=ReleaseEstimator(
        ball_model_path=Path(__file__).parent / YOLO_MODEL_PATH,
        person_model_path=Path(__file__).parent / "yolov8n.pt",
        ball_conf_min=BALL_CONF_THRESHOLD,
        person_conf_min=0.25,
        backward_step=25,
        forward_step=5,
        backward_max_delta=200,
        forward_post_up_cap=5,
    )
)

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
    video_path: str,
    model: Any,
    frame_width: int,
    hoop_accepted_count: int,
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
                    is_made, score_detail = entry_make_miss.score_shot(
                        video_path, model, ball_pos, hoop_pos,
                        up_frame, down_frame, frame_count, frame_width,
                        hoop_accepted_count,
                    )
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


# ── Floor-origin helper ───────────────────────────────────────────────────────

def _detect_player_feet(
    video_path: str,
    up_frame: int,
    person_model,
) -> tuple[Optional[int], Optional[int]]:
    """
    Return the (u, v) pixel of the largest detected person's feet
    in a window of frames before up_frame.  Feet = bottom-centre of the
    person bounding box, which lies on the court floor — unlike the
    ball (chest height), which cannot be accurately mapped through
    a floor-plane homography.

    Scans every 3rd frame in [up_frame-30, up_frame-3] and returns the
    detection with the largest bounding-box area across all sampled frames.
    This is more robust than a single-frame lookup, which can miss the person
    if YOLO has a transient detection gap.

    Returns (None, None) if no person is detected or the model is absent.
    """
    if person_model is None:
        return None, None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, None

    best_area = 0
    foot_u, foot_v = None, None
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
                    foot_v = int(y2)   # bottom of bbox ≈ feet on floor

    cap.release()
    return foot_u, foot_v


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _run_pipeline_inner(video_path: str, court_mapper: Optional[CourtMapper] = None) -> tuple[list[dict], dict]:
    """Default: single-pass runtime. Set XSHOT_LEGACY_PIPELINE=1 for double-pass rollback."""
    import os
    if os.environ.get("XSHOT_LEGACY_PIPELINE", "0") == "1":
        return _run_pipeline_inner_legacy(video_path, court_mapper)
    from single_pass_pipeline import run as single_pass_run
    return single_pass_run(video_path, court_mapper)


def _run_pipeline_inner_legacy(video_path: str, court_mapper: Optional[CourtMapper] = None) -> tuple[list[dict], dict]:
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
    frame_width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
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
                    ball_window = [
                        p for p in ball_pos if up_frame <= p[2] <= down_frame
                    ]
                    ev_dict = {
                        "ball_points_window": ball_window,
                        "ball_pos_snapshot":  list(ball_pos),
                        "up_frame":           up_frame,
                        "down_frame":         down_frame,
                        "hoop_stable": list(hoop_pos[-1]) if hoop_pos else None,
                        "_video_path": str(path),
                    }
                    shot_data = build_shot_data(
                        str(path), model, ev_dict,
                        up_frame, down_frame, frame_count, frame_width,
                        hoop_accepted_count,
                    )
                    is_made, score_detail = entry_make_miss.score_shot_from_data(
                        shot_data, frame_width, hoop_accepted_count,
                    )
                    apex = _find_apex(ball_pos, up_frame, down_frame)
                    if apex is not None:
                        ev_dict["frame_index"] = apex[2]
                        ev_dict["u"]           = int(apex[0])
                        ev_dict["v"]           = int(apex[1])
                        ev_dict["result"]      = "made" if is_made else "missed"
                        ev_dict["_shot_data"]  = shot_data
                        shot_events.append(ev_dict)
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
                all_ball_raw,
                fb_tuple,
                frame_count,
                str(path),
                model,
                frame_width,
                hoop_accepted_count,
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
    # Internal-only context for OriginEstimator plug-ins (e.g., ReleaseEstimator).
    # Load the person-detection model once — used by shot_data_builder for feet detection.
    _person_model = None
    if court_mapper is not None:
        person_model_path = Path(__file__).parent / "yolov8n.pt"
        if person_model_path.exists():
            from ultralytics import YOLO as _YOLO
            _person_model = _YOLO(str(person_model_path))
            logger.info("Loaded person model for floor-origin detection")
        else:
            logger.warning("yolov8n.pt not found — falling back to ball pixel for court mapping")

    # When court_mapper is active, rebuild shot_data with person detection included.
    # shot_data was built during the confirmation loop without person_model; rebuild
    # it now if court_mapper is present so person_feet is populated.
    if court_mapper is not None and _person_model is not None:
        for ev in shot_events:
            sd: ShotData = ev.get("_shot_data")
            if sd is not None and sd.person_feet is None:
                sd.person_feet = __import__("shot_data_builder")._scan_person_feet(
                    str(path), ev["up_frame"], _person_model
                )

    shot_points: list[dict] = []
    for i, ev in enumerate(shot_events, start=1):
        origin_pixel = _origin_estimator.estimate(ev)

        court = None
        zone  = None
        if court_mapper is not None:
            # Use person_feet from ShotData (pre-shot person scan) when available.
            sd = ev.get("_shot_data")
            floor_u: Optional[int] = None
            floor_v: Optional[int] = None
            if sd is not None and sd.person_feet is not None:
                floor_u, floor_v = sd.person_feet

            using_ball_pixel = False
            if floor_u is not None:
                logger.info("Shot s%03d feet pixel = (%d, %d)", i, floor_u, floor_v)
            elif origin_pixel is not None:
                floor_u = origin_pixel.get("u")
                floor_v = origin_pixel.get("v")
                using_ball_pixel = True
                logger.info("Shot s%03d no person found — using ball pixel (%s, %s)", i, floor_u, floor_v)

            if floor_u is not None and floor_v is not None:
                # When ball pixel is used, it is aerial (not on the floor), so the
                # floor-plane homography gives an unreliable x-coordinate.  Pass the
                # hoop's pixel x as a reference so classify_zone can determine
                # left/right by direct pixel comparison instead of via homography.
                hoop = ev.get("hoop_stable")
                hoop_cx = int(hoop[0]) if hoop else None
                pixel_side_ref = (floor_u, hoop_cx) if using_ball_pixel and hoop_cx is not None else None
                court, zone = court_mapper.map_shot(floor_u, floor_v, pixel_side_ref=pixel_side_ref)
                logger.info("Shot s%03d court = %s  zone = %s", i, court, zone)

        # Trajectory metadata — arc height and apex pixel for debug/UI.
        hs     = ev.get("hoop_stable")          # [cx, cy, frame_idx, w, h, conf]
        apex_v = ev.get("v")
        arc_px: Optional[float] = None
        if hs is not None and apex_v is not None:
            rim_top_y = hs[1] - hs[4] / 2
            arc_px = round(rim_top_y - apex_v, 1)

        shot_points.append({
            "shot_id": f"s{i:03d}",
            "result":  ev["result"],
            "origin": {
                "pixel": origin_pixel,
                "court": court,
            },
            "zone": zone,
            "trajectory": {
                "arc_height_px": arc_px,
                "apex_pixel": {
                    "u":           ev["u"],
                    "v":           ev["v"],
                    "frame_index": ev["frame_index"],
                },
                "up_frame":   ev["up_frame"],
                "down_frame": ev["down_frame"],
            },
        })

    diag: dict = {
        "hoop_fallback_used":   hoop_fallback_used,
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

def process_video(
    video_path: str,
    court_mapper: Optional[CourtMapper] = None,
) -> list[dict]:
    """
    Analyse a basketball training video and return a list of ShotPoint dicts
    conforming to the frozen AnalyzeResult contract.

    If court_mapper is provided (built from user calibration), origin.court
    and zone are populated for each shot; otherwise they remain None.

    Raises RuntimeError on unrecoverable errors (missing model, corrupt file).
    Returns an empty list if the video is valid but no shots were detected.
    """
    shot_points, _ = _run_pipeline_inner(video_path, court_mapper)
    return shot_points


def _run_pipeline_verbose(video_path: str, court_mapper: Optional[CourtMapper] = None) -> dict:
    """
    Run the full pipeline and return detailed diagnostic data.
    Used by test_cv.py. Not part of the public API contract.

    Returned dict keys:
      hoop_raw_count, hoop_accepted_count, hoop_stable_bbox,
      hoop_detections_all, ball_raw_count, ball_accepted_count,
      ball_near_hoop_count, shot_events, fps, frame_count,
      frame_height, shot_points
    """
    shot_points, diag = _run_pipeline_inner(video_path, court_mapper)
    return {**diag, "shot_points": shot_points}
