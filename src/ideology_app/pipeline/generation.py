"""Statement generation: chunk the manifesto pages, map to candidates, reduce.

Pure of the database. Depends only on ``llm.base`` (never on a concrete
provider) and on the prompts module. Party names never enter a prompt: the
input holds only ids and page text.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.llm.base import LLMProvider, LLMRequest, LLMResult
from ideology_app.models import SourceDocumentRole
from ideology_app.pipeline.prompts import (
    GENERATE_STATEMENTS,
    STATEMENT_CANDIDATES,
    TARGET_STATEMENT_COUNT,
    CandidateList,
    PromptSpec,
    StatementDraft,
    StatementSet,
)

CHUNK_MAX_CHARS = 40_000
MAX_LLM_CALLS_PER_RUN = 200
NO_CANDIDATES_REASON = "no statement candidates were found in the source documents"
_PAGE_SEPARATOR = "\n\n"


class GenerationError(Exception):
    """Statement generation cannot produce a result (not an LLM failure)."""


@dataclass(frozen=True)
class DocumentPages:
    """The parsed pages of one Source Document, as plain data (no ORM objects)."""

    party_id: int
    document_id: int
    pages: Sequence[tuple[int, str]]  # (page_number, text as stored)
    source_url: str | None = None  # set for documents that came from a URL
    role: SourceDocumentRole = SourceDocumentRole.MAIN


@dataclass(frozen=True)
class Chunk:
    """One prompt-sized piece of a single Source Document."""

    party_id: int
    document_id: int
    text: str


@dataclass
class Usage:
    """LLM usage of a run, updated after each successful call."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(self, result: LLMResult[Any]) -> None:
        self.calls += 1
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens


def _page_marker(page_number: int) -> str:
    return f"[página {page_number}]\n"


def _page_pieces(page_number: int, text: str, max_chars: int) -> list[str]:
    """Render one page under its marker; cut it into slices if it is too long."""
    marker = _page_marker(page_number)
    if len(marker) + len(text) <= max_chars:
        return [marker + text]
    room = max_chars - len(marker)
    if room <= 0:
        raise ValueError(f"max_chars {max_chars} is too small for a page marker")
    return [marker + text[start : start + room] for start in range(0, len(text), room)]


def _chunk(document: DocumentPages, pieces: Sequence[str]) -> Chunk:
    return Chunk(document.party_id, document.document_id, _PAGE_SEPARATOR.join(pieces))


def build_document_chunks(
    documents: Iterable[DocumentPages], max_chars: int = CHUNK_MAX_CHARS
) -> list[Chunk]:
    """Split parsed pages into prompt-sized chunks of at most ``max_chars``.

    Documents are ordered by Party id, then document id; pages by page number.
    A chunk holds whole consecutive pages of one document, each under a
    ``[página N]`` marker. A page longer than the limit is cut into consecutive
    slices (each under its page marker). Whitespace-only pages are left out.
    """
    chunks: list[Chunk] = []
    for document in sorted(documents, key=lambda d: (d.party_id, d.document_id)):
        current: list[str] = []
        size = 0
        for page_number, text in sorted(document.pages, key=lambda p: p[0]):
            if not text.strip():
                continue
            for piece in _page_pieces(page_number, text, max_chars):
                added = len(piece) + (len(_PAGE_SEPARATOR) if current else 0)
                if current and size + added > max_chars:
                    chunks.append(_chunk(document, current))
                    current, size = [], 0
                    added = len(piece)
                current.append(piece)
                size += added
        if current:
            chunks.append(_chunk(document, current))
    return chunks


def build_chunks(
    documents: Iterable[DocumentPages], max_chars: int = CHUNK_MAX_CHARS
) -> list[str]:
    """The text of ``build_document_chunks``, for Statement generation."""
    return [chunk.text for chunk in build_document_chunks(documents, max_chars)]


def _request(spec: PromptSpec, **fields: object) -> LLMRequest[Any]:
    return LLMRequest(
        task=spec.task,
        system=spec.system,
        prompt=spec.template.format(**fields),
        schema=spec.schema,
        max_tokens=spec.max_tokens,
    )


def candidate_request(chunk: str) -> LLMRequest[Any]:
    """The ``statement_candidates`` request for one chunk."""
    return _request(STATEMENT_CANDIDATES, chunk=chunk)


def reduce_request(candidates: Iterable[StatementDraft]) -> LLMRequest[Any]:
    """The ``generate_statements`` request: candidates deduplicated and sorted."""
    unique = sorted({(c.topic, c.text) for c in candidates})
    lines = "\n".join(f"- [{topic}] {text}" for topic, text in unique)
    return _request(GENERATE_STATEMENTS, candidates=lines, count=TARGET_STATEMENT_COUNT)


def generate_statements(
    provider: LLMProvider, chunks: Sequence[str], usage: Usage
) -> list[StatementDraft]:
    """Map each chunk to candidates, then reduce them to the final Statements.

    Raises ``GenerationError`` before any call when there are too many chunks,
    or when no chunk yields a candidate. ``LLMError`` from the provider
    propagates; ``usage`` keeps the counts of the calls that succeeded.
    """
    if len(chunks) + 1 > MAX_LLM_CALLS_PER_RUN:
        raise GenerationError(
            f"too many chunks: {len(chunks)} (limit {MAX_LLM_CALLS_PER_RUN - 1})"
        )
    candidates: list[StatementDraft] = []
    for chunk in chunks:
        result = provider.generate(candidate_request(chunk))
        usage.record(result)
        output: CandidateList = result.output
        candidates.extend(output.candidates)
    if not candidates:
        raise GenerationError(NO_CANDIDATES_REASON)
    result = provider.generate(reduce_request(candidates))
    usage.record(result)
    final: StatementSet = result.output
    return list(final.statements)


__all__ = [
    "CHUNK_MAX_CHARS",
    "MAX_LLM_CALLS_PER_RUN",
    "NO_CANDIDATES_REASON",
    "Chunk",
    "DocumentPages",
    "GenerationError",
    "Usage",
    "build_chunks",
    "build_document_chunks",
    "candidate_request",
    "generate_statements",
    "reduce_request",
]
