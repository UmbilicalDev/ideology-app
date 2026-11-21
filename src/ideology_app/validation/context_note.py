"""Check ``context_note`` (domain check 7): every Statement has a neutral context note.

Per Statement, in Statement order:

- a NULL or whitespace-only note gives ``statement S has no context note``;
- otherwise a trimmed length outside ``settings.context_note_min_chars``..
  ``settings.context_note_max_chars`` gives
  ``statement S context note has N characters; expected MIN to MAX``;
- and a note that uses entries of ``settings.context_note_evaluative_words``
  gives one ``statement S context note uses evaluative wording: a, b`` entry
  listing the matched entries (folded form, list order).

Matching is by whole words: the note and each list entry are split into words
(runs of letters and digits) and every word is folded with
``normalize_for_match`` (case, accents and compatibility forms ignored). An
entry matches when its word sequence occurs consecutively in the note, so
``injusto`` never matches inside ``justicia`` or ``injustamente``, and
``por desgracia`` matches only as those two consecutive words.

Any entry fails the whole run. Notes are stored exactly as the provider
returned them; nothing is trimmed, dropped or edited. Statement Selection
(``pipeline.selection``) uses this check on the pool to leave out Statements
whose note would fail. A note's factual accuracy is not checked.
"""

import re
import unicodedata
from collections.abc import Sequence

from ideology_app.validation.base import Check, ReportEntry, ValidationInput
from ideology_app.validation.evidence_quotes import normalize_for_match

NAME = "context_note"

_WORD_RE = re.compile(r"[^\W_]+")


def note_words(text: str) -> tuple[str, ...]:
    """The folded words of ``text`` (runs of letters and digits), in order."""
    composed = unicodedata.normalize("NFC", text)
    words = (normalize_for_match(token) for token in _WORD_RE.findall(composed))
    return tuple(word for word in words if word)


def _contains(words: Sequence[str], phrase: Sequence[str]) -> bool:
    size = len(phrase)
    if size == 0:
        return False
    return any(
        tuple(words[start : start + size]) == tuple(phrase)
        for start in range(len(words) - size + 1)
    )


def evaluative_matches(note: str, entries: Sequence[str]) -> list[str]:
    """The entries of ``entries`` that ``note`` uses, folded, in list order, once each."""
    words = note_words(note)
    found: list[str] = []
    for entry in entries:
        phrase = note_words(entry)
        label = " ".join(phrase)
        if label not in found and _contains(words, phrase):
            found.append(label)
    return found


def check_context_note(data: ValidationInput) -> list[ReportEntry]:
    """Entries for missing, out-of-range or evaluative context notes, in Statement order."""
    low = data.settings.context_note_min_chars
    high = data.settings.context_note_max_chars
    entries_list = data.settings.context_note_evaluative_words
    entries: list[ReportEntry] = []
    for statement in data.statements:
        note = statement.context_note
        if note is None or not note.strip():
            entries.append(
                ReportEntry(
                    f"statement {statement.position} has no context note",
                    statement_id=statement.id,
                )
            )
            continue
        length = len(note.strip())
        if not low <= length <= high:
            entries.append(
                ReportEntry(
                    f"statement {statement.position} context note has {length} "
                    f"characters; expected {low} to {high}",
                    statement_id=statement.id,
                )
            )
        matched = evaluative_matches(note, entries_list)
        if matched:
            entries.append(
                ReportEntry(
                    f"statement {statement.position} context note uses evaluative "
                    f"wording: {', '.join(matched)}",
                    statement_id=statement.id,
                )
            )
    return entries


CONTEXT_NOTE = Check(NAME, check_context_note)
