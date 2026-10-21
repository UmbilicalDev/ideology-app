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
TABLES_AT_0004 = TABLES_AT_0003 | PIPELINE_TABLES
POSITION_TABLES = {"party_positions", "pipeline_run_source_documents"}
TABLES_AT_0005 = TABLES_AT_0004 | POSITION_TABLES
VALIDATION_TABLES = {"validation_results", "validation_report_entries"}
TABLES_AT_0009 = TABLES_AT_0005 | VALIDATION_TABLES
ALL_TABLES = TABLES_AT_0009 | {"pipeline_run_calls"}


def test_upgrade_on_empty_database_creates_tables_at_head(db_url: str) -> None:
    assert _tables(db_url) == set()

    run_migrations(db_url)

    assert _tables(db_url) == ALL_TABLES
    assert _version(db_url) == "0010"


def test_second_upgrade_is_a_noop(db_url: str) -> None:
    run_migrations(db_url)
    run_migrations(db_url)

    assert _tables(db_url) == ALL_TABLES
    assert _version(db_url) == "0010"


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
        run_migrations(db_url, "0004")
        assert not is_initialised(engine)
        run_migrations(db_url, "0005")
        assert not is_initialised(engine)
        run_migrations(db_url, "0006")
        assert not is_initialised(engine)
        run_migrations(db_url, "0007")
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
    assert "CREATE TABLE pipeline_run_source_documents" in sql
    assert "CREATE TABLE party_positions" in sql
    assert sql.count("ck_pipeline_run_source_documents_source_document_role") == 1
    assert sql.count("ck_party_positions_value_range") == 1
    assert sql.count("ck_party_positions_evidence_page_positive") == 1
    assert sql.count("ck_party_positions_evidence_matches_value") == 1
    assert "CREATE TABLE validation_results" in sql
    assert "CREATE TABLE validation_report_entries" in sql
    assert (
        "CREATE UNIQUE INDEX uq_dataset_versions_published_election_id "
        "ON dataset_versions (election_id) WHERE status = 'published'"
    ) in sql
    assert "ALTER TABLE pipeline_runs ADD COLUMN validation_settings JSON" in sql
    assert sql.count("CHECK") == 14


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
    # 0007 adds the partial unique index (checked below).
    assert {i["name"] for i in inspector.get_indexes("dataset_versions")} == {
        "ix_dataset_versions_election_id",
        "uq_dataset_versions_published_election_id",
    }


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


# Migration 0005: party_positions and pipeline_run_source_documents.


def test_downgrade_to_0004_drops_exactly_the_position_tables(db_url: str) -> None:
    run_migrations(db_url)
    assert POSITION_TABLES <= _tables(db_url)

    downgrade(db_url, "0004")

    assert _tables(db_url) == TABLES_AT_0004
    assert _version(db_url) == "0004"


def test_upgrade_0005_creates_position_constraints(migrated_engine: Engine) -> None:
    inspector = sa.inspect(migrated_engine)
    assert {c["name"] for c in inspector.get_check_constraints("party_positions")} == {
        "ck_party_positions_value_range",
        "ck_party_positions_evidence_page_positive",
        "ck_party_positions_evidence_matches_value",
    }
    assert {
        c["name"] for c in inspector.get_check_constraints("pipeline_run_source_documents")
    } == {"ck_pipeline_run_source_documents_source_document_role"}
    assert [u["name"] for u in inspector.get_unique_constraints("party_positions")] == [
        "uq_party_positions_statement_id_party_id"
    ]
    assert [i["name"] for i in inspector.get_indexes("party_positions")] == [
        "ix_party_positions_party_id"
    ]
    assert inspector.get_pk_constraint("pipeline_run_source_documents")[
        "constrained_columns"
    ] == ["pipeline_run_id", "source_document_id"]


_POSITION_COLUMNS = (
    "statement_id, party_id, value, evidence_source_document_id, evidence_quote, "
    "evidence_page, evidence_url"
)


def _seed_positions(engine: Engine) -> None:
    _seed_run_and_version(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                f"INSERT INTO party_positions ({_POSITION_COLUMNS}) "
                "VALUES (1, 1, 2, 1, 'cita', 1, NULL)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO pipeline_run_source_documents "
                "(pipeline_run_id, source_document_id, role) VALUES (1, 1, 'main')"
            )
        )
        conn.execute(
            sa.text("INSERT INTO parties (id, election_id, name, short_name) VALUES (2, 1, 'b', 'B')")
        )


def _position(values: str) -> str:
    return f"INSERT INTO party_positions ({_POSITION_COLUMNS}) VALUES ({values})"


@pytest.mark.parametrize(
    "values",
    [
        "1, 2, NULL, NULL, NULL, NULL, NULL",
        "1, 2, -2, 1, 'cita', 1, 'https://example.org/a.pdf'",
        "1, 2, 0, 1, 'cita', 1, NULL",
    ],
    ids=["no-stance", "stance-with-url", "neutral"],
)
def test_party_positions_accept_good_rows(migrated_engine: Engine, values: str) -> None:
    _seed_positions(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text(_position(values)))


@pytest.mark.parametrize(
    "statement",
    [
        _position("1, 2, 3, 1, 'cita', 1, NULL"),
        _position("1, 2, -3, 1, 'cita', 1, NULL"),
        _position("1, 2, 1, 1, NULL, 1, NULL"),
        _position("1, 2, 1, NULL, 'cita', 1, NULL"),
        _position("1, 2, 1, 1, 'cita', NULL, NULL"),
        _position("1, 2, NULL, 1, NULL, NULL, NULL"),
        _position("1, 2, NULL, NULL, 'cita', NULL, NULL"),
        _position("1, 2, NULL, NULL, NULL, 1, NULL"),
        _position("1, 2, NULL, NULL, NULL, NULL, 'https://example.org/a.pdf'"),
        _position("1, 2, 1, 1, 'cita', 0, NULL"),
        _position("1, 1, NULL, NULL, NULL, NULL, NULL"),
        _position("999, 2, NULL, NULL, NULL, NULL, NULL"),
        _position("1, 999, NULL, NULL, NULL, NULL, NULL"),
        _position("1, 2, 1, 999, 'cita', 1, NULL"),
        "INSERT INTO pipeline_run_source_documents (pipeline_run_id, source_document_id, role) "
        "VALUES (1, 1, 'additional')",
        "INSERT INTO pipeline_run_source_documents (pipeline_run_id, source_document_id, role) "
        "VALUES (1, 1, 'bogus')",
        "INSERT INTO pipeline_run_source_documents (pipeline_run_id, source_document_id, role) "
        "VALUES (999, 1, 'main')",
        "INSERT INTO pipeline_run_source_documents (pipeline_run_id, source_document_id, role) "
        "VALUES (1, 999, 'main')",
    ],
    ids=[
        "value-3",
        "value-minus-3",
        "stance-without-quote",
        "stance-without-document",
        "stance-without-page",
        "no-stance-with-document",
        "no-stance-with-quote",
        "no-stance-with-page",
        "no-stance-with-url",
        "page-zero",
        "duplicate-statement-party",
        "unknown-statement",
        "unknown-party",
        "unknown-evidence-document",
        "duplicate-run-document",
        "bad-role",
        "unknown-run",
        "unknown-source-document",
    ],
)
def test_position_constraints_reject_bad_rows(migrated_engine: Engine, statement: str) -> None:
    _seed_positions(migrated_engine)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


def test_deleting_an_election_cascades_to_position_rows(migrated_engine: Engine) -> None:
    _seed_positions(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
        for table in POSITION_TABLES:
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


# Migration 0006: validation_results and validation_report_entries.


def test_downgrade_to_0005_drops_exactly_the_validation_tables(db_url: str) -> None:
    run_migrations(db_url)
    assert VALIDATION_TABLES <= _tables(db_url)

    downgrade(db_url, "0005")

    assert _tables(db_url) == TABLES_AT_0005
    assert _version(db_url) == "0005"

    run_migrations(db_url)
    assert _tables(db_url) == ALL_TABLES


def test_upgrade_0006_creates_validation_constraints(migrated_engine: Engine) -> None:
    inspector = sa.inspect(migrated_engine)
    assert [u["name"] for u in inspector.get_unique_constraints("validation_results")] == [
        "uq_validation_results_pipeline_run_id_check_name"
    ]
    assert [i["name"] for i in inspector.get_indexes("validation_results")] == [
        "ix_validation_results_pipeline_run_id"
    ]
    assert [i["name"] for i in inspector.get_indexes("validation_report_entries")] == [
        "ix_validation_report_entries_validation_result_id"
    ]
    assert {
        f["name"] for f in inspector.get_foreign_keys("validation_report_entries")
    } == {
        "fk_validation_report_entries_validation_result_id_validation_results",
        "fk_validation_report_entries_statement_id_statements",
        "fk_validation_report_entries_party_id_parties",
    }
    columns = {c["name"]: c for c in inspector.get_columns("validation_report_entries")}
    assert columns["statement_id"]["nullable"] and columns["party_id"]["nullable"]
    assert not columns["message"]["nullable"]


def _seed_validation(engine: Engine) -> None:
    _seed_positions(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO validation_results (id, pipeline_run_id, check_name, passed, "
                "created_at) VALUES (1, 1, 'evidence_quotes', 0, '2026-10-19 00:00:00')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO validation_report_entries "
                "(validation_result_id, statement_id, party_id, message) "
                "VALUES (1, 1, 1, 'quote not found in source document 1')"
            )
        )


def test_validation_rows_accept_entries_without_statement_or_party(
    migrated_engine: Engine,
) -> None:
    _seed_validation(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO validation_report_entries (validation_result_id, message) "
                "VALUES (1, 'run-level problem')"
            )
        )


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO validation_results (pipeline_run_id, check_name, passed, created_at) "
        "VALUES (1, 'evidence_quotes', 1, '2026-10-19 00:00:00')",
        "INSERT INTO validation_results (pipeline_run_id, check_name, passed, created_at) "
        "VALUES (999, 'other', 1, '2026-10-19 00:00:00')",
        "INSERT INTO validation_results (pipeline_run_id, check_name, created_at) "
        "VALUES (1, 'other', '2026-10-19 00:00:00')",
        "INSERT INTO validation_report_entries (validation_result_id, message) "
        "VALUES (999, 'x')",
        "INSERT INTO validation_report_entries (validation_result_id, statement_id, message) "
        "VALUES (1, 999, 'x')",
        "INSERT INTO validation_report_entries (validation_result_id, party_id, message) "
        "VALUES (1, 999, 'x')",
        "INSERT INTO validation_report_entries (validation_result_id) VALUES (1)",
    ],
    ids=[
        "duplicate-run-check",
        "unknown-run",
        "missing-passed",
        "unknown-result",
        "unknown-statement",
        "unknown-party",
        "missing-message",
    ],
)
def test_validation_constraints_reject_bad_rows(migrated_engine: Engine, statement: str) -> None:
    _seed_validation(migrated_engine)
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


def test_deleting_an_election_cascades_to_validation_rows(migrated_engine: Engine) -> None:
    _seed_validation(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
        for table in VALIDATION_TABLES:
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0


# Migration 0007: at most one Published Dataset Version per Election
# (auto-publish-dataset-version Scenario 7).

PUBLISHED_INDEX = "uq_dataset_versions_published_election_id"


def _dataset_version_indexes(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return {i["name"] for i in sa.inspect(engine).get_indexes("dataset_versions")}
    finally:
        engine.dispose()


def test_downgrade_to_0006_drops_only_the_published_index(db_url: str) -> None:
    run_migrations(db_url)
    assert PUBLISHED_INDEX in _dataset_version_indexes(db_url)

    downgrade(db_url, "0006")

    assert _dataset_version_indexes(db_url) == {"ix_dataset_versions_election_id"}
    assert _tables(db_url) == TABLES_AT_0009
    assert _version(db_url) == "0006"

    run_migrations(db_url)
    assert PUBLISHED_INDEX in _dataset_version_indexes(db_url)


def test_published_index_is_partial(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        sql = conn.execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"),
            {"name": PUBLISHED_INDEX},
        ).scalar_one()
    assert sql.startswith("CREATE UNIQUE INDEX")
    assert "WHERE status = 'published'" in sql
    info = {i["name"]: i for i in sa.inspect(migrated_engine).get_indexes("dataset_versions")}
    assert info[PUBLISHED_INDEX]["unique"]
    assert info[PUBLISHED_INDEX]["column_names"] == ["election_id"]


def _seed_versions(engine: Engine, statuses: list[tuple[int, str]]) -> None:
    """Elections 1 and 2; one run and Dataset Version per ``(election_id, status)``."""
    _seed_party_and_document(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO elections (id, country, type, date, name, status) "
                "VALUES (2, 'ES', 'general', '2027-07-23', 'y', 'draft')"
            )
        )
        for number, (election_id, status) in enumerate(statuses, start=1):
            conn.execute(
                sa.text(
                    f"INSERT INTO pipeline_runs (id, {_RUN_COLUMNS}) VALUES "
                    f"({number}, {election_id}, 'passed', 'fake', 'fake-model', 'precomputed', "
                    "'{}', 0, 0, 0, '2026-10-19 00:00:00')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO dataset_versions "
                    "(id, election_id, pipeline_run_id, status, created_at) "
                    f"VALUES ({number}, {election_id}, {number}, '{status}', "
                    "'2026-10-19 00:00:00')"
                )
            )


def test_published_index_accepts_one_published_per_election(migrated_engine: Engine) -> None:
    _seed_versions(
        migrated_engine,
        [
            (1, "published"),
            (2, "published"),
            (1, "superseded"),
            (1, "superseded"),
            (1, "candidate"),
            (1, "candidate"),
            (2, "candidate"),
        ],
    )
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT election_id, count(*) FROM dataset_versions "
                "WHERE status = 'published' GROUP BY election_id ORDER BY election_id"
            )
        ).all()
    assert [tuple(r) for r in rows] == [(1, 1), (2, 1)]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE dataset_versions SET status = 'published' WHERE id = 2",
        "UPDATE dataset_versions SET status = 'published' WHERE id = 3",
        "UPDATE dataset_versions SET status = 'published' WHERE election_id = 1",
    ],
    ids=["candidate-to-published", "superseded-to-published", "all-published"],
)
def test_published_index_rejects_a_second_published_version(
    migrated_engine: Engine, statement: str
) -> None:
    _seed_versions(migrated_engine, [(1, "published"), (1, "candidate"), (1, "superseded")])
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text(statement))


# Migration 0008: the ValidationSettings a run was validated with
# (pipeline-run-report).


def _pipeline_run_columns(url: str) -> dict[str, dict[str, object]]:
    engine = make_engine(url)
    try:
        return {c["name"]: c for c in sa.inspect(engine).get_columns("pipeline_runs")}
    finally:
        engine.dispose()


def _pipeline_run_sql(url: str) -> str:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pipeline_runs'")
            ).scalar_one()
    finally:
        engine.dispose()


def test_upgrade_0008_adds_a_nullable_validation_settings_column(db_url: str) -> None:
    run_migrations(db_url, "0007")
    before = _pipeline_run_columns(db_url)
    assert "validation_settings" not in before

    run_migrations(db_url, "0008")

    after = _pipeline_run_columns(db_url)
    assert set(after) - set(before) == {"validation_settings"}
    assert after["validation_settings"]["nullable"] is True
    assert isinstance(after["validation_settings"]["type"], sa.JSON)


def test_downgrade_to_0007_drops_only_the_column_and_keeps_rows(db_url: str) -> None:
    run_migrations(db_url, "0009")
    engine = make_engine(db_url)
    try:
        _seed_versions(engine, [(1, "published"), (1, "candidate")])
        with engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE pipeline_runs SET validation_settings = '{\"min_statements\": 25}'"
            ))
    finally:
        engine.dispose()
    sql_before = _pipeline_run_sql(db_url)
    columns_before = set(_pipeline_run_columns(db_url))

    downgrade(db_url, "0007")

    assert _version(db_url) == "0007"
    assert set(_pipeline_run_columns(db_url)) == columns_before - {"validation_settings"}
    assert _tables(db_url) == TABLES_AT_0009
    assert PUBLISHED_INDEX in _dataset_version_indexes(db_url)
    # The table is not recreated: its CHECKs stay, and the ON DELETE CASCADE
    # from dataset_versions never fires.
    sql_after = _pipeline_run_sql(db_url)
    for name in ("ck_pipeline_runs_pipeline_run_status", "ck_pipeline_runs_generation_mode"):
        assert name in sql_before and name in sql_after
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            for table, count in (("pipeline_runs", 2), ("dataset_versions", 2)):
                assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == count
    finally:
        engine.dispose()

    run_migrations(db_url)
    assert "validation_settings" in _pipeline_run_columns(db_url)
    assert _version(db_url) == "0010"


def test_offline_postgresql_render_of_0008() -> None:
    upgrade = io.StringIO()
    command.upgrade(
        alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=upgrade),
        "0007:0008",
        sql=True,
    )
    down = io.StringIO()
    command.downgrade(
        alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=down),
        "0008:0007",
        sql=True,
    )

    assert "ALTER TABLE pipeline_runs ADD COLUMN validation_settings JSON;" in upgrade.getvalue()
    assert "CHECK" not in upgrade.getvalue()
    assert "ALTER TABLE pipeline_runs DROP COLUMN validation_settings;" in down.getvalue()


# Migration 0009: URL re-fetch state on source_documents (live-mode-url-refetch).


def _source_document_columns(url: str) -> dict[str, dict[str, object]]:
    engine = make_engine(url)
    try:
        return {c["name"]: c for c in sa.inspect(engine).get_columns("source_documents")}
    finally:
        engine.dispose()


def _source_document_sql(url: str) -> str:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'source_documents'"
                )
            ).scalar_one()
    finally:
        engine.dispose()


def _counts(url: str, tables: tuple[str, ...]) -> dict[str, int]:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return {
                t: conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in tables
            }
    finally:
        engine.dispose()


def test_upgrade_0009_adds_two_nullable_columns_and_keeps_rows(db_url: str) -> None:
    run_migrations(db_url, "0008")
    engine = make_engine(db_url)
    try:
        _seed_party_and_document(engine)
    finally:
        engine.dispose()
    before = _source_document_columns(db_url)
    assert "replaced_by_id" not in before and "last_checked_at" not in before

    run_migrations(db_url, "0009")

    assert _version(db_url) == "0009"
    after = _source_document_columns(db_url)
    assert set(after) - set(before) == {"replaced_by_id", "last_checked_at"}
    assert after["replaced_by_id"]["nullable"] is True
    assert isinstance(after["replaced_by_id"]["type"], sa.Integer)
    assert after["last_checked_at"]["nullable"] is True
    assert isinstance(after["last_checked_at"]["type"], sa.DateTime)
    assert _counts(db_url, ("source_documents", "source_document_pages")) == {
        "source_documents": 1,
        "source_document_pages": 1,
    }
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT replaced_by_id, last_checked_at FROM source_documents")
            ).one()
        assert tuple(row) == (None, None)
        # No FOREIGN KEY on replaced_by_id (the service keeps it consistent).
        fks = sa.inspect(engine).get_foreign_keys("source_documents")
        assert [fk["constrained_columns"] for fk in fks] == [["party_id"]]
    finally:
        engine.dispose()


def test_downgrade_to_0008_drops_only_the_columns_and_keeps_pages(db_url: str) -> None:
    run_migrations(db_url, "0009")
    engine = make_engine(db_url)
    try:
        _seed_party_and_document(engine)
        with engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE source_documents SET replaced_by_id = 7, "
                "last_checked_at = '2026-10-20 06:00:00'"
            ))
    finally:
        engine.dispose()
    sql_before = _source_document_sql(db_url)
    columns_before = set(_source_document_columns(db_url))

    downgrade(db_url, "0008")

    assert _version(db_url) == "0008"
    assert set(_source_document_columns(db_url)) == columns_before - {
        "replaced_by_id",
        "last_checked_at",
    }
    assert _tables(db_url) == TABLES_AT_0009
    # Not recreated: the CHECKs stay and the cascade to pages never fires.
    sql_after = _source_document_sql(db_url)
    for name in (
        "ck_source_documents_source_document_origin",
        "ck_source_documents_source_document_status",
        "ck_source_documents_source_url_matches_origin",
    ):
        assert name in sql_before and name in sql_after
    assert _counts(db_url, ("source_documents", "source_document_pages")) == {
        "source_documents": 1,
        "source_document_pages": 1,
    }

    run_migrations(db_url)
    assert {"replaced_by_id", "last_checked_at"} <= set(_source_document_columns(db_url))
    assert _version(db_url) == "0010"


def test_offline_postgresql_render_of_0009() -> None:
    upgrade = io.StringIO()
    command.upgrade(
        alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=upgrade),
        "0008:0009",
        sql=True,
    )
    down = io.StringIO()
    command.downgrade(
        alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=down),
        "0009:0008",
        sql=True,
    )

    up_sql = upgrade.getvalue()
    assert "ALTER TABLE source_documents ADD COLUMN replaced_by_id INTEGER;" in up_sql
    assert (
        "ALTER TABLE source_documents ADD COLUMN last_checked_at TIMESTAMP WITH TIME ZONE;"
        in up_sql
    )
    assert "CHECK" not in up_sql and "FOREIGN KEY" not in up_sql
    down_sql = down.getvalue()
    assert "ALTER TABLE source_documents DROP COLUMN last_checked_at;" in down_sql
    assert "ALTER TABLE source_documents DROP COLUMN replaced_by_id;" in down_sql


# Migration 0010: recorded LLM calls and resumed_from_run_id (pipeline-run-checkpoint).


def test_upgrade_0010_adds_the_calls_table_and_column_and_keeps_rows(db_url: str) -> None:
    run_migrations(db_url, "0009")
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO elections (id, country, type, date, name, status)"
                    " VALUES (1, 'ES', 'general', '2023-07-23', 'G', 'draft')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO pipeline_runs (id, election_id, status, llm_provider,"
                    " llm_model, generation_mode, prompt_versions, llm_calls, input_tokens,"
                    " output_tokens, created_at) VALUES (1, 1, 'failed', 'fake', 'm',"
                    " 'precomputed', '{}', 0, 0, 0, '2026-01-01')"
                )
            )
    finally:
        engine.dispose()

    run_migrations(db_url)

    assert _version(db_url) == "0010"
    assert _tables(db_url) == ALL_TABLES
    columns = _pipeline_run_columns(db_url)
    assert columns["resumed_from_run_id"]["nullable"] is True
    assert _counts(db_url, ("pipeline_runs",)) == {"pipeline_runs": 1}


def test_downgrade_to_0009_drops_the_calls_and_keeps_runs_and_versions(db_url: str) -> None:
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO elections (id, country, type, date, name, status)"
                    " VALUES (1, 'ES', 'general', '2023-07-23', 'G', 'draft')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO pipeline_runs (id, election_id, status, llm_provider,"
                    " llm_model, generation_mode, prompt_versions, llm_calls, input_tokens,"
                    " output_tokens, created_at, resumed_from_run_id) VALUES (1, 1,"
                    " 'validating', 'fake', 'm', 'precomputed', '{}', 0, 0, 0,"
                    " '2026-01-01', NULL)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO dataset_versions (id, election_id, pipeline_run_id, status,"
                    " created_at) VALUES (1, 1, 1, 'candidate', '2026-01-01')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO pipeline_run_calls (pipeline_run_id, sequence, task,"
                    " request_hash, output, input_tokens, output_tokens, reused, created_at)"
                    " VALUES (1, 1, 't', :h, '{}', 1, 1, 0, '2026-01-01')"
                ),
                {"h": "a" * 64},
            )
    finally:
        engine.dispose()

    downgrade(db_url, "0009")

    assert _version(db_url) == "0009"
    assert _tables(db_url) == TABLES_AT_0009
    assert "resumed_from_run_id" not in _pipeline_run_columns(db_url)
    assert _counts(db_url, ("pipeline_runs", "dataset_versions")) == {
        "pipeline_runs": 1,
        "dataset_versions": 1,
    }
    run_migrations(db_url)
    assert _version(db_url) == "0010"


def test_offline_postgresql_render_of_0010() -> None:
    upgrade = io.StringIO()
    command.upgrade(
        alembic_config("postgresql://user:secret@localhost/ideology", output_buffer=upgrade),
        "0009:0010",
        sql=True,
    )
    up_sql = upgrade.getvalue()
    assert "CREATE TABLE pipeline_run_calls" in up_sql
    assert "ON DELETE CASCADE" in up_sql
    assert "ALTER TABLE pipeline_runs ADD COLUMN resumed_from_run_id INTEGER;" in up_sql
