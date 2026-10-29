"""feedback-api Scenarios 7 and 9: ``ideology feedback list [--since DATE]``;
feedback-admin Scenarios 9 and 10: the reviewed suffix and ``ideology feedback upgrade``.

``list`` is read-only: it never creates or writes a file. Temporary files only.
"""

import datetime as dt
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from ideology_app.cli import main
from ideology_app.db import make_engine
from ideology_app.feedback.store import add_message, mark_reviewed, upgrade_schema
from feedback_factory import make_legacy_store

OWN = "FEEDBACK_DATABASE_URL must point at its own database, not at"


def run(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(main, list(args), env=env)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A feedback store with 3 messages: 2026-10-01, 2026-10-05 (multi-line) and 2026-10-05."""
    path = tmp_path / "fb.db"
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade_schema(engine)
        add_message(engine, "Muy útil", "landing", dt.datetime(2026, 10, 1, 8, 0, 1, tzinfo=dt.UTC))
        add_message(
            engine,
            "Dos líneas:\nla segunda",
            "results",
            dt.datetime(2026, 10, 5, 0, 0, 0, tzinfo=dt.UTC),
        )
        add_message(engine, "Último", "landing", dt.datetime(2026, 10, 5, 23, 59, 59, tzinfo=dt.UTC))
    finally:
        engine.dispose()
    return path


ALL = (
    "#1  2026-10-01T08:00:01Z  landing\n"
    "  Muy útil\n"
    "\n"
    "#2  2026-10-05T00:00:00Z  results\n"
    "  Dos líneas:\n"
    "  la segunda\n"
    "\n"
    "#3  2026-10-05T23:59:59Z  landing\n"
    "  Último\n"
    "\n"
    "3 message(s)\n"
)


def test_list_prints_every_message(store: Path) -> None:
    result = run("feedback", "--feedback-database-url", f"sqlite:///{store}", "list")
    assert result.exit_code == 0, result.output
    assert result.output == ALL


def test_list_reads_the_env_variable(store: Path) -> None:
    result = run("feedback", "list", env={"FEEDBACK_DATABASE_URL": f"  sqlite:///{store}  "})
    assert result.exit_code == 0, result.output
    assert result.output == ALL


def test_since_filters_from_midnight_utc(store: Path) -> None:
    result = run(
        "feedback", "--feedback-database-url", f"sqlite:///{store}", "list", "--since", "2026-10-05"
    )
    assert result.exit_code == 0, result.output
    assert result.output == ALL.split("\n\n", 1)[1].replace("3 message(s)", "2 message(s)")
    later = run(
        "feedback", "--feedback-database-url", f"sqlite:///{store}", "list", "--since", "2026-10-06"
    )
    assert later.exit_code == 0
    assert later.output == "No feedback messages.\n"


def test_since_needs_iso_date(store: Path) -> None:
    result = run(
        "feedback", "--feedback-database-url", f"sqlite:///{store}", "list", "--since", "05/10/2026"
    )
    assert result.exit_code == 2


def test_empty_store(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path}/empty.db")
    upgrade_schema(engine)
    engine.dispose()
    result = run("feedback", "--feedback-database-url", f"sqlite:///{tmp_path}/empty.db", "list")
    assert result.exit_code == 0
    assert result.output == "No feedback messages.\n"


def test_default_store_missing_is_an_error_and_creates_nothing(tmp_path: Path) -> None:
    result = run("feedback", "list")
    assert result.exit_code == 1
    assert result.output == (
        "Error: no feedback store at feedback.db; the server creates it on startup\n"
    )
    assert list(tmp_path.iterdir()) == []


def test_file_without_the_table_is_not_a_feedback_store(tmp_path: Path) -> None:
    other = tmp_path / "other.db"
    with closing(sqlite3.connect(other)) as connection:
        connection.execute("CREATE TABLE t (x)")
    text = tmp_path / "notes.db"
    text.write_text("not sqlite")
    for path in (other, text):
        before = path.read_bytes()
        result = run("feedback", "--feedback-database-url", f"sqlite:///{path}", "list")
        assert result.exit_code == 1
        assert result.output == f"Error: {path} is not a feedback store\n"
        assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.db", "other.db"]


def test_list_never_writes_the_store(store: Path) -> None:
    before = store.read_bytes()
    mtime = store.stat().st_mtime_ns
    assert run("feedback", "--feedback-database-url", f"sqlite:///{store}", "list").exit_code == 0
    assert store.read_bytes() == before
    assert store.stat().st_mtime_ns == mtime
    assert sorted(p.name for p in store.parent.iterdir()) == ["fb.db"]


def test_refuses_shared_database_and_its_aliases(tmp_path: Path) -> None:
    shared = tmp_path / "data" / "ideology.db"
    shared.parent.mkdir()
    with closing(sqlite3.connect(shared)) as connection:
        connection.execute("CREATE TABLE t (x)")
    before = shared.read_bytes()
    link = tmp_path / "link.db"
    link.symlink_to(shared)
    main_db = tmp_path / "main.db"
    cases = [
        (["feedback", "--feedback-database-url", "sqlite:///data/ideology.db", "list"], "data/ideology.db"),
        (["feedback", "--feedback-database-url", f"sqlite:///{link}", "list"], "data/ideology.db"),
        (
            ["--database-url", f"sqlite:///{main_db}", "feedback", "--feedback-database-url",
             "sqlite:///main.db", "list"],
            "the DATABASE_URL database",
        ),
    ]
    for args, target in cases:
        result = run(*args)
        assert result.exit_code == 1, result.output
        assert result.output == f"Error: {OWN} {target}; use e.g. sqlite:///feedback.db\n"
    memory = run("feedback", "list", env={"FEEDBACK_DATABASE_URL": "sqlite://"})
    assert memory.exit_code == 1
    assert memory.output == (
        "Error: FEEDBACK_DATABASE_URL must not be an in-memory database; "
        "use e.g. sqlite:///feedback.db\n"
    )
    env_shared = run("feedback", "list", env={"FEEDBACK_DATABASE_URL": "sqlite:///data/ideology.db"})
    assert env_shared.exit_code == 1
    assert shared.read_bytes() == before
    assert not main_db.exists()
    assert not (tmp_path / "feedback.db").exists()


def test_help_works_without_a_store() -> None:
    result = run("feedback", "list", "--help", env={"FEEDBACK_DATABASE_URL": "sqlite://"})
    assert result.exit_code == 0
    assert "--since" in result.output


# --- feedback-admin: reviewed suffix, legacy stores and upgrade ---------------


def test_list_shows_the_reviewed_time_only_on_reviewed_messages(store: Path) -> None:
    engine = make_engine(f"sqlite:///{store}")
    try:
        mark_reviewed(engine, 2, dt.datetime(2026, 10, 29, 14, 5, 7, tzinfo=dt.UTC))
    finally:
        engine.dispose()
    result = run("feedback", "--feedback-database-url", f"sqlite:///{store}", "list")
    assert result.exit_code == 0, result.output
    assert result.output == ALL.replace(
        "#2  2026-10-05T00:00:00Z  results\n",
        "#2  2026-10-05T00:00:00Z  results  reviewed 2026-10-29T14:05:07Z\n",
    )


LEGACY = [
    ("Uno", "landing", dt.datetime(2026, 10, 1, 8, 0, 1, tzinfo=dt.UTC)),
    ("Dos", "results", dt.datetime(2026, 10, 2, 8, 0, 1, tzinfo=dt.UTC)),
    ("Tres", "landing", dt.datetime(2026, 10, 3, 8, 0, 1, tzinfo=dt.UTC)),
]


def test_list_on_a_legacy_store_asks_for_an_upgrade_and_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_legacy_store(path, LEGACY)
    before = path.read_bytes()
    result = run("feedback", "--feedback-database-url", f"sqlite:///{path}", "list")
    assert result.exit_code == 1
    assert result.output == (
        f'Error: {path} needs an upgrade; run "ideology feedback upgrade" or start the server\n'
    )
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["legacy.db"]


def test_upgrade_keeps_every_message_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    make_legacy_store(path, LEGACY)
    args = ("feedback", "--feedback-database-url", f"sqlite:///{path}")
    for _ in range(2):
        result = run(*args, "upgrade")
        assert result.exit_code == 0, result.output
        assert result.output == f"Feedback store {path} is at revision f0002 (head).\n"
    listed = run(*args, "list")
    assert listed.exit_code == 0, listed.output
    assert listed.output.endswith("3 message(s)\n")
    assert "reviewed" not in listed.output
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT message, reviewed_at FROM feedback_messages ORDER BY id"
        ).fetchall() == [("Uno", None), ("Dos", None), ("Tres", None)]


def test_upgrade_refuses_a_missing_store_and_the_shared_database(tmp_path: Path) -> None:
    missing = run("feedback", "upgrade")
    assert missing.exit_code == 1
    assert missing.output == (
        "Error: no feedback store at feedback.db; the server creates it on startup\n"
    )
    assert list(tmp_path.iterdir()) == []
    shared = run("feedback", "--feedback-database-url", "sqlite:///data/ideology.db", "upgrade")
    assert shared.exit_code == 1
    assert shared.output == f"Error: {OWN} data/ideology.db; use e.g. sqlite:///feedback.db\n"
