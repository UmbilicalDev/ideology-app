"""Party Position extraction: per-chunk findings, then one reduce per Party.

Pure of the database. Depends only on ``llm.base`` (never on a concrete
provider), the prompts and the chunking in ``generation``. Party names never
enter a prompt: the input holds only ids, Statement texts and page text.

For each Party (in id order) every chunk of its parsed documents (main document
first) gets one ``position_findings`` call. The findings become numbered
candidates, and one ``party_positions`` call picks a stance per Statement and
the candidate that supports it. A Party with no candidate gets no reduce call
and ``no stance`` everywhere.

Every finding is checked against its cited page as soon as its call returns,
with the ``evidence_quotes`` matcher (``validation.find_quote_miss``, the same
code Validation runs) and only on pages of its own chunk. Quotes are never
edited. The ``party_positions`` request still lists every finding, verified or
not, so recorded calls stay reusable (``--resume-from`` / ``--reuse-from``);
a reduce choice that cites an unverifiable finding becomes ``no stance``
instead. ``FindingCheck`` records the counts and every discarded finding.
Validation's ``evidence_quotes`` check stays the final guard.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
    finding_list_schema,
    position_list_schema,
)
from ideology_app.validation.evidence_quotes import find_quote_miss, normalize_pages

MAX_POSITION_CALLS_PER_RUN = 300
FINDINGS_CHECK_VERSION = "v1"
PAGE_NOT_IN_CHUNK = "page_not_in_chunk"


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
    miss: str | None = None  # why the quote is not on its page; None when verified
    found_on: int | None = None  # for ``other_page``: the page it starts on


@dataclass(frozen=True)
class DiscardedFinding:
    """A finding whose quote is not on its cited page, so it is never Evidence.

    ``reason``: ``page_not_in_chunk``, ``no_letters``, ``other_page`` (it
    starts on page ``found_on``) or ``not_found``. ``cleared``: the Statement
    numbers whose reduce choice cited it and became ``no stance``. ``quote`` is
    verbatim.
    """

    party_id: int
    document_id: int
    statement: int
    value: int
    page: int
    quote: str
    reason: str
    found_on: int | None = None
    cleared: tuple[int, ...] = ()


@dataclass
class FindingCheck:
    """What extraction checked and discarded, updated after each Party's reduce.

    ``checked`` holds the number of findings per Party id (0 for a Party with
    none); ``discarded`` the discarded findings in call order.
    """

    checked: dict[int, int] = field(default_factory=dict)
    discarded: list[DiscardedFinding] = field(default_factory=list)

    def record(self, party_id: int, findings: int, discarded: Sequence[DiscardedFinding]) -> None:
        self.checked[party_id] = findings
        self.discarded.extend(discarded)

    def report(self) -> dict[str, Any]:
        """The JSON-ready summary stored in ``statement_selection["findings"]``."""
        parties = []
        for party_id in sorted(self.checked):
            own = [d for d in self.discarded if d.party_id == party_id]
            parties.append(
                {
                    "party_id": party_id,
                    "findings": self.checked[party_id],
                    "discarded": len(own),
                    "cleared": sum(len(d.cleared) for d in own),
                }
            )
        return {
            "version": FINDINGS_CHECK_VERSION,
            "checked": sum(self.checked.values()),
            "discarded": len(self.discarded),
            "cleared": sum(len(d.cleared) for d in self.discarded),
            "parties": parties,
            "items": [
                {
                    "party_id": d.party_id,
                    "document_id": d.document_id,
                    "page": d.page,
                    "statement": d.statement,
                    "value": d.value,
                    "reason": d.reason,
                    "found_on": d.found_on,
                    "cleared": list(d.cleared),
                    "quote": d.quote,
                }
                for d in self.discarded
            ],
        }


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


def _request(spec: PromptSpec, schema: type[Any], **fields: object) -> LLMRequest[Any]:
    return LLMRequest(
        task=spec.task,
        system=spec.system,
        prompt=spec.template.format(**fields),
        schema=schema,
        max_tokens=spec.max_tokens,
    )


def findings_request(statements: str, chunk: str, statement_count: int) -> LLMRequest[Any]:
    """The ``position_findings`` request for one chunk.

    Its schema bounds every ``statement`` to 1..``statement_count``.
    """
    return _request(
        POSITION_FINDINGS,
        finding_list_schema(statement_count),
        statements=statements,
        chunk=chunk,
    )


def _candidate_line(number: int, candidate: _Candidate) -> str:
    main = candidate.document.role is SourceDocumentRole.MAIN
    label = MAIN_LABEL if main else ADDITIONAL_LABEL
    return (
        f"C{number} [{label}] [afirmación {candidate.statement}] [valor {candidate.value}] "
        f"[página {candidate.page}] «{candidate.quote}»"
    )


def positions_request(
    statements: str, candidates: Sequence[_Candidate], statement_count: int
) -> LLMRequest[Any]:
    """The ``party_positions`` request: candidates numbered C1, C2... in order.

    Its schema bounds ``statement`` to 1..``statement_count``, ``evidence`` to
    1..``len(candidates)`` and the list to ``statement_count`` entries.
    """
    lines = "\n".join(_candidate_line(k, c) for k, c in enumerate(candidates, start=1))
    return _request(
        PARTY_POSITIONS,
        position_list_schema(statement_count, len(candidates)),
        statements=statements,
        candidates=lines,
    )


def _reduce(
    provider: LLMProvider,
    statements: str,
    count: int,
    candidates: Sequence[_Candidate],
    usage: Usage,
) -> tuple[dict[int, PositionResult], dict[int, list[int]]]:
    """The chosen positions, and the Statements cleared per candidate index.

    A choice citing an unverifiable candidate becomes ``no stance``; no other
    candidate is picked in its place.
    """
    result = provider.generate(positions_request(statements, candidates, count))
    usage.record(result)
    output: PositionList = result.output
    seen: set[int] = set()
    for choice in output.positions:
        if choice.statement in seen:
            raise GenerationError(
                f"{PARTY_POSITIONS.task} repeated statement {choice.statement}"
            )
        seen.add(choice.statement)
    chosen: dict[int, PositionResult] = {}
    cleared: dict[int, list[int]] = {}
    # The schema already bounds statement (1..count) and evidence (1..K).
    for choice in output.positions:
        cited = candidates[choice.evidence - 1]
        if cited.miss is not None:
            cleared.setdefault(choice.evidence - 1, []).append(choice.statement)
            chosen[choice.statement] = PositionResult(choice.statement, None)
            continue
        chosen[choice.statement] = PositionResult(
            statement_number=choice.statement,
            value=choice.value,
            document_id=cited.document.document_id,
            quote=cited.quote,
            page=cited.page,
            url=cited.document.source_url,
        )
    return chosen, cleared


def _check(
    finding_page: int, quote: str, chunk: Chunk, norm_pages: Mapping[int, str]
) -> tuple[str | None, int | None]:
    """``(reason, found_on)`` for a finding, ``(None, None)`` when verified."""
    if finding_page not in chunk.pages:
        return PAGE_NOT_IN_CHUNK, None
    miss = find_quote_miss(quote, norm_pages, finding_page)
    return (None, None) if miss is None else (miss.reason, miss.found_on)


def extract_positions(
    provider: LLMProvider,
    statements: Sequence[str],
    documents: Iterable[DocumentPages],
    party_ids: Iterable[int],
    usage: Usage,
    findings: FindingCheck | None = None,
) -> dict[int, list[PositionResult]]:
    """A position for every Statement x Party, keyed by Party id.

    Each list holds exactly ``len(statements)`` results in Statement order;
    omitted Statements and Parties without documents are ``no stance``.
    The request schemas bound every Statement number to 1..``len(statements)``
    and every evidence number to the candidates listed, so out-of-range output
    fails its call with ``LLMOutputError``. Raises ``GenerationError`` when a
    ``party_positions`` answer repeats a Statement. ``LLMError`` propagates;
    ``usage`` keeps the counts of the calls that succeeded.

    Every finding is checked against its cited page (module docstring); a
    choice citing one that fails is ``no stance``. ``findings`` records the
    check per Party, after its reduce.
    """
    count = len(statements)
    listed = statement_lines(statements)
    chunks = _party_chunks(documents)
    normalised: dict[int, dict[int, str]] = {}
    positions: dict[int, list[PositionResult]] = {}
    for party_id in sorted(set(party_ids)):
        candidates: list[_Candidate] = []
        for document, chunk in chunks.get(party_id, []):
            result = provider.generate(findings_request(listed, chunk.text, count))
            usage.record(result)
            output: FindingList = result.output
            if document.document_id not in normalised:
                normalised[document.document_id] = normalize_pages(document.pages)
            for finding in output.findings:
                miss, found_on = _check(
                    finding.page, finding.quote, chunk, normalised[document.document_id]
                )
                candidates.append(
                    _Candidate(
                        finding.statement,
                        finding.value,
                        finding.quote,
                        finding.page,
                        document,
                        miss,
                        found_on,
                    )
                )
        chosen: Mapping[int, PositionResult] = {}
        cleared: Mapping[int, list[int]] = {}
        if candidates:
            chosen, cleared = _reduce(provider, listed, count, candidates, usage)
        if findings is not None:
            findings.record(
                party_id,
                len(candidates),
                [
                    DiscardedFinding(
                        party_id=party_id,
                        document_id=c.document.document_id,
                        statement=c.statement,
                        value=c.value,
                        page=c.page,
                        quote=c.quote,
                        reason=c.miss,
                        found_on=c.found_on,
                        cleared=tuple(cleared.get(index, ())),
                    )
                    for index, c in enumerate(candidates)
                    if c.miss is not None
                ],
            )
        positions[party_id] = [
            chosen.get(n) or PositionResult(statement_number=n, value=None)
            for n in range(1, count + 1)
        ]
    return positions


__all__ = [
    "FINDINGS_CHECK_VERSION",
    "MAX_POSITION_CALLS_PER_RUN",
    "PAGE_NOT_IN_CHUNK",
    "DiscardedFinding",
    "FindingCheck",
    "PositionResult",
    "check_position_budget",
    "extract_positions",
    "findings_request",
    "plan_position_calls",
    "positions_request",
    "statement_lines",
]
