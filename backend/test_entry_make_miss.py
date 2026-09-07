"""
Geometry-only tests for the hardened make/miss entry rule (no video, no YOLO).

Covers the Priority-2 audit fixes:
  - directional (downward-only) rim-plane crossing
  - confirmation must follow the crossing, within a frame-rate-scaled window,
    while descending, near the rim centre
  - front-rim bounce-outs -> MISS
  - net/rim occlusion gap -> still MAKE (segment bridge / parabolic bridge)
  - resolution-independent tolerances (BLUE eps / rim-exit margin scale w/ hoop)
"""

from __future__ import annotations

import unittest

import entry_make_miss as emm


def _hoop(hcx=500.0, hcy=200.0, hw=60.0, hh=40.0):
    return (hcx, hcy, 0, hw, hh, 0.9)


def _geom(hoop):
    y_blue, xb1, xb2 = emm.blue_rim_chord(hoop)
    cap = emm.capture_zone_rect(hoop)
    confirm = emm.confirmation_zone_rect(hoop, y_blue)
    return y_blue, xb1, xb2, cap, confirm


def _evaluate(pts, hoop, *, fps=30.0, radius_by_frame=None):
    y_blue, xb1, xb2, _cap, confirm = _geom(hoop)
    return emm.evaluate_entry_rule(
        pts, y_blue, xb1, xb2, confirm,
        hoop_tuple=hoop, fps=fps,
        radius_by_frame=radius_by_frame,
        blue_eps=emm._blue_eps(hoop),
    )


class DirectionalEntryRuleTests(unittest.TestCase):
    def test_clean_swish_is_make(self):
        hoop = _hoop()
        pts = [(0, 500, 130), (2, 500, 150), (4, 500, 170),
               (6, 500, 190), (8, 500, 210)]
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MAKE")
        self.assertEqual(out["reason"], "blue_cross_then_confirmation")

    def test_rattle_in_is_make(self):
        hoop = _hoop()
        pts = [(0, 505, 140), (2, 503, 165), (4, 501, 182),
               (6, 500, 178),                       # rattled up a touch
               (8, 501, 192), (10, 502, 200)]       # drops into confirm zone
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MAKE")

    def test_front_rim_bounce_out_is_miss(self):
        hoop = _hoop()
        # descends onto the front rim, pops UP through the plane, arcs away in front
        pts = [(0, 476, 140), (2, 474, 160), (4, 473, 178),
               (6, 472, 182),                       # crossed downward at the FRONT edge
               (8, 470, 168), (10, 464, 152), (12, 456, 143),  # bounced up + out
               (14, 450, 178), (16, 446, 235)]      # falls away, well left of the rim
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MISS")

    def test_upward_only_crossing_is_miss(self):
        hoop = _hoop()
        # ball travelling upward through the rim plane (e.g. a scoop/pop) — never a make
        pts = [(0, 500, 230), (2, 500, 205), (4, 500, 182),
               (6, 500, 165), (8, 500, 150)]
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MISS")
        self.assertEqual(out["reason"], "no_downward_cross")

    def test_airball_wide_no_crossing_is_miss(self):
        hoop = _hoop()
        pts = [(0, 380, 150), (2, 385, 175), (4, 390, 200), (6, 395, 230)]
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MISS")
        self.assertIn(out["reason"], ("no_blue_cross", "no_blue_cross_confirm_only"))

    def test_confirmation_outside_temporal_window_is_miss(self):
        hoop = _hoop()
        # downward crossing near frame 4, but the ball then veers hard left and
        # never re-enters the confirmation zone until a spurious blob ~40 frames
        # later — outside the fps-scaled window (~12 frames @ 30 fps).
        pts = [(0, 500, 150), (2, 500, 170), (4, 500, 178),
               (6, 430, 195), (8, 380, 240), (10, 330, 300),
               (48, 500, 194), (50, 500, 199)]
        out = _evaluate(pts, hoop, fps=30.0)
        self.assertEqual(out["diagnostic_result"], "MISS")

    def test_behind_rim_small_ball_crossing_is_rejected(self):
        hoop = _hoop()
        pts = [(0, 500, 150), (2, 500, 170), (4, 500, 178),
               (6, 500, 190), (8, 500, 205)]
        # ball radius collapses to ~1/4 of the trajectory median at the crossing
        radii = {0: 12.0, 2: 12.0, 4: 3.0, 6: 12.0, 8: 12.0}
        out = _evaluate(pts, hoop, radius_by_frame=radii)
        self.assertEqual(out["diagnostic_result"], "MISS")


class OcclusionBridgeTests(unittest.TestCase):
    def test_net_occlusion_gap_still_scores_make(self):
        hoop = _hoop()
        # above the rim, descending toward centre, 3-frame gap over the plane,
        # reappears cleanly below the rim near centre.
        pts = [(0, 500, 150), (2, 500, 165), (4, 500, 176),
               (8, 500, 206)]
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MAKE")

    def test_bridge_helper_tags_the_recovery(self):
        hoop = _hoop()
        y_blue, xb1, xb2, _cap, confirm = _geom(hoop)
        # engineer a straddling gap the direct crossing test cannot confirm
        # (post point sits below the confirmation zone), so the bridge is used.
        pts = [(0, 496, 150), (2, 498, 165), (4, 499, 178),
               (7, 501, 235)]
        res = emm._bridge_occlusion_make(
            pts, y_blue, xb1, xb2, hoop, confirm, fps=30.0, radius_by_frame=None,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["diagnostic_result"], "MAKE")
        self.assertEqual(res["audit_tag"], "occlusion_bridge")

    def test_bridge_rejects_gap_that_lands_outside_the_rim(self):
        hoop = _hoop()
        y_blue, xb1, xb2, _cap, confirm = _geom(hoop)
        # pre point over the opening, but the ball drifts far right through the gap
        pts = [(0, 498, 150), (2, 499, 168), (4, 500, 178),
               (7, 590, 235)]
        res = emm._bridge_occlusion_make(
            pts, y_blue, xb1, xb2, hoop, confirm, fps=30.0, radius_by_frame=None,
        )
        self.assertIsNone(res)


class ResolutionScalingTests(unittest.TestCase):
    def test_blue_eps_and_exit_margin_scale_with_hoop(self):
        small = _hoop(hw=20.0, hh=14.0)
        big = _hoop(hw=200.0, hh=140.0)
        self.assertLess(emm._blue_eps(small), emm._blue_eps(big))
        self.assertLess(emm._rim_exit_margin(small), emm._rim_exit_margin(big))
        # legacy absolute fallback when no geometry is supplied
        self.assertEqual(emm._blue_eps(None), emm.BLUE_TOUCH_EPS_PX)

    def test_confirm_window_scales_with_fps(self):
        self.assertLess(emm._confirm_window_frames(24.0),
                        emm._confirm_window_frames(60.0))

    def test_high_res_swish_not_lost_to_frame_skipping(self):
        # big hoop (4K-ish), sparse sampling — ball is above the plane one sample
        # and below the next, never exactly on it; the segment crossing + scaled
        # eps must still catch it.
        hoop = _hoop(hcx=1800.0, hcy=700.0, hw=200.0, hh=140.0)
        y_blue, *_ = _geom(hoop)          # y_blue = 700 - 70 = 630
        pts = [(0, 1800, 560), (3, 1800, 615), (6, 1800, 690), (9, 1800, 780)]
        out = _evaluate(pts, hoop)
        self.assertEqual(out["diagnostic_result"], "MAKE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
