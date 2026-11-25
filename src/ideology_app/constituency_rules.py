"""Per-Constituency Statement rules of a v2 Dataset Version (constituency-selection-validation).

Pure (standard library only, like ``constituencies``): no database, LLM, clock
or randomness, and no iteration over unordered sets, so the same input always
gives the same result. Every Party is treated the same: results depend only on
how many Parties take each side, never on which Party or on Party ids.

The one source of these rules. ``pipeline.v2.selection`` computes the stored
rows with them before the Dataset Version is written, ``validation``
recomputes them from the stored rows, and ``public-dataset-api-v2`` will read
Party Positions per Constituency only through ``effective_value``.

Terms: R(c) are the non-Excluded Parties running in Constituency c (the
Dataset Version's frozen candidature copy). A value is *sided* at +1/+2 (in
favour) or -1/-2 (against); 0 and ``no stance`` are on neither side.

- **S5** (``effective_value``): a Party's value in c is its Position's value
  only when one of the Position's Evidence Proposals counts in c; otherwise it
  is ``no stance`` there.
- **K1 validity** (``is_valid``): a Statement is valid in c when, among R(c)
  with S5 values, at least one Party is in favour and at least one against.
- **K2 priority order** (``priority_order``): the valid Statements ranked by
  ``(-sided, -separation, position)``, then topic deferral for each offered
  length L below n: ``cap_L = max(1, share * L // 100)``; at rank k up to the
  largest such L the first remaining Statement whose topic has fewer than
  ``cap(k)`` placed so far is taken (``cap(k)``: the cap of the first such
  L >= k), else the first remaining one. Every valid Statement is placed.
- **K5 availability** (``availability``): the first rule that fails gives the
  reason: ``fewer_than_two_parties``, ``too_few_statements``,
  ``low_party_coverage``.
- **K10 offered lengths** (``offered_lengths``): ``OFFERED_LENGTHS`` up to n,
  or ``[n]`` ("Todas (N)") when n is below the shortest one.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# The questionnaire lengths a Constituency offers (user decision; not configurable).
OFFERED_LENGTHS: tuple[int, ...] = (20, 30, 40, 50)


class UnavailableReason(StrEnum):
    """Why a Constituency is unavailable; the first rule that fails, in this order."""

    FEWER_THAN_TWO_PARTIES = "fewer_than_two_parties"
    TOO_FEW_STATEMENTS = "too_few_statements"
    LOW_PARTY_COVERAGE = "low_party_coverage"


@dataclass(frozen=True)
class Stance:
    """A Party's stored Position on a Statement: ``value`` (None: ``no stance``) and,
    per Evidence Proposal in rank order, the Constituency codes where it counts."""

    value: int | None
    evidence: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class RuleStatement:
    """A Statement as the rules read it.

    ``key`` identifies it in results (a pool number or a Statement id);
    ``position`` is ``statements.position`` (the pool order, the last tie-break);
    ``stances`` maps Party id to its ``Stance`` (a missing Party is ``no stance``).
    """

    key: int
    position: int
    topic: str
    stances: Mapping[int, Stance] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    """Whether a Constituency is available, else its reason and the detail stored with it."""

    available: bool
    reason: UnavailableReason | None = None
    detail: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConstituencyResult:
    """Everything the rules decide for one Constituency.

    ``parties`` are R(c) sorted by id; ``valid`` the valid Statement keys in
    priority order (also when unavailable); ``ordered`` the stored ranking
    (``valid`` when available, else empty); ``sides`` each Party of R(c) and
    its number of sided valid Statements, by Party id.
    """

    code: str
    parties: tuple[int, ...]
    valid: tuple[int, ...]
    availability: Availability
    lengths: tuple[int, ...]
    sides: tuple[tuple[int, int], ...]

    @property
    def ordered(self) -> tuple[int, ...]:
        return self.valid if self.availability.available else ()


def effective_value(
    value: int | None, evidence_constituencies: Iterable[Iterable[str]], code: str
) -> int | None:
    """S5: ``value`` when one Evidence row lists ``code``, else ``None`` (``no stance``).

    ``evidence_constituencies`` holds, per Evidence Proposal of the Position,
    the codes where it counts (``party_position_proposals.constituencies``).
    A ``no stance`` Position stays ``None``.
    """
    if value is None:
        return None
    for codes in evidence_constituencies:
        if code in codes:
            return value
    return None


def _value_in(statement: RuleStatement, party_id: int, code: str) -> int | None:
    stance = statement.stances.get(party_id)
    if stance is None:
        return None
    return effective_value(stance.value, stance.evidence, code)


def _sided(value: int | None) -> bool:
    return value is not None and value != 0


def side_counts(
    statement: RuleStatement, parties: Sequence[int], code: str
) -> tuple[int, int]:
    """``(in favour, against)`` among ``parties`` in ``code``, with S5 values."""
    favour = against = 0
    for party_id in parties:
        value = _value_in(statement, party_id, code)
        if value is not None and value > 0:
            favour += 1
        elif value is not None and value < 0:
            against += 1
    return favour, against


def is_valid(statement: RuleStatement, parties: Sequence[int], code: str) -> bool:
    """K1: at least one of ``parties`` in favour and one against in ``code``."""
    favour, against = side_counts(statement, parties, code)
    return favour > 0 and against > 0


def valid_statements(
    statements: Sequence[RuleStatement], parties: Sequence[int], code: str
) -> tuple[RuleStatement, ...]:
    """The Statements valid in ``code`` among R(c) = ``parties``, in input order."""
    if len(parties) < 2:
        return ()
    return tuple(s for s in statements if is_valid(s, parties, code))


def offered_lengths(n: int) -> tuple[int, ...]:
    """K10: the lengths an available Constituency with ``n`` valid Statements offers."""
    if n <= 0:
        return ()
    if n < OFFERED_LENGTHS[0]:
        return (n,)
    return tuple(length for length in OFFERED_LENGTHS if length <= n)


def topic_caps(n: int, max_topic_share_percent: int) -> tuple[tuple[int, int], ...]:
    """``(L, cap_L)`` for each offered length L strictly below ``n`` (K2 deferral)."""
    return tuple(
        (length, max(1, max_topic_share_percent * length // 100))
        for length in offered_lengths(n)
        if length < n
    )


def priority_order(
    statements: Sequence[RuleStatement],
    parties: Sequence[int],
    code: str,
    max_topic_share_percent: int,
) -> tuple[int, ...]:
    """K2: the keys of the Statements valid in ``code``, in that Constituency's order."""
    valid = valid_statements(statements, parties, code)

    def rank_key(statement: RuleStatement) -> tuple[int, int, int]:
        favour, against = side_counts(statement, parties, code)
        return (-(favour + against), -min(favour, against), statement.position)

    remaining = sorted(valid, key=rank_key)
    caps = topic_caps(len(remaining), max_topic_share_percent)
    capped_until = caps[-1][0] if caps else 0
    placed: Counter[str] = Counter()
    order: list[int] = []
    while remaining:
        k = len(order) + 1
        pick = remaining[0]
        if k <= capped_until:
            cap = next(c for length, c in caps if length >= k)
            pick = next((s for s in remaining if placed[s.topic] < cap), remaining[0])
        remaining.remove(pick)
        order.append(pick.key)
        placed[pick.topic] += 1
    return tuple(order)


def party_sides(
    statements: Sequence[RuleStatement], parties: Sequence[int], code: str
) -> tuple[tuple[int, int], ...]:
    """``(party id, sided Statements among ``statements``)`` for ``parties``, by Party id."""
    return tuple(
        (party_id, sum(_sided(_value_in(s, party_id, code)) for s in statements))
        for party_id in sorted(parties)
    )


def availability(
    party_count: int,
    valid_count: int,
    sides: Sequence[tuple[int, int]],
    min_statements: int,
    min_party_sides: int,
) -> Availability:
    """K5: available, or the first failing rule with its ``detail`` (plain JSON data)."""
    if party_count < 2:
        return Availability(
            False, UnavailableReason.FEWER_THAN_TWO_PARTIES, {"parties": party_count}
        )
    if valid_count < min_statements:
        return Availability(
            False,
            UnavailableReason.TOO_FEW_STATEMENTS,
            {"statements": valid_count, "minimum": min_statements},
        )
    low = [
        {"party_id": party_id, "sides": count}
        for party_id, count in sorted(sides)
        if count < min_party_sides
    ]
    if low:
        return Availability(
            False,
            UnavailableReason.LOW_PARTY_COVERAGE,
            {"parties": low, "minimum": min_party_sides},
        )
    return Availability(True)


def evaluate(
    code: str,
    statements: Sequence[RuleStatement],
    parties: Iterable[int],
    *,
    min_statements: int,
    min_party_sides: int,
    max_topic_share_percent: int,
) -> ConstituencyResult:
    """Apply K1, K2, K5 and K10 to one Constituency with R(c) = ``parties``."""
    running = tuple(sorted(parties))
    order = priority_order(statements, running, code, max_topic_share_percent)
    by_key = {s.key: s for s in statements}
    valid = tuple(by_key[key] for key in order)
    sides = party_sides(valid, running, code)
    state = availability(len(running), len(order), sides, min_statements, min_party_sides)
    lengths = offered_lengths(len(order)) if state.available else ()
    return ConstituencyResult(code, running, order, state, lengths, sides)


__all__ = [
    "OFFERED_LENGTHS",
    "Availability",
    "ConstituencyResult",
    "RuleStatement",
    "Stance",
    "UnavailableReason",
    "availability",
    "effective_value",
    "evaluate",
    "is_valid",
    "offered_lengths",
    "party_sides",
    "priority_order",
    "side_counts",
    "topic_caps",
    "valid_statements",
]
