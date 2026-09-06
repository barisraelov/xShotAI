"""
Authentication helpers: password hashing, JWT minting, and the FastAPI
dependencies that resolve the current user from a bearer token.

Token payload shape:
    {
        "sub":   <user_id>,          # subject = user id
        "email": <email>,
        "exp":   <unix timestamp>,   # added by create_access_token
    }
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

import crud
from config import settings
from db import get_db
from models import User
from schemas import TokenData

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl is only used by the OpenAPI docs "Authorize" button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


# ── Passwords ─────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Encode `data` into a signed JWT with an `exp` claim. Defaults to
    settings.ACCESS_TOKEN_EXPIRE_MINUTES (24h) when no delta is given."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def _decode_token(token: str) -> Optional[TokenData]:
    """Return TokenData for a valid token, or None if it is missing/expired/bad."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
    user_id = payload.get("sub")
    email = payload.get("email")
    if user_id is None and email is None:
        return None
    return TokenData(user_id=user_id, email=email)


def _resolve_user(db: Session, token_data: TokenData) -> Optional[User]:
    user = None
    if token_data.user_id:
        user = crud.get_user_by_id(db, token_data.user_id)
    if user is None and token_data.email:
        user = crud.get_user_by_email(db, token_data.email)
    return user


# ── FastAPI dependencies ─────────────────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the bearer token to a User row, or raise 401."""
    token_data = _decode_token(token)
    if token_data is None:
        raise _CREDENTIALS_EXC
    user = _resolve_user(db, token_data)
    if user is None:
        raise _CREDENTIALS_EXC
    return user


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of raising — for
    endpoints that serve both guests and authenticated users."""
    if not token:
        return None
    token_data = _decode_token(token)
    if token_data is None:
        return None
    return _resolve_user(db, token_data)
