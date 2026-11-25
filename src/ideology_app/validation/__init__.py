"""Validation: pure checks over a Pipeline Run's candidate Dataset Version.

Depends on ``models`` and ``config`` (for ``ValidationSettings``) only; never
imports ``pipeline``, ``llm`` or ``pdf_text``. To add a check, write
``validation/<name>.py`` exporting a ``Check`` and append it to ``CHECKS``
(registry order is run order; current checks: evidence quotes, party coverage
(by side, per offered questionnaire length),
statement separation (a Party on each side), statement uniqueness, statement
count (and stored lengths), topic spread (per offered length),
context note; v2 runs use ``V2_CHECKS``: evidence quotes, evidence
proposals, statement sources, uniqueness, context note, then the four
per-Constituency checks: snapshot, validity, availability, order, and
``statement_rewording``); a
threshold it needs is a ``ValidationSettings`` field read from the environment
in ``config``. ``pipeline.runs.validate_run`` stores the results.
"""

from collections.abc import Sequence

from ideology_app.config import ValidationSettings
from ideology_app.models import ModelGeneration

from ideology_app.validation.base import (
    CHECK_NAME_MAX,
    MESSAGE_MAX,
    Check,
    CheckResult,
    ConstituencyRowData,
    EvidenceRow,
    PositionRow,
    ProposalRow,
    ReportEntry,
    RunDocument,
    SnapshotRow,
    StatementRow,
    ValidationInput,
    load_input,
    offered_lengths,
)
from ideology_app.validation.constituencies import (
    CONSTITUENCY_AVAILABILITY,
    CONSTITUENCY_ORDER,
    CONSTITUENCY_SNAPSHOT,
    CONSTITUENCY_VALIDITY,
)
from ideology_app.validation.context_note import CONTEXT_NOTE
from ideology_app.validation.evidence_quotes import (
    EVIDENCE_QUOTES,
    QuoteMiss,
    find_quote_miss,
    normalize_for_match,
    normalize_pages,
    quote_starts_on,
)
from ideology_app.validation.evidence_proposals import EVIDENCE_PROPOSALS
from ideology_app.validation.party_coverage import PARTY_COVERAGE
from ideology_app.validation.statement_count import STATEMENT_COUNT
from ideology_app.validation.statement_rewording import STATEMENT_REWORDING
from ideology_app.validation.statement_separation import STATEMENT_SEPARATION
from ideology_app.validation.statement_sources import STATEMENT_SOURCES
from ideology_app.validation.statement_uniqueness import STATEMENT_UNIQUENESS
from ideology_app.validation.topic_spread import TOPIC_SPREAD

# Registry order is run order. Checks are appended as they are added, so
# existing result rows and ``failure_reason`` strings stay stable.
CHECKS: tuple[Check, ...] = (
    EVIDENCE_QUOTES,
    PARTY_COVERAGE,
    STATEMENT_SEPARATION,
    STATEMENT_UNIQUENESS,
    STATEMENT_COUNT,
    TOPIC_SPREAD,
    CONTEXT_NOTE,
)

# v2 runs (statements-from-proposals): checks 1 (uniqueness), 2 (quotes on the
# mirrored rank-1 columns and every Evidence Proposal), Statement sources and 7;
# then (constituency-selection-validation) the per-Constituency checks that
# replace coverage, separation, count and topic spread (3-6); then
# (statement-rewording) the Statement Rewording check.
V2_CHECKS: tuple[Check, ...] = (
    EVIDENCE_QUOTES,
    EVIDENCE_PROPOSALS,
    STATEMENT_SOURCES,
    STATEMENT_UNIQUENESS,
    CONTEXT_NOTE,
    CONSTITUENCY_SNAPSHOT,
    CONSTITUENCY_VALIDITY,
    CONSTITUENCY_AVAILABILITY,
    CONSTITUENCY_ORDER,
    STATEMENT_REWORDING,
)


def checks_for(generation: ModelGeneration) -> tuple[Check, ...]:
    """The checks of a run of ``generation``: ``CHECKS`` (legacy) or ``V2_CHECKS``."""
    return V2_CHECKS if generation is ModelGeneration.V2 else CHECKS


def run_checks(data: ValidationInput, checks: Sequence[Check] = CHECKS) -> list[CheckResult]:
    """Run every check in order (no short-circuit) and return their results."""
    return [CheckResult(check.name, tuple(check.run(data))) for check in checks]


__all__ = [
    "CHECKS",
    "CHECK_NAME_MAX",
    "CONSTITUENCY_AVAILABILITY",
    "CONSTITUENCY_ORDER",
    "CONSTITUENCY_SNAPSHOT",
    "CONSTITUENCY_VALIDITY",
    "CONTEXT_NOTE",
    "EVIDENCE_PROPOSALS",
    "EVIDENCE_QUOTES",
    "MESSAGE_MAX",
    "PARTY_COVERAGE",
    "STATEMENT_COUNT",
    "STATEMENT_REWORDING",
    "STATEMENT_SEPARATION",
    "STATEMENT_SOURCES",
    "STATEMENT_UNIQUENESS",
    "TOPIC_SPREAD",
    "V2_CHECKS",
    "Check",
    "CheckResult",
    "ConstituencyRowData",
    "EvidenceRow",
    "PositionRow",
    "ProposalRow",
    "QuoteMiss",
    "ReportEntry",
    "RunDocument",
    "SnapshotRow",
    "StatementRow",
    "ValidationInput",
    "ValidationSettings",
    "checks_for",
    "find_quote_miss",
    "load_input",
    "normalize_for_match",
    "normalize_pages",
    "offered_lengths",
    "quote_starts_on",
    "run_checks",
]
