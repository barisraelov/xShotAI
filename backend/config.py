"""
Application configuration.

Reads settings from environment variables (or a .env file) via pydantic-settings.

  DATABASE_URL                  — PostgreSQL DSN (defaults to the local
                                  docker-compose instance)
  SECRET_KEY                    — HMAC key for signing JWTs. A random key is
                                  generated per process if unset, which is fine
                                  for local dev but logs out every restart;
                                  set it explicitly in any real deployment.
  JWT_ALGORITHM                 — signing algorithm (HS256)
  ACCESS_TOKEN_EXPIRE_MINUTES   — access-token lifetime (default 24h)
"""

import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = (
        "postgresql://xshot_user:xshot_password@localhost:5432/xshot_db"
    )

    SECRET_KEY: str = secrets.token_urlsafe(64)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours


settings = Settings()
