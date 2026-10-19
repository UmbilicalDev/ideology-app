"""Check ``statement_count`` (domain check 5): the Questionnaire has the configured length.

The number of the run's Statements must be within
``settings.min_statements``..``settings.max_statements`` (inclusive). Otherwise
the check returns one run-level entry (no Statement or Party id) and the whole
run fails; no Statement is dropped or added. This check owns the zero
Statements case.
"""

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "statement_count"


def check_statement_count(data: ValidationInput) -> list[ReportEntry]:
    """One entry when the Statement count is out of range, else none."""
    count = len(data.statements)
    low = data.settings.min_statements
    high = data.settings.max_statements
    if low <= count <= high:
        return []
    return [ReportEntry(f"questionnaire has {count} statements; expected {low} to {high}")]


STATEMENT_COUNT = Check(NAME, check_statement_count)
