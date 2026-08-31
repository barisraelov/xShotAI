"""
/users endpoints — per-account data for the authenticated user.

  GET /users/me/history  -> 200 list[JobOut]   (Bearer-protected)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import crud
from auth import get_current_user
from db import get_db
from models import User
from schemas import JobOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/history", response_model=list[JobOut])
def my_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    """Every job owned by the current user, newest first."""
    return crud.get_jobs_by_user_id(db, current_user.id)
