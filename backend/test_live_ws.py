"""Short WebSocket integration with a fake ShotSessionEngine (no YOLO)."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from live_constants import JPEG_QUALITY, PROTOCOL_VERSION
from live_persist import MemoryLivePersist
from live_protocol import pack_frame
from routers import live as live_router
from shot_session_engine import ShotDecided
from test_live_runtime import RecordingEngine

ALLOWED_ORIGIN = "http://localhost:5173"
FOREIGN_ORIGIN = "https://evil.example"


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

    def _connect(self):
        return self.client.websocket_connect("/live", headers={"Origin": ALLOWED_ORIGIN})

    def test_rejects_unauthenticated(self) -> None:
        with self._connect() as ws:
            ws.send_text(json.dumps({"type": "go"}))
            data = ws.receive_json()
            self.assertEqual(data["type"], "error")
            self.assertEqual(data["code"], "unauthorized")

    def test_auth_prepare_ping_go_frames_ack_stop(self) -> None:
        with self._connect() as ws:
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

    def test_prepare_does_not_insert_session_row(self) -> None:
        with self._connect() as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            _recv_until(ws, "auth_ok")
            ws.send_text(json.dumps({"type": "prepare"}))
            _recv_until(ws, "prepared")
            self.assertEqual(self.persist.sessions, {})
            self.assertEqual(self.persist.history, [])

    def test_prepare_disconnect_leaves_no_session_row(self) -> None:
        with self._connect() as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            _recv_until(ws, "auth_ok")
            ws.send_text(json.dumps({"type": "prepare"}))
            _recv_until(ws, "prepared")
        self.assertEqual(self.persist.sessions, {})
        self.assertEqual(self.persist.history, [])

    def test_go_creates_one_active_row_and_is_idempotent(self) -> None:
        with self._connect() as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            _recv_until(ws, "auth_ok")
            ws.send_text(json.dumps({"type": "prepare"}))
            prepared = _recv_until(ws, "prepared")
            sid = prepared["live_session_id"]
            ws.send_text(json.dumps({"type": "go"}))
            _recv_until(ws, "go_ack")
            self.assertEqual(len(self.persist.sessions), 1)
            self.assertEqual(self.persist.sessions[sid]["status"], "active")
            ws.send_text(json.dumps({"type": "go"}))
            _recv_until(ws, "go_ack")
            self.assertEqual(len(self.persist.sessions), 1)

    def test_frames_before_go_are_not_processed(self) -> None:
        with self._connect() as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            _recv_until(ws, "auth_ok")
            ws.send_text(json.dumps({"type": "prepare"}))
            prepared = _recv_until(ws, "prepared")
            sid = prepared["live_session_id"]
            for i in range(3):
                ws.send_bytes(pack_frame(_header(sid, i), b""))
            ws.send_text(json.dumps({"type": "ping", "t": 1}))
            _recv_until(ws, "pong")
            self.assertEqual(self.engines[0].frames, [])
            self.assertEqual(self.persist.shots, {})
            self.assertEqual(self.persist.sessions, {})


class LiveWsOriginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.persist = MemoryLivePersist()
        self.lookup_calls: list[str] = []
        app = FastAPI()
        app.include_router(live_router.router)
        app.state.live_persist = self.persist
        app.state.live_engine_factory = RecordingEngine
        app.state.live_user_from_token = lambda token: self.lookup_calls.append(token) or None
        app.state.live_registry = {}
        self.client = TestClient(app)

    def _connect(self, origin=ALLOWED_ORIGIN):
        headers = {} if origin is None else {"Origin": origin}
        return self.client.websocket_connect("/live", headers=headers)

    def _assert_rejected(self, origin):
        headers = {} if origin is None else {"Origin": origin}
        with self.assertRaises(Exception) as ctx:
            with self.client.websocket_connect("/live", headers=headers) as ws:
                ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
        exc = ctx.exception
        if isinstance(exc, WebSocketDisconnect):
            self.assertEqual(exc.code, live_router.WS_ORIGIN_REJECT_CODE)
        self.assertEqual(self.persist.sessions, {})
        self.assertEqual(self.persist.activate_calls, 0)
        self.assertEqual(self.persist.shots, {})
        self.assertEqual(self.lookup_calls, [])
        self.assertEqual(self.client.app.state.live_registry, {})

    def test_helper_allows_configured_and_localhost_only(self) -> None:
        preview = "https://xshot-git-feature-realtime-feedback.vercel.app"
        self.assertTrue(live_router.origin_is_allowed("http://localhost:5173"))
        self.assertTrue(live_router.origin_is_allowed("http://127.0.0.1:5173"))
        self.assertFalse(live_router.origin_is_allowed(None))
        self.assertFalse(live_router.origin_is_allowed(""))
        self.assertFalse(live_router.origin_is_allowed(FOREIGN_ORIGIN))
        self.assertFalse(live_router.origin_is_allowed(preview))
        self.assertTrue(live_router.origin_is_allowed(preview, allowed=[preview]))
        self.assertFalse(live_router.origin_is_allowed("*", allowed=[preview]))

    def test_allowed_origin_is_accepted(self) -> None:
        app_persist = MemoryLivePersist()
        app = FastAPI()
        app.include_router(live_router.router)
        app.state.live_persist = app_persist
        app.state.live_engine_factory = RecordingEngine
        app.state.live_user_from_token = (
            lambda token: SimpleNamespace(id="user-1") if token == "good-token" else None
        )
        app.state.live_registry = {}
        client = TestClient(app)
        with client.websocket_connect("/live", headers={"Origin": ALLOWED_ORIGIN}) as ws:
            ws.send_text(json.dumps({"type": "auth", "access_token": "good-token"}))
            self.assertEqual(_recv_until(ws, "auth_ok")["type"], "auth_ok")
        self.assertEqual(app_persist.sessions, {})
        self.assertEqual(app_persist.activate_calls, 0)

    def test_foreign_origin_is_rejected_before_session(self) -> None:
        self._assert_rejected(FOREIGN_ORIGIN)

    def test_missing_origin_is_rejected_before_session(self) -> None:
        self.assertFalse(live_router.origin_is_allowed(None))
        self._assert_rejected(None)
        self._assert_rejected("")


if __name__ == "__main__":
    unittest.main()
