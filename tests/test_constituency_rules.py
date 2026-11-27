"""``constituency_rules``: S5, K1 validity, K2 order, K5 availability, K10 lengths.

constituency-selection-validation scenarios 2-5 and 7 (the pure part). Plain
data only: no database, no provider.
"""

import random
from collections.abc import Mapping, Sequence

import pytest

from ideology_app.constituency_rules import (
    OFFERED_LENGTHS,
    Availability,
    RuleStatement,
    Stance,
    UnavailableReason,
    availability,
    counting_evidence,
    effective_value,
    evaluate,
    is_valid,
    offered_lengths,
    priority_order,
    topic_caps,
    valid_statements,
)


def statement(
    key: int,
    values: Mapping[int, int | None],
    topic: str = "housing",
    codes: Mapping[int, Sequence[str]] | None = None,
    position: int | None = None,
) -> RuleStatement:
    """A Statement where each Party's Evidence counts in ``codes[party]`` (default: 28 and 31)."""
    codes = codes or {}
    return RuleStatement(
        key=key,
        position=key if position is None else position,
        topic=topic,
        stances={
            party: Stance(value, () if value is None else (tuple(codes.get(party, ("28", "31"))),))
            for party, value in values.items()
        },
    )


OTHER = ("economy", "health", "education")


def evaluate_default(code: str, statements: Sequence[RuleStatement], parties: Sequence[int]):
    return evaluate(
        code, statements, parties, min_statements=10, min_party_sides=5, max_topic_share_percent=30
    )


# --- S5 -------------------------------------------------------------------------------


def test_effective_value_needs_evidence_counting_in_the_constituency() -> None:
    assert effective_value(2, [("28",), ("31", "08")], "31") == 2
    assert effective_value(-1, [("28",)], "28") == -1
    assert effective_value(0, [("28",)], "28") == 0
    assert effective_value(2, [("28",)], "31") is None
    assert effective_value(2, [], "28") is None
    assert effective_value(None, [("28",)], "28") is None


def test_counting_evidence_lists_the_rows_that_count_in_rank_order() -> None:
    # public-dataset-api-v2 A6: the Evidence a reader shows in a Constituency.
    rows = [("28",), ("08", "31"), ("28", "31")]
    assert counting_evidence(rows, "28") == (0, 2)
    assert counting_evidence(rows, "31") == (1, 2)
    assert counting_evidence(rows, "08") == (1,)
    assert counting_evidence(rows, "01") == ()
    assert counting_evidence([], "28") == ()
    assert counting_evidence(iter([["28"], []]), "28") == (0,)


@pytest.mark.parametrize("value", [None, -2, -1, 0, 1, 2])
def test_effective_value_is_the_value_exactly_when_some_evidence_counts(
    value: int | None,
) -> None:
    # effective_value behaves as before: the value when any row counts, else None.
    for rows in ([], [("28",)], [("31",)], [("31",), ("28", "08")], [(), ()]):
        for code in ("28", "31", "08", "01"):
            before = None if value is None else next(
                (value for codes in rows if code in codes), None
            )
            assert effective_value(value, rows, code) == before
            assert (effective_value(value, rows, code) is None) == (
                value is None or not counting_evidence(rows, code)
            )


def test_s5_evidence_only_in_28_is_no_stance_in_31() -> None:
    # Scenario 2: Party 2's only Evidence counts in 28, so in 31 it is no stance and
    # nothing is against there; Party 3 is in favour everywhere.
    s = statement(1, {1: 1, 2: -2, 3: 2}, codes={2: ("28",)})
    assert is_valid(s, (1, 2, 3), "28")
    assert not is_valid(s, (1, 2, 3), "31")
    assert valid_statements([s], (1, 2, 3), "31") == ()


# --- K1 -------------------------------------------------------------------------------


def test_validity_needs_one_side_each_among_the_running_parties() -> None:
    s = statement(1, {1: 2, 2: -1, 3: 0, 4: None})
    assert is_valid(s, (1, 2), "28")
    assert not is_valid(s, (1, 3, 4), "28")  # 0 and no stance are on neither side
    assert not is_valid(s, (2, 3), "28")
    assert valid_statements([s], (1,), "28") == ()  # fewer than two Parties
    # Only Parties running there count: Party 2 against does not help where it does not run.
    assert valid_statements([s], (1, 3), "28") == ()
    # Two Parties are enough (no legacy "at least 3 Parties" rule).
    assert [v.key for v in valid_statements([s], (1, 2), "28")] == [1]


# --- K2 -------------------------------------------------------------------------------


def test_order_by_sided_then_separation_then_pool_position() -> None:
    parties = (1, 2, 3, 4)
    statements = [
        statement(1, {1: 1, 2: -1}),  # sided 2, separation 1
        statement(2, {1: 1, 2: -1, 3: 1, 4: 1}),  # sided 4, separation 1
        statement(3, {1: 1, 2: -1, 3: -1, 4: 1}),  # sided 4, separation 2
        statement(4, {1: 1, 2: -1}),  # ties with 1: pool order
        statement(5, {1: 1, 2: 1}),  # not valid
        statement(6, {1: 2, 2: -2, 3: 1}),  # sided 3, separation 1
    ]
    assert priority_order(statements, parties, "28", 30) == (3, 2, 6, 1, 4)


def test_equal_keys_follow_pool_position_not_key() -> None:
    statements = [
        statement(10, {1: 1, 2: -1}, position=3),
        statement(11, {1: 1, 2: -1}, position=1),
        statement(12, {1: 1, 2: -1}, position=2),
    ]
    assert priority_order(statements, (1, 2), "28", 30) == (11, 12, 10)


def test_topic_deferral_moves_the_excess_after_20_and_drops_nothing() -> None:
    # Scenario 3: 10 housing Statements rank first (4 sided), then 15 of three other
    # topics (2 sided). cap(20) = 6 for every topic.
    housing = [statement(k, {1: 1, 2: -1, 3: 1, 4: -1}, "housing") for k in range(1, 11)]
    others = [statement(k, {1: 1, 2: -1}, OTHER[k % 3]) for k in range(11, 26)]
    order = priority_order(housing + others, (1, 2, 3, 4), "28", 30)
    assert topic_caps(25, 30) == ((20, 6),)
    assert len(order) == 25 and sorted(order) == list(range(1, 26))
    first_20 = order[:20]
    assert sum(k <= 10 for k in first_20) == 6
    # The six housing Statements come first (cap not reached), then the others fill up.
    assert order[:6] == (1, 2, 3, 4, 5, 6)
    assert order[6:20] == tuple(range(11, 25))
    assert order[20:] == (7, 8, 9, 10, 25)


def test_no_deferral_when_n_is_an_offered_length_or_below() -> None:
    housing = [statement(k, {1: 1, 2: -1, 3: 1}, "housing") for k in range(1, 16)]
    economy = [statement(k, {1: 1, 2: -1}, "economy") for k in range(16, 21)]
    assert topic_caps(20, 30) == ()
    assert priority_order(housing + economy, (1, 2, 3), "28", 30) == tuple(range(1, 21))


def test_deferral_uses_the_cap_of_the_first_length_at_or_above_k() -> None:
    # n = 41: lengths 20, 30 and 40 (caps 6, 9 and 12). Ranks 21..30 allow 9 per topic.
    housing = [statement(k, {1: 1, 2: -1, 3: 1}, "housing") for k in range(1, 21)]
    topics = [f"topic{i}" for i in range(7)]
    others = [statement(k, {1: 1, 2: -1}, topics[k % 7]) for k in range(21, 42)]
    order = priority_order(housing + others, (1, 2, 3), "28", 30)
    assert topic_caps(41, 30) == ((20, 6), (30, 9), (40, 12))
    assert sum(k <= 20 for k in order[:20]) == 6
    assert sum(k <= 20 for k in order[:30]) == 9
    assert sum(k <= 20 for k in order[:40]) == 19  # 12 by the cap, then the fallback
    assert sorted(order) == list(range(1, 42))


def test_deferral_takes_the_first_remaining_when_no_topic_fits() -> None:
    # Two topics, cap(20) = 6 each: after 6 + 6 nothing fits, so rank order resumes.
    housing = [statement(k, {1: 1, 2: -1, 3: 1}, "housing") for k in range(1, 11)]
    economy = [statement(k, {1: 1, 2: -1}, "economy") for k in range(11, 26)]
    assert priority_order(housing + economy, (1, 2, 3), "28", 30) == (
        1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16, 7, 8, 9, 10, *range(17, 26),
    )


def test_deferral_falls_back_to_the_first_remaining_statement() -> None:
    # Only one topic: nothing fits the cap, so the ranking order is kept.
    same = [statement(k, {1: 1, 2: -1}, "housing") for k in range(1, 26)]
    assert priority_order(same, (1, 2), "28", 30) == tuple(range(1, 26))


# --- K10 and K5 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "lengths"),
    [(0, ()), (1, (1,)), (12, (12,)), (19, (19,)), (20, (20,)), (29, (20,)),
     (37, (20, 30)), (50, (20, 30, 40, 50)), (55, (20, 30, 40, 50))],
)
def test_offered_lengths(n: int, lengths: tuple[int, ...]) -> None:
    assert OFFERED_LENGTHS == (20, 30, 40, 50)
    assert offered_lengths(n) == lengths


def _separating(n: int) -> list[RuleStatement]:
    return [statement(k, {1: 1, 2: -1}, "housing" if k % 2 else "economy") for k in range(1, n + 1)]


@pytest.mark.parametrize(
    ("n", "available", "lengths"),
    [(9, False, ()), (12, True, (12,)), (20, True, (20,)), (37, True, (20, 30)),
     (55, True, (20, 30, 40, 50))],
)
def test_scenario_4_lengths_with_default_minimums(
    n: int, available: bool, lengths: tuple[int, ...]
) -> None:
    result = evaluate_default("28", _separating(n), (1, 2))
    assert result.availability.available is available
    assert result.lengths == lengths
    assert len(result.valid) == n
    if not available:
        assert result.availability == Availability(
            False, UnavailableReason.TOO_FEW_STATEMENTS, {"statements": 9, "minimum": 10}
        )
        assert result.ordered == ()


def test_low_party_coverage_names_the_party() -> None:
    # Scenario 5: Party 3 takes a side on 4 of the 12 valid Statements.
    statements = [
        statement(k, {1: 1, 2: -1, 3: 1 if k <= 4 else None}) for k in range(1, 13)
    ]
    result = evaluate_default("28", statements, (3, 1, 2))
    assert result.parties == (1, 2, 3)
    assert result.sides == ((1, 12), (2, 12), (3, 4))
    assert result.availability == Availability(
        False,
        UnavailableReason.LOW_PARTY_COVERAGE,
        {"parties": [{"party_id": 3, "sides": 4}], "minimum": 5},
    )
    assert result.lengths == () and result.ordered == ()
    assert len(result.valid) == 12


def test_reasons_follow_the_rule_order() -> None:
    assert availability(1, 0, [(1, 0)], 10, 5) == Availability(
        False, UnavailableReason.FEWER_THAN_TWO_PARTIES, {"parties": 1}
    )
    assert availability(0, 0, [], 10, 5).detail == {"parties": 0}
    # Too few Statements wins over low coverage.
    assert availability(3, 4, [(1, 0), (2, 4), (3, 4)], 10, 5).reason is (
        UnavailableReason.TOO_FEW_STATEMENTS
    )
    assert availability(2, 10, [(1, 5), (2, 5)], 10, 5) == Availability(True)


# --- Scenario 7: Party symmetry and determinism ----------------------------------------


def _random_statements(seed: int, parties: Sequence[int]) -> list[RuleStatement]:
    rng = random.Random(seed)
    topics = ["housing", "economy", "health", "education"]
    out = []
    for key in range(1, 61):
        values = {p: rng.choice([-2, -1, 0, 1, 2, None]) for p in parties}
        codes = {p: rng.choice([("28",), ("31",), ("28", "31")]) for p in parties}
        out.append(statement(key, values, rng.choice(topics), codes))
    return out


def test_relabelling_parties_gives_the_same_result_up_to_the_relabelling() -> None:
    parties = (1, 2, 3, 4, 5)
    statements = _random_statements(7, parties)
    relabel = {1: 40, 2: 10, 3: 50, 4: 20, 5: 30}
    relabelled = [
        RuleStatement(
            s.key, s.position, s.topic, {relabel[p]: stance for p, stance in s.stances.items()}
        )
        for s in statements
    ]
    for code in ("28", "31", "08"):
        for subset in ((1, 2, 3, 4, 5), (2, 4), (1, 3, 5)):
            original = evaluate(code, statements, subset, min_statements=3,
                                min_party_sides=2, max_topic_share_percent=30)
            mapped = evaluate(code, relabelled, [relabel[p] for p in subset], min_statements=3,
                              min_party_sides=2, max_topic_share_percent=30)
            assert mapped.valid == original.valid
            assert mapped.ordered == original.ordered
            assert mapped.lengths == original.lengths
            assert mapped.availability.available == original.availability.available
            assert mapped.availability.reason == original.availability.reason
            assert sorted((relabel[p], n) for p, n in original.sides) == sorted(mapped.sides)
            # The order of the input Party list never matters.
            assert evaluate(code, statements, tuple(reversed(subset)), min_statements=3,
                            min_party_sides=2, max_topic_share_percent=30) == original


def test_two_evaluations_of_the_same_input_are_equal() -> None:
    statements = _random_statements(11, (1, 2, 3))
    first = evaluate_default("28", statements, (1, 2, 3))
    second = evaluate_default("28", list(statements), [3, 2, 1])
    assert first == second
