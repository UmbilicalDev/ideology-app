"""Repair a finding's Evidence when the model's copy of the quote slipped.

e2e-real-2026-election: real runs lost stances because the model miscopied a
quote it had read ("centrales nu - clearas" for "centrales nu - cleares") or
cited the wrong page of its chunk. The stance itself was right; only the
Evidence pointer was off. Two repairs, both only on pages of the finding's own
chunk (the text the model read):

- ``page_corrected``: the quote is verbatim (``evidence_quotes`` matcher) on
  another page of the chunk; the page becomes that page.
- ``quote_snapped``: the quote is on no page but a near-identical span of the
  source starts on a page of the chunk; the quote becomes that span of the
  source text, verbatim (whitespace runs collapsed to one space, which the
  matcher ignores anyway).

The finding's Statement and value are never changed, and no stance is ever
added: a repair only replaces the model's slipped copy with the source's own
words, so the stored Evidence is always verbatim and Validation's exact
``evidence_quotes`` check still runs on it unchanged.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from ideology_app.validation.evidence_quotes import (
    NOT_FOUND,
    OTHER_PAGE,
    normalize_for_match,
    normalize_with_offsets,
)

QUOTE_REPAIR_VERSION = "v1"
PAGE_CORRECTED = "page_corrected"
QUOTE_SNAPPED = "quote_snapped"

# A snap needs a quote of at least this many letters and digits, and a source
# span whose similarity (2 * matched / (quote + span), on normalised text) is
# at least SNAP_MIN_SIMILARITY. Matched characters count only in blocks of at
# least SNAP_MIN_BLOCK, so scattered single letters never make a match.
SNAP_MIN_CHARS = 40
SNAP_MIN_SIMILARITY = 0.85
SNAP_MIN_BLOCK = 4
# A stored quote is at most 500 characters (``prompts.EvidenceQuote``).
SNAP_MAX_QUOTE = 500


@dataclass(frozen=True)
class Repair:
    """How a finding's Evidence was repaired: ``kind``, new ``page`` and ``quote``."""

    kind: str
    page: int
    quote: str


def _snap_on(norm_quote: str, text: str, own_length: int) -> tuple[float, str] | None:
    """Best near-copy of ``norm_quote`` starting in the first ``own_length`` characters."""
    norm, offsets = normalize_with_offsets(text)
    if norm != normalize_for_match(text):  # pragma: no cover - defensive
        return None
    norm_own = len(normalize_for_match(text[:own_length]))
    matcher = SequenceMatcher(None, norm, norm_quote, autojunk=False)
    anchor = matcher.find_longest_match(0, len(norm), 0, len(norm_quote))
    if anchor.size < SNAP_MIN_BLOCK:
        return None
    # The window where the quote would sit if the anchor is part of it.
    low = max(0, anchor.a - anchor.b - len(norm_quote) // 4)
    high = min(len(norm), anchor.a + (len(norm_quote) - anchor.b) + len(norm_quote) // 4)
    window = SequenceMatcher(None, norm[low:high], norm_quote, autojunk=False)
    blocks = [b for b in window.get_matching_blocks() if b.size >= SNAP_MIN_BLOCK]
    if not blocks:
        return None
    # The span runs from where the quote's start would be to where its end
    # would be, so a slip at either end does not cut the source span short.
    first, last = blocks[0], blocks[-1]
    start = low + max(0, first.a - first.b)
    end = min(len(norm), low + last.a + last.size + (len(norm_quote) - last.b - last.size))
    if start >= norm_own or end <= start:
        return None
    matched = sum(b.size for b in blocks)
    similarity = 2 * matched / (len(norm_quote) + (end - start))
    if similarity < SNAP_MIN_SIMILARITY:
        return None
    raw = text[offsets[start] : offsets[end - 1] + 1]
    quote = " ".join(raw.split())
    if not quote or len(quote) > SNAP_MAX_QUOTE:
        return None
    return similarity, quote


def repair_finding(
    quote: str,
    page: int,
    miss: str,
    found_on: int | None,
    chunk_pages: Sequence[int],
    pages: Mapping[int, str],
) -> Repair | None:
    """The repair for a finding whose quote missed with ``miss``, or ``None``.

    ``pages`` are the document's pages as stored; ``chunk_pages`` the pages of
    the finding's chunk. Only ``other_page`` and ``not_found`` misses are
    repaired, and only onto a page of the chunk.
    """
    if miss == OTHER_PAGE:
        if found_on is not None and found_on in chunk_pages:
            return Repair(PAGE_CORRECTED, found_on, quote)
        return None
    if miss != NOT_FOUND:
        return None
    norm_quote = normalize_for_match(quote)
    if len(norm_quote) < SNAP_MIN_CHARS:
        return None
    # The cited page first, then the rest of the chunk in page order.
    order = ([page] if page in chunk_pages else []) + [p for p in chunk_pages if p != page]
    best: tuple[float, int, str] | None = None
    for candidate in order:
        if candidate not in pages:
            continue
        own = pages[candidate]
        text = own + "\n" + pages.get(candidate + 1, "")
        snapped = _snap_on(norm_quote, text, len(own))
        if snapped is not None and (best is None or snapped[0] > best[0]):
            best = (snapped[0], candidate, snapped[1])
    if best is None:
        return None
    return Repair(QUOTE_SNAPPED, best[1], best[2])


__all__ = [
    "PAGE_CORRECTED",
    "QUOTE_REPAIR_VERSION",
    "QUOTE_SNAPPED",
    "SNAP_MIN_CHARS",
    "SNAP_MIN_SIMILARITY",
    "Repair",
    "repair_finding",
]
