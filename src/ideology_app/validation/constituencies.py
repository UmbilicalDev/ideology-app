"""The per-Constituency checks of a v2 run (constituency-selection-validation).

They replace legacy checks 3-6 (coverage, separation, count, topic spread)
for v2 Dataset Versions. Each recomputes, with ``constituency_rules`` only,
what Constituency Selection stored, from the stored Positions, their Evidence
Constituencies (S5) and the frozen candidature copy. By construction they
pass; a failure means rows were corrupted or written inconsistently. A
Constituency below a minimum is never a failure: it is stored unavailable.

- ``constituency_snapshot``: one row per seeded Constituency; every Party with
  Positions runs somewhere and is not Excluded; an Excluded Party has no
  Positions and one reason on every row; every non-Excluded Party of the copy
  has Positions; every Evidence Proposal counts only where its Party runs.
- ``constituency_validity`` (check 4): an available Constituency lists exactly
  the valid Statements (K1); an unavailable one lists none.
- ``constituency_availability`` (checks 3 and 5): availability, reason,
  detail, n(c) and offered lengths equal K5/K10; at least one Constituency is
  available (K8).
- ``constituency_order``: ranks are 1..n in the K2 order.

Messages about one Constituency start with ``constituency CC: ``.
"""

from collections.abc import Mapping, Sequence

from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.constituency_rules import (
    RuleStatement,
    Stance,
    evaluate,
    priority_order,
    valid_statements,
)
from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NO_CONSTITUENCY_AVAILABLE = "no constituency is available"


def _prefix(code: str) -> str:
    return f"constituency {code}: "


def rule_statements(data: ValidationInput) -> tuple[RuleStatement, ...]:
    """The stored Statements as ``constituency_rules`` reads them (key: Statement id)."""
    stances: dict[int, dict[int, Stance]] = {}
    for p in data.positions:
        stances.setdefault(p.statement_id, {})[p.party_id] = Stance(
            p.value,
            tuple(row.constituencies for row in data.evidence.get((p.statement_id, p.party_id), ())),
        )
    return tuple(
        RuleStatement(key=s.id, position=s.position, topic=s.topic, stances=stances.get(s.id, {}))
        for s in data.statements
    )


def _snapshot(data: ValidationInput) -> tuple[dict[int, list[str]], dict[int, list[str | None]]]:
    """Party id -> its codes, and Party id -> its rows' excluded reasons (snapshot order)."""
    codes: dict[int, list[str]] = {}
    reasons: dict[int, list[str | None]] = {}
    for row in data.candidatures:
        codes.setdefault(row.party_id, []).append(row.code)
        reasons.setdefault(row.party_id, []).append(row.excluded_reason)
    return codes, reasons


def running(data: ValidationInput, code: str) -> tuple[int, ...]:
    """R(c): the Parties of the copy running in ``code`` with no excluded reason, by id."""
    codes, reasons = _snapshot(data)
    return tuple(
        party_id
        for party_id in sorted(codes)
        if code in codes[party_id] and all(r is None for r in reasons[party_id])
    )


def check_constituency_snapshot(data: ValidationInput) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    seeded = [code for code, _ in CONSTITUENCIES]
    stored = [row.code for row in data.constituency_rows]
    if sorted(stored) != seeded:
        missing = [c for c in seeded if c not in stored]
        unexpected = sorted({c for c in stored if c not in seeded or stored.count(c) > 1})
        entries.append(
            ReportEntry(
                f"constituency rows: {len(stored)} stored, expected one per seeded "
                f"constituency (missing: {', '.join(missing) or 'none'}; "
                f"unexpected or repeated: {', '.join(unexpected) or 'none'})"
            )
        )
    codes, reasons = _snapshot(data)
    with_positions = set(data.party_ids)
    for party_id in data.party_ids:
        if party_id not in codes:
            entries.append(
                ReportEntry(f"party {party_id} has positions but no candidature rows", party_id=party_id)
            )
        elif any(r is not None for r in reasons[party_id]):
            entries.append(
                ReportEntry(f"party {party_id} has positions but is excluded", party_id=party_id)
            )
    for party_id in sorted(codes):
        party_reasons = reasons[party_id]
        if any(r is not None for r in party_reasons):
            if len(set(party_reasons)) > 1:
                entries.append(
                    ReportEntry(
                        f"party {party_id} has different excluded reasons on its candidature rows",
                        party_id=party_id,
                    )
                )
        elif data.statements and party_id not in with_positions:
            entries.append(
                ReportEntry(
                    f"party {party_id} is not excluded but has no positions", party_id=party_id
                )
            )
    for (statement_id, party_id), rows in sorted(data.evidence.items()):
        allowed = set(codes.get(party_id, ()))
        for row in rows:
            outside = sorted(set(row.constituencies) - allowed)
            if outside:
                entries.append(
                    ReportEntry(
                        f"evidence proposal {row.proposal_id} counts in "
                        f"{', '.join(outside)}, where party {party_id} does not run",
                        statement_id=statement_id,
                        party_id=party_id,
                    )
                )
    return entries


def _listed(data: ValidationInput, code: str) -> list[int]:
    return [statement_id for _, statement_id in data.constituency_statements.get(code, ())]


def check_constituency_validity(data: ValidationInput) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    statements = rule_statements(data)
    position = {s.id: s.position for s in data.statements}
    stored = {row.code for row in data.constituency_rows}
    for row in data.constituency_rows:
        listed = _listed(data, row.code)
        if not row.available:
            if listed:
                entries.append(
                    ReportEntry(f"{_prefix(row.code)}unavailable but lists {len(listed)} statements")
                )
            continue
        valid = {s.key for s in valid_statements(statements, running(data, row.code), row.code)}
        missing = sorted(position[k] for k in valid - set(listed))
        extra = sorted(position.get(k, 0) for k in set(listed) - valid)
        if missing or extra:
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}listed statements differ from the valid ones "
                    f"(missing positions: {', '.join(map(str, missing)) or 'none'}; "
                    f"not valid: {', '.join(map(str, extra)) or 'none'})"
                )
            )
    for code in sorted(set(data.constituency_statements) - stored):
        entries.append(ReportEntry(f"{_prefix(code)}lists statements but has no constituency row"))
    return entries


def check_constituency_availability(data: ValidationInput) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    statements = rule_statements(data)
    settings = data.constituency_settings
    for row in data.constituency_rows:
        result = evaluate(
            row.code,
            statements,
            running(data, row.code),
            min_statements=settings.v2_min_statements,
            min_party_sides=settings.v2_min_party_sides,
            max_topic_share_percent=data.settings.max_topic_share_percent,
        )
        state = result.availability
        expected_reason = None if state.reason is None else state.reason.value
        if (row.available, row.unavailable_reason) != (state.available, expected_reason):
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}stored "
                    f"{_describe(row.available, row.unavailable_reason)}, expected "
                    f"{_describe(state.available, expected_reason)}"
                )
            )
        elif _plain(row.detail) != state.detail:
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}stored detail {_plain(row.detail)}, "
                    f"expected {state.detail}"
                )
            )
        if row.valid_statement_count != len(result.valid):
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}valid_statement_count is {row.valid_statement_count}, "
                    f"expected {len(result.valid)}"
                )
            )
        if row.offered_lengths != result.lengths:
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}offered lengths are {list(row.offered_lengths)}, "
                    f"expected {list(result.lengths)}"
                )
            )
    if not any(row.available for row in data.constituency_rows):
        entries.append(ReportEntry(NO_CONSTITUENCY_AVAILABLE))
    return entries


def _describe(available: bool, reason: str | None) -> str:
    return "available" if available else f"unavailable ({reason})"


def _plain(detail: Mapping[str, object] | None) -> object:
    return None if detail is None else dict(detail)


def check_constituency_order(data: ValidationInput) -> list[ReportEntry]:
    entries: list[ReportEntry] = []
    statements = rule_statements(data)
    position = {s.id: s.position for s in data.statements}
    for row in data.constituency_rows:
        if not row.available:
            continue
        items: Sequence[tuple[int, int]] = data.constituency_statements.get(row.code, ())
        ranks = [rank for rank, _ in items]
        if ranks != list(range(1, len(items) + 1)):
            entries.append(ReportEntry(f"{_prefix(row.code)}ranks are not 1..{len(items)}"))
            continue
        expected = priority_order(
            statements, running(data, row.code), row.code, data.settings.max_topic_share_percent
        )
        listed = tuple(statement_id for _, statement_id in items)
        if listed != expected:
            first = next(
                (i for i, (a, b) in enumerate(zip(listed, expected, strict=False)) if a != b),
                min(len(listed), len(expected)),
            )
            entries.append(
                ReportEntry(
                    f"{_prefix(row.code)}rank {first + 1} differs from the priority order "
                    f"(stored position {_at(listed, first, position)}, "
                    f"expected position {_at(expected, first, position)})"
                )
            )
    return entries


def _at(keys: Sequence[int], index: int, position: Mapping[int, int]) -> str:
    return str(position.get(keys[index], "?")) if index < len(keys) else "none"


CONSTITUENCY_SNAPSHOT = Check("constituency_snapshot", check_constituency_snapshot)
CONSTITUENCY_VALIDITY = Check("constituency_validity", check_constituency_validity)
CONSTITUENCY_AVAILABILITY = Check("constituency_availability", check_constituency_availability)
CONSTITUENCY_ORDER = Check("constituency_order", check_constituency_order)

__all__ = [
    "CONSTITUENCY_AVAILABILITY",
    "CONSTITUENCY_ORDER",
    "CONSTITUENCY_SNAPSHOT",
    "CONSTITUENCY_VALIDITY",
    "NO_CONSTITUENCY_AVAILABLE",
    "check_constituency_availability",
    "check_constituency_order",
    "check_constituency_snapshot",
    "check_constituency_validity",
    "rule_statements",
    "running",
]
