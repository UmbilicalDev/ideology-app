"""feedback-api: the separate feedback store (Decisions 4, 5 and 7; Scenarios 7 and 8)."""

import datetime as dt
import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect

from ideology_app import config, models
from ideology_app.db import head_revision, make_engine
from ideology_app.feedback.store import (
    FEEDBACK_METADATA,
    FeedbackStoreError,
    add_message,
    check_separate,
    upgrade_schema,
    has_schema,
    list_messages,
)

OWN = "FEEDBACK_DATABASE_URL must point at its own database, not at"
SHARED_MSG = f"{OWN} data/ideology.db; use e.g. sqlite:///feedback.db"
SAME_MSG = f"{OWN} the DATABASE_URL database; use e.g. sqlite:///feedback.db"
MEMORY_MSG = "FEEDBACK_DATABASE_URL must not be an in-memory database; use e.g. sqlite:///feedback.db"


@pytest.fixture
def shared_file(tmp_path: Path) -> Path:
    """A stand-in ``data/ideology.db`` under tmp_path (the conftest chdirs there)."""
    path = tmp_path / "data" / "ideology.db"
    path.parent.mkdir()
    sqlite3.connect(path).close()
    return path


# --- check_separate --------------------------------------------------------


def test_feedback_error_is_a_config_error() -> None:
    assert issubclass(FeedbackStoreError, config.ConfigError)


def test_a_file_of_its_own_is_accepted(tmp_path: Path) -> None:
    check_separate("sqlite:///feedback.db", "sqlite:///data/ideology.db")
    check_separate(f"sqlite:///{tmp_path}/fb.db", f"sqlite:///{tmp_path}/main.db")
    check_separate("sqlite:///feedback.db", "sqlite://")
    check_separate("postgresql://u:p@h/feedback", "postgresql://u:p@h/main")
    check_separate("postgresql://u:p@h/feedback", "sqlite:///ideology.db")


@pytest.mark.parametrize(
    "url", ["sqlite:///data/ideology.db", "sqlite:///./data/../data/ideology.db"]
)
def test_shared_database_is_refused(url: str) -> None:
    with pytest.raises(FeedbackStoreError) as info:
        check_separate(url, "sqlite:///other.db")
    assert str(info.value) == SHARED_MSG


def test_symlink_to_shared_database_is_refused(tmp_path: Path, shared_file: Path) -> None:
    link = tmp_path / "link.db"
    link.symlink_to(shared_file)
    with pytest.raises(FeedbackStoreError, match="not at data/ideology.db"):
        check_separate(f"sqlite:///{link}", "sqlite:///other.db")


def test_hard_link_to_shared_database_is_refused(tmp_path: Path, shared_file: Path) -> None:
    link = tmp_path / "hard.db"
    os.link(shared_file, link)
    with pytest.raises(FeedbackStoreError, match="not at data/ideology.db"):
        check_separate(f"sqlite:///{link}", "sqlite:///other.db")


def test_same_file_as_database_url_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FeedbackStoreError) as info:
        check_separate("sqlite:///main.db", f"sqlite:///{tmp_path}/main.db")
    assert str(info.value) == SAME_MSG


def test_symlink_and_hard_link_to_database_url_are_refused(tmp_path: Path) -> None:
    main_db = tmp_path / "main.db"
    sqlite3.connect(main_db).close()
    soft = tmp_path / "soft.db"
    soft.symlink_to(main_db)
    hard = tmp_path / "hard.db"
    os.link(main_db, hard)
    for link in (soft, hard):
        with pytest.raises(FeedbackStoreError, match="the DATABASE_URL database"):
            check_separate(f"sqlite:///{link}", f"sqlite:///{main_db}")


def test_same_non_sqlite_url_is_refused_without_leaking_the_password() -> None:
    url = "postgresql://user:s3cret@db.example/ideology"
    with pytest.raises(FeedbackStoreError) as info:
        check_separate(url, url)
    assert str(info.value) == SAME_MSG
    assert "s3cret" not in str(info.value)


@pytest.mark.parametrize("url", ["sqlite://", "sqlite:///:memory:"])
def test_in_memory_is_refused(url: str) -> None:
    with pytest.raises(FeedbackStoreError) as info:
        check_separate(url, "sqlite:///ideology.db")
    assert str(info.value) == MEMORY_MSG


def test_unparsable_url_is_refused() -> None:
    with pytest.raises(FeedbackStoreError, match="not a valid database URL"):
        check_separate("not a url", "sqlite:///ideology.db")


# --- store -----------------------------------------------------------------


def test_add_and_list_messages_in_utc_whole_seconds(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/fb.db")
    try:
        upgrade_schema(engine)
        upgrade_schema(engine)  # a second start is a no-op
        madrid = dt.timezone(dt.timedelta(hours=2))
        add_message(engine, "b", "results", dt.datetime(2026, 10, 5, 12, 0, 0, 999, tzinfo=madrid))
        add_message(engine, "a", "landing", dt.datetime(2026, 10, 1, 9, 30, 5, 500_000, tzinfo=dt.UTC))
        messages = list_messages(engine)
        assert [(m.message, m.origin) for m in messages] == [("a", "landing"), ("b", "results")]
        assert messages[0].created_at == dt.datetime(2026, 10, 1, 9, 30, 5, tzinfo=dt.UTC)
        assert messages[1].created_at == dt.datetime(2026, 10, 5, 10, 0, 0, tzinfo=dt.UTC)
        since = list_messages(engine, dt.datetime(2026, 10, 5, tzinfo=dt.UTC))
        assert [m.message for m in since] == ["b"]
        with pytest.raises(ValueError):
            add_message(engine, "x", "admin", dt.datetime.now(dt.UTC))
        with pytest.raises(ValueError):
            add_message(engine, "x", "landing", dt.datetime(2026, 1, 1))
    finally:
        engine.dispose()


def test_table_holds_only_id_message_origin_created_and_reviewed_at(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/fb.db")
    try:
        assert not has_schema(engine)
        upgrade_schema(engine)
        assert has_schema(engine)
        inspector = inspect(engine)
        # The data table plus the feedback store's own Alembic version table (feedback-admin).
        assert inspector.get_table_names() == ["feedback_alembic_version", "feedback_messages"]
        columns = [c["name"] for c in inspector.get_columns("feedback_messages")]
        assert columns == ["id", "message", "origin", "created_at", "reviewed_at"]
        # The origin CHECK constraint is enforced by the database too.
        with engine.begin() as connection, pytest.raises(Exception):
            connection.exec_driver_sql(
                "INSERT INTO feedback_messages (message, origin, created_at) "
                "VALUES ('x', 'admin', '2026-01-01 00:00:00')"
            )
    finally:
        engine.dispose()


# --- Scenario 8: shared DB untouched ---------------------------------------


def test_shared_database_metadata_and_migrations_are_untouched() -> None:
    assert "feedback_messages" not in models.Base.metadata.tables
    assert list(FEEDBACK_METADATA.tables) == ["feedback_messages"]
    assert head_revision() == "0013"
    versions = Path(models.__file__).parent / "migrations" / "versions"
    assert not list(versions.glob("0014*"))
    assert not any("feedback" in p.name for p in versions.glob("*.py"))


# --- config ----------------------------------------------------------------


def test_feedback_database_url_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.feedback_database_url() == "sqlite:///feedback.db"
    monkeypatch.setenv("FEEDBACK_DATABASE_URL", "   ")
    assert config.feedback_database_url() == "sqlite:///feedback.db"
    monkeypatch.setenv("FEEDBACK_DATABASE_URL", "  postgresql://u@h/fb  ")
    assert config.feedback_database_url() == "postgresql://u@h/fb"
