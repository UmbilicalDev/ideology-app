"""Party Position extraction: per-chunk findings, then one reduce per Party.

Pure of the database. Depends only on ``llm.base`` (never on a concrete
provider), the prompts and the chunking in ``generation``. Party names never
enter a prompt: the input holds only ids, Statement texts and page text.

For each Party (in id order) every chunk of its parsed documents (main document
first) gets one ``position_findings`` call. The findings become numbered
candidates, and one ``party_positions`` call picks a stance per Statement and
the candidate that supports it. A Party with no candidate gets no reduce call
and ``no stance`` everywhere. Quotes are kept exactly as the LLM returned them;
checking them against the source is Validation's job.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.llm.base import LLMProvider, LLMRequest
from ideology_app.models import SourceDocumentRole
from ideology_app.pipeline.generation import (
    CHUNK_MAX_CHARS,
    Chunk,
    DocumentPages,
    GenerationError,
    Usage,
    build_document_chunks,
)
from ideology_app.pipeline.prompts import (
    ADDITIONAL_LABEL,
    MAIN_LABEL,
    PARTY_POSITIONS,
    POSITION_FINDINGS,
    FindingList,
    PositionList,
    PromptSpec,
)

MAX_POSITION_CALLS_PER_RUN = 300


@dataclass(frozen=True)
class PositionResult:
    """One Party's position on one Statement (1-based number); ``value`` None is no stance."""

    statement_number: int
    value: int | None
    document_id: int | None = None
    quote: str | None = None
    page: int | None = None
    url: str | None = None


@dataclass(frozen=True)
class _Candidate:
    statement: int
    value: int
    quote: str
    page: int
    document: DocumentPages


def _role_order(document: DocumentPages) -> tuple[int, int]:
    return (0 if document.role is SourceDocumentRole.MAIN else 1, document.document_id)


def _party_chunks(
    documents: Iterable[DocumentPages], max_chars: int = CHUNK_MAX_CHARS
) -> dict[int, list[tuple[DocumentPages, Chunk]]]:
    """Chunks per Party, ordered main document first, then document id, then page."""
    by_id = {d.document_id: d for d in documents}
    result: dict[int, list[tuple[DocumentPages, Chunk]]] = {}
    for chunk in build_document_chunks(by_id.values(), max_chars):
        result.setdefault(chunk.party_id, []).append((by_id[chunk.document_id], chunk))
    for chunks in result.values():
        # A stable sort keeps the page order of each document.
        chunks.sort(key=lambda item: _role_order(item[0]))
    return result


def plan_position_calls(
    documents: Iterable[DocumentPages], max_chars: int = CHUNK_MAX_CHARS
) -> int:
    """The most LLM calls extraction can make: every chunk plus one reduce per Party."""
    chunks = _party_chunks(documents, max_chars)
    return sum(len(c) for c in chunks.values()) + len(chunks)


def check_position_budget(documents: Iterable[DocumentPages]) -> None:
    """Raise ``GenerationError`` when extraction could exceed the call cap."""
    planned = plan_position_calls(documents)
    if planned > MAX_POSITION_CALLS_PER_RUN:
        raise GenerationError(
            f"too many position extraction calls: {planned} "
            f"(limit {MAX_POSITION_CALLS_PER_RUN})"
        )


def statement_lines(statements: Sequence[str]) -> str:
    """The Statements as ``[n] <text>`` lines, n = 1-based Statement position."""
    return "\n".join(f"[{n}] {text}" for n, text in enumerate(statements, start=1))


def _request(spec: PromptSpec, **fields: object) -> LLMRequest[Any]:
    return LLMRequest(
        task=spec.task,
        system=spec.system,
        prompt=spec.template.format(**fields),
        schema=spec.schema,
        max_tokens=spec.max_tokens,
    )


def findings_request(statements: str, chunk: str) -> LLMRequest[Any]:
    """The ``position_findings`` request for one chunk."""
    return _request(POSITION_FINDINGS, statements=statements, chunk=chunk)


def _candidate_line(number: int, candidate: _Candidate) -> str:
    main = candidate.document.role is SourceDocumentRole.MAIN
    label = MAIN_LABEL if main else ADDITIONAL_LABEL
    return (
        f"C{number} [{label}] [afirmación {candidate.statement}] [valor {candidate.value}] "
        f"[página {candidate.page}] «{candidate.quote}»"
    )


def positions_request(statements: str, candidates: Sequence[_Candidate]) -> LLMRequest[Any]:
    """The ``party_positions`` request: candidates numbered C1, C2... in order."""
    lines = "\n".join(_candidate_line(k, c) for k, c in enumerate(candidates, start=1))
    return _request(PARTY_POSITIONS, statements=statements, candidates=lines)


def _check_statement(task: str, number: int, count: int) -> None:
    if not 1 <= number <= count:
        raise GenerationError(f"{task} referred to unknown statement {number}")


def _reduce(
    provider: LLMProvider,
    statements: str,
    count: int,
    candidates: Sequence[_Candidate],
    usage: Usage,
) -> dict[int, PositionResult]:
    result = provider.generate(positions_request(statements, candidates))
    usage.record(result)
    output: PositionList = result.output
    chosen: dict[int, PositionResult] = {}
    for choice in output.positions:
        _check_statement(PARTY_POSITIONS.task, choice.statement, count)
        if choice.statement in chosen:
            raise GenerationError(
                f"{PARTY_POSITIONS.task} repeated statement {choice.statement}"
            )
        if not 1 <= choice.evidence <= len(candidates):
            raise GenerationError(
                f"{PARTY_POSITIONS.task} referred to unknown evidence candidate "
                f"{choice.evidence} (statement {choice.statement}, "
                f"{len(candidates)} candidates)"
            )
        cited = candidates[choice.evidence - 1]
        chosen[choice.statement] = PositionResult(
            statement_number=choice.statement,
            value=choice.value,
            document_id=cited.document.document_id,
            quote=cited.quote,
            page=cited.page,
            url=cited.document.source_url,
        )
    return chosen


def extract_positions(
    provider: LLMProvider,
    statements: Sequence[str],
    documents: Iterable[DocumentPages],
    party_ids: Iterable[int],
    usage: Usage,
) -> dict[int, list[PositionResult]]:
    """A position for every Statement x Party, keyed by Party id.

    Each list holds exactly ``len(statements)`` results in Statement order;
    omitted Statements and Parties without documents are ``no stance``.
    Raises ``GenerationError`` when the LLM output refers to an unknown
    Statement or candidate, or repeats a Statement. ``LLMError`` propagates;
    ``usage`` keeps the counts of the calls that succeeded.
    """
    count = len(statements)
    listed = statement_lines(statements)
    chunks = _party_chunks(documents)
    positions: dict[int, list[PositionResult]] = {}
    for party_id in sorted(set(party_ids)):
        candidates: list[_Candidate] = []
        for document, chunk in chunks.get(party_id, []):
            result = provider.generate(findings_request(listed, chunk.text))
            usage.record(result)
            output: FindingList = result.output
            for finding in output.findings:
                _check_statement(POSITION_FINDINGS.task, finding.statement, count)
                candidates.append(
                    _Candidate(
                        finding.statement, finding.value, finding.quote, finding.page, document
                    )
                )
        chosen: Mapping[int, PositionResult] = (
            _reduce(provider, listed, count, candidates, usage) if candidates else {}
        )
        positions[party_id] = [
            chosen.get(n) or PositionResult(statement_number=n, value=None)
            for n in range(1, count + 1)
        ]
    return positions


__all__ = [
    "MAX_POSITION_CALLS_PER_RUN",
    "PositionResult",
    "check_position_budget",
    "extract_positions",
    "findings_request",
    "plan_position_calls",
    "positions_request",
    "statement_lines",
]
