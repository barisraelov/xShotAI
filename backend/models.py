"""
ORM models.

Job — one uploaded video analysis. `result` holds the full AnalyzeResult dict
(as defined in xShot-prototype/analyze_result_spec.md) once processing finishes,
or the failed-result dict, or NULL while still processing.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    job_id     = Column(String, primary_key=True)
    user_id    = Column(String, nullable=True)
    status     = Column(String, nullable=False, default="processing")
    result     = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
