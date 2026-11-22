"""Statement Selection: choose and order the Questionnaire's Statements from the Statement Pool.

Pure: no database, LLM, clock or randomness, and no iteration over unordered
sets, so the same pool, Party Positions, Party ids and settings always give the
same selection and report. Every Party is treated the same: the order of
``party_ids`` and which Party owns which values never matter.

The rules (``SELECTION_VERSION`` v3, ``pipeline-statement-priority-tiers``;
v2 chose by worst-Party coverage and kept pool order), with pool numbers
1-based. A Party is *in favour* of a Statement at +1/+2 and *against* it at
−1/−2; 0 and ``no stance`` count on neither side. ``parties`` is the number of
Parties in favour or against, ``separation`` the smaller of the two sides.

Each pool Statement gets exactly one status:

0. ``context_invalid``: its context note fails ``validation.check_context_note``
   on the pool, so a note that would fail Validation costs one Statement, not
   the run.
1. ``duplicate``: ``validation.check_statement_uniqueness`` on the Statements
   left by rule 0; the first copy in pool order stays.
2. ``not_separating``: no Party in favour or none against (every Statement when
   the Election has fewer than two Parties). Never used to fill up a count.
3. ``few_parties``: fewer than ``settings.min_statement_parties`` Parties in
   favour or against.
4. Otherwise it is *ranked* by ``(-parties, -separation, pool number)``.

Placement fills positions 1..``max_statements`` in ranking order: at position
k it takes the first ranked Statement whose topic has fewer than ``cap(k)``
picks; one skipped there is tried again at k+1. The caps (``topic_caps``) are
``max(1, max_topic_share_percent * L // 100)`` for each offered shorter length
L (``settings.questionnaire_lengths``) and then for ``min_statements``;
``cap(k)`` is the cap of the first length ``>= k``, else the last one. So every
offered prefix of a selection of at least ``min_statements`` passes
``topic_spread``. Placement stops at ``max_statements`` or when nothing fits.

Count: the largest prefix of that sequence, from ``min_statements`` up, on
which ``check_party_coverage`` passes for the full set; if none passes, the
one with the best worst-Party coverage ratio (ties: the larger); with no more
than ``min_statements`` placed, all of them (``short``). Cutting the tail never
changes a shorter prefix.

The selected Statements are written in priority order (position 1 = the most
Parties), keeping their text, topic and context note, with their Party
Positions (value and Evidence) renumbered 1..n. ``Selection.lengths`` are the
offered lengths below n, then n, so a questionnaire of length N is always the
first N Statements. Anchors (``PoolStatement.anchor``) get no preference.
Rules 0 and 1 depend only on Statement text and notes, so Party symmetry is
unaffected.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from ideology_app.config import ValidationSettings
from ideology_app.pipeline.positions import PositionResult
from ideology_app.pipeline.prompts import PoolStatement
from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PositionRow,
    StatementRow,
    ValidationInput,
    normalize_for_match,
    run_checks,
)
from ideology_app.validation.context_note import check_context_note
from ideology_app.validation.party_coverage import check_party_coverage
from ideology_app.validation.statement_count import expected_lengths
from ideology_app.validation.statement_uniqueness import check_statement_uniqueness

SELECTION_VERSION = "v3"

RULE_COVERAGE_MET = "coverage_met"
RULE_BEST_COVERAGE = "best_coverage"
RULE_SHORT = "short"

STATUS_SELECTED = "selected"
STATUS_CONTEXT_INVALID = "context_invalid"
STATUS_DUPLICATE = "duplicate"
STATUS_NOT_SEPARATING = "not_separating"
STATUS_FEW_PARTIES = "few_parties"
STATUS_TOPIC_FULL = "topic_full"
STATUS_NOT_PICKED = "not_picked"

# Every check except ``evidence_quotes``, which needs the Source Documents.
_PROJECTED_CHECKS = tuple(check for check in CHECKS if check.name != EVIDENCE_QUOTES.name)


@dataclass(frozen=True)
class Selection:
    """The selected Statements (priority order), their Positions renumbered 1..n, and the report.

    ``positions`` maps each Party id of the input to one ``PositionResult`` per
    selected Statement, in order. ``lengths`` are the offered questionnaire
    lengths (ascending, the last is n; ``()`` when nothing is selected), stored
    on the Dataset Version. ``report`` is plain JSON data, stored on the run as
    ``pipeline_runs.statement_selection``.
    """

    statements: tuple[PoolStatement, ...]
    positions: dict[int, list[PositionResult]]
    report: dict[str, Any]
    lengths: tuple[int, ...] = ()


def topic_caps(settings: ValidationSettings) -> tuple[int, ...]:
    """The topic cap of each offered shorter length, then of ``min_statements``."""
    share = settings.max_topic_share_percent
    return tuple(
        max(1, share * length // 100)
        for length in (*settings.questionnaire_lengths, settings.min_statements)
    )


def topic_cap(settings: ValidationSettings) -> int:
    """The most Statements one topic may get in a whole selection (the last cap)."""
    return topic_caps(settings)[-1]


def _cap_at(position: int, settings: ValidationSettings, caps: Sequence[int]) -> int:
    """``cap(k)``: the cap of the first offered shorter length ``>= position``, else the last."""
    for length, cap in zip(settings.questionnaire_lengths, caps, strict=False):
        if position <= length:
            return cap
    return caps[-1]


def _sides(value: int | None) -> bool:
    """True when ``value`` is in favour or against (not 0, not ``no stance``)."""
    return value is not None and value != 0


def _validation_input(
    numbers: Sequence[int],
    pool: Sequence[PoolStatement],
    values: Mapping[int, Mapping[int, int | None]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
    lengths: tuple[int, ...] = (),
) -> ValidationInput:
    """The pool Statements ``numbers``, in that order, as Validation data.

    Statement id = pool number; position = index in ``numbers`` (1-based).
    """
    return ValidationInput(
        statements=tuple(
            StatementRow(
                id=n,
                position=i,
                text=pool[n - 1].text,
                topic=pool[n - 1].topic,
                context_note=pool[n - 1].context_note,
            )
            for i, n in enumerate(numbers, start=1)
        ),
        positions=tuple(
            PositionRow(
                statement_id=n,
                statement_position=i,
                party_id=party_id,
                value=values[n][party_id],
                document_id=None,
                quote=None,
                page=None,
                url=None,
            )
            for i, n in enumerate(numbers, start=1)
            for party_id in party_ids
        ),
        party_ids=tuple(party_ids),
        settings=settings,
        lengths=lengths,
    )


def _count(
    sequence: Sequence[int],
    pool: Sequence[PoolStatement],
    values: Mapping[int, Mapping[int, int | None]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
) -> tuple[int, str]:
    """How many Statements of ``sequence`` to keep, and the rule that decided it."""
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
            (sum(_sides(values[s][p]) for s in sequence[:n]) for p in party_ids),
            default=0,
        )
        # worst / n >= best_worst / best_n, compared as integers; ties go to the larger n.
        if best_worst < 0 or worst * best_n >= best_worst * n:
            best_n, best_worst = n, worst
    return best_n, RULE_BEST_COVERAGE


def select_statements(
    pool: Sequence[PoolStatement],
    positions: Mapping[int, Sequence[PositionResult]],
    party_ids: Sequence[int],
    settings: ValidationSettings,
) -> Selection:
    """Choose and order the Questionnaire's Statements from ``pool`` (see the module docstring).

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
    favour = {n: sum(v is not None and v > 0 for v in values[n].values()) for n in numbers}
    against = {n: sum(v is not None and v < 0 for v in values[n].values()) for n in numbers}
    sided = {n: favour[n] + against[n] for n in numbers}
    separation = {n: min(favour[n], against[n]) for n in numbers}

    pool_data = _validation_input(numbers, pool, values, party_ids, settings)
    context_invalid = {e.statement_id for e in check_context_note(pool_data)}
    eligible = [n for n in numbers if n not in context_invalid]
    eligible_data = _validation_input(eligible, pool, values, party_ids, settings)
    duplicates = {e.statement_id for e in check_statement_uniqueness(eligible_data)}
    first_by_text: dict[str, int] = {}
    duplicate_of: dict[int, int] = {}
    for n in eligible:
        first = first_by_text.setdefault(normalize_for_match(pool[n - 1].text), n)
        if n in duplicates:
            duplicate_of[n] = first

    filtered: dict[int, str] = {}
    for n in eligible:
        if n in duplicates:
            continue
        if len(party_ids) < 2 or favour[n] == 0 or against[n] == 0:
            filtered[n] = STATUS_NOT_SEPARATING
        elif sided[n] < settings.min_statement_parties:
            filtered[n] = STATUS_FEW_PARTIES
    ranked = sorted(
        (n for n in eligible if n not in duplicates and n not in filtered),
        key=lambda n: (-sided[n], -separation[n], n),
    )
    rank = {n: i for i, n in enumerate(ranked, start=1)}

    caps = topic_caps(settings)
    per_topic: Counter[str] = Counter()
    sequence: list[int] = []
    remaining = list(ranked)
    while len(sequence) < settings.max_statements:
        cap = _cap_at(len(sequence) + 1, settings, caps)
        pick = next((n for n in remaining if per_topic[pool[n - 1].topic] < cap), None)
        if pick is None:
            break
        remaining.remove(pick)
        sequence.append(pick)
        per_topic[pool[pick - 1].topic] += 1
    last_cap = _cap_at(len(sequence) + 1, settings, caps)

    count, rule = _count(sequence, pool, values, party_ids, settings)
    selected = sequence[:count]
    lengths = expected_lengths(count, settings)
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

    selected_data = _validation_input(selected, pool, values, party_ids, settings, lengths)
    projected = [r.name for r in run_checks(selected_data, _PROJECTED_CHECKS) if not r.passed]
    placed = set(sequence)

    def status(n: int) -> str:
        if n in new_position:
            return STATUS_SELECTED
        if n in context_invalid:
            return STATUS_CONTEXT_INVALID
        if n in duplicates:
            return STATUS_DUPLICATE
        if n in filtered:
            return filtered[n]
        if n not in placed and per_topic[pool[n - 1].topic] >= last_cap:
            return STATUS_TOPIC_FULL
        return STATUS_NOT_PICKED

    def tier(position: int | None) -> int | None:
        if position is None:
            return None
        return next(length for length in lengths if length >= position)

    report: dict[str, Any] = {
        "version": SELECTION_VERSION,
        # JSON-native: tuples (word list, lengths) as lists.
        "settings": {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in asdict(settings).items()
        },
        "lengths": list(lengths),
        "topic_caps": list(caps),
        "party_ids": list(party_ids),
        "pool_size": len(pool),
        "eligible_count": len(ranked),
        "selected_count": len(selected),
        "count_rule": rule,
        "projected_failures": projected,
        "parties": [
            {
                "party_id": p,
                "pool_sides": sum(_sides(values[n][p]) for n in numbers),
                "selected_sides": [
                    sum(_sides(values[n][p]) for n in selected[:length]) for length in lengths
                ],
            }
            for p in party_ids
        ],
        "pool": [
            {
                "pool": n,
                "text": pool[n - 1].text,
                "topic": pool[n - 1].topic,
                "context_note": pool[n - 1].context_note,
                "anchor": pool[n - 1].anchor,
                "values": [values[n][p] for p in party_ids],
                "parties": sided[n],
                "favour": favour[n],
                "against": against[n],
                "separation": separation[n],
                "status": status(n),
                "duplicate_of": duplicate_of.get(n),
                "rank": rank.get(n),
                "position": new_position.get(n),
                "tier": tier(new_position.get(n)),
            }
            for n in numbers
        ],
    }
    return Selection(statements, renumbered, report, lengths)


def anchor_summary(
    pool_rows: Sequence[Mapping[str, Any]],
    dataset_version_id: int | None,
    anchor_count: int,
) -> dict[str, Any]:
    """What became of the anchors, from a selection report's ``pool`` rows.

    ``in_pool``: the sorted anchor numbers some pool Statement carries;
    ``selected``: those carried by a selected Statement; ``missing``: the
    numbers 1..``anchor_count`` no pool Statement carries.
    ``dataset_version_id`` is the anchor Dataset Version (None without one).
    """
    in_pool = sorted({row["anchor"] for row in pool_rows if row.get("anchor") is not None})
    selected = sorted(
        {
            row["anchor"]
            for row in pool_rows
            if row.get("anchor") is not None and row.get("status") == STATUS_SELECTED
        }
    )
    present = set(in_pool)
    return {
        "dataset_version_id": dataset_version_id,
        "count": anchor_count,
        "in_pool": in_pool,
        "selected": selected,
        "missing": [k for k in range(1, anchor_count + 1) if k not in present],
    }


__all__ = [
    "SELECTION_VERSION",
    "STATUS_CONTEXT_INVALID",
    "STATUS_FEW_PARTIES",
    "STATUS_NOT_SEPARATING",
    "Selection",
    "anchor_summary",
    "select_statements",
    "topic_cap",
    "topic_caps",
]
