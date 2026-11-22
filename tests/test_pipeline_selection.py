"""Statement Selection on plain data: no database, no LLM.

Selection v3 (pipeline-statement-priority-tiers): side rule, few-Party drop,
ranking by Parties with a side, priority order and per-length topic caps.
"""

import dataclasses
import json
from collections import Counter
from collections.abc import Sequence

import pytest
from pipeline_fixtures import offline_guard

from ideology_app.config import ValidationSettings
from ideology_app.pipeline import (
    SELECTION_VERSION,
    PoolStatement,
    PositionResult,
    TOPICS,
    anchor_summary,
    pool_bounds,
    select_statements,
    topic_cap,
    topic_caps,
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
    min_party_coverage_percent=70, min_statements=10, max_statements=20, max_topic_share_percent=30,
    questionnaire_lengths=(), min_statement_parties=2,
)
# Room for any ranking: up to 40 Statements are all kept (``short``), no topic
# cap binds (100 % of 40), no shorter length, one Party with a side is enough.
OPEN = ValidationSettings(
    min_statements=40, max_statements=40, max_topic_share_percent=100,
    questionnaire_lengths=(), min_statement_parties=1,
)

Values = dict[int, Sequence[int | None]]  # party id -> value per pool Statement


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def note(n: int) -> str:
    """A valid context note (30..300 characters, no evaluative word)."""
    return f"El ámbito {n} reúne las normas y los servicios públicos de esa materia."


def draft(
    text: str, topic: str, context_note: str | None = None, anchor: int | None = None
) -> PoolStatement:
    """A pool Statement; its note defaults to a valid one."""
    return PoolStatement(
        text=text,
        topic=topic,
        context_note=note(0) if context_note is None else context_note,
        anchor=anchor,
    )


def pool(count: int, topics: Sequence[str] | None = None) -> list[PoolStatement]:
    """``count`` distinct Statements with valid notes; topics ``TOPICS[i % 18]`` unless given."""
    return [
        draft(
            f"Afirmación {n}: el Estado debe actuar en el ámbito {n}.",
            topics[n - 1] if topics else TOPICS[(n - 1) % len(TOPICS)],
            note(n),
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


def separating(count: int, parties: int = 3) -> Values:
    """Every Party has a stance everywhere; Party 1 agrees, the others disagree."""
    return {p: [1 if p == 1 else -1] * count for p in range(1, parties + 1)}


def settings_json(settings: ValidationSettings) -> dict:
    """``asdict(settings)`` as stored in the report: tuples as JSON lists."""
    return {
        **dataclasses.asdict(settings),
        "context_note_evaluative_words": list(settings.context_note_evaluative_words),
        "questionnaire_lengths": list(settings.questionnaire_lengths),
    }


def selected_numbers(report: dict) -> list[int]:
    """The selected pool numbers in position (priority) order."""
    chosen = [e for e in report["pool"] if e["status"] == "selected"]
    return [e["pool"] for e in sorted(chosen, key=lambda e: e["position"])]


def as_input(selection, settings: ValidationSettings, party_ids: Sequence[int]) -> ValidationInput:
    return ValidationInput(
        statements=tuple(
            StatementRow(
                id=n, position=n, text=s.text, topic=s.topic, context_note=s.context_note
            )
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
        lengths=selection.lengths,
    )


def _mixed_values(count: int) -> Values:
    """A deterministic, uneven matrix with gaps, zeros and ties, for five Parties."""
    def value(party: int, n: int) -> int | None:
        code = (party * 7 + n * 3 + party * n) % 9
        return None if code >= 7 or (party == 3 and n % 4 == 0) else code % 5 - 2

    return {p: [value(p, n) for n in range(1, count + 1)] for p in (1, 2, 3, 4, 5)}


PARTIES5 = [1, 2, 3, 4, 5]


def rows_values(rows: Sequence[Sequence[int | None]]) -> Values:
    """``rows[n - 1]`` holds pool Statement n's value per Party 1..k."""
    width = len(rows[0])
    return {p: [row[p - 1] for row in rows] for p in range(1, width + 1)}


def test_selection_is_deterministic() -> None:
    drafts = pool(120)
    values = _mixed_values(120)
    first = select_statements(drafts, positions(values), PARTIES5, DEFAULTS)
    second = select_statements(list(drafts), positions(values), tuple(PARTIES5), DEFAULTS)

    assert first == second
    assert json.dumps(first.report, sort_keys=True) == json.dumps(second.report, sort_keys=True)
    assert first.report["selected_count"] == len(first.statements) > 0


def test_party_relabelling_changes_only_party_ids() -> None:
    drafts = pool(120)
    values = _mixed_values(120)
    base = select_statements(drafts, positions(values), PARTIES5, DEFAULTS)

    def without_values(report: dict) -> list[dict]:
        return [{k: v for k, v in e.items() if k != "values"} for e in report["pool"]]

    for order in ((2, 3, 1, 5, 4), (5, 4, 3, 2, 1), (3, 1, 2, 4, 5)):
        relabelled = {party: values[source] for party, source in zip(PARTIES5, order)}
        other = select_statements(drafts, positions(relabelled), PARTIES5, DEFAULTS)
        assert other.statements == base.statements, order
        assert other.lengths == base.lengths
        assert without_values(other.report) == without_values(base.report)
        for key in ("count_rule", "lengths", "topic_caps", "eligible_count",
                    "projected_failures"):
            assert other.report[key] == base.report[key]
        # The Party rows move with their values.
        moved = {p["party_id"]: p for p in other.report["parties"]}
        for party, source in zip(PARTIES5, order):
            row = next(r for r in base.report["parties"] if r["party_id"] == source)
            assert {**moved[party], "party_id": source} == row
    # The order in which the Party ids are passed does not matter either.
    shuffled = select_statements(drafts, positions(values), [3, 1, 5, 2, 4], DEFAULTS)
    assert selected_numbers(shuffled.report) == selected_numbers(base.report)
    assert shuffled.statements == base.statements


def test_duplicates_keep_first_in_pool_order() -> None:
    drafts = pool(50)
    drafts[4] = draft("  AFIRMACIÓN 2: el estado debe actuar en el ámbito 2 ", "health")
    drafts[30] = draft(drafts[1].text, "economy")

    selection = select_statements(drafts, positions(separating(50)), [1, 2, 3], DEFAULTS)

    entries = selection.report["pool"]
    assert [(e["pool"], e["status"], e["duplicate_of"], e["rank"]) for e in entries
            if e["duplicate_of"] is not None] == [
        (5, "duplicate", 2, None),
        (31, "duplicate", 2, None),
    ]
    assert entries[1]["status"] == "selected"
    assert 5 not in selected_numbers(selection.report)
    assert check_statement_uniqueness(as_input(selection, DEFAULTS, [1, 2, 3])) == []


# Scenario 8: eligibility statuses


def test_side_rule_and_few_parties_statuses() -> None:
    rows = [
        (1, -1, 1, None),     # 1: 3 sided, ranked
        (1, 2, 2, 1),         # 2: nobody against
        (-1, -2, None, -1),   # 3: nobody in favour
        (0, 0, 0, None),      # 4: only zeros
        (None, None, None, None),  # 5: no stance at all
        (1, -1, 0, None),     # 6: 2 sided (zero does not count): few_parties
        (2, -1, None, None),  # 7: 2 sided: few_parties
        (-2, 1, 1, -1),       # 8: 4 sided, ranked
    ]
    settings = dataclasses.replace(OPEN, min_statement_parties=3)
    selection = select_statements(pool(8), positions(rows_values(rows)), [1, 2, 3, 4], settings)

    entries = selection.report["pool"]
    assert [e["status"] for e in entries] == [
        "selected", "not_separating", "not_separating", "not_separating", "not_separating",
        "few_parties", "few_parties", "selected",
    ]
    assert [(e["parties"], e["favour"], e["against"], e["separation"]) for e in entries] == [
        (3, 2, 1, 1), (4, 4, 0, 0), (3, 0, 3, 0), (0, 0, 0, 0), (0, 0, 0, 0),
        (2, 1, 1, 1), (2, 1, 1, 1), (4, 2, 2, 2),
    ]
    assert selected_numbers(selection.report) == [8, 1]
    assert selection.report["eligible_count"] == 2
    assert [e["rank"] for e in entries] == [2, None, None, None, None, None, None, 1]


def test_min_statement_parties_is_read_from_settings() -> None:
    rows = [(1, -1, None), (1, -1, -1)]
    two = select_statements(pool(2), positions(rows_values(rows)), [1, 2, 3],
                            dataclasses.replace(OPEN, min_statement_parties=2))
    assert selected_numbers(two.report) == [2, 1]
    three = select_statements(pool(2), positions(rows_values(rows)), [1, 2, 3],
                              dataclasses.replace(OPEN, min_statement_parties=3))
    assert selected_numbers(three.report) == [2]
    assert three.report["pool"][0]["status"] == "few_parties"


def test_non_separating_statements_never_fill_up_to_the_minimum() -> None:
    # Only the first 8 Statements separate the Parties; tier-2 fill is gone.
    values = {1: [1] * 30, 2: [-1] * 8 + [1] * 22}

    selection = select_statements(pool(30), positions(values), [1, 2], SMALL)

    report = selection.report
    assert report["count_rule"] == "short"
    assert report["selected_count"] == 8
    assert selected_numbers(report) == list(range(1, 9))
    assert {e["status"] for e in report["pool"][8:]} == {"not_separating"}
    assert report["projected_failures"] == ["statement_count"]


def test_fewer_unique_than_minimum_keeps_all() -> None:
    drafts = pool(12)
    for n in range(6, 12):
        drafts[n] = draft(drafts[n - 6].text, drafts[n].topic)

    selection = select_statements(drafts, positions(separating(12)), [1, 2, 3], SMALL)

    assert selected_numbers(selection.report) == [1, 2, 3, 4, 5, 6]
    assert selection.report["count_rule"] == "short"
    assert selection.report["projected_failures"] == ["statement_count"]


def test_fewer_than_two_parties_makes_every_statement_not_separating() -> None:
    selection = select_statements(pool(30), positions({1: [1] * 30}), [1], SMALL)
    assert {e["status"] for e in selection.report["pool"]} == {"not_separating"}
    assert selection.report["selected_count"] == 0
    assert selection.statements == () and selection.lengths == ()


# Scenario 9: priority order


def test_ranking_by_parties_then_separation_then_pool_order() -> None:
    rows = [
        (1, -1, None, None, None),   # 1: 2 parties, separation 1
        (1, 1, -1, None, None),      # 2: 3 parties, separation 1
        (1, -1, -1, 1, None),        # 3: 4 parties, separation 2
        (1, 1, 1, -1, None),         # 4: 4 parties, separation 1
        (2, -2, 1, None, None),      # 5: 3 parties, separation 1 (ties with 2; later)
        (-1, 1, -1, 1, 0),           # 6: 4 parties, separation 2 (ties with 3; later)
        (1, -1, 2, -2, 1),           # 7: 5 parties, separation 2
    ]
    selection = select_statements(pool(7), positions(rows_values(rows)), PARTIES5, OPEN)

    assert selected_numbers(selection.report) == [7, 3, 6, 4, 2, 5, 1]
    ranks = {e["pool"]: e["rank"] for e in selection.report["pool"]}
    assert [ranks[n] for n in (7, 3, 6, 4, 2, 5, 1)] == [1, 2, 3, 4, 5, 6, 7]
    assert [s.text for s in selection.statements] == [
        pool(7)[n - 1].text for n in (7, 3, 6, 4, 2, 5, 1)
    ]


def _counts_matrix(counts: Sequence[int], parties: int = 10) -> Values:
    """Pool Statement n has ``counts[n - 1]`` Parties with a side: Party 1 in favour,
    the next ones against, and the rest no stance."""
    rows = [
        [1 if p == 1 else (-1 if p <= k else None) for p in range(1, parties + 1)]
        for k in counts
    ]
    return rows_values(rows)


def test_positions_follow_the_party_count_order() -> None:
    # 20 eligible Statements with 9, 9, 8, ... Parties, given in a shuffled pool order.
    counts = [3, 9, 5, 8, 9, 4, 7, 6, 8, 3, 5, 7, 6, 4, 9, 5, 8, 6, 7, 4]
    selection = select_statements(
        pool(20), positions(_counts_matrix(counts)), list(range(1, 11)), OPEN
    )
    order = selected_numbers(selection.report)
    assert [counts[n - 1] for n in order] == sorted(counts, reverse=True)
    # Equal counts (equal separation 1) keep pool order.
    assert order[:3] == [2, 5, 15]
    assert [e["position"] for e in selection.report["pool"]] == [
        order.index(n) + 1 for n in range(1, 21)
    ]


def test_a_topic_cap_defers_but_never_reorders_other_topics() -> None:
    # Lengths (5,), min 10, share 40: caps 2 for positions 1..5, then 4.
    settings = ValidationSettings(
        min_statements=10, max_statements=10, max_topic_share_percent=40,
        questionnaire_lengths=(5,), min_statement_parties=1,
    )
    assert topic_caps(settings) == (2, 4)
    topics = ["economy", "economy", "economy", "health", "housing", "taxation", "education",
              "pensions", "employment", "culture_language"]
    counts = [10, 9, 8, 7, 6, 5, 4, 3, 2, 2]
    selection = select_statements(
        pool(10, topics), positions(_counts_matrix(counts)), list(range(1, 11)), settings
    )
    order = selected_numbers(selection.report)
    # The third economy Statement (pool 3) waits for position 6, the first with cap 4.
    assert order == [1, 2, 4, 5, 6, 3, 7, 8, 9, 10]
    others = [n for n in order if topics[n - 1] != "economy"]
    assert others == sorted(others)
    assert check_topic_spread(as_input(selection, settings, list(range(1, 11)))) == []


@pytest.mark.parametrize("settings", [DEFAULTS, dataclasses.replace(DEFAULTS, max_statements=36)])
def test_topic_caps_make_every_prefix_pass_topic_spread(settings: ValidationSettings) -> None:
    topics = ["economy"] * 40 + [TOPICS[1 + n % 17] for n in range(80)]
    drafts = pool(120, topics)

    selection = select_statements(drafts, positions(separating(120)), [1, 2, 3], settings)

    caps = topic_caps(settings)
    assert selection.report["topic_caps"] == list(caps) == [4, 9, 10]
    order = [s.topic for s in selection.statements]
    assert order[:15].count("economy") == 4
    assert order[:30].count("economy") == 9
    assert order.count("economy") == 10
    assert selection.lengths[-1] == len(selection.statements) >= settings.min_statements
    assert check_topic_spread(as_input(selection, settings, [1, 2, 3])) == []
    statuses = {e["status"] for e in selection.report["pool"] if e["topic"] == "economy"}
    assert statuses == {"selected", "topic_full"}


def test_topic_caps_follow_settings() -> None:
    assert topic_caps(DEFAULTS) == (4, 9, 10)
    assert topic_cap(DEFAULTS) == 10
    assert topic_caps(ValidationSettings(min_statements=10, max_statements=12,
                                         max_topic_share_percent=40,
                                         questionnaire_lengths=())) == (4,)
    assert topic_caps(ValidationSettings(max_topic_share_percent=0)) == (1, 1, 1)


# Scenario 10: count, lengths and the Dataset Version order


@pytest.mark.parametrize(
    ("settings", "low", "high"),
    [
        (DEFAULTS, 35, 40),
        (ValidationSettings(min_party_coverage_percent=50, min_statements=10, max_statements=12,
                            max_topic_share_percent=40,
                            questionnaire_lengths=(),), 10, 12),
    ],
)
def test_count_within_settings_range(settings: ValidationSettings, low: int, high: int) -> None:
    pool_low, pool_high, _ = pool_bounds(settings)
    assert (pool_low, pool_high) == (100, 140)
    for size in (pool_low, pool_high):
        values = separating(size, parties=4)
        selection = select_statements(pool(size), positions(values), [1, 2, 3, 4], settings)
        assert low <= len(selection.statements) <= high
        assert check_statement_count(as_input(selection, settings, [1, 2, 3, 4])) == []
        assert selection.report["settings"] == settings_json(settings)


def test_lengths_and_tiers_of_a_full_selection() -> None:
    selection = select_statements(pool(120), positions(separating(120)), [1, 2, 3], DEFAULTS)
    assert len(selection.statements) == 40
    assert selection.lengths == (15, 30, 40)
    assert selection.report["lengths"] == [15, 30, 40]
    tiers = {e["position"]: e["tier"] for e in selection.report["pool"] if e["position"]}
    assert [tiers[k] for k in range(1, 41)] == [15] * 15 + [30] * 15 + [40] * 10
    assert {e["tier"] for e in selection.report["pool"] if e["position"] is None} == {None}


def _partial_party3(stances: int, count: int = 30) -> Values:
    values = separating(count, parties=3)
    values[3] = [-1 if n <= stances else None for n in range(1, count + 1)]
    return values


def test_largest_count_that_meets_coverage() -> None:
    # Party 3 covers 12 Statements, ranked first (3 Parties); 12 / n >= 70 % up to n = 17.
    selection = select_statements(pool(30), positions(_partial_party3(12)), [1, 2, 3], SMALL)

    assert selection.report["count_rule"] == "coverage_met"
    assert selection.report["selected_count"] == 17
    assert check_party_coverage(as_input(selection, SMALL, [1, 2, 3])) == []
    # The placed Statements beyond the count stay in the report as not selected.
    placed = [e for e in selection.report["pool"] if e["rank"] is not None and e["rank"] <= 20]
    assert len(placed) == 20
    assert {e["status"] for e in placed if e["rank"] > 17} == {"not_picked"}


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


def test_zero_values_do_not_count_toward_coverage() -> None:
    values = separating(30, parties=3)
    values[3] = [0 if n > 12 else -1 for n in range(1, 31)]
    selection = select_statements(pool(30), positions(values), [1, 2, 3], SMALL)
    assert selection.report["selected_count"] == 17
    party3 = next(p for p in selection.report["parties"] if p["party_id"] == 3)
    assert party3["pool_sides"] == 12


def test_selected_in_priority_order_and_positions_renumbered_with_evidence_unchanged() -> None:
    values = separating(50, parties=4)
    values[4] = [1 if n % 3 == 0 else None for n in range(1, 51)]
    drafts = pool(50)
    extracted = positions(values)

    selection = select_statements(drafts, extracted, [1, 2, 3, 4], DEFAULTS)

    numbers = selected_numbers(selection.report)
    # Statements where Party 4 takes a side (4 Parties) come first, in pool order.
    with_four = [n for n in numbers if n % 3 == 0]
    assert numbers[: len(with_four)] == with_four == sorted(with_four)
    assert list(selection.statements) == [drafts[n - 1] for n in numbers]
    assert all(selection.statements[i] is drafts[n - 1] for i, n in enumerate(numbers))
    assert sorted(selection.positions) == [1, 2, 3, 4]
    for party, results in selection.positions.items():
        assert [r.statement_number for r in results] == list(range(1, len(numbers) + 1))
        for new, (result, n) in enumerate(zip(results, numbers, strict=True), start=1):
            assert result == dataclasses.replace(extracted[party][n - 1], statement_number=new)


def _late_party3() -> Values:
    """Statements 1..20 have 4 Parties (not Party 3); 21..60 have Parties 1-3 only."""
    rows = [
        (1, -1, None, -1, 1) if n <= 20 else (1, -1, -1, None, None) for n in range(1, 61)
    ]
    return rows_values(rows)


def test_a_party_sided_only_below_rank_15_is_a_projected_failure() -> None:
    # Scenario 11 at selection level: the full set passes coverage, the 15 prefix does not.
    selection = select_statements(pool(60), positions(_late_party3()), PARTIES5, DEFAULTS)
    assert selection.report["count_rule"] == "coverage_met"
    assert selection.lengths == (15, 30, 40)
    assert selection.report["projected_failures"] == ["party_coverage"]
    party3 = next(p for p in selection.report["parties"] if p["party_id"] == 3)
    assert party3["selected_sides"] == [0, 10, 20]
    entries = check_party_coverage(as_input(selection, DEFAULTS, PARTIES5))
    assert [e.message for e in entries] == [
        "first 15 statements: party 3 is in favour or against on 0 of 15 statements (0%); "
        "minimum is 50%",
        "first 30 statements: party 3 is in favour or against on 10 of 30 statements (33%); "
        "minimum is 50%",
    ]


def test_report_is_json_and_complete() -> None:
    drafts = pool(120)
    drafts[9] = draft(drafts[0].text, "health")
    values = _mixed_values(120)

    selection = select_statements(drafts, positions(values), PARTIES5, DEFAULTS)

    report = json.loads(json.dumps(selection.report))
    assert report == selection.report
    assert list(report) == [
        "version", "settings", "lengths", "topic_caps", "party_ids", "pool_size",
        "eligible_count", "selected_count", "count_rule", "projected_failures", "parties",
        "pool",
    ]
    assert report["version"] == SELECTION_VERSION == "v3"
    assert report["settings"] == settings_json(DEFAULTS)
    assert report["lengths"] == list(selection.lengths)
    assert report["topic_caps"] == [4, 9, 10]
    assert report["party_ids"] == PARTIES5
    assert report["pool_size"] == 120
    assert report["selected_count"] == len(selection.statements)
    assert report["eligible_count"] == sum(e["rank"] is not None for e in report["pool"])
    assert report["count_rule"] in ("coverage_met", "best_coverage", "short")
    selected = selected_numbers(report)
    assert [p["party_id"] for p in report["parties"]] == PARTIES5
    for party in report["parties"]:
        column = values[party["party_id"]]
        assert party["pool_sides"] == sum(v not in (None, 0) for v in column)
        assert party["selected_sides"] == [
            sum(column[n - 1] not in (None, 0) for n in selected[:length])
            for length in report["lengths"]
        ]
    assert [e["pool"] for e in report["pool"]] == list(range(1, 121))
    for entry in report["pool"]:
        n = entry["pool"]
        assert list(entry) == [
            "pool", "text", "topic", "context_note", "anchor", "values", "parties", "favour",
            "against", "separation", "status", "duplicate_of", "rank", "position", "tier",
        ]
        assert entry["text"] == drafts[n - 1].text and entry["topic"] == drafts[n - 1].topic
        assert entry["context_note"] == drafts[n - 1].context_note
        assert entry["anchor"] is None
        assert entry["values"] == [values[p][n - 1] for p in PARTIES5]
        found = [v for v in entry["values"] if v is not None]
        assert entry["favour"] == sum(v > 0 for v in found)
        assert entry["against"] == sum(v < 0 for v in found)
        assert entry["parties"] == entry["favour"] + entry["against"]
        assert entry["separation"] == min(entry["favour"], entry["against"])
        assert entry["status"] in (
            "selected", "context_invalid", "duplicate", "not_separating", "few_parties",
            "topic_full", "not_picked",
        )
        assert (entry["position"] is not None) == (entry["status"] == "selected")
        assert (entry["rank"] is not None) == (
            entry["status"] in ("selected", "topic_full", "not_picked")
        )
    assert report["pool"][9]["status"] == "duplicate"
    assert report["pool"][9]["duplicate_of"] == 1


# pipeline-verified-findings: the default coverage target is 50 % (60 before).


def _party2_on_first(count: int, covered: int) -> Values:
    return {
        1: [1] * count,
        2: [-1] * covered + [None] * (count - covered),
        3: [-1] * count,
        4: [1] * count,
    }


def test_default_coverage_target_is_50_percent() -> None:
    assert DEFAULTS.min_party_coverage_percent == 50
    values = _party2_on_first(60, 20)
    selection = select_statements(pool(60), positions(values), [1, 2, 3, 4], DEFAULTS)
    report = selection.report
    # Party 2's 20 Statements rank first (4 Parties); 20 of 40 is exactly 50 %.
    assert (report["selected_count"], report["count_rule"]) == (40, "coverage_met")
    party2 = next(p for p in report["parties"] if p["party_id"] == 2)
    assert party2["selected_sides"] == [15, 20, 20]
    assert check_party_coverage(as_input(selection, DEFAULTS, [1, 2, 3, 4])) == []

    # At an explicit 60 % no count from 35 reaches it (20 of 33): the best ratio is 35.
    strict = dataclasses.replace(DEFAULTS, min_party_coverage_percent=60)
    report = select_statements(pool(60), positions(values), [1, 2, 3, 4], strict).report
    assert (report["selected_count"], report["count_rule"]) == (35, "best_coverage")


# pipeline-statement-clarity-context: rule 0 (context notes) and anchors (kept by v3).


def test_a_failing_note_is_never_selected_and_its_duplicate_can_stay() -> None:
    drafts = pool(50)
    # Statement 4's note is too short; Statement 40 repeats its text with a valid note.
    drafts[3] = draft(drafts[3].text, drafts[3].topic, "Corta.")
    drafts[39] = draft(drafts[3].text, drafts[39].topic, note(40))
    # Statement 7's note uses an evaluative word.
    drafts[6] = draft(drafts[6].text, drafts[6].topic, "Una medida polémica " + note(7))

    selection = select_statements(drafts, positions(separating(50)), [1, 2, 3], DEFAULTS)

    entries = selection.report["pool"]
    assert [(e["pool"], e["status"], e["tier"], e["rank"]) for e in entries
            if e["status"] == "context_invalid"] == [(4, "context_invalid", None, None),
                                                     (7, "context_invalid", None, None)]
    # Duplicate detection runs only among the eligible Statements: 40 is no duplicate.
    assert entries[39]["duplicate_of"] is None and entries[39]["status"] != "duplicate"
    assert 4 not in selected_numbers(selection.report)
    assert 7 not in selected_numbers(selection.report)
    assert "context_note" not in selection.report["projected_failures"]
    assert all(s.context_note in (note(n) for n in range(1, 51)) for s in selection.statements)


def test_whitespace_note_is_context_invalid() -> None:
    drafts = pool(40)
    # The schema refuses a blank note; model_construct stands for one that got through.
    drafts[0] = PoolStatement.model_construct(
        text=drafts[0].text, topic=drafts[0].topic, context_note=" \n ", anchor=None
    )
    selection = select_statements(drafts, positions(separating(40)), [1, 2, 3], DEFAULTS)
    assert selection.report["pool"][0]["status"] == "context_invalid"


def test_anchors_get_no_preference() -> None:
    plain = pool(120)
    anchored = [
        draft(d.text, d.topic, d.context_note, anchor=(n % 7) + 1 if n % 3 == 0 else None)
        for n, d in enumerate(plain, start=1)
    ]
    values = _mixed_values(120)

    base = select_statements(plain, positions(values), PARTIES5, DEFAULTS)
    other = select_statements(anchored, positions(values), PARTIES5, DEFAULTS)

    assert selected_numbers(other.report) == selected_numbers(base.report)
    assert [e["anchor"] for e in other.report["pool"]] == [d.anchor for d in anchored]


def test_anchor_summary_reports_pool_selected_and_missing() -> None:
    rows = [
        {"pool": 1, "anchor": 3, "status": "selected"},
        {"pool": 2, "anchor": 1, "status": "not_picked"},
        {"pool": 3, "anchor": 3, "status": "duplicate"},
        {"pool": 4, "anchor": None, "status": "selected"},
        {"pool": 5, "anchor": 5, "status": "selected"},
    ]
    assert anchor_summary(rows, 5, 6) == {
        "dataset_version_id": 5,
        "count": 6,
        "in_pool": [1, 3, 5],
        "selected": [3, 5],
        "missing": [2, 4, 6],
    }
    assert anchor_summary([], None, 0) == {
        "dataset_version_id": None, "count": 0, "in_pool": [], "selected": [], "missing": []
    }
