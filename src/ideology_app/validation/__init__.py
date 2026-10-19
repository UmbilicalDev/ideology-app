"""Validation: pure checks over a Pipeline Run's candidate Dataset Version.

Depends on ``models`` and ``config`` (for ``ValidationSettings``) only; never
imports ``pipeline``, ``llm`` or ``pdf_text``. To add a check, write
``validation/<name>.py`` exporting a ``Check`` and append it to ``CHECKS``; a
threshold it needs is a ``ValidationSettings`` field read from the environment
in ``config``. ``pipeline.runs.validate_run`` stores the results.
"""

from collections.abc import Sequence

from ideology_app.config import ValidationSettings

from ideology_app.validation.base import (
    CHECK_NAME_MAX,
    MESSAGE_MAX,
    Check,
    CheckResult,
    PositionRow,
    ReportEntry,
    RunDocument,
    StatementRow,
    ValidationInput,
    load_input,
)
from ideology_app.validation.evidence_quotes import (
    EVIDENCE_QUOTES,
    normalize_for_match,
    quote_starts_on,
)
from ideology_app.validation.party_coverage import PARTY_COVERAGE
from ideology_app.validation.statement_separation import STATEMENT_SEPARATION

# Registry order is run order (domain check order: 2 evidence quotes,
# 3 party coverage, 4 statement separation).
CHECKS: tuple[Check, ...] = (EVIDENCE_QUOTES, PARTY_COVERAGE, STATEMENT_SEPARATION)


def run_checks(data: ValidationInput, checks: Sequence[Check] = CHECKS) -> list[CheckResult]:
    """Run every check in order (no short-circuit) and return their results."""
    return [CheckResult(check.name, tuple(check.run(data))) for check in checks]


__all__ = [
    "CHECKS",
    "CHECK_NAME_MAX",
    "EVIDENCE_QUOTES",
    "MESSAGE_MAX",
    "PARTY_COVERAGE",
    "STATEMENT_SEPARATION",
    "Check",
    "CheckResult",
    "PositionRow",
    "ReportEntry",
    "RunDocument",
    "StatementRow",
    "ValidationInput",
    "ValidationSettings",
    "load_input",
    "normalize_for_match",
    "quote_starts_on",
    "run_checks",
]
