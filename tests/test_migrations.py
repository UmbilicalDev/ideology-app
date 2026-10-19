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


TABLES_AT_0003 = {
    "alembic_version",
    "elections",
    "parties",
    "source_documents",
    "source_document_pages",
}
PIPELINE_TABLES = {"pipeline_runs", "dataset_versions", "statements"}
ALL_TABLES = TABLES_AT_0003 | PIPELINE_TABLES


def test_upgrade_on_empty_database_creates_tables_at_head(db_url: str) -> None:
    assert _tables(db_url) == set()

    run_migrations(db_url)

    assert _tables(db_url) == ALL_TABLES
    assert _version(db_url) == "0004"


def test_second_upgrade_is_a_noop(db_url: str) -> None:
    run_migrations(db_url)
    run_migrations(db_url)

    assert _tables(db_url) == ALL_TABLES
    assert _version(db_url) == "0004"


def test_downgrade_to_0001_drops_source_document_tables(db_url: str) -> None:
    run_migrations(db_url)

    downgrade(db_url, "0001")

    assert _tables(db_url) == {"alembic_version", "elections", "parties"}
    assert _version(db_url) == "0001"


def _source_document_columns(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return {c["name"] for c in sa.inspect(engine).get_columns("source_documents")}
    finally:
        engine.dispose()


def test_downgrade_to_0002_drops_source_url(db_url: str) -> None:
    run_migrations(db_url)
    assert "source_url" in _source_document_columns(db_url)

    downgrade(db_url, "0002")

    assert "source_url" not in _source_document_columns(db_url)
    assert _tables(db_url) == TABLES_AT_0003
    assert _version(db_url) == "0002"
    engine = make_engine(db_url)
    try:
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_check_constraints("source_documents")} == {
            "ck_source_documents_source_document_origin",
            "ck_source_documents_source_document_status",
        }
        assert [i["name"] for i in inspector.get_indexes("source_documents")] == [
            "ix_source_documents_party_id"
        ]
    finally:
        engine.dispose()


def test_upgrade_0003_keeps_existing_constraints_and_index(migrated_engine: Engine) -> None:
    inspector = sa.inspect(migrated_engine)
    checks = {c["name"] for c in inspector.get_check_constraints("source_documents")}
    assert checks == {
        "ck_source_documents_source_document_origin",
        "ck_source_documents_source_document_status",
        "ck_source_documents_source_url_matches_origin",
    }
    assert [i["name"] for i in inspector.get_indexes("source_documents")] == [
        "ix_source_documents_party_id"
    ]
    assert [u["name"] for u in inspector.get_unique_constraints("source_documents")] == [
        "uq_source_documents_party_id_content_hash"
    ]
    assert [f["name"] for f in inspector.get_foreign_keys("source_documents")] == [
        "fk_source_documents_party_id_parties"
    ]


def test_downgrade_to_base_removes_domain_tables(db_url: str) -> None:
    run_migrations(db_url)

    downgrade(db_url, "base")

    assert _tables(db_url) == {"alembic_version"}
    assert _version(db_url) is None


def test_is_initialised(db_url: str) -> None:
    engine = make_engine(db_url)
    try:
        assert not is_initialised(engine)
        run_migrations(db_url, "0001")
        assert not is_initialised(engine)
        run_migrations(db_url, "0002")
        assert not is_initialised(engine)
        run_migrations(db_url, "0003")
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


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO source_documents (party_id, origin, status, created_at) "
        "VALUES (1, 'upload', 'bogus', '2026-10-19 00:00:00')",
        "INSERT INTO source_documents (party_id, origin, status, created_at) "
        "VALUES (1, 'email', 'parsed', '2026-10-19 00:00:00')",
        "INSERT INTO source_documents (party_id, origin, status, created_at) "
        "VALUES (1, 'url', 'failed', '2026-10-19 00:00:00')",
        "INSERT INTO source_documents (party_id, origin, status, source_url, created_at) "
        "VALUES (1, 'upload', 'parsed', 'https://example.org/a.pdf', '2026-10-19 00:00:00')",
        "INSERT INTO source_documents (party_id, origin, status, created_at) "
        "VALUES (999, 'upload', 'parsed', '2026-10-19 00:00:00')",
        "INSERT INTO source_document_pages (source_document_id, page_number, text) "
        "VALUES (1, 0, 'x')",
        "INSERT INTO source_document_pages (source_document_id, page_number, text) "
        "VALUES (999, 1, 'x')",
        "INSERT INTO source_document_pages (source_document_id, page_number, text) "
        "VALUES (1, 1, 'again')",
    ],
    ids=[
        "bad-source-status",
        "bad-source-origin",
        "url-without-source-url",
        "upload-with-source-url",
        "unknown-party",
        "page-number-zero",
        "unknown-source-document",
        "duplicate-page-number",
    ],
)
def test_source_document_constraints_reject_bad_rows(
    migrated_engine: Engine, statement: str
) -> None:
    _seed_party_and_document(migrated_engine)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


def _seed_party_and_document(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO elections (id, country, type, date, name, status) "
                "VALUES (1, 'ES', 'general', '2023-07-23', 'x', 'draft')"
            )
        )
        conn.execute(
            sa.text("INSERT INTO parties (id, election_id, name, short_name) VALUES (1, 1, 'a', 'A')")
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_documents (id, party_id, origin, status, content_hash, created_at) "
                "VALUES (1, 1, 'upload', 'parsed', 'h', '2026-10-19 00:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO source_document_pages (source_document_id, page_number, text) "
                "VALUES (1, 1, 'x')"
            )
        )


def test_source_documents_cascade_on_party_delete(migrated_engine: Engine) -> None:
    _seed_party_and_document(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM parties"))
        assert conn.execute(sa.text("SELECT count(*) FROM source_documents")).scalar_one() == 0
        assert conn.execute(sa.text("SELECT count(*) FROM source_document_pages")).scalar_one() == 0


def test_offline_postgresql_render_has_each_check_once() -> None:
    buffer = io.StringIO()
    cfg = alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=buffer)

    command.upgrade(cfg, "head", sql=True)

    sql = buffer.getvalue()
    assert "CREATE TABLE elections" in sql
    assert "CREATE TABLE parties" in sql
    assert sql.count("ck_elections_election_status") == 1
    assert sql.count("ck_elections_election_type") == 1
    assert "CREATE TABLE source_documents" in sql
    assert "CREATE TABLE source_document_pages" in sql
    assert sql.count("ck_source_documents_source_document_origin") == 1
    assert sql.count("ck_source_documents_source_document_status") == 1
    assert sql.count("ck_source_document_pages_page_number_positive") == 1
    assert sql.count("ck_source_documents_source_url_matches_origin") == 1
    assert "ADD COLUMN source_url VARCHAR(2048)" in sql
    assert "CREATE TABLE pipeline_runs" in sql
    assert "CREATE TABLE dataset_versions" in sql
    assert "CREATE TABLE statements" in sql
    assert sql.count("ck_pipeline_runs_pipeline_run_status") == 1
    assert sql.count("ck_pipeline_runs_generation_mode") == 1
    assert sql.count("ck_dataset_versions_dataset_version_status") == 1
    assert sql.count("ck_statements_position_positive") == 1
    assert sql.count("CHECK") == 10


def test_downgrade_to_0003_drops_exactly_the_pipeline_tables(db_url: str) -> None:
    run_migrations(db_url)
    assert PIPELINE_TABLES <= _tables(db_url)

    downgrade(db_url, "0003")

    assert _tables(db_url) == TABLES_AT_0003
    assert _version(db_url) == "0003"
    assert "source_url" in _source_document_columns(db_url)


def test_upgrade_0004_creates_pipeline_constraints(migrated_engine: Engine) -> None:
    inspector = sa.inspect(migrated_engine)
    assert {c["name"] for c in inspector.get_check_constraints("pipeline_runs")} == {
        "ck_pipeline_runs_pipeline_run_status",
        "ck_pipeline_runs_generation_mode",
    }
    assert {c["name"] for c in inspector.get_check_constraints("dataset_versions")} == {
        "ck_dataset_versions_dataset_version_status"
    }
    assert {c["name"] for c in inspector.get_check_constraints("statements")} == {
        "ck_statements_position_positive"
    }
    assert [u["name"] for u in inspector.get_unique_constraints("dataset_versions")] == [
        "uq_dataset_versions_pipeline_run_id"
    ]
    assert [u["name"] for u in inspector.get_unique_constraints("statements")] == [
        "uq_statements_dataset_version_id_position"
    ]
    assert [i["name"] for i in inspector.get_indexes("pipeline_runs")] == [
        "ix_pipeline_runs_election_id"
    ]
    assert [i["name"] for i in inspector.get_indexes("dataset_versions")] == [
        "ix_dataset_versions_election_id"
    ]


_RUN_COLUMNS = (
    "election_id, status, llm_provider, llm_model, generation_mode, prompt_versions, "
    "llm_calls, input_tokens, output_tokens, created_at"
)


def _seed_run_and_version(engine: Engine) -> None:
    _seed_party_and_document(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f"INSERT INTO pipeline_runs (id, {_RUN_COLUMNS}) VALUES "
                "(1, 1, 'validating', 'fake', 'fake-model', 'precomputed', '{}', 0, 0, 0, "
                "'2026-10-19 00:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO dataset_versions (id, election_id, pipeline_run_id, status, created_at) "
                "VALUES (1, 1, 1, 'candidate', '2026-10-19 00:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO statements (dataset_version_id, position, text, topic) "
                "VALUES (1, 1, 'x', 'economy')"
            )
        )


@pytest.mark.parametrize(
    "statement",
    [
        f"INSERT INTO pipeline_runs ({_RUN_COLUMNS}) VALUES "
        "(1, 'bogus', 'fake', 'm', 'precomputed', '{}', 0, 0, 0, '2026-10-19 00:00:00')",
        f"INSERT INTO pipeline_runs ({_RUN_COLUMNS}) VALUES "
        "(1, 'queued', 'fake', 'm', 'sometimes', '{}', 0, 0, 0, '2026-10-19 00:00:00')",
        f"INSERT INTO pipeline_runs ({_RUN_COLUMNS}) VALUES "
        "(999, 'queued', 'fake', 'm', 'precomputed', '{}', 0, 0, 0, '2026-10-19 00:00:00')",
        "INSERT INTO dataset_versions (election_id, pipeline_run_id, status, created_at) "
        "VALUES (1, 1, 'bogus', '2026-10-19 00:00:00')",
        "INSERT INTO dataset_versions (election_id, pipeline_run_id, status, created_at) "
        "VALUES (1, 1, 'candidate', '2026-10-19 00:00:00')",
        "INSERT INTO dataset_versions (election_id, pipeline_run_id, status, created_at) "
        "VALUES (1, 999, 'candidate', '2026-10-19 00:00:00')",
        "INSERT INTO statements (dataset_version_id, position, text, topic) "
        "VALUES (1, 1, 'again', 'economy')",
        "INSERT INTO statements (dataset_version_id, position, text, topic) "
        "VALUES (1, 0, 'zero', 'economy')",
        "INSERT INTO statements (dataset_version_id, position, text, topic) "
        "VALUES (999, 2, 'x', 'economy')",
    ],
    ids=[
        "bad-run-status",
        "bad-generation-mode",
        "run-unknown-election",
        "bad-dataset-version-status",
        "duplicate-pipeline-run-id",
        "unknown-pipeline-run",
        "duplicate-position",
        "position-zero",
        "unknown-dataset-version",
    ],
)
def test_pipeline_constraints_reject_bad_rows(migrated_engine: Engine, statement: str) -> None:
    _seed_run_and_version(migrated_engine)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


def test_deleting_an_election_cascades_to_pipeline_rows(migrated_engine: Engine) -> None:
    _seed_run_and_version(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
        for table in ("pipeline_runs", "dataset_versions", "statements"):
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
