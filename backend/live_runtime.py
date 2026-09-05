"""Live session runtime: queue, overload, reconnect, stop races (no YOLO)."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from live_constants import (
    DISCONNECT_TTL_S,
    HUMAN_OVERLOAD,
    HUMAN_OVERLOAD_PROMPT,
    JPEG_QUALITY,
    METADATA_TTL_S,
    OVERLOAD_DROP_WINDOW_S,
    OVERLOAD_DROPS,
    OVERLOAD_LATENCY_HOLD_S,
    OVERLOAD_LATENCY_MS,
    OVERLOAD_PROMPT_S,
    OVERLOAD_RECOVERY_S,
    QUEUE_MAXSIZE,
    RECONNECT_KEEP_ENGINE_S,
)
from live_log import live_log
from live_protocol import FrameProtocolError, validate_header
from live_queue import DropOldestQueue, QueuedFrame

STATUS_PREPARE = "prepare"
STATUS_ACTIVE = "active"
STATUS_STOPPING = "stopping"
STATUS_COMPLETED = "completed"


def _mode_name(engine: Any) -> Optional[str]:
    mode = getattr(engine, "global_mode", None)
    if mode is None:
        return None
    return getattr(mode, "name", str(mode))


def _percentile(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


@dataclass
class ProcessOutcome:
    ignored: bool
    decided: list[Any] = field(default_factory=list)
    frame_id: Optional[int] = None


class LiveRuntime:
    """Per-session Live state. CV work is injected via `engine`; persist via callbacks."""

    def __init__(
        self,
        live_session_id: str,
        user_id: str,
        engine: Any = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        persist: Any = None,
        on_outbound: Optional[Callable[[dict], None]] = None,
        queue_maxsize: int = QUEUE_MAXSIZE,
        started: bool = False,
        engine_factory: Optional[Callable[[int], Any]] = None,
    ) -> None:
        self.live_session_id = live_session_id
        self.user_id = user_id
        self.engine = engine
        self.engine_factory = engine_factory
        self.clock = clock
        self.persist = persist
        self.on_outbound = on_outbound

        self.status = STATUS_PREPARE
        self.generation = 0
        self.go_started = False

        self.queue = DropOldestQueue(maxsize=queue_maxsize)
        self._proc_lock = threading.Lock()
        self.max_seen_id = -1

        self.clock_offset_ms = 0.0
        self.degraded = False
        self.degraded_since: Optional[float] = None
        self.overload_prompt_sent = False
        self.overload_continue_chosen = False
        self._drop_times: deque[float] = deque()
        self._latency_high_since: Optional[float] = None
        self._last_e2e_ms: Optional[float] = None
        self._recovery_since: Optional[float] = None

        self.disconnected_at: Optional[float] = None
        self.reconnect_count = 0
        self.history_session_id: Optional[str] = None
        self.completed_result: Optional[dict] = None

        self.decided_shots: dict[str, dict] = {}
        self.unacked: dict[str, dict] = {}

        self.metadata: deque[dict] = deque()
        self.latency_samples: list[float] = []

        self.frames_captured = 0
        self.frames_sent = 0
        self.frames_received = 0
        self.frames_processed = 0
        self.frames_dropped_client = 0
        self.frames_dropped_server = 0
        self.duplicate_stale_frames = 0
        self.max_queue_size = 0
        self.overload_events = 0
        self.gap_count = 0

        self.engine_started = started
        self.frame_width: Optional[int] = None
        self.frame_height: Optional[int] = None
        self._go_lock = threading.Lock()

    # ── outbound ────────────────────────────────────────────────────────────

    def _emit(self, payload: dict) -> None:
        if self.on_outbound is not None:
            self.on_outbound(payload)

    def _engine_shot_id(self) -> Optional[str]:
        events = getattr(self.engine, "shot_events", None) or []
        if events:
            return events[-1].get("shot_id")
        return None

    # ── clock / metadata ────────────────────────────────────────────────────

    def set_clock_offset(self, offset_ms: float) -> None:
        self.clock_offset_ms = float(offset_ms)

    def note_client_stats(
        self,
        *,
        frames_captured: Optional[int] = None,
        frames_sent: Optional[int] = None,
        frames_dropped_client: Optional[int] = None,
    ) -> None:
        if frames_captured is not None:
            self.frames_captured = int(frames_captured)
        if frames_sent is not None:
            self.frames_sent = int(frames_sent)
        if frames_dropped_client is not None:
            self.frames_dropped_client = int(frames_dropped_client)

    def _e2e_ms(self, capture_ms: float, server_mono_s: float) -> float:
        return (server_mono_s * 1000.0) - float(capture_ms) + self.clock_offset_ms

    def _record_e2e(self, e2e_ms: float, now: float) -> None:
        self._last_e2e_ms = e2e_ms
        self.latency_samples.append(e2e_ms)
        if e2e_ms > OVERLOAD_LATENCY_MS:
            if self._latency_high_since is None:
                self._latency_high_since = now
        else:
            self._latency_high_since = None

    def _evict_metadata(self, now: float) -> None:
        cutoff = now - METADATA_TTL_S
        while self.metadata and self.metadata[0]["recorded_at"] < cutoff:
            self.metadata.popleft()

    def _add_meta(self, row: dict, now: float) -> None:
        row = dict(row)
        row["recorded_at"] = now
        row.setdefault("live_session_id", self.live_session_id)
        self.metadata.append(row)
        self._evict_metadata(now)

    def latency_stats(self) -> dict[str, Optional[float]]:
        samples = list(self.latency_samples)
        if not samples:
            return {"average_latency": None, "p95_latency": None, "max_latency": None}
        return {
            "average_latency": sum(samples) / len(samples),
            "p95_latency": _percentile(samples, 95),
            "max_latency": max(samples),
        }

    def session_counters(self) -> dict[str, Any]:
        stats = self.latency_stats()
        return {
            "frames_captured": self.frames_captured,
            "frames_sent": self.frames_sent,
            "frames_received": self.frames_received,
            "frames_processed": self.frames_processed,
            "frames_dropped_client": self.frames_dropped_client,
            "frames_dropped_server": self.frames_dropped_server,
            "duplicate_stale_frames": self.duplicate_stale_frames,
            "max_queue_size": self.max_queue_size,
            "average_latency": stats["average_latency"],
            "p95_latency": stats["p95_latency"],
            "max_latency": stats["max_latency"],
            "overload_events": self.overload_events,
            "reconnect_count": self.reconnect_count,
            "gap_count": self.gap_count,
        }

    # ── overload (LIVE-12 / LIVE-13) ────────────────────────────────────────

    def _emit_degraded(self, on: bool) -> None:
        self._emit({
            "type": "status",
            "degraded": on,
            "trace_code": "LIVE-12",
            "message": HUMAN_OVERLOAD if on else None,
            "live_session_id": self.live_session_id,
        })

    def _emit_overload_prompt(self) -> None:
        self._emit({
            "type": "overload_prompt",
            "trace_code": "LIVE-12",
            "message": HUMAN_OVERLOAD_PROMPT,
            "live_session_id": self.live_session_id,
        })

    def _enter_degraded(self, now: float) -> None:
        if self.degraded:
            return
        self.degraded = True
        self.degraded_since = now
        self.overload_prompt_sent = False
        self.overload_continue_chosen = False
        self.overload_events += 1
        self._recovery_since = None
        live_log(
            "LIVE-12",
            "overload_enter",
            live_session_id=self.live_session_id,
            drop_window=len(self._drop_times),
            last_e2e_ms=self._last_e2e_ms,
        )
        self._emit_degraded(True)

    def _recover(self) -> None:
        self.degraded = False
        self.degraded_since = None
        self.overload_prompt_sent = False
        self.overload_continue_chosen = False
        self._recovery_since = None
        live_log("LIVE-12", "overload_recover", live_session_id=self.live_session_id)
        self._emit_degraded(False)

    def _eval_overload(self, now: float) -> None:
        while self._drop_times and now - self._drop_times[0] > OVERLOAD_DROP_WINDOW_S:
            self._drop_times.popleft()
        drops_trigger = len(self._drop_times) >= OVERLOAD_DROPS
        lat_trigger = (
            self._latency_high_since is not None
            and (now - self._latency_high_since) >= OVERLOAD_LATENCY_HOLD_S
            and self._last_e2e_ms is not None
            and self._last_e2e_ms > OVERLOAD_LATENCY_MS
        )

        if drops_trigger or lat_trigger:
            self._recovery_since = None
            if not self.degraded:
                self._enter_degraded(now)
            elif (
                self.degraded_since is not None
                and (now - self.degraded_since) >= OVERLOAD_PROMPT_S
                and not self.overload_prompt_sent
            ):
                self.overload_prompt_sent = True
                self._emit_overload_prompt()
            return

        if not self.degraded:
            return

        last_drop = self._drop_times[-1] if self._drop_times else None
        no_new_drops = last_drop is None or (now - last_drop) >= OVERLOAD_RECOVERY_S
        latency_ok = self._last_e2e_ms is None or self._last_e2e_ms < OVERLOAD_LATENCY_MS
        if no_new_drops and latency_ok:
            if self._recovery_since is None:
                self._recovery_since = now
            elif (now - self._recovery_since) >= OVERLOAD_RECOVERY_S:
                self._recover()
        else:
            self._recovery_since = None

        if (
            self.degraded
            and self.degraded_since is not None
            and (now - self.degraded_since) >= OVERLOAD_PROMPT_S
            and not self.overload_prompt_sent
        ):
            self.overload_prompt_sent = True
            self._emit_overload_prompt()

    def continue_overload(self) -> None:
        self.overload_continue_chosen = True
        live_log("LIVE-12", "overload_continue", live_session_id=self.live_session_id)

    def tick(self, now: Optional[float] = None) -> Optional[dict]:
        now = self.clock() if now is None else now
        self._evict_metadata(now)
        self._eval_overload(now)
        return self.check_auto_complete(now)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def ensure_engine_started(self, frame_width: int) -> None:
        if int(frame_width) <= 0:
            raise ValueError("frame_width must be positive")
        if self.engine_started:
            return
        next_idx = getattr(self.engine, "_next_shot_index", 1) if self.engine else 1
        if self.engine is None and self.engine_factory is not None:
            self.engine = self.engine_factory(int(frame_width))
            if hasattr(self.engine, "_next_shot_index"):
                self.engine._next_shot_index = next_idx
            self.engine_started = True
            return
        start = getattr(self.engine, "start", None) if self.engine is not None else None
        if start is not None:
            start(
                model=getattr(self.engine, "_model", None),
                frame_width=int(frame_width),
                total_frames=None,
                video_path=None,
                person_model=None,
                collect_weak_detections=False,
            )
        elif self.engine_factory is not None:
            self.engine = self.engine_factory(int(frame_width))
            if hasattr(self.engine, "_next_shot_index"):
                self.engine._next_shot_index = next_idx
        self.engine_started = True

    def go(self, now: Optional[float] = None) -> bool:
        now = self.clock() if now is None else now
        with self._go_lock:
            if self.go_started:
                self._emit({"type": "go_ack", "live_session_id": self.live_session_id})
                return True
            if self.status in (STATUS_STOPPING, STATUS_COMPLETED):
                self._emit({
                    "type": "go_error",
                    "code": "session_closed",
                    "message": "live session is not awaiting GO",
                    "live_session_id": self.live_session_id,
                })
                return False
            if self.persist is not None:
                try:
                    self.persist.activate(self.live_session_id, user_id=self.user_id)
                except Exception as exc:
                    live_log(
                        "LIVE-18",
                        "go_persist_failed",
                        live_session_id=self.live_session_id,
                        error=str(exc),
                    )
                    self._emit({
                        "type": "go_error",
                        "code": "persist_failed",
                        "message": "Could not create the live session. Try Start again.",
                        "live_session_id": self.live_session_id,
                    })
                    return False
            self.status = STATUS_ACTIVE
            self.go_started = True
            self.queue.clear()
            self.metadata.clear()
            self.max_seen_id = -1
            self.frames_received = 0
            self.frames_processed = 0
            self.frames_dropped_server = 0
            self.duplicate_stale_frames = 0
            self.max_queue_size = 0
            self.gap_count = 0
            self._drop_times.clear()
            self.degraded = False
            self.degraded_since = None
            self._last_e2e_ms = None
            self._latency_high_since = None
            live_log("LIVE-18", "go", live_session_id=self.live_session_id, user_id=self.user_id)
            self._emit({"type": "go_ack", "live_session_id": self.live_session_id})
            return True

    def stop(self, now: Optional[float] = None) -> int:
        now = self.clock() if now is None else now
        if self.status in (STATUS_STOPPING, STATUS_COMPLETED):
            return self.generation
        self.status = STATUS_STOPPING
        self.generation += 1
        dumped = self.queue.clear()
        abort = getattr(self.engine, "abort_open_shot", None)
        if abort is not None:
            abort()
        live_log(
            "LIVE-19",
            "stop",
            live_session_id=self.live_session_id,
            dropped_waiting=len(dumped),
            generation=self.generation,
        )
        self.complete(now=now, reason="stop")
        return self.generation

    def complete(self, now: Optional[float] = None, reason: str = "complete") -> dict:
        if self.status == STATUS_COMPLETED and self.completed_result is not None:
            return self.completed_result
        now = self.clock() if now is None else now
        self.status = STATUS_COMPLETED
        shot_points = [self.decided_shots[k] for k in sorted(self.decided_shots)]
        result = None
        history_id = None
        if self.persist is not None:
            packed = self.persist.complete(
                self.live_session_id,
                self.user_id,
                shot_points,
                save_history=self.go_started,
            )
            result = packed["result"]
            history_id = packed.get("history_session_id")
        else:
            from result_builder import build_real_result

            result = build_real_result(self.live_session_id, shot_points, None)
        self.completed_result = result
        self.history_session_id = history_id
        live_log(
            "LIVE-18",
            "session_complete",
            live_session_id=self.live_session_id,
            reason=reason,
            shots=len(shot_points),
            history_session_id=history_id,
        )
        self._emit({
            "type": "session_complete",
            "live_session_id": self.live_session_id,
            "session_id": history_id,
            "result": result,
            "reason": reason,
        })
        return result

    def on_disconnect(self, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if self.status == STATUS_COMPLETED:
            return
        self.disconnected_at = now
        live_log("LIVE-17", "disconnect", live_session_id=self.live_session_id)

    def on_reconnect(self, user_id: str, now: Optional[float] = None) -> dict:
        now = self.clock() if now is None else now
        if user_id != self.user_id:
            raise PermissionError("live session belongs to another user")
        if self.status == STATUS_COMPLETED:
            raise RuntimeError("live session already completed")
        gap = 0.0 if self.disconnected_at is None else (now - self.disconnected_at)
        self.disconnected_at = None
        self.reconnect_count += 1
        aborted_open = False
        if gap > RECONNECT_KEEP_ENGINE_S:
            has_open = False
            if self.engine is not None:
                has_open = bool(getattr(self.engine, "has_open_shot", lambda: False)())
                if not has_open and hasattr(self.engine, "open_shots"):
                    has_open = bool(self.engine.open_shots)
            self.generation += 1
            dumped = self.queue.clear()
            self._replace_or_reset_engine(reason="reconnect_gap")
            aborted_open = has_open
            live_log(
                "LIVE-17",
                "generation_bump",
                live_session_id=self.live_session_id,
                gap_s=gap,
                generation=self.generation,
                dropped_waiting=len(dumped),
                aborted_open=aborted_open,
            )
        live_log(
            "LIVE-17",
            "reconnect",
            live_session_id=self.live_session_id,
            gap_s=gap,
            aborted_open=aborted_open,
            reconnect_count=self.reconnect_count,
        )
        replay = list(self.unacked.values())
        return {"gap_s": gap, "aborted_open": aborted_open, "replay": replay}

    def check_auto_complete(self, now: Optional[float] = None) -> Optional[dict]:
        now = self.clock() if now is None else now
        if self.disconnected_at is None or self.status == STATUS_COMPLETED:
            return None
        if (now - self.disconnected_at) >= DISCONNECT_TTL_S:
            abort = getattr(self.engine, "abort_open_shot", None)
            if abort is not None:
                abort()
            live_log("LIVE-17", "disconnect_timeout", live_session_id=self.live_session_id)
            return self.complete(now=now, reason="disconnect_timeout")
        return None

    # ── frames ──────────────────────────────────────────────────────────────

    def accept_frame(self, header: dict, jpeg: bytes, received_at: Optional[float] = None) -> str:
        now = self.clock() if received_at is None else received_at
        if self.status != STATUS_ACTIVE:
            return "ignored"
        try:
            validate_header(header)
        except FrameProtocolError:
            live_log("LIVE-09", "bad_header", live_session_id=self.live_session_id)
            return "rejected"
        if header.get("live_session_id") not in (None, "", self.live_session_id):
            return "rejected"
        frame_id = int(header["frame_id"])
        self.frames_received += 1

        if frame_id <= self.max_seen_id:
            self.duplicate_stale_frames += 1
            kind = "duplicate" if frame_id == self.max_seen_id else "stale"
            live_log(
                "LIVE-09",
                f"frame_{kind}",
                frame_id=frame_id,
                live_session_id=self.live_session_id,
                max_seen_id=self.max_seen_id,
            )
            self._add_meta(
                {
                    "frame_id": frame_id,
                    "capture_timestamp_monotonic_ms": header.get("capture_timestamp_monotonic_ms"),
                    "server_received_ts": now,
                    "processed": False,
                    "dropped": False,
                    "duplicate_or_stale": kind,
                    "queue_size": len(self.queue),
                    "degraded": self.degraded,
                    "width": header.get("width"),
                    "height": header.get("height"),
                    "jpeg_quality": header.get("jpeg_quality", JPEG_QUALITY),
                },
                now,
            )
            return kind

        if self.max_seen_id >= 0 and frame_id > self.max_seen_id + 1:
            self.gap_count += 1
            live_log(
                "LIVE-09",
                "frame_gap",
                frame_id=frame_id,
                expected=self.max_seen_id + 1,
                live_session_id=self.live_session_id,
            )

        self.max_seen_id = frame_id
        item = QueuedFrame(
            frame_id=frame_id,
            header=header,
            jpeg=jpeg,
            received_at=now,
            generation=self.generation,
        )
        dropped = self.queue.put(item)
        self.max_queue_size = max(self.max_queue_size, len(self.queue))
        self._add_meta(
            {
                "frame_id": frame_id,
                "capture_timestamp_monotonic_ms": header.get("capture_timestamp_monotonic_ms"),
                "server_received_ts": now,
                "processed": False,
                "dropped": False,
                "queue_size": len(self.queue),
                "degraded": self.degraded,
                "engine_mode": _mode_name(self.engine),
                "active_shot_id": self._engine_shot_id(),
                "width": header.get("width"),
                "height": header.get("height"),
                "jpeg_quality": header.get("jpeg_quality", JPEG_QUALITY),
            },
            now,
        )
        if dropped is not None:
            self.frames_dropped_server += 1
            self._drop_times.append(now)
            live_log(
                "LIVE-11",
                "frame_dropped",
                frame_id=dropped.frame_id,
                queue_size=self.queue.maxsize,
                live_session_id=self.live_session_id,
                incoming_frame_id=frame_id,
            )
            self._add_meta(
                {
                    "frame_id": dropped.frame_id,
                    "capture_timestamp_monotonic_ms": dropped.header.get(
                        "capture_timestamp_monotonic_ms"
                    ),
                    "server_received_ts": dropped.received_at,
                    "processed": False,
                    "dropped": True,
                    "queue_size": len(self.queue),
                    "degraded": self.degraded,
                    "engine_mode": _mode_name(self.engine),
                    "active_shot_id": self._engine_shot_id(),
                    "width": dropped.header.get("width"),
                    "height": dropped.header.get("height"),
                },
                now,
            )
            self._eval_overload(now)
        return "accepted"

    def _decode_jpeg(self, jpeg: bytes) -> Any:
        if not jpeg:
            return None
        import cv2
        import numpy as np

        arr = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame

    def _next_shot_index(self) -> int:
        if self.engine is None:
            return 1 + len(self.decided_shots)
        return getattr(self.engine, "_next_shot_index", 1 + len(self.decided_shots))

    def _replace_or_reset_engine(self, *, reason: str, frame_width: Optional[int] = None) -> Any:
        """Abandon the current engine instance (or reset it) for a new generation."""
        width = frame_width or self.frame_width
        next_idx = self._next_shot_index()
        live_log(
            "LIVE-17",
            "engine_reset",
            live_session_id=self.live_session_id,
            reason=reason,
            generation=self.generation,
            frame_width=width,
        )
        if self.engine_factory is not None and width:
            self.engine = self.engine_factory(int(width))
            if hasattr(self.engine, "_next_shot_index"):
                self.engine._next_shot_index = next_idx
            self.engine_started = True
            return self.engine
        if self.engine is not None:
            reset = getattr(self.engine, "reset_open_tracking", None)
            if reset is not None:
                reset()
            else:
                abort = getattr(self.engine, "abort_open_shot", None)
                if abort is not None:
                    abort()
        return self.engine

    def _engine_for_decoded_frame(self, frame_bgr: Any, header: dict) -> tuple[Any, bool]:
        """Bind scoring to decoded pixels. Returns (engine, dim_changed)."""
        if frame_bgr is None:
            if self.engine is not None and not self.engine_started:
                # Tests may feed empty JPEG; do not invent a 1280 scoring width.
                return self.engine, False
            return self.engine, False
        height, width = int(frame_bgr.shape[0]), int(frame_bgr.shape[1])
        header_w = int(header.get("width") or 0)
        header_h = int(header.get("height") or 0)
        if (header_w and header_w != width) or (header_h and header_h != height):
            live_log(
                "LIVE-09",
                "dimension_mismatch",
                live_session_id=self.live_session_id,
                header_width=header_w,
                header_height=header_h,
                decoded_width=width,
                decoded_height=height,
            )
        if self.frame_width is None:
            self.frame_width = width
            self.frame_height = height
            self.ensure_engine_started(width)
            return self.engine, False
        if width != self.frame_width or height != self.frame_height:
            live_log(
                "LIVE-07",
                "dimension_change",
                live_session_id=self.live_session_id,
                old_width=self.frame_width,
                old_height=self.frame_height,
                new_width=width,
                new_height=height,
            )
            self.generation += 1
            self.queue.clear()
            self.frame_width = width
            self.frame_height = height
            engine = self._replace_or_reset_engine(
                reason="dimension_change", frame_width=width
            )
            return engine, True
        if not self.engine_started:
            self.ensure_engine_started(width)
        return self.engine, False

    def process_one(self, now: Optional[float] = None) -> ProcessOutcome:
        """Serial engine step. Safe to call from a worker thread (LIVE-04)."""
        with self._proc_lock:
            item = self.queue.pop()
            if item is None:
                return ProcessOutcome(ignored=True)
            start_gen = self.generation
            if self.status != STATUS_ACTIVE or item.generation != start_gen:
                live_log(
                    "LIVE-17",
                    "stale_generation_frame",
                    frame_id=item.frame_id,
                    live_session_id=self.live_session_id,
                    frame_generation=item.generation,
                    current_generation=self.generation,
                )
                return ProcessOutcome(ignored=True, frame_id=item.frame_id)

            start = self.clock() if now is None else now
            frame_bgr = self._decode_jpeg(item.jpeg)
            engine, dim_changed = self._engine_for_decoded_frame(frame_bgr, item.header)
            if engine is None:
                return ProcessOutcome(ignored=True, frame_id=item.frame_id)
            if self.status != STATUS_ACTIVE:
                return ProcessOutcome(ignored=True, frame_id=item.frame_id)
            if self.generation != start_gen and not dim_changed:
                live_log(
                    "LIVE-17",
                    "stale_generation_frame",
                    frame_id=item.frame_id,
                    live_session_id=self.live_session_id,
                    frame_generation=item.generation,
                    current_generation=self.generation,
                )
                return ProcessOutcome(ignored=True, frame_id=item.frame_id)
            commit_gen = self.generation
            decided = engine.process_frame(frame_bgr, item.frame_id)
            end = self.clock()
            return self._commit_process(item, commit_gen, decided, start, end, engine=engine)

    def _commit_process(
        self,
        item: QueuedFrame,
        gen: int,
        decided: list,
        start: float,
        end: float,
        engine: Any = None,
    ) -> ProcessOutcome:
        if self.generation != gen or self.status != STATUS_ACTIVE:
            live_log(
                "LIVE-19",
                "inflight_ignored",
                frame_id=item.frame_id,
                live_session_id=self.live_session_id,
                generation=gen,
                current_generation=self.generation,
            )
            return ProcessOutcome(ignored=True, frame_id=item.frame_id)

        src = engine if engine is not None else self.engine
        self.frames_processed += 1
        capture_ms = float(item.header.get("capture_timestamp_monotonic_ms") or 0)
        e2e_ms = self._e2e_ms(capture_ms, end)
        self._record_e2e(e2e_ms, end)
        events = getattr(src, "shot_events", None) or []
        active_id = events[-1].get("shot_id") if events else None
        self._add_meta(
            {
                "frame_id": item.frame_id,
                "capture_timestamp_monotonic_ms": capture_ms,
                "server_received_ts": item.received_at,
                "processing_start_ts": start,
                "processing_end_ts": end,
                "processed": True,
                "dropped": False,
                "width": item.header.get("width"),
                "height": item.header.get("height"),
                "engine_mode": _mode_name(src),
                "active_shot_id": active_id,
                "queue_size": len(self.queue),
                "e2e_latency_ms": e2e_ms,
                "degraded": self.degraded,
            },
            end,
        )
        self._eval_overload(end)

        kept: list[Any] = []
        for shot in decided or []:
            payload = self._persist_shot(shot, engine=engine)
            if payload is None:
                continue
            kept.append(shot)
            event = {
                "type": "shot_decided",
                "trace_code": "LIVE-16",
                "live_session_id": self.live_session_id,
                "shot_id": payload["shot_id"],
                "result": payload["result"],
                "decision_frame": getattr(shot, "decision_frame", None),
                "decided_at_unix_ms": int(time.time() * 1000),
                "degraded": bool(self.degraded),
            }
            self.unacked[payload["shot_id"]] = event
            self._emit(event)
        return ProcessOutcome(ignored=False, decided=kept, frame_id=item.frame_id)

    def _persist_shot(self, shot: Any, engine: Any = None) -> Optional[dict]:
        shot_id = getattr(shot, "shot_id", None)
        result = getattr(shot, "result", None)
        decision_frame = getattr(shot, "decision_frame", None)
        if not shot_id or result not in ("made", "missed"):
            return None
        if shot_id in self.decided_shots:
            live_log(
                "LIVE-16",
                "shot_idempotent",
                live_session_id=self.live_session_id,
                shot_id=shot_id,
            )
            return self.decided_shots[shot_id]

        src = engine if engine is not None else self.engine
        payload = None
        if self.persist is not None:
            payload = self.persist.upsert_shot(
                live_session_id=self.live_session_id,
                shot_id=shot_id,
                result=result,
                decision_frame=decision_frame,
                engine=src,
                degraded=self.degraded,
            )
            if payload is None:
                live_log(
                    "LIVE-18",
                    "shot_without_parent",
                    live_session_id=self.live_session_id,
                    shot_id=shot_id,
                )
                return None
        if payload is None:
            payload = _shot_point_from_engine(src, shot, self.degraded)
        self.decided_shots[shot_id] = payload
        live_log(
            "LIVE-16",
            "shot_decided",
            live_session_id=self.live_session_id,
            shot_id=shot_id,
            result=result,
            degraded=self.degraded,
        )
        return payload

    def ack_shot(self, shot_id: str) -> None:
        self.unacked.pop(shot_id, None)
        live_log("LIVE-20", "decision_ack", live_session_id=self.live_session_id, shot_id=shot_id)

    def replay_unacked(self) -> list[dict]:
        return list(self.unacked.values())

    def restore_decided_shots(self, shots: list[dict]) -> None:
        """Keep already-persisted shots when a new RAM runtime replaces a lost one."""
        for payload in shots or []:
            shot_id = payload.get("shot_id")
            if not shot_id:
                continue
            self.decided_shots[shot_id] = payload


def _shot_point_from_engine(engine: Any, shot: Any, degraded: bool) -> dict:
    shot_id = shot.shot_id
    events = getattr(engine, "shot_events", None) or []
    ev = next((e for e in events if e.get("shot_id") == shot_id), None)
    if ev is not None:
        from live_shot_point import shot_point_from_event

        return shot_point_from_event(ev, degraded=degraded)
    return {
        "shot_id": shot_id,
        "result": shot.result,
        "origin": {"pixel": None, "court": None},
        "zone": None,
        "trajectory": {
            "arc_height_px": None,
            "apex_pixel": {
                "u": None,
                "v": None,
                "frame_index": getattr(shot, "decision_frame", None),
            },
            "up_frame": None,
            "down_frame": None,
        },
        "degraded": degraded,
    }
