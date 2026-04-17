"""
xShot AI — OriginEstimator  (Phase 2)

PURPOSE
-------
Computes origin.pixel for each shot — the pixel coordinate that best represents
where the ball was when the shot was released from the shooter.

WHY THIS MODULE EXISTS (semantic correction)
--------------------------------------------
The previous implementation used _find_apex (the ball's highest mid-air point)
as origin.pixel.  The apex is spatially wrong for court-zone mapping: it is
mid-arc and mid-air, not on the court floor.

The correct origin for zone classification is the ball's position near the
START of the shot arc — when the ball was still close to the shooter's hands
and near floor level.  That corresponds to ball detections before or at
up_frame, not at the apex.

DECOUPLING CONTRACT
-------------------
This module has no dependency on cv_pipeline._score() or any make/miss logic.
Its only input is a "RichShotEvent" dict produced by the shot state machine
(see cv_pipeline._run_pipeline_inner for the dict shape).

TWO-LAYER DESIGN
----------------
Baseline (now — Phase 2):
    TrajectoryAnchorEstimator built into this class.
    Uses the ball's last detected position BELOW the hoop line before up_frame.
    No pose, no extra model.  Fast, deterministic, no new dependencies.

Future upgrade (Phase 6 — ReleaseEstimator plugin):
    Pass a ReleaseEstimator instance to OriginEstimator.__init__().
    Contract: estimator.estimate(shot_event: dict) -> dict | None
    Return dict must contain {"u": int, "v": int, "frame_index": int}.
    Return None (or raise) to signal low confidence → baseline takes over.
    Zero changes to this class are needed to enable the upgrade.

RICHCHOTEVENT DICT SHAPE (expected keys)
-----------------------------------------
    result              : "made" | "missed"
    ball_pos_snapshot   : list of (cx, cy, frame_idx, w, h, conf) tuples —
                          full rolling window at shot-confirmation time,
                          includes detections before up_frame.
    ball_points_window  : list of the same tuples, filtered to up_frame→down_frame.
    up_frame            : int — frame where state machine triggered "up".
    down_frame          : int — frame where state machine triggered "down".
    hoop_stable         : list (cx, cy, frame_idx, w, h, conf) or None —
                          most recent hoop detection at confirmation time.
    # legacy fields (apex) — kept for test_cv.py debug video, not used here:
    frame_index, u, v   : int — apex pixel (unchanged from pre-Phase-2 logic).
"""

from __future__ import annotations

from typing import Optional


class OriginEstimator:
    """
    Estimates origin.pixel from a RichShotEvent dict.

    Parameters
    ----------
    release_estimator : optional
        Future Phase 6 plugin.  Must implement:
            estimate(shot_event: dict) -> dict | None
        Return {"u": int, "v": int, "frame_index": int} when confident,
        or None to fall through to the trajectory-anchor baseline.
        May also raise an exception — handled silently.
    pre_up_window : int
        How many frames before up_frame to include when searching for
        pre-ascent ball positions.  Default of 40 frames covers ~1.3 s of
        lead-in at FRAME_STRIDE=2 on 30 fps footage.
    """

    def __init__(
        self,
        release_estimator=None,
        pre_up_window: int = 40,
    ) -> None:
        self._release_estimator = release_estimator
        self._pre_up_window = pre_up_window

    # ── Public API ─────────────────────────────────────────────────────────────

    def estimate(self, shot_event: dict) -> dict:
        """
        Return origin.pixel as {"u": int, "v": int, "frame_index": int}.

        Tries the optional release_estimator first (Phase 6 hook).
        Falls back to the trajectory-anchor baseline when the plugin is
        absent, returns None, or raises.
        """
        # ── Phase 6 hook ───────────────────────────────────────────────────
        # A ReleaseEstimator plugin can be injected at construction time.
        # Return None from the plugin to signal low confidence → baseline.
        if self._release_estimator is not None:
            try:
                result = self._release_estimator.estimate(shot_event)
                if result is not None:
                    return result
            except Exception:
                pass  # Plugin failed — fall through silently to baseline.

        # ── Baseline: trajectory anchor ────────────────────────────────────
        return self._trajectory_anchor(shot_event)

    # ── Baseline implementation ────────────────────────────────────────────────

    def _trajectory_anchor(self, shot_event: dict) -> dict:
        """
        Trajectory-anchor baseline.

        Finds the ball's last detected position BELOW the hoop line and
        BEFORE up_frame.  This is the closest observable approximation to
        where the ball was at release — when it was still near the shooter's
        hands at roughly floor level.

        Priority order:
        1. Last pre-ascent detection below the hoop centre (cy > hoop_cy)
           in the window [up_frame - pre_up_window, up_frame].
        2. Earliest detection in ball_points_window (start of up-zone entry).
        3. Earliest detection in ball_pos_snapshot (any available position).
        4. Zero detections — returns (0, 0, up_frame) as hard fallback.
           Should not occur in practice since a shot requires ball detection.
        """
        up_frame: int           = shot_event.get("up_frame", 0)
        hoop_stable: Optional[list] = shot_event.get("hoop_stable")
        ball_pos_snapshot: list = shot_event.get("ball_pos_snapshot", [])
        ball_points_window: list = shot_event.get("ball_points_window", [])

        # Hoop centre y (image pixels, top-left origin).
        # "Below the hoop" = larger cy value = lower in the image = floor level.
        hoop_cy: Optional[float] = float(hoop_stable[1]) if hoop_stable else None

        # ── Priority 1: last pre-ascent detection below hoop line ──────────
        # Search ball_pos_snapshot for detections in the lead-in window that
        # are spatially below the hoop — i.e., the ball was at shooter level.
        look_back_start = up_frame - self._pre_up_window
        pre_ascent = [
            p for p in ball_pos_snapshot
            if look_back_start <= p[2] <= up_frame
        ]

        if pre_ascent and hoop_cy is not None:
            below_hoop = [p for p in pre_ascent if p[1] > hoop_cy]
            if below_hoop:
                # Latest below-hoop detection = closest to release moment.
                best = max(below_hoop, key=lambda p: p[2])
                return {
                    "u":           int(best[0]),
                    "v":           int(best[1]),
                    "frame_index": int(best[2]),
                }

        # ── Priority 2: earliest detection in the up→down window ───────────
        # Ball is already in the up-zone here, but it's the earliest point
        # we can see, which is geometrically better than the mid-arc apex.
        if ball_points_window:
            best = min(ball_points_window, key=lambda p: p[2])
            return {
                "u":           int(best[0]),
                "v":           int(best[1]),
                "frame_index": int(best[2]),
            }

        # ── Priority 3: any detection in snapshot ──────────────────────────
        if ball_pos_snapshot:
            best = min(ball_pos_snapshot, key=lambda p: p[2])
            return {
                "u":           int(best[0]),
                "v":           int(best[1]),
                "frame_index": int(best[2]),
            }

        # ── Priority 4: no detections (hard fallback) ──────────────────────
        # Cannot happen in practice — a shot requires at least one ball
        # detection to have fired the state machine.
        return {"u": 0, "v": 0, "frame_index": up_frame}
