from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app.db import make_engine, run_migrations


@pytest.fixture(autouse=True)
def _no_default_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never let a test fall back to ./ideology.db or a developer's web build."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    monkeypatch.delenv("ELECTIONS_DATA_DIR", raising=False)
    # The feedback store then defaults to ./feedback.db, inside tmp_path.
    monkeypatch.delenv("FEEDBACK_DATABASE_URL", raising=False)
    # No Operator account unless a test passes admin_users= (feedback-admin).
    monkeypatch.delenv("ADMIN_USERS", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path}/test.db"


@pytest.fixture
def migrated_engine(db_url: str) -> Iterator[Engine]:
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as s:
        yield s
