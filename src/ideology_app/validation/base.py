"""Validation data: what a check reads (``ValidationInput``) and what it returns.

Checks are pure functions of ``ValidationInput``: no database, LLM, network or
clock. ``load_input`` is the only place that reads the database for them.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ideology_app.config import ConstituencySettings, ValidationSettings
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    ModelGeneration,
    Party,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunSourceDocument,
    Proposal,
    SourceDocument,
    SourceDocumentRole,
    Statement,
    StatementProposal,
)

MESSAGE_MAX = 500
CHECK_NAME_MAX = 50


@dataclass(frozen=True)
class StatementRow:
    """A Statement; ``context_note`` is None when it has none (versions before ``0014``)."""

    id: int
    position: int
    text: str
    topic: str
    context_note: str | None = None


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
    content_hash: str | None = None


@dataclass(frozen=True)
class EvidenceRow:
    """One Evidence Proposal of a v2 Party Position (``party_position_proposals``)."""

    rank: int
    proposal_id: int
    source_document_id: int
    constituencies: tuple[str, ...]


@dataclass(frozen=True)
class ProposalRow:
    """A Proposal a v2 run cites (source or Evidence), as stored."""

    content_hash: str
    page: int
    text: str


@dataclass(frozen=True)
class SnapshotRow:
    """A frozen candidature of a v2 Dataset Version (``dataset_version_candidatures``)."""

    party_id: int
    code: str
    excluded_reason: str | None = None


@dataclass(frozen=True)
class ConstituencyRowData:
    """A stored ``dataset_version_constituencies`` row."""

    code: str
    available: bool
    unavailable_reason: str | None
    valid_statement_count: int
    offered_lengths: tuple[int, ...]
    detail: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ValidationInput:
    """Everything the checks may read about one run, as plain data.

    ``statements`` are in position order; ``positions`` by Statement position
    then Party id; ``party_ids`` are the Election's Parties in id order;
    ``documents`` maps document id to every Source Document the run read;
    ``settings`` holds the configured thresholds; ``lengths`` are the
    questionnaire lengths the Dataset Version offers, ascending, the last
    being its Statement count (``()`` for versions created before lengths
    existed, read as the full length by ``offered_lengths``). A check that needs more data
    adds a field here and fills it in ``load_input``; a check that needs a new
    threshold adds a field to ``config.ValidationSettings`` instead.
    """

    statements: tuple[StatementRow, ...]
    positions: tuple[PositionRow, ...]
    party_ids: tuple[int, ...]
    documents: Mapping[int, RunDocument] = field(default_factory=dict)
    settings: ValidationSettings = ValidationSettings()
    lengths: tuple[int, ...] = ()
    # v2 runs only (statements-from-proposals); empty for legacy runs.
    generation: ModelGeneration = ModelGeneration.LEGACY
    # Statement id -> its source Proposal ids in rank order.
    statement_sources: Mapping[int, tuple[int, ...]] = field(default_factory=dict)
    # (Statement id, Party id) -> the Position's Evidence rows in rank order.
    evidence: Mapping[tuple[int, int], tuple[EvidenceRow, ...]] = field(default_factory=dict)
    # Proposal id -> every Proposal cited as a source or as Evidence.
    proposals: Mapping[int, ProposalRow] = field(default_factory=dict)
    # v2 runs only (constituency-selection-validation); empty for legacy runs.
    constituency_settings: ConstituencySettings = ConstituencySettings()
    # The frozen candidature copy, by Party id then code.
    candidatures: tuple[SnapshotRow, ...] = ()
    # The stored Constituency rows, by code.
    constituency_rows: tuple[ConstituencyRowData, ...] = ()
    # Constituency code -> its (rank, Statement id) rows in rank order.
    constituency_statements: Mapping[str, tuple[tuple[int, int], ...]] = field(
        default_factory=dict
    )


def offered_lengths(data: ValidationInput) -> tuple[int, ...]:
    """The questionnaire lengths to check: ``data.lengths``, or the full length.

    Empty when there are no Statements. A questionnaire of length L is the
    first L Statements in position order.
    """
    if not data.statements:
        return ()
    return data.lengths or (len(data.statements),)


def length_prefix(length: int, total: int) -> str:
    """The message prefix for a check on the first ``length`` of ``total`` Statements."""
    return "" if length == total else f"first {length} statements: "


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


def load_input(
    session: Session,
    run: PipelineRun,
    settings: ValidationSettings,
    constituency_settings: ConstituencySettings | None = None,
) -> ValidationInput:
    """Read the run's Dataset Version and the Source Documents it read.

    ``settings`` is passed through unchanged. The run must have a Dataset Version.
    For a v2 run it also reads the Statement sources, the Evidence Proposals
    and the Proposals they cite, the candidature snapshot, the Constituency
    rows and each Constituency's ranked Statements, and ``party_ids`` are the
    Parties with Positions (the non-Excluded ones), not every Party of the
    Election. ``constituency_settings`` (v2 only; ``None``: the defaults) is
    passed through unchanged.
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
    generation = run.model_generation
    statement_sources: dict[int, tuple[int, ...]] = {}
    evidence: dict[tuple[int, int], tuple[EvidenceRow, ...]] = {}
    proposals: dict[int, ProposalRow] = {}
    candidatures: tuple[SnapshotRow, ...] = ()
    constituency_rows: tuple[ConstituencyRowData, ...] = ()
    constituency_statements: dict[str, tuple[tuple[int, int], ...]] = {}
    if generation is ModelGeneration.V2:
        party_ids = sorted({p.party_id for p, _ in positions})
        sources: dict[int, list[int]] = {}
        for link in session.scalars(
            select(StatementProposal)
            .join(Statement, StatementProposal.statement_id == Statement.id)
            .where(Statement.dataset_version_id == version.id)
            .order_by(StatementProposal.statement_id, StatementProposal.rank)
        ):
            sources.setdefault(link.statement_id, []).append(link.proposal_id)
        statement_sources = {sid: tuple(ids) for sid, ids in sources.items()}
        rows: dict[tuple[int, int], list[EvidenceRow]] = {}
        for item, statement_id, party_id in session.execute(
            select(PartyPositionProposal, PartyPosition.statement_id, PartyPosition.party_id)
            .join(PartyPosition, PartyPositionProposal.party_position_id == PartyPosition.id)
            .join(Statement, PartyPosition.statement_id == Statement.id)
            .where(Statement.dataset_version_id == version.id)
            .order_by(PartyPosition.id, PartyPositionProposal.rank)
        ):
            rows.setdefault((statement_id, party_id), []).append(
                EvidenceRow(
                    rank=item.rank,
                    proposal_id=item.proposal_id,
                    source_document_id=item.source_document_id,
                    constituencies=tuple(item.constituencies),
                )
            )
        evidence = {key: tuple(items) for key, items in rows.items()}
        cited = {pid for ids in statement_sources.values() for pid in ids} | {
            row.proposal_id for items in evidence.values() for row in items
        }
        if cited:
            proposals = {
                p.id: ProposalRow(content_hash=p.content_hash, page=p.page, text=p.text)
                for p in session.scalars(select(Proposal).where(Proposal.id.in_(cited)))
            }
        candidatures = tuple(
            SnapshotRow(c.party_id, c.constituency_code, c.excluded_reason)
            for c in session.scalars(
                select(DatasetVersionCandidature)
                .where(DatasetVersionCandidature.dataset_version_id == version.id)
                .order_by(
                    DatasetVersionCandidature.party_id, DatasetVersionCandidature.constituency_code
                )
            )
        )
        constituency_rows = tuple(
            ConstituencyRowData(
                code=c.constituency_code,
                available=c.available,
                unavailable_reason=c.unavailable_reason,
                valid_statement_count=c.valid_statement_count,
                offered_lengths=tuple(c.offered_lengths),
                detail=c.detail,
            )
            for c in session.scalars(
                select(DatasetVersionConstituency)
                .where(DatasetVersionConstituency.dataset_version_id == version.id)
                .order_by(DatasetVersionConstituency.constituency_code)
            )
        )
        ranked: dict[str, list[tuple[int, int]]] = {}
        for c in session.scalars(
            select(ConstituencyStatement)
            .where(ConstituencyStatement.dataset_version_id == version.id)
            .order_by(ConstituencyStatement.constituency_code, ConstituencyStatement.rank)
        ):
            ranked.setdefault(c.constituency_code, []).append((c.rank, c.statement_id))
        constituency_statements = {code: tuple(items) for code, items in ranked.items()}
    return ValidationInput(
        statements=tuple(
            StatementRow(
                id=s.id,
                position=s.position,
                text=s.text,
                topic=s.topic,
                context_note=s.context_note,
            )
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
                content_hash=d.content_hash,
            )
            for link, d in run_documents
        },
        settings=settings,
        lengths=tuple(version.questionnaire_lengths or ()),
        generation=generation,
        statement_sources=statement_sources,
        evidence=evidence,
        proposals=proposals,
        constituency_settings=(
            constituency_settings
            if constituency_settings is not None and generation is ModelGeneration.V2
            else ConstituencySettings()
        ),
        candidatures=candidatures,
        constituency_rows=constituency_rows,
        constituency_statements=constituency_statements,
    )
