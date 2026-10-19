"""Validation at the run level: ``execute_run`` / ``validate_run`` with the fake provider.

validation-evidence-quotes Scenarios 1, 2 and 6; validation-party-coverage
Scenario 4.
"""

from typing import Any

import pytest
from pipeline_fixtures import (
    PAGES,
    chunk_pages,
    fake_provider,
    findings_response,
    offline_guard,
    positions_response,
    seed_election,
)
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from ideology_app.config import ConfigError, GenerationMode, ValidationSettings
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError
from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    PartyPosition,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentStatus,
    Statement,
    ValidationReportEntry,
    ValidationResult,
)
from ideology_app.pipeline import (
    INTERRUPTED_REASON,
    execute_run,
    list_validation_results,
    queue_run,
    validate_run,
)
from ideology_app.pipeline import runs as runs_module
from ideology_app.validation import Check, ReportEntry, ValidationInput

INVENTED = "Bajaremos el IVA de los libros al cero por ciento."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    seed_election(migrated_engine)
    return migrated_engine


def queue(engine: Engine, provider: FakeProvider) -> int:
    with session_scope(engine) as session:
        run = queue_run(
            session,
            1,
            llm_provider=provider.name,
            llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        )
        return run.id


def validating_run(engine: Engine, provider: FakeProvider | None = None) -> int:
    """A run left in ``validating``, as before this feature or after a crash."""
    provider = provider or fake_provider()
    run_id = queue(engine, provider)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
        execute_run(engine, run_id, provider)
    assert read_run(engine, run_id).status is PipelineRunStatus.VALIDATING
    return run_id


def read_run(engine: Engine, run_id: int) -> PipelineRun:
    with Session(engine, expire_on_commit=False) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        s.expunge(run)
        return run


def results(engine: Engine, run_id: int) -> list[tuple[str, bool, list[tuple[Any, ...]]]]:
    with Session(engine) as s:
        return [
            (
                r.check_name,
                r.passed,
                [(e.statement_id, e.party_id, e.message) for e in r.entries],
            )
            for r in list_validation_results(s, run_id)
        ]


def table_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as s:
        return {
            model.__tablename__: s.scalar(select(func.count()).select_from(model)) or 0
            for model in (
                DatasetVersion,
                Statement,
                PartyPosition,
                ValidationResult,
                ValidationReportEntry,
            )
        }


def statement_id(engine: Engine, position: int) -> int:
    with Session(engine) as s:
        found = s.scalar(select(Statement.id).where(Statement.position == position))
        assert found is not None
        return found


# Scenario 1: real quotes pass


def test_real_quotes_pass(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    assert outcome.failure_reason is None
    assert outcome.failed_checks == ()
    assert (outcome.dataset_version_id, outcome.statement_count, outcome.position_count) == (
        1, 30, 60
    )
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.PASSED
    assert run.failure_reason is None
    with Session(seeded) as s:
        version = s.get(DatasetVersion, outcome.dataset_version_id)
        assert version is not None
        assert version.status is DatasetVersionStatus.CANDIDATE
        stored = s.scalars(select(ValidationResult)).all()
        assert [(r.pipeline_run_id, r.check_name, r.passed, r.entries) for r in stored] == [
            (run_id, "evidence_quotes", True, []),
            (run_id, "party_coverage", True, []),
        ]
        assert stored[0].created_at is not None
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
    ]


# Scenario 2: an invented quote fails the run with a report entry


def _invented_for_party2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2 cites an invented quote for Statement 1 only.

    Its real Statement 2 finding comes first, so the default (filling) fake
    cites the real quote on every other Statement.
    """
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    kept = [f for f in real["findings"] if f["statement"] != 1]
    return {"findings": [*kept, {"statement": 1, "value": 1, "quote": INVENTED, "page": 1}]}


def test_invented_quote_fails_the_run_with_one_entry(seeded: Engine) -> None:
    provider = fake_provider(position_findings=_invented_for_party2)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: evidence_quotes"
    assert outcome.failed_checks == ("evidence_quotes",)
    assert (outcome.dataset_version_id, outcome.statement_count, outcome.position_count) == (
        1, 30, 60
    )
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == "validation failed: evidence_quotes"
    # The Dataset Version, its Statements and Party Positions are kept unchanged.
    assert table_counts(seeded) == {
        "dataset_versions": 1,
        "statements": 30,
        "party_positions": 60,
        "validation_results": 2,
        "validation_report_entries": 1,
    }
    with Session(seeded) as s:
        version = s.get(DatasetVersion, 1)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        invented = s.scalars(
            select(PartyPosition).where(PartyPosition.evidence_quote == INVENTED)
        ).all()
        assert [(p.party_id, p.value, p.evidence_page) for p in invented] == [(2, 1, 1)]
    assert results(seeded, run_id) == [
        (
            "evidence_quotes",
            False,
            [(statement_id(seeded, 1), 2, "quote not found in source document 2")],
        ),
        ("party_coverage", True, []),
    ]


def test_list_validation_results_unknown_run(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        with pytest.raises(NotFoundError, match="^pipeline run 9 not found$"):
            list_validation_results(s, 9)


# Scenario 6: registry behaviour

calls: list[str] = []


def _passing(data: ValidationInput) -> list[ReportEntry]:
    calls.append("passing_stub")
    return []


def _failing(data: ValidationInput) -> list[ReportEntry]:
    calls.append("failing_stub")
    first = data.positions[0]
    return [
        ReportEntry("second problem", first.statement_id, first.party_id),
        ReportEntry("run-level problem"),
    ]


PASSING = Check("passing_stub", _passing)
FAILING = Check("failing_stub", _failing)


@pytest.fixture(autouse=True)
def _reset_calls() -> None:
    calls.clear()


def test_every_check_runs_in_order_without_short_circuit(seeded: Engine) -> None:
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id, checks=(FAILING, PASSING))

    assert calls == ["failing_stub", "passing_stub"]
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: failing_stub"
    assert outcome.failed_checks == ("failing_stub",)
    assert read_run(seeded, run_id).failure_reason == "validation failed: failing_stub"
    first = statement_id(seeded, 1)
    assert results(seeded, run_id) == [
        (
            "failing_stub",
            False,
            [(first, 1, "second problem"), (None, None, "run-level problem")],
        ),
        ("passing_stub", True, []),
    ]


def test_several_failed_checks_are_all_named(seeded: Engine) -> None:
    other = Check("other_failing_stub", lambda data: [ReportEntry("x")])
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id, checks=(FAILING, PASSING, other))

    assert outcome.failure_reason == "validation failed: failing_stub, other_failing_stub"
    assert outcome.failed_checks == ("failing_stub", "other_failing_stub")


def test_all_passing_checks_pass_the_run(seeded: Engine) -> None:
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id, checks=(PASSING,))

    assert outcome.status is PipelineRunStatus.PASSED
    assert (outcome.dataset_version_id, outcome.statement_count, outcome.position_count) == (
        1, 30, 60
    )
    assert results(seeded, run_id) == [("passing_stub", True, [])]


def test_default_checks_pass_a_validating_run(seeded: Engine) -> None:
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id)

    assert outcome.status is PipelineRunStatus.PASSED
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
    ]


def test_long_entry_messages_are_cut(seeded: Engine) -> None:
    long = Check("long_stub", lambda data: [ReportEntry("x" * 600)])
    run_id = validating_run(seeded)

    validate_run(seeded, run_id, checks=(long,))

    assert results(seeded, run_id) == [("long_stub", False, [(None, None, "x" * 500)])]


def _crash(data: ValidationInput) -> list[ReportEntry]:
    raise KeyError("boom")


def _interrupt(data: ValidationInput) -> list[ReportEntry]:
    raise KeyboardInterrupt


@pytest.mark.parametrize(
    ("raising", "exc", "reason"),
    [
        (_crash, KeyError, "unexpected error: KeyError"),
        (_interrupt, KeyboardInterrupt, INTERRUPTED_REASON),
    ],
    ids=["error", "interrupt"],
)
def test_a_raising_check_fails_the_run_stores_nothing_and_reraises(
    seeded: Engine, raising: Any, exc: type[BaseException], reason: str
) -> None:
    run_id = validating_run(seeded)

    with pytest.raises(exc):
        validate_run(seeded, run_id, checks=(PASSING, Check("raising_stub", raising)))

    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == reason
    assert results(seeded, run_id) == []
    assert table_counts(seeded)["dataset_versions"] == 1


def test_a_check_raising_inside_execute_run_is_recorded_once(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "run_checks", lambda data, checks: _crash(data))
    provider = fake_provider()
    run_id = queue(seeded, provider)

    with pytest.raises(KeyError):
        execute_run(seeded, run_id, provider)

    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == "unexpected error: KeyError"
    assert run.llm_calls == 7
    assert table_counts(seeded)["dataset_versions"] == 1


@pytest.mark.parametrize("status", ["passed", "failed"])
def test_validate_run_rejects_a_run_that_is_not_validating(seeded: Engine, status: str) -> None:
    provider = fake_provider(
        position_findings=findings_response() if status == "passed" else _invented_for_party2
    )
    run_id = queue(seeded, provider)
    execute_run(seeded, run_id, provider)
    before = results(seeded, run_id)

    with pytest.raises(
        InvalidInputError, match=f"^pipeline run {run_id} is {status}, expected validating$"
    ):
        validate_run(seeded, run_id, checks=(PASSING,))

    assert calls == []
    assert read_run(seeded, run_id).status.value == status
    assert results(seeded, run_id) == before


def test_validate_run_rejects_a_queued_run(seeded: Engine) -> None:
    run_id = queue(seeded, fake_provider())
    with pytest.raises(InvalidInputError, match="is queued, expected validating$"):
        validate_run(seeded, run_id)
    assert read_run(seeded, run_id).status is PipelineRunStatus.QUEUED


def test_validate_run_unknown_run(migrated_engine: Engine) -> None:
    with pytest.raises(NotFoundError, match="^pipeline run 5 not found$"):
        validate_run(migrated_engine, 5)


# validation-party-coverage Scenario 4: party_coverage at the run level

PARTY2_ZERO = "party 2 has positions on 0 of 30 statements (0%); minimum is 70%"


def _no_findings_for_party2(request: LLMRequest[Any]) -> dict[str, Any]:
    if dict(chunk_pages(request)).get(1) == PAGES[2][0]:
        return {"findings": []}
    return findings_response()(request)


def _fail_party2_document(engine: Engine) -> None:
    with session_scope(engine) as s:
        s.execute(
            update(SourceDocument)
            .where(SourceDocument.id == 2)
            .values(status=SourceDocumentStatus.FAILED)
        )


def _assert_kept_candidate(engine: Engine) -> None:
    assert table_counts(engine)["party_positions"] == 60
    with Session(engine) as s:
        version = s.get(DatasetVersion, 1)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        party2 = s.scalars(select(PartyPosition).where(PartyPosition.party_id == 2)).all()
        assert len(party2) == 30 and all(p.value is None for p in party2)


@pytest.mark.parametrize("cause", ["no-document", "no-findings"])
def test_party_with_no_stance_fails_the_run_on_coverage(seeded: Engine, cause: str) -> None:
    if cause == "no-document":
        _fail_party2_document(seeded)
        provider = fake_provider()
    else:
        provider = fake_provider(position_findings=_no_findings_for_party2)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: party_coverage"
    assert outcome.failed_checks == ("party_coverage",)
    assert read_run(seeded, run_id).failure_reason == "validation failed: party_coverage"
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", False, [(None, 2, PARTY2_ZERO)]),
    ]
    _assert_kept_candidate(seeded)


def test_both_checks_failing_are_named(seeded: Engine) -> None:
    provider = fake_provider(
        position_findings=_invented_for_party2, party_positions=positions_response()
    )
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.failure_reason == "validation failed: evidence_quotes, party_coverage"
    assert outcome.failed_checks == ("evidence_quotes", "party_coverage")
    [quotes, coverage] = results(seeded, run_id)
    assert quotes[:2] == ("evidence_quotes", False)
    assert coverage == (
        "party_coverage",
        False,
        [
            (None, 1, "party 1 has positions on 2 of 30 statements (6%); minimum is 70%"),
            (None, 2, "party 2 has positions on 2 of 30 statements (6%); minimum is 70%"),
        ],
    )


def test_execute_run_passes_its_validation_settings(seeded: Engine) -> None:
    _fail_party2_document(seeded)
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider, ValidationSettings(0))

    assert outcome.status is PipelineRunStatus.PASSED
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
    ]


def test_validate_run_with_explicit_settings(seeded: Engine) -> None:
    _fail_party2_document(seeded)
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id, settings=ValidationSettings(0))

    assert outcome.status is PipelineRunStatus.PASSED
    assert results(seeded, run_id)[1] == ("party_coverage", True, [])


@pytest.mark.parametrize(("raw", "status"), [("0", "passed"), ("71", "failed")])
def test_validate_run_reads_settings_from_env_when_none(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch, raw: str, status: str
) -> None:
    # Party 2 without findings: party 1 covers every Statement, party 2 none.
    run_id = validating_run(seeded, fake_provider(position_findings=_no_findings_for_party2))
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", raw)

    outcome = validate_run(seeded, run_id)

    assert outcome.status.value == status


def test_validate_run_with_invalid_env_changes_nothing(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = validating_run(seeded)
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "70%")
    before = table_counts(seeded)

    with pytest.raises(ConfigError, match="^Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT"):
        validate_run(seeded, run_id)

    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.VALIDATING
    assert run.failure_reason is None
    assert results(seeded, run_id) == []
    assert table_counts(seeded) == before


def test_execute_run_with_invalid_env_changes_nothing(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", "abc")

    with pytest.raises(ConfigError):
        execute_run(seeded, run_id, provider)

    assert read_run(seeded, run_id).status is PipelineRunStatus.QUEUED
    assert provider.calls == []
    assert table_counts(seeded)["dataset_versions"] == 0
