"""Phase 3 on the database: extract, resume, finalize, reuse and the ledger handoff.

Extraction state is per document content (``content_hash``): one
``proposal_extractions`` row serves every Source Document row and Election
with those bytes (D1, P3). For chunk *i* a recorded call with an equal
``request_hash`` (``pipeline.checkpoint.request_hash``) is re-validated and
reused with zero calls; otherwise the provider is called and the call row is
committed on its own as soon as it returns. When every chunk has a call,
finalize (deterministic, one transaction) checks the items and inserts the
Proposals. A complete extraction is never redone (P4).

The Ingestion Ledger is read only through ``read_ledger`` + ``reconcile`` and
written only through ``ingestion_ledger.record_extraction_in_dir``.

Depends on ``llm.base`` (never a concrete provider), ``models``, ``db``,
``bundle_import``, ``source_bundle``, ``ingestion_ledger`` and
``pipeline.checkpoint.request_hash``.
"""

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from ideology_app import ingestion_ledger as ledgers
from ideology_app.bundle_import import find_election
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError
from ideology_app.llm.base import LLMError, LLMProvider, LLMRequest, LLMResult
from ideology_app.models import (
    Party,
    Proposal,
    ProposalExtraction,
    ProposalExtractionCall,
    ProposalExtractionStatus,
    SourceDocument,
    SourceDocumentPage,
    SourceDocumentStatus,
)
from ideology_app.pipeline.checkpoint import request_hash
from ideology_app.proposals.extraction import (
    CHECK_VERSION,
    DROP_REASONS,
    PROPOSAL_CHUNK_MAX_CHARS,
    Chunk,
    build_chunks,
    check_items,
)
from ideology_app.proposals.prompts import (
    PROPOSAL_EXTRACTION,
    TASK,
    ProposalList,
    proposal_request,
)
from ideology_app.source_bundle import Bundle, read_bundle

DEFAULT_MAX_CALLS = 300

type Echo = Callable[..., None]


class ProposalError(InvalidInputError):
    """Phase 3 cannot run as asked (bundle, ledger, import or resume pin)."""


def _short(content_hash: str) -> str:
    return content_hash[:12]


# --- Reading ----------------------------------------------------------------------


def get_extraction(session: Session, content_hash: str) -> ProposalExtraction | None:
    return session.scalars(
        select(ProposalExtraction).where(ProposalExtraction.content_hash == content_hash)
    ).one_or_none()


def _complete(session: Session, content_hash: str) -> ProposalExtraction | None:
    extraction = get_extraction(session, content_hash)
    if extraction is None or extraction.status is not ProposalExtractionStatus.COMPLETE:
        return None
    return extraction


def _recorded_count(session: Session, extraction_id: int) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ProposalExtractionCall)
        .where(ProposalExtractionCall.extraction_id == extraction_id)
    ) or 0


def _proposal_count(session: Session, extraction_id: int) -> int:
    return session.scalar(
        select(func.count()).select_from(Proposal).where(Proposal.extraction_id == extraction_id)
    ) or 0


def load_proposals(session: Session, content_hash: str) -> Sequence[Proposal]:
    """The Proposals of the complete extraction of ``content_hash`` in ordinal order
    (empty when there is none). The read path for ``statements-from-proposals``."""
    extraction = _complete(session, content_hash)
    if extraction is None:
        return []
    return session.scalars(
        select(Proposal).where(Proposal.extraction_id == extraction.id).order_by(Proposal.ordinal)
    ).all()


def dropped_items(session: Session, content_hash: str) -> list[dict[str, Any]]:
    """The dropped items of the complete extraction of ``content_hash`` (report order)."""
    extraction = _complete(session, content_hash)
    if extraction is None or extraction.report is None:
        return []
    return list(extraction.report.get("dropped", []))


def dropped_counts(extraction: ProposalExtraction) -> dict[str, int]:
    counts = (extraction.report or {}).get("dropped_counts", {})
    return {reason: int(counts.get(reason, 0)) for reason in DROP_REASONS}


def _kept_entry(bundle: Bundle, ledger: ledgers.Ledger, file: str) -> ledgers.DocumentEntry:
    ledgers.listed_document(bundle, file)
    entry = ledger.document(file)
    review = entry.review
    if review is None or review.decision is not ledgers.ReviewDecision.KEPT:
        raise ProposalError(
            f"document {file} is {ledgers.review_label(review)}; "
            "only a document reviewed kept is extracted"
        )
    return entry


def kept_documents(ledger: ledgers.Ledger) -> list[ledgers.DocumentEntry]:
    """The ledger documents reviewed ``kept``, in manifest order."""
    return [
        entry
        for entry in ledger.documents
        if entry.review is not None and entry.review.decision is ledgers.ReviewDecision.KEPT
    ]


def ledger_count_problems(
    session: Session, bundle: Bundle, ledger: ledgers.Ledger
) -> list[str]:
    """Kept documents whose ledger count is not the number of stored Proposals.

    For each document reviewed kept whose ``proposals`` is set: there must be a
    complete extraction of its ``content_hash`` holding exactly that many
    Proposal rows. Callers: ``db check``, ``data check``, ``proposals status``
    and (handoff) ``statements-from-proposals`` before a v2 run.
    """
    if bundle.format != 2:
        return []
    problems: list[str] = []
    for entry in kept_documents(ledger):
        if entry.proposals is None:
            continue
        extraction = _complete(session, entry.content_hash)
        where = f"document {entry.file}: ledger records {entry.proposals} validated proposals"
        if extraction is None:
            problems.append(
                f"{where} but there is no complete extraction for {_short(entry.content_hash)}..."
            )
            continue
        stored = _proposal_count(session, extraction.id)
        if stored != entry.proposals:
            problems.append(
                f"{where}, the database has {stored} for {_short(entry.content_hash)}..."
            )
    return problems


def bundle_count_problems(session: Session, bundle: Bundle) -> list[str]:
    """``ledger_count_problems`` for a bundle's stored ledger; empty without a valid one
    (an invalid ledger is already reported by ``ingestion_ledger.ledger_problems``)."""
    if bundle.format != 2:
        return []
    try:
        ledger = ledgers.read_ledger(bundle.path)
    except ledgers.LedgerError:
        return []
    if ledger is None:
        return []
    return ledger_count_problems(session, bundle, ledger)


@dataclass(frozen=True)
class UnfinishedExtraction:
    content_hash: str
    chunks_done: int
    chunk_count: int


def unfinished_extractions(session: Session) -> list[UnfinishedExtraction]:
    """Every ``in_progress`` extraction with its recorded chunks (``db check`` info)."""
    rows = session.scalars(
        select(ProposalExtraction)
        .where(ProposalExtraction.status == ProposalExtractionStatus.IN_PROGRESS)
        .order_by(ProposalExtraction.id)
    ).all()
    return [
        UnfinishedExtraction(row.content_hash, _recorded_count(session, row.id), row.chunk_count)
        for row in rows
    ]


@dataclass(frozen=True)
class StatusRow:
    file: str
    content_hash: str
    state: str
    chunks_done: int
    chunk_count: int
    validated: int | None
    ledger: int | None


def status_rows(session: Session, bundle: Bundle, ledger: ledgers.Ledger) -> list[StatusRow]:
    """One row per kept document: extraction state, chunks, validated and ledger counts."""
    rows: list[StatusRow] = []
    for entry in kept_documents(ledger):
        extraction = get_extraction(session, entry.content_hash)
        if extraction is None:
            pages = ledgers.listed_document(bundle, entry.file).text.pages
            rows.append(
                StatusRow(
                    entry.file,
                    entry.content_hash,
                    "not_started",
                    0,
                    len(build_chunks(pages)),
                    None,
                    entry.proposals,
                )
            )
            continue
        rows.append(
            StatusRow(
                entry.file,
                entry.content_hash,
                extraction.status.value,
                _recorded_count(session, extraction.id),
                extraction.chunk_count,
                extraction.validated_count,
                entry.proposals,
            )
        )
    return rows


# --- Reading the bundle and ledger for phase 3 -----------------------------------


def read_phase3(bundle_dir: Path) -> tuple[Bundle, ledgers.Ledger]:
    """The bundle and its ledger, refusing a format-1 bundle and a missing, invalid
    or out-of-date ledger (it must equal what ``reconcile`` writes, byte for byte)."""
    bundle = read_bundle(Path(bundle_dir))
    ledgers.reconcile(bundle, None)  # raises LedgerError for a format-1 bundle
    ledger = ledgers.read_ledger(bundle.path)
    if ledger is None:
        raise ProposalError(
            f'no ingestion ledger yet; run "ideology ingestion update {bundle.path}"'
        )
    derived, lines = ledgers.reconcile(bundle, ledger)
    if ledgers.render_ledger(derived) != ledgers.render_ledger(ledger):
        raise ProposalError(ledgers.out_of_date_problem(bundle, lines))
    return bundle, ledger


def kept_entry(bundle: Bundle, ledger: ledgers.Ledger, file: str) -> ledgers.DocumentEntry:
    """The ledger entry of ``file``; refuses an unlisted or not-kept document."""
    return _kept_entry(bundle, ledger, file)


@dataclass(frozen=True)
class DocumentSource:
    """A kept document resolved to its imported page text (lowest-id current row)."""

    file: str
    content_hash: str
    source_document_id: int
    pages: tuple[str, ...]


def resolve_document(
    session: Session, bundle: Bundle, entry: ledgers.DocumentEntry
) -> DocumentSource | str:
    """The imported page text of ``entry``, or the problem when it is not imported."""
    missing = (
        f"document {entry.file}: content_hash {_short(entry.content_hash)}... is not imported; "
        f'run "ideology data import {bundle.path}"'
    )
    election = find_election(session, bundle)
    if election is None:
        return missing
    row = session.scalars(
        select(SourceDocument)
        .join(Party, Party.id == SourceDocument.party_id)
        .where(
            Party.election_id == election.id,
            SourceDocument.bundle_file == entry.file,
            SourceDocument.content_hash == entry.content_hash,
            SourceDocument.status == SourceDocumentStatus.PARSED,
            SourceDocument.replaced_by_id.is_(None),
        )
        .order_by(SourceDocument.id)
        .limit(1)
    ).one_or_none()
    if row is None:
        return missing
    pages = session.execute(
        select(SourceDocumentPage.page_number, SourceDocumentPage.text)
        .where(SourceDocumentPage.source_document_id == row.id)
        .order_by(SourceDocumentPage.page_number)
    ).all()
    if [number for number, _ in pages] != list(range(1, len(pages) + 1)):
        return f"document {entry.file}: source document {row.id} does not have pages 1..n"
    return DocumentSource(entry.file, entry.content_hash, row.id, tuple(t for _, t in pages))


# --- Pinning ----------------------------------------------------------------------


def _pin_problem(extraction: ProposalExtraction, provider: LLMProvider, file: str) -> str | None:
    pinned = (
        extraction.llm_provider,
        extraction.llm_model,
        extraction.prompt_version,
        extraction.chunk_max_chars,
    )
    current = (
        provider.name,
        provider.model,
        PROPOSAL_EXTRACTION.version,
        PROPOSAL_CHUNK_MAX_CHARS,
    )
    if pinned == current:
        return None
    return _mismatch(extraction, file)


def _mismatch(extraction: ProposalExtraction, file: str) -> str:
    return (
        f"document {file}: extraction {_short(extraction.content_hash)}... is in progress with "
        f"provider {extraction.llm_provider}, model {extraction.llm_model}, prompt {TASK} "
        f"{extraction.prompt_version} (chunks of {extraction.chunk_max_chars} characters); "
        f"set LLM_PROVIDER/LLM_MODEL to match, or pass --restart {file}"
    )


# --- Planning (no writes) ---------------------------------------------------------


@dataclass
class PlannedDocument:
    entry: ledgers.DocumentEntry
    source: DocumentSource | None
    problem: str | None = None


@dataclass
class ExtractionPlan:
    bundle: Bundle
    documents: list[PlannedDocument]
    restart: str | None = None


def prepare_extraction(
    engine: Engine,
    bundle_dir: Path,
    provider: LLMProvider,
    *,
    file: str | None = None,
    restart: str | None = None,
) -> ExtractionPlan:
    """Every check that refuses ``extract`` before anything is called or written.

    Raises for a format-1 bundle, a missing/invalid/out-of-date ledger, a
    ``--file`` or ``--restart`` that is not a kept document, ``--restart`` of a
    complete (or absent) extraction, and an in-progress extraction pinned to
    another provider, model, prompt version or chunk size (P10). A kept
    document that is not imported is not refused: it gets a ``problem``.
    """
    bundle, ledger = read_phase3(bundle_dir)
    entries = [_kept_entry(bundle, ledger, file)] if file is not None else kept_documents(ledger)
    if restart is not None:
        restart_entry = _kept_entry(bundle, ledger, restart)
        if file is not None and restart != file:
            # Validation Low: a restart outside the selection would be ignored silently.
            raise ProposalError(
                f"--restart {restart} must name the selected document (--file {file})"
            )
    documents: list[PlannedDocument] = []
    session = Session(engine)
    try:
        if restart is not None:
            extraction = get_extraction(session, restart_entry.content_hash)
            if extraction is None:
                raise ProposalError(f"document {restart}: there is no extraction to restart")
            if extraction.status is ProposalExtractionStatus.COMPLETE:
                raise ProposalError(
                    f"document {restart}: extraction {_short(extraction.content_hash)}... is "
                    "complete; --restart applies only to an in-progress extraction"
                )
        for entry in entries:
            resolved = resolve_document(session, bundle, entry)
            if isinstance(resolved, str):
                documents.append(PlannedDocument(entry, None, resolved))
                continue
            extraction = get_extraction(session, entry.content_hash)
            if (
                extraction is not None
                and extraction.status is ProposalExtractionStatus.IN_PROGRESS
                and entry.file != restart
            ):
                problem = _pin_problem(extraction, provider, entry.file)
                if problem is not None:
                    raise ProposalError(problem)
            documents.append(PlannedDocument(entry, resolved))
    finally:
        session.rollback()
        session.close()
    return ExtractionPlan(bundle, documents, restart)


# --- Extracting -------------------------------------------------------------------


@dataclass
class Budget:
    """The new-call limit of one invocation (``--max-calls``) and its usage."""

    max_calls: int = DEFAULT_MAX_CALLS
    new_calls: int = 0
    reused_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def exhausted(self) -> bool:
        return self.new_calls >= self.max_calls

    def record(self, result: LLMResult[Any]) -> None:
        self.new_calls += 1
        self.input_tokens += result.input_tokens
        self.output_tokens += result.output_tokens


@dataclass(frozen=True)
class DocumentOutcome:
    """``reused`` (complete before), ``complete`` (finalized now) or ``stopped`` (budget)."""

    state: str
    validated_count: int | None = None
    counts: dict[str, int] = field(default_factory=dict)


def restart_extraction(engine: Engine, content_hash: str) -> int:
    """Delete an ``in_progress`` extraction and its calls (``--restart``); return the
    number of calls deleted. Refuses a complete extraction."""
    with session_scope(engine) as session:
        extraction = get_extraction(session, content_hash)
        if extraction is None:
            return 0
        if extraction.status is not ProposalExtractionStatus.IN_PROGRESS:
            raise ProposalError(
                f"extraction {_short(content_hash)}... is complete and is never deleted"
            )
        deleted = session.execute(
            delete(ProposalExtractionCall).where(
                ProposalExtractionCall.extraction_id == extraction.id
            )
        ).rowcount
        session.delete(extraction)
    return int(deleted or 0)


def _no_echo(*args: Any, **kwargs: Any) -> None:
    return None


def _completion_line(label: str, extraction: ProposalExtraction) -> str:
    counts = dropped_counts(extraction)
    dropped = ", ".join(f"{reason} {counts[reason]}" for reason in DROP_REASONS)
    return f"{label}: complete: {extraction.validated_count} proposals (dropped: {dropped})"


def _requests(chunks: Sequence[Chunk]) -> list[LLMRequest[ProposalList]]:
    return [proposal_request(chunk) for chunk in chunks]


def _finalize(
    engine: Engine,
    extraction_id: int,
    chunks: Sequence[Chunk],
    requests: Sequence[LLMRequest[ProposalList]],
    pages: Sequence[str],
) -> ProposalExtraction:
    """Check every recorded output and store the Proposals, in one transaction. No LLM."""
    with session_scope(engine) as session:
        extraction = session.get(ProposalExtraction, extraction_id)
        assert extraction is not None
        if extraction.status is ProposalExtractionStatus.COMPLETE:
            session.expunge(extraction)
            return extraction
        calls = session.scalars(
            select(ProposalExtractionCall)
            .where(ProposalExtractionCall.extraction_id == extraction_id)
            .order_by(ProposalExtractionCall.chunk_index)
        ).all()
        if [call.chunk_index for call in calls] != list(range(len(chunks))):
            raise ProposalError(
                f"extraction {_short(extraction.content_hash)}...: recorded chunks do not "
                f"cover 0..{len(chunks) - 1}"
            )
        outputs = [
            request.schema.model_validate(call.output)
            for request, call in zip(requests, calls, strict=True)
        ]
        result = check_items(chunks, outputs, pages)
        session.add_all(
            Proposal(
                extraction_id=extraction_id,
                content_hash=extraction.content_hash,
                ordinal=item.ordinal,
                chunk_index=item.chunk_index,
                page=item.page,
                text=item.text,
                categories=list(item.categories),
                tags=list(item.tags),
            )
            for item in result.kept
        )
        extraction.validated_count = len(result.kept)
        extraction.report = result.report()
        extraction.status = ProposalExtractionStatus.COMPLETE
        extraction.completed_at = dt.datetime.now(dt.UTC)
        session.flush()
        session.expunge(extraction)
        return extraction


def extract_document(
    engine: Engine,
    provider: LLMProvider,
    source: DocumentSource,
    *,
    budget: Budget,
    echo: Echo = _no_echo,
) -> DocumentOutcome:
    """Extract one document: reuse, resume or call chunk by chunk, then finalize.

    Each new call is committed on its own as soon as it returns. Stops (state
    ``stopped``) when the budget is spent and a call is still needed. An
    ``LLMError`` propagates with every earlier call kept. Raises
    ``ProposalError`` when a recorded call was made with another request
    (pinning, P10) or no longer validates.
    """
    label = f"Document {source.file} ({_short(source.content_hash)})"
    chunks = build_chunks(source.pages)
    requests = _requests(chunks)
    hashes = [request_hash(provider.name, provider.model, request) for request in requests]
    with session_scope(engine) as session:
        extraction = get_extraction(session, source.content_hash)
        if extraction is not None and extraction.status is ProposalExtractionStatus.COMPLETE:
            echo(
                f"{label}: reused complete extraction ({extraction.validated_count} proposals)"
            )
            return DocumentOutcome("reused", extraction.validated_count, dropped_counts(extraction))
        if extraction is None:
            extraction = ProposalExtraction(
                content_hash=source.content_hash,
                status=ProposalExtractionStatus.IN_PROGRESS,
                llm_provider=provider.name,
                llm_model=provider.model,
                prompt_version=PROPOSAL_EXTRACTION.version,
                chunk_max_chars=PROPOSAL_CHUNK_MAX_CHARS,
                chunk_count=len(chunks),
                check_version=CHECK_VERSION,
            )
            session.add(extraction)
            session.flush()
        else:
            problem = _pin_problem(extraction, provider, source.file)
            if problem is None and extraction.chunk_count != len(chunks):
                problem = _mismatch(extraction, source.file)
            if problem is not None:
                raise ProposalError(problem)
        extraction_id = extraction.id
        recorded = {
            call.chunk_index: (call.request_hash, call.output)
            for call in session.scalars(
                select(ProposalExtractionCall).where(
                    ProposalExtractionCall.extraction_id == extraction_id
                )
            )
        }
        mismatch = _mismatch(extraction, source.file)
    # Check every recorded call before the first new one.
    for index, (stored_hash, output) in sorted(recorded.items()):
        if index >= len(chunks) or stored_hash != hashes[index]:
            raise ProposalError(mismatch)
        try:
            requests[index].schema.model_validate(output)
        except ValidationError:
            raise ProposalError(
                f"document {source.file}: the recorded call of chunk {index + 1} no longer "
                f"validates; pass --restart {source.file}"
            ) from None
    if recorded:
        echo(f"{label}: resuming ({len(recorded)}/{len(chunks)} chunks recorded)")
    budget.reused_calls += len(recorded)
    for chunk, request, hash_ in zip(chunks, requests, hashes, strict=True):
        if chunk.index in recorded:
            continue
        if budget.exhausted:
            return DocumentOutcome("stopped")
        result = provider.generate(request)
        with session_scope(engine) as session:
            session.add(
                ProposalExtractionCall(
                    extraction_id=extraction_id,
                    chunk_index=chunk.index,
                    first_page=chunk.first_page,
                    last_page=chunk.last_page,
                    request_hash=hash_,
                    output=result.output.model_dump(mode="json"),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            )
        budget.record(result)
        echo(f"{label}: chunk {chunk.index + 1}/{len(chunks)}")
    extraction = _finalize(engine, extraction_id, chunks, requests, source.pages)
    echo(_completion_line(label, extraction))
    return DocumentOutcome("complete", extraction.validated_count, dropped_counts(extraction))


# --- Ledger handoff ---------------------------------------------------------------


def record_in_ledger(
    bundle_dir: Path, entry: ledgers.DocumentEntry, validated_count: int, echo: Echo = _no_echo
) -> bool:
    """Record ``validated_count`` for ``entry`` unless the ledger already has it.

    Only through ``ingestion_ledger.record_extraction_in_dir``; the Parties'
    phases follow from the summed counts and N. Returns True when it wrote.
    """
    ledger = ledgers.read_ledger(bundle_dir)
    if ledger is not None and ledger.document(entry.file).proposals == validated_count:
        return False
    parties = ledgers.record_extraction_in_dir(
        bundle_dir,
        entry.file,
        content_hash=entry.content_hash,
        validated_proposals=validated_count,
    )
    after = ledgers.read_ledger(bundle_dir)
    assert after is not None
    echo(f"Ledger: {entry.file}: {validated_count} validated proposals")
    for party in parties:
        echo(f"Party {party.short_name}: {ledgers.state_label(party, after.min_proposals)}")
    return True


@dataclass
class RunSummary:
    budget: Budget
    failed: list[str] = field(default_factory=list)
    stopped: bool = False
    error: str | None = None


def execute_plan(
    engine: Engine,
    provider: LLMProvider,
    plan: ExtractionPlan,
    *,
    max_calls: int = DEFAULT_MAX_CALLS,
    echo: Echo = _no_echo,
) -> RunSummary:
    """Run a prepared plan: documents in order, one finished before the next.

    A document that is not imported is reported (``Error:``) and skipped. After
    each complete or reused extraction the ledger count is recorded when it
    differs. Stops at the call budget or at the first ``LLMError`` (kept in
    ``RunSummary.error``); every call made so far stays recorded.
    """
    summary = RunSummary(Budget(max_calls=max_calls))
    for planned in plan.documents:
        if planned.problem is not None or planned.source is None:
            assert planned.problem is not None
            echo(f"Error: {planned.problem}", err=True)
            summary.failed.append(planned.problem)
            continue
        if planned.entry.file == plan.restart:
            deleted = restart_extraction(engine, planned.entry.content_hash)
            echo(
                f"Document {planned.entry.file} ({_short(planned.entry.content_hash)}): "
                f"restarted ({deleted} recorded calls deleted)"
            )
        try:
            outcome = extract_document(
                engine, provider, planned.source, budget=summary.budget, echo=echo
            )
        except LLMError as exc:
            summary.error = f"document {planned.entry.file}: {exc}"
            break
        if outcome.state == "stopped":
            summary.stopped = True
            break
        assert outcome.validated_count is not None
        record_in_ledger(plan.bundle.path, planned.entry, outcome.validated_count, echo)
    return summary


__all__ = [
    "DEFAULT_MAX_CALLS",
    "Budget",
    "DocumentOutcome",
    "DocumentSource",
    "ExtractionPlan",
    "PlannedDocument",
    "ProposalError",
    "RunSummary",
    "StatusRow",
    "UnfinishedExtraction",
    "bundle_count_problems",
    "dropped_counts",
    "dropped_items",
    "execute_plan",
    "extract_document",
    "get_extraction",
    "kept_documents",
    "kept_entry",
    "ledger_count_problems",
    "load_proposals",
    "prepare_extraction",
    "read_phase3",
    "record_in_ledger",
    "resolve_document",
    "restart_extraction",
    "status_rows",
    "unfinished_extractions",
]
