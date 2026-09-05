"""LIVE runtime tests without YOLO (queue, overload, reconnect, stop, shot_id)."""

from __future__ import annotations

import threading
import unittest

from live_constants import (
    HUMAN_OVERLOAD,
    HUMAN_OVERLOAD_PROMPT,
    JPEG_QUALITY,
    OVERLOAD_DROPS,
    PROTOCOL_VERSION,
)
from live_persist import MemoryLivePersist
from live_runtime import STATUS_COMPLETED, LiveRuntime
from shot_session_engine import ShotDecided


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class RecordingEngine:
    def __init__(self, decide_on: dict | None = None) -> None:
        self.frames: list[int] = []
        self.open_shots: list[object] = []
        self.shot_events: list[dict] = []
        self.aborted = 0
        self.start_kwargs: dict | None = None
        self.decide_on = decide_on or {}
        self.block = False
        self.in_process = threading.Event()
        self.release = threading.Event()
        self.concurrent = 0
        self.max_concurrent = 0
        self._gate = threading.Lock()
        self.global_mode = type("M", (), {"name": "IDLE"})()

    def start(self, **kwargs) -> None:
        self.start_kwargs = kwargs

    def process_frame(self, frame, frame_id: int):
        with self._gate:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.block:
                self.in_process.set()
                self.release.wait(timeout=5)
            self.frames.append(frame_id)
            shot = self.decide_on.get(frame_id)
            if shot is None:
                return []
            self.shot_events.append({
                "shot_id": shot.shot_id,
                "result": shot.result,
                "u": 1,
                "v": 2,
                "frame_index": frame_id,
                "up_frame": 0,
                "down_frame": 1,
            })
            return [shot]
        finally:
            with self._gate:
                self.concurrent -= 1

    def abort_open_shot(self) -> None:
        self.aborted += 1
        self.open_shots.clear()

    def has_open_shot(self) -> bool:
        return bool(self.open_shots)

    def finalize(self):
        return self.shot_events, {}


def _header(sid: str, frame_id: int, capture_ms: float = 0.0) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "live_session_id": sid,
        "frame_id": frame_id,
        "capture_timestamp_monotonic_ms": capture_ms,
        "width": 16,
        "height": 16,
        "jpeg_quality": JPEG_QUALITY,
    }


def _runtime(engine=None, clock=None, persist=None, sid="live-1") -> LiveRuntime:
    return LiveRuntime(
        sid,
        "user-1",
        engine or RecordingEngine(),
        clock=clock or FakeClock(),
        persist=persist or MemoryLivePersist(),
        on_outbound=lambda _p: None,
    )


class LiveRuntimeTests(unittest.TestCase):
    def test_drop_oldest_keeps_frame_id(self) -> None:
        rt = _runtime()
        rt.go()
        for i in range(8):
            self.assertEqual(rt.accept_frame(_header(rt.live_session_id, i), b""), "accepted")
        self.assertEqual(rt.queue.peek_ids(), [2, 3, 4, 5, 6, 7])
        self.assertEqual(rt.frames_dropped_server, 2)
        self.assertEqual(rt.queue.peek_ids()[0], 2)

    def test_stale_and_duplicate_rejected(self) -> None:
        rt = _runtime()
        rt.go()
        self.assertEqual(rt.accept_frame(_header(rt.live_session_id, 0), b""), "accepted")
        self.assertEqual(rt.accept_frame(_header(rt.live_session_id, 0), b""), "duplicate")
        self.assertEqual(rt.accept_frame(_header(rt.live_session_id, 2), b""), "accepted")
        self.assertEqual(rt.accept_frame(_header(rt.live_session_id, 1), b""), "stale")
        self.assertEqual(rt.duplicate_stale_frames, 2)
        self.assertNotIn(1, rt.queue.peek_ids())

    def test_metadata_evicted_after_15s(self) -> None:
        clock = FakeClock(0.0)
        rt = _runtime(clock=clock)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"", received_at=0.0)
        self.assertTrue(rt.metadata)
        clock.t = 16.0
        rt.tick()
        self.assertEqual(len(rt.metadata), 0)

    def test_overload_twenty_drops_in_two_seconds(self) -> None:
        outbound: list[dict] = []
        clock = FakeClock(1.0)
        rt = LiveRuntime(
            "live-1", "user-1", RecordingEngine(),
            clock=clock, persist=MemoryLivePersist(),
            on_outbound=outbound.append,
        )
        rt.go()
        for i in range(6 + OVERLOAD_DROPS):
            rt.accept_frame(_header(rt.live_session_id, i), b"")
        rt.tick()
        self.assertTrue(rt.degraded)
        self.assertGreaterEqual(rt.frames_dropped_server, OVERLOAD_DROPS)
        self.assertTrue(any(m.get("type") == "status" and m.get("degraded") for m in outbound))
        self.assertTrue(any(HUMAN_OVERLOAD in str(m.get("message")) for m in outbound if m.get("degraded")))

    def test_overload_latency_one_second(self) -> None:
        clock = FakeClock(0.0)
        rt = _runtime(clock=clock)
        rt.go()
        rt.set_clock_offset(0.0)
        rt.accept_frame(_header(rt.live_session_id, 0, capture_ms=0.0), b"")
        clock.t = 0.6
        rt.process_one()
        self.assertFalse(rt.degraded)
        clock.t = 1.7
        rt.tick()
        self.assertTrue(rt.degraded)

    def test_recovery_three_seconds(self) -> None:
        clock = FakeClock(0.0)
        rt = _runtime(clock=clock)
        rt.go()
        for i in range(6 + OVERLOAD_DROPS):
            rt.accept_frame(_header(rt.live_session_id, i), b"")
        self.assertTrue(rt.degraded)
        # Drain waiting frames so later frames process with low latency.
        while rt.queue.peek_ids():
            rt.process_one()
        clock.t = 5.0
        rt.set_clock_offset(0.0)
        rt.accept_frame(_header(rt.live_session_id, 1000, capture_ms=5000.0), b"")
        rt.process_one()
        clock.t = 8.1
        rt.tick()
        self.assertFalse(rt.degraded)

    def test_prompt_after_ten_seconds(self) -> None:
        outbound: list[dict] = []
        clock = FakeClock(0.0)
        rt = LiveRuntime(
            "live-1", "user-1", RecordingEngine(),
            clock=clock, persist=MemoryLivePersist(),
            on_outbound=outbound.append,
        )
        rt.go()
        for i in range(6 + OVERLOAD_DROPS):
            rt.accept_frame(_header(rt.live_session_id, i), b"")
        clock.t = 10.0
        # Keep the drop window full so overload does not recover before the prompt.
        for i in range(20):
            rt._drop_times.append(clock.t)
        rt.tick()
        self.assertTrue(any(m.get("type") == "overload_prompt" for m in outbound))
        self.assertTrue(any(HUMAN_OVERLOAD_PROMPT in str(m.get("message")) for m in outbound))
        outbound.clear()
        rt.continue_overload()
        rt.tick()
        self.assertFalse(any(m.get("type") == "overload_prompt" for m in outbound))
        self.assertTrue(rt.degraded)

    def test_serial_processing(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        for i in range(4):
            rt.accept_frame(_header(rt.live_session_id, i), b"")

        barrier = threading.Barrier(3)

        def run() -> None:
            barrier.wait()
            for _ in range(2):
                rt.process_one()

        threads = [threading.Thread(target=run) for _ in range(2)]
        for t in threads:
            t.start()
        barrier.wait()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(engine.max_concurrent, 1)
        self.assertEqual(engine.frames, sorted(engine.frames))

    def test_stop_ignores_inflight_decision(self) -> None:
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        engine.block = True
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        thread = threading.Thread(target=rt.process_one)
        thread.start()
        self.assertTrue(engine.in_process.wait(timeout=2))
        rt.stop()
        engine.release.set()
        thread.join(timeout=5)
        self.assertNotIn("s001", rt.decided_shots)
        self.assertEqual(persist.shots, {})
        self.assertEqual(rt.status, STATUS_COMPLETED)

    def test_reconnect_under_500ms_keeps_open_shot(self) -> None:
        clock = FakeClock(0.0)
        engine = RecordingEngine()
        engine.open_shots.append(object())
        rt = _runtime(engine=engine, clock=clock)
        rt.go()
        rt.on_disconnect()
        clock.t = 0.4
        info = rt.on_reconnect("user-1")
        self.assertEqual(engine.aborted, 0)
        self.assertFalse(info["aborted_open"])
        self.assertEqual(len(engine.open_shots), 1)

    def test_reconnect_over_500ms_aborts_only_open_shot(self) -> None:
        clock = FakeClock(0.0)
        shot = ShotDecided(shot_id="s001", result="missed", decision_frame=1)
        engine = RecordingEngine(decide_on={0: shot})
        rt = _runtime(engine=engine, clock=clock)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.process_one()
        engine.open_shots.append(object())
        rt.on_disconnect()
        clock.t = 0.8
        info = rt.on_reconnect("user-1")
        self.assertTrue(info["aborted_open"])
        self.assertEqual(engine.aborted, 1)
        self.assertIn("s001", rt.decided_shots)
        self.assertEqual(len(engine.open_shots), 0)

    def test_reconnect_over_500ms_no_open_keeps_decided(self) -> None:
        clock = FakeClock(0.0)
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        rt = _runtime(engine=engine, clock=clock)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.process_one()
        rt.on_disconnect()
        clock.t = 0.9
        info = rt.on_reconnect("user-1")
        self.assertFalse(info["aborted_open"])
        self.assertEqual(engine.aborted, 0)
        self.assertIn("s001", rt.decided_shots)

    def test_disconnect_timeout_ten_seconds(self) -> None:
        clock = FakeClock(0.0)
        rt = _runtime(clock=clock)
        rt.go()
        rt.on_disconnect()
        clock.t = 9.9
        self.assertIsNone(rt.check_auto_complete())
        clock.t = 10.0
        result = rt.check_auto_complete()
        self.assertIsNotNone(result)
        self.assertEqual(rt.status, STATUS_COMPLETED)

    def test_shot_id_idempotent(self) -> None:
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot, 1: shot})
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.accept_frame(_header(rt.live_session_id, 1), b"")
        rt.process_one()
        rt.process_one()
        self.assertEqual(list(rt.decided_shots), ["s001"])
        self.assertEqual(len(persist.shots), 1)

    def test_ack_and_replay_unacked(self) -> None:
        outbound: list[dict] = []
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        rt = LiveRuntime(
            "live-1", "user-1", engine,
            persist=MemoryLivePersist(), on_outbound=outbound.append,
        )
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.process_one()
        self.assertEqual(list(rt.unacked), ["s001"])
        replay = rt.replay_unacked()
        self.assertEqual(replay[0]["shot_id"], "s001")
        rt.ack_shot("s001")
        self.assertEqual(rt.replay_unacked(), [])

    def test_degraded_shot_still_counts(self) -> None:
        clock = FakeClock(0.0)
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        rt = _runtime(engine=engine, clock=clock)
        rt.go()
        for i in range(6 + OVERLOAD_DROPS):
            rt.accept_frame(_header(rt.live_session_id, i), b"")
        self.assertTrue(rt.degraded)
        # Frame 0 was dropped from the queue; decide on a fresh id.
        engine.decide_on[100] = shot
        while rt.queue.peek_ids():
            rt.queue.pop()
        rt.accept_frame(_header(rt.live_session_id, 100), b"")
        rt.process_one()
        self.assertIn("s001", rt.decided_shots)
        self.assertTrue(rt.decided_shots["s001"].get("degraded"))

    def test_prepare_does_not_create_history(self) -> None:
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist)
        persist.create_prepare(rt.live_session_id, rt.user_id)
        self.assertEqual(persist.history, [])
        rt.complete(reason="abandon")
        self.assertEqual(persist.history, [])

    def test_live_engine_start_skips_weak_hoop(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        self.assertIsNotNone(engine.start_kwargs)
        self.assertFalse(engine.start_kwargs["collect_weak_detections"])
        self.assertIsNone(engine.start_kwargs["person_model"])
        self.assertIsNone(engine.start_kwargs["video_path"])
        self.assertIsNone(engine.start_kwargs["total_frames"])


if __name__ == "__main__":
    unittest.main()
