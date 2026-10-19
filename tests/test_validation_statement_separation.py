"""Check ``statement_separation`` on plain data, and its place in the registry.

validation-statement-separation Scenarios 1, 2 and 3. No database, LLM or network.
"""

from collections.abc import Mapping, Sequence

import pytest

from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PARTY_COVERAGE,
    STATEMENT_SEPARATION,
    PositionRow,
    ReportEntry,
    StatementRow,
    ValidationInput,
    run_checks,
)
from ideology_app.validation.statement_separation import check_statement_separation

NO = None  # no stance


def statements(count: int) -> tuple[StatementRow, ...]:
    """Statements at positions 1..count with ids 101..100+count."""
    return tuple(
        StatementRow(id=100 + n, position=n, text=f"Afirmación {n}.", topic="economy")
        for n in range(1, count + 1)
    )


def position(
    party_id: int, n: int, value: int | None, statement_id: int | None = None
) -> PositionRow:
    stance = value is not None
    return PositionRow(
        statement_id=statement_id if statement_id is not None else 100 + n,
        statement_position=n,
        party_id=party_id,
        value=value,
        document_id=party_id if stance else None,
        quote="Cita." if stance else None,
        page=1 if stance else None,
        url=None,
    )


def data(
    values: Mapping[int, Sequence[int | None]],
    party_ids: tuple[int, ...] = (1, 2),
    extra: Sequence[PositionRow] = (),
) -> ValidationInput:
    """``values[n]`` holds Statement n's value per Party, in ``party_ids`` order."""
    rows = [
        position(party_id, n, value)
        for n, row in sorted(values.items())
        for party_id, value in zip(party_ids, row, strict=True)
    ]
    return ValidationInput(
        statements=statements(len(values)),
        positions=(*rows, *extra),
        party_ids=party_ids,
    )


def entry(n: int, detail: str) -> ReportEntry:
    return ReportEntry(f"statement {n} does not separate parties: {detail}", statement_id=100 + n)


# Registry


def test_registry_runs_statement_separation_after_party_coverage() -> None:
    assert CHECKS == (EVIDENCE_QUOTES, PARTY_COVERAGE, STATEMENT_SEPARATION)
    assert STATEMENT_SEPARATION.name == "statement_separation"
    assert STATEMENT_SEPARATION.run is check_statement_separation


def test_run_checks_returns_three_results_in_order() -> None:
    results = run_checks(data({1: (1, -1), 2: (1, 1)}))
    assert [(r.name, r.passed) for r in results] == [
        ("evidence_quotes", False),  # plain data has no documents
        ("party_coverage", True),
        ("statement_separation", False),
    ]
    assert results[2].entries == (
        entry(2, "all 2 parties with a stance have value 1"),
    )


# Scenario 1: one Statement with every position equal is named


def test_one_statement_with_equal_values_is_named() -> None:
    result = STATEMENT_SEPARATION.run(data({1: (1, -1), 2: (1, 1), 3: (2, 0)}))

    assert result == [
        ReportEntry(
            "statement 2 does not separate parties: all 2 parties with a stance have value 1",
            statement_id=102,
        )
    ]
    assert result[0].party_id is None


def test_three_parties_with_one_different_value_separate() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (2, 2, -2), 2: (1, 1, -1)}, (1, 2, 3))) == []


def test_all_neutral_values_do_not_separate() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (2, 2, -2), 2: (0, 0, 0)}, (1, 2, 3))) == [
        entry(2, "all 3 parties with a stance have value 0")
    ]


def test_every_statement_separating_passes() -> None:
    assert STATEMENT_SEPARATION.run(data({n: (1, -1) for n in range(1, 31)})) == []


# Scenario 2: ``no stance`` is ignored


def test_no_stance_is_ignored_when_the_others_differ() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (1, NO, -1)}, (1, 2, 3))) == []


def test_no_stance_is_ignored_when_the_others_are_equal() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (1, NO, 1)}, (1, 2, 3))) == [
        entry(1, "all 2 parties with a stance have value 1")
    ]


def test_every_party_with_no_stance() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (1, -1), 2: (NO, NO)})) == [
        entry(2, "no party has a stance")
    ]


def test_statement_without_any_position_rows() -> None:
    rows = data({1: (1, -1)})
    no_rows = ValidationInput(statements=statements(2), positions=rows.positions, party_ids=(1, 2))
    assert STATEMENT_SEPARATION.run(no_rows) == [entry(2, "no party has a stance")]


def test_only_one_party_with_a_stance() -> None:
    assert STATEMENT_SEPARATION.run(data({1: (NO, -2, NO)}, (1, 2, 3))) == [
        entry(1, "only party 2 has a stance (value -2)")
    ]


# Scenario 3: Election-level and empty edge cases


@pytest.mark.parametrize(
    ("party_ids", "count"),
    [((1,), "1 party"), ((), "0 parties")],
    ids=["one-party", "zero-parties"],
)
def test_election_with_fewer_than_two_parties(party_ids: tuple[int, ...], count: str) -> None:
    values = {n: tuple(1 for _ in party_ids) for n in range(1, 4)}

    result = STATEMENT_SEPARATION.run(data(values, party_ids))

    assert result == [
        ReportEntry(
            f"statements cannot separate parties: the election has {count}; "
            "at least 2 are needed"
        )
    ]
    assert (result[0].statement_id, result[0].party_id) == (None, None)


@pytest.mark.parametrize("party_ids", [(), (1,), (1, 2), (1, 2, 3)])
def test_zero_statements_report_nothing(party_ids: tuple[int, ...]) -> None:
    empty = ValidationInput(statements=(), positions=(), party_ids=party_ids)
    assert STATEMENT_SEPARATION.run(empty) == []


def test_foreign_party_positions_are_ignored() -> None:
    foreign = position(9, 1, -1)
    assert STATEMENT_SEPARATION.run(data({1: (1, 1)}, extra=[foreign])) == [
        entry(1, "all 2 parties with a stance have value 1")
    ]


def test_foreign_party_alone_does_not_count_as_a_stance() -> None:
    foreign = position(9, 1, -1)
    assert STATEMENT_SEPARATION.run(data({1: (NO, 1)}, extra=[foreign])) == [
        entry(1, "only party 2 has a stance (value 1)")
    ]


def test_unknown_statement_positions_are_ignored() -> None:
    # Rows for Statement id 999 (not in the run) would separate Statement 1's
    # position number if they were counted.
    unknown = [position(1, 1, -2, statement_id=999), position(2, 1, 2, statement_id=999)]
    assert STATEMENT_SEPARATION.run(data({1: (1, 1)}, extra=unknown)) == [
        entry(1, "all 2 parties with a stance have value 1")
    ]


def test_several_offenders_in_statement_order() -> None:
    values = {1: (1, 1), 2: (1, -1), 3: (NO, NO), 4: (-2, NO), 5: (0, 1), 6: (-1, -1)}
    # Positions given out of Statement order: entries still follow ``statements``.
    shuffled = data(values)
    reordered = ValidationInput(
        statements=shuffled.statements,
        positions=tuple(reversed(shuffled.positions)),
        party_ids=shuffled.party_ids,
    )

    assert STATEMENT_SEPARATION.run(reordered) == [
        entry(1, "all 2 parties with a stance have value 1"),
        entry(3, "no party has a stance"),
        entry(4, "only party 1 has a stance (value -2)"),
        entry(6, "all 2 parties with a stance have value -1"),
    ]


def test_input_is_not_mutated_and_result_is_repeatable() -> None:
    given = data({1: (1, 1), 2: (1, -1)})
    first = STATEMENT_SEPARATION.run(given)
    assert STATEMENT_SEPARATION.run(given) == first
    assert given == data({1: (1, 1), 2: (1, -1)})
