"""Upload-path regression (LIVE-01 / LIVE-03 / LIVE-24). No Clip 14."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

import single_pass_pipeline
from shot_session_engine import ShotSessionEngine


ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parent


class FakeYOLO:
    def __call__(self, frame, verbose=False, conf=0.0):
        return []


class UploadRegressionTests(unittest.TestCase):
    def test_imports(self) -> None:
        self.assertTrue(callable(single_pass_pipeline.run))
        self.assertTrue(callable(ShotSessionEngine.process_frame))

    def test_upload_keeps_weak_hoop_and_person_feet(self) -> None:
        src = (BACKEND / "single_pass_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("collect_weak_detections=True", src)
        self.assertIn("person_model=_person_model", src)
        self.assertIn("_scan_person_feet", src)
        self.assertIn("_run_state_machine_with_fallback", src)
        self.assertIn("court_mapper", src)

    def test_skip_location_unchanged(self) -> None:
        src = (ROOT / "frontend" / "src" / "screens" / "Calibrate.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("function handleSkip()", src)
        self.assertIn("submit(null)", src)
        self.assertIn("origin.court and zone will be null", src)

    def test_engine_smoke_without_weights(self) -> None:
        engine = ShotSessionEngine()
        engine.start(
            model=FakeYOLO(),
            frame_width=32,
            total_frames=None,
            video_path=None,
            person_model=None,
            collect_weak_detections=False,
        )
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        for i in (1, 2, 3):
            decided = engine.process_frame(frame, i)
            self.assertEqual(decided, [])
        events, diag = engine.finalize()
        self.assertEqual(events, [])
        self.assertIn("shot_events", diag)
        self.assertEqual(engine.weak_hoop_raw, [])


if __name__ == "__main__":
    unittest.main()
