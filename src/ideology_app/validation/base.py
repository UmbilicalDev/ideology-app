"""Validation data: what a check reads (``ValidationInput``) and what it returns.

Checks are pure functions of ``ValidationInput``: no database, LLM, network or
clock. ``load_input`` is the only place that reads the database for them.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ideology_app.models import (
    Party,
    PartyPosition,
    PipelineRun,
    PipelineRunSourceDocument,
    SourceDocument,
    SourceDocumentRole,
    Statement,
)

MESSAGE_MAX = 500
CHECK_NAME_MAX = 50


@dataclass(frozen=True)
class StatementRow:
    id: int
    position: int
    text: str
    topic: str


@dataclass(frozen=True)
class PositionRow:
    """A Party Position with its Evidence; ``value`` None means ``no stance``."""

    statement_id: int
    statement_position: int
    party_id: int
    value: int | None
    document_id: int | None
    quote: str | None
    page: int | None
    url: str | None


@dataclass(frozen=True)
class RunDocument:
    """A Source Document the run read, with its page texts as stored (by page number)."""

    party_id: int
    role: SourceDocumentRole
    source_url: str | None
    pages: Mapping[int, str]


@dataclass(frozen=True)
class ValidationInput:
    """Everything the checks may read about one run, as plain data.

    ``statements`` are in position order; ``positions`` by Statement position
    then Party id; ``party_ids`` are the Election's Parties in id order;
    ``documents`` maps document id to every Source Document the run read.
    A check that needs more (e.g. a configured threshold) adds a field here and
    fills it in ``load_input``.
    """

    statements: tuple[StatementRow, ...]
    positions: tuple[PositionRow, ...]
    party_ids: tuple[int, ...]
    documents: Mapping[int, RunDocument] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportEntry:
    """One offending item of a check, e.g. a Party Position."""

    message: str
    statement_id: int | None = None
    party_id: int | None = None


@dataclass(frozen=True)
class Check:
    """A named, pure Validation check. ``name`` is a stable slug (≤ 50 chars)."""

    name: str
    run: Callable[[ValidationInput], list[ReportEntry]]

    def __post_init__(self) -> None:
        if not 0 < len(self.name) <= CHECK_NAME_MAX:
            raise ValueError(f"check name must be 1..{CHECK_NAME_MAX} characters")


@dataclass(frozen=True)
class CheckResult:
    name: str
    entries: tuple[ReportEntry, ...]

    @property
    def passed(self) -> bool:
        return not self.entries


def load_input(session: Session, run: PipelineRun) -> ValidationInput:
    """Read the run's Dataset Version and the Source Documents it read.

    The run must have a Dataset Version.
    """
    version = run.dataset_version
    assert version is not None
    statements = session.scalars(
        select(Statement)
        .where(Statement.dataset_version_id == version.id)
        .order_by(Statement.position)
    ).all()
    positions = session.execute(
        select(PartyPosition, Statement.position)
        .join(Statement, PartyPosition.statement_id == Statement.id)
        .where(Statement.dataset_version_id == version.id)
        .order_by(Statement.position, PartyPosition.party_id)
    ).all()
    party_ids = session.scalars(
        select(Party.id).where(Party.election_id == run.election_id).order_by(Party.id)
    ).all()
    run_documents = session.execute(
        select(PipelineRunSourceDocument, SourceDocument)
        .join(SourceDocument, PipelineRunSourceDocument.source_document_id == SourceDocument.id)
        .where(PipelineRunSourceDocument.pipeline_run_id == run.id)
        .options(selectinload(SourceDocument.pages))
        .order_by(SourceDocument.id)
    ).all()
    return ValidationInput(
        statements=tuple(
            StatementRow(id=s.id, position=s.position, text=s.text, topic=s.topic)
            for s in statements
        ),
        positions=tuple(
            PositionRow(
                statement_id=p.statement_id,
                statement_position=position,
                party_id=p.party_id,
                value=p.value,
                document_id=p.evidence_source_document_id,
                quote=p.evidence_quote,
                page=p.evidence_page,
                url=p.evidence_url,
            )
            for p, position in positions
        ),
        party_ids=tuple(party_ids),
        documents={
            d.id: RunDocument(
                party_id=d.party_id,
                role=link.role,
                source_url=d.source_url,
                pages={page.page_number: page.text for page in d.pages},
            )
            for link, d in run_documents
        },
    )
