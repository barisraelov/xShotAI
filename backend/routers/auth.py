"""
/auth endpoints — registration, login, and the current-user probe.

  POST /auth/register  -> 201 UserOut
  POST /auth/login     -> 200 Token          (OAuth2 password form; Swagger-native)
  GET  /auth/me        -> 200 UserOut        (Bearer-protected)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import crud
from auth import create_access_token, get_current_user, verify_password
from db import get_db
from models import User
from schemas import Token, UserCreate, UserOut

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
