"""
WebSocket /live — JPEG frames + control messages (LIVE-04 / LIVE-05 / LIVE-09).

Auth is the first in-socket JSON message (no JWT query string).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth import _decode_token, _resolve_user
from config import settings
from db import SessionLocal
from live_constants import CLOCK_RESYNC_S, DISCONNECT_TTL_S, PROTOCOL_VERSION
from live_engine import default_engine_factory
from live_log import live_log
from live_persist import DbLivePersist
from live_protocol import FrameProtocolError, unpack_frame
from live_runtime import STATUS_ACTIVE, STATUS_COMPLETED, LiveRuntime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

WS_ORIGIN_REJECT_CODE = 4403


def _normalize_origin(origin: Optional[str]) -> str:
    return (origin or "").strip().rstrip("/")


def origin_is_allowed(
    origin: Optional[str],
    allowed: Optional[list[str]] = None,
) -> bool:
    """Exact Origin match against CORS_ORIGINS + local dev. '*' is never allow-all."""
    normalized = _normalize_origin(origin)
    if not normalized:
        return False
    origins = allowed if allowed is not None else settings.websocket_allowed_origins
    allowed_set = {_normalize_origin(item) for item in origins if item}
    return normalized in allowed_set


async def _reject_origin(websocket: WebSocket, origin: Optional[str]) -> None:
    logger.warning("live websocket origin rejected origin=%r", origin or "")
    await websocket.close(code=WS_ORIGIN_REJECT_CODE)


def _state(ws: WebSocket, name: str, default: Any) -> Any:
    return getattr(ws.app.state, name, default)


def _lookup_user(ws: WebSocket, token: str) -> Any:
    custom = _state(ws, "live_user_from_token", None)
    if custom is not None:
        return custom(token)
    token_data = _decode_token(token)
    if token_data is None:
        return None
    db = SessionLocal()
    try:
        return _resolve_user(db, token_data)
    finally:
        db.close()


def _persist(ws: WebSocket) -> Any:
    return _state(ws, "live_persist", None) or DbLivePersist()


def _engine_factory(ws: WebSocket):
    return _state(ws, "live_engine_factory", default_engine_factory)


def _registry(ws: WebSocket) -> dict:
    reg = _state(ws, "live_registry", None)
    if reg is None:
        reg = {}
        ws.app.state.live_registry = reg
    return reg


def _ttl_tasks(ws: WebSocket) -> dict:
    tasks = _state(ws, "live_ttl_tasks", None)
    if tasks is None:
        tasks = {}
        ws.app.state.live_ttl_tasks = tasks
    return tasks


def _cancel_ttl(ws: WebSocket, live_session_id: str) -> None:
    tasks = _ttl_tasks(ws)
    task = tasks.pop(live_session_id, None)
    if task is not None:
        task.cancel()


def _schedule_ttl(ws: WebSocket, runtime: LiveRuntime, persist: Any) -> None:
    tasks = _ttl_tasks(ws)

    async def _ttl() -> None:
        try:
            await asyncio.sleep(DISCONNECT_TTL_S)
        except asyncio.CancelledError:
            return
        if runtime.disconnected_at is None or runtime.status == STATUS_COMPLETED:
            return
        runtime.persist = persist
        runtime.complete(reason="disconnect_timeout")
        live_log("LIVE-17", "ttl_complete", live_session_id=runtime.live_session_id)

    _cancel_ttl(ws, runtime.live_session_id)
    tasks[runtime.live_session_id] = asyncio.create_task(_ttl())


async def _send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        logger.debug("live send failed", exc_info=True)


async def _authenticate(ws: WebSocket) -> Any:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=15.0)
    except Exception:
        await _send(ws, {
            "type": "error",
            "code": "unauthorized",
            "message": "Authentication required",
        })
        await ws.close(code=4401)
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await _send(ws, {
            "type": "error",
            "code": "unauthorized",
            "message": "Authentication required",
        })
        await ws.close(code=4401)
        return None
    token = None
    if msg.get("type") == "auth":
        token = msg.get("access_token")
    elif msg.get("type") == "prepare" and msg.get("access_token"):
        token = msg.get("access_token")
        ws.state._pending_prepare = msg
    if not token:
        await _send(ws, {
            "type": "error",
            "code": "unauthorized",
            "message": "Authentication required",
        })
        await ws.close(code=4401)
        return None
    user = _lookup_user(ws, token)
    if user is None:
        await _send(ws, {
            "type": "error",
            "code": "unauthorized",
            "message": "Authentication required",
        })
        await ws.close(code=4401)
        return None
    await _send(ws, {
        "type": "auth_ok",
        "user_id": getattr(user, "id", None),
        "protocol_version": PROTOCOL_VERSION,
    })
    return user


async def _warmup_engine(ws: WebSocket) -> Any:
    factory = _engine_factory(ws)
    return await asyncio.to_thread(factory)


@router.websocket("/live")
async def live_socket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if not origin_is_allowed(origin):
        await _reject_origin(websocket, origin)
        return
    await websocket.accept()
    user = await _authenticate(websocket)
    if user is None:
        return

    persist = _persist(websocket)
    registry = _registry(websocket)
    runtime: Optional[LiveRuntime] = None
    worker_task: Optional[asyncio.Task] = None
    tick_task: Optional[asyncio.Task] = None
    q_event = asyncio.Event()
    outbound: asyncio.Queue = asyncio.Queue()

    def emit(payload: dict) -> None:
        outbound.put_nowait(payload)

    sender_task = asyncio.create_task(_drain_outbound(websocket, outbound))

    async def worker() -> None:
        while True:
            await q_event.wait()
            q_event.clear()
            if runtime is None or runtime.status == STATUS_COMPLETED:
                break
            if runtime.status != STATUS_ACTIVE:
                continue
            outcome = await asyncio.to_thread(runtime.process_one)
            if outcome and not outcome.ignored:
                pass
            if runtime is not None and len(runtime.queue):
                q_event.set()

    async def ticker() -> None:
        while True:
            await asyncio.sleep(0.25)
            if runtime is None or runtime.status == STATUS_COMPLETED:
                return
            runtime.tick()

    async def handle_prepare(msg: dict) -> None:
        nonlocal runtime, worker_task, tick_task
        resume_id = msg.get("live_session_id")
        existing = registry.get(resume_id) if resume_id else None
        if existing is not None:
            if existing.user_id != user.id:
                await _send(websocket, {
                    "type": "error",
                    "code": "forbidden",
                    "message": "live session belongs to another user",
                })
                await websocket.close(code=4403)
                return
            _cancel_ttl(websocket, existing.live_session_id)
            try:
                info = existing.on_reconnect(user.id)
            except Exception as exc:
                await _send(websocket, {
                    "type": "error",
                    "code": "session_closed",
                    "message": str(exc),
                })
                if existing.completed_result is not None:
                    await _send(websocket, {
                        "type": "session_complete",
                        "live_session_id": existing.live_session_id,
                        "session_id": existing.history_session_id,
                        "result": existing.completed_result,
                        "reason": "already_completed",
                    })
                return
            runtime = existing
            runtime.on_outbound = emit
            await _send(websocket, {
                "type": "prepared",
                "live_session_id": runtime.live_session_id,
                "resumed": True,
                "gap_s": info["gap_s"],
                "protocol_version": PROTOCOL_VERSION,
            })
            for event in info.get("replay") or []:
                await _send(websocket, event)
        else:
            live_session_id = resume_id or str(uuid.uuid4())
            warmed = await _warmup_engine(websocket)
            engine = None
            engine_factory = None
            if callable(warmed) and not hasattr(warmed, "process_frame"):
                engine_factory = warmed
            else:
                engine = warmed
            runtime = LiveRuntime(
                live_session_id,
                user.id,
                engine,
                persist=persist,
                on_outbound=emit,
                started=False,
                engine_factory=engine_factory,
            )
            existing_row = persist.get_session(live_session_id) if persist is not None else None
            if existing_row and existing_row.get("status") == "completed":
                await _send(websocket, {
                    "type": "error",
                    "code": "session_closed",
                    "message": "live session already completed",
                    "live_session_id": live_session_id,
                })
                return
            if existing_row and existing_row.get("status") == "active":
                runtime.restore_decided_shots(persist.load_shots(live_session_id))
            registry[live_session_id] = runtime
            await _send(websocket, {
                "type": "prepared",
                "live_session_id": live_session_id,
                "resumed": False,
                "protocol_version": PROTOCOL_VERSION,
            })
        if worker_task is None or worker_task.done():
            worker_task = asyncio.create_task(worker())
        if tick_task is None or tick_task.done():
            tick_task = asyncio.create_task(ticker())

    try:
        pending = getattr(websocket.state, "_pending_prepare", None)
        if pending is not None:
            await handle_prepare(pending)

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                if runtime is None:
                    continue
                try:
                    header, jpeg = unpack_frame(message["bytes"])
                except FrameProtocolError as exc:
                    live_log("LIVE-09", "unpack_failed", error=str(exc))
                    continue
                runtime.accept_frame(header, jpeg)
                q_event.set()
                continue
            text = message.get("text")
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue
            typ = msg.get("type")
            if typ == "prepare":
                await handle_prepare(msg)
            elif typ == "ping":
                pong = {
                    "type": "pong",
                    "t": msg.get("t"),
                    "server_t": time.monotonic() * 1000.0,
                    "resync_s": CLOCK_RESYNC_S,
                }
                if msg.get("ping_id") is not None:
                    pong["ping_id"] = msg.get("ping_id")
                await _send(websocket, pong)
            elif typ == "clock_offset":
                if runtime is not None:
                    runtime.set_clock_offset(float(msg.get("offset_ms") or 0))
            elif typ == "client_stats":
                if runtime is not None:
                    runtime.note_client_stats(
                        frames_captured=msg.get("frames_captured"),
                        frames_sent=msg.get("frames_sent"),
                        frames_dropped_client=msg.get("frames_dropped_client"),
                    )
            elif typ == "go":
                if runtime is None:
                    continue
                runtime.go()
                q_event.set()
            elif typ == "stop":
                if runtime is None:
                    continue
                runtime.stop()
                break
            elif typ == "continue":
                if runtime is not None:
                    runtime.continue_overload()
            elif typ == "decision_ack":
                if runtime is not None:
                    runtime.ack_shot(str(msg.get("shot_id") or ""))
            elif typ == "auth":
                continue
    except WebSocketDisconnect:
        pass
    finally:
        if worker_task is not None:
            worker_task.cancel()
        if tick_task is not None:
            tick_task.cancel()
        try:
            while not outbound.empty():
                await _send(websocket, outbound.get_nowait())
        except Exception:
            pass
        sender_task.cancel()
        if runtime is not None and runtime.status != STATUS_COMPLETED:
            runtime.on_disconnect()
            _schedule_ttl(websocket, runtime, persist)


async def _drain_outbound(ws: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            payload = await queue.get()
            await _send(ws, payload)
    except asyncio.CancelledError:
        return
