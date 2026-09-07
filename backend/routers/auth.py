"""
/auth endpoints — registration, login, current-user probe, password change.

  POST /auth/register         -> 201 UserOut
  POST /auth/login            -> 200 Token          (OAuth2 password form; Swagger-native)
  GET  /auth/me               -> 200 UserOut        (Bearer-protected)
  POST /auth/change-password  -> 200 MessageResult  (Bearer-protected)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import crud
from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from db import get_db
from models import User
from schemas import ChangePasswordRequest, MessageResult, Token, UserCreate, UserOut

MIN_PASSWORD_LEN = 8

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)) -> User:
    if crud.get_user_by_email(db, user.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    try:
        return crud.create_user(db, user)
    except IntegrityError:
        # Lost a race against a concurrent registration on the same unique value.
        db.rollback()
        raise HTTPException(status_code=400, detail="Email or username already taken")


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """`username` in the form may be either the account email or the username."""
    identifier = form_data.username
    user = crud.get_user_by_email(db, identifier) or crud.get_user_by_username(
        db, identifier
    )
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": user.id, "email": user.email})
    return Token(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", response_model=MessageResult)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResult:
    """Change the signed-in user's password. The current password must match;
    the new one must be at least 8 characters and different from the old one."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(payload.new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"New password must be at least {MIN_PASSWORD_LEN} characters.",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=400,
            detail="New password must be different from the current one.",
        )

    crud.set_user_password(db, current_user, hash_password(payload.new_password))
    return MessageResult(detail="Password updated successfully.")
