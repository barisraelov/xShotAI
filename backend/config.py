"""
Application configuration.

Reads settings from environment variables (or a .env file) via pydantic-settings.
The only setting today is DATABASE_URL, which points at the local docker-compose
PostgreSQL instance by default.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = (
        "postgresql://xshot_user:xshot_password@localhost:5432/xshot_db"
    )


settings = Settings()
