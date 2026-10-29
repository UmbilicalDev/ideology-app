"""feedback-admin Decision 10 and Scenario 9: the feedback store's own Alembic environment.

A store made by feedback-api (no version table) is stamped at f0001 and
upgraded to f0002, keeping every message. The shared database is untouched.
Temporary SQLite files only.
"""

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from ideology_app import models
from ideology_app.db import head_revision as shared_head_revision
from ideology_app.db import make_engine
from ideology_app.feedback import store
from ideology_app.feedback.store import (
    FEEDBACK_METADATA,
    VERSION_TABLE,
    current_revision,
    head_revision,
    is_at_head,
    list_messages,
    upgrade_schema,
)
from ideology_app.main import create_app
from feedback_factory import make_legacy_store

LEGACY = [
    ("Primero", "landing", dt.datetime(2026, 10, 1, 8, 0, 1, tzinfo=dt.UTC)),
    ("Dos\nlíneas", "results", dt.datetime(2026, 10, 2, 9, 0, 0, tzinfo=dt.UTC)),
    ("Último 👍", "landing", dt.datetime(2026, 10, 3, 23, 59, 59, tzinfo=dt.UTC)),
]


def _diff(path: Path) -> list[object]:
    engine = make_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE})
            return list(compare_metadata(context, FEEDBACK_METADATA))
    finally:
        engine.dispose()


def _rows(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT id, message, origin, created_at, reviewed_at FROM feedback_messages ORDER BY id"
        ).fetchall()


def test_head_is_f0002_and_revisions_are_in_their_own_environment() -> None:
    assert head_revision() == "f0002"
    assert store.SCRIPT_LOCATION == "ideology_app.feedback:migrations"
    versions = Path(store.__file__).parent / "migrations" / "versions"
    assert sorted(p.name for p in versions.glob("*.py")) == [
        "f0001_feedback_messages.py",
        "f0002_reviewed_at.py",
    ]
    # No __init__.py, like the shared environment.
    assert not (Path(store.__file__).parent / "migrations" / "__init__.py").exists()


def test_fresh_store_matches_the_metadata(tmp_path: Path) -> None:
    path = tmp_path / "fb.db"
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade_schema(engine)
        assert current_revision(engine) == "f0002"
        assert is_at_head(engine)
    finally:
        engine.dispose()
    assert _diff(path) == []
    # One CHECK, named feedback_origin, exactly as create_all made it.
    with closing(sqlite3.connect(path)) as connection:
        (sql,) = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'feedback_messages'"
        ).fetchone()
    assert sql.count("CHECK") == 1
    assert "CONSTRAINT feedback_origin CHECK" in sql


def test_legacy_store_is_stamped_and_upgraded_keeping_every_message(tmp_path: Path) -> None:
    path = tmp_path / "fb.db"
    make_legacy_store(path, LEGACY)
    before = _rows_without_reviewed(path)
    engine = make_engine(f"sqlite:///{path}")
    try:
        assert current_revision(engine) is None
        assert not is_at_head(engine)
        upgrade_schema(engine)
        assert current_revision(engine) == "f0002"
        messages = list_messages(engine)
    finally:
        engine.dispose()
    assert [(m.message, m.origin, m.created_at) for m in messages] == LEGACY
    assert all(m.reviewed_at is None for m in messages)
    assert [row[:4] for row in _rows(path)] == before
    assert _diff(path) == []


def _rows_without_reviewed(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT id, message, origin, created_at FROM feedback_messages ORDER BY id"
        ).fetchall()


def test_second_upgrade_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "fb.db"
    make_legacy_store(path, LEGACY)
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade_schema(engine)
        first = _rows(path)
        schema = _schema(path)
        upgrade_schema(engine)
        assert current_revision(engine) == "f0002"
    finally:
        engine.dispose()
    assert _rows(path) == first
    assert _schema(path) == schema


def _schema(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()


def test_app_startup_upgrades_a_legacy_store(tmp_path: Path, db_url: str) -> None:
    path = tmp_path / "fb.db"
    make_legacy_store(path, LEGACY)
    with TestClient(create_app(db_url, feedback_database_url=f"sqlite:///{path}")):
        pass
    rows = _rows(path)
    assert [row[1] for row in rows] == [m[0] for m in LEGACY]
    assert all(row[4] is None for row in rows)
    engine = make_engine(f"sqlite:///{path}")
    try:
        assert current_revision(engine) == "f0002"
    finally:
        engine.dispose()
    assert inspect_tables(path) == ["feedback_alembic_version", "feedback_messages"]


def inspect_tables(path: Path) -> list[str]:
    engine = make_engine(f"sqlite:///{path}")
    try:
        return sorted(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_shared_database_head_and_metadata_are_untouched() -> None:
    assert shared_head_revision() == "0013"
    assert "feedback_messages" not in models.Base.metadata.tables
    assert "reviewed_at" in FEEDBACK_METADATA.tables["feedback_messages"].c
    shared_versions = Path(models.__file__).parent / "migrations" / "versions"
    assert not list(shared_versions.glob("0014*"))


def test_revisions_never_reach_the_shared_version_table(tmp_path: Path) -> None:
    path = tmp_path / "fb.db"
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade_schema(engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "alembic_version" not in tables
        assert connection.execute(f"SELECT version_num FROM {VERSION_TABLE}").fetchall() == [
            ("f0002",)
        ]
