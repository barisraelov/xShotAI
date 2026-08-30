"""
Data-access helpers for the Job model. Thin wrappers around a SQLAlchemy
Session — the caller owns the session lifecycle.
"""

from typing import Optional

from sqlalchemy.orm import Session

from models import Job


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
