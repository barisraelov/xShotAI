"""Short WebSocket integration with a fake ShotSessionEngine (no YOLO)."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from live_constants import JPEG_QUALITY, PROTOCOL_VERSION
from live_persist import MemoryLivePersist
from live_protocol import pack_frame
from routers import live as live_router
from shot_session_engine import ShotDecided
from test_live_runtime import RecordingEngine


def _header(sid: str, frame_id: int) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "live_session_id": sid,
        "frame_id": frame_id,
        "capture_timestamp_monotonic_ms": frame_id * 33.3,
        "width": 16,
        "height": 16,
        "jpeg_quality": JPEG_QUALITY,
    }


def _recv_until(ws, typ: str, limit: int = 40) -> dict:
    seen = []
    for _ in range(limit):
        data = ws.receive_json()
        seen.append(data.get("type"))
        if data.get("type") == typ:
            return data
    raise AssertionError(f"did not receive {typ}; saw {seen}")


class LiveWsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.persist = MemoryLivePersist()
        self.engines: list[RecordingEngine] = []
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=2)

        def factory() -> RecordingEngine:
            engine = RecordingEngine(decide_on={2: shot})
            self.engines.append(engine)
            return engine

        app = FastAPI()
        app.include_router(live_router.router)
        app.state.live_persist = self.persist
        app.state.live_engine_factory = factory
        app.state.live_user_from_token = (
            lambda token: SimpleNamespace(id="user-1") if token == "good-token" else None
        )
        app.state.live_registry = {}
        self.client = TestClient(app)

    def test_rejects_unauthenticated(self) -> None:
        with self.client.websocket_connect("/live") as ws:
            ws.send_text(json.dumps({"type": "go"}))
            data = ws.receive_json()
            self.assertEqual(data["type"], "error")
            self.assertEqual(data["code"], "unauthorized")

    def test_auth_prepare_ping_go_frames_ack_stop(self) -> None:
        with self.client.websocket_connect("/live") as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            self.assertEqual(_recv_until(ws, "auth_ok")["type"], "auth_ok")

            ws.send_text(json.dumps({"type": "prepare"}))
            prepared = _recv_until(ws, "prepared")
            sid = prepared["live_session_id"]
            self.assertTrue(sid)

            ws.send_text(json.dumps({"type": "ping", "t": 100}))
            pong = _recv_until(ws, "pong")
            self.assertEqual(pong["t"], 100)
            self.assertIn("server_t", pong)

            ws.send_text(json.dumps({"type": "go"}))
            _recv_until(ws, "go_ack")

            for i in range(3):
                ws.send_bytes(pack_frame(_header(sid, i), b""))

            decided = _recv_until(ws, "shot_decided")
            self.assertEqual(decided["shot_id"], "s001")
            self.assertEqual(decided["result"], "made")

            ws.send_text(json.dumps({"type": "decision_ack", "shot_id": "s001"}))
            ws.send_text(json.dumps({"type": "stop"}))
            complete = _recv_until(ws, "session_complete")
            self.assertEqual(complete["result"]["status"], "completed")
            self.assertEqual(complete["result"]["summary"]["made"], 1)
            self.assertIsNone(complete["result"]["shot_points"][0]["zone"])
            self.assertIsNone(complete["result"]["shot_points"][0]["origin"]["court"])

        self.assertEqual(self.engines[0].frames, [0, 1, 2])
        self.assertTrue(self.persist.history)


if __name__ == "__main__":
    unittest.main()
