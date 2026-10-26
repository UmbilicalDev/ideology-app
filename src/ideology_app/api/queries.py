"""Read model of the public API: SELECT only, never a write.

``candidate`` Dataset Versions are never exposed: they are indistinguishable
from an unknown id.
"""

import datetime as dt

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.orm import Session

from ideology_app.api.schemas import (
    DatasetVersionOut,
    ElectionListOut,
    ElectionOut,
    EvidenceOut,
    PartyOut,
    PositionOut,
    StatementOut,
)
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    Party,
    PartyPosition,
    Statement,
)
from ideology_app.party_logos import logo_url
from ideology_app.pipeline.publishing import get_published_dataset_version

PUBLIC_STATUSES = frozenset({DatasetVersionStatus.PUBLISHED, DatasetVersionStatus.SUPERSEDED})


class ApiNotFoundError(Exception):
    """A resource the API does not serve; rendered as ``404 {"error": {...}}``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _election_not_found(election_id: int) -> ApiNotFoundError:
    return ApiNotFoundError("election_not_found", f"election {election_id} not found")


def _version_not_found(dataset_version_id: int) -> ApiNotFoundError:
    return ApiNotFoundError(
        "dataset_version_not_found", f"dataset version {dataset_version_id} not found"
    )


def _election_out(election: Election, published_id: int | None) -> ElectionOut:
    return ElectionOut(
        id=election.id,
        country=election.country,
        type=election.type.value,
        date=election.date,
        name=election.name,
        status=election.status.value,
        published_dataset_version_id=published_id,
    )


def _published_join() -> ColumnElement[bool]:
    return and_(
        DatasetVersion.election_id == Election.id,
        DatasetVersion.status == DatasetVersionStatus.PUBLISHED,
    )


def list_active_elections(session: Session) -> ElectionListOut:
    """``active`` Elections, newest date first (then highest id)."""
    rows = session.execute(
        select(Election, DatasetVersion.id)
        .outerjoin(DatasetVersion, _published_join())
        .where(Election.status == ElectionStatus.ACTIVE)
        .order_by(Election.date.desc(), Election.id.desc())
    ).all()
    return ElectionListOut(elections=[_election_out(e, v) for e, v in rows])


def get_election(session: Session, election_id: int) -> ElectionOut:
    """Any Election, whatever its status (``draft`` included)."""
    row = session.execute(
        select(Election, DatasetVersion.id)
        .outerjoin(DatasetVersion, _published_join())
        .where(Election.id == election_id)
    ).first()
    if row is None:
        raise _election_not_found(election_id)
    return _election_out(row[0], row[1])


def get_published_version(session: Session, election_id: int) -> DatasetVersionOut:
    """The Election's Published Dataset Version, as ``get_public_version`` renders it."""
    if session.get(Election, election_id) is None:
        raise _election_not_found(election_id)
    version = get_published_dataset_version(session, election_id)
    if version is None:
        raise ApiNotFoundError(
            "no_published_dataset_version",
            f"election {election_id} has no published dataset version",
        )
    return _version_out(session, version)


def get_public_version(session: Session, dataset_version_id: int) -> DatasetVersionOut:
    """A ``published`` or ``superseded`` Dataset Version; anything else is not found."""
    version = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == dataset_version_id,
            DatasetVersion.status.in_(PUBLIC_STATUSES),
        )
    )
    if version is None:
        raise _version_not_found(dataset_version_id)
    return _version_out(session, version)


def get_party_logo(session: Session, party_id: int) -> tuple[bytes, str, str]:
    """``(bytes, media_type, sha256)`` of a Party's logo (one SELECT of three columns).

    Any Party of any Election: a logo is not part of a Dataset Version.
    """
    row = session.execute(
        select(Party.logo, Party.logo_media_type, Party.logo_sha256).where(Party.id == party_id)
    ).first()
    if row is None:
        raise ApiNotFoundError("party_not_found", f"party {party_id} not found")
    data, media_type, sha256 = row
    if data is None or media_type is None or sha256 is None:
        raise ApiNotFoundError("party_logo_not_found", f"party {party_id} has no logo")
    return data, media_type, sha256


def _utc_timestamp(value: dt.datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ``; a naive value (SQLite) is read as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _position_out(position: PartyPosition) -> PositionOut:
    evidence = None
    if position.value is not None:
        assert position.evidence_quote is not None
        assert position.evidence_page is not None
        assert position.evidence_source_document_id is not None
        evidence = EvidenceOut(
            quote=position.evidence_quote,
            page=position.evidence_page,
            url=position.evidence_url,
            source_document_id=position.evidence_source_document_id,
        )
    return PositionOut(
        statement_id=position.statement_id, value=position.engine_value, evidence=evidence
    )


def _version_out(session: Session, version: DatasetVersion) -> DatasetVersionOut:
    statements = session.scalars(
        select(Statement)
        .where(Statement.dataset_version_id == version.id)
        .order_by(Statement.position)
    ).all()
    positions = session.scalars(
        select(PartyPosition)
        .join(Statement, PartyPosition.statement_id == Statement.id)
        .where(Statement.dataset_version_id == version.id)
        .order_by(Statement.position, PartyPosition.party_id)
    ).all()
    by_party: dict[int, list[PositionOut]] = {}
    for position in positions:
        by_party.setdefault(position.party_id, []).append(_position_out(position))
    parties = (
        session.scalars(
            select(Party).where(Party.id.in_(by_party)).order_by(Party.id)
        ).all()
        if by_party
        else []
    )
    return DatasetVersionOut(
        id=version.id,
        election_id=version.election_id,
        created_at=_utc_timestamp(version.created_at),
        statements=[
            StatementOut(id=s.id, position=s.position, text=s.text, topic=s.topic)
            for s in statements
        ],
        parties=[
            PartyOut(
                id=p.id,
                name=p.name,
                short_name=p.short_name,
                logo_url=logo_url(p.id, p.logo_sha256),
                positions=by_party[p.id],
            )
            for p in parties
        ],
    )
