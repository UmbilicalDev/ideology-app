"""Check ``statement_separation`` (domain check 4): each Statement separates the Parties.

A Statement separates the Parties when the Party Positions on it, ignoring
``no stance``, hold at least two different values. Only Parties of the Election
(``party_ids``) and Statements of the run count; other rows are ignored. A
Statement that does not separate them fails the whole run; it is never dropped.
An Election with fewer than two Parties gets one Election-level entry instead
of one per Statement. With zero Statements the check reports nothing (the
Statement count is another check's job). There is no threshold.
"""

from collections import defaultdict

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "statement_separation"


def _election_entry(parties: int) -> ReportEntry:
    noun = "party" if parties == 1 else "parties"
    return ReportEntry(
        f"statements cannot separate parties: the election has {parties} {noun}; "
        "at least 2 are needed"
    )


def check_statement_separation(data: ValidationInput) -> list[ReportEntry]:
    """One entry per Statement with fewer than two distinct stances, in Statement order."""
    if not data.statements:
        return []
    if len(data.party_ids) < 2:
        return [_election_entry(len(data.party_ids))]
    parties = set(data.party_ids)
    statement_ids = {s.id for s in data.statements}
    stances: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for p in data.positions:
        if p.value is not None and p.party_id in parties and p.statement_id in statement_ids:
            stances[p.statement_id].append((p.party_id, p.value))
    entries: list[ReportEntry] = []
    for statement in data.statements:
        found = stances[statement.id]
        if len({value for _, value in found}) >= 2:
            continue
        prefix = f"statement {statement.position} does not separate parties: "
        if not found:
            detail = "no party has a stance"
        elif len(found) == 1:
            party_id, value = found[0]
            detail = f"only party {party_id} has a stance (value {value})"
        else:
            detail = f"all {len(found)} parties with a stance have value {found[0][1]}"
        entries.append(ReportEntry(prefix + detail, statement_id=statement.id))
    return entries


STATEMENT_SEPARATION = Check(NAME, check_statement_separation)
