"""Check ``evidence_quotes`` (domain check 2): every quote is on its cited page.

A match is an exact substring of the normalised text (``normalize_for_match``):
no edit distance and no minimum length. The quote must start on the cited page
and may run onto the next one. Stored quotes and page texts are never changed.
"""

import unicodedata
from collections.abc import Mapping

from ideology_app.validation.base import Check, PositionRow, ReportEntry, ValidationInput

NAME = "evidence_quotes"


def normalize_for_match(text: str) -> str:
    """Fold case, accents and compatibility forms; drop everything but letters and digits.

    NFKD, ``casefold()``, NFKD again, then keep only alphanumeric characters
    that are not combining marks. So ``ó`` -> ``o``, ``ﬁ`` -> ``fi``, and all
    whitespace, punctuation, hyphens, NBSP and soft hyphens disappear, while
    word order and every letter and digit must still match.
    """
    folded = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", text).casefold())
    return "".join(ch for ch in folded if ch.isalnum() and not unicodedata.combining(ch))


def quote_starts_on(norm_quote: str, norm_pages: Mapping[int, str], page: int) -> bool:
    """True when ``norm_quote`` starts on ``page`` (it may run onto ``page + 1``)."""
    own = norm_pages[page]
    index = (own + norm_pages.get(page + 1, "")).find(norm_quote)
    return index != -1 and index < len(own)


def _first_failure(
    position: PositionRow,
    data: ValidationInput,
    normalised: dict[int, dict[int, str]],
) -> str | None:
    document_id = position.document_id
    assert document_id is not None and position.page is not None and position.quote is not None
    document = data.documents.get(document_id)
    if document is None or document.party_id != position.party_id:
        return (
            f"source document {document_id} is not a source document of party "
            f"{position.party_id} in this run"
        )
    if position.url != document.source_url:
        return f"evidence URL does not match source document {document_id}"
    page = position.page
    if page not in document.pages:
        return (
            f"page {page} does not exist in source document {document_id} "
            f"({len(document.pages)} pages)"
        )
    quote = normalize_for_match(position.quote)
    if not quote:
        return "quote has no letters or digits"
    if document_id not in normalised:
        normalised[document_id] = {n: normalize_for_match(t) for n, t in document.pages.items()}
    pages = normalised[document_id]
    if quote_starts_on(quote, pages, page):
        return None
    for other in sorted(pages):
        if other != page and quote_starts_on(quote, pages, other):
            return (
                f"quote not found on page {page} of source document {document_id} "
                f"(found on page {other})"
            )
    return f"quote not found in source document {document_id}"


def check_evidence_quotes(data: ValidationInput) -> list[ReportEntry]:
    """One entry per stance (not ``no stance``) whose Evidence fails a rule."""
    normalised: dict[int, dict[int, str]] = {}
    entries: list[ReportEntry] = []
    for position in data.positions:
        if position.value is None:
            continue
        message = _first_failure(position, data, normalised)
        if message is not None:
            entries.append(ReportEntry(message, position.statement_id, position.party_id))
    return entries


EVIDENCE_QUOTES = Check(NAME, check_evidence_quotes)
