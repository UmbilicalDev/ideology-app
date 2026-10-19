"""Check ``party_coverage`` on plain data, and its threshold configuration.

validation-party-coverage Scenarios 1, 2 and 3. No database, LLM or network.
"""

import pytest

from ideology_app.config import (
    DEFAULT_MIN_PARTY_COVERAGE_PERCENT,
    ConfigError,
    ValidationSettings,
    validation_settings,
)
from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PARTY_COVERAGE,
    PositionRow,
    ReportEntry,
    StatementRow,
    ValidationInput,
    run_checks,
)

ENV = "VALIDATION_MIN_PARTY_COVERAGE_PERCENT"


@pytest.fixture(autouse=True)
def _no_threshold_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)


def statements(count: int) -> tuple[StatementRow, ...]:
    return tuple(
        StatementRow(id=100 + n, position=n, text=f"Afirmación {n}.", topic="economy")
        for n in range(1, count + 1)
    )


def position(party_id: int, n: int, value: int | None) -> PositionRow:
    stance = value is not None
    return PositionRow(
        statement_id=100 + n,
        statement_position=n,
        party_id=party_id,
        value=value,
        document_id=party_id if stance else None,
        quote="Cita." if stance else None,
        page=1 if stance else None,
        url=None,
    )


def data(
    total: int,
    covered: dict[int, int],
    party_ids: tuple[int, ...] | None = None,
    settings: ValidationSettings | None = None,
) -> ValidationInput:
    """``total`` Statements; Party p has a stance on the first ``covered[p]``, else no stance."""
    rows = tuple(
        position(party_id, n, 1 if n <= count else None)
        for n in range(1, total + 1)
        for party_id, count in sorted(covered.items())
    )
    return ValidationInput(
        statements=statements(total),
        positions=rows,
        party_ids=party_ids if party_ids is not None else tuple(sorted(covered)),
        settings=settings or ValidationSettings(),
    )


def entry(party_id: int, covered: int, total: int, percent: int, minimum: int) -> ReportEntry:
    return ReportEntry(
        f"party {party_id} has positions on {covered} of {total} statements "
        f"({percent}%); minimum is {minimum}%",
        party_id=party_id,
    )


# Registry


def test_registry_runs_party_coverage_after_evidence_quotes() -> None:
    assert CHECKS == (EVIDENCE_QUOTES, PARTY_COVERAGE)
    assert PARTY_COVERAGE.name == "party_coverage"


# Scenario 1: boundary at the default threshold


def test_70_percent_passes_and_60_percent_fails_at_10_statements() -> None:
    result = PARTY_COVERAGE.run(data(10, {1: 7, 2: 6}))

    assert result == [entry(2, 6, 10, 60, 70)]
    assert result[0].message == (
        "party 2 has positions on 6 of 10 statements (60%); minimum is 70%"
    )
    assert result[0].statement_id is None


@pytest.mark.parametrize(
    ("covered", "expected"),
    [
        (30, []),
        (21, []),
        (20, [entry(1, 20, 30, 66, 70)]),
        (18, [entry(1, 18, 30, 60, 70)]),
    ],
    ids=["30-of-30", "21-of-30-is-70", "20-of-30-is-66", "18-of-30-is-60"],
)
def test_boundary_at_30_statements(covered: int, expected: list[ReportEntry]) -> None:
    assert PARTY_COVERAGE.run(data(30, {1: covered})) == expected


def test_default_threshold_is_70() -> None:
    assert DEFAULT_MIN_PARTY_COVERAGE_PERCENT == 70
    assert ValidationSettings().min_party_coverage_percent == 70
    assert ValidationInput(statements=(), positions=(), party_ids=()).settings == (
        ValidationSettings()
    )


def test_run_checks_reports_party_coverage() -> None:
    results = run_checks(data(10, {1: 7, 2: 6}))
    assert [(r.name, r.passed) for r in results] == [
        ("evidence_quotes", False),  # plain data has no documents
        ("party_coverage", False),
    ]
    assert results[1].entries == (entry(2, 6, 10, 60, 70),)


# Scenario 2: threshold is configurable


def test_threshold_60_passes_18_of_30() -> None:
    assert PARTY_COVERAGE.run(data(30, {1: 18}, settings=ValidationSettings(60))) == []
    assert PARTY_COVERAGE.run(data(30, {1: 17}, settings=ValidationSettings(60))) == [
        entry(1, 17, 30, 56, 60)
    ]


def test_threshold_100_fails_29_of_30() -> None:
    settings = ValidationSettings(100)
    assert PARTY_COVERAGE.run(data(30, {1: 29}, settings=settings)) == [
        entry(1, 29, 30, 96, 100)
    ]
    assert PARTY_COVERAGE.run(data(30, {1: 30}, settings=settings)) == []


def test_threshold_0_passes_a_party_without_stances() -> None:
    assert PARTY_COVERAGE.run(data(30, {1: 0}, settings=ValidationSettings(0))) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 70), ("", 70), ("   ", 70), (" 55 ", 55), ("0", 0), ("100", 100), ("70", 70)],
)
def test_validation_settings_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: int
) -> None:
    if raw is not None:
        monkeypatch.setenv(ENV, raw)
    assert validation_settings() == ValidationSettings(expected)


@pytest.mark.parametrize("raw", ["0.7", "70%", "-1", "101", "abc", "+5", "٧٠"])
def test_invalid_env_values_raise_config_error(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv(ENV, raw)
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == (
        f"Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT {raw!r}; "
        "expected an integer from 0 to 100"
    )


@pytest.mark.parametrize("value", [-1, 101, 70.0, "70", True, None])
def test_validation_settings_rejects_bad_values(value: object) -> None:
    with pytest.raises(ValueError, match="integer from 0 to 100"):
        ValidationSettings(value)  # type: ignore[arg-type]


# Scenario 3: edge cases


def test_party_without_rows_or_only_no_stance_has_zero_coverage() -> None:
    only_no_stance = data(30, {1: 21, 2: 0})
    assert PARTY_COVERAGE.run(only_no_stance) == [entry(2, 0, 30, 0, 70)]
    no_rows = data(30, {1: 21}, party_ids=(1, 2))
    assert PARTY_COVERAGE.run(no_rows) == [entry(2, 0, 30, 0, 70)]
    assert PARTY_COVERAGE.run(no_rows)[0].message == (
        "party 2 has positions on 0 of 30 statements (0%); minimum is 70%"
    )


def test_several_offending_parties_are_reported_in_party_id_order() -> None:
    result = PARTY_COVERAGE.run(data(10, {1: 7, 2: 3, 5: 0, 9: 6}))
    assert result == [entry(2, 3, 10, 30, 70), entry(5, 0, 10, 0, 70), entry(9, 6, 10, 60, 70)]


def test_positions_of_parties_not_in_the_election_are_ignored() -> None:
    mixed = data(10, {1: 7, 2: 10}, party_ids=(1,))
    assert PARTY_COVERAGE.run(mixed) == []
    foreign_only = data(10, {1: 0, 7: 10}, party_ids=(1,))
    assert PARTY_COVERAGE.run(foreign_only) == [entry(1, 0, 10, 0, 70)]


def test_zero_statements_report_nothing() -> None:
    empty = ValidationInput(statements=(), positions=(), party_ids=(1, 2))
    assert PARTY_COVERAGE.run(empty) == []


def test_zero_parties_report_nothing() -> None:
    assert PARTY_COVERAGE.run(data(10, {}, party_ids=())) == []


def test_negative_and_zero_values_count_as_stances() -> None:
    rows = tuple(
        position(1, n, (-2, 0, 2)[n % 3] if n <= 7 else None) for n in range(1, 11)
    )
    covered = ValidationInput(statements=statements(10), positions=rows, party_ids=(1,))
    assert PARTY_COVERAGE.run(covered) == []
