"""Constituency Selection of a v2 run (constituency-selection-validation).

The step between ``V2Pool`` and ``_finish_v2``: deterministic, AI-free and
Party-identical. For each of the 52 Constituencies (``CONSTITUENCIES`` order)
it applies ``constituency_rules.evaluate`` to the pool, the Positions (with
their Evidence Constituencies, S5) and the run's frozen candidature copy, and
returns what ``_finish_v2`` writes in the Dataset Version's commit: one row per
Constituency (available, or unavailable with its reason), the ordered
Statements of each available one, the candidature snapshot with each Excluded
Party's reason, and the ``statement_selection["constituencies"]`` report.

Pure: no database, LLM, clock or randomness, and no iteration over unordered
sets. A Constituency below a minimum is stored unavailable; it never fails the
run (K8 is Validation's ``constituency_availability``). Statements valid in
no available Constituency stay in the pool (K7) and are listed in the report.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.config import ConstituencySettings
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.constituency_rules import (
    ConstituencyResult,
    RuleStatement,
    Stance,
    evaluate,
    party_sides,
)
from ideology_app.pipeline.v2.gate import Phase4Input
from ideology_app.pipeline.v2.pool import PoolDraft
from ideology_app.pipeline.v2.positions import V2Position

SELECTION_VERSION = "v2-constituency-1"


@dataclass(frozen=True)
class ConstituencyRow:
    """One ``dataset_version_constituencies`` row (plain data)."""

    code: str
    available: bool
    unavailable_reason: str | None
    valid_statement_count: int
    offered_lengths: tuple[int, ...]
    detail: dict[str, Any] | None


@dataclass(frozen=True)
class CandidatureRow:
    """One ``dataset_version_candidatures`` row: who runs where, Excluded with its reason."""

    party_id: int
    code: str
    excluded_reason: str | None


@dataclass(frozen=True)
class ConstituencySelection:
    """What ``_finish_v2`` writes for the Constituencies.

    ``rows`` has one entry per Constituency in code order; ``statements_by_code``
    maps each available code to its pool numbers (1-based, = ``statements.position``)
    in rank order; ``snapshot`` is sorted by Party id then code.
    """

    rows: tuple[ConstituencyRow, ...]
    statements_by_code: Mapping[str, tuple[int, ...]]
    snapshot: tuple[CandidatureRow, ...]
    report: dict[str, Any]


def rule_statements(
    statements: Sequence[PoolDraft], positions: Mapping[int, Sequence[V2Position]]
) -> tuple[RuleStatement, ...]:
    """The pool as ``constituency_rules`` reads it: key and position = the pool number."""
    return tuple(
        RuleStatement(
            key=number,
            position=number,
            topic=draft.category,
            stances={
                party_id: Stance(
                    party_positions[number - 1].value,
                    tuple(ref.constituencies for ref in party_positions[number - 1].evidence),
                )
                for party_id, party_positions in sorted(positions.items())
            },
        )
        for number, draft in enumerate(statements, start=1)
    )


def running_parties(
    candidatures: Mapping[int, Sequence[str]], excluded: Sequence[int], code: str
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """``(R(c), E(c))``: the non-Excluded and the Excluded Parties running in ``code``, by id."""
    left_out = set(excluded)
    running = [party_id for party_id in sorted(candidatures) if code in candidatures[party_id]]
    return (
        tuple(p for p in running if p not in left_out),
        tuple(p for p in running if p in left_out),
    )


def _first_length_sides(
    result: ConstituencyResult, by_key: Mapping[int, RuleStatement]
) -> dict[int, int] | None:
    if not result.lengths:
        return None
    first = [by_key[key] for key in result.ordered[: result.lengths[0]]]
    return dict(party_sides(first, result.parties, result.code))


def _topic_max_share(
    result: ConstituencyResult, by_key: Mapping[int, RuleStatement]
) -> list[int]:
    """Per offered length L, the largest share (percent, rounded down) of one topic in 1..L."""
    shares: list[int] = []
    for length in result.lengths:
        counts: dict[str, int] = {}
        for key in result.ordered[:length]:
            topic = by_key[key].topic
            counts[topic] = counts.get(topic, 0) + 1
        shares.append(max(counts.values()) * 100 // length)
    return shares


def select_constituencies(
    statements: Sequence[PoolDraft],
    positions: Mapping[int, Sequence[V2Position]],
    phase4: Phase4Input,
    max_topic_share_percent: int,
    settings: ConstituencySettings,
) -> ConstituencySelection:
    """Decide every Constituency of a v2 Dataset Version (see the module docstring).

    ``statements`` and ``positions`` are the ``V2Pool``'s (one ``V2Position``
    per Statement for each non-Excluded Party); ``phase4`` gives the
    candidature snapshot and the Excluded Parties; ``max_topic_share_percent``
    is the run's ``ValidationSettings`` value; ``settings`` the minimums.
    """
    pool = rule_statements(statements, positions)
    by_key = {s.key: s for s in pool}
    excluded_reason = {p.party_id: p.reason for p in phase4.excluded}
    excluded_ids = sorted(excluded_reason)
    rows: list[ConstituencyRow] = []
    ordered: dict[str, tuple[int, ...]] = {}
    report_rows: list[dict[str, Any]] = []
    for code, _ in CONSTITUENCIES:
        running, left_out = running_parties(phase4.candidatures, excluded_ids, code)
        result = evaluate(
            code,
            pool,
            running,
            min_statements=settings.v2_min_statements,
            min_party_sides=settings.v2_min_party_sides,
            max_topic_share_percent=max_topic_share_percent,
        )
        state = result.availability
        rows.append(
            ConstituencyRow(
                code=code,
                available=state.available,
                unavailable_reason=None if state.reason is None else state.reason.value,
                valid_statement_count=len(result.valid),
                offered_lengths=result.lengths,
                detail=state.detail,
            )
        )
        if state.available:
            ordered[code] = result.ordered
        first = _first_length_sides(result, by_key)
        report_rows.append(
            {
                "code": code,
                "parties": list(result.parties),
                "excluded": list(left_out),
                "valid": len(result.valid),
                "lengths": list(result.lengths),
                "party_sides": [
                    {
                        "party_id": party_id,
                        "sides": sides,
                        "first_length_sides": None if first is None else first[party_id],
                    }
                    for party_id, sides in result.sides
                ],
                "topic_max_share": _topic_max_share(result, by_key),
            }
        )
    in_questionnaire = {key for keys in ordered.values() for key in keys}
    snapshot = tuple(
        CandidatureRow(party_id, code, excluded_reason.get(party_id))
        for party_id in sorted(phase4.candidatures)
        for code in sorted(phase4.candidatures[party_id])
    )
    report: dict[str, Any] = {
        "version": SELECTION_VERSION,
        "settings": {
            "v2_min_statements": settings.v2_min_statements,
            "v2_min_party_sides": settings.v2_min_party_sides,
            "max_topic_share_percent": max_topic_share_percent,
        },
        "available": sum(row.available for row in rows),
        "unavailable": [
            {"code": row.code, "reason": row.unavailable_reason}
            for row in rows
            if not row.available
        ],
        "valid_nowhere": [s.key for s in pool if s.key not in in_questionnaire],
        "rows": report_rows,
    }
    return ConstituencySelection(tuple(rows), ordered, snapshot, report)


__all__ = [
    "SELECTION_VERSION",
    "CandidatureRow",
    "ConstituencyRow",
    "ConstituencySelection",
    "rule_statements",
    "running_parties",
    "select_constituencies",
]
