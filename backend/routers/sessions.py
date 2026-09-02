"""
/sessions endpoints — a logged-in user's saved analysis history.

  GET /sessions              -> 200 list[SessionSummary]   (newest first)
  GET /sessions/{session_id} -> 200 SessionDetail          (full AnalyzeResult)

Both are Bearer-protected. A session that exists but belongs to another user
returns 404 (so ownership isn't leaked).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

import crud
from auth import get_current_user
from db import get_db
from models import User
from schemas import SessionDetail, SessionSummary

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
