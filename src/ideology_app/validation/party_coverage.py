"""Check ``party_coverage`` (domain check 3): every Party covers enough Statements.

A Party is covered on a Statement when its Party Position there is not
``no stance``. A Party of the Election fails when it is covered on less than
``settings.min_party_coverage_percent`` of the run's Statements (integer
arithmetic, no floats). A failing Party fails the whole run; it is never
excluded. With zero Statements coverage is undefined and the check reports
nothing (the Statement count is another check's job).
"""

from collections import Counter

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "party_coverage"


def check_party_coverage(data: ValidationInput) -> list[ReportEntry]:
    """One entry per Party below the threshold, in ``party_ids`` order."""
    total = len(data.statements)
    if total == 0:
        return []
    percent = data.settings.min_party_coverage_percent
    parties = set(data.party_ids)
    covered = Counter(
        p.party_id for p in data.positions if p.value is not None and p.party_id in parties
    )
    entries: list[ReportEntry] = []
    for party_id in data.party_ids:
        count = covered[party_id]
        if count * 100 < percent * total:
            entries.append(
                ReportEntry(
                    f"party {party_id} has positions on {count} of {total} statements "
                    f"({count * 100 // total}%); minimum is {percent}%",
                    party_id=party_id,
                )
            )
    return entries


PARTY_COVERAGE = Check(NAME, check_party_coverage)
