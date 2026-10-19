"""Check ``statement_uniqueness`` (domain check 1, uniqueness part): no repeated Statement.

Two Statements are duplicates when their texts are equal after
``normalize_for_match`` (the Validation normaliser: case, accents, ligatures,
whitespace and punctuation are ignored; word order and every letter and digit
still count). Topic is ignored. Each later copy is reported against the first
Statement with that text, in Statement order. A duplicate fails the whole run;
no Statement is dropped or merged. Paraphrases are not detected, and the
single-proposition half of check 1 is not automated. There is no threshold.
"""

from ideology_app.validation.base import Check, ReportEntry, StatementRow, ValidationInput
from ideology_app.validation.evidence_quotes import normalize_for_match

NAME = "statement_uniqueness"


def check_statement_uniqueness(data: ValidationInput) -> list[ReportEntry]:
    """One entry per Statement whose text repeats an earlier one, in Statement order."""
    first_by_text: dict[str, StatementRow] = {}
    entries: list[ReportEntry] = []
    for statement in data.statements:
        key = normalize_for_match(statement.text)
        first = first_by_text.setdefault(key, statement)
        if first is not statement:
            entries.append(
                ReportEntry(
                    f"statement {statement.position} duplicates statement {first.position}",
                    statement_id=statement.id,
                )
            )
    return entries


STATEMENT_UNIQUENESS = Check(NAME, check_statement_uniqueness)
