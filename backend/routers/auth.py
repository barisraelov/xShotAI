"""
/auth endpoints — registration, login, email verification, current-user probe.

  POST /auth/register      -> 201 UserOut
  POST /auth/login         -> 200 Token          (OAuth2 password form; Swagger-native)
  GET  /auth/verify-email  -> 200 MessageResult  (?token=...)
  GET  /auth/me            -> 200 UserOut        (Bearer-protected)

Email verification: when Gmail SMTP is configured (settings.email_verification_active)
a new account is created unverified with a 24h token and a verification email is
sent from a background task. Unverified accounts cannot log in. When SMTP is not
configured (local dev / CI) accounts are created already verified and no email
is sent.
"""

import logging
import smtplib
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import crud
from auth import create_access_token, get_current_user, verify_password
from config import settings
from db import get_db
from email_utils import send_verification_email
from models import User
from schemas import MessageResult, Token, UserCreate, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_VERIFY_FIRST_DETAIL = "Please verify your email before logging in"
_BAD_TOKEN_DETAIL = "Verification link is invalid or has expired"


def _dispatch_verification_email(email: str, username: str, token: str) -> None:
    """Background task: best-effort send. Runs AFTER the registration response
    has been returned, so nothing here can turn a 201 into a 500. Every failure
    is swallowed and logged; the account already exists and can be re-sent a
    link later.
    """
    try:
        send_verification_email(to_email=email, username=username, token=token)
    except (smtplib.SMTPException, OSError, RuntimeError) as exc:
        # Expected operational failures: auth rejected, SSL/handshake, timeout,
        # DNS/socket error, or SMTP not configured. One concise line, no stack.
        logger.warning("Verification email to %s not sent: %s", email, exc)
    except Exception:  # noqa: BLE001 — never let a background task raise
        logger.exception("Unexpected error sending verification email to %s", email)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    user: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> User:
    if crud.get_user_by_email(db, user.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if crud.get_user_by_username(db, user.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    require_verification = settings.email_verification_active
    try:
        row = crud.create_user(db, user, require_verification=require_verification)
    except IntegrityError:
        # Lost a race against a concurrent registration on the same unique value.
        db.rollback()
        raise HTTPException(status_code=400, detail="Email or username already taken")
    except SQLAlchemyError:
        # Any other DB failure — e.g. the email-verification columns are missing
        # because migration 002_email_verification.sql has not been applied to
        # this database. Roll back and surface a clean 503 instead of a raw 500.
        db.rollback()
        logger.exception("Registration failed: database error while creating user")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registration is temporarily unavailable. Please try again later.",
        )

    if require_verification and row.verification_token:
        background_tasks.add_task(
            _dispatch_verification_email,
            row.email,
            row.username,
            row.verification_token,
        )

    return row


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

    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_VERIFY_FIRST_DETAIL)

    token = create_access_token({"sub": user.id, "email": user.email})
    return Token(access_token=token, token_type="bearer")


@router.get("/verify-email", response_model=MessageResult)
def verify_email(token: str, db: Session = Depends(get_db)) -> MessageResult:
    """Confirm an address from the emailed link. Idempotent-ish: once a token is
    consumed it is cleared, so a second click reports the link as invalid."""
    user = crud.get_user_by_verification_token(db, token)
    if user is None:
        raise HTTPException(status_code=400, detail=_BAD_TOKEN_DETAIL)

    expires_at = user.verification_token_expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is None or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail=_BAD_TOKEN_DETAIL)

    crud.mark_user_verified(db, user)
    return MessageResult(detail="Email verified successfully")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
