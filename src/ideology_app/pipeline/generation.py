"""Statement generation: chunk the manifesto pages, map to candidates, reduce.

Pure of the database. Depends only on ``llm.base`` (never on a concrete
provider), the prompts module and ``pipeline.agenda``. Party names never enter
a prompt: the input holds only ids and page text, and the candidates of the
reduce are the Party-balanced Agenda (``agenda.balance_candidates``), which
carries no Party id either.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.config import ValidationSettings
from ideology_app.llm.base import LLMProvider, LLMRequest, LLMResult
from ideology_app.models import SourceDocumentRole
from ideology_app.pipeline.agenda import Agenda, balance_candidates
from ideology_app.pipeline.prompts import (
    GENERATE_STATEMENTS,
    POOL_MAX_STATEMENTS,
    POOL_MIN_STATEMENTS,
    POOL_TARGET_STATEMENTS,
    STATEMENT_CANDIDATES,
    CandidateList,
    PromptSpec,
    StatementDraft,
    StatementSet,
    statement_set_schema,
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


@dataclass(frozen=True)
class StatementPool:
    """The Statement Pool of a run and the Party-balanced Agenda it came from."""

    statements: tuple[StatementDraft, ...]
    agenda: Agenda


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


def _request(
    spec: PromptSpec, schema: type[Any] | None = None, **fields: object
) -> LLMRequest[Any]:
    return LLMRequest(
        task=spec.task,
        system=spec.system,
        prompt=spec.template.format(**fields),
        schema=spec.schema if schema is None else schema,
        max_tokens=spec.max_tokens,
    )


def candidate_request(chunk: str) -> LLMRequest[Any]:
    """The ``statement_candidates`` request for one chunk."""
    return _request(STATEMENT_CANDIDATES, chunk=chunk)


def pool_bounds(settings: ValidationSettings | None = None) -> tuple[int, int, int]:
    """``(low, high, target)`` for the Statement Pool of a run with ``settings``.

    ``low`` is at least ``POOL_MIN_STATEMENTS`` and at least
    ``settings.max_statements``, so the pool is never smaller than the largest
    allowed Questionnaire; ``high`` is at least ``POOL_MAX_STATEMENTS`` and at
    least ``low``; ``target`` is ``POOL_TARGET_STATEMENTS`` clamped to them.
    ``None``: the ``config.ValidationSettings`` defaults (env is never read here).
    """
    if settings is None:
        settings = ValidationSettings()
    low = max(POOL_MIN_STATEMENTS, settings.max_statements)
    high = max(POOL_MAX_STATEMENTS, low)
    target = min(max(POOL_TARGET_STATEMENTS, low), high)
    return low, high, target


def reduce_request(
    candidates: Iterable[StatementDraft], settings: ValidationSettings | None = None
) -> LLMRequest[Any]:
    """The ``generate_statements`` request for the Statement Pool.

    Candidates are deduplicated and sorted. The schema bounds the pool size to
    ``pool_bounds(settings)`` (``None``: the ``config.ValidationSettings``
    defaults), and the prompt asks for its ``target``.
    """
    low, high, target = pool_bounds(settings)
    unique = sorted({(c.topic, c.text) for c in candidates})
    lines = "\n".join(f"- [{topic}] {text}" for topic, text in unique)
    return _request(
        GENERATE_STATEMENTS,
        schema=statement_set_schema(low, high),
        candidates=lines,
        count=target,
        min_count=low,
        max_count=high,
    )


def generate_statements(
    provider: LLMProvider,
    chunks: Sequence[Chunk],
    usage: Usage,
    settings: ValidationSettings | None = None,
) -> StatementPool:
    """Map each chunk to candidates, balance them per Party, reduce them to the pool.

    The candidates of every chunk go through ``agenda.balance_candidates``
    (with the pool's ``high`` bound as ``pool_max``), so every Party weighs the
    same in the reduce whatever its manifesto length. The final Statements are
    chosen from the pool later
    (``pipeline.selection``). ``settings`` (a ``config.ValidationSettings``;
    ``None``: its defaults) gives the pool bounds of the reduce schema
    (``pool_bounds``), so an out-of-range list fails that call with
    ``LLMOutputError``. Raises ``GenerationError`` before
    any call when there are too many chunks, and before the reduce call when
    no chunk yields a candidate. ``LLMError`` from the provider propagates; ``usage`` keeps the
    counts of the calls that succeeded.
    """
    if len(chunks) + 1 > MAX_LLM_CALLS_PER_RUN:
        raise GenerationError(
            f"too many chunks: {len(chunks)} (limit {MAX_LLM_CALLS_PER_RUN - 1})"
        )
    per_chunk: list[tuple[int, Sequence[StatementDraft]]] = []
    for chunk in chunks:
        result = provider.generate(candidate_request(chunk.text))
        usage.record(result)
        output: CandidateList = result.output
        per_chunk.append((chunk.party_id, output.candidates))
    agenda = balance_candidates(per_chunk, pool_max=pool_bounds(settings)[1])
    if not agenda.candidates:
        raise GenerationError(NO_CANDIDATES_REASON)
    result = provider.generate(reduce_request(agenda.candidates, settings))
    usage.record(result)
    final: StatementSet = result.output
    return StatementPool(statements=tuple(final.statements), agenda=agenda)


__all__ = [
    "CHUNK_MAX_CHARS",
    "MAX_LLM_CALLS_PER_RUN",
    "NO_CANDIDATES_REASON",
    "Chunk",
    "DocumentPages",
    "GenerationError",
    "StatementPool",
    "Usage",
    "build_chunks",
    "build_document_chunks",
    "candidate_request",
    "generate_statements",
    "pool_bounds",
    "reduce_request",
]
