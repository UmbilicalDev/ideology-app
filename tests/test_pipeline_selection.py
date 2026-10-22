"""Statement Selection (pipeline-coverage-selection) on plain data: no database, no LLM."""

import dataclasses
import json
from collections import Counter
from collections.abc import Sequence

import pytest
from pipeline_fixtures import offline_guard

from ideology_app.config import ValidationSettings
from ideology_app.pipeline import (
    SELECTION_VERSION,
    PositionResult,
    StatementDraft,
    TOPICS,
    pool_bounds,
    select_statements,
    topic_cap,
)
from ideology_app.validation import (
    PositionRow,
    StatementRow,
    ValidationInput,
)
from ideology_app.validation.party_coverage import check_party_coverage
from ideology_app.validation.statement_count import check_statement_count
from ideology_app.validation.statement_uniqueness import check_statement_uniqueness
from ideology_app.validation.topic_spread import check_topic_spread

DEFAULTS = ValidationSettings()
SMALL = ValidationSettings(
    min_party_coverage_percent=70, min_statements=10, max_statements=20, max_topic_share_percent=30
)

Values = dict[int, Sequence[int | None]]  # party id -> value per pool Statement


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def pool(count: int, topics: Sequence[str] | None = None) -> list[StatementDraft]:
    """``count`` distinct Statements; topics ``TOPICS[i % 18]`` unless given."""
    return [
        StatementDraft(
            text=f"Afirmación {n}: el Estado debe actuar en el ámbito {n}.",
            topic=topics[n - 1] if topics else TOPICS[(n - 1) % len(TOPICS)],
        )
        for n in range(1, count + 1)
    ]


def positions(values: Values) -> dict[int, list[PositionResult]]:
    """PositionResults with Evidence that identifies Party and Statement."""
    return {
        party: [
            PositionResult(statement_number=n, value=None)
            if value is None
            else PositionResult(
                statement_number=n,
                value=value,
                document_id=party,
                quote=f"Cita {party}-{n}.",
                page=n,
                url=f"https://example.org/{party}.pdf" if party % 2 else None,
            )
            for n, value in enumerate(column, start=1)
        ]
        for party, column in values.items()
    }


def separating(count: int, parties: int = 2) -> Values:
    """Every Party has a stance everywhere; Party 1 agrees, the others disagree."""
    return {p: [1 if p == 1 else -1] * count for p in range(1, parties + 1)}


def selected_numbers(report: dict) -> list[int]:
    return [e["pool"] for e in report["pool"] if e["status"] == "selected"]


def as_input(selection, settings: ValidationSettings, party_ids: Sequence[int]) -> ValidationInput:
    return ValidationInput(
        statements=tuple(
            StatementRow(id=n, position=n, text=s.text, topic=s.topic)
            for n, s in enumerate(selection.statements, start=1)
        ),
        positions=tuple(
            PositionRow(r.statement_number, r.statement_number, party, r.value,
                        r.document_id, r.quote, r.page, r.url)
            for party, results in selection.positions.items()
            for r in results
        ),
        party_ids=tuple(party_ids),
        settings=settings,
    )


def _mixed_values(count: int) -> Values:
    """A deterministic, uneven matrix with gaps and ties, for three Parties."""
    def value(party: int, n: int) -> int | None:
        code = (party * 7 + n * 3 + party * n) % 9
        return None if code >= 6 or (party == 3 and n % 4) else code % 5 - 2

    return {p: [value(p, n) for n in range(1, count + 1)] for p in (1, 2, 3)}


def test_selection_is_deterministic() -> None:
    drafts = pool(55)
    values = _mixed_values(55)
    first = select_statements(drafts, positions(values), [1, 2, 3], DEFAULTS)
    second = select_statements(list(drafts), positions(values), (1, 2, 3), DEFAULTS)

    assert first == second
    assert json.dumps(first.report, sort_keys=True) == json.dumps(second.report, sort_keys=True)
    assert first.report["selected_count"] == len(first.statements)


def test_party_relabelling_does_not_change_selection() -> None:
    drafts = pool(55)
    values = _mixed_values(55)
    base = select_statements(drafts, positions(values), [1, 2, 3], DEFAULTS)
    for order in ((2, 3, 1), (3, 1, 2), (3, 2, 1)):
        relabelled = {party: values[source] for party, source in zip((1, 2, 3), order)}
        other = select_statements(drafts, positions(relabelled), [1, 2, 3], DEFAULTS)
        assert selected_numbers(other.report) == selected_numbers(base.report), order
        assert other.report["count_rule"] == base.report["count_rule"]
    # The order in which the Party ids are passed does not matter either.
    shuffled = select_statements(drafts, positions(values), [3, 1, 2], DEFAULTS)
    assert selected_numbers(shuffled.report) == selected_numbers(base.report)


def test_duplicates_keep_first_in_pool_order() -> None:
    drafts = pool(50)
    drafts[4] = StatementDraft(text="  AFIRMACIÓN 2: el estado debe actuar en el ámbito 2 ", topic="health")
    drafts[30] = StatementDraft(text=drafts[1].text, topic="economy")

    selection = select_statements(drafts, positions(separating(50)), [1, 2], DEFAULTS)

    entries = selection.report["pool"]
    assert [(e["pool"], e["status"], e["duplicate_of"], e["tier"]) for e in entries
            if e["duplicate_of"] is not None] == [
        (5, "duplicate", 2, None),
        (31, "duplicate", 2, None),
    ]
    assert entries[1]["status"] == "selected"
    assert 5 not in selected_numbers(selection.report)
    assert check_statement_uniqueness(as_input(selection, DEFAULTS, [1, 2])) == []


@pytest.mark.parametrize("settings", [DEFAULTS, SMALL,
                                      ValidationSettings(min_statements=10, max_statements=12,
                                                         max_topic_share_percent=40)])
def test_topic_cap_is_never_exceeded_and_topic_spread_passes(
    settings: ValidationSettings,
) -> None:
    topics = ["economy"] * 25 + [TOPICS[1 + n % 17] for n in range(30)]
    drafts = pool(55, topics)

    selection = select_statements(drafts, positions(separating(55)), [1, 2], settings)

    cap = topic_cap(settings)
    assert selection.report["topic_cap"] == cap
    counts = Counter(s.topic for s in selection.statements)
    assert counts["economy"] == cap
    assert max(counts.values()) <= cap
    assert check_topic_spread(as_input(selection, settings, [1, 2])) == []
    statuses = {e["status"] for e in selection.report["pool"] if e["topic"] == "economy"}
    assert statuses == {"selected", "topic_full"}


def test_topic_cap_follows_settings() -> None:
    assert topic_cap(DEFAULTS) == 7
    assert topic_cap(ValidationSettings(min_statements=10, max_statements=12,
                                        max_topic_share_percent=40)) == 4
    assert topic_cap(ValidationSettings(max_topic_share_percent=0)) == 1


@pytest.mark.parametrize(
    ("settings", "low", "high"),
    [
        (DEFAULTS, 25, 35),
        (ValidationSettings(min_party_coverage_percent=50, min_statements=10, max_statements=12,
                            max_topic_share_percent=40), 10, 12),
    ],
)
def test_count_within_settings_range(settings: ValidationSettings, low: int, high: int) -> None:
    pool_low, pool_high, _ = pool_bounds(settings)
    assert (pool_low, pool_high) == (45, 60)
    for size, values in ((pool_low, _mixed_values(pool_low)), (pool_high, separating(pool_high))):
        parties = sorted(values)
        selection = select_statements(pool(size), positions(values), parties, settings)
        assert low <= len(selection.statements) <= high
        assert check_statement_count(as_input(selection, settings, parties)) == []
        assert selection.report["settings"] == dataclasses.asdict(settings)


def test_worst_covered_party_is_served_first() -> None:
    # Party 3 has stances only on pool Statements 40..44; Parties 1 and 2 everywhere.
    values = separating(50, parties=3)
    values[3] = [-1 if 40 <= n <= 44 else None for n in range(1, 51)]

    selection = select_statements(pool(50), positions(values), [1, 2, 3], DEFAULTS)

    picks = {e["pool"]: e["pick"] for e in selection.report["pool"]}
    assert sorted(picks[n] for n in range(40, 45)) == [1, 2, 3, 4, 5]
    assert set(range(40, 45)) <= set(selected_numbers(selection.report))
    party3 = next(p for p in selection.report["parties"] if p["party_id"] == 3)
    assert party3 == {"party_id": 3, "pool_stances": 5, "selected_stances": 5}


def test_ties_prefer_distinct_then_spread_then_pool_order() -> None:
    # Every Party has a stance everywhere, so coverage always ties.
    rows = [
        (1, 1, -1),   # 1: distinct 2, spread 2
        (2, 0, -2),   # 2: distinct 3, spread 4
        (1, 0, -1),   # 3: distinct 3, spread 2
        (2, 2, -2),   # 4: distinct 2, spread 4
        (1, 1, -1),   # 5: distinct 2, spread 2 (ties with 1; later in the pool)
        (2, -2, 0),   # 6: distinct 3, spread 4 (ties with 2; later in the pool)
    ]
    values = {p: [row[p - 1] for row in rows] for p in (1, 2, 3)}
    settings = ValidationSettings(min_statements=1, max_statements=6, max_topic_share_percent=100)

    selection = select_statements(pool(6), positions(values), [1, 2, 3], settings)

    order = sorted(selection.report["pool"], key=lambda e: e["pick"])
    assert [e["pool"] for e in order] == [2, 6, 3, 4, 1, 5]
    assert [(e["distinct"], e["spread"]) for e in order] == [
        (3, 4), (3, 4), (3, 2), (2, 4), (2, 2), (2, 2)
    ]


def _partial_party3(stances: int, count: int = 30) -> Values:
    values = separating(count, parties=3)
    values[3] = [1 if n <= stances else None for n in range(1, count + 1)]
    return values


def test_largest_count_that_meets_coverage() -> None:
    # Party 3 covers 12 Statements: 12 / n >= 70 % up to n = 17.
    selection = select_statements(pool(30), positions(_partial_party3(12)), [1, 2, 3], SMALL)

    assert selection.report["count_rule"] == "coverage_met"
    assert selection.report["selected_count"] == 17
    assert check_party_coverage(as_input(selection, SMALL, [1, 2, 3])) == []
    # The picks beyond the count stay in the report as not selected.
    picked = [e for e in selection.report["pool"] if e["pick"] is not None]
    assert len(picked) == 20
    assert {e["status"] for e in picked if e["pick"] > 17} == {"not_picked"}


def test_best_worst_coverage_when_threshold_unreachable() -> None:
    # Party 3 covers 5: 5 / n never reaches 70 % for n >= 10; the best is n = 10.
    selection = select_statements(pool(30), positions(_partial_party3(5)), [1, 2, 3], SMALL)
    assert selection.report["count_rule"] == "best_coverage"
    assert selection.report["selected_count"] == 10
    assert selection.report["projected_failures"] == ["party_coverage"]

    # No stance at all: every n ties at 0, so the larger n wins.
    none = select_statements(pool(30), positions(_partial_party3(0)), [1, 2, 3], SMALL)
    assert none.report["count_rule"] == "best_coverage"
    assert none.report["selected_count"] == 20


def test_non_separating_fill_only_to_minimum() -> None:
    # Only the first 8 Statements separate the two Parties.
    values = {1: [1] * 30, 2: [-1] * 8 + [1] * 22}

    selection = select_statements(pool(30), positions(values), [1, 2], SMALL)

    report = selection.report
    assert report["count_rule"] == "short"
    assert report["selected_count"] == SMALL.min_statements == 10
    tiers = {e["pool"]: e["tier"] for e in report["pool"]}
    assert [tiers[n] for n in selected_numbers(report)] == [1] * 8 + [2] * 2
    assert selected_numbers(report) == list(range(1, 11))
    assert report["projected_failures"] == ["statement_separation"]


def test_fewer_unique_than_minimum_keeps_all() -> None:
    drafts = pool(12)
    for n in range(6, 12):
        drafts[n] = StatementDraft(text=drafts[n - 6].text, topic=drafts[n].topic)

    selection = select_statements(drafts, positions(separating(12)), [1, 2], SMALL)

    assert selected_numbers(selection.report) == [1, 2, 3, 4, 5, 6]
    assert selection.report["count_rule"] == "short"
    assert selection.report["projected_failures"] == ["statement_count"]


def test_fewer_than_two_parties_makes_every_statement_tier_2() -> None:
    selection = select_statements(pool(30), positions({1: [1] * 30}), [1], SMALL)
    assert {e["tier"] for e in selection.report["pool"]} == {2}
    assert selection.report["selected_count"] == SMALL.min_statements


def test_selected_in_pool_order_and_positions_renumbered_with_evidence_unchanged() -> None:
    values = separating(50, parties=3)
    values[3] = [-1 if n % 3 == 0 else None for n in range(1, 51)]
    drafts = pool(50)
    extracted = positions(values)

    selection = select_statements(drafts, extracted, [1, 2, 3], DEFAULTS)

    numbers = selected_numbers(selection.report)
    assert numbers == sorted(numbers)
    assert list(selection.statements) == [drafts[n - 1] for n in numbers]
    assert all(selection.statements[i] is drafts[n - 1] for i, n in enumerate(numbers))
    assert [e["position"] for e in selection.report["pool"] if e["status"] == "selected"] == (
        list(range(1, len(numbers) + 1))
    )
    assert sorted(selection.positions) == [1, 2, 3]
    for party, results in selection.positions.items():
        assert [r.statement_number for r in results] == list(range(1, len(numbers) + 1))
        for new, (result, n) in enumerate(zip(results, numbers, strict=True), start=1):
            assert result == dataclasses.replace(extracted[party][n - 1], statement_number=new)


def test_report_is_json_and_complete() -> None:
    drafts = pool(50)
    drafts[9] = StatementDraft(text=drafts[0].text, topic="health")
    values = _mixed_values(50)

    selection = select_statements(drafts, positions(values), [1, 2, 3], DEFAULTS)

    report = json.loads(json.dumps(selection.report))
    assert report == selection.report
    assert list(report) == [
        "version", "settings", "topic_cap", "party_ids", "pool_size", "selected_count",
        "count_rule", "projected_failures", "parties", "pool",
    ]
    assert report["version"] == SELECTION_VERSION == "v1"
    assert report["settings"] == dataclasses.asdict(DEFAULTS)
    assert report["party_ids"] == [1, 2, 3]
    assert report["pool_size"] == 50
    assert report["selected_count"] == len(selection.statements)
    assert report["count_rule"] in ("coverage_met", "best_coverage", "short")
    assert [p["party_id"] for p in report["parties"]] == [1, 2, 3]
    for party in report["parties"]:
        column = values[party["party_id"]]
        assert party["pool_stances"] == sum(v is not None for v in column)
        assert party["selected_stances"] == sum(
            column[n - 1] is not None for n in selected_numbers(report)
        )
    assert [e["pool"] for e in report["pool"]] == list(range(1, 51))
    for entry in report["pool"]:
        n = entry["pool"]
        assert list(entry) == [
            "pool", "text", "topic", "values", "stances", "distinct", "spread", "tier",
            "status", "duplicate_of", "pick", "position",
        ]
        assert entry["text"] == drafts[n - 1].text and entry["topic"] == drafts[n - 1].topic
        assert entry["values"] == [values[p][n - 1] for p in (1, 2, 3)]
        found = [v for v in entry["values"] if v is not None]
        assert entry["stances"] == len(found)
        assert entry["distinct"] == len(set(found))
        assert entry["spread"] == (max(found) - min(found) if len(found) > 1 else 0)
        assert entry["status"] in ("selected", "duplicate", "topic_full", "not_picked")
        assert (entry["position"] is not None) == (entry["status"] == "selected")
    assert report["pool"][9]["status"] == "duplicate"
    assert report["pool"][9]["duplicate_of"] == 1


# pipeline-verified-findings: the default coverage target is 50 % (60 before).


def _party2_on_first(count: int, covered: int) -> Values:
    return {
        1: [1] * count,
        2: [-1] * covered + [None] * (count - covered),
        3: [-1] * count,
    }


def test_default_coverage_target_is_50_percent() -> None:
    assert DEFAULTS.min_party_coverage_percent == 50
    values = _party2_on_first(50, 17)
    selection = select_statements(pool(50), positions(values), [1, 2, 3], DEFAULTS)
    report = selection.report
    # 17 of 34 is exactly 50 %: the largest Questionnaire that meets the target.
    assert (report["selected_count"], report["count_rule"]) == (34, "coverage_met")
    party2 = next(p for p in report["parties"] if p["party_id"] == 2)
    assert party2["selected_stances"] == 17
    assert check_party_coverage(as_input(selection, DEFAULTS, [1, 2, 3])) == []

    # The same pool at an explicit 60 % stops at 28 (17 of 28, 60.7 %).
    strict = dataclasses.replace(DEFAULTS, min_party_coverage_percent=60)
    report = select_statements(pool(50), positions(values), [1, 2, 3], strict).report
    assert (report["selected_count"], report["count_rule"]) == (28, "coverage_met")
