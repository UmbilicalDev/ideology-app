"""Chunking and the Proposal check (pure: no database, no LLM, no clock).

``build_chunks`` splits a document's pages into prompt-sized chunks of whole
pages (P2). ``check_items`` keeps a returned item only when its text starts on
its cited page (``validation.evidence_quotes.find_quote_miss``, the one
matcher), it does not start on the chunk's context page, and it is not an
exact normalised duplicate of an earlier kept item (P1, P5). Text, page,
categories and tags are never changed.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.proposals.prompts import ProposalList
from ideology_app.validation.evidence_quotes import (
    NO_LETTERS,
    NOT_FOUND,
    OTHER_PAGE,
    find_quote_miss,
    normalize_for_match,
    normalize_pages,
)

PROPOSAL_CHUNK_MAX_CHARS = 12_000
CHECK_VERSION = "v1"

CONTEXT_PAGE = "context_page"
DUPLICATE = "duplicate"
# Drop reasons in the order the CLI prints them.
DROP_REASONS: tuple[str, ...] = (NOT_FOUND, OTHER_PAGE, CONTEXT_PAGE, DUPLICATE, NO_LETTERS)

_PAGE_SEPARATOR = "\n\n"


def page_marker(page: int) -> str:
    return f"[página {page}]\n"


def context_marker(page: int) -> str:
    return f"[página {page} — solo contexto]\n"


@dataclass(frozen=True)
class Chunk:
    """Whole consecutive non-blank pages, plus the next one as context (not the last chunk)."""

    index: int
    pages: tuple[int, ...]
    context_page: int | None
    text: str

    @property
    def first_page(self) -> int:
        return self.pages[0]

    @property
    def last_page(self) -> int:
        """The last page a Proposal may cite in the schema: the context page when there is one."""
        return self.context_page if self.context_page is not None else self.pages[-1]


def build_chunks(
    pages: Sequence[str], max_chars: int = PROPOSAL_CHUNK_MAX_CHARS
) -> list[Chunk]:
    """Split ``pages`` (page 1 first) into chunks of whole non-blank pages.

    A chunk holds consecutive non-blank pages under ``[página N]`` markers, up
    to ``max_chars`` counting markers and separators; a page is never sliced,
    so a single page over the limit is a chunk alone. Every chunk except the
    last also shows the next non-blank page as ``[página N — solo contexto]``
    (not counted in the limit). Whitespace-only pages are left out.
    """
    groups: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for number, text in enumerate(pages, start=1):
        if not text.strip():
            continue
        piece = page_marker(number) + text
        added = len(piece) + (len(_PAGE_SEPARATOR) if current else 0)
        if current and size + added > max_chars:
            groups.append(current)
            current, size = [], 0
            added = len(piece)
        current.append((number, piece))
        size += added
    if current:
        groups.append(current)
    chunks: list[Chunk] = []
    for index, group in enumerate(groups):
        parts = [piece for _, piece in group]
        context_page: int | None = None
        if index + 1 < len(groups):
            context_page = groups[index + 1][0][0]
            parts.append(context_marker(context_page) + pages[context_page - 1])
        chunks.append(
            Chunk(index, tuple(number for number, _ in group), context_page, _PAGE_SEPARATOR.join(parts))
        )
    return chunks


@dataclass(frozen=True)
class CheckedProposal:
    """A kept item, exactly as returned, with its 1-based ordinal in the document."""

    ordinal: int
    chunk_index: int
    page: int
    text: str
    categories: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DroppedItem:
    chunk: int
    page: int
    reason: str
    found_on: int | None
    text: str


@dataclass(frozen=True)
class CheckResult:
    kept: tuple[CheckedProposal, ...]
    dropped: tuple[DroppedItem, ...]
    returned: int

    def counts(self) -> dict[str, int]:
        """Dropped items per reason, every reason present (0 when none)."""
        counts = dict.fromkeys(DROP_REASONS, 0)
        for item in self.dropped:
            counts[item.reason] += 1
        return counts

    def report(self) -> dict[str, Any]:
        """The ``proposal_extractions.report`` JSON."""
        return {
            "check_version": CHECK_VERSION,
            "returned": self.returned,
            "kept": len(self.kept),
            "dropped_counts": self.counts(),
            "dropped": [
                {
                    "chunk": item.chunk,
                    "page": item.page,
                    "reason": item.reason,
                    "found_on": item.found_on,
                    "text": item.text,
                }
                for item in self.dropped
            ],
        }


def _miss_reason(text: str, norm_pages: Mapping[int, str], page: int) -> tuple[str, int | None] | None:
    if page not in norm_pages:
        return NOT_FOUND, None
    miss = find_quote_miss(text, norm_pages, page)
    if miss is None:
        return None
    return miss.reason, miss.found_on


def check_items(
    chunks: Sequence[Chunk], outputs: Sequence[ProposalList], pages: Sequence[str]
) -> CheckResult:
    """Check every returned item, chunk order then item order (``CHECK_VERSION`` v1).

    In order: drop ``context_page`` (it starts on the chunk's context page; the
    next chunk extracts it), then ``no_letters`` / ``other_page`` / ``not_found``
    (``find_quote_miss`` against every page of the document), then
    ``duplicate`` (normalised text equal to an earlier kept item's). Kept items
    get ordinals 1..n.
    """
    if len(chunks) != len(outputs):
        raise ValueError(f"{len(chunks)} chunks but {len(outputs)} outputs")
    norm_pages = normalize_pages(enumerate(pages, start=1))
    kept: list[CheckedProposal] = []
    dropped: list[DroppedItem] = []
    seen: set[str] = set()
    returned = 0
    for chunk, output in zip(chunks, outputs, strict=True):
        for item in output.proposals:
            returned += 1
            reason: tuple[str, int | None] | None
            if chunk.context_page is not None and item.page == chunk.context_page:
                reason = (CONTEXT_PAGE, None)
            else:
                reason = _miss_reason(item.text, norm_pages, item.page)
                if reason is None and normalize_for_match(item.text) in seen:
                    reason = (DUPLICATE, None)
            if reason is not None:
                dropped.append(DroppedItem(chunk.index, item.page, reason[0], reason[1], item.text))
                continue
            seen.add(normalize_for_match(item.text))
            kept.append(
                CheckedProposal(
                    len(kept) + 1,
                    chunk.index,
                    item.page,
                    item.text,
                    tuple(item.categories),
                    tuple(item.tags),
                )
            )
    return CheckResult(tuple(kept), tuple(dropped), returned)


__all__ = [
    "CHECK_VERSION",
    "CONTEXT_PAGE",
    "DROP_REASONS",
    "DUPLICATE",
    "PROPOSAL_CHUNK_MAX_CHARS",
    "CheckResult",
    "CheckedProposal",
    "Chunk",
    "DroppedItem",
    "build_chunks",
    "check_items",
    "context_marker",
    "page_marker",
]
