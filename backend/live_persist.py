"""PostgreSQL persistence for Live sessions (LIVE-16 / LIVE-18)."""

from __future__ import annotations

from typing import Any, Optional

from live_shot_point import shot_point_from_decided
from result_builder import build_real_result


class _Decided:
    def __init__(self, shot_id: str, result: str, decision_frame: Optional[int]) -> None:
        self.shot_id = shot_id
        self.result = result
        self.decision_frame = decision_frame


class DbLivePersist:
    def create_prepare(self, live_session_id: str, user_id: str) -> None:
        import crud
        from db import SessionLocal

        db = SessionLocal()
        try:
            existing = crud.get_live_session(db, live_session_id)
            if existing is None:
                crud.create_live_session(
                    db, live_session_id=live_session_id, user_id=user_id
                )
        finally:
            db.close()

    def activate(self, live_session_id: str) -> None:
        import crud
        from db import SessionLocal

        db = SessionLocal()
        try:
            crud.activate_live_session(db, live_session_id)
        finally:
            db.close()

    def upsert_shot(
        self,
        *,
        live_session_id: str,
        shot_id: str,
        result: str,
        decision_frame: Optional[int],
        engine: Any,
        degraded: bool,
    ) -> dict:
        import crud
        from db import SessionLocal

        payload = shot_point_from_decided(
            engine,
            _Decided(shot_id, result, decision_frame),
            degraded=degraded,
        )
        db = SessionLocal()
        try:
            row, _inserted = crud.upsert_live_shot(
                db,
                live_session_id=live_session_id,
                shot_id=shot_id,
                result=result,
                decision_frame=decision_frame,
                payload=payload,
                degraded=degraded,
            )
            return row.payload
        finally:
            db.close()

    def complete(
        self,
        live_session_id: str,
        user_id: str,
        shot_points: list[dict],
        *,
        save_history: bool = True,
    ) -> dict:
        import crud
        from db import SessionLocal

        db = SessionLocal()
        try:
            existing = crud.get_live_session(db, live_session_id)
            if existing is not None and existing.status == "completed" and existing.result:
                return {
                    "result": existing.result,
                    "history_session_id": existing.history_session_id,
                }
            result = build_real_result(live_session_id, shot_points, None)
            history_id = None
            if save_history:
                session_row = crud.create_session(
                    db, user_id=user_id, result=result, job_id=None
                )
                history_id = session_row.id
            crud.complete_live_session(
                db,
                live_session_id,
                result=result,
                history_session_id=history_id,
            )
            return {"result": result, "history_session_id": history_id}
        finally:
            db.close()


class MemoryLivePersist:
    """In-memory persist for tests (no PostgreSQL)."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.shots: dict[tuple[str, str], dict] = {}
        self.history: list[dict] = []

    def create_prepare(self, live_session_id: str, user_id: str) -> None:
        self.sessions.setdefault(
            live_session_id,
            {"user_id": user_id, "status": "prepare", "history_session_id": None},
        )

    def activate(self, live_session_id: str) -> None:
        row = self.sessions.setdefault(
            live_session_id, {"user_id": None, "status": "prepare"}
        )
        row["status"] = "active"

    def upsert_shot(
        self,
        *,
        live_session_id: str,
        shot_id: str,
        result: str,
        decision_frame: Optional[int],
        engine: Any,
        degraded: bool,
    ) -> dict:
        key = (live_session_id, shot_id)
        if key in self.shots:
            return self.shots[key]
        payload = shot_point_from_decided(
            engine,
            _Decided(shot_id, result, decision_frame),
            degraded=degraded,
        )
        self.shots[key] = payload
        return payload

    def complete(
        self,
        live_session_id: str,
        user_id: str,
        shot_points: list[dict],
        *,
        save_history: bool = True,
    ) -> dict:
        result = build_real_result(live_session_id, shot_points, None)
        history_id = None
        if save_history:
            history_id = f"hist-{len(self.history) + 1}"
            self.history.append({"id": history_id, "result": result, "user_id": user_id})
        row = self.sessions.setdefault(live_session_id, {"user_id": user_id})
        row["status"] = "completed"
        row["result"] = result
        row["history_session_id"] = history_id
        return {"result": result, "history_session_id": history_id}
