"""
SQLAlchemy engine / session wiring.

    engine        — the connection pool to PostgreSQL
    SessionLocal  — factory for short-lived Session objects
    Base          — declarative base every model inherits from
    get_db()      — FastAPI dependency yielding a request-scoped session

Background workers that run outside the request lifecycle should use
SessionLocal() directly in a try/finally (see main.py).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # transparently recycle stale connections
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
