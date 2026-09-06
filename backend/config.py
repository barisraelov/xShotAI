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
                                  any origin (default; convenient for the first
                                  cloud deploy, tighten later).
  RAILWAY_GIT_* / BUILD_SHA     — deploy fingerprint. Railway injects
                                  RAILWAY_GIT_COMMIT_SHA / _BRANCH / _COMMIT_MESSAGE
                                  into the running container automatically; set
                                  BUILD_SHA yourself on other platforms. Surfaced
                                  at GET /version and in /openapi.json info.version.
"""

import os
import secrets

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Evaluated once per process. Only used when SECRET_KEY is not in the environment.
_DEV_SECRET_FALLBACK = os.getenv("SECRET_KEY") or "dev-only-" + secrets.token_urlsafe(48)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = (
        "postgresql://xshot_user:xshot_password@localhost:5432/xshot_db"
    )

    SECRET_KEY: str = _DEV_SECRET_FALLBACK
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    CORS_ORIGINS: str = "*"

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
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS parsed into the list form CORSMiddleware expects."""
        raw = self.CORS_ORIGINS.strip()
        if raw in ("", "*"):
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


settings = Settings()
