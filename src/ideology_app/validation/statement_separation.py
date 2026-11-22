"""Check ``statement_separation`` (domain check 4): each Statement separates the Parties.

A Statement separates the Parties when at least one Party is in favour
(+1/+2) and at least one is against (−1/−2); 0 and ``no stance`` count on
neither side (three-option rule, ``pipeline-statement-priority-tiers``). Only
Parties of the Election (``party_ids``) and Statements of the run count; other
rows are ignored. A Statement that does not separate them fails the whole run;
it is never dropped. An Election with fewer than two Parties gets one
Election-level entry instead of one per Statement. With zero Statements the
check reports nothing (the Statement count is another check's job). There is
no threshold.
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


def side_counts(values: list[int]) -> tuple[int, int]:
    """``(favour, against)``: how many of ``values`` are above 0 and below 0."""
    return sum(v > 0 for v in values), sum(v < 0 for v in values)


def check_statement_separation(data: ValidationInput) -> list[ReportEntry]:
    """One entry per Statement without a Party on each side, in Statement order."""
    if not data.statements:
        return []
    if len(data.party_ids) < 2:
        return [_election_entry(len(data.party_ids))]
    parties = set(data.party_ids)
    statement_ids = {s.id for s in data.statements}
    stances: dict[int, list[int]] = defaultdict(list)
    for p in data.positions:
        if p.value is not None and p.party_id in parties and p.statement_id in statement_ids:
            stances[p.statement_id].append(p.value)
    entries: list[ReportEntry] = []
    for statement in data.statements:
        found = stances[statement.id]
        favour, against = side_counts(found)
        if favour and against:
            continue
        prefix = f"statement {statement.position} does not separate parties: "
        if not found:
            detail = "no party has a stance"
        elif favour:
            detail = f"no party is against ({favour} in favour)"
        elif against:
            detail = f"no party is in favour ({against} against)"
        else:
            detail = "no party is in favour or against"
        entries.append(ReportEntry(prefix + detail, statement_id=statement.id))
    return entries


STATEMENT_SEPARATION = Check(NAME, check_statement_separation)
