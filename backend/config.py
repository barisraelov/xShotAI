"""
Application configuration.

Settings come from environment variables (or a local .env file) via
pydantic-settings, with development-friendly fallbacks.

  DATABASE_URL                  — PostgreSQL DSN. A `postgres://` scheme (used by
                                  Heroku / Render / Railway) is rewritten to
                                  `postgresql://`, which SQLAlchemy 2.0 requires.
                                  Defaults to the local docker-compose instance.
  SECRET_KEY                    — HMAC key for signing JWTs. Read from the
                                  environment; a random per-process key is used
                                  as a dev fallback (tokens then reset on every
                                  restart — always set this in production).
  JWT_ALGORITHM                 — signing algorithm (HS256)
  ACCESS_TOKEN_EXPIRE_MINUTES   — access-token lifetime (default 24h)
  CORS_ORIGINS                  — comma-separated allowed origins, or "*" to allow
                                  any origin for HTTP CORS (default). WebSocket /live
                                  never treats "*" as allow-all: it uses this list
                                  plus local Vite/prototype origins, and rejects a
                                  missing or unknown Origin.
  RAILWAY_GIT_* / BUILD_SHA     — deploy fingerprint. Railway injects
                                  RAILWAY_GIT_COMMIT_SHA / _BRANCH / _COMMIT_MESSAGE
                                  into the running container automatically; set
                                  BUILD_SHA yourself on other platforms. Surfaced
                                  at GET /version and in /openapi.json info.version.
  SMTP_HOST / _PORT / _USER /   — Gmail SMTP credentials for the registration
  SMTP_PASS / SMTP_FROM           verification email. SMTP_PORT 465 uses implicit
                                  SSL; 587 uses STARTTLS. SMTP_FROM overrides the
                                  visible From address (defaults to SMTP_USER).
                                  When SMTP_USER / SMTP_PASS are unset, email
                                  verification is disabled and new accounts are
                                  created already-verified (local dev / tests).
  FRONTEND_URL                  — public origin of the SPA, used to build the
                                  {FRONTEND_URL}/verify-email?token=... link in
                                  the verification email. Defaults to the local
                                  Vite dev server.
"""

import os
import secrets

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Evaluated once per process. Only used when SECRET_KEY is not in the environment.
_DEV_SECRET_FALLBACK = os.getenv("SECRET_KEY") or "dev-only-" + secrets.token_urlsafe(48)

# Always merged into a tightened CORS list and into WebSocket Origin checks.
LOCAL_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = (
        "postgresql://xshot_user:xshot_password@localhost:5432/xshot_db"
    )

    SECRET_KEY: str = _DEV_SECRET_FALLBACK
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    CORS_ORIGINS: str = "*"

    # ── Email verification (Gmail SMTP) ──────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""  # visible From address; falls back to SMTP_USER
    FRONTEND_URL: str = "http://localhost:5173"

    # Deploy fingerprint (all optional; empty in local dev).
    RAILWAY_GIT_COMMIT_SHA: str = ""
    RAILWAY_GIT_BRANCH: str = ""
    RAILWAY_GIT_COMMIT_MESSAGE: str = ""
    BUILD_SHA: str = ""

    @property
    def git_sha(self) -> str:
        return self.RAILWAY_GIT_COMMIT_SHA or self.BUILD_SHA or "unknown"

    @property
    def git_sha_short(self) -> str:
        return self.git_sha[:12] if self.git_sha != "unknown" else "unknown"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_postgres_scheme(cls, v: str) -> str:
        """Cloud providers hand out `postgres://…`; SQLAlchemy 2.0 needs
        `postgresql://…` (or a driver-qualified scheme)."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        return v

    @property
    def email_verification_active(self) -> bool:
        """True only when Gmail SMTP credentials are present. When False, the
        registration flow skips the email and marks new users verified so local
        dev / CI keeps working without SMTP secrets."""
        return bool(self.SMTP_USER and self.SMTP_PASS)

    @property
    def frontend_base_url(self) -> str:
        """FRONTEND_URL without a trailing slash."""
        return self.FRONTEND_URL.rstrip("/") or "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS parsed into the list form CORSMiddleware expects."""
        raw = self.CORS_ORIGINS.strip()
        if raw in ("", "*"):
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def websocket_allowed_origins(self) -> list[str]:
        """Origins allowed for /live. '*' is never treated as allow-all."""
        extra = [
            origin.strip().rstrip("/")
            for origin in self.cors_origins_list
            if origin.strip() and origin.strip() != "*"
        ]
        return sorted(set(extra) | {item.rstrip("/") for item in LOCAL_DEV_ORIGINS})


settings = Settings()
