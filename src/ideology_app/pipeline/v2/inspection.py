"""Read-only views of a stored v2 Dataset Version for the Operator CLI (v2-run-inspection).

``pipeline report`` prints ``party_rows``, ``source_no_stance`` and
``constituency_rows`` (the 52-row table); ``pipeline statements --sources``
prints ``statement_sources`` and ``pipeline positions --evidence``
``position_evidence``. ``recorded_constituency_settings`` gives
``pipeline validate`` the thresholds a v2 run selected with. Only ``SELECT``
statements, one per table, joined in Python; the results are frozen
dataclasses of plain values. Nothing here writes, and no LLM provider is read.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app.config import ConstituencySettings
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.models import (
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    Party,
    PartyPosition,
    PartyPositionProposal,
    Proposal,
    SourceDocument,
    Statement,
    StatementProposal,
)
from ideology_app.pipeline.runs import list_positions

EXCERPT_LIMIT = 120
ELLIPSIS = "…"


@dataclass(frozen=True)
class PartyRow:
    """A Party of the candidature snapshot. An Excluded Party has only ``excluded`` set
    (with its id and short name); the counts are ``None`` for it."""

    party_id: int
    short_name: str
    proposals: int | None
    partial_scope: bool | None
    sided: int | None
    no_stance: int | None
    excluded: str | None


@dataclass(frozen=True)
class PartySides:
    party_id: int
    sides: int
    first_length_sides: int | None


@dataclass(frozen=True)
class ConstituencyTableRow:
    """One Constituency: availability from the table, the rest from the selection report.

    ``valid`` is the stored ``valid_statement_count`` when the row is stored.
    """

    code: str
    name: str
    available: bool | None
    reason: str | None
    parties: tuple[int, ...]
    excluded: tuple[int, ...]
    valid: int | None
    lengths: tuple[int, ...]
    party_sides: tuple[PartySides, ...]
    topic_max_share: tuple[int, ...]


@dataclass(frozen=True)
class SourceRow:
    """A source Proposal of a Statement, once per Party that counts it in the version.

    ``party_id`` and ``file`` are ``None`` when no Party counts it.
    """

    statement: int
    rank: int
    proposal_id: int
    party_id: int | None
    file: str | None
    page: int
    excerpt: str


@dataclass(frozen=True)
class EvidenceRow:
    """An Evidence Proposal of a Position. A ``no stance`` Position is one row with
    ``value``, ``rank`` and every later field ``None``. ``all_constituencies`` is true
    when the frozen codes equal the Party's codes in the candidature snapshot."""

    statement: int
    party_id: int
    value: int | None
    rank: int | None
    proposal_id: int | None
    file: str | None
    page: int | None
    constituencies: tuple[str, ...] | None
    all_constituencies: bool
    excerpt: str | None


def excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """``text`` on one line (each whitespace run as one space), cut at ``limit``
    characters with a trailing ``…`` when cut."""
    line = re.sub(r"\s+", " ", text)
    return line if len(line) <= limit else line[:limit] + ELLIPSIS


def recorded_constituency_settings(
    selection: Mapping[str, Any] | None,
) -> tuple[ConstituencySettings, int] | None:
    """The per-Constituency minimums and the topic share a v2 run selected with
    (``statement_selection.constituencies.settings``), or ``None`` when not recorded."""
    if not selection:
        return None
    settings = (selection.get("constituencies") or {}).get("settings")
    if not settings:
        return None
    return (
        ConstituencySettings(
            v2_min_statements=settings["v2_min_statements"],
            v2_min_party_sides=settings["v2_min_party_sides"],
        ),
        settings["max_topic_share_percent"],
    )


def _file(document: SourceDocument | None) -> str | None:
    if document is None:
        return None
    return document.original_filename or document.source_url


def _documents(session: Session, ids: set[int]) -> dict[int, SourceDocument]:
    if not ids:
        return {}
    return {
        d.id: d for d in session.scalars(select(SourceDocument).where(SourceDocument.id.in_(ids)))
    }


def _proposals(session: Session, ids: set[int]) -> dict[int, tuple[int, str]]:
    if not ids:
        return {}
    return {
        pid: (page, text)
        for pid, page, text in session.execute(
            select(Proposal.id, Proposal.page, Proposal.text).where(Proposal.id.in_(ids))
        )
    }


def _snapshot(session: Session, version_id: int) -> dict[int, tuple[list[str], str | None]]:
    """Party id -> (sorted Constituency codes, excluded reason) of the candidature snapshot."""
    parties: dict[int, tuple[list[str], str | None]] = {}
    for party_id, code, reason in session.execute(
        select(
            DatasetVersionCandidature.party_id,
            DatasetVersionCandidature.constituency_code,
            DatasetVersionCandidature.excluded_reason,
        )
        .where(DatasetVersionCandidature.dataset_version_id == version_id)
        .order_by(DatasetVersionCandidature.party_id, DatasetVersionCandidature.constituency_code)
    ):
        codes, _ = parties.setdefault(party_id, ([], reason))
        codes.append(code)
    return parties


def party_rows(
    session: Session, version_id: int, selection: Mapping[str, Any] | None
) -> list[PartyRow]:
    """One row per Party of the candidature snapshot, by Party id (see ``PartyRow``)."""
    snapshot = _snapshot(session, version_id)
    reported = {p["party_id"]: p for p in (selection or {}).get("parties", [])}
    names: dict[int, str] = {}
    if snapshot:
        names = {
            party_id: short_name
            for party_id, short_name in session.execute(
                select(Party.id, Party.short_name).where(Party.id.in_(set(snapshot)))
            )
        }
    sided: dict[int, int] = {}
    no_stance: dict[int, int] = {}
    for party_id, value in session.execute(
        select(PartyPosition.party_id, PartyPosition.value)
        .join(Statement, PartyPosition.statement_id == Statement.id)
        .where(Statement.dataset_version_id == version_id)
    ):
        counts = no_stance if value is None else sided
        counts[party_id] = counts.get(party_id, 0) + 1
    rows: list[PartyRow] = []
    for party_id, (_, reason) in sorted(snapshot.items()):
        short_name = names.get(party_id, "")
        if reason is not None:
            rows.append(PartyRow(party_id, short_name, None, None, None, None, reason))
            continue
        entry = reported.get(party_id)
        rows.append(
            PartyRow(
                party_id,
                short_name,
                None if entry is None else entry["proposals"],
                None if entry is None else entry["partial_scope"],
                sided.get(party_id, 0),
                no_stance.get(party_id, 0),
                None,
            )
        )
    return rows


def _statement_positions(session: Session, version_id: int) -> dict[int, int]:
    """Statement id -> position of the version's Statements."""
    return {
        statement_id: position
        for statement_id, position in session.execute(
            select(Statement.id, Statement.position).where(
                Statement.dataset_version_id == version_id
            )
        )
    }


def _statement_sources(
    session: Session, positions: Mapping[int, int]
) -> list[tuple[int, int, int]]:
    """(Statement position, rank, Proposal id) of every source, by position then rank."""
    if not positions:
        return []
    rows = [
        (positions[statement_id], rank, proposal_id)
        for statement_id, rank, proposal_id in session.execute(
            select(
                StatementProposal.statement_id,
                StatementProposal.rank,
                StatementProposal.proposal_id,
            ).where(StatementProposal.statement_id.in_(set(positions)))
        )
    ]
    return sorted(rows)


def _frozen(session: Session, version_id: int) -> list[tuple[int, int, int]]:
    """(Party id, Proposal id, Source Document id) of the frozen counted Proposals."""
    return [
        (party_id, proposal_id, document_id)
        for party_id, proposal_id, document_id in session.execute(
            select(
                DatasetVersionProposal.party_id,
                DatasetVersionProposal.proposal_id,
                DatasetVersionProposal.source_document_id,
            )
            .where(DatasetVersionProposal.dataset_version_id == version_id)
            .order_by(DatasetVersionProposal.party_id, DatasetVersionProposal.rank)
        )
    ]


def source_no_stance(session: Session, version_id: int) -> list[tuple[int, int]]:
    """(Statement position, Party id) where the Party has ``no stance`` although one of
    its frozen counted Proposals is a source of the Statement; by position, Party id."""
    positions = _statement_positions(session, version_id)
    sources: dict[int, set[int]] = {}
    for position, _, proposal_id in _statement_sources(session, positions):
        sources.setdefault(position, set()).add(proposal_id)
    counted: dict[int, set[int]] = {}
    for party_id, proposal_id, _ in _frozen(session, version_id):
        counted.setdefault(party_id, set()).add(proposal_id)
    found: list[tuple[int, int]] = []
    if not positions:
        return found
    for statement_id, party_id in session.execute(
        select(PartyPosition.statement_id, PartyPosition.party_id).where(
            PartyPosition.statement_id.in_(set(positions)),
            PartyPosition.value.is_(None),
        )
    ):
        position = positions[statement_id]
        if sources.get(position, set()) & counted.get(party_id, set()):
            found.append((position, party_id))
    return sorted(found)


def constituency_rows(
    session: Session, version_id: int, selection: Mapping[str, Any] | None
) -> list[ConstituencyTableRow] | None:
    """The 52 rows in ``CONSTITUENCIES`` order, or ``None`` when the run's report has
    no ``constituencies`` key (scratch databases of earlier slices)."""
    report = (selection or {}).get("constituencies")
    if report is None:
        return None
    reported = {row["code"]: row for row in report.get("rows", [])}
    stored = {
        code: (available, reason, valid)
        for code, available, reason, valid in session.execute(
            select(
                DatasetVersionConstituency.constituency_code,
                DatasetVersionConstituency.available,
                DatasetVersionConstituency.unavailable_reason,
                DatasetVersionConstituency.valid_statement_count,
            ).where(DatasetVersionConstituency.dataset_version_id == version_id)
        )
    }
    rows: list[ConstituencyTableRow] = []
    for code, name in CONSTITUENCIES:
        row = reported.get(code, {})
        available, reason, valid = stored.get(code, (None, None, row.get("valid")))
        rows.append(
            ConstituencyTableRow(
                code=code,
                name=name,
                available=available,
                reason=reason,
                parties=tuple(row.get("parties", ())),
                excluded=tuple(row.get("excluded", ())),
                valid=valid,
                lengths=tuple(row.get("lengths", ())),
                party_sides=tuple(
                    PartySides(s["party_id"], s["sides"], s.get("first_length_sides"))
                    for s in row.get("party_sides", ())
                ),
                topic_max_share=tuple(row.get("topic_max_share", ())),
            )
        )
    return rows


def statement_sources(session: Session, version_id: int) -> list[SourceRow]:
    """Every source Proposal of the version's Statements, by Statement position then
    rank, once per Party that counts it in the version (by Party id)."""
    positions = _statement_positions(session, version_id)
    sources = _statement_sources(session, positions)
    counting: dict[int, list[tuple[int, int]]] = {}
    for party_id, proposal_id, document_id in _frozen(session, version_id):
        counting.setdefault(proposal_id, []).append((party_id, document_id))
    proposals = _proposals(session, {proposal_id for _, _, proposal_id in sources})
    documents = _documents(
        session, {d for parties in counting.values() for _, d in parties}
    )
    rows: list[SourceRow] = []
    for position, rank, proposal_id in sources:
        page, text = proposals[proposal_id]
        parties = sorted(counting.get(proposal_id, []))
        if not parties:
            rows.append(SourceRow(position, rank, proposal_id, None, None, page, excerpt(text)))
            continue
        rows.extend(
            SourceRow(
                position,
                rank,
                proposal_id,
                party_id,
                _file(documents.get(document_id)),
                page,
                excerpt(text),
            )
            for party_id, document_id in parties
        )
    return rows


def position_evidence(
    session: Session, version_id: int, party_id: int | None = None
) -> list[EvidenceRow]:
    """One row per Position x Evidence Proposal, by Statement position, Party id, rank.

    Raises NotFoundError (``list_positions``) for an unknown version or Party.
    """
    positions = list_positions(session, version_id, party_id)
    evidence: dict[int, list[tuple[int, int, int, list[str]]]] = {}
    if positions:
        for position_id, rank, proposal_id, document_id, codes in session.execute(
            select(
                PartyPositionProposal.party_position_id,
                PartyPositionProposal.rank,
                PartyPositionProposal.proposal_id,
                PartyPositionProposal.source_document_id,
                PartyPositionProposal.constituencies,
            ).where(PartyPositionProposal.party_position_id.in_({p.id for p in positions}))
        ):
            evidence.setdefault(position_id, []).append(
                (rank, proposal_id, document_id, list(codes))
            )
    proposals = _proposals(
        session, {proposal_id for refs in evidence.values() for _, proposal_id, _, _ in refs}
    )
    documents = _documents(
        session, {document_id for refs in evidence.values() for _, _, document_id, _ in refs}
    )
    snapshot = _snapshot(session, version_id)
    rows: list[EvidenceRow] = []
    for p in positions:
        statement = p.statement.position
        refs = sorted(evidence.get(p.id, []))
        if p.value is None or not refs:
            rows.append(
                EvidenceRow(statement, p.party_id, p.value, None, None, None, None, None,
                            False, None)
            )
            continue
        party_codes = snapshot.get(p.party_id, ([], None))[0]
        for rank, proposal_id, document_id, codes in refs:
            page, text = proposals[proposal_id]
            rows.append(
                EvidenceRow(
                    statement=statement,
                    party_id=p.party_id,
                    value=p.value,
                    rank=rank,
                    proposal_id=proposal_id,
                    file=_file(documents.get(document_id)),
                    page=page,
                    constituencies=tuple(codes),
                    all_constituencies=sorted(codes) == party_codes,
                    excerpt=excerpt(text),
                )
            )
    return rows


__all__ = [
    "ELLIPSIS",
    "EXCERPT_LIMIT",
    "ConstituencyTableRow",
    "EvidenceRow",
    "PartyRow",
    "PartySides",
    "SourceRow",
    "constituency_rows",
    "excerpt",
    "party_rows",
    "position_evidence",
    "recorded_constituency_settings",
    "source_no_stance",
    "statement_sources",
]
