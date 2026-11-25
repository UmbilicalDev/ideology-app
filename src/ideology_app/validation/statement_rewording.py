"""Check ``statement_rewording`` (v2, ``statement-rewording``): rewordings only through the check.

A v2 Statement's text differs from the AI text only when the run's rewording
report holds an ``applied`` entry (an equivalent ``statement_rewording_check``
verdict) for it. The check compares the stored ``statement_rewordings`` rows
with those entries, matching Statement position, AI text, new text and
reason exactly:

- ``statement S rewording keeps the AI text``: a row whose ``ai_text`` equals
  the Statement's text;
- ``statement S is reworded without an accepted equivalence check``: a row
  with no matching ``applied`` entry;
- ``applied rewording of statement S is not stored``: an ``applied`` entry
  with no matching row.

It cannot see a change of a Statement that has no row and no entry: the AI
text of an unreworded Statement is stored only in ``statements.text`` and in
the recorded calls. Uniqueness and the Context Note are checked on the final
text by their own checks. There is no threshold.
"""

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "statement_rewording"


def check_statement_rewording(data: ValidationInput) -> list[ReportEntry]:
    """One entry per inconsistent Statement, then per unstored applied entry, in position order."""
    applied = set(data.applied_rewordings)
    stored: set[tuple[int, str, str, str]] = set()
    entries: list[ReportEntry] = []
    for statement in data.statements:
        if statement.ai_text is None:
            continue
        key = (
            statement.position,
            statement.ai_text,
            statement.text,
            statement.rewording_reason or "",
        )
        stored.add(key)
        if statement.ai_text == statement.text:
            message = f"statement {statement.position} rewording keeps the AI text"
        elif key not in applied:
            message = (
                f"statement {statement.position} is reworded without an accepted "
                "equivalence check"
            )
        else:
            continue
        entries.append(ReportEntry(message, statement_id=statement.id))
    by_position = {s.position: s.id for s in data.statements}
    for item in sorted(applied - stored, key=lambda k: (k[0] if isinstance(k[0], int) else 0)):
        position = item[0]
        entries.append(
            ReportEntry(
                f"applied rewording of statement {position} is not stored",
                statement_id=by_position.get(position) if isinstance(position, int) else None,
            )
        )
    return entries


STATEMENT_REWORDING = Check(NAME, check_statement_rewording)
