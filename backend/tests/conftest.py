"""Test DB setup — an isolated SQLite file, never the real app.db.

The DATABASE_URL env var must be overridden before app.db (or anything importing it) is
imported anywhere in the process, since app.config.get_settings() is @lru_cache'd — hence this
happens at module import time, before any `from app...` import below.
"""

import os
import uuid
from pathlib import Path

_TEST_DB_PATH = Path(__file__).parent / f"test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"

import pytest  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401 — registers every model on Base.metadata
from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_schema():
    """Full schema reset before every test — simplest possible isolation, and cheap enough at
    this table count/SQLite speed that per-test overhead doesn't matter."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()
