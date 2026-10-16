import io

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError

from ideology_app.db import alembic_config, downgrade, is_initialised, make_engine, run_migrations
from ideology_app.models import Base


def _tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _version(url: str) -> str | None:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def test_upgrade_on_empty_database_creates_tables_at_head(db_url: str) -> None:
    assert _tables(db_url) == set()

    run_migrations(db_url)

    assert _tables(db_url) == {"alembic_version", "elections", "parties"}
    assert _version(db_url) == "0001"


def test_second_upgrade_is_a_noop(db_url: str) -> None:
    run_migrations(db_url)
    run_migrations(db_url)

    assert _tables(db_url) == {"alembic_version", "elections", "parties"}
    assert _version(db_url) == "0001"


def test_downgrade_to_base_removes_domain_tables(db_url: str) -> None:
    run_migrations(db_url)

    downgrade(db_url, "base")

    assert _tables(db_url) == {"alembic_version"}
    assert _version(db_url) is None


def test_is_initialised(db_url: str) -> None:
    engine = make_engine(db_url)
    try:
        assert not is_initialised(engine)
        run_migrations(db_url)
        assert is_initialised(engine)
    finally:
        engine.dispose()


def test_migrations_match_models(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO elections (country, type, date, name, status) "
        "VALUES ('ES', 'general', '2023-07-23', 'x', 'bogus')",
        "INSERT INTO elections (country, type, date, name, status) "
        "VALUES ('ES', 'regional', '2023-07-23', 'x', 'draft')",
        "INSERT INTO parties (election_id, name, short_name) VALUES (999, 'x', 'X')",
    ],
    ids=["bad-status", "bad-type", "unknown-election"],
)
def test_database_constraints_reject_bad_rows(migrated_engine: Engine, statement: str) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


def test_party_rows_cascade_on_election_delete(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO elections (id, country, type, date, name, status) "
                "VALUES (1, 'ES', 'general', '2023-07-23', 'x', 'draft')"
            )
        )
        conn.execute(sa.text("INSERT INTO parties (election_id, name, short_name) VALUES (1, 'a', 'A')"))
        conn.execute(sa.text("DELETE FROM elections"))
        assert conn.execute(sa.text("SELECT count(*) FROM parties")).scalar_one() == 0


def test_offline_postgresql_render_has_each_check_once() -> None:
    buffer = io.StringIO()
    cfg = alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=buffer)

    command.upgrade(cfg, "head", sql=True)

    sql = buffer.getvalue()
    assert "CREATE TABLE elections" in sql
    assert "CREATE TABLE parties" in sql
    assert sql.count("ck_elections_election_status") == 1
    assert sql.count("ck_elections_election_type") == 1
    assert sql.count("CHECK") == 2
