"""Phase 4 of a format-2 Election (statements-from-proposals): the v2 Pipeline Run.

Statements are drafted from groups of similar counted Proposals and every
non-Excluded Party is positioned with its own Proposals as Evidence; then
Constituency Selection (constituency-selection-validation, ``selection``)
decides each Constituency's Questionnaire with ``constituency_rules``. Depends
on ``llm.base`` (never a concrete provider), ``models``, ``proposals``
(``counted_proposals``, ``ledger_count_problems``), ``ingestion_ledger``,
``bundle_import``, ``validation`` and ``pipeline`` (checkpoint, usage, runs).
"""

from ideology_app.pipeline.v2.gate import (
    ExcludedParty,
    Phase4Error,
    Phase4Input,
    Phase4Party,
    PhaseProposal,
    load_phase4,
)
from ideology_app.pipeline.v2.pool import (
    DRAFT_SLICE_MAX_CHARS,
    POOL_TARGET,
    DraftPool,
    FilteredPool,
    PoolDraft,
    build_pool,
    draft_buckets,
    draft_slices,
    filter_pool,
)
from ideology_app.pipeline.v2.positions import (
    POSITION_SLICE_MAX_CHARS,
    EvidenceRef,
    V2Position,
    assign_positions,
    plan_position_calls,
)
from ideology_app.pipeline.v2.prompts import (
    PROPOSAL_POSITIONS,
    STATEMENT_DRAFTS,
    V2_PROMPT_VERSIONS,
    V2_PROMPTS,
    draft_request,
    draft_set_schema,
    position_request,
    position_set_schema,
)
from ideology_app.pipeline.v2.run import (
    MAX_V2_CALLS_PER_RUN,
    REPORT_VERSION,
    V2Pool,
    execute_v2_run,
    plan_calls,
    pool_summary,
    queue_v2_run,
)
from ideology_app.pipeline.v2.selection import (
    SELECTION_VERSION,
    CandidatureRow,
    ConstituencyRow,
    ConstituencySelection,
    select_constituencies,
)
from ideology_app.pipeline.v2.stored import constituency_summary, dataset_version_problems

__all__ = [
    "DRAFT_SLICE_MAX_CHARS",
    "MAX_V2_CALLS_PER_RUN",
    "POOL_TARGET",
    "POSITION_SLICE_MAX_CHARS",
    "PROPOSAL_POSITIONS",
    "REPORT_VERSION",
    "SELECTION_VERSION",
    "STATEMENT_DRAFTS",
    "V2_PROMPTS",
    "V2_PROMPT_VERSIONS",
    "CandidatureRow",
    "ConstituencyRow",
    "ConstituencySelection",
    "DraftPool",
    "EvidenceRef",
    "ExcludedParty",
    "FilteredPool",
    "Phase4Error",
    "Phase4Input",
    "Phase4Party",
    "PhaseProposal",
    "PoolDraft",
    "V2Pool",
    "V2Position",
    "assign_positions",
    "build_pool",
    "constituency_summary",
    "dataset_version_problems",
    "draft_buckets",
    "draft_request",
    "draft_set_schema",
    "draft_slices",
    "execute_v2_run",
    "filter_pool",
    "load_phase4",
    "plan_calls",
    "plan_position_calls",
    "pool_summary",
    "position_request",
    "position_set_schema",
    "queue_v2_run",
    "select_constituencies",
]
