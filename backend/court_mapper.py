"""
CourtMapper — pixel-to-court homography and zone classification.

Calibration points map 4 known pixel locations to their normalized court
coordinates (x: 0=left sideline→1=right, y: 0=baseline→1=half-court).
The homography is computed with OpenCV findHomography and applied to each
shot's origin.pixel to produce origin.court.

Court dimensions: NCAA / High School
  Court:       50 ft wide × 47 ft long (half court)
  Basket:      25 ft from each sideline, 5.25 ft from baseline
  3-pt radius: 20.75 ft from basket center
"""

import math

import cv2
import numpy as np

_COURT_W       = 50.0    # ft — full width
_COURT_H       = 47.0    # ft — half-court length
_BASKET_X_FT   = 25.0    # ft from left sideline
_BASKET_Y_FT   = 5.25    # ft from baseline
_THREE_PT_FT   = 20.75   # ft radius (NCAA)

# Paint is 12 ft wide, centered → left at 19 ft, right at 31 ft from sideline.
# Free-throw line is 19 ft from baseline.
# 3-pt elbow x=19 ft: Δx=6, Δy=sqrt(20.75²-6²)≈19.86 → y≈25.11 ft from baseline.
# Normalized court coords: x=0 left sideline, y=0 baseline (near hoop), y=1 half-court.
# These 6 positions match the fixed order in Calibrate.jsx REFS.
_CALIB_COURT_REFS = [
    (19 / _COURT_W, 0.0),               # 1: paint corner — bottom left
    (31 / _COURT_W, 0.0),               # 2: paint corner — bottom right
    (19 / _COURT_W, 19 / _COURT_H),     # 3: paint corner — top left (free-throw line)
    (31 / _COURT_W, 19 / _COURT_H),     # 4: paint corner — top right
    (19 / _COURT_W, 25.11 / _COURT_H),  # 5: 3-pt arc — left elbow
    (31 / _COURT_W, 25.11 / _COURT_H),  # 6: 3-pt arc — right elbow
]


class CourtMapper:
    def __init__(self, calibration_points: list):
        """
        calibration_points: list of 6 [u, v] pixel pairs (from Calibrate.jsx),
        in the fixed order defined by _CALIB_COURT_REFS.
        Needs at least 4 non-collinear points.
        """
        if len(calibration_points) < 4:
            raise ValueError(f"Need at least 4 calibration points, got {len(calibration_points)}")
        src = np.array(
            [[pt[0], pt[1]] for pt in calibration_points],
            dtype=np.float32,
        )
        dst = np.array(
            [list(ref) for ref in _CALIB_COURT_REFS[:len(calibration_points)]],
            dtype=np.float32,
        )
        H, _ = cv2.findHomography(src, dst)
        if H is None:
            raise ValueError("findHomography failed — calibration points may be collinear")
        self._H = H

    def map_pixel(self, u: int, v: int) -> tuple[float, float]:
        """Return (x_norm, y_norm) clamped to [0, 1]."""
        pt = np.array([[[float(u), float(v)]]], dtype=np.float32)
        out = cv2.perspectiveTransform(pt, self._H)
        x = float(np.clip(out[0, 0, 0], 0.0, 1.0))
        y = float(np.clip(out[0, 0, 1], 0.0, 1.0))
        return round(x, 4), round(y, 4)

    def classify_zone(self, x_norm: float, y_norm: float, pixel_side_ref: tuple | None = None) -> dict:
        """Classify into one of 4 zones: two_left, two_right, three_left, three_right.

        pixel_side_ref: optional (ball_u, hoop_cx) tuple.  When provided, left/right is
        determined by comparing ball_u to hoop_cx directly in pixel space.  Use this when
        the input pixel was aerial (ball position), because the floor-plane homography gives
        an unreliable x_norm for non-floor points.
        """
        x_ft = x_norm * _COURT_W
        y_ft = y_norm * _COURT_H
        dist = math.sqrt((x_ft - _BASKET_X_FT) ** 2 + (y_ft - _BASKET_Y_FT) ** 2)
        is_three = dist >= _THREE_PT_FT

        if pixel_side_ref is not None:
            ball_u, hoop_cx = pixel_side_ref
            side = "left" if ball_u < hoop_cx else "right"
        else:
            side = "left" if x_norm < 0.5 else "right"
        side_label = "Left" if side == "left" else "Right"

        if is_three:
            return {"polygon_id": f"three_{side}", "range_class": "three_point", "label": f"3pt {side_label}"}
        else:
            return {"polygon_id": f"two_{side}", "range_class": "two_point", "label": f"2pt {side_label}"}

    def map_shot(self, u: int, v: int, pixel_side_ref: tuple | None = None) -> tuple[dict | None, dict | None]:
        """Return (court_dict, zone_dict) for a pixel position.

        pixel_side_ref: forwarded to classify_zone — see its docstring.
        """
        x, y = self.map_pixel(u, v)
        court = {"x": x, "y": y}
        zone = self.classify_zone(x, y, pixel_side_ref=pixel_side_ref)
        return court, zone

    @property
    def homography_matrix(self) -> list:
        return self._H.tolist()
