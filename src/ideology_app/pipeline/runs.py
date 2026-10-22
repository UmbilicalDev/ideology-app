"""Pipeline Run service: queue a run, execute it, list runs and Dataset Versions.

Lifecycle: ``queued`` -> ``running`` -> ``validating`` -> ``passed`` | ``failed``.
A run is ``failed`` when Statement generation or Party Position extraction fails
(or is interrupted), or when a Validation check fails; a run that failed
Validation keeps its ``candidate`` Dataset Version, which is never published.
A ``passed`` run publishes its version (``publishing.publish_dataset_version``)
in the commit that stores its Validation results, unless a newer run's version
is already Published.
Statement generation returns a Statement Pool (built from the Party-balanced
Agenda, ``agenda.balance_candidates``); Party Positions are extracted
for the whole pool, and ``selection.select_statements`` (deterministic, no LLM)
chooses the Questionnaire's Statements before anything is written.
Dataset Versions, Statements and Party Positions are only ever inserted here,
together in one commit with the run's ``statement_selection``; Validation results are inserted with the run's
``passed`` / ``failed`` status and the ``validation_settings`` it used. The only update is the Dataset Version status
change made by ``publishing``; there is no delete path.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import Engine, Select, exists, func, select
from sqlalchemy.orm import Session, selectinload

from ideology_app import config
from ideology_app.config import GenerationMode, ValidationSettings
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
    PipelineRunCall,
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
    build_document_chunks,
    generate_statements,
)
from ideology_app.pipeline import publishing
from ideology_app.pipeline.checkpoint import CheckpointProvider
from ideology_app.pipeline.positions import (
    PositionResult,
    check_position_budget,
    extract_positions,
)
from ideology_app.pipeline.prompts import PROMPT_VERSIONS, StatementDraft
from ideology_app.pipeline.selection import select_statements
from ideology_app.validation import CHECKS, MESSAGE_MAX, Check, load_input, run_checks

_REASON_MAX = 500
INTERRUPTED_REASON = "interrupted"


@dataclass(frozen=True)
class RunOutcome:
    """What ``execute_run`` / ``validate_run`` ended with (plain data, safe after the session).

    ``failed_checks`` names the Validation checks that failed, in registry order.
    ``publish`` is set only for a ``passed`` run: what publishing its version did.
    """

    run_id: int
    status: PipelineRunStatus
    dataset_version_id: int | None
    statement_count: int
    failure_reason: str | None
    position_count: int = 0
    failed_checks: tuple[str, ...] = ()
    publish: publishing.PublishOutcome | None = None


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
            # Only current documents: a re-fetched URL's older version stays
            # for old Evidence but is never read again.
            SourceDocument.replaced_by_id.is_(None),
        )
    )


def _lineage_roots(session: Session, election_id: int) -> dict[int, int]:
    """For every Source Document of the Election, the id of its first version.

    A document that ``source refetch`` registered as the replacement of
    another one shares that one's root, so a re-fetched main manifesto stays
    first in its Party.
    """
    rows = session.execute(
        select(SourceDocument.id, SourceDocument.replaced_by_id)
        .join(Party, SourceDocument.party_id == Party.id)
        .where(Party.election_id == election_id)
    ).all()
    predecessor = {new: old for old, new in rows if new is not None}
    roots: dict[int, int] = {}
    for document_id, _ in rows:
        root = document_id
        seen = {root}
        while root in predecessor and predecessor[root] not in seen:
            root = predecessor[root]
            seen.add(root)
        roots[document_id] = root
    return roots


def queue_run(
    session: Session,
    election_id: int,
    *,
    llm_provider: str,
    llm_model: str,
    generation_mode: GenerationMode,
    resumed_from_run_id: int | None = None,
    allow_finished_source: bool = False,
) -> PipelineRun:
    """Record a ``queued`` run. Raises NotFoundError or InvalidInputError.

    With ``resumed_from_run_id`` the run will reuse that run's identical
    recorded LLM calls (``pipeline-run-checkpoint``); it must be a run of the
    same Election, queued for the same provider and model, that has no Dataset
    Version (``--resume-from``). With ``allow_finished_source`` that run may
    also have a Dataset Version (``--reuse-from``: reuse from a finished run).
    The caller commits.
    """
    _get_election(session, election_id)
    has_parsed = session.scalar(select(exists(_parsed_documents_query(election_id))))
    if not has_parsed:
        raise InvalidInputError(f"election {election_id} has no parsed source documents")
    if resumed_from_run_id is not None:
        _check_resumable(
            session,
            resumed_from_run_id,
            election_id,
            llm_provider,
            llm_model,
            allow_finished_source=allow_finished_source,
        )
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
        resumed_from_run_id=resumed_from_run_id,
    )
    session.add(run)
    session.flush()
    return run


def _check_resumable(
    session: Session,
    run_id: int,
    election_id: int,
    llm_provider: str,
    llm_model: str,
    *,
    allow_finished_source: bool = False,
) -> None:
    source = session.get(PipelineRun, run_id)
    if source is None:
        raise NotFoundError(f"pipeline run {run_id} not found")
    if source.election_id != election_id:
        raise InvalidInputError(
            f"pipeline run {run_id} belongs to election {source.election_id}, "
            f"not {election_id}"
        )
    if (source.llm_provider, source.llm_model) != (llm_provider, llm_model):
        raise InvalidInputError(
            f"pipeline run {run_id} used {source.llm_provider}/{source.llm_model}, "
            f"not {llm_provider}/{llm_model}"
        )
    if source.dataset_version is not None and not allow_finished_source:
        raise InvalidInputError(
            f"pipeline run {run_id} already has dataset version "
            f"{source.dataset_version.id}; there is nothing to resume"
        )


@dataclass(frozen=True)
class _RunInput:
    documents: list[DocumentPages]
    party_ids: list[int]
    resumed_from_run_id: int | None = None


def _start(engine: Engine, run_id: int, provider: LLMProvider) -> _RunInput:
    """Check the run, mark it ``running``, record and load its input. Commits.

    Only current documents (``replaced_by_id`` null) are read. Each Party's
    parsed document with the lowest first-version id (lineage root) is its
    ``main`` (joint) manifesto; any other parsed document is ``additional``.
    Without re-fetched replacements this is the lowest-id document.
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
        roots = _lineage_roots(session, run.election_id)
        documents = sorted(
            session.scalars(
                _parsed_documents_query(run.election_id).options(
                    selectinload(SourceDocument.pages)
                )
            ).all(),
            key=lambda d: (d.party_id, roots.get(d.id, d.id), d.id),
        )
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
        resumed_from = run.resumed_from_run_id
    return _RunInput(loaded, party_ids, resumed_from)


def _finish(
    engine: Engine,
    run_id: int,
    usage: Usage,
    statements: Sequence[StatementDraft] | None,
    positions: dict[int, list[PositionResult]] | None,
    failure_reason: str | None,
    selection: dict[str, Any] | None = None,
) -> RunOutcome:
    """Record the result: a complete candidate Dataset Version, or ``failed``. Commits.

    The Dataset Version, its Statements, every Party Position and the run's
    ``statement_selection`` report are inserted in this one commit, so a
    Dataset Version never exists without them. A failed run stores no selection.
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
        run.statement_selection = selection
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


def execute_run(
    engine: Engine,
    run_id: int,
    provider: LLMProvider,
    validation_settings: ValidationSettings | None = None,
) -> RunOutcome:
    """Generate Statements and extract Party Positions for a ``queued`` run, then validate it.

    Generation returns a Statement Pool; positions are extracted for the whole
    pool, and ``selection.select_statements`` (with the same
    ``validation_settings``) chooses the Statements of the Dataset Version.
    Commits up to four times: ``running`` (with the Source Documents it reads)
    before any LLM call, then (after the calls, made outside any transaction)
    either ``validating`` with a complete ``candidate`` Dataset Version, or
    ``failed`` with a reason and no Dataset Version. A ``validating`` run is
    then validated by ``validate_run`` (``passed`` or ``failed``), whose outcome
    is returned; the same ``validation_settings`` object gives the pool bounds
    of the ``generate_statements`` schema, drives the selection and is passed to it (``None``:
    read with ``config.validation_settings()`` first, so an invalid value raises
    ``ConfigError`` before any write or LLM call). Ctrl-C records ``failed``
    (``interrupted``) and re-raises. Every successful LLM call is committed to
    ``pipeline_run_calls`` as it returns; a run queued with
    ``resumed_from_run_id`` reuses that run's identical calls
    (``checkpoint.CheckpointProvider``).
    Raises NotFoundError / InvalidInputError, changing nothing, when the run is
    unknown, not ``queued``, or was queued for another provider or model.
    """
    if validation_settings is None:
        validation_settings = config.validation_settings()
    run_input = _start(engine, run_id, provider)
    provider = CheckpointProvider(provider, engine, run_id, run_input.resumed_from_run_id)
    usage = Usage()
    try:
        check_position_budget(run_input.documents)
        pool = generate_statements(
            provider,
            build_document_chunks(run_input.documents),
            usage,
            settings=validation_settings,
        )
        pool_positions = extract_positions(
            provider,
            [s.text for s in pool.statements],
            run_input.documents,
            run_input.party_ids,
            usage,
        )
        selection = select_statements(
            pool.statements, pool_positions, run_input.party_ids, validation_settings
        )
        outcome = _finish(
            engine,
            run_id,
            usage,
            selection.statements,
            selection.positions,
            None,
            selection={**selection.report, "agenda": pool.agenda.report},
        )
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
        return validate_run(engine, run_id, settings=validation_settings)
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
    engine: Engine,
    run_id: int,
    checks: Sequence[Check] = CHECKS,
    settings: ValidationSettings | None = None,
) -> RunOutcome:
    """Run every Validation check on a ``validating`` run and record the result. Commits.

    In one commit, inserts one ``ValidationResult`` (with its report entries)
    per check, in order, and sets ``passed`` when every check passed, else
    ``failed`` with ``validation failed: <names>``. On ``passed`` the same commit
    publishes the Dataset Version (``publishing.publish_dataset_version``:
    supersedes the Election's Published version, sets a ``draft`` Election
    ``active``), unless a newer run's version is Published, in which case it
    stays ``candidate``; on ``failed`` it stays ``candidate`` and nothing about
    publication changes. If a check or the publish step raises, nothing is
    stored, the run is set ``failed`` with ``unexpected error: <ClassName>``
    (Ctrl-C: ``interrupted``) and the exception is re-raised. Raises NotFoundError / InvalidInputError,
    changing nothing, when the run is unknown or not ``validating``. Needs no
    LLM provider. ``settings`` holds the check thresholds; when ``None`` it is
    read with ``config.validation_settings()`` first, so an invalid value
    raises ``ConfigError`` before any session and changes nothing. The
    thresholds are recorded on the run (``validation_settings``) in the commit
    that stores the results, on both outcomes; never on the rollback path.
    """
    if settings is None:
        settings = config.validation_settings()
    checking = False
    try:
        with session_scope(engine) as session:
            run = _validating_run(session, run_id)
            checking = True
            data = load_input(session, run, settings)
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
            run.validation_settings = asdict(settings)
            if failed:
                run.status = PipelineRunStatus.FAILED
                run.failure_reason = ("validation failed: " + ", ".join(failed))[:_REASON_MAX]
            else:
                run.status = PipelineRunStatus.PASSED
                run.failure_reason = None
            # This flush is the session's first write, so on SQLite it takes the
            # database write lock before publishing reads the Published version.
            session.flush()
            version = run.dataset_version
            assert version is not None
            publish = None if failed else publishing.publish_dataset_version(session, version)
            outcome = RunOutcome(
                run_id,
                run.status,
                version.id,
                len(data.statements),
                run.failure_reason,
                len(data.positions),
                failed,
                publish,
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


def list_queued_run_ids(session: Session, election_id: int | None = None) -> list[int]:
    """The ids of ``queued`` Pipeline Runs in id order, of one Election or all.

    Raises NotFoundError for an unknown Election.
    """
    query = select(PipelineRun.id).where(PipelineRun.status == PipelineRunStatus.QUEUED)
    if election_id is not None:
        _get_election(session, election_id)
        query = query.where(PipelineRun.election_id == election_id)
    return list(session.scalars(query.order_by(PipelineRun.id)))


@dataclass(frozen=True)
class UnfinishedRun:
    """A stopped run that should be resumed rather than paid for again (plain data)."""

    run_id: int
    status: PipelineRunStatus
    recorded_calls: int


_UNFINISHED_STATUSES = (PipelineRunStatus.RUNNING, PipelineRunStatus.FAILED)


def find_unfinished_run(
    session: Session,
    election_id: int,
    provider: str | None = None,
    model: str | None = None,
) -> UnfinishedRun | None:
    """The Election's latest run with recorded calls, when it is unfinished. Read-only.

    It takes the highest-id run of ``election_id`` that has at least one
    recorded LLM call. It is unfinished when it has no Dataset Version, its
    status is ``running`` or ``failed``, and (when given) its provider and model
    equal ``provider`` / ``model`` (another model's run cannot be resumed).
    Otherwise, or when the Election has no such run, ``None``.
    """
    calls = (
        select(PipelineRunCall.pipeline_run_id, func.count().label("calls"))
        .group_by(PipelineRunCall.pipeline_run_id)
        .subquery()
    )
    row = session.execute(
        select(PipelineRun, calls.c.calls)
        .join(calls, calls.c.pipeline_run_id == PipelineRun.id)
        .where(PipelineRun.election_id == election_id)
        .order_by(PipelineRun.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    run, recorded = row
    if run.dataset_version is not None or run.status not in _UNFINISHED_STATUSES:
        return None
    if provider is not None and run.llm_provider != provider:
        return None
    if model is not None and run.llm_model != model:
        return None
    return UnfinishedRun(run_id=run.id, status=run.status, recorded_calls=int(recorded))


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
