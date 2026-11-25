"""Phase 4 of a format-2 Election (statements-from-proposals): the v2 Pipeline Run.

Statements are drafted from groups of similar counted Proposals and every
non-Excluded Party is positioned with its own Proposals as Evidence; then
Constituency Selection (constituency-selection-validation, ``selection``)
decides each Constituency's Questionnaire with ``constituency_rules``.
Statement Rewordings from ``statement-rewordings.toml`` (``rewording``,
statement-rewording) are judged after positioning and stored with the new
Dataset Version. ``inspection`` (v2-run-inspection) holds the read-only views
the Operator CLI prints for a stored v2 version. Depends
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
from ideology_app.pipeline.v2.inspection import (
    ConstituencyTableRow,
    EvidenceRow,
    PartyRow,
    PartySides,
    SourceRow,
    constituency_rows,
    excerpt,
    party_rows,
    position_evidence,
    recorded_constituency_settings,
    source_no_stance,
    statement_sources,
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
    STATEMENT_REWORDING_CHECK,
    V2_PROMPT_VERSIONS,
    V2_PROMPTS,
    RewordingVerdict,
    draft_request,
    draft_set_schema,
    position_request,
    position_set_schema,
    rewording_request,
)
from ideology_app.pipeline.v2.rewording import (
    MAX_REWORDINGS,
    REWORDINGS_NAME,
    AppliedRewording,
    RewordingEntry,
    RewordingFile,
    RewordingFileError,
    RewordingOutcome,
    apply_rewordings,
    read_rewordings,
    rewording_summary,
)
from ideology_app.pipeline.v2.run import (
    MAX_V2_CALLS_PER_RUN,
    REPORT_VERSION,
    REWORDING_INVALID_PREFIX,
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
    "MAX_REWORDINGS",
    "MAX_V2_CALLS_PER_RUN",
    "POOL_TARGET",
    "POSITION_SLICE_MAX_CHARS",
    "PROPOSAL_POSITIONS",
    "REPORT_VERSION",
    "REWORDINGS_NAME",
    "REWORDING_INVALID_PREFIX",
    "SELECTION_VERSION",
    "STATEMENT_DRAFTS",
    "STATEMENT_REWORDING_CHECK",
    "V2_PROMPTS",
    "V2_PROMPT_VERSIONS",
    "AppliedRewording",
    "CandidatureRow",
    "ConstituencyRow",
    "ConstituencySelection",
    "ConstituencyTableRow",
    "DraftPool",
    "EvidenceRef",
    "EvidenceRow",
    "ExcludedParty",
    "FilteredPool",
    "PartyRow",
    "PartySides",
    "Phase4Error",
    "Phase4Input",
    "Phase4Party",
    "PhaseProposal",
    "PoolDraft",
    "RewordingEntry",
    "RewordingFile",
    "RewordingFileError",
    "RewordingOutcome",
    "RewordingVerdict",
    "SourceRow",
    "V2Pool",
    "V2Position",
    "apply_rewordings",
    "assign_positions",
    "build_pool",
    "constituency_rows",
    "constituency_summary",
    "dataset_version_problems",
    "draft_buckets",
    "draft_request",
    "draft_set_schema",
    "draft_slices",
    "excerpt",
    "execute_v2_run",
    "filter_pool",
    "load_phase4",
    "party_rows",
    "plan_calls",
    "plan_position_calls",
    "pool_summary",
    "position_evidence",
    "position_request",
    "position_set_schema",
    "queue_v2_run",
    "read_rewordings",
    "recorded_constituency_settings",
    "rewording_request",
    "rewording_summary",
    "select_constituencies",
    "source_no_stance",
    "statement_sources",
]
