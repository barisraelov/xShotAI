"""
xShot AI — Two-Gate Presence Diagnostic (Clip 6)

Diagnostic-only script.  Tests the idea of requiring a ball to pass through
BOTH an upper gate AND a lower gate in the correct temporal order as evidence
of a make.  Does NOT change _score(), AnalyzeResult, or any production file.

Two-gate definition (anchored to detected hoop bbox  hcx, hcy, hw, hh):

    hoop_top    = hcy - 0.5 * hh   (top edge of hoop bbox)
    hoop_bottom = hcy + 0.5 * hh   (bottom edge of hoop bbox)

    UPPER gate:
        x:  hcx - 0.5*hw  …  hcx + 0.5*hw   (= hoop bbox width)
        y:  hoop_top - hh  …  hoop_top        (one hoop height above hoop)

    LOWER gate:
        x:  hcx - 0.5*hw  …  hcx + 0.5*hw   (= hoop bbox width)
        y:  hoop_bottom    …  hoop_bottom + hh  (one hoop height below hoop)

Decision rule:
    A shot WOULD be upgraded MISS → MAKE if:
        ∃ upper_hit with upper_hit.frame < lower_hit.frame
    for at least one lower_hit.
    One gate alone is not enough.  Order matters.

Two detection sources are checked independently:
    PROD — detections that passed the pipeline's confidence threshold
           (from ball_pos_snapshot stored with each shot event)
    RAW  — all YOLO detections at low conf=0.10 for visual completeness

Per-shot report classifies each shot as:
    CASE 1 — no detections in either gate
    CASE 2 — only upper gate hits
    CASE 3 — only lower gate hits
    CASE 4 — hits in both gates but wrong order (lower before upper)
    CASE 5 — valid upper → lower sequence  (would upgrade to MAKE)

Outputs:
    test_videos/output/6_below_rim_gate/
        s001_gate_diag.mp4  … s004_gate_diag.mp4   (one annotated MP4 per shot)
        gate_diag_report.txt

Per-shot video overlays:
    BLUE  rectangle   = upper gate
    GREEN rectangle   = lower gate
    Dim-cyan rect     = hoop bbox
    Yellow h-line     = hoop_top  (rim_y)
    Red    h-line     = hoop_bottom
    White cross       = hoop centre
    BLUE  filled      = ball PROD detection inside upper gate
    CYAN  outline     = ball RAW  detection inside upper gate (not in PROD)
    GREEN filled      = ball PROD detection inside lower gate
    LIME  outline     = ball RAW  detection inside lower gate  (not in PROD)
    GREY  circle      = ball detection near but outside both gates
    GREEN border      = up_frame
    RED   border      = down_frame
    MAGENTA border    = shot time-window boundary

Constraints:
    Does NOT modify cv_pipeline.py or any production file.
    Does NOT affect AnalyzeResult, _score(), or any scoring helper.
    Does NOT change constants or tune thresholds.
    Does NOT add dense sampling; respects FRAME_STRIDE from cv_pipeline.
    Outputs are isolated in test_videos/output/6_below_rim_gate/.

Usage:
    cd backend
    python _diag_below_rim_gate.py              # auto-finds 6.mp4
    python _diag_below_rim_gate.py path/to/6.mp4
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).parent))
import cv_pipeline as cvp  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

# ── Diagnostic config ─────────────────────────────────────────────────────────
_PRE_FRAMES      = 20    # frames before up_frame to include in output video
_POST_FRAMES     = 20    # frames after shot window end to include
_VIZ_BALL_CONF   = 0.10  # confidence floor for the raw visualisation pass
# Shot time window: [up_frame, down_frame + _SHOT_TAIL]
_SHOT_TAIL       = cvp.BELOW_RIM_FRAME_WINDOW   # reuse existing constant

# ── Colours (BGR) ─────────────────────────────────────────────────────────────
_C_UPPER_GATE    = (255,  80,  80)   # blue
_C_LOWER_GATE    = ( 50, 220,  50)   # green
_C_HOOP_BBOX     = ( 60, 200, 200)   # dim cyan
_C_HOOP_CTR      = (255, 255, 255)   # white
_C_RIM_TOP_LINE  = (  0, 255, 255)   # yellow  (hoop_top / rim_y)
_C_RIM_BOT_LINE  = ( 80,  80, 255)   # red     (hoop_bottom)
_C_BALL_U_PROD   = (255,  80,  80)   # blue filled  — PROD upper hit
_C_BALL_U_RAW    = (255, 160, 160)   # light-blue outline — RAW-only upper hit
_C_BALL_L_PROD   = ( 50, 220,  50)   # green filled  — PROD lower hit
_C_BALL_L_RAW    = (100, 255, 100)   # light-green outline — RAW-only lower hit
_C_BALL_NEAR     = (160, 160, 160)   # grey — near gates, not inside
_C_UP_BORDER     = (  0, 255,   0)   # green border — up_frame
_C_DOWN_BORDER   = (  0,   0, 255)   # red border   — down_frame
_C_WIN_BORDER    = (255,   0, 255)   # magenta border — window boundary


def _put(img, text, pos, scale=0.38, color=(255, 255, 255), thick=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thick, cv2.LINE_AA)


def _panel(img, lines, x=5, y=14, scale=0.36, lh=13):
    for i, (text, color) in enumerate(lines):
        if text:
            _put(img, text, (x, y + i * lh), scale, color)


def _border(img, color, thick=3):
    h, w = img.shape[:2]
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), color, thick)


# ── Gate geometry helper ──────────────────────────────────────────────────────

def _gates(hcx, hcy, hw, hh):
    """Return (upper_gate, lower_gate) each as (x1, y1, x2, y2)."""
    hoop_top    = hcy - 0.5 * hh
    hoop_bottom = hcy + 0.5 * hh
    x1 = hcx - 0.5 * hw
    x2 = hcx + 0.5 * hw
    upper = (x1, hoop_top - hh, x2, hoop_top)
    lower = (x1, hoop_bottom,   x2, hoop_bottom + hh)
    return upper, lower


def _in_gate(cx, cy, gate):
    x1, y1, x2, y2 = gate
    return x1 < cx < x2 and y1 < cy < y2


def _near_gates(cx, cy, upper, lower, hcx, hcy, hw, hh):
    """True if within 2× hoop dimensions of either gate centre."""
    uc = ((upper[0] + upper[2]) / 2, (upper[1] + upper[3]) / 2)
    lc = ((lower[0] + lower[2]) / 2, (lower[1] + lower[3]) / 2)
    for gc in (uc, lc):
        if abs(cx - gc[0]) < hw * 2 and abs(cy - gc[1]) < hh * 2:
            return True
    return False


# ── Two-gate decision ─────────────────────────────────────────────────────────

def _two_gate_check(detections, upper, lower, up_frame, t_hi):
    """
    detections: list of (fi, cx, cy, conf) in the shot window.
    Returns (would_upgrade: bool, case: str, upper_hits, lower_hits).
    """
    win_dets = [(fi, cx, cy, conf)
                for fi, cx, cy, conf in detections
                if up_frame <= fi <= t_hi]

    upper_hits = [(fi, cx, cy, conf)
                  for fi, cx, cy, conf in win_dets
                  if _in_gate(cx, cy, upper)]
    lower_hits = [(fi, cx, cy, conf)
                  for fi, cx, cy, conf in win_dets
                  if _in_gate(cx, cy, lower)]

    if not upper_hits and not lower_hits:
        return False, "CASE 1 — no detections in either gate", [], []
    if upper_hits and not lower_hits:
        return False, "CASE 2 — only upper gate hits", upper_hits, []
    if lower_hits and not upper_hits:
        return False, "CASE 3 — only lower gate hits", [], lower_hits

    # Both gates hit — check ordering
    min_upper_fi = min(h[0] for h in upper_hits)
    has_lower_after = any(h[0] > min_upper_fi for h in lower_hits)
    if has_lower_after:
        return True, "CASE 5 — valid upper→lower sequence", upper_hits, lower_hits
    return False, "CASE 4 — both gates hit but wrong order", upper_hits, lower_hits


# ── Core diagnostic ───────────────────────────────────────────────────────────

def run_diag(video_path: str) -> None:
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    out_dir = (Path(__file__).parent
               / "test_videos" / "output" / "6_below_rim_gate")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: full production pipeline ──────────────────────────────────────
    logger.info("Running full pipeline on %s …", path.name)
    diag        = cvp._run_pipeline_verbose(str(path))
    shot_events = diag["shot_events"]
    fps         = diag["fps"] or 30.0
    frame_count = diag["frame_count"]

    if not shot_events:
        logger.warning("No shots detected — nothing to visualise.")
        return
    logger.info("%d shot(s). Collecting raw ball detections …",
                len(shot_events))

    # ── Step 2: raw YOLO pass for visualisation ────────────────────────────────
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("ultralytics not installed") from exc

    model = YOLO(str(Path(__file__).parent / cvp.YOLO_MODEL_PATH))

    # all_balls[fi] = list of (cx, cy, w, h, conf)
    all_balls: dict[int, list] = {}
    cap_scan = cv2.VideoCapture(str(path))
    fi = 0
    while True:
        ok, frame = cap_scan.read()
        if not ok:
            break
        if fi % cvp.FRAME_STRIDE == 0:
            results = model(frame, verbose=False, conf=_VIZ_BALL_CONF)
            boxes = []
            for r in results:
                for box in r.boxes:
                    if int(box.cls[0]) == 0:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        boxes.append(((x1 + x2) / 2, (y1 + y2) / 2,
                                      x2 - x1, y2 - y1, float(box.conf[0])))
            if boxes:
                all_balls[fi] = boxes
        fi += 1
    cap_scan.release()
    logger.info("Raw scan: %d frames with ≥1 ball detection.", len(all_balls))

    # ── Step 3: per-shot analysis and video ───────────────────────────────────
    report: list[str] = []
    report += [
        f"Two-Gate Presence Diagnostic — {path.name}",
        "=" * 64,
        f"Shots detected : {len(shot_events)}",
        f"fps            : {fps:.1f}",
        "",
        "Gate geometry (per shot):",
        "  X range (both gates) : hcx ± 0.5*hw  (= hoop bbox width)",
        "  Upper gate y : [hoop_top - hh .. hoop_top]",
        "  Lower gate y : [hoop_bottom  .. hoop_bottom + hh]",
        "  Shot window  : [up_frame .. down_frame + BELOW_RIM_FRAME_WINDOW]",
        f"  BELOW_RIM_FRAME_WINDOW = {cvp.BELOW_RIM_FRAME_WINDOW}",
        "",
        "Detection sources:",
        "  PROD = ball_pos_snapshot (pipeline-accepted, conf ≥ threshold)",
        f"  RAW  = re-scan at conf ≥ {_VIZ_BALL_CONF} (diagnostic only)",
        "",
    ]

    for si, ev in enumerate(shot_events, start=1):
        shot_id    = f"s{si:03d}"
        up_frame   = ev["up_frame"]
        down_frame = ev["down_frame"]
        result     = ev["result"]
        t_hi       = down_frame + _SHOT_TAIL

        hs   = ev["hoop_stable"]
        hcx, hcy, hw, hh = hs[0], hs[1], hs[3], hs[4]
        hoop_top    = hcy - 0.5 * hh
        hoop_bottom = hcy + 0.5 * hh

        upper, lower = _gates(hcx, hcy, hw, hh)

        # ── Build detection lists ─────────────────────────────────────────────
        # PROD: from ball_pos_snapshot stored with the shot event.
        prod_dets: list[tuple] = [
            (p[2], p[0], p[1], p[5])          # (fi, cx, cy, conf)
            for p in ev["ball_pos_snapshot"]
        ]
        # RAW: from the full re-scan.
        raw_dets: list[tuple] = [
            (f, cx, cy, conf)
            for f, balls in all_balls.items()
            for cx, cy, _, _, conf in balls
        ]

        # Two-gate check with PROD detections.
        prod_upgrade, prod_case, prod_u, prod_l = _two_gate_check(
            prod_dets, upper, lower, up_frame, t_hi)

        # Two-gate check with RAW detections.
        raw_upgrade, raw_case, raw_u, raw_l = _two_gate_check(
            raw_dets, upper, lower, up_frame, t_hi)

        # Mark which raw hits are NOT in prod (low-conf only).
        prod_set = {(fi, round(cx, 1), round(cy, 1))
                    for fi, cx, cy, _ in prod_dets}

        def _raw_only(hits):
            return [(fi, cx, cy, conf) for fi, cx, cy, conf in hits
                    if (fi, round(cx, 1), round(cy, 1)) not in prod_set]

        raw_only_u = _raw_only(raw_u)
        raw_only_l = _raw_only(raw_l)

        # Would the raw-only upgrade be based solely on low-conf detections?
        raw_upgrade_needs_lowconf = (
            raw_upgrade and not prod_upgrade
        )

        # ── Per-shot video ────────────────────────────────────────────────────
        viz_start = max(0, up_frame - _PRE_FRAMES)
        viz_end   = min(frame_count - 1, t_hi + _POST_FRAMES)

        cap = cv2.VideoCapture(str(path))
        fw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        out_mp4 = out_dir / f"{shot_id}_gate_diag.mp4"
        writer  = cv2.VideoWriter(str(out_mp4),
                                  cv2.VideoWriter_fourcc(*"mp4v"),
                                  fps, (fw, fh))

        cap.set(cv2.CAP_PROP_POS_FRAMES, viz_start)
        frames_written = 0

        for frame_fi in range(viz_start, viz_end + 1):
            ok, frame = cap.read()
            if not ok:
                break

            in_win = up_frame <= frame_fi <= t_hi

            # Frame border
            if frame_fi == up_frame:
                _border(frame, _C_UP_BORDER, 4)
            elif frame_fi == down_frame:
                _border(frame, _C_DOWN_BORDER, 4)
            elif frame_fi == t_hi:
                _border(frame, _C_WIN_BORDER, 2)

            # Hoop reference lines
            cv2.line(frame, (0, int(round(hoop_top))),
                     (fw, int(round(hoop_top))), _C_RIM_TOP_LINE, 1)
            cv2.line(frame, (0, int(round(hoop_bottom))),
                     (fw, int(round(hoop_bottom))), _C_RIM_BOT_LINE, 1)

            # Hoop bbox
            cv2.rectangle(frame,
                          (int(round(hcx - hw / 2)), int(round(hcy - hh / 2))),
                          (int(round(hcx + hw / 2)), int(round(hcy + hh / 2))),
                          _C_HOOP_BBOX, 1)

            # Upper gate (blue)
            cv2.rectangle(frame,
                          (int(round(upper[0])), int(round(upper[1]))),
                          (int(round(upper[2])), int(round(upper[3]))),
                          _C_UPPER_GATE, 2)

            # Lower gate (green)
            cv2.rectangle(frame,
                          (int(round(lower[0])), int(round(lower[1]))),
                          (int(round(lower[2])), int(round(lower[3]))),
                          _C_LOWER_GATE, 2)

            # Hoop centre cross
            cv2.drawMarker(frame,
                           (int(round(hcx)), int(round(hcy))),
                           _C_HOOP_CTR, cv2.MARKER_CROSS,
                           markerSize=12, thickness=1)

            # Ball detections for this frame
            if frame_fi in all_balls:
                for cx, cy, w_b, _, conf in all_balls[frame_fi]:
                    in_upper = _in_gate(cx, cy, upper)
                    in_lower = _in_gate(cx, cy, lower)
                    near     = _near_gates(cx, cy, upper, lower, hcx, hcy, hw, hh)

                    # Is this detection in PROD (ball_pos_snapshot)?
                    is_prod = any(
                        abs(p[0] - cx) < 2 and abs(p[1] - cy) < 2
                        for p in ev["ball_pos_snapshot"]
                        if p[2] == frame_fi
                    )

                    radius = max(4, int(w_b / 2))
                    if in_upper:
                        color    = _C_BALL_U_PROD if is_prod else _C_BALL_U_RAW
                        fill     = -1 if is_prod else 1
                    elif in_lower:
                        color    = _C_BALL_L_PROD if is_prod else _C_BALL_L_RAW
                        fill     = -1 if is_prod else 1
                    elif in_win and near:
                        color    = _C_BALL_NEAR
                        fill     = 1
                    else:
                        color    = (80, 80, 80)
                        fill     = 1

                    cv2.circle(frame, (int(round(cx)), int(round(cy))),
                               radius, color, fill)
                    tag = f"{conf:.2f}{'P' if is_prod else 'r'}"
                    _put(frame, tag,
                         (int(cx) + radius + 2, int(cy) - 2), 0.27, color)

            # Determine frame label
            if frame_fi == up_frame:
                role = "[UP]"
            elif frame_fi == down_frame:
                role = "[DOWN]"
            elif frame_fi == t_hi:
                role = "[WIN_END]"
            elif in_win:
                role = "[in window]"
            else:
                role = ""

            prod_col = (50, 220, 50) if prod_upgrade else (80, 80, 255)
            raw_col  = (50, 220, 50) if raw_upgrade  else (80, 80, 255)
            p_case_short = prod_case.split(" — ")[0]   # "CASE N"
            r_case_short = raw_case.split(" — ")[0]

            _panel(frame, [
                (f"Shot {shot_id}  {result.upper()}", (255, 255, 255)),
                (f"up={up_frame}  down={down_frame}  win_end={t_hi}",
                 (200, 200, 200)),
                (f"Hoop: cx={hcx:.0f} cy={hcy:.0f} hw={hw:.0f} hh={hh:.0f}",
                 _C_HOOP_CTR),
                (f"Upper: y=[{upper[1]:.0f}..{upper[3]:.0f}]",
                 _C_UPPER_GATE),
                (f"Lower: y=[{lower[1]:.0f}..{lower[3]:.0f}]",
                 _C_LOWER_GATE),
                (f"x=[{upper[0]:.0f}..{upper[2]:.0f}]  (both gates)",
                 (200, 200, 200)),
                (f"PROD: {p_case_short}", prod_col),
                (f"RAW:  {r_case_short}", raw_col),
                (f"Frame {frame_fi}  {role}", (255, 255, 0)),
                ("", (0, 0, 0)),
                ("BLUE  fill/line = upper gate hit (P/r)", _C_BALL_U_PROD),
                ("GREEN fill/line = lower gate hit (P/r)", _C_BALL_L_PROD),
                ("P=prod conf  r=raw low-conf", (180, 180, 180)),
            ])

            writer.write(frame)
            frames_written += 1

        cap.release()
        writer.release()
        logger.info("Shot %s: %d frames  ->  %s",
                    shot_id, frames_written, out_mp4.name)

        # ── Per-shot report ───────────────────────────────────────────────────
        report.append(f"{'='*64}")
        report.append(f"Shot {shot_id}  result={result}  "
                      f"up={up_frame} ({up_frame/fps:.2f}s)  "
                      f"down={down_frame} ({down_frame/fps:.2f}s)")
        report.append(f"  Shot window : [up={up_frame} .. {t_hi}]"
                      f"  (down+{_SHOT_TAIL})")
        report.append(f"  Hoop        : cx={hcx:.1f}  cy={hcy:.1f}  "
                      f"hw={hw:.1f}  hh={hh:.1f}")
        report.append(f"  Upper gate  : x=[{upper[0]:.1f}..{upper[2]:.1f}]"
                      f"  y=[{upper[1]:.1f}..{upper[3]:.1f}]"
                      f"  (w={upper[2]-upper[0]:.1f}  h={upper[3]-upper[1]:.1f} px)")
        report.append(f"  Lower gate  : x=[{lower[0]:.1f}..{lower[2]:.1f}]"
                      f"  y=[{lower[1]:.1f}..{lower[3]:.1f}]"
                      f"  (w={lower[2]-lower[0]:.1f}  h={lower[3]-lower[1]:.1f} px)")

        # PROD result
        report.append(f"")
        report.append(f"  [PROD detections]  {prod_case}")
        if prod_u:
            report.append(f"    Upper hits ({len(prod_u)}):")
            for fi, cx, cy, conf in sorted(prod_u, key=lambda x: x[0]):
                report.append(f"      frame={fi}  cx={cx:.1f}  cy={cy:.1f}"
                               f"  conf={conf:.3f}")
        else:
            report.append("    Upper hits : 0")
        if prod_l:
            report.append(f"    Lower hits ({len(prod_l)}):")
            for fi, cx, cy, conf in sorted(prod_l, key=lambda x: x[0]):
                report.append(f"      frame={fi}  cx={cx:.1f}  cy={cy:.1f}"
                               f"  conf={conf:.3f}")
        else:
            report.append("    Lower hits : 0")
        report.append(f"    → Would upgrade MISS→MAKE (PROD): {prod_upgrade}")

        # RAW result
        report.append(f"")
        report.append(f"  [RAW detections]  {raw_case}")
        if raw_u:
            report.append(f"    Upper hits ({len(raw_u)}):")
            for fi, cx, cy, conf in sorted(raw_u, key=lambda x: x[0]):
                tag = "PROD" if (fi, round(cx,1), round(cy,1)) in prod_set else "raw-only"
                report.append(f"      frame={fi}  cx={cx:.1f}  cy={cy:.1f}"
                               f"  conf={conf:.3f}  [{tag}]")
        else:
            report.append("    Upper hits : 0")
        if raw_l:
            report.append(f"    Lower hits ({len(raw_l)}):")
            for fi, cx, cy, conf in sorted(raw_l, key=lambda x: x[0]):
                tag = "PROD" if (fi, round(cx,1), round(cy,1)) in prod_set else "raw-only"
                report.append(f"      frame={fi}  cx={cx:.1f}  cy={cy:.1f}"
                               f"  conf={conf:.3f}  [{tag}]")
        else:
            report.append("    Lower hits : 0")
        report.append(f"    → Would upgrade MISS→MAKE (RAW):  {raw_upgrade}")
        if raw_upgrade_needs_lowconf:
            report.append(f"    ⚠ RAW upgrade relies on low-conf detections "
                          f"not accepted by the pipeline")

        report.append(f"  Output video : {out_mp4.name}"
                      f"  ({frames_written} frames, fi {viz_start}–{viz_end})")
        report.append("")

    # ── Summary ───────────────────────────────────────────────────────────────
    report.append("=" * 64)
    report.append("SUMMARY")
    report.append("=" * 64)
    for si, ev in enumerate(shot_events, start=1):
        shot_id = f"s{si:03d}"
        # Re-derive for summary (values already computed above; re-derive here
        # just for the summary table by replaying the same logic concisely).
        up_frame   = ev["up_frame"]
        down_frame = ev["down_frame"]
        t_hi       = down_frame + _SHOT_TAIL
        hs         = ev["hoop_stable"]
        hcx, hcy, hw, hh = hs[0], hs[1], hs[3], hs[4]
        upper, lower = _gates(hcx, hcy, hw, hh)
        prod_dets  = [(p[2], p[0], p[1], p[5]) for p in ev["ball_pos_snapshot"]]
        raw_dets   = [(f, cx, cy, conf)
                      for f, balls in all_balls.items()
                      for cx, cy, _, _, conf in balls]
        pu, pc, _, _ = _two_gate_check(prod_dets, upper, lower, up_frame, t_hi)
        ru, rc, _, _ = _two_gate_check(raw_dets,  upper, lower, up_frame, t_hi)
        report.append(
            f"  {shot_id}  {ev['result']:6s}  "
            f"PROD→MAKE:{str(pu):5s}  RAW→MAKE:{str(ru):5s}  "
            f"PROD:{pc.split(' — ')[0]:6s}  RAW:{rc.split(' — ')[0]}"
        )

    report_path = out_dir / "gate_diag_report.txt"
    report_path.write_text("\n".join(report), encoding="utf-8")
    logger.info("Report  -> %s", report_path)
    logger.info("All outputs in: %s", out_dir)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    input_dir = Path(__file__).parent / "test_videos" / "input"

    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        candidates = sorted(input_dir.glob("6.mp4"))
        if not candidates:
            candidates = sorted(input_dir.glob("*.mp4"))
        if not candidates:
            raise SystemExit(f"No .mp4 files found in {input_dir}")
        target = str(candidates[0])

    logger.info("Target video: %s", target)
    run_diag(target)
