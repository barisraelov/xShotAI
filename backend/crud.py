"""
Data-access helpers for the Job, User, and Session models. Thin wrappers around
a SQLAlchemy session — the caller owns the session lifecycle.

The ORM model `Session` shadows sqlalchemy's `Session` type, so db-handle
parameters are typed with the `DbSession` alias below.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from models import Job, LiveSession, LiveShot, Session, User
from schemas import UserCreate

VERIFICATION_TOKEN_TTL = timedelta(hours=24)


def _new_verification_token() -> str:
    """A cryptographically secure, URL-safe verification token."""
    return secrets.token_urlsafe(32)


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

def create_user(
    db: DbSession, user: UserCreate, *, require_verification: bool = False
) -> User:
    """Hash the password and insert a new user row.

    When `require_verification` is True the row starts unverified with a
    24-hour verification token; the caller is responsible for emailing it.
    When False (SMTP not configured — local dev / tests) the account is
    created already verified with no token.
    """
    from auth import hash_password  # local import avoids an auth <-> crud cycle

    token = _new_verification_token() if require_verification else None
    expires_at = (
        datetime.now(timezone.utc) + VERIFICATION_TOKEN_TTL
        if require_verification
        else None
    )

    row = User(
        email=user.email,
        username=user.username,
        hashed_password=hash_password(user.password),
        is_verified=not require_verification,
        verification_token=token,
        verification_token_expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_user_by_verification_token(db: DbSession, token: str) -> Optional[User]:
    """The user holding this pending verification token, or None."""
    if not token:
        return None
    return db.scalars(
        select(User).where(User.verification_token == token)
    ).first()


def mark_user_verified(db: DbSession, user: User) -> User:
    """Flip is_verified on and clear the token + its expiry."""
    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    db.commit()
    db.refresh(user)
    return user


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
