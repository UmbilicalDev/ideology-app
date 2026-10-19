"""Validation at the run level: ``execute_run`` / ``validate_run`` with the fake provider.

validation-evidence-quotes Scenarios 1, 2 and 6; validation-party-coverage
Scenario 4; validation-statement-separation Scenario 4;
validation-questionnaire-shape Scenario 5.
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
    statements_payload,
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

# validation-questionnaire-shape: the default fake's 30 distinct Statements over
# 18 topics pass the three checks appended after statement_separation.
SHAPE_PASSED = [
    ("statement_uniqueness", True, []),
    ("statement_count", True, []),
    ("topic_spread", True, []),
]


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
        # auto-publish-dataset-version: a passed run publishes its version.
        assert version.status is DatasetVersionStatus.PUBLISHED
        stored = s.scalars(select(ValidationResult)).all()
        assert [(r.pipeline_run_id, r.check_name, r.passed, r.entries) for r in stored] == [
            (run_id, "evidence_quotes", True, []),
            (run_id, "party_coverage", True, []),
            (run_id, "statement_separation", True, []),
            *[(run_id, *row) for row in SHAPE_PASSED],
        ]
        assert stored[0].created_at is not None
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
        ("statement_separation", True, []),
        *SHAPE_PASSED,
    ]


# Scenario 2: an invented quote fails the run with a report entry


def _invented_for_party2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2 cites an invented quote for Statement 1 only.

    Its real Statement 2 finding comes first, so the default (filling) fake
    cites the real quote on every other Statement. The invented finding keeps
    Party 2's default value (-1), so the Statements still separate the Parties.
    """
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    kept = [f for f in real["findings"] if f["statement"] != 1]
    return {"findings": [*kept, {"statement": 1, "value": -1, "quote": INVENTED, "page": 1}]}


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
        "validation_results": 6,
        "validation_report_entries": 1,
    }
    with Session(seeded) as s:
        version = s.get(DatasetVersion, 1)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        invented = s.scalars(
            select(PartyPosition).where(PartyPosition.evidence_quote == INVENTED)
        ).all()
        assert [(p.party_id, p.value, p.evidence_page) for p in invented] == [(2, -1, 1)]
    assert results(seeded, run_id) == [
        (
            "evidence_quotes",
            False,
            [(statement_id(seeded, 1), 2, "quote not found in source document 2")],
        ),
        ("party_coverage", True, []),
        ("statement_separation", True, []),
        *SHAPE_PASSED,
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
        ("statement_separation", True, []),
        *SHAPE_PASSED,
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
ONLY_PARTY1 = "does not separate parties: only party 1 has a stance (value 1)"


def statement_ids(engine: Engine) -> list[int]:
    """The run's Statement ids in position order."""
    with Session(engine) as s:
        return list(s.scalars(select(Statement.id).order_by(Statement.position)))


def only_party1_entries(engine: Engine) -> list[tuple[Any, ...]]:
    """statement_separation entries when only Party 1 has stances (value 1)."""
    return [
        (sid, None, f"statement {n} {ONLY_PARTY1}")
        for n, sid in enumerate(statement_ids(engine), start=1)
    ]


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

    # Coverage reports Party 2 once; with two Parties no Statement separates
    # them either, so separation names all 30 (double reporting is intended).
    reason = "validation failed: party_coverage, statement_separation"
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == reason
    assert outcome.failed_checks == ("party_coverage", "statement_separation")
    assert read_run(seeded, run_id).failure_reason == reason
    separation = only_party1_entries(seeded)
    assert len(separation) == 30
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", False, [(None, 2, PARTY2_ZERO)]),
        ("statement_separation", False, separation),
        *SHAPE_PASSED,
    ]
    _assert_kept_candidate(seeded)


def test_both_checks_failing_are_named(seeded: Engine) -> None:
    provider = fake_provider(
        position_findings=_invented_for_party2, party_positions=positions_response()
    )
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    # Sparse (no fill), so Statements 3..30 also fail statement_separation.
    assert outcome.failure_reason == (
        "validation failed: evidence_quotes, party_coverage, statement_separation"
    )
    assert outcome.failed_checks == ("evidence_quotes", "party_coverage", "statement_separation")
    [quotes, coverage, separation, *shape] = results(seeded, run_id)
    assert shape == SHAPE_PASSED
    assert quotes[:2] == ("evidence_quotes", False)
    assert separation[:2] == ("statement_separation", False)
    assert [e[2] for e in separation[2]] == [
        f"statement {n} does not separate parties: no party has a stance" for n in range(3, 31)
    ]
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

    # Coverage passes with the 0% threshold; Party 2 without stances still
    # leaves every Statement unseparated, which no threshold changes.
    assert outcome.failed_checks == ("statement_separation",)
    assert results(seeded, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
        ("statement_separation", False, only_party1_entries(seeded)),
        *SHAPE_PASSED,
    ]


def test_validate_run_with_explicit_settings(seeded: Engine) -> None:
    _fail_party2_document(seeded)
    run_id = validating_run(seeded)

    outcome = validate_run(seeded, run_id, settings=ValidationSettings(0))

    assert outcome.failed_checks == ("statement_separation",)
    assert results(seeded, run_id)[1] == ("party_coverage", True, [])


@pytest.mark.parametrize(
    ("raw", "failed"),
    [("0", ("statement_separation",)), ("71", ("party_coverage", "statement_separation"))],
)
def test_validate_run_reads_settings_from_env_when_none(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch, raw: str, failed: tuple[str, ...]
) -> None:
    # Party 2 without findings: party 1 covers every Statement, party 2 none,
    # so separation always fails and only coverage depends on the threshold.
    run_id = validating_run(seeded, fake_provider(position_findings=_no_findings_for_party2))
    monkeypatch.setenv("VALIDATION_MIN_PARTY_COVERAGE_PERCENT", raw)

    outcome = validate_run(seeded, run_id)

    assert outcome.failed_checks == failed


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


# validation-statement-separation Scenario 4: statement_separation at the run level

EQUAL_ON_2 = "statement 2 does not separate parties: all 2 parties with a stance have value 1"


def _party2_agrees_on_statement2(request: LLMRequest[Any]) -> dict[str, Any]:
    """Party 2's page-2 finding (Statement 2) takes value 1, equal to Party 1's.

    Its page-1 finding (value -1) stays first, so the filling fake copies -1
    to Statements 3..30, which keep separating.
    """
    real = findings_response()(request)
    if dict(chunk_pages(request)).get(1) != PAGES[2][0]:
        return real
    return {
        "findings": [
            f | {"value": 1} if f["statement"] == 2 else f for f in real["findings"]
        ]
    }


def _assert_statement2_fails_alone(engine: Engine, run_id: int, outcome: Any) -> None:
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: statement_separation"
    assert outcome.failed_checks == ("statement_separation",)
    assert read_run(engine, run_id).failure_reason == "validation failed: statement_separation"
    assert results(engine, run_id) == [
        ("evidence_quotes", True, []),
        ("party_coverage", True, []),
        ("statement_separation", False, [(statement_id(engine, 2), None, EQUAL_ON_2)]),
        *SHAPE_PASSED,
    ]
    counts = table_counts(engine)
    assert (counts["dataset_versions"], counts["statements"], counts["party_positions"]) == (
        1, 30, 60
    )
    with Session(engine) as s:
        version = s.get(DatasetVersion, 1)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        values = {
            (p.statement.position, p.party_id): p.value for p in s.scalars(select(PartyPosition))
        }
    assert (values[(2, 1)], values[(2, 2)]) == (1, 1)
    assert all(values[(n, 1)] == 1 and values[(n, 2)] == -1 for n in range(3, 31))


def test_default_fake_separates_every_statement(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    with Session(seeded) as s:
        values = {(p.statement.position, p.party_id): p.value
                  for p in s.scalars(select(PartyPosition))}
    assert all(values[(n, 1)] == 1 and values[(n, 2)] == -1 for n in range(1, 31))


def test_equal_positions_fail_the_run_naming_the_statement(seeded: Engine) -> None:
    provider = fake_provider(position_findings=_party2_agrees_on_statement2)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    _assert_statement2_fails_alone(seeded, run_id, outcome)


def test_validate_run_fails_a_validating_run_on_separation(seeded: Engine) -> None:
    run_id = validating_run(seeded, fake_provider(position_findings=_party2_agrees_on_statement2))

    outcome = validate_run(seeded, run_id)

    _assert_statement2_fails_alone(seeded, run_id, outcome)
    with pytest.raises(InvalidInputError, match="is failed, expected validating$"):
        validate_run(seeded, run_id)


# validation-questionnaire-shape Scenario 5: count, uniqueness and topic spread
# at the run level (the feature_list.json verification cases).


def _assert_shape_failure(
    engine: Engine, run_id: int, outcome: Any, payload: dict[str, Any], failed: str, entry: Any
) -> None:
    """Only ``failed`` fails, with ``entry``; the candidate version is kept as returned."""
    reason = f"validation failed: {failed}"
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == reason
    assert outcome.failed_checks == (failed,)
    assert read_run(engine, run_id).failure_reason == reason
    stored = results(engine, run_id)
    assert [name for name, _, _ in stored] == [
        "evidence_quotes",
        "party_coverage",
        "statement_separation",
        "statement_uniqueness",
        "statement_count",
        "topic_spread",
    ]
    assert [(name, entries) for name, passed, entries in stored if not passed] == [
        (failed, [entry])
    ]
    with Session(engine) as s:
        version = s.get(DatasetVersion, outcome.dataset_version_id)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        kept = s.scalars(select(Statement).order_by(Statement.position)).all()
        assert [(st.position, st.text, st.topic) for st in kept] == [
            (n, st["text"], st["topic"])
            for n, st in enumerate(payload["statements"], start=1)
        ]


def test_twenty_statements_fail_the_run_on_statement_count(seeded: Engine) -> None:
    payload = statements_payload(20)
    provider = fake_provider(generate_statements=payload)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.statement_count == 20
    _assert_shape_failure(
        seeded, run_id, outcome, payload, "statement_count",
        (None, None, "questionnaire has 20 statements; expected 25 to 35"),
    )


def test_duplicated_statement_fails_the_run_on_uniqueness(seeded: Engine) -> None:
    payload = statements_payload(duplicate=(2, 5))
    provider = fake_provider(generate_statements=payload)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.statement_count == 30
    _assert_shape_failure(
        seeded, run_id, outcome, payload, "statement_uniqueness",
        (statement_id(seeded, 5), None, "statement 5 duplicates statement 2"),
    )


def test_half_on_one_topic_fails_the_run_on_topic_spread(seeded: Engine) -> None:
    payload = statements_payload(topic=("economy", 15))
    provider = fake_provider(generate_statements=payload)
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    _assert_shape_failure(
        seeded, run_id, outcome, payload, "topic_spread",
        (None, None, "topic economy has 15 of 30 statements (50%); maximum is 30%"),
    )


def test_valid_statement_set_passes_all_six_checks(seeded: Engine) -> None:
    provider = fake_provider(generate_statements=statements_payload(25))
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    assert outcome.failed_checks == ()
    assert [(name, passed) for name, passed, _ in results(seeded, run_id)] == [
        ("evidence_quotes", True),
        ("party_coverage", True),
        ("statement_separation", True),
        ("statement_uniqueness", True),
        ("statement_count", True),
        ("topic_spread", True),
    ]


def test_execute_run_uses_the_configured_statement_range(seeded: Engine) -> None:
    provider = fake_provider(generate_statements=statements_payload(20))
    run_id = queue(seeded, provider)

    outcome = execute_run(
        seeded, run_id, provider, ValidationSettings(min_statements=20, max_statements=20)
    )

    assert outcome.status is PipelineRunStatus.PASSED


def test_validate_run_reads_statement_range_from_env(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = validating_run(seeded, fake_provider(generate_statements=statements_payload(20)))
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "20")

    outcome = validate_run(seeded, run_id)

    assert outcome.status is PipelineRunStatus.PASSED


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "abc"),
        ("VALIDATION_MIN_STATEMENTS", "0"),
        ("VALIDATION_MIN_STATEMENTS", "40"),
    ],
)
def test_execute_run_with_invalid_shape_env_changes_nothing(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch, name: str, raw: str
) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    monkeypatch.setenv(name, raw)

    with pytest.raises(ConfigError):
        execute_run(seeded, run_id, provider)

    assert read_run(seeded, run_id).status is PipelineRunStatus.QUEUED
    assert provider.calls == []
    assert table_counts(seeded)["dataset_versions"] == 0
