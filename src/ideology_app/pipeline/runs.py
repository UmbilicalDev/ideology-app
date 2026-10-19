"""Pipeline Run service: queue a run, execute it, list runs and Dataset Versions.

Lifecycle in this feature: ``queued`` -> ``running`` -> ``validating``, or
``failed`` when generation fails. Later features run Validation from
``validating``. Dataset Versions and Statements are only ever inserted here;
there is no update or delete path.
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
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentStatus,
    Statement,
    _utcnow,
)
from ideology_app.pipeline.generation import (
    DocumentPages,
    GenerationError,
    Usage,
    build_chunks,
    generate_statements,
)
from ideology_app.pipeline.prompts import PROMPT_VERSIONS, StatementDraft

_REASON_MAX = 500


@dataclass(frozen=True)
class RunOutcome:
    """What ``execute_run`` ended with (plain data, safe after the session)."""

    run_id: int
    status: PipelineRunStatus
    dataset_version_id: int | None
    statement_count: int
    failure_reason: str | None


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


def _start(engine: Engine, run_id: int, provider: LLMProvider) -> list[DocumentPages]:
    """Check the run, mark it ``running`` and load its input. Commits."""
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
        documents = session.scalars(
            _parsed_documents_query(run.election_id)
            .options(selectinload(SourceDocument.pages))
            .order_by(SourceDocument.party_id, SourceDocument.id)
        ).all()
        loaded = [
            DocumentPages(
                party_id=d.party_id,
                document_id=d.id,
                pages=[(p.page_number, p.text) for p in d.pages],
            )
            for d in documents
        ]
        run.status = PipelineRunStatus.RUNNING
        run.started_at = _utcnow()
    return loaded


def _finish(
    engine: Engine,
    run_id: int,
    usage: Usage,
    statements: Sequence[StatementDraft] | None,
    failure_reason: str | None,
) -> RunOutcome:
    """Record the result: a candidate Dataset Version, or ``failed``. Commits."""
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.llm_calls = usage.calls
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.generation_finished_at = _utcnow()
        if statements is None:
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
        session.add_all(
            Statement(
                dataset_version_id=version.id,
                position=position,
                text=draft.text,
                topic=draft.topic,
            )
            for position, draft in enumerate(statements, start=1)
        )
        run.status = PipelineRunStatus.VALIDATING
        session.flush()
        return RunOutcome(run_id, run.status, version.id, len(statements), None)


def execute_run(engine: Engine, run_id: int, provider: LLMProvider) -> RunOutcome:
    """Run Statement generation for a ``queued`` run and record the outcome.

    Commits three times: ``running`` before any LLM call, then (after the calls,
    made outside any transaction) either ``validating`` with a ``candidate``
    Dataset Version, or ``failed`` with a reason and no Dataset Version.
    Raises NotFoundError / InvalidInputError, changing nothing, when the run is
    unknown, not ``queued``, or was queued for another provider or model.
    """
    documents = _start(engine, run_id, provider)
    usage = Usage()
    try:
        statements = generate_statements(provider, build_chunks(documents), usage)
    except (LLMError, GenerationError) as exc:
        return _finish(engine, run_id, usage, None, str(exc))
    except Exception as exc:
        _finish(engine, run_id, usage, None, f"unexpected error: {type(exc).__name__}")
        raise
    try:
        return _finish(engine, run_id, usage, statements, None)
    except Exception as exc:
        _finish(engine, run_id, usage, None, f"unexpected error: {type(exc).__name__}")
        raise


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
