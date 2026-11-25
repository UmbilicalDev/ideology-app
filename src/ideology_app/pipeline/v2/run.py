"""The v2 Pipeline Run: queue, execute, write the Dataset Version, validate.

``execute_v2_run`` runs ``build_pool`` -> ``filter_pool`` ->
``assign_positions`` -> ``V2Pool`` -> ``_finish_v2`` -> ``validate_run``. The
seam for ``constituency-selection-validation`` is ``V2Pool``: it inserts its
per-Constituency selection between ``V2Pool`` and ``_finish_v2``, extends
``_finish_v2`` with its rows in the same commit, and flips
``publishing.PUBLISH_ON_PASS[v2]``.

Commits, as ``runs.execute_run``: ``running`` (with the Source Documents it
reads) before any LLM call; each call as it returns (``CheckpointProvider``,
so ``--resume-from`` / ``--reuse-from`` replay recorded calls); then either
``validating`` with the complete ``candidate`` Dataset Version (Statements,
source Proposals, one Position per Party x Statement with its Evidence
Proposals, the pool report) in one commit, or ``failed`` with a reason. v2
runs never resolve Anchors (``anchor_dataset_version_id`` stays NULL, S8).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app import config
from ideology_app.config import GenerationMode, ValidationSettings
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError
from ideology_app.llm.base import LLMError, LLMProvider
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    Election,
    ModelGeneration,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunSourceDocument,
    PipelineRunStatus,
    SourceDocumentRole,
    Statement,
    StatementProposal,
    _utcnow,
)
from ideology_app.pipeline.checkpoint import CheckpointProvider
from ideology_app.pipeline.generation import GenerationError, Usage
from ideology_app.pipeline.runs import (
    INTERRUPTED_REASON,
    RunOutcome,
    _check_resumable,
    validate_run,
)
from ideology_app.pipeline.v2.gate import Phase4Error, Phase4Input, Phase4Party, load_phase4
from ideology_app.pipeline.v2.pool import (
    PoolDraft,
    build_pool,
    filter_pool,
    plan_draft_calls,
)
from ideology_app.pipeline.v2.positions import (
    V2Position,
    assign_positions,
    plan_position_calls,
)
from ideology_app.pipeline.v2.prompts import V2_PROMPT_VERSIONS

MAX_V2_CALLS_PER_RUN = 800
REPORT_VERSION = "v2-pool-1"
BLOCKED_PREFIX = "phase 4 blocked: "
NO_PROPOSALS_REASON = "no counted proposals: every Party is Excluded or has none"
NO_STATEMENTS_REASON = "no statement was drafted from the counted proposals"
_REASON_MAX = 500


@dataclass(frozen=True)
class V2Pool:
    """What a v2 run writes: the filtered pool, every Party's Positions and the report.

    ``positions`` maps each non-Excluded Party id to one ``V2Position`` per
    Statement, in ``statements`` order.
    """

    statements: tuple[PoolDraft, ...]
    positions: dict[int, list[V2Position]]
    report: dict[str, Any]


def queue_v2_run(
    session: Session,
    election_id: int,
    *,
    llm_provider: str,
    llm_model: str,
    generation_mode: GenerationMode,
    resumed_from_run_id: int | None = None,
    allow_finished_source: bool = False,
) -> PipelineRun:
    """Record a ``queued`` v2 run (``model_generation`` v2). The caller commits.

    The phase-4 gate (``load_phase4``) is checked by the caller before and by
    ``execute_v2_run`` again. A source run (``--resume-from`` / ``--reuse-from``)
    must be a v2 run of the same Election, provider and model.
    """
    if session.get(Election, election_id) is None:
        raise NotFoundError(f"election {election_id} not found")
    if resumed_from_run_id is not None:
        _check_resumable(
            session,
            resumed_from_run_id,
            election_id,
            llm_provider,
            llm_model,
            allow_finished_source=allow_finished_source,
            generation=ModelGeneration.V2,
        )
    run = PipelineRun(
        election_id=election_id,
        status=PipelineRunStatus.QUEUED,
        llm_provider=llm_provider,
        llm_model=llm_model,
        generation_mode=generation_mode,
        prompt_versions=dict(V2_PROMPT_VERSIONS),
        llm_calls=0,
        input_tokens=0,
        output_tokens=0,
        resumed_from_run_id=resumed_from_run_id,
        model_generation=ModelGeneration.V2,
    )
    session.add(run)
    session.flush()
    return run


@dataclass(frozen=True)
class _Started:
    phase4: Phase4Input
    resumed_from_run_id: int | None


def _start_v2(
    engine: Engine, run_id: int, provider: LLMProvider, bundle_dir: Path
) -> _Started | RunOutcome:
    """Check the run, re-check the gate, record its documents and mark it ``running``. Commits.

    Raises NotFoundError / InvalidInputError (nothing changes) for an unknown
    run, one that is not ``queued`` or not v2, another provider or model, or a
    bundle of another Election. When the gate refuses, the run is set
    ``failed`` (``phase 4 blocked: ...``) and that outcome is returned.
    """
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError(f"pipeline run {run_id} not found")
        if run.status is not PipelineRunStatus.QUEUED:
            raise InvalidInputError(f"pipeline run {run_id} is {run.status.value}, expected queued")
        if run.model_generation is not ModelGeneration.V2:
            raise InvalidInputError(f"pipeline run {run_id} is a legacy run, not v2")
        if (provider.name, provider.model) != (run.llm_provider, run.llm_model):
            raise InvalidInputError(
                f"pipeline run {run_id} was queued for {run.llm_provider}/{run.llm_model}, "
                f"not {provider.name}/{provider.model}"
            )
        try:
            phase4 = load_phase4(session, bundle_dir)
        except Phase4Error as exc:
            reason = BLOCKED_PREFIX + ("; ".join(exc.blockers) or str(exc))
            run.status = PipelineRunStatus.FAILED
            run.failure_reason = reason[:_REASON_MAX]
            return RunOutcome(
                run_id, run.status, None, 0, run.failure_reason,
                model_generation=ModelGeneration.V2,
            )
        if phase4.election_id != run.election_id:
            raise InvalidInputError(
                f"bundle {phase4.slug} is election {phase4.election_id}; "
                f"pipeline run {run_id} belongs to election {run.election_id}"
            )
        for party in phase4.parties:
            for position, document_id in enumerate(party.document_ids):
                session.add(
                    PipelineRunSourceDocument(
                        pipeline_run_id=run.id,
                        source_document_id=document_id,
                        role=SourceDocumentRole.MAIN if position == 0 else SourceDocumentRole.ADDITIONAL,
                    )
                )
        run.anchor_dataset_version_id = None
        run.status = PipelineRunStatus.RUNNING
        run.started_at = _utcnow()
        return _Started(phase4, run.resumed_from_run_id)


def _record_failure(engine: Engine, run_id: int, usage: Usage, reason: str) -> RunOutcome:
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.llm_calls = usage.calls
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.generation_finished_at = _utcnow()
        run.status = PipelineRunStatus.FAILED
        run.failure_reason = reason[:_REASON_MAX]
        return RunOutcome(
            run_id, run.status, None, 0, run.failure_reason, model_generation=ModelGeneration.V2
        )


def _finish_v2(engine: Engine, run_id: int, usage: Usage, pool: V2Pool) -> RunOutcome:
    """Write the complete ``candidate`` v2 Dataset Version in one commit (insert-only).

    The version (``model_generation`` v2, ``questionnaire_lengths`` NULL), the
    Statements in pool order (category in ``topic``), their source Proposals
    in citation order, one Position per Party x Statement with rank 1 of its
    Evidence mirrored into the ``evidence_*`` columns (the Proposal text
    exactly, its page, its Source Document and that document's URL), the
    Evidence rows, and the run's ``statement_selection`` (the v2 pool report).
    """
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.llm_calls = usage.calls
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.generation_finished_at = _utcnow()
        run.statement_selection = pool.report
        version = DatasetVersion(
            election_id=run.election_id,
            pipeline_run_id=run.id,
            status=DatasetVersionStatus.CANDIDATE,
            questionnaire_lengths=None,
            model_generation=run.model_generation,
        )
        session.add(version)
        session.flush()
        rows = [
            Statement(
                dataset_version_id=version.id,
                position=position,
                text=draft.text,
                topic=draft.category,
                context_note=draft.context_note,
            )
            for position, draft in enumerate(pool.statements, start=1)
        ]
        session.add_all(rows)
        session.flush()
        for row, draft in zip(rows, pool.statements, strict=True):
            session.add_all(
                StatementProposal(statement_id=row.id, rank=rank, proposal_id=proposal_id)
                for rank, proposal_id in enumerate(draft.sources, start=1)
            )
        count = 0
        for party_id in sorted(pool.positions):
            for row, position in zip(rows, pool.positions[party_id], strict=True):
                first = position.evidence[0] if position.evidence else None
                party_position = PartyPosition(
                    statement_id=row.id,
                    party_id=party_id,
                    value=position.value,
                    evidence_source_document_id=None if first is None else first.source_document_id,
                    evidence_quote=None if first is None else first.text,
                    evidence_page=None if first is None else first.page,
                    evidence_url=None if first is None else first.source_url,
                )
                session.add(party_position)
                session.flush()
                session.add_all(
                    PartyPositionProposal(
                        party_position_id=party_position.id,
                        rank=rank,
                        proposal_id=ref.proposal_id,
                        source_document_id=ref.source_document_id,
                        constituencies=list(ref.constituencies),
                    )
                    for rank, ref in enumerate(position.evidence, start=1)
                )
                count += 1
        run.status = PipelineRunStatus.VALIDATING
        session.flush()
        return RunOutcome(
            run_id, run.status, version.id, len(rows), None, count,
            model_generation=ModelGeneration.V2,
        )


def _partial_scope(party: Phase4Party) -> bool:
    """True when the Party's counted Proposals differ between its Constituencies (S5)."""
    codes = [set(p.constituencies) for p in party.proposals]
    union = set().union(*codes) if codes else set()
    return any(c != union for c in codes)


def plan_calls(phase4: Phase4Input) -> int:
    """The most LLM calls a v2 run of ``phase4`` can make (drafts exact, positions bound)."""
    return plan_draft_calls(phase4.parties) + plan_position_calls(phase4.parties)


def execute_v2_run(
    engine: Engine,
    run_id: int,
    provider: LLMProvider,
    bundle_dir: Path,
    validation_settings: ValidationSettings | None = None,
) -> RunOutcome:
    """Draft the pool, position every Party, write the Dataset Version, validate it.

    See the module docstring. ``validation_settings`` (``None``: read first
    with ``config.validation_settings()``) gives the filter's Context Note
    rules, the prompt's note bounds and the Validation thresholds. Planned calls
    above ``MAX_V2_CALLS_PER_RUN`` fail the run before any call. ``LLMError`` /
    ``GenerationError`` give ``failed`` with the reason; Ctrl-C records
    ``interrupted`` and re-raises; any other error records
    ``unexpected error: <ClassName>`` and re-raises.
    """
    if validation_settings is None:
        validation_settings = config.validation_settings()
    started = _start_v2(engine, run_id, provider, Path(bundle_dir))
    if isinstance(started, RunOutcome):
        return started
    phase4 = started.phase4
    provider = CheckpointProvider(provider, engine, run_id, started.resumed_from_run_id)
    usage = Usage()
    try:
        planned = plan_calls(phase4)
        if planned > MAX_V2_CALLS_PER_RUN:
            raise GenerationError(
                f"too many v2 calls planned: {planned} (limit {MAX_V2_CALLS_PER_RUN})"
            )
        if not any(party.proposals for party in phase4.parties):
            raise GenerationError(NO_PROPOSALS_REASON)
        drafted = build_pool(provider, phase4.parties, usage, validation_settings)
        kept = filter_pool(drafted.statements, validation_settings)
        if not kept.statements:
            raise GenerationError(NO_STATEMENTS_REASON)
        assigned = assign_positions(provider, kept.statements, phase4.parties, usage)
        pool = V2Pool(
            statements=kept.statements,
            positions=assigned.positions,
            report={
                "version": REPORT_VERSION,
                "bundle": phase4.slug,
                "parties": [
                    {
                        "party_id": party.party_id,
                        "proposals": len(party.proposals),
                        "partial_scope": _partial_scope(party),
                    }
                    for party in phase4.parties
                ],
                "partial_scope_parties": [
                    party.party_id for party in phase4.parties if _partial_scope(party)
                ],
                "proposals": drafted.proposals,
                "categories": list(drafted.categories),
                "filtered": list(kept.filtered),
                "pool_size": len(kept.statements),
                "positions": assigned.report,
            },
        )
        outcome = _finish_v2(engine, run_id, usage, pool)
    except (LLMError, GenerationError) as exc:
        return _record_failure(engine, run_id, usage, str(exc))
    except KeyboardInterrupt:
        _record_failure(engine, run_id, usage, INTERRUPTED_REASON)
        raise
    except Exception as exc:
        _record_failure(engine, run_id, usage, f"unexpected error: {type(exc).__name__}")
        raise
    return validate_run(engine, run_id, settings=validation_settings)


def pool_summary(report: dict[str, Any] | None) -> str | None:
    """The one ``pipeline report`` line of a v2 run, or ``None`` without a report."""
    if report is None or report.get("version") != REPORT_VERSION:
        return None
    return (
        f"v2 pool {report['pool_size']} statements from {report['proposals']} proposals "
        f"({len(report['filtered'])} filtered), {report['positions']['calls']} position calls"
    )


__all__ = [
    "BLOCKED_PREFIX",
    "MAX_V2_CALLS_PER_RUN",
    "NO_PROPOSALS_REASON",
    "NO_STATEMENTS_REASON",
    "REPORT_VERSION",
    "V2Pool",
    "execute_v2_run",
    "plan_calls",
    "pool_summary",
    "queue_v2_run",
]
