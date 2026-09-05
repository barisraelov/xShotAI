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
from live_runtime import STATUS_ACTIVE, STATUS_COMPLETED, STATUS_PREPARE, LiveRuntime
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
        self._next_shot_index = 1

    def start(self, **kwargs) -> None:
        self.start_kwargs = kwargs
        self._next_shot_index = 1

    def next_shot_index(self) -> int:
        return int(self._next_shot_index)

    def seed_next_shot_index(self, next_index: int) -> None:
        self._next_shot_index = max(1, int(next_index))

    def process_frame(self, frame, frame_id: int):
        with self._gate:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.block:
                self.in_process.set()
                self.release.wait(timeout=5)
            self.frames.append(frame_id)
            spec = self.decide_on.get(frame_id)
            if spec is None:
                return []
            if spec.shot_id == "auto":
                shot = ShotDecided(
                    shot_id=f"s{self._next_shot_index:03d}",
                    result=spec.result,
                    decision_frame=spec.decision_frame,
                )
                self._next_shot_index += 1
            else:
                shot = spec
                from live_runtime import shot_index_from_id

                n = shot_index_from_id(spec.shot_id)
                if n is not None and n >= self._next_shot_index:
                    self._next_shot_index = n + 1
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
        if self.open_shots:
            self.aborted += 1
        self.open_shots.clear()

    def reset_open_tracking(self) -> None:
        self.abort_open_shot()

    def has_open_shot(self) -> bool:
        return bool(self.open_shots)

    def finalize(self):
        return self.shot_events, {}


def jpeg_of(width: int, height: int) -> bytes:
    import cv2
    import numpy as np

    img = np.zeros((int(height), int(width), 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


def _header(
    sid: str,
    frame_id: int,
    capture_ms: float = 0.0,
    width: int = 16,
    height: int = 16,
) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "live_session_id": sid,
        "frame_id": frame_id,
        "capture_timestamp_monotonic_ms": capture_ms,
        "width": width,
        "height": height,
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
        self.assertEqual(persist.sessions, {})
        rt.complete(reason="abandon")
        self.assertEqual(persist.history, [])
        self.assertEqual(persist.sessions, {})

    def test_live_engine_start_skips_weak_hoop(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        jpeg = jpeg_of(32, 24)
        rt.accept_frame(_header(rt.live_session_id, 0, width=32, height=24), jpeg)
        rt.process_one()
        self.assertIsNotNone(engine.start_kwargs)
        self.assertEqual(engine.start_kwargs["frame_width"], 32)
        self.assertFalse(engine.start_kwargs["collect_weak_detections"])
        self.assertIsNone(engine.start_kwargs["person_model"])
        self.assertIsNone(engine.start_kwargs["video_path"])
        self.assertIsNone(engine.start_kwargs["total_frames"])
        self.assertEqual(rt.frame_width, 32)
        self.assertEqual(rt.frame_height, 24)


class LiveRuntimeFixTests(unittest.TestCase):
    """FIX-03 / FIX-04 / FIX-06 — generation, decoded width, GO persistence."""

    def test_prepare_only_has_no_db_row(self) -> None:
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist)
        persist.create_prepare(rt.live_session_id, rt.user_id)
        self.assertEqual(persist.sessions, {})

    def test_prepare_disconnect_timeout_has_no_db_row(self) -> None:
        clock = FakeClock(0.0)
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist, clock=clock)
        persist.create_prepare(rt.live_session_id, rt.user_id)
        rt.on_disconnect()
        clock.t = 10.0
        rt.check_auto_complete()
        self.assertEqual(persist.sessions, {})
        self.assertEqual(persist.history, [])
        self.assertEqual(rt.status, STATUS_COMPLETED)

    def test_go_creates_one_active_row(self) -> None:
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist)
        rt.go()
        self.assertEqual(len(persist.sessions), 1)
        row = persist.sessions[rt.live_session_id]
        self.assertEqual(row["status"], "active")
        rt.go()
        self.assertEqual(len(persist.sessions), 1)
        self.assertEqual(persist.sessions[rt.live_session_id]["status"], "active")

    def test_frames_before_go_are_ignored(self) -> None:
        persist = MemoryLivePersist()
        engine = RecordingEngine()
        rt = _runtime(engine=engine, persist=persist)
        self.assertEqual(
            rt.accept_frame(_header(rt.live_session_id, 0), jpeg_of(16, 16)),
            "ignored",
        )
        self.assertEqual(rt.process_one().ignored, True)
        self.assertEqual(engine.frames, [])
        self.assertEqual(persist.shots, {})
        self.assertEqual(persist.sessions, {})

    def test_reconnect_over_500ms_drops_queue_and_inflight(self) -> None:
        clock = FakeClock(0.0)
        created: list[RecordingEngine] = []

        def factory(width: int) -> RecordingEngine:
            engine = RecordingEngine()
            engine.start(
                model=None,
                frame_width=width,
                total_frames=None,
                video_path=None,
                person_model=None,
                collect_weak_detections=False,
            )
            created.append(engine)
            return engine

        first = factory(16)
        kept = ShotDecided(shot_id="s001", result="missed", decision_frame=0)
        stale = ShotDecided(shot_id="s099", result="made", decision_frame=1)
        first.decide_on[0] = kept
        persist = MemoryLivePersist()
        jpeg = jpeg_of(16, 16)
        outbound: list[dict] = []
        rt = LiveRuntime(
            "live-1",
            "user-1",
            first,
            clock=clock,
            persist=persist,
            on_outbound=outbound.append,
            engine_factory=factory,
        )
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        self.assertIn("s001", rt.decided_shots)

        first.block = True
        first.decide_on[1] = stale
        first.open_shots.append(object())
        rt.accept_frame(_header(rt.live_session_id, 1, width=16, height=16), jpeg)
        rt.accept_frame(_header(rt.live_session_id, 2, width=16, height=16), jpeg)
        rt.accept_frame(_header(rt.live_session_id, 3, width=16, height=16), jpeg)
        self.assertEqual(len(rt.queue), 3)

        thread = threading.Thread(target=rt.process_one)
        thread.start()
        self.assertTrue(first.in_process.wait(timeout=2))
        self.assertGreaterEqual(len(rt.queue), 1)

        gen_before = rt.generation
        rt.on_disconnect()
        clock.t = 0.8
        info = rt.on_reconnect("user-1")
        self.assertTrue(info["aborted_open"])
        self.assertGreater(rt.generation, gen_before)
        self.assertEqual(len(rt.queue), 0)
        self.assertIsNot(rt.engine, first)

        first.release.set()
        thread.join(timeout=5)
        self.assertNotIn("s099", rt.decided_shots)
        self.assertIn("s001", rt.decided_shots)
        self.assertFalse(any(m.get("shot_id") == "s099" for m in outbound))
        self.assertFalse(rt.engine.has_open_shot())

        rt.accept_frame(_header(rt.live_session_id, 4, width=16, height=16), jpeg)
        rt.process_one()
        self.assertNotIn("s099", rt.decided_shots)
        self.assertIn(4, rt.engine.frames)
        self.assertNotIn(1, rt.engine.frames)

    def test_reconnect_under_500ms_keeps_engine(self) -> None:
        clock = FakeClock(0.0)
        created: list[RecordingEngine] = []

        def factory(width: int) -> RecordingEngine:
            engine = RecordingEngine()
            created.append(engine)
            return engine

        first = factory(16)
        first.open_shots.append(object())
        jpeg = jpeg_of(16, 16)
        rt = LiveRuntime(
            "live-1",
            "user-1",
            first,
            clock=clock,
            persist=MemoryLivePersist(),
            on_outbound=lambda _p: None,
            engine_factory=factory,
        )
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        gen = rt.generation
        rt.on_disconnect()
        clock.t = 0.4
        info = rt.on_reconnect("user-1")
        self.assertFalse(info["aborted_open"])
        self.assertEqual(rt.generation, gen)
        self.assertIs(rt.engine, first)
        self.assertEqual(len(first.open_shots), 1)
        self.assertEqual(len(created), 1)

    def test_scoring_width_landscape_1280x720(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        jpeg = jpeg_of(1280, 720)
        rt.accept_frame(_header(rt.live_session_id, 0, width=1280, height=720), jpeg)
        rt.process_one()
        self.assertEqual(rt.frame_width, 1280)
        self.assertEqual(rt.frame_height, 720)
        self.assertEqual(engine.start_kwargs["frame_width"], 1280)

    def test_scoring_width_landscape_854x480(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        jpeg = jpeg_of(854, 480)
        rt.accept_frame(_header(rt.live_session_id, 0, width=854, height=480), jpeg)
        rt.process_one()
        self.assertEqual(rt.frame_width, 854)
        self.assertEqual(engine.start_kwargs["frame_width"], 854)

    def test_scoring_width_portrait_720x1280(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        jpeg = jpeg_of(720, 1280)
        rt.accept_frame(_header(rt.live_session_id, 0, width=720, height=1280), jpeg)
        rt.process_one()
        self.assertEqual(rt.frame_width, 720)
        self.assertEqual(rt.frame_height, 1280)
        self.assertEqual(engine.start_kwargs["frame_width"], 720)

    def test_decoded_width_wins_over_header(self) -> None:
        engine = RecordingEngine()
        rt = _runtime(engine=engine)
        rt.go()
        jpeg = jpeg_of(854, 480)
        rt.accept_frame(_header(rt.live_session_id, 0, width=1280, height=720), jpeg)
        rt.process_one()
        self.assertEqual(rt.frame_width, 854)
        self.assertEqual(rt.frame_height, 480)
        self.assertEqual(engine.start_kwargs["frame_width"], 854)

    def test_dimension_change_aborts_open_keeps_decided(self) -> None:
        created: list[RecordingEngine] = []

        def factory(width: int) -> RecordingEngine:
            engine = RecordingEngine()
            engine.start(
                model=None,
                frame_width=width,
                total_frames=None,
                video_path=None,
                person_model=None,
                collect_weak_detections=False,
            )
            created.append(engine)
            return engine

        first = factory(1280)
        kept = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        first.decide_on[0] = kept
        persist = MemoryLivePersist()
        rt = LiveRuntime(
            "live-1",
            "user-1",
            first,
            persist=persist,
            on_outbound=lambda _p: None,
            engine_factory=factory,
        )
        rt.go()
        rt.accept_frame(
            _header(rt.live_session_id, 0, width=1280, height=720),
            jpeg_of(1280, 720),
        )
        rt.process_one()
        first.open_shots.append(object())
        gen = rt.generation

        late = ShotDecided(shot_id="s002", result="missed", decision_frame=1)
        first.decide_on[1] = late
        rt.accept_frame(
            _header(rt.live_session_id, 1, width=720, height=1280),
            jpeg_of(720, 1280),
        )
        outcome = rt.process_one()
        self.assertFalse(outcome.ignored)
        self.assertGreater(rt.generation, gen)
        self.assertEqual(rt.frame_width, 720)
        self.assertEqual(rt.frame_height, 1280)
        self.assertIn("s001", rt.decided_shots)
        self.assertIsNot(rt.engine, first)
        self.assertFalse(rt.engine.has_open_shot())
        self.assertEqual(rt.engine.start_kwargs["frame_width"], 720)
        self.assertNotIn("s002", rt.decided_shots)


class LiveRuntimePatchTests(unittest.TestCase):
    def test_go_persist_success_emits_go_ack(self) -> None:
        outbound: list[dict] = []
        persist = MemoryLivePersist()
        rt = LiveRuntime(
            "live-1", "user-1", RecordingEngine(),
            persist=persist, on_outbound=outbound.append,
        )
        self.assertTrue(rt.go())
        self.assertEqual(rt.status, STATUS_ACTIVE)
        self.assertTrue(rt.go_started)
        self.assertEqual(persist.sessions["live-1"]["status"], "active")
        self.assertTrue(any(m.get("type") == "go_ack" for m in outbound))
        self.assertFalse(any(m.get("type") == "go_error" for m in outbound))

    def test_go_persist_failure_stays_prepare(self) -> None:
        outbound: list[dict] = []
        persist = MemoryLivePersist()
        persist.fail_activate = True
        rt = LiveRuntime(
            "live-1", "user-1", RecordingEngine(),
            persist=persist, on_outbound=outbound.append,
        )
        self.assertFalse(rt.go())
        self.assertEqual(rt.status, STATUS_PREPARE)
        self.assertFalse(rt.go_started)
        self.assertEqual(persist.sessions, {})
        self.assertTrue(any(m.get("type") == "go_error" for m in outbound))
        self.assertFalse(any(m.get("type") == "go_ack" for m in outbound))

    def test_go_retries_after_persist_failure(self) -> None:
        outbound: list[dict] = []
        persist = MemoryLivePersist()
        persist.fail_activate = True
        rt = LiveRuntime(
            "live-1", "user-1", RecordingEngine(),
            persist=persist, on_outbound=outbound.append,
        )
        self.assertFalse(rt.go())
        persist.fail_activate = False
        outbound.clear()
        self.assertTrue(rt.go())
        self.assertEqual(rt.status, STATUS_ACTIVE)
        self.assertEqual(len(persist.sessions), 1)
        self.assertTrue(any(m.get("type") == "go_ack" for m in outbound))

    def test_duplicate_go_after_success_one_row(self) -> None:
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist)
        self.assertTrue(rt.go())
        self.assertTrue(rt.go())
        self.assertEqual(len(persist.sessions), 1)
        self.assertEqual(persist.activate_calls, 1)

    def test_parallel_go_does_not_duplicate_row(self) -> None:
        persist = MemoryLivePersist()
        rt = _runtime(persist=persist)
        threads = [threading.Thread(target=rt.go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(persist.sessions), 1)
        self.assertEqual(persist.activate_calls, 1)
        self.assertTrue(rt.go_started)

    def test_shot_not_saved_without_parent_session(self) -> None:
        persist = MemoryLivePersist()
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        rt = _runtime(engine=engine, persist=persist)
        rt.status = STATUS_ACTIVE
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.process_one()
        self.assertEqual(persist.shots, {})
        self.assertNotIn("s001", rt.decided_shots)
        self.assertEqual(persist.sessions, {})

    def test_restore_keeps_completed_shots_on_new_runtime(self) -> None:
        persist = MemoryLivePersist()
        shot = ShotDecided(shot_id="s001", result="made", decision_frame=0)
        engine = RecordingEngine(decide_on={0: shot})
        rt = _runtime(engine=engine, persist=persist)
        rt.go()
        rt.accept_frame(_header(rt.live_session_id, 0), b"")
        rt.process_one()
        self.assertIn("s001", rt.decided_shots)
        saved = persist.load_shots(rt.live_session_id)
        fresh = _runtime(persist=persist, sid=rt.live_session_id)
        fresh.restore_decided_shots(saved)
        self.assertIn("s001", fresh.decided_shots)
        self.assertEqual(persist.load_shots(rt.live_session_id)[0]["shot_id"], "s001")
        self.assertFalse(fresh.engine.has_open_shot())
        self.assertEqual(fresh._seed_shot_index, 2)

    def test_restore_empty_next_shot_is_s001(self) -> None:
        engine = RecordingEngine(decide_on={0: ShotDecided("auto", "made", 0)})
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist)
        rt.restore_decided_shots([])
        self.assertEqual(engine.next_shot_index(), 1)
        rt.go()
        jpeg = jpeg_of(16, 16)
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        self.assertEqual(list(rt.decided_shots), ["s001"])
        self.assertEqual(engine.next_shot_index(), 2)

    def test_restore_s001_s002_next_shot_is_s003(self) -> None:
        engine = RecordingEngine(decide_on={0: ShotDecided("auto", "missed", 0)})
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist)
        rt.restore_decided_shots([
            {"shot_id": "s001", "result": "made"},
            {"shot_id": "s002", "result": "missed"},
        ])
        self.assertEqual(rt.decided_shots["s001"]["result"], "made")
        self.assertEqual(rt.decided_shots["s002"]["result"], "missed")
        self.assertEqual(engine.next_shot_index(), 3)
        rt.go()
        jpeg = jpeg_of(16, 16)
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        self.assertIn("s003", rt.decided_shots)
        self.assertEqual(rt.decided_shots["s001"]["result"], "made")
        self.assertEqual(rt.decided_shots["s002"]["result"], "missed")
        self.assertEqual(engine.next_shot_index(), 4)

    def test_restore_gap_s001_s004_next_shot_is_s005(self) -> None:
        engine = RecordingEngine(decide_on={0: ShotDecided("auto", "made", 0)})
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist)
        rt.restore_decided_shots([
            {"shot_id": "s001", "result": "made"},
            {"shot_id": "s004", "result": "missed"},
        ])
        self.assertEqual(engine.next_shot_index(), 5)
        rt.go()
        jpeg = jpeg_of(16, 16)
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        self.assertIn("s005", rt.decided_shots)
        self.assertEqual(rt.decided_shots["s004"]["result"], "missed")
        self.assertNotIn("s002", rt.decided_shots)

    def test_reconnect_does_not_reset_shot_index(self) -> None:
        clock = FakeClock(0.0)
        engine = RecordingEngine(decide_on={
            0: ShotDecided("auto", "made", 0),
            1: ShotDecided("auto", "missed", 1),
            2: ShotDecided("auto", "made", 2),
        })
        persist = MemoryLivePersist()
        rt = _runtime(engine=engine, persist=persist, clock=clock)
        rt.go()
        jpeg = jpeg_of(16, 16)
        for i in (0, 1):
            rt.accept_frame(_header(rt.live_session_id, i, width=16, height=16), jpeg)
            rt.process_one()
        self.assertEqual(sorted(rt.decided_shots), ["s001", "s002"])
        rt.on_disconnect()
        clock.t = 0.4
        rt.on_reconnect("user-1")
        rt.accept_frame(_header(rt.live_session_id, 2, width=16, height=16), jpeg)
        rt.process_one()
        self.assertEqual(sorted(rt.decided_shots), ["s001", "s002", "s003"])

    def test_shot_id_collision_does_not_return_old_result(self) -> None:
        outbound: list[dict] = []
        persist = MemoryLivePersist()
        engine = RecordingEngine(decide_on={
            0: ShotDecided("s001", "made", 0),
            1: ShotDecided("s001", "missed", 1),
        })
        rt = LiveRuntime(
            "live-1",
            "user-1",
            engine,
            persist=persist,
            on_outbound=outbound.append,
        )
        rt.go()
        jpeg = jpeg_of(16, 16)
        rt.accept_frame(_header(rt.live_session_id, 0, width=16, height=16), jpeg)
        rt.process_one()
        self.assertEqual(rt.decided_shots["s001"]["result"], "made")
        outbound.clear()
        rt.accept_frame(_header(rt.live_session_id, 1, width=16, height=16), jpeg)
        outcome = rt.process_one()
        self.assertEqual(rt.decided_shots["s001"]["result"], "made")
        self.assertFalse(any(m.get("result") == "missed" for m in outbound))
        self.assertEqual(outcome.decided, [])
        self.assertEqual(persist.shots[("live-1", "s001")]["result"], "made")


if __name__ == "__main__":
    unittest.main()
