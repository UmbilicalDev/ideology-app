"""live-mode-source-change-trigger Scenarios 2, 3 and 8-10: ``source add`` and ``pipeline run-queued``."""

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from pdf_factory import blank_pdf, make_text_pdf
from pipeline_fixtures import (
    default_responses,
    fake_provider,
    findings_response,
    offline_guard,
    seed_election,
    statements_payload,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import main
from ideology_app.db import make_engine, run_migrations
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.models import (
    PipelineRun,
    PipelineRunSourceDocument,
    PipelineRunStatus,
    SourceDocument,
)
from ideology_app.pdf_text import NO_TEXT_LAYER

RUN_HEADER = (
    "id\tstatus\tprovider\tmodel\tmode\tdataset_version\tstatements\t"
    "llm_calls\tinput_tokens\toutput_tokens\tfailure_reason"
)
# seed_election stores documents 1-3; the first CLI document is 4.
NEW_PAGES = ["Propuestas nuevas sobre transporte público.", "Propuestas sobre energía."]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    offline_guard(monkeypatch)
    monkeypatch.setenv("SOURCE_FILES_DIR", str(tmp_path / "stored"))


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def seeded(db_url: str) -> None:
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        seed_election(engine)
    finally:
        engine.dispose()


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "nuevo.pdf"
    path.write_bytes(make_text_pdf(NEW_PAGES))
    return path


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture
def use_fake(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


def _count(db_url: str, model: type) -> int:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            return s.scalar(select(func.count()).select_from(model)) or 0
    finally:
        engine.dispose()


def _statuses(db_url: str) -> list[tuple[int, PipelineRunStatus]]:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            runs = s.scalars(select(PipelineRun).order_by(PipelineRun.id))
            return [(r.id, r.status) for r in runs]
    finally:
        engine.dispose()


def _second_election(run, tmp_path: Path) -> None:
    """Election 2 with Party 3 (no documents)."""
    for args in (
        ("election", "create", "--country", "ES", "--type", "general",
         "--date", "2027-07-23", "--name", "Generales 2027"),
        ("party", "add", "--election", "2", "--name", "Partido Gamma", "--short-name", "PG"),
    ):
        result = run(*args)
        assert result.exit_code == 0, result.output


def _pdf_at(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_bytes(make_text_pdf([text]))
    return path


# Scenario 1 / 5 through the CLI


def test_live_source_add_queues_a_run(run, seeded, live, pdf: Path, db_url: str) -> None:
    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Created source document 4: parsed (2 pages)\n"
        "Queued pipeline run 1 for election 1 (generation mode live)\n"
    )
    listed = run("pipeline", "list", "--election", "1").output.splitlines()
    assert listed[0] == RUN_HEADER
    assert listed[1].split("\t") == [
        "1", "queued", "fake", "fake-model", "live", "", "", "0", "0", "0", ""
    ]


def test_live_second_document_reports_the_queued_run(
    run, seeded, live, pdf: Path, tmp_path: Path
) -> None:
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0

    result = run("source", "add", "--party", "2", "--file", str(pdf))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Created source document 5: parsed (2 pages)\n"
        "Pipeline run 1 is already queued for election 1\n"
    )
    assert len(run("pipeline", "list", "--election", "1").output.splitlines()) == 2


def test_live_blank_pdf_keeps_todays_error_and_queues_nothing(
    run, seeded, live, tmp_path: Path, db_url: str
) -> None:
    blank = tmp_path / "scan.pdf"
    blank.write_bytes(blank_pdf(1))

    result = run("source", "add", "--party", "1", "--file", str(blank))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"Error: source document 4 failed: {NO_TEXT_LAYER}\n"
    assert _count(db_url, PipelineRun) == 0


# Scenario 2


def test_live_same_hash_is_a_duplicate_and_queues_nothing(
    run, seeded, pdf: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = run("source", "add", "--party", "1", "--file", str(pdf))
    assert first.output == "Created source document 4: parsed (2 pages)\n"
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    again = run("source", "add", "--party", "1", "--file", str(pdf))

    assert again.exit_code == 1
    assert again.stdout == ""
    assert again.stderr.startswith(
        "Error: party 1 already has a source document with content hash "
    )
    assert _count(db_url, SourceDocument) == 4
    assert run("pipeline", "list", "--election", "1").output == RUN_HEADER + "\n"


# Scenario 3


@pytest.mark.parametrize("mode", [None, "precomputed", " PRECOMPUTED "])
def test_precomputed_output_is_unchanged(
    run, seeded, pdf: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, mode: str | None
) -> None:
    if mode is not None:
        monkeypatch.setenv("GENERATION_MODE", mode)

    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 0, result.output
    assert result.output == "Created source document 4: parsed (2 pages)\n"
    assert _count(db_url, PipelineRun) == 0


# Scenario 8


def test_invalid_generation_mode_writes_nothing(
    run, seeded, pdf: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "bogus")

    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: Invalid GENERATION_MODE 'bogus'; supported values: precomputed, live\n"
    )
    assert _count(db_url, SourceDocument) == 3
    assert not (tmp_path / "stored").exists()


def test_live_with_invalid_provider_writes_nothing(
    run, seeded, pdf: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "bogus")

    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, claude_code, fake\n"
    )
    assert _count(db_url, SourceDocument) == 3
    assert _count(db_url, PipelineRun) == 0
    assert not (tmp_path / "stored").exists()


def test_precomputed_ignores_llm_settings(
    run, seeded, pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "bogus")

    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 0, result.output
    assert result.output == "Created source document 4: parsed (2 pages)\n"


def test_live_with_anthropic_needs_no_api_key(
    run, seeded, pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")

    result = run("source", "add", "--party", "1", "--file", str(pdf))

    assert result.exit_code == 0, result.output
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1:5] == ["queued", "anthropic", "claude-sonnet-5-5", "live"]


# Scenario 9


def test_run_queued_executes_the_queued_run(run, seeded, live, pdf: Path, use_fake) -> None:
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    provider = use_fake(fake_provider())

    result = run("pipeline", "run-queued")

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Pipeline run 1: passed (dataset version 1, 35 statements, 70 party positions)\n"
        "Published dataset version 1 for election 1\n"
    )
    assert provider.calls
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1:6] == ["passed", "fake", "fake-model", "live", "1"]


def test_run_queued_reads_every_document_added_before_it_starts(
    run, seeded, live, pdf: Path, use_fake, db_url: str
) -> None:
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    assert run("source", "add", "--party", "2", "--file", str(pdf)).exit_code == 0
    use_fake(fake_provider())

    assert run("pipeline", "run-queued").exit_code == 0

    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            read = sorted(
                s.scalars(select(PipelineRunSourceDocument.source_document_id)).all()
            )
    finally:
        engine.dispose()
    assert read == [1, 2, 4, 5]


# Scenario 10


def test_run_queued_with_nothing_queued(run, seeded, use_fake) -> None:
    provider = use_fake(fake_provider())

    result = run("pipeline", "run-queued")

    assert result.exit_code == 0, result.output
    assert result.output == "No queued pipeline runs\n"
    assert provider.calls == []


def test_run_queued_for_one_election(
    run, seeded, live, pdf: Path, use_fake, tmp_path: Path, db_url: str
) -> None:
    _second_election(run, tmp_path)
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    gamma = _pdf_at(tmp_path, "gamma.pdf", "Programa de Gamma.")
    queued = run("source", "add", "--party", "3", "--file", str(gamma))
    assert queued.output.endswith("Queued pipeline run 2 for election 2 (generation mode live)\n")
    use_fake(fake_provider())

    result = run("pipeline", "run-queued", "--election", "1")

    assert result.exit_code == 0, result.output
    assert result.output.startswith("Pipeline run 1: passed")
    assert _statuses(db_url) == [(1, PipelineRunStatus.PASSED), (2, PipelineRunStatus.QUEUED)]


def test_run_queued_unknown_election(run, seeded, use_fake) -> None:
    use_fake(fake_provider())

    result = run("pipeline", "run-queued", "--election", "9")

    assert result.exit_code == 1
    assert result.stderr == "Error: election 9 not found\n"


def test_failed_run_is_reported_and_later_runs_still_execute(
    run, seeded, live, pdf: Path, use_fake, tmp_path: Path, db_url: str
) -> None:
    # Run 1 (election 2) fails generation; run 2 (election 1) passes.
    _second_election(run, tmp_path)
    gamma = _pdf_at(tmp_path, "gamma.pdf", "Programa de Gamma.")
    assert run("source", "add", "--party", "3", "--file", str(gamma)).exit_code == 0
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    calls: list[int] = []

    def _first_fails(request: LLMRequest[Any]) -> dict[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            raise LLMProviderError("APIConnectionError")
        return statements_payload()

    use_fake(fake_provider(generate_statements=_first_fails))

    result = run("pipeline", "run-queued")

    assert result.exit_code == 1
    assert result.stdout == (
        "Pipeline run 2: passed (dataset version 1, 35 statements, 70 party positions)\n"
        "Published dataset version 1 for election 1\n"
    )
    assert result.stderr == (
        "Error: pipeline run 1 failed: APIConnectionError\n"
        "Error: 1 of 2 queued pipeline runs failed\n"
    )
    assert _statuses(db_url) == [(1, PipelineRunStatus.FAILED), (2, PipelineRunStatus.PASSED)]


def test_validation_failure_points_at_the_checks(
    run, seeded, live, pdf: Path, use_fake, db_url: str
) -> None:
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    # A Validation failure the selection cannot fix: every Party agrees everywhere.
    use_fake(fake_provider(position_findings=findings_response(value=1)))

    result = run("pipeline", "run-queued")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: pipeline run 1 failed: validation failed: statement_separation; "
        'see "ideology pipeline checks --run 1"\n'
        "Error: 1 of 1 queued pipeline runs failed\n"
    )


def test_run_queued_for_another_model_stays_queued(
    run, seeded, live, pdf: Path, use_fake, tmp_path: Path, db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _second_election(run, tmp_path)
    monkeypatch.setenv("LLM_MODEL", "other-model")
    gamma = _pdf_at(tmp_path, "gamma.pdf", "Programa de Gamma.")
    assert run("source", "add", "--party", "3", "--file", str(gamma)).exit_code == 0
    monkeypatch.delenv("LLM_MODEL")
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    use_fake(fake_provider())

    result = run("pipeline", "run-queued")

    assert result.exit_code == 1
    assert result.stdout.startswith("Pipeline run 2: passed")
    assert result.stderr == (
        "Error: pipeline run 1 was queued for fake/other-model, not fake/fake-model\n"
        "Error: 1 of 2 queued pipeline runs failed\n"
    )
    assert _statuses(db_url) == [(1, PipelineRunStatus.QUEUED), (2, PipelineRunStatus.PASSED)]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("LLM_PROVIDER", "Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, claude_code, fake\n"),
        (
            "VALIDATION_MIN_STATEMENTS",
            "Error: Invalid VALIDATION_MIN_STATEMENTS 'bogus'; expected a positive integer\n",
        ),
    ],
)
def test_run_queued_config_errors_change_nothing(
    run, seeded, live, pdf: Path, db_url: str, monkeypatch: pytest.MonkeyPatch,
    name: str, message: str,
) -> None:
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    monkeypatch.setenv(name, "bogus")

    result = run("pipeline", "run-queued")

    assert result.exit_code == 1
    assert result.stderr == message
    assert _statuses(db_url) == [(1, PipelineRunStatus.QUEUED)]


@pytest.mark.parametrize("queued", [True, False], ids=["with-runs", "empty"])
def test_run_queued_closes_the_provider_once(
    run, seeded, live, pdf: Path, use_fake, queued: bool
) -> None:
    closed: list[bool] = []

    class ClosingFake(FakeProvider):
        def close(self) -> None:
            closed.append(True)

    if queued:
        assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    use_fake(ClosingFake(default_responses()))

    assert run("pipeline", "run-queued").exit_code == 0
    assert closed == [True]


def test_pipeline_run_is_unchanged_in_live_mode(run, seeded, live, use_fake, db_url: str) -> None:
    use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert _statuses(db_url) == [(1, PipelineRunStatus.PASSED)]
