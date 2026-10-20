"""What a Generation Mode does when a Source Document changes.

``QUEUE_ON_SOURCE_CHANGE`` is the only place in the code that gives a
Generation Mode a behaviour: in ``live`` a new ``parsed`` Source Document
queues a Pipeline Run for its Election; in ``precomputed`` nothing happens.

The trigger only records a ``queued`` run, in the caller's transaction (so the
document and its run commit together). It never calls an LLM, builds a
provider or reads an API key; queued runs are executed by the Operator
(``ideology pipeline run-queued``). At most one ``queued`` run exists per
Election: a later document joins the run that is already queued, which loads
every ``parsed`` document when it starts. Runs already ``running`` or
``validating`` loaded their input earlier, so they never suppress queuing.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode, LLMSettings
from ideology_app.models import (
    Party,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentStatus,
)
from ideology_app.pipeline import publishing
from ideology_app.pipeline.runs import queue_run

QUEUE_ON_SOURCE_CHANGE: dict[GenerationMode, bool] = {
    GenerationMode.PRECOMPUTED: False,
    GenerationMode.LIVE: True,
}


def queues_on_source_change(mode: GenerationMode) -> bool:
    """Whether a new parsed Source Document queues a Pipeline Run in ``mode``."""
    return QUEUE_ON_SOURCE_CHANGE[mode]


@dataclass(frozen=True)
class SourceChangeOutcome:
    """What the trigger did (plain data, safe after the session).

    ``run_id`` is the ``queued`` run that will read the document (``None`` when
    nothing was queued); ``newly_queued`` is ``False`` when that run already
    existed.
    """

    election_id: int
    run_id: int | None
    newly_queued: bool


def queue_run_for_source_change(
    session: Session,
    document: SourceDocument,
    *,
    generation_mode: GenerationMode,
    llm: LLMSettings | None,
) -> SourceChangeOutcome:
    """Queue (or join) a Pipeline Run for ``document``'s Election. Never commits.

    Writes nothing when ``generation_mode`` does not queue or the document is
    not ``parsed``. Otherwise locks the Election row, returns the lowest-id
    ``queued`` run of the Election if there is one, else queues a new run with
    ``llm``'s provider and model. Raises ValueError when the mode queues and
    ``llm`` is ``None``.
    """
    election_id = session.scalars(
        select(Party.election_id).where(Party.id == document.party_id)
    ).one()
    if not queues_on_source_change(generation_mode):
        return SourceChangeOutcome(election_id, None, False)
    if llm is None:
        raise ValueError(f"generation mode {generation_mode.value} needs LLM settings")
    if document.status is not SourceDocumentStatus.PARSED:
        return SourceChangeOutcome(election_id, None, False)
    session.scalars(publishing.election_lock_statement(election_id)).one()
    existing = session.scalar(
        select(PipelineRun.id)
        .where(
            PipelineRun.election_id == election_id,
            PipelineRun.status == PipelineRunStatus.QUEUED,
        )
        .order_by(PipelineRun.id)
        .limit(1)
    )
    if existing is not None:
        return SourceChangeOutcome(election_id, existing, False)
    run = queue_run(
        session,
        election_id,
        llm_provider=llm.provider,
        llm_model=llm.model,
        generation_mode=generation_mode,
    )
    return SourceChangeOutcome(election_id, run.id, True)
