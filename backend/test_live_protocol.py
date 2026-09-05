"""LIVE-05 / LIVE-09 binary frame pack/unpack."""

from __future__ import annotations

import unittest

from live_constants import JPEG_QUALITY, PROTOCOL_VERSION
from live_protocol import FrameProtocolError, pack_frame, unpack_frame, validate_header


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        header = {
            "protocol_version": PROTOCOL_VERSION,
            "live_session_id": "abc",
            "frame_id": 7,
            "capture_timestamp_monotonic_ms": 12.5,
            "width": 1280,
            "height": 720,
            "jpeg_quality": JPEG_QUALITY,
        }
        jpeg = b"\xff\xd8fakejpeg"
        packed = pack_frame(header, jpeg)
        self.assertTrue(packed.startswith(b"XSH1"))
        got, raw = unpack_frame(packed)
        self.assertEqual(got["frame_id"], 7)
        self.assertEqual(got["jpeg_quality"], JPEG_QUALITY)
        self.assertEqual(raw, jpeg)
        validate_header(got)

    def test_bad_magic(self) -> None:
        with self.assertRaises(FrameProtocolError):
            unpack_frame(b"NOPE\x00\x02{}")


if __name__ == "__main__":
    unittest.main()
