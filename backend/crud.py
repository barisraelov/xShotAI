"""
Data-access helpers for the Job and User models. Thin wrappers around a
SQLAlchemy Session — the caller owns the session lifecycle.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Job, User
from schemas import UserCreate


# ── Jobs ─────────────────────────────────────────────────────────────────────

def create_job(db: Session, job_id: str, user_id: Optional[str] = None) -> Job:
    """Insert a new job row in the 'processing' state."""
    job = Job(job_id=job_id, user_id=user_id, status="processing", result=None)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    db: Session,
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


def get_job(db: Session, job_id: str) -> Optional[Job]:
    """Fetch a single job by id, or None."""
    return db.get(Job, job_id)


def get_jobs_by_user_id(db: Session, user_id: str) -> list[Job]:
    """All jobs owned by a user, newest first."""
    stmt = (
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
    )
    return list(db.scalars(stmt).all())


# ── Users ────────────────────────────────────────────────────────────────────

def create_user(db: Session, user: UserCreate) -> User:
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


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalars(select(User).where(User.email == email)).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.scalars(select(User).where(User.username == username)).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.get(User, user_id)
