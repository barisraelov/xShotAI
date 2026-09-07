"""
Data-access helpers for the Job, User, and Session models. Thin wrappers around
a SQLAlchemy session — the caller owns the session lifecycle.

The ORM model `Session` shadows sqlalchemy's `Session` type, so db-handle
parameters are typed with the `DbSession` alias below.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
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
    # Default label: "Session #N" where N counts this user's saved sessions.
    prior = db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == user_id)
    ) or 0
    row = Session(
        user_id=user_id,
        job_id=job_id,
        title=f"Session #{prior + 1}",
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


def update_session(
    db: DbSession,
    session_id: str,
    *,
    new_created_at: Optional[datetime] = None,
    new_title: Optional[str] = None,
) -> Optional[Session]:
    """Edit a saved session's date and/or title. Only the fields passed as
    non-None are changed. Returns the updated row, or None if the id is
    unknown. Ownership is checked by the caller."""
    row = db.get(Session, session_id)
    if row is None:
        return None
    if new_created_at is not None:
        row.created_at = new_created_at
    if new_title is not None:
        row.title = new_title
    db.commit()
    db.refresh(row)
    return row


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


def set_user_password(db: DbSession, user: User, new_hashed_password: str) -> User:
    """Store a new bcrypt hash for the user."""
    user.hashed_password = new_hashed_password
    db.commit()
    db.refresh(user)
    return user


# ── Live sessions ────────────────────────────────────────────────────────────

def create_live_session(db: DbSession, *, live_session_id: str, user_id: str) -> LiveSession:
    row = LiveSession(id=live_session_id, user_id=user_id, status="prepare")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_live_session(db: DbSession, live_session_id: str) -> Optional[LiveSession]:
    return db.get(LiveSession, live_session_id)


def ensure_active_live_session(
    db: DbSession, *, live_session_id: str, user_id: str
) -> LiveSession:
    """Create the live_sessions row on GO, or reuse it (LIVE-18 idempotent)."""
    row = db.get(LiveSession, live_session_id)
    if row is None:
        row = LiveSession(
            id=live_session_id,
            user_id=user_id,
            status="active",
            started_at=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
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
