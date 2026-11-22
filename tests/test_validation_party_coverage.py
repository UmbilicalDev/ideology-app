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


def entry(
    party_id: int, covered: int, total: int, percent: int, minimum: int, prefix: int | None = None
) -> ReportEntry:
    start = "" if prefix is None else f"first {prefix} statements: "
    return ReportEntry(
        f"{start}party {party_id} is in favour or against on {covered} of {total} statements "
        f"({percent}%); minimum is {minimum}%",
        party_id=party_id,
    )


# Registry


def test_registry_runs_party_coverage_after_evidence_quotes() -> None:
    # Later checks are appended after it (domain check order).
    assert CHECKS[:2] == (EVIDENCE_QUOTES, PARTY_COVERAGE)
    assert PARTY_COVERAGE.name == "party_coverage"


# Scenario 1: boundary at the default threshold (50 since pipeline-verified-findings)


def test_50_percent_passes_and_40_percent_fails_at_10_statements() -> None:
    result = PARTY_COVERAGE.run(data(10, {1: 5, 2: 4}))

    assert result == [entry(2, 4, 10, 40, 50)]
    assert result[0].message == (
        "party 2 is in favour or against on 4 of 10 statements (40%); minimum is 50%"
    )
    assert result[0].statement_id is None


@pytest.mark.parametrize(
    ("covered", "expected"),
    [
        (30, []),
        (15, []),
        (14, [entry(1, 14, 30, 46, 50)]),
        (12, [entry(1, 12, 30, 40, 50)]),
    ],
    ids=["30-of-30", "15-of-30-is-50", "14-of-30-is-46", "12-of-30-is-40"],
)
def test_boundary_at_30_statements(covered: int, expected: list[ReportEntry]) -> None:
    assert PARTY_COVERAGE.run(data(30, {1: covered})) == expected


def test_default_threshold_is_50() -> None:
    # pipeline-balanced-statements lowered it from 70 to 60, and
    # pipeline-verified-findings from 60 to 50 (user decisions 2026-10-22).
    assert DEFAULT_MIN_PARTY_COVERAGE_PERCENT == 50
    assert ValidationSettings().min_party_coverage_percent == 50
    assert ValidationInput(statements=(), positions=(), party_ids=()).settings == (
        ValidationSettings()
    )


@pytest.mark.parametrize(
    ("covered", "expected"),
    [(21, []), (20, [entry(1, 20, 30, 66, 70)]), (18, [entry(1, 18, 30, 60, 70)])],
    ids=["21-of-30-is-70", "20-of-30-is-66", "18-of-30-is-60"],
)
def test_explicit_threshold_70_keeps_its_boundary(
    covered: int, expected: list[ReportEntry]
) -> None:
    settings = ValidationSettings(70)
    assert PARTY_COVERAGE.run(data(30, {1: covered}, settings=settings)) == expected


def test_run_checks_reports_party_coverage() -> None:
    results = run_checks(data(10, {1: 5, 2: 4}), CHECKS[:3])
    assert [(r.name, r.passed) for r in results] == [
        ("evidence_quotes", False),  # plain data has no documents
        ("party_coverage", False),
        ("statement_separation", False),  # every plain-data value is 1
    ]
    assert results[1].entries == (entry(2, 4, 10, 40, 50),)


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
    [(None, 50), ("", 50), ("   ", 50), (" 55 ", 55), ("0", 0), ("100", 100), ("70", 70)],
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
    assert PARTY_COVERAGE.run(only_no_stance) == [entry(2, 0, 30, 0, 50)]
    no_rows = data(30, {1: 21}, party_ids=(1, 2))
    assert PARTY_COVERAGE.run(no_rows) == [entry(2, 0, 30, 0, 50)]
    assert PARTY_COVERAGE.run(no_rows)[0].message == (
        "party 2 is in favour or against on 0 of 30 statements (0%); minimum is 50%"
    )


def test_several_offending_parties_are_reported_in_party_id_order() -> None:
    result = PARTY_COVERAGE.run(data(10, {1: 7, 2: 3, 5: 0, 9: 4}))
    assert result == [entry(2, 3, 10, 30, 50), entry(5, 0, 10, 0, 50), entry(9, 4, 10, 40, 50)]


def test_positions_of_parties_not_in_the_election_are_ignored() -> None:
    mixed = data(10, {1: 7, 2: 10}, party_ids=(1,))
    assert PARTY_COVERAGE.run(mixed) == []
    foreign_only = data(10, {1: 0, 7: 10}, party_ids=(1,))
    assert PARTY_COVERAGE.run(foreign_only) == [entry(1, 0, 10, 0, 50)]


def test_zero_statements_report_nothing() -> None:
    empty = ValidationInput(statements=(), positions=(), party_ids=(1, 2))
    assert PARTY_COVERAGE.run(empty) == []


def test_zero_parties_report_nothing() -> None:
    assert PARTY_COVERAGE.run(data(10, {}, party_ids=())) == []


def test_negative_values_count_and_zero_does_not() -> None:
    # pipeline-statement-priority-tiers: only +1/+2 and -1/-2 count (Settled Decision 4).
    rows = tuple(
        position(1, n, (-2, -1, 1, 2, 0)[n % 5] if n <= 10 else None) for n in range(1, 11)
    )
    data_ = ValidationInput(statements=statements(10), positions=rows, party_ids=(1,))
    # n = 1..10: values -1, 1, 2, 0, -2, -1, 1, 2, 0, -2 -> 8 sided, 2 zero.
    assert PARTY_COVERAGE.run(data_) == []
    zeros = tuple(position(1, n, 0 if n <= 6 else (1 if n <= 9 else None)) for n in range(1, 11))
    only_zero = ValidationInput(statements=statements(10), positions=zeros, party_ids=(1,))
    assert PARTY_COVERAGE.run(only_zero) == [entry(1, 3, 10, 30, 50)]


# pipeline-statement-priority-tiers, scenario 5: every offered length (prefix).


def sided_on(total: int, sides: dict[int, tuple[int, ...]], lengths: tuple[int, ...]) -> ValidationInput:
    """Party p has value +1 on the Statement positions ``sides[p]``, else no stance."""
    rows = tuple(
        position(party_id, n, 1 if n in on else None)
        for n in range(1, total + 1)
        for party_id, on in sorted(sides.items())
    )
    return ValidationInput(
        statements=statements(total),
        positions=rows,
        party_ids=tuple(sorted(sides)),
        settings=ValidationSettings(questionnaire_lengths=()),
        lengths=lengths,
    )


def test_each_offered_length_is_checked_on_its_prefix() -> None:
    # Party 3 is sided on 7 of the first 15, 15 of the first 30 and 17 of 40.
    on = tuple(range(1, 8)) + tuple(range(16, 24)) + (31, 32)
    full = tuple(range(1, 41))
    data_ = sided_on(40, {1: full, 3: on}, (15, 30, 40))
    result = PARTY_COVERAGE.run(data_)
    assert result == [entry(3, 7, 15, 46, 50, prefix=15), entry(3, 17, 40, 42, 50)]
    assert result[0].message == (
        "first 15 statements: party 3 is in favour or against on 7 of 15 statements (46%); "
        "minimum is 50%"
    )
    assert result[1].message == (
        "party 3 is in favour or against on 17 of 40 statements (42%); minimum is 50%"
    )


def test_entries_are_ordered_by_length_then_party() -> None:
    data_ = sided_on(40, {1: (), 2: tuple(range(1, 41)), 4: ()}, (15, 30, 40))
    assert PARTY_COVERAGE.run(data_) == [
        entry(1, 0, 15, 0, 50, prefix=15),
        entry(4, 0, 15, 0, 50, prefix=15),
        entry(1, 0, 30, 0, 50, prefix=30),
        entry(4, 0, 30, 0, 50, prefix=30),
        entry(1, 0, 40, 0, 50),
        entry(4, 0, 40, 0, 50),
    ]


def test_a_party_sided_only_after_the_first_15_fails_only_the_15_prefix() -> None:
    data_ = sided_on(40, {1: tuple(range(16, 41))}, (15, 30, 40))
    assert PARTY_COVERAGE.run(data_) == [entry(1, 0, 15, 0, 50, prefix=15)]


def test_no_stored_lengths_check_only_the_full_set() -> None:
    data_ = sided_on(40, {1: tuple(range(16, 41))}, ())
    assert PARTY_COVERAGE.run(data_) == []
