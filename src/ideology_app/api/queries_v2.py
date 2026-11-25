"""Read model of the public API for v2 Dataset Versions (public-dataset-api-v2).

SELECT only, one Constituency at a time. Imports only ``models``,
``constituency_rules``, ``topic_catalog``, ``party_logos`` and the legacy
read model's version lookup; never ``pipeline.runs``, the ingestion ledger,
``counted_proposals`` or ``llm``.

- Only ``published`` and ``superseded`` versions are served; a legacy one is
  refused with ``dataset_version_is_legacy`` (A2).
- A Party's value and Evidence in a Constituency come only from
  ``constituency_rules.effective_value`` and ``counting_evidence`` (S5, A6).
- ``statements.text`` is the only Statement text served: Statement
  Rewordings are never read (R12).
- A version's Proposals come only from its frozen ``dataset_version_proposals``
  rows (A8), filtered in Python.
- Excluded Parties appear only in ``excluded_parties``; every Party list is
  ordered by Party id and every Party is shaped the same.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app.api.queries import ApiNotFoundError, _utc_timestamp, public_version
from ideology_app.api.schemas import (
    ConstituencyListOut,
    ConstituencyPartyOut,
    ConstituencyPositionOut,
    ConstituencyProposalsOut,
    ConstituencyQuestionnaireOut,
    ConstituencyStatementOut,
    ConstituencySummaryOut,
    ExcludedPartyOut,
    PartyProposalsOut,
    ProposalOut,
)
from ideology_app.constituency_rules import counting_evidence, effective_value
from ideology_app.models import (
    NO_STANCE,
    Constituency,
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    ModelGeneration,
    Party,
    PartyPosition,
    PartyPositionProposal,
    Proposal,
    SourceDocument,
    Statement,
)
from ideology_app.party_logos import logo_url
from ideology_app.topic_catalog import TOPIC_CATALOG

CATEGORY_KEYS = frozenset(entry.key for entry in TOPIC_CATALOG)


def _version_is_legacy(dataset_version_id: int) -> ApiNotFoundError:
    return ApiNotFoundError(
        "dataset_version_is_legacy",
        f"dataset version {dataset_version_id} is a legacy version; "
        f"read /api/v1/dataset-versions/{dataset_version_id}",
    )


def _v2_version(session: Session, dataset_version_id: int) -> DatasetVersion:
    version = public_version(session, dataset_version_id)
    if version.model_generation is not ModelGeneration.V2:
        raise _version_is_legacy(dataset_version_id)
    return version


def _constituency(
    session: Session, dataset_version_id: int, code: str
) -> tuple[DatasetVersionConstituency, str]:
    row = session.execute(
        select(DatasetVersionConstituency, Constituency.name)
        .join(Constituency, Constituency.code == DatasetVersionConstituency.constituency_code)
        .where(
            DatasetVersionConstituency.dataset_version_id == dataset_version_id,
            DatasetVersionConstituency.constituency_code == code,
        )
    ).first()
    if row is None:
        raise ApiNotFoundError("constituency_not_found", f"constituency {code} not found")
    return row[0], row[1]


@dataclass(frozen=True)
class _Candidates:
    """R(c) (``running``) and the Excluded Parties of c (``excluded``: id -> reason), by id."""

    running: tuple[int, ...]
    excluded: dict[int, str]


def _candidates(session: Session, dataset_version_id: int, code: str) -> _Candidates:
    rows = session.execute(
        select(DatasetVersionCandidature.party_id, DatasetVersionCandidature.excluded_reason)
        .where(
            DatasetVersionCandidature.dataset_version_id == dataset_version_id,
            DatasetVersionCandidature.constituency_code == code,
        )
        .order_by(DatasetVersionCandidature.party_id)
    ).all()
    return _Candidates(
        running=tuple(party_id for party_id, reason in rows if reason is None),
        excluded={party_id: reason for party_id, reason in rows if reason is not None},
    )


def list_constituencies(session: Session, dataset_version_id: int) -> ConstituencyListOut:
    """Every Constituency row of a public v2 version, in code order."""
    version = _v2_version(session, dataset_version_id)
    rows = session.execute(
        select(DatasetVersionConstituency, Constituency.name)
        .join(Constituency, Constituency.code == DatasetVersionConstituency.constituency_code)
        .where(DatasetVersionConstituency.dataset_version_id == version.id)
        .order_by(DatasetVersionConstituency.constituency_code)
    ).all()
    return ConstituencyListOut(
        id=version.id,
        election_id=version.election_id,
        created_at=_utc_timestamp(version.created_at),
        constituencies=[
            ConstituencySummaryOut(
                code=row.constituency_code,
                name=name,
                available=row.available,
                unavailable_reason=row.unavailable_reason,
                valid_statement_count=row.valid_statement_count,
                offered_lengths=list(row.offered_lengths),
            )
            for row, name in rows
        ],
    )


@dataclass(frozen=True)
class _Evidence:
    proposal_id: int
    constituencies: tuple[str, ...]
    proposal: ProposalOut


def _proposal_out(
    proposal_id: int, text: str, page: int, url: str | None, source_document_id: int
) -> ProposalOut:
    return ProposalOut(
        id=proposal_id, text=text, page=page, url=url, source_document_id=source_document_id
    )


def _evidence_by_position(
    session: Session, position_ids: Sequence[int]
) -> dict[int, list[_Evidence]]:
    """Each Position's Evidence rows in rank order, with the Proposal and its URL."""
    if not position_ids:
        return {}
    rows = session.execute(
        select(
            PartyPositionProposal.party_position_id,
            PartyPositionProposal.proposal_id,
            PartyPositionProposal.source_document_id,
            PartyPositionProposal.constituencies,
            Proposal.text,
            Proposal.page,
            SourceDocument.source_url,
        )
        .join(Proposal, Proposal.id == PartyPositionProposal.proposal_id)
        .join(SourceDocument, SourceDocument.id == PartyPositionProposal.source_document_id)
        .where(PartyPositionProposal.party_position_id.in_(position_ids))
        .order_by(PartyPositionProposal.party_position_id, PartyPositionProposal.rank)
    ).all()
    result: dict[int, list[_Evidence]] = {}
    for position_id, proposal_id, document_id, codes, text, page, url in rows:
        result.setdefault(position_id, []).append(
            _Evidence(
                proposal_id,
                tuple(codes),
                _proposal_out(proposal_id, text, page, url, document_id),
            )
        )
    return result


def _parties(session: Session, party_ids: Sequence[int]) -> dict[int, Party]:
    if not party_ids:
        return {}
    return {
        party.id: party
        for party in session.scalars(select(Party).where(Party.id.in_(party_ids)))
    }


def get_questionnaire(
    session: Session, dataset_version_id: int, code: str
) -> ConstituencyQuestionnaireOut:
    """One Constituency of a public v2 version: ranked Statements, R(c) with S5 values."""
    version = _v2_version(session, dataset_version_id)
    row, name = _constituency(session, version.id, code)
    statements = session.execute(
        select(Statement, ConstituencyStatement.rank)
        .join(ConstituencyStatement, ConstituencyStatement.statement_id == Statement.id)
        .where(
            ConstituencyStatement.dataset_version_id == version.id,
            ConstituencyStatement.constituency_code == code,
        )
        .order_by(ConstituencyStatement.rank)
    ).all()
    candidates = _candidates(session, version.id, code)
    parties = _parties(session, [*candidates.running, *candidates.excluded])
    statement_ids = [statement.id for statement, _ in statements]
    positions: dict[tuple[int, int], PartyPosition] = {}
    if statement_ids and candidates.running:
        positions = {
            (position.party_id, position.statement_id): position
            for position in session.scalars(
                select(PartyPosition).where(
                    PartyPosition.statement_id.in_(statement_ids),
                    PartyPosition.party_id.in_(candidates.running),
                )
            )
        }
    evidence = _evidence_by_position(session, sorted(p.id for p in positions.values()))

    party_outs: list[ConstituencyPartyOut] = []
    for party_id in candidates.running:
        party = parties[party_id]
        position_outs: list[ConstituencyPositionOut] = []
        shown: dict[int, ProposalOut] = {}
        for statement_id in statement_ids:
            position = positions.get((party_id, statement_id))
            rows = [] if position is None else evidence.get(position.id, [])
            codes = [e.constituencies for e in rows]
            value = effective_value(None if position is None else position.value, codes, code)
            counting = () if value is None else counting_evidence(codes, code)
            for index in counting:
                shown.setdefault(rows[index].proposal_id, rows[index].proposal)
            position_outs.append(
                ConstituencyPositionOut(
                    statement_id=statement_id,
                    value=NO_STANCE if value is None else value,
                    evidence_proposal_ids=[rows[index].proposal_id for index in counting],
                )
            )
        party_outs.append(
            ConstituencyPartyOut(
                id=party.id,
                name=party.name,
                short_name=party.short_name,
                logo_url=logo_url(party.id, party.logo_sha256),
                positions=position_outs,
                evidence=[shown[proposal_id] for proposal_id in sorted(shown)],
            )
        )
    return ConstituencyQuestionnaireOut(
        dataset_version_id=version.id,
        code=code,
        name=name,
        available=row.available,
        unavailable_reason=row.unavailable_reason,
        offered_lengths=list(row.offered_lengths),
        statements=[
            ConstituencyStatementOut(
                id=statement.id,
                rank=rank,
                text=statement.text,
                topic=statement.topic,
                context_note=statement.context_note,
            )
            for statement, rank in statements
        ],
        parties=party_outs,
        excluded_parties=[
            ExcludedPartyOut(
                id=party_id,
                name=parties[party_id].name,
                short_name=parties[party_id].short_name,
                reason=reason,
            )
            for party_id, reason in sorted(candidates.excluded.items())
        ],
    )


def get_proposals(
    session: Session, dataset_version_id: int, code: str, category: str
) -> ConstituencyProposalsOut:
    """Each Party of R(c) with its frozen Proposals counting in c that carry ``category``."""
    version = _v2_version(session, dataset_version_id)
    _constituency(session, version.id, code)
    if category not in CATEGORY_KEYS:
        raise ApiNotFoundError("category_not_found", f"category {category} not found")
    running = _candidates(session, version.id, code).running
    frozen: dict[int, list[tuple[tuple[str, ...], tuple[str, ...], ProposalOut]]] = {
        party_id: [] for party_id in running
    }
    if running:
        rows = session.execute(
            select(
                DatasetVersionProposal.party_id,
                DatasetVersionProposal.proposal_id,
                DatasetVersionProposal.source_document_id,
                DatasetVersionProposal.constituencies,
                Proposal.text,
                Proposal.page,
                Proposal.categories,
                SourceDocument.source_url,
            )
            .join(Proposal, Proposal.id == DatasetVersionProposal.proposal_id)
            .join(SourceDocument, SourceDocument.id == DatasetVersionProposal.source_document_id)
            .where(
                DatasetVersionProposal.dataset_version_id == version.id,
                DatasetVersionProposal.party_id.in_(running),
            )
            .order_by(DatasetVersionProposal.party_id, DatasetVersionProposal.rank)
        ).all()
        for party_id, proposal_id, document_id, codes, text, page, categories, url in rows:
            frozen[party_id].append(
                (
                    tuple(codes),
                    tuple(categories),
                    _proposal_out(proposal_id, text, page, url, document_id),
                )
            )
    parties: list[PartyProposalsOut] = []
    for party_id in running:
        items = frozen[party_id]
        # The same "counts in c" rule as Evidence: one row per counted Proposal.
        counting = counting_evidence([codes for codes, _, _ in items], code)
        parties.append(
            PartyProposalsOut(
                party_id=party_id,
                proposals=[
                    items[index][2] for index in counting if category in items[index][1]
                ],
            )
        )
    return ConstituencyProposalsOut(
        dataset_version_id=version.id, code=code, category=category, parties=parties
    )


__all__ = ["CATEGORY_KEYS", "get_proposals", "get_questionnaire", "list_constituencies"]
