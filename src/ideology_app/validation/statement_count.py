"""Check ``statement_count`` (domain check 5): the Questionnaire has the configured length.

The number of the run's Statements must be within
``settings.min_statements``..``settings.max_statements`` (inclusive). The
questionnaire lengths stored on the Dataset Version must also be the ones the
settings give for that count: every ``settings.questionnaire_lengths`` entry
below the count, then the count (``expected_lengths``); stored NULL or ``()``
is read as the count alone. Each failure is one run-level entry (no Statement
or Party id) and fails the whole run; no Statement is dropped or added. This
check owns the zero Statements case (no length entry then).
"""

from ideology_app.config import ValidationSettings
from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "statement_count"


def expected_lengths(count: int, settings: ValidationSettings) -> tuple[int, ...]:
    """The lengths a version of ``count`` Statements offers (``()`` when 0)."""
    if count <= 0:
        return ()
    return tuple(length for length in settings.questionnaire_lengths if length < count) + (count,)


def _shown(lengths: tuple[int, ...]) -> str:
    return ", ".join(str(length) for length in lengths)


def check_statement_count(data: ValidationInput) -> list[ReportEntry]:
    """One entry when the count is out of range, one when the stored lengths differ."""
    count = len(data.statements)
    low = data.settings.min_statements
    high = data.settings.max_statements
    entries: list[ReportEntry] = []
    if not low <= count <= high:
        entries.append(
            ReportEntry(f"questionnaire has {count} statements; expected {low} to {high}")
        )
    if count:
        stored = data.lengths or (count,)
        expected = expected_lengths(count, data.settings)
        if stored != expected:
            entries.append(
                ReportEntry(
                    f"questionnaire lengths are {_shown(stored)}; expected {_shown(expected)}"
                )
            )
    return entries


STATEMENT_COUNT = Check(NAME, check_statement_count)
