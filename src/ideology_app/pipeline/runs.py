"""Pipeline Run service: queue a run, execute it, list runs and Dataset Versions.

Lifecycle: ``queued`` -> ``running`` -> ``validating`` -> ``passed`` | ``failed``.
A run is ``failed`` when Statement generation or Party Position extraction fails
(or is interrupted), or when a Validation check fails; a run that failed
Validation keeps its ``candidate`` Dataset Version, which is never published.
Dataset Versions, Statements and Party Positions are only ever inserted here,
together in one commit; Validation results are inserted with the run's
``passed`` / ``failed`` status. There is no update or delete path.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, Select, exists, select
from sqlalchemy.orm import Session, selectinload

from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError
from ideology_app.llm.base import LLMError, LLMProvider
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    Election,
    Party,
    PartyPosition,
    PipelineRun,
    PipelineRunSourceDocument,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentRole,
    SourceDocumentStatus,
    Statement,
    ValidationReportEntry,
    ValidationResult,
    _utcnow,
)
from ideology_app.pipeline.generation import (
    DocumentPages,
    GenerationError,
    Usage,
    build_chunks,
    generate_statements,
)
from ideology_app.pipeline.positions import (
    PositionResult,
    check_position_budget,
    extract_positions,
)
from ideology_app.pipeline.prompts import PROMPT_VERSIONS, StatementDraft
from ideology_app.validation import CHECKS, MESSAGE_MAX, Check, load_input, run_checks

_REASON_MAX = 500
INTERRUPTED_REASON = "interrupted"


@dataclass(frozen=True)
class RunOutcome:
    """What ``execute_run`` / ``validate_run`` ended with (plain data, safe after the session).

    ``failed_checks`` names the Validation checks that failed, in registry order.
    """

    run_id: int
    status: PipelineRunStatus
    dataset_version_id: int | None
    statement_count: int
    failure_reason: str | None
    position_count: int = 0
    failed_checks: tuple[str, ...] = ()


def _get_election(session: Session, election_id: int) -> Election:
    election = session.get(Election, election_id)
    if election is None:
        raise NotFoundError(f"election {election_id} not found")
    return election


def _parsed_documents_query(election_id: int) -> Select[tuple[SourceDocument]]:
    return (
        select(SourceDocument)
        .join(Party, SourceDocument.party_id == Party.id)
        .where(
            Party.election_id == election_id,
            SourceDocument.status == SourceDocumentStatus.PARSED,
        )
    )


def queue_run(
    session: Session,
    election_id: int,
    *,
    llm_provider: str,
    llm_model: str,
    generation_mode: GenerationMode,
) -> PipelineRun:
    """Record a ``queued`` run. Raises NotFoundError or InvalidInputError.

    The caller commits.
    """
    _get_election(session, election_id)
    has_parsed = session.scalar(select(exists(_parsed_documents_query(election_id))))
    if not has_parsed:
        raise InvalidInputError(f"election {election_id} has no parsed source documents")
    run = PipelineRun(
        election_id=election_id,
        status=PipelineRunStatus.QUEUED,
        llm_provider=llm_provider,
        llm_model=llm_model,
        generation_mode=generation_mode,
        prompt_versions=dict(PROMPT_VERSIONS),
        llm_calls=0,
        input_tokens=0,
        output_tokens=0,
    )
    session.add(run)
    session.flush()
    return run


@dataclass(frozen=True)
class _RunInput:
    documents: list[DocumentPages]
    party_ids: list[int]


def _start(engine: Engine, run_id: int, provider: LLMProvider) -> _RunInput:
    """Check the run, mark it ``running``, record and load its input. Commits.

    Each Party's lowest-id parsed document is its ``main`` (joint) manifesto;
    any other parsed document is ``additional``.
    """
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError(f"pipeline run {run_id} not found")
        if run.status is not PipelineRunStatus.QUEUED:
            raise InvalidInputError(
                f"pipeline run {run_id} is {run.status.value}, expected queued"
            )
        if (provider.name, provider.model) != (run.llm_provider, run.llm_model):
            raise InvalidInputError(
                f"pipeline run {run_id} was queued for {run.llm_provider}/{run.llm_model}, "
                f"not {provider.name}/{provider.model}"
            )
        party_ids = list(
            session.scalars(
                select(Party.id).where(Party.election_id == run.election_id).order_by(Party.id)
            )
        )
        documents = session.scalars(
            _parsed_documents_query(run.election_id)
            .options(selectinload(SourceDocument.pages))
            .order_by(SourceDocument.party_id, SourceDocument.id)
        ).all()
        loaded: list[DocumentPages] = []
        seen_parties: set[int] = set()
        for d in documents:
            role = (
                SourceDocumentRole.ADDITIONAL
                if d.party_id in seen_parties
                else SourceDocumentRole.MAIN
            )
            seen_parties.add(d.party_id)
            loaded.append(
                DocumentPages(
                    party_id=d.party_id,
                    document_id=d.id,
                    pages=[(p.page_number, p.text) for p in d.pages],
                    source_url=d.source_url,
                    role=role,
                )
            )
            session.add(
                PipelineRunSourceDocument(
                    pipeline_run_id=run.id, source_document_id=d.id, role=role
                )
            )
        run.status = PipelineRunStatus.RUNNING
        run.started_at = _utcnow()
    return _RunInput(loaded, party_ids)


def _finish(
    engine: Engine,
    run_id: int,
    usage: Usage,
    statements: Sequence[StatementDraft] | None,
    positions: dict[int, list[PositionResult]] | None,
    failure_reason: str | None,
) -> RunOutcome:
    """Record the result: a complete candidate Dataset Version, or ``failed``. Commits.

    The Dataset Version, its Statements and every Party Position are inserted
    in this one commit, so a Dataset Version never exists without them.
    """
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.llm_calls = usage.calls
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.generation_finished_at = _utcnow()
        if statements is None or positions is None:
            run.status = PipelineRunStatus.FAILED
            run.failure_reason = (failure_reason or "")[:_REASON_MAX]
            session.flush()
            return RunOutcome(run_id, run.status, None, 0, run.failure_reason)
        version = DatasetVersion(
            election_id=run.election_id,
            pipeline_run_id=run.id,
            status=DatasetVersionStatus.CANDIDATE,
        )
        session.add(version)
        session.flush()
        rows = [
            Statement(
                dataset_version_id=version.id,
                position=position,
                text=draft.text,
                topic=draft.topic,
            )
            for position, draft in enumerate(statements, start=1)
        ]
        session.add_all(rows)
        session.flush()
        position_count = 0
        for party_id in sorted(positions):
            for result in positions[party_id]:
                session.add(
                    PartyPosition(
                        statement_id=rows[result.statement_number - 1].id,
                        party_id=party_id,
                        value=result.value,
                        evidence_source_document_id=result.document_id,
                        evidence_quote=result.quote,
                        evidence_page=result.page,
                        evidence_url=result.url,
                    )
                )
                position_count += 1
        run.status = PipelineRunStatus.VALIDATING
        session.flush()
        return RunOutcome(
            run_id, run.status, version.id, len(statements), None, position_count
        )


def _fail(engine: Engine, run_id: int, usage: Usage, reason: str) -> RunOutcome:
    return _finish(engine, run_id, usage, None, None, reason)


def execute_run(engine: Engine, run_id: int, provider: LLMProvider) -> RunOutcome:
    """Generate Statements and extract Party Positions for a ``queued`` run, then validate it.

    Commits up to four times: ``running`` (with the Source Documents it reads)
    before any LLM call, then (after the calls, made outside any transaction)
    either ``validating`` with a complete ``candidate`` Dataset Version, or
    ``failed`` with a reason and no Dataset Version. A ``validating`` run is
    then validated by ``validate_run`` (``passed`` or ``failed``), whose outcome
    is returned. Ctrl-C records ``failed`` (``interrupted``) and re-raises.
    Raises NotFoundError / InvalidInputError, changing nothing, when the run is
    unknown, not ``queued``, or was queued for another provider or model.
    """
    run_input = _start(engine, run_id, provider)
    usage = Usage()
    try:
        check_position_budget(run_input.documents)
        statements = generate_statements(provider, build_chunks(run_input.documents), usage)
        positions = extract_positions(
            provider,
            [s.text for s in statements],
            run_input.documents,
            run_input.party_ids,
            usage,
        )
        outcome = _finish(engine, run_id, usage, statements, positions, None)
    except (LLMError, GenerationError) as exc:
        return _fail(engine, run_id, usage, str(exc))
    except KeyboardInterrupt:
        _fail(engine, run_id, usage, INTERRUPTED_REASON)
        raise
    except Exception as exc:
        _fail(engine, run_id, usage, f"unexpected error: {type(exc).__name__}")
        raise
    # Outside the try: validate_run records its own errors.
    if outcome.status is PipelineRunStatus.VALIDATING:
        return validate_run(engine, run_id)
    return outcome


def _validating_run(session: Session, run_id: int) -> PipelineRun:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError(f"pipeline run {run_id} not found")
    if run.status is not PipelineRunStatus.VALIDATING:
        raise InvalidInputError(
            f"pipeline run {run_id} is {run.status.value}, expected validating"
        )
    if run.dataset_version is None:
        raise InvalidInputError(f"pipeline run {run_id} has no dataset version")
    return run


def _mark_failed(engine: Engine, run_id: int, reason: str) -> None:
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.status = PipelineRunStatus.FAILED
        run.failure_reason = reason[:_REASON_MAX]


def validate_run(
    engine: Engine, run_id: int, checks: Sequence[Check] = CHECKS
) -> RunOutcome:
    """Run every Validation check on a ``validating`` run and record the result. Commits.

    In one commit, inserts one ``ValidationResult`` (with its report entries)
    per check, in order, and sets ``passed`` when every check passed, else
    ``failed`` with ``validation failed: <names>``. The Dataset Version stays
    ``candidate`` either way (publishing is a later feature, hooked on the
    ``passed`` path). If a check raises, nothing is stored, the run is set
    ``failed`` with ``unexpected error: <ClassName>`` (Ctrl-C: ``interrupted``)
    and the exception is re-raised. Raises NotFoundError / InvalidInputError,
    changing nothing, when the run is unknown or not ``validating``. Needs no
    LLM provider.
    """
    checking = False
    try:
        with session_scope(engine) as session:
            run = _validating_run(session, run_id)
            checking = True
            data = load_input(session, run)
            results = run_checks(data, checks)
            for result in results:
                session.add(
                    ValidationResult(
                        pipeline_run_id=run.id,
                        check_name=result.name,
                        passed=result.passed,
                        entries=[
                            ValidationReportEntry(
                                statement_id=entry.statement_id,
                                party_id=entry.party_id,
                                message=entry.message[:MESSAGE_MAX],
                            )
                            for entry in result.entries
                        ],
                    )
                )
            failed = tuple(r.name for r in results if not r.passed)
            if failed:
                run.status = PipelineRunStatus.FAILED
                run.failure_reason = ("validation failed: " + ", ".join(failed))[:_REASON_MAX]
            else:
                run.status = PipelineRunStatus.PASSED
                run.failure_reason = None
            session.flush()
            version = run.dataset_version
            assert version is not None
            outcome = RunOutcome(
                run_id,
                run.status,
                version.id,
                len(data.statements),
                run.failure_reason,
                len(data.positions),
                failed,
            )
    except KeyboardInterrupt:
        if checking:
            _mark_failed(engine, run_id, INTERRUPTED_REASON)
        raise
    except Exception as exc:
        if checking:
            _mark_failed(engine, run_id, f"unexpected error: {type(exc).__name__}")
        raise
    return outcome


def list_validation_results(session: Session, run_id: int) -> Sequence[ValidationResult]:
    """A run's Validation results in check order, with their entries. Raises NotFoundError."""
    if session.get(PipelineRun, run_id) is None:
        raise NotFoundError(f"pipeline run {run_id} not found")
    return session.scalars(
        select(ValidationResult)
        .where(ValidationResult.pipeline_run_id == run_id)
        .options(
            selectinload(ValidationResult.entries).selectinload(ValidationReportEntry.statement)
        )
        .order_by(ValidationResult.id)
    ).all()


def list_runs(session: Session, election_id: int) -> Sequence[PipelineRun]:
    """The Pipeline Runs of an Election in creation order. Raises NotFoundError."""
    _get_election(session, election_id)
    return session.scalars(
        select(PipelineRun)
        .where(PipelineRun.election_id == election_id)
        .options(
            selectinload(PipelineRun.dataset_version).selectinload(DatasetVersion.statements)
        )
        .order_by(PipelineRun.id)
    ).all()


def get_dataset_version(session: Session, dataset_version_id: int) -> DatasetVersion:
    """A Dataset Version with its Statements. Raises NotFoundError."""
    version = session.get(DatasetVersion, dataset_version_id)
    if version is None:
        raise NotFoundError(f"dataset version {dataset_version_id} not found")
    return version


def list_positions(
    session: Session, dataset_version_id: int, party_id: int | None = None
) -> Sequence[PartyPosition]:
    """The Party Positions of a Dataset Version, by Statement position then Party id.

    Raises NotFoundError for an unknown Dataset Version, or a Party that is
    unknown or not in the Dataset Version's Election.
    """
    version = get_dataset_version(session, dataset_version_id)
    query = (
        select(PartyPosition)
        .join(Statement, PartyPosition.statement_id == Statement.id)
        .where(Statement.dataset_version_id == version.id)
        .options(selectinload(PartyPosition.statement))
        .order_by(Statement.position, PartyPosition.party_id)
    )
    if party_id is not None:
        party = session.get(Party, party_id)
        if party is None or party.election_id != version.election_id:
            raise NotFoundError(f"party {party_id} not found")
        query = query.where(PartyPosition.party_id == party_id)
    return session.scalars(query).all()
