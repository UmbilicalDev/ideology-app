"""Pipeline Run report: everything stored about one run, read in one place.

Read-only: this module only runs ``SELECT`` statements and has no write path
for runs, Dataset Versions, Statements, Party Positions or Validation results.
Formatting belongs to the CLI (``ideology pipeline report``).
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode
from ideology_app.elections import NotFoundError
from ideology_app.models import (
    DatasetVersionStatus,
    PipelineRun,
    PipelineRunStatus,
    Statement,
    ValidationResult,
)
from ideology_app.pipeline.publishing import get_published_dataset_version
from ideology_app.pipeline.runs import list_validation_results


@dataclass(frozen=True)
class RunReport:
    """One Pipeline Run's stored fields plus what is derived from them at read time.

    ``validated_at`` is the earliest Validation result's ``created_at`` (``None``
    before Validation). ``dataset_version_*`` and ``statement_count`` are
    ``None`` when the run has no Dataset Version. ``live_*`` name the Election's
    Published Dataset Version (``None`` before its first publish). ``results``
    are the run's Validation results in check order, with their entries; they
    are ORM rows, so read them inside the session that built the report.
    """

    run_id: int
    election_id: int
    status: PipelineRunStatus
    failure_reason: str | None
    llm_provider: str
    llm_model: str
    generation_mode: GenerationMode
    prompt_versions: dict[str, str]
    created_at: dt.datetime
    started_at: dt.datetime | None
    generation_finished_at: dt.datetime | None
    validated_at: dt.datetime | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    validation_settings: dict[str, int] | None
    dataset_version_id: int | None
    dataset_version_status: DatasetVersionStatus | None
    statement_count: int | None
    live_dataset_version_id: int | None
    live_run_id: int | None
    results: Sequence[ValidationResult]


def get_run_report(session: Session, run_id: int) -> RunReport:
    """Read one Pipeline Run's report. Raises NotFoundError for an unknown run."""
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise NotFoundError(f"pipeline run {run_id} not found")
    validated_at = session.scalar(
        select(func.min(ValidationResult.created_at)).where(
            ValidationResult.pipeline_run_id == run.id
        )
    )
    version = run.dataset_version
    statement_count = (
        None
        if version is None
        else session.scalar(
            select(func.count())
            .select_from(Statement)
            .where(Statement.dataset_version_id == version.id)
        )
    )
    live = get_published_dataset_version(session, run.election_id)
    return RunReport(
        run_id=run.id,
        election_id=run.election_id,
        status=run.status,
        failure_reason=run.failure_reason,
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        generation_mode=run.generation_mode,
        prompt_versions=dict(run.prompt_versions),
        created_at=run.created_at,
        started_at=run.started_at,
        generation_finished_at=run.generation_finished_at,
        validated_at=validated_at,
        llm_calls=run.llm_calls,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        validation_settings=(
            None if run.validation_settings is None else dict(run.validation_settings)
        ),
        dataset_version_id=None if version is None else version.id,
        dataset_version_status=None if version is None else version.status,
        statement_count=statement_count,
        live_dataset_version_id=None if live is None else live.id,
        live_run_id=None if live is None else live.pipeline_run_id,
        results=list_validation_results(session, run.id),
    )
