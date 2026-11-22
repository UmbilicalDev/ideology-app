"""Check ``party_coverage`` (domain check 3): every Party covers enough Statements.

A Party covers a Statement when it is in favour (+1/+2) or against (−1/−2)
there: ``no stance`` and 0 do not count (three-option rule,
``pipeline-statement-priority-tiers``). The check runs on every questionnaire
length the Dataset Version offers (``base.offered_lengths``, ascending), each
on its first L Statements in position order: a Party of the Election fails a
length when it covers less than ``settings.min_party_coverage_percent`` of
those L Statements (integer arithmetic, no floats). A failing Party fails the
whole run; it is never excluded, and no length is dropped. With zero
Statements coverage is undefined and the check reports nothing (the Statement
count is another check's job).
"""

from collections import Counter

from ideology_app.validation.base import (
    Check,
    ReportEntry,
    ValidationInput,
    length_prefix,
    offered_lengths,
)

NAME = "party_coverage"


def check_party_coverage(data: ValidationInput) -> list[ReportEntry]:
    """One entry per length and Party below the threshold, by length then ``party_ids``."""
    total = len(data.statements)
    percent = data.settings.min_party_coverage_percent
    parties = set(data.party_ids)
    entries: list[ReportEntry] = []
    for length in offered_lengths(data):
        statements = data.statements[:length]
        count_of = len(statements)
        ids = {s.id for s in statements}
        covered = Counter(
            p.party_id
            for p in data.positions
            if p.value is not None
            and p.value != 0
            and p.party_id in parties
            and p.statement_id in ids
        )
        prefix = length_prefix(length, total)
        for party_id in data.party_ids:
            count = covered[party_id]
            if count * 100 < percent * count_of:
                entries.append(
                    ReportEntry(
                        f"{prefix}party {party_id} is in favour or against on {count} of "
                        f"{count_of} statements ({count * 100 // count_of}%); "
                        f"minimum is {percent}%",
                        party_id=party_id,
                    )
                )
    return entries


PARTY_COVERAGE = Check(NAME, check_party_coverage)
