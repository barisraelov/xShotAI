"""
/sessions endpoints — a logged-in user's saved analysis history.

  GET   /sessions              -> 200 list[SessionSummary]   (newest first)
  GET   /sessions/{session_id} -> 200 SessionDetail          (full AnalyzeResult)
  PATCH /sessions/{session_id} -> 200 SessionDetail          (reschedule date)

All are Bearer-protected. A session that exists but belongs to another user
returns 404 (so ownership isn't leaked).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

import crud
from auth import get_current_user
from db import get_db
from models import User
from schemas import SessionDateUpdate, SessionDetail, SessionSummary

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionSummary])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> list:
    return crud.get_sessions_by_user_id(db, current_user.id)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    session = crud.get_session(db, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionDetail)
def update_session(
    session_id: str,
    payload: SessionDateUpdate,
    current_user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    """Reschedule a saved session to a different date. Only the owner may do
    this; a future date is rejected."""
    session = crud.get_session(db, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    new_dt = payload.created_at
    if new_dt.tzinfo is None:
        new_dt = new_dt.replace(tzinfo=timezone.utc)
    if new_dt > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400, detail="Session date cannot be in the future"
        )

    return crud.update_session_created_at(db, session_id, new_dt)
