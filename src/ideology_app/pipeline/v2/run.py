"""The v2 Pipeline Run: queue, execute, write the Dataset Version, validate.

``execute_v2_run`` runs ``build_pool`` -> ``filter_pool`` ->
``assign_positions`` -> ``apply_rewordings`` (only with a
``statement-rewordings.toml``) -> ``V2Pool`` -> ``select_constituencies`` ->
``_finish_v2`` -> ``validate_run``. Rewordings apply after positioning, so
Positions and Evidence are computed on the AI text and a ``--reuse-from``
replay reuses every draft and position call (``statement-rewording``, R3). Constituency Selection
(constituency-selection-validation) is deterministic and AI-free; its rows
are written by ``_finish_v2`` in the Dataset Version's commit, and a passed
v2 run is published (``publishing.PUBLISH_ON_PASS[v2]``).

Commits, as ``runs.execute_run``: ``running`` (with the Source Documents it
reads) before any LLM call; each call as it returns (``CheckpointProvider``,
so ``--resume-from`` / ``--reuse-from`` replay recorded calls); then either
``validating`` with the complete ``candidate`` Dataset Version (Statements,
source Proposals, one Position per Party x Statement with its Evidence
Proposals, the 52 Constituency rows, the candidature snapshot, each available
Constituency's ordered Statements, the applied Statement Rewordings, the pool
report) in one commit, or ``failed`` with a reason. v2
runs never resolve Anchors (``anchor_dataset_version_id`` stays NULL, S8).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app import config
from ideology_app.config import ConstituencySettings, GenerationMode, ValidationSettings
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError
from ideology_app.llm.base import LLMError, LLMProvider
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
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
    StatementRewording,
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
from ideology_app.pipeline.v2.rewording import (
    AppliedRewording,
    RewordingFile,
    RewordingFileError,
    apply_rewordings,
    read_rewordings,
)
from ideology_app.pipeline.v2.selection import ConstituencySelection, select_constituencies

MAX_V2_CALLS_PER_RUN = 800
REPORT_VERSION = "v2-pool-1"
BLOCKED_PREFIX = "phase 4 blocked: "
NO_PROPOSALS_REASON = "no counted proposals: every Party is Excluded or has none"
NO_STATEMENTS_REASON = "no statement was drafted from the counted proposals"
REWORDING_INVALID_PREFIX = "rewording file invalid: "
_REASON_MAX = 500


@dataclass(frozen=True)
class V2Pool:
    """What a v2 run writes: the filtered pool, every Party's Positions and the report.

    ``positions`` maps each non-Excluded Party id to one ``V2Position`` per
    Statement, in ``statements`` order. ``statements`` keep the AI text;
    ``rewordings`` maps a 0-based pool index to its applied Statement
    Rewording, whose text ``_finish_v2`` stores instead.
    """

    statements: tuple[PoolDraft, ...]
    positions: dict[int, list[V2Position]]
    report: dict[str, Any]
    rewordings: Mapping[int, AppliedRewording] = field(default_factory=dict)


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
    rewordings: RewordingFile | None = None


def _start_v2(
    engine: Engine, run_id: int, provider: LLMProvider, bundle_dir: Path
) -> _Started | RunOutcome:
    """Check the run, re-check the gate, record its documents and mark it ``running``. Commits.

    Raises NotFoundError / InvalidInputError (nothing changes) for an unknown
    run, one that is not ``queued`` or not v2, another provider or model, or a
    bundle of another Election. When the gate refuses, the run is set
    ``failed`` (``phase 4 blocked: ...``) and that outcome is returned; an
    invalid ``statement-rewordings.toml`` sets it ``failed`` with
    ``rewording file invalid: ...``.
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
        try:
            rewordings = read_rewordings(bundle_dir)
        except RewordingFileError as exc:
            run.status = PipelineRunStatus.FAILED
            run.failure_reason = (REWORDING_INVALID_PREFIX + str(exc))[:_REASON_MAX]
            return RunOutcome(
                run_id, run.status, None, 0, run.failure_reason,
                model_generation=ModelGeneration.V2,
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
        return _Started(phase4, run.resumed_from_run_id, rewordings)


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


def _finish_v2(
    engine: Engine,
    run_id: int,
    usage: Usage,
    pool: V2Pool,
    selection: ConstituencySelection,
) -> RunOutcome:
    """Write the complete ``candidate`` v2 Dataset Version in one commit (insert-only).

    The version (``model_generation`` v2, ``questionnaire_lengths`` NULL), the
    Statements in pool order (category in ``topic``), their source Proposals
    in citation order, one Position per Party x Statement with rank 1 of its
    Evidence mirrored into the ``evidence_*`` columns (the Proposal text
    exactly, its page, its Source Document and that document's URL), the
    Evidence rows, the Constituency Selection (52 Constituency rows, the
    candidature snapshot, the ranked Statements of each available
    Constituency), one ``statement_rewordings`` row per applied Statement
    Rewording (``statements.text`` is then the Operator's text and the row
    keeps the AI text) and the run's ``statement_selection`` (the v2 pool
    report with the selection report under ``"constituencies"``).
    """
    with session_scope(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.llm_calls = usage.calls
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.generation_finished_at = _utcnow()
        run.statement_selection = {**pool.report, "constituencies": selection.report}
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
                position=index + 1,
                text=pool.rewordings[index].text if index in pool.rewordings else draft.text,
                topic=draft.category,
                context_note=draft.context_note,
            )
            for index, draft in enumerate(pool.statements)
        ]
        session.add_all(rows)
        session.flush()
        session.add_all(
            StatementRewording(
                statement_id=rows[index].id,
                ai_text=pool.statements[index].text,
                reason=applied.reason,
                explanation=applied.explanation,
            )
            for index, applied in sorted(pool.rewordings.items())
        )
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
        session.add_all(
            DatasetVersionConstituency(
                dataset_version_id=version.id,
                constituency_code=row.code,
                available=row.available,
                unavailable_reason=row.unavailable_reason,
                valid_statement_count=row.valid_statement_count,
                offered_lengths=list(row.offered_lengths),
                detail=row.detail,
            )
            for row in selection.rows
        )
        session.add_all(
            DatasetVersionCandidature(
                dataset_version_id=version.id,
                party_id=item.party_id,
                constituency_code=item.code,
                excluded_reason=item.excluded_reason,
            )
            for item in selection.snapshot
        )
        session.add_all(
            ConstituencyStatement(
                dataset_version_id=version.id,
                constituency_code=code,
                rank=rank,
                statement_id=rows[number - 1].id,
            )
            for code, numbers in selection.statements_by_code.items()
            for rank, number in enumerate(numbers, start=1)
        )
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


def plan_calls(phase4: Phase4Input, rewordings: int = 0) -> int:
    """The most LLM calls a v2 run of ``phase4`` can make (drafts exact, positions bound),
    plus one equivalence call per rewording entry (``rewordings``, a bound)."""
    return plan_draft_calls(phase4.parties) + plan_position_calls(phase4.parties) + rewordings


def execute_v2_run(
    engine: Engine,
    run_id: int,
    provider: LLMProvider,
    bundle_dir: Path,
    validation_settings: ValidationSettings | None = None,
    constituency_settings: ConstituencySettings | None = None,
) -> RunOutcome:
    """Draft the pool, position every Party, select per Constituency, write, validate.

    See the module docstring. ``validation_settings`` (``None``: read first
    with ``config.validation_settings()``) gives the filter's Context Note
    rules, the prompt's note bounds, the topic share of the Constituency order
    and the Validation thresholds; ``constituency_settings`` (``None``: read
    first with ``config.constituency_settings()``) the per-Constituency minimums. Planned calls
    above ``MAX_V2_CALLS_PER_RUN`` fail the run before any call. ``LLMError`` /
    ``GenerationError`` give ``failed`` with the reason; Ctrl-C records
    ``interrupted`` and re-raises; any other error records
    ``unexpected error: <ClassName>`` and re-raises.
    """
    if validation_settings is None:
        validation_settings = config.validation_settings()
    if constituency_settings is None:
        constituency_settings = config.constituency_settings()
    started = _start_v2(engine, run_id, provider, Path(bundle_dir))
    if isinstance(started, RunOutcome):
        return started
    phase4 = started.phase4
    provider = CheckpointProvider(provider, engine, run_id, started.resumed_from_run_id)
    usage = Usage()
    try:
        rewording_file = started.rewordings
        planned = plan_calls(
            phase4, 0 if rewording_file is None else len(rewording_file.entries)
        )
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
        reworded = (
            None
            if rewording_file is None
            else apply_rewordings(provider, kept.statements, rewording_file, usage)
        )
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
                **({} if reworded is None else {"rewordings": reworded.report}),
            },
            rewordings={} if reworded is None else reworded.applied,
        )
        selection = select_constituencies(
            pool.statements,
            pool.positions,
            phase4,
            validation_settings.max_topic_share_percent,
            constituency_settings,
        )
        _finish_v2(engine, run_id, usage, pool, selection)
    except (LLMError, GenerationError) as exc:
        return _record_failure(engine, run_id, usage, str(exc))
    except KeyboardInterrupt:
        _record_failure(engine, run_id, usage, INTERRUPTED_REASON)
        raise
    except Exception as exc:
        _record_failure(engine, run_id, usage, f"unexpected error: {type(exc).__name__}")
        raise
    return validate_run(
        engine,
        run_id,
        settings=validation_settings,
        constituency_settings=constituency_settings,
    )


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
    "REWORDING_INVALID_PREFIX",
    "V2Pool",
    "execute_v2_run",
    "plan_calls",
    "pool_summary",
    "queue_v2_run",
]
