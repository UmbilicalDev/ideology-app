"""Statement Selection: choose the Questionnaire's Statements from the Statement Pool.

Pure: no database, LLM, clock or randomness, and no iteration over unordered
sets, so the same pool, Party Positions, Party ids and settings always give the
same selection and report. Every Party is treated the same: the order of
``party_ids`` and which Party owns which values never matter.

The rules (``pipeline-coverage-selection``), with pool numbers 1-based:

1. Duplicates (``validation.check_statement_uniqueness`` on the pool) are left
   out; the first copy in pool order stays.
2. Statements that separate the Parties (``check_statement_separation``) are
   tier 1; the others are tier 2 (every Statement with fewer than two Parties).
3. No topic gets more than ``topic_cap`` picks:
   ``max(1, max_topic_share_percent * min_statements // 100)``, so any count of
   at least ``min_statements`` passes ``topic_spread``.
4. Greedy leximin: repeatedly pick the tier-1 Statement whose stances most
   raise the worst-covered Party's count (then the next worst, and so on), ties
   by more distinct values, then a larger spread, then the lower pool number,
   until ``max_statements``. Tier 2 is used only to reach ``min_statements``.
5. Count: the largest prefix of that sequence, from ``min_statements`` up, on
   which ``check_party_coverage`` passes; if none passes, the one with the best
   worst-Party coverage ratio (ties: the larger).

The selected Statements keep their pool order, text and topic, and are
renumbered 1..n; their Party Positions keep value and Evidence.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from ideology_app.config import ValidationSettings
from ideology_app.pipeline.positions import PositionResult
from ideology_app.pipeline.prompts import StatementDraft
from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PositionRow,
    StatementRow,
    ValidationInput,
    normalize_for_match,
    run_checks,
)
from ideology_app.validation.party_coverage import check_party_coverage
from ideology_app.validation.statement_separation import check_statement_separation
from ideology_app.validation.statement_uniqueness import check_statement_uniqueness

SELECTION_VERSION = "v1"

RULE_COVERAGE_MET = "coverage_met"
RULE_BEST_COVERAGE = "best_coverage"
RULE_SHORT = "short"

STATUS_SELECTED = "selected"
STATUS_DUPLICATE = "duplicate"
STATUS_TOPIC_FULL = "topic_full"
STATUS_NOT_PICKED = "not_picked"

# Every check except ``evidence_quotes``, which needs the Source Documents.
_PROJECTED_CHECKS = tuple(check for check in CHECKS if check.name != EVIDENCE_QUOTES.name)


@dataclass(frozen=True)
class Selection:
    """The selected Statements (pool order), their Positions renumbered 1..n, and the report.

    ``positions`` maps each Party id of the input to one ``PositionResult`` per
    selected Statement, in order. ``report`` is plain JSON data, stored on the
    run as ``pipeline_runs.statement_selection``.
    """

    statements: tuple[StatementDraft, ...]
    positions: dict[int, list[PositionResult]]
    report: dict[str, Any]


def topic_cap(settings: ValidationSettings) -> int:
    """The most Statements one topic may get in a selection."""
    return max(1, settings.max_topic_share_percent * settings.min_statements // 100)


def _validation_input(
    numbers: Sequence[int],
    pool: Sequence[StatementDraft],
    values: Mapping[int, Mapping[int, int | None]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
) -> ValidationInput:
    """The pool Statements ``numbers`` as Validation data (id = position = pool number)."""
    return ValidationInput(
        statements=tuple(
            StatementRow(id=n, position=n, text=pool[n - 1].text, topic=pool[n - 1].topic)
            for n in numbers
        ),
        positions=tuple(
            PositionRow(
                statement_id=n,
                statement_position=n,
                party_id=party_id,
                value=values[n][party_id],
                document_id=None,
                quote=None,
                page=None,
                url=None,
            )
            for n in numbers
            for party_id in party_ids
        ),
        party_ids=tuple(party_ids),
        settings=settings,
    )


def _count(
    sequence: Sequence[int],
    pool: Sequence[StatementDraft],
    values: Mapping[int, Mapping[int, int | None]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
) -> tuple[int, str]:
    """How many picks of ``sequence`` to keep, and the rule that decided it."""
    length = len(sequence)
    low = settings.min_statements
    if length <= low:
        return length, RULE_SHORT
    for n in range(length, low - 1, -1):
        data = _validation_input(sequence[:n], pool, values, party_ids, settings)
        if not check_party_coverage(data):
            return n, RULE_COVERAGE_MET
    best_n, best_worst = low, -1
    for n in range(low, length + 1):
        worst = min(
            (sum(values[s][p] is not None for s in sequence[:n]) for p in party_ids),
            default=0,
        )
        # worst / n >= best_worst / best_n, compared as integers; ties go to the larger n.
        if best_worst < 0 or worst * best_n >= best_worst * n:
            best_n, best_worst = n, worst
    return best_n, RULE_BEST_COVERAGE


def select_statements(
    pool: Sequence[StatementDraft],
    positions: Mapping[int, Sequence[PositionResult]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
) -> Selection:
    """Choose the Questionnaire's Statements from ``pool`` (see the module docstring).

    ``positions`` maps Party id to its ``PositionResult``s, numbered by 1-based
    pool position (``extract_positions`` over the pool); a missing entry is
    ``no stance``. ``party_ids`` are the Election's Parties; ``settings`` are
    the run's ``ValidationSettings`` (the same object Validation uses).
    """
    party_ids = list(party_ids)
    numbers = list(range(1, len(pool) + 1))
    by_number: dict[int, dict[int, PositionResult]] = {
        party_id: {r.statement_number: r for r in results}
        for party_id, results in positions.items()
    }

    def value(n: int, party_id: int) -> int | None:
        result = by_number.get(party_id, {}).get(n)
        return None if result is None else result.value

    values = {n: {p: value(n, p) for p in party_ids} for n in numbers}
    stances: dict[int, int] = {}
    distinct: dict[int, int] = {}
    spread: dict[int, int] = {}
    for n in numbers:
        found = [v for v in values[n].values() if v is not None]
        stances[n] = len(found)
        distinct[n] = len(dict.fromkeys(found))
        spread[n] = max(found) - min(found) if len(found) >= 2 else 0

    pool_data = _validation_input(numbers, pool, values, party_ids, settings)
    duplicates = {e.statement_id for e in check_statement_uniqueness(pool_data)}
    first_by_text: dict[str, int] = {}
    duplicate_of: dict[int, int] = {}
    for n in numbers:
        first = first_by_text.setdefault(normalize_for_match(pool[n - 1].text), n)
        if n in duplicates:
            duplicate_of[n] = first
    if len(party_ids) < 2:
        not_separating = set(numbers)
    else:
        not_separating = {e.statement_id for e in check_statement_separation(pool_data)}
    unique = [n for n in numbers if n not in duplicates]
    tier = {n: 2 if n in not_separating else 1 for n in unique}

    cap = topic_cap(settings)
    coverage = {p: 0 for p in party_ids}
    per_topic: Counter[str] = Counter()
    sequence: list[int] = []

    def key(n: int) -> tuple[tuple[int, ...], int, int, int]:
        after = sorted(coverage[p] + (values[n][p] is not None) for p in party_ids)
        return (tuple(after), distinct[n], spread[n], -n)

    for wanted_tier, limit in ((1, settings.max_statements), (2, settings.min_statements)):
        remaining = [n for n in unique if tier[n] == wanted_tier]
        while len(sequence) < limit:
            allowed = [n for n in remaining if per_topic[pool[n - 1].topic] < cap]
            if not allowed:
                break
            pick = max(allowed, key=key)
            remaining.remove(pick)
            sequence.append(pick)
            per_topic[pool[pick - 1].topic] += 1
            for p in party_ids:
                coverage[p] += values[pick][p] is not None

    count, rule = _count(sequence, pool, values, party_ids, settings)
    selected = sorted(sequence[:count])
    new_position = {n: i for i, n in enumerate(selected, start=1)}
    statements = tuple(pool[n - 1] for n in selected)
    renumbered = {
        party_id: [
            replace(by_number[party_id][n], statement_number=new_position[n])
            if n in by_number[party_id]
            else PositionResult(statement_number=new_position[n], value=None)
            for n in selected
        ]
        for party_id in positions
    }

    selected_data = _validation_input(selected, pool, values, party_ids, settings)
    projected = [r.name for r in run_checks(selected_data, _PROJECTED_CHECKS) if not r.passed]
    pick_index = {n: i for i, n in enumerate(sequence, start=1)}

    def status(n: int) -> str:
        if n in new_position:
            return STATUS_SELECTED
        if n in duplicates:
            return STATUS_DUPLICATE
        if n not in pick_index and per_topic[pool[n - 1].topic] >= cap:
            return STATUS_TOPIC_FULL
        return STATUS_NOT_PICKED

    report: dict[str, Any] = {
        "version": SELECTION_VERSION,
        "settings": asdict(settings),
        "topic_cap": cap,
        "party_ids": list(party_ids),
        "pool_size": len(pool),
        "selected_count": len(selected),
        "count_rule": rule,
        "projected_failures": projected,
        "parties": [
            {
                "party_id": p,
                "pool_stances": sum(values[n][p] is not None for n in numbers),
                "selected_stances": sum(values[n][p] is not None for n in selected),
            }
            for p in party_ids
        ],
        "pool": [
            {
                "pool": n,
                "text": pool[n - 1].text,
                "topic": pool[n - 1].topic,
                "values": [values[n][p] for p in party_ids],
                "stances": stances[n],
                "distinct": distinct[n],
                "spread": spread[n],
                "tier": tier.get(n),
                "status": status(n),
                "duplicate_of": duplicate_of.get(n),
                "pick": pick_index.get(n),
                "position": new_position.get(n),
            }
            for n in numbers
        ],
    }
    return Selection(statements, renumbered, report)


__all__ = [
    "SELECTION_VERSION",
    "Selection",
    "select_statements",
    "topic_cap",
]
