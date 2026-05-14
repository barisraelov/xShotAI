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


class CourtMapper:
    def __init__(self, calibration_points: list[dict]):
        """
        calibration_points: list of {"pixel": {"u": int, "v": int},
                                     "court_ref": {"x": float, "y": float}}
        Needs at least 4 non-collinear points.
        """
        src = np.array(
            [[cp["pixel"]["u"], cp["pixel"]["v"]] for cp in calibration_points],
            dtype=np.float32,
        )
        dst = np.array(
            [[cp["court_ref"]["x"], cp["court_ref"]["y"]] for cp in calibration_points],
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

    def classify_zone(self, x_norm: float, y_norm: float) -> dict:
        """Classify into one of 4 zones: two_left, two_right, three_left, three_right."""
        x_ft = x_norm * _COURT_W
        y_ft = y_norm * _COURT_H
        dist = math.sqrt((x_ft - _BASKET_X_FT) ** 2 + (y_ft - _BASKET_Y_FT) ** 2)
        is_three = dist >= _THREE_PT_FT
        side = "left" if x_norm < 0.5 else "right"
        side_label = "Left" if side == "left" else "Right"

        if is_three:
            return {"polygon_id": f"three_{side}", "range_class": "three_point", "label": f"3pt {side_label}"}
        else:
            return {"polygon_id": f"two_{side}", "range_class": "two_point", "label": f"2pt {side_label}"}

    @property
    def homography_matrix(self) -> list:
        return self._H.tolist()
