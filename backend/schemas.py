"""
Pydantic request/response models for the auth layer.

These are transport shapes only — the ORM models live in models.py.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Shown when a session has no user-set title (old rows, or a cleared field).
DEFAULT_SESSION_TITLE = "Training Session"


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    username: str
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    user_id: Optional[str] = None
    status: str
    result: Optional[dict] = None
    created_at: datetime


class SessionSummary(BaseModel):
    """One row in the user's history list."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: Optional[str] = None
    created_at: datetime
    total_shots: int
    made: int
    missed: int
    accuracy_pct: float


class SessionDetail(SessionSummary):
    """A single past session with its full AnalyzeResult payload."""
    job_id: Optional[str] = None
    result: dict


class SessionUpdate(BaseModel):
    """PATCH /sessions/{id} body — edit a saved session's date and/or title.
    Both fields optional so a caller can change just one."""
    created_at: Optional[datetime] = None
    title: Optional[str] = Field(None, max_length=60)


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password body (Bearer-protected)."""
    current_password: str
    new_password: str


class ContactMessage(BaseModel):
    """POST /contact body — support / feedback form."""
    name: str
    email: str
    subject: str
    message: str


class MessageResult(BaseModel):
    """`{ "detail": "..." }` body for status-only endpoints."""
    detail: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
