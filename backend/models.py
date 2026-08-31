"""
ORM models.

User — an authenticated account. `hashed_password` is a passlib/bcrypt hash,
never a plaintext password.

Job — one uploaded video analysis. `result` holds the full AnalyzeResult dict
(as defined in xShot-prototype/analyze_result_spec.md) once processing finishes,
or the failed-result dict, or NULL while still processing. `user_id` links to the
owning account, but stays nullable so pre-auth jobs keep working.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_str() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id              = Column(String, primary_key=True, default=_uuid_str)
    email           = Column(String, unique=True, index=True, nullable=False)
    username        = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Job(Base):
    __tablename__ = "jobs"

    job_id     = Column(String, primary_key=True)
    user_id    = Column(String, ForeignKey("users.id"), nullable=True)
    status     = Column(String, nullable=False, default="processing")
    result     = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
