"""
Data-access helpers for the Job, User, and Session models. Thin wrappers around
a SQLAlchemy session — the caller owns the session lifecycle.

The ORM model `Session` shadows sqlalchemy's `Session` type, so db-handle
parameters are typed with the `DbSession` alias below.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from models import Job, LiveSession, LiveShot, Session, User
from schemas import UserCreate


# ── Jobs ─────────────────────────────────────────────────────────────────────

def create_job(db: DbSession, job_id: str, user_id: Optional[str] = None) -> Job:
    """Insert a new job row in the 'processing' state."""
    job = Job(job_id=job_id, user_id=user_id, status="processing", result=None)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    db: DbSession,
    job_id: str,
    status: str,
    result: Optional[dict] = None,
) -> Optional[Job]:
    """Update status (and optionally result) for an existing job. Returns the
    updated row, or None if the job_id is unknown."""
    job = db.get(Job, job_id)
    if job is None:
        return None
    job.status = status
    job.result = result
    db.commit()
    db.refresh(job)
    return job


def get_job(db: DbSession, job_id: str) -> Optional[Job]:
    """Fetch a single job by id, or None."""
    return db.get(Job, job_id)


def get_jobs_by_user_id(db: DbSession, user_id: str) -> list[Job]:
    """All jobs owned by a user, newest first."""
    stmt = (
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
    )
    return list(db.scalars(stmt).all())


# ── Sessions (saved analysis history) ────────────────────────────────────────

def create_session(
    db: DbSession,
    *,
    user_id: str,
    result: dict,
    job_id: Optional[str] = None,
) -> Session:
    """Persist a completed AnalyzeResult to a user's history. Summary columns
    are derived from result["summary"]."""
    summary = result.get("summary") or {}
    row = Session(
        user_id=user_id,
        job_id=job_id,
        total_shots=int(summary.get("total_shots", 0) or 0),
        made=int(summary.get("made", 0) or 0),
        missed=int(summary.get("missed", 0) or 0),
        accuracy_pct=float(summary.get("accuracy_pct", 0.0) or 0.0),
        result=result,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_sessions_by_user_id(db: DbSession, user_id: str) -> list[Session]:
    """All saved sessions for a user, most recent first."""
    stmt = (
        select(Session)
        .where(Session.user_id == user_id)
        .order_by(Session.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def get_session(db: DbSession, session_id: str) -> Optional[Session]:
    """Fetch a single saved session by id, or None."""
    return db.get(Session, session_id)


# ── Users ────────────────────────────────────────────────────────────────────

def create_user(db: DbSession, user: UserCreate) -> User:
    """Hash the password and insert a new user row."""
    from auth import hash_password  # local import avoids an auth <-> crud cycle

    row = User(
        email=user.email,
        username=user.username,
        hashed_password=hash_password(user.password),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_user_by_email(db: DbSession, email: str) -> Optional[User]:
    return db.scalars(select(User).where(User.email == email)).first()


def get_user_by_username(db: DbSession, username: str) -> Optional[User]:
    return db.scalars(select(User).where(User.username == username)).first()


def get_user_by_id(db: DbSession, user_id: str) -> Optional[User]:
    return db.get(User, user_id)


# ── Live sessions ────────────────────────────────────────────────────────────

def create_live_session(db: DbSession, *, live_session_id: str, user_id: str) -> LiveSession:
    row = LiveSession(id=live_session_id, user_id=user_id, status="prepare")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_live_session(db: DbSession, live_session_id: str) -> Optional[LiveSession]:
    return db.get(LiveSession, live_session_id)


def activate_live_session(db: DbSession, live_session_id: str) -> Optional[LiveSession]:
    row = db.get(LiveSession, live_session_id)
    if row is None:
        return None
    if row.status == "prepare":
        row.status = "active"
        row.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


def complete_live_session(
    db: DbSession,
    live_session_id: str,
    *,
    result: dict,
    history_session_id: Optional[str],
) -> Optional[LiveSession]:
    row = db.get(LiveSession, live_session_id)
    if row is None:
        return None
    row.status = "completed"
    row.completed_at = datetime.now(timezone.utc)
    row.result = result
    row.history_session_id = history_session_id
    db.commit()
    db.refresh(row)
    return row


def upsert_live_shot(
    db: DbSession,
    *,
    live_session_id: str,
    shot_id: str,
    result: str,
    decision_frame: Optional[int],
    payload: dict,
    degraded: bool,
) -> tuple[LiveShot, bool]:
    """Insert a decided shot. Returns (row, inserted). Existing rows are left unchanged."""
    stmt = select(LiveShot).where(
        LiveShot.live_session_id == live_session_id,
        LiveShot.shot_id == shot_id,
    )
    existing = db.scalars(stmt).first()
    if existing is not None:
        return existing, False
    row = LiveShot(
        live_session_id=live_session_id,
        shot_id=shot_id,
        result=result,
        decision_frame=decision_frame,
        payload=payload,
        degraded=degraded,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def list_live_shots(db: DbSession, live_session_id: str) -> list[LiveShot]:
    stmt = (
        select(LiveShot)
        .where(LiveShot.live_session_id == live_session_id)
        .order_by(LiveShot.shot_id.asc())
    )
    return list(db.scalars(stmt).all())
