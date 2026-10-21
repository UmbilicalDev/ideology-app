"""``ideology pipeline report --run N`` with the fake provider (pipeline-run-report).

Scenarios 1-8 of docs/specs/pipeline-run-report.md. No API key, no network:
runs are produced with ``FakeProvider`` through ``cli._provider``, and the
report itself is read with the provider seam disabled.
"""

import datetime as dt
from typing import Any

import pytest
from click.testing import CliRunner, Result
from pipeline_fixtures import (
    PAGES,
    chunk_pages,
    fake_provider,
    findings_response,
    offline_guard,
    seed_election,
    statements_payload,
)
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.config import GenerationMode
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.models import PipelineRun, ValidationResult
from ideology_app.pipeline import PROMPT_VERSIONS, execute_run, queue_run
from ideology_app.pipeline import runs as runs_module

CHECKS_HEADER = "check\tresult\tstatement\tparty\tmessage"
PASSED_ROWS = [
    f"{name}\tpassed\t\t\t"
    for name in (
        "evidence_quotes",
        "party_coverage",
        "statement_separation",
        "statement_uniqueness",
        "statement_count",
        "topic_spread",
    )
]
UNIQUENESS_ROW = "statement_uniqueness\tfailed\t5\t\tstatement 5 duplicates statement 2"
DEFAULT_SETTINGS = (
    "validation_settings: max_statements=35, max_topic_share_percent=30, "
    "min_party_coverage_percent=70, min_statements=25"
)
PROMPTS_LINE = "prompt_versions: " + ", ".join(
    f"{task}={PROMPT_VERSIONS[task]}" for task in sorted(PROMPT_VERSIONS)
)
KEYS = [
    "pipeline run",
    "election",
    "status",
    "failure_reason",
    "provider",
    "model",
    "generation_mode",
    "prompt_versions",
    "created_at",
    "started_at",
    "generation_finished_at",
    "validated_at",
    "duration",
    "llm_calls",
    "input_tokens",
    "output_tokens",
    "resumed_from",
    "reused_calls",
    "cost",
    "validation_settings",
    "dataset_version",
    "dataset_version_status",
    "statements",
    "publication",
]
TABLES = [
    "elections",
    "pipeline_runs",
    "dataset_versions",
    "statements",
    "party_positions",
    "validation_results",
    "validation_report_entries",
]
INVENTED = "Bajaremos el IVA de los libros al cero por ciento."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


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
def use_fake(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


@pytest.fixture
def report(run, monkeypatch: pytest.MonkeyPatch):
    """Run ``pipeline report``; it must not resolve a provider or read LLM settings."""

    def _boom() -> FakeProvider:
        raise AssertionError("pipeline report must not need a provider")

    def _report(run_id: int) -> Result:
        with monkeypatch.context() as mp:
            mp.setattr(cli, "_provider", _boom)
            mp.setenv("LLM_PROVIDER", "bogus")
            return run("pipeline", "report", "--run", str(run_id))

    return _report


def _engine(db_url: str) -> Engine:
    return make_engine(db_url)


def read_run(db_url: str, run_id: int) -> PipelineRun:
    engine = _engine(db_url)
    try:
        with Session(engine, expire_on_commit=False) as s:
            found = s.get(PipelineRun, run_id)
            assert found is not None
            s.expunge(found)
            return found
    finally:
        engine.dispose()


def validated_at(db_url: str, run_id: int) -> dt.datetime | None:
    engine = _engine(db_url)
    try:
        with Session(engine) as s:
            return s.scalar(
                select(func.min(ValidationResult.created_at)).where(
                    ValidationResult.pipeline_run_id == run_id
                )
            )
    finally:
        engine.dispose()


def fields(result: Result) -> dict[str, str]:
    """The ``key: value`` lines before the blank line, checked for order and keys."""
    head = result.output.split("\n\n", 1)[0].splitlines()
    pairs = [line.split(": ", 1) for line in head]
    assert [key for key, _ in pairs] == KEYS
    return {key: value for key, value in pairs}


def table(result: Result) -> list[str]:
    """The Validation report table after the blank line."""
    tail = result.output.split("\n\n", 1)[1].splitlines()
    assert tail[:2] == ["validation report:", CHECKS_HEADER]
    return tail[2:]


def iso(value: dt.datetime | None) -> str:
    return "not recorded" if value is None else value.isoformat(timespec="seconds")


def _invented_for_party2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2 cites an invented quote for Statement 1 (evidence_quotes fails)."""
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    kept = [f for f in real["findings"] if f["statement"] != 1]
    return {"findings": [*kept, {"statement": 1, "value": -1, "quote": INVENTED, "page": 1}]}


def _queue(db_url: str, provider: FakeProvider) -> int:
    engine = _engine(db_url)
    try:
        with session_scope(engine) as session:
            return queue_run(
                session,
                1,
                llm_provider=provider.name,
                llm_model=provider.model,
                generation_mode=GenerationMode.PRECOMPUTED,
            ).id
    finally:
        engine.dispose()


def _validating_run(db_url: str, provider: FakeProvider) -> int:
    """Leave a new run in ``validating`` (generation done, Validation not run)."""
    run_id = _queue(db_url, provider)
    engine = _engine(db_url)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
            execute_run(engine, run_id, provider)
    finally:
        engine.dispose()
    return run_id


def snapshot(db_url: str) -> dict[str, list[tuple[Any, ...]]]:
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            return {
                name: [tuple(r) for r in conn.execute(text(f"SELECT * FROM {name} ORDER BY 1"))]
                for name in TABLES
            }
    finally:
        engine.dispose()


# Scenario 1: passed and published run


def test_report_of_a_passed_and_published_run(run, report, seeded, use_fake, db_url) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0

    result = report(1)

    assert result.exit_code == 0, result.output
    stored = read_run(db_url, 1)
    assert stored.llm_calls == 7
    assert stored.input_tokens > 0 and stored.output_tokens > 0
    assert stored.started_at is not None and stored.generation_finished_at is not None
    seconds = (stored.generation_finished_at - stored.started_at).total_seconds()
    checked = validated_at(db_url, 1)
    assert checked is not None
    expected_head = [
        "pipeline run: 1",
        "election: 1",
        "status: passed",
        "failure_reason: none",
        "provider: fake",
        "model: fake-model",
        "generation_mode: precomputed",
        PROMPTS_LINE,
        f"created_at: {iso(stored.created_at)}",
        f"started_at: {iso(stored.started_at)}",
        f"generation_finished_at: {iso(stored.generation_finished_at)}",
        f"validated_at: {iso(checked)}",
        f"duration: {seconds:.1f} s (generation)",
        "llm_calls: 7",
        f"input_tokens: {stored.input_tokens}",
        f"output_tokens: {stored.output_tokens}",
        "resumed_from: none",
        "reused_calls: 0",
        "cost: not estimated (no price table)",
        DEFAULT_SETTINGS,
        "dataset_version: 1",
        "dataset_version_status: published",
        "statements: 30",
        "publication: published: live for election 1",
        "",
        "validation report:",
        CHECKS_HEADER,
        *PASSED_ROWS,
    ]
    assert result.output == "".join(f"{line}\n" for line in expected_head)
    assert len(PROMPT_VERSIONS) == 4
    assert result.stderr == ""
    # The table is exactly what ``pipeline checks`` prints.
    checks = run("pipeline", "checks", "--run", "1")
    assert table(result) == checks.output.splitlines()[1:]


def test_usage_is_deterministic(run, report, seeded, use_fake, db_url) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0

    first, second = fields(report(1)), fields(report(2))

    for key in ("llm_calls", "input_tokens", "output_tokens"):
        assert first[key] == second[key]


# Scenario 2: failed run (Validation failure)


def test_report_of_a_run_that_failed_validation(run, report, seeded, use_fake) -> None:
    # A Validation failure the generate_statements schema still allows (since
    # pipeline-output-bounds 20 Statements fail at generation).
    use_fake(fake_provider(generate_statements=statements_payload(duplicate=(2, 5))))
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = report(1)

    assert result.exit_code == 0, result.output
    got = fields(result)
    assert got["status"] == "failed"
    assert got["failure_reason"] == "validation failed: statement_uniqueness"
    assert got["dataset_version"] == "1"
    assert got["dataset_version_status"] == "candidate"
    assert got["statements"] == "30"
    assert got["publication"] == "not published: the run failed; live for election 1: none"
    assert got["validation_settings"] == DEFAULT_SETTINGS.split(": ", 1)[1]
    assert got["validated_at"] != "not recorded"
    assert UNIQUENESS_ROW in table(result)
    assert table(result) == run("pipeline", "checks", "--run", "1").output.splitlines()[1:]


def test_report_of_a_failed_run_names_the_earlier_live_version(
    run, report, seeded, use_fake
) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    use_fake(fake_provider(position_findings=_invented_for_party2))
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = report(2)

    got = fields(result)
    assert got["status"] == "failed"
    assert got["failure_reason"] == "validation failed: evidence_quotes"
    assert got["dataset_version_status"] == "candidate"
    assert got["publication"] == (
        "not published: the run failed; live for election 1: "
        "dataset version 1 of pipeline run 1"
    )
    rows = table(result)
    assert [r for r in rows if r.startswith("evidence_quotes\tfailed\t1\t2\t")]
    assert rows == run("pipeline", "checks", "--run", "2").output.splitlines()[1:]


# Scenario 3: passed but kept candidate


def test_report_of_a_passed_run_kept_candidate(run, report, seeded, use_fake, db_url) -> None:
    _validating_run(db_url, fake_provider())
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    assert run("pipeline", "validate", "--run", "1").exit_code == 0

    result = report(1)

    got = fields(result)
    assert got["status"] == "passed"
    assert got["failure_reason"] == "none"
    assert got["dataset_version"] == "1"
    assert got["dataset_version_status"] == "candidate"
    assert got["publication"] == (
        "not published: the run passed but its dataset version was kept candidate; "
        "live for election 1: dataset version 2 of pipeline run 2"
    )
    assert not got["publication"].startswith("not published: the run failed")
    assert table(result) == PASSED_ROWS


# Scenario 4: superseded run


def test_report_of_a_superseded_run(run, report, seeded, use_fake) -> None:
    for _ in range(2):
        use_fake(fake_provider())
        assert run("pipeline", "run", "--election", "1").exit_code == 0

    got = fields(report(1))

    assert got["status"] == "passed"
    assert got["dataset_version_status"] == "superseded"
    assert got["publication"] == (
        "superseded: live for election 1: dataset version 2 of pipeline run 2"
    )
    assert fields(report(2))["publication"] == "published: live for election 1"


# Scenario 5: run failed during generation


def test_report_of_a_run_that_failed_during_generation(
    run, report, seeded, use_fake, db_url
) -> None:
    def _boom(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMProviderError("APIConnectionError")

    use_fake(fake_provider(generate_statements=_boom))
    assert run("pipeline", "run", "--election", "1").exit_code == 1

    result = report(1)

    assert result.exit_code == 0, result.output
    stored = read_run(db_url, 1)
    got = fields(result)
    assert got["status"] == "failed"
    assert got["failure_reason"] == "APIConnectionError"
    assert got["dataset_version"] == "none"
    assert got["dataset_version_status"] == "none"
    assert got["statements"] == "none"
    assert got["publication"] == "none: the run failed before a dataset version was created"
    assert got["validated_at"] == "not recorded"
    assert got["validation_settings"] == "not recorded"
    assert got["generation_finished_at"] == iso(stored.generation_finished_at) != "not recorded"
    assert stored.llm_calls > 0
    assert (got["llm_calls"], got["input_tokens"], got["output_tokens"]) == (
        str(stored.llm_calls),
        str(stored.input_tokens),
        str(stored.output_tokens),
    )
    assert table(result) == []


def test_multi_line_failure_reason_is_one_line(run, report, seeded, use_fake, db_url) -> None:
    use_fake(fake_provider(generate_statements=statements_payload(20)))
    assert run("pipeline", "run", "--election", "1").exit_code == 1
    engine = _engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                update(PipelineRun).where(PipelineRun.id == 1).values(failure_reason="a\n\tb")
            )
    finally:
        engine.dispose()

    assert fields(report(1))["failure_reason"] == "a b"


# Scenario 6: stored thresholds and older runs


def test_report_shows_the_threshold_used_by_pipeline_run(
    run, report, seeded, use_fake, monkeypatch
) -> None:
    use_fake(fake_provider())
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "50")
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    monkeypatch.delenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT")

    assert fields(report(1))["validation_settings"] == (
        "max_statements=35, max_topic_share_percent=30, "
        "min_party_coverage_percent=50, min_statements=25"
    )


def test_report_shows_the_threshold_used_by_pipeline_validate(
    run, report, seeded, db_url, monkeypatch
) -> None:
    _validating_run(db_url, fake_provider())
    assert fields(report(1))["validation_settings"] == "not recorded"
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "50")
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "40")
    assert run("pipeline", "validate", "--run", "1").exit_code == 0
    monkeypatch.delenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT")
    monkeypatch.delenv("VALIDATION_MAX_STATEMENTS")

    assert fields(report(1))["validation_settings"] == (
        "max_statements=40, max_topic_share_percent=30, "
        "min_party_coverage_percent=50, min_statements=25"
    )


def test_run_validated_before_0008_shows_not_recorded(
    run, report, seeded, use_fake, db_url
) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    engine = _engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                update(PipelineRun).where(PipelineRun.id == 1).values(validation_settings=None)
            )
    finally:
        engine.dispose()

    got = fields(report(1))

    assert got["validation_settings"] == "not recorded"
    assert got["status"] == "passed"


# Scenario 7: duration, validating and queued runs


def test_duration_is_generation_time(run, report, seeded, use_fake, db_url) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    start = dt.datetime(2026, 10, 19, 10, 0, 0)
    engine = _engine(db_url)
    try:
        with session_scope(engine) as session:
            stored = session.get(PipelineRun, 1)
            assert stored is not None
            stored.started_at = start
            stored.generation_finished_at = start + dt.timedelta(seconds=12.34)
    finally:
        engine.dispose()

    got = fields(report(1))

    assert got["duration"] == "12.3 s (generation)"
    assert got["started_at"] == "2026-10-19T10:00:00"
    assert got["generation_finished_at"] == "2026-10-19T10:00:12"


def test_report_of_a_validating_run(report, seeded, db_url) -> None:
    _validating_run(db_url, fake_provider())

    got = fields(report(1))

    assert got["status"] == "validating"
    assert got["dataset_version_status"] == "candidate"
    assert got["publication"] == (
        'not published: awaiting Validation (run "ideology pipeline validate --run 1")'
    )
    assert got["validated_at"] == "not recorded"
    assert got["llm_calls"] == "7"


def test_report_of_a_queued_run(report, seeded, db_url) -> None:
    _queue(db_url, fake_provider())

    result = report(1)

    assert result.exit_code == 0, result.output
    got = fields(result)
    assert got["status"] == "queued"
    for key in (
        "started_at",
        "generation_finished_at",
        "validated_at",
        "duration",
        "llm_calls",
        "input_tokens",
        "output_tokens",
        "validation_settings",
    ):
        assert got[key] == "not recorded", key
    assert got["created_at"] != "not recorded"
    assert got["dataset_version"] == "none"
    assert got["publication"] == "none: the run has not produced a dataset version yet"
    assert table(result) == []


# Scenario 8: read-only and errors


def test_report_changes_nothing(run, report, seeded, use_fake, db_url) -> None:
    use_fake(fake_provider())
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    use_fake(fake_provider(generate_statements=statements_payload(duplicate=(2, 5))))
    assert run("pipeline", "run", "--election", "1").exit_code == 1
    _validating_run(db_url, fake_provider())
    before = snapshot(db_url)
    assert all(before[name] for name in TABLES)

    for run_id in (1, 2, 3):
        assert report(run_id).exit_code == 0

    assert snapshot(db_url) == before


def test_help_lists_only_run(run) -> None:
    result = run("pipeline", "report", "--help")

    assert result.exit_code == 0
    options = [line.split()[0] for line in result.output.splitlines() if line.startswith("  -")]
    assert options == ["--run", "--help"]


def test_unknown_run(report, seeded, db_url) -> None:
    result = report(9)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: pipeline run 9 not found\n"


def test_missing_run_option(run, seeded) -> None:
    result = run("pipeline", "report")

    assert result.exit_code == 2
    assert "Missing option '--run'" in result.stderr


@pytest.mark.parametrize("revision", [None, "0006", "0007"], ids=["empty", "0006", "0007"])
def test_requires_current_schema(db_url: str, revision: str | None) -> None:
    if revision:
        run_migrations(db_url, revision)

    result = CliRunner().invoke(main, ["--database-url", db_url, "pipeline", "report", "--run", "1"])

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
