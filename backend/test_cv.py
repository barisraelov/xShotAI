"""
xShot AI — CV pipeline validation runner

Usage:
    python test_cv.py <video_path> [--debug-video]

    <video_path>    Path to your .mp4 training clip (relative or absolute).
    --debug-video   Write an annotated video to test_videos/output/ (slower).

What this script does:
    Runs _run_pipeline_verbose() — a single-pass of the full pipeline — then
    prints a structured diagnostic report in four stages:

    [ Stage 1 ]  Hoop detection — how many frames YOLO found the hoop,
                 where the canonical (median) position ended up, and whether
                 it looks correct.

    [ Stage 2 ]  Ball detection — total raw YOLO detections, how many
                 survived cleaning, and how many triggered the lower-confidence
                 near-hoop threshold.

    [ Stage 3 ]  Shot events — attempt count, makes, misses, FG%, and a
                 per-shot table with frame index, timestamp, pixel position,
                 and make/miss verdict.

    [ Stage 4 ]  Full pipeline JSON — the exact shot_points list that
                 process_video() returns (same format as AnalyzeResult).

    (Optional)   Debug video with yellow hoop box and green/red shot markers.

Exit codes: 0 = success (even if 0 shots found), 1 = pipeline error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
from pathlib import Path

import cv2

# Ensure we import from the same directory regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))
import cv_pipeline  # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Debug video writer ────────────────────────────────────────────────────────

def _write_debug_video(
    video_path: Path,
    hoop_bbox: tuple[int, int, int, int] | None,
    shot_events: list[dict],
    out_path: Path,
) -> None:
    """
    Re-read the video and write an annotated copy with:
      - Yellow rectangle at the canonical (median) hoop bounding box
      - Thin yellow circle at the hoop centre
      - Green filled circle + "MADE" label at apex frame of each make
      - Red filled circle + "MISS" label at apex frame of each miss
      - Frame index printed top-left
    """
    cap    = cv2.VideoCapture(str(video_path))
    fps    = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))

    # Build lookup: frame_index → shot event
    shot_lookup: dict[int, dict] = {ev["frame_index"]: ev for ev in shot_events}

    hoop_cx = hoop_cy = 0
    hoop_rect: tuple[int, int, int, int] | None = None
    if hoop_bbox is not None:
        hx, hy, hw, hh = hoop_bbox
        hoop_cx = hx + hw // 2
        hoop_cy = hy + hh // 2
        hoop_rect = (hx, hy, hx + hw, hy + hh)

    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if hoop_rect:
            cv2.rectangle(frame, (hoop_rect[0], hoop_rect[1]),
                          (hoop_rect[2], hoop_rect[3]), (0, 255, 255), 2)
            cv2.circle(frame, (hoop_cx, hoop_cy), 4, (0, 255, 255), -1)

        if frame_idx in shot_lookup:
            ev    = shot_lookup[frame_idx]
            color = (0, 200, 0) if ev["result"] == "made" else (0, 0, 220)
            label = "MADE"      if ev["result"] == "made" else "MISS"
            cv2.circle(frame, (ev["u"], ev["v"]), 18, color, 3)
            cv2.putText(frame, label, (ev["u"] + 22, ev["v"] + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        cv2.putText(frame, f"frame {frame_idx}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()
    logger.info("Debug video written -> %s", out_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the xShot AI CV pipeline on a real video clip.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", help="Path to the .mp4 basketball training clip")
    parser.add_argument(
        "--debug-video",
        action="store_true",
        help="Write an annotated debug video to test_videos/output/",
    )
    args = parser.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        print(f"\n[ERROR] File not found: {video_path}\n")
        return 1

    # ── Basic video info ──────────────────────────────────────────────────────
    cap_info = cv2.VideoCapture(str(video_path))
    if not cap_info.isOpened():
        print(f"\n[ERROR] OpenCV cannot open: {video_path}\n")
        return 1

    fps_info         = cap_info.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count_info = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_width      = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height     = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_s       = frame_count_info / fps_info
    cap_info.release()

    print("\n" + "=" * 62)
    print("  xShot AI — CV Pipeline Validation")
    print("=" * 62)
    print(f"  File       : {video_path.name}")
    print(f"  Size       : {video_path.stat().st_size / 1_048_576:.1f} MB")
    print(f"  Duration   : {duration_s:.1f} s  ({frame_count_info} frames @ {fps_info:.1f} fps)")
    print(f"  Resolution : {frame_width}×{frame_height}")
    print(f"  Model      : {cv_pipeline.YOLO_MODEL_PATH}  (frame stride: {cv_pipeline.FRAME_STRIDE})")
    print("=" * 62 + "\n")

    # ── Run pipeline (single pass) ────────────────────────────────────────────
    print("Running pipeline — this may take a few minutes on CPU …\n")
    try:
        diag = cv_pipeline._run_pipeline_verbose(str(video_path))
    except RuntimeError as exc:
        print(f"\n[ERROR] Pipeline failed: {exc}\n")
        return 1

    fps          = diag["fps"]
    shot_events  = diag["shot_events"]
    hoop_bbox    = diag["hoop_stable_bbox"]

    # ── Stage 1: Hoop detection ───────────────────────────────────────────────
    print("[ Stage 1 ]  Hoop detection (YOLO Basketball Hoop class)")
    print(f"  Raw YOLO detections : {diag['hoop_raw_count']}")
    print(f"  After cleaning      : {diag['hoop_accepted_count']}")

    if hoop_bbox is None:
        print("  RESULT : *** HOOP NOT FOUND ***")
        print("  IMPACT : All shots will be classified as MISSED (no make detection).")
        print("  ACTION : Check that best.pt is present and the hoop is visible in the footage.")
        print("           Lower HOOP_CONF_THRESHOLD (currently "
              f"{cv_pipeline.HOOP_CONF_THRESHOLD}) if the model is confident but below threshold.")
    else:
        hx, hy, hw, hh = hoop_bbox
        hcx = hx + hw // 2
        hcy = hy + hh // 2
        upper_frac = hcy / frame_height
        print(f"  RESULT : Hoop found at centre=({hcx}, {hcy})  size={hw}×{hh} px")
        print(f"  Height : {upper_frac:.0%} from top of frame")

        # Confidence distribution over all accepted hoop detections
        confs = [p[5] for p in diag["hoop_detections_all"]]
        if confs:
            print(f"  Conf   : min={min(confs):.2f}  median={sorted(confs)[len(confs)//2]:.2f}  max={max(confs):.2f}")

        if upper_frac > 0.70:
            print("  WARNING: Hoop is in the lower 30% of the frame. Expected upper portion.")
            print("           Check camera framing or lower HOOP_CONF_THRESHOLD.")
        else:
            print("  OK     : Hoop position looks reasonable (upper portion of frame).")
    print()

    # ── Stage 2: Ball detection ───────────────────────────────────────────────
    print("[ Stage 2 ]  Ball detection (YOLO Basketball class)")
    print(f"  Raw YOLO detections   : {diag['ball_raw_count']}")
    print(f"  After cleaning        : {diag['ball_accepted_count']}")
    print(f"  Near-hoop detections  : {diag['ball_near_hoop_count']}  "
          f"(used lower conf {cv_pipeline.BALL_CONF_NEAR_HOOP})")

    if diag["ball_raw_count"] == 0:
        print("\n  WARNING: YOLO found NO ball detections at all.")
        print("  ACTION : Lower BALL_CONF_THRESHOLD (currently "
              f"{cv_pipeline.BALL_CONF_THRESHOLD}).")
        print("           Check that the ball is clearly visible and the footage is not")
        print("           a screen recording (double-compressed video degrades detection).")
    elif diag["ball_accepted_count"] == 0:
        print("\n  WARNING: Ball was detected but all detections were cleaned out.")
        print("  ACTION : Lower BALL_CONF_THRESHOLD or BALL_CLEAN_JUMP_FACTOR.")
    else:
        accept_rate = diag["ball_accepted_count"] / max(diag["ball_raw_count"], 1) * 100
        print(f"  Accept rate           : {accept_rate:.0f}%")
    print()

    # ── Stage 3: Shot events ──────────────────────────────────────────────────
    print("[ Stage 3 ]  Shot detection and make/miss classification")

    makes  = [e for e in shot_events if e["result"] == "made"]
    misses = [e for e in shot_events if e["result"] == "missed"]

    print(f"  Shots detected : {len(shot_events)}")
    print(f"  Makes          : {len(makes)}")
    print(f"  Misses         : {len(misses)}")
    if shot_events:
        fg = len(makes) / len(shot_events) * 100
        print(f"  FG%%            : {fg:.1f}%%")
    print()

    if shot_events:
        # frame_index/u/v here are the APEX (highest mid-air point) — used for
        # debug-video marker placement.  origin.pixel in Stage 4 (AnalyzeResult)
        # uses the trajectory-anchor baseline from OriginEstimator (Phase 2),
        # which is the ball's position near the shot start, not the apex.
        print("  Per-shot details (debug marker = apex; origin.pixel in Stage 4 = trajectory anchor):")
        print(f"  {'Shot':>5}  {'Frame':>6}  {'Time':>6}  {'Apex (u,v)':>14}  Result")
        print("  " + "-" * 52)
        for i, ev in enumerate(shot_events, start=1):
            t = ev["frame_index"] / fps
            print(f"  s{i:03d}   {ev['frame_index']:6d}  {t:5.1f}s  "
                  f"({ev['u']:4d},{ev['v']:4d})        {ev['result'].upper()}")
        print()

    # ── Stage 4: Full pipeline JSON ───────────────────────────────────────────
    print("[ Stage 4 ]  Full pipeline output (AnalyzeResult.shot_points) ─────")
    print(json.dumps(diag["shot_points"], indent=2))
    print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 62)
    print("  VALIDATION SUMMARY")
    print("=" * 62)

    if hoop_bbox is None:
        print("  [!] Hoop not detected — make/miss classification disabled.")
    else:
        hx, hy, hw, hh = hoop_bbox
        print(f"  [✓] Hoop detected at ({hx + hw//2}, {hy + hh//2})  size={hw}×{hh}")

    print(f"  [{'✓' if shot_events else '!'}] {len(shot_events)} shot(s) detected  "
          f"({len(makes)} made / {len(misses)} missed)")

    print()
    print("  How to verify quality:")
    print(textwrap.dedent(f"""
      1. SHOT COUNT — Compare {len(shot_events)} detected shot(s) against how many
         attempts you actually made. They should match.

      2. MAKE/MISS — Check the per-shot table above against what you know.
         "Frame" is the apex frame; divide by {fps:.0f} fps to get the timestamp,
         then scrub to that point in the video to verify.
         Note: origin.pixel in Stage 4 (AnalyzeResult) uses a trajectory-anchor
         baseline (ball near shot start, not apex) — this is what court-zone
         mapping will use.

      3. HOOP BOX WRONG — Run with --debug-video, open the output file, and
         confirm the yellow box sits on the real rim. If not:
           • The model may struggle with your specific court; check confidence stats.
           • Lower HOOP_CONF_THRESHOLD (current: {cv_pipeline.HOOP_CONF_THRESHOLD})
             or raise it if a wrong object is being detected.

      4. MISSED DETECTIONS — If shot count is too LOW:
           • Lower BALL_CONF_THRESHOLD    (current: {cv_pipeline.BALL_CONF_THRESHOLD})
           • Lower UP_ZONE_X_FACTOR       (current: {cv_pipeline.UP_ZONE_X_FACTOR}) —
             or raise it if shots from wide angles are missed.
           • Raise ATTEMPT_MAX_FRAME_GAP  (current: {cv_pipeline.ATTEMPT_MAX_FRAME_GAP})
             for very slow high-arc shots.

      5. FALSE DETECTIONS — If shot count is too HIGH:
           • Raise BALL_CONF_THRESHOLD    (current: {cv_pipeline.BALL_CONF_THRESHOLD})
           • Lower UP_ZONE_X_FACTOR       (current: {cv_pipeline.UP_ZONE_X_FACTOR})
             to tighten the up-zone so dribbling doesn't trigger it.
           • Lower ATTEMPT_MAX_FRAME_GAP  (current: {cv_pipeline.ATTEMPT_MAX_FRAME_GAP})

      6. MAKE/MISS WRONG — If totals are right but make/miss is off:
           • Raise SCORE_RIM_X_FRACTION   (current: {cv_pipeline.SCORE_RIM_X_FRACTION})
             if makes are being called misses.
           • Lower SCORE_RIM_X_FRACTION if misses are being called makes.
           • SCORE_REBOUND_PX (current: {cv_pipeline.SCORE_REBOUND_PX}) adds a pixel
             buffer for near-rim rebounds — raise to be more generous, lower to be strict.

      7. NO DETECTIONS AT ALL:
           • Check that best.pt is in the backend/ directory.
           • Ensure the ball is clearly visible (not a screen recording).
           • Try direct-camera footage rather than a screen capture.
    """))

    # ── Optional debug video ──────────────────────────────────────────────────
    if args.debug_video:
        out_dir = Path(__file__).parent / "test_videos" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / (video_path.stem + "_debug.mp4")
        print(f"  Writing debug video -> test_videos/output/{out_path.name} …")
        _write_debug_video(video_path, hoop_bbox, shot_events, out_path)
        print(f"  Done. Open {out_path.name} to visually confirm hoop box and shot markers.")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
