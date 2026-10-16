"""Domain service for Elections and their Parties (ballot tickets).

Functions take a Session and leave committing to the caller. Inputs are
validated here, so every caller (CLI today, others later) gets the same rules.
"""

import datetime as dt
import re
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ideology_app.models import Election, ElectionStatus, ElectionType, Party

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_NAME_MAX = 200
_SHORT_NAME_MAX = 50


class ElectionsError(Exception):
    """Base class for errors raised by this service."""


class InvalidInputError(ElectionsError):
    """An input field is malformed. The message names the field."""


class NotFoundError(ElectionsError):
    """A referenced Election does not exist."""


class DuplicateError(ElectionsError):
    """A uniqueness rule would be violated."""


def _required_text(field: str, value: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise InvalidInputError(f"{field} must not be empty")
    if len(cleaned) > max_length:
        raise InvalidInputError(f"{field} must be at most {max_length} characters")
    return cleaned


def _flush_or_duplicate(session: Session, message: str) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(message) from exc


def create_election(
    session: Session, *, country: str, type: str, date: dt.date, name: str
) -> Election:
    """Create a ``draft`` Election. Raises InvalidInputError or DuplicateError."""
    country_code = (country or "").strip().upper()
    if not _COUNTRY_RE.match(country_code):
        raise InvalidInputError(
            f"country {country!r} is invalid: expected a two-letter code such as ES"
        )
    type_value = (type or "").strip().lower()
    try:
        election_type = ElectionType(type_value)
    except ValueError:
        allowed = ", ".join(t.value for t in ElectionType)
        raise InvalidInputError(
            f"type {type!r} is invalid: expected one of {allowed}"
        ) from None
    if not isinstance(date, dt.date) or isinstance(date, dt.datetime):
        raise InvalidInputError(f"date {date!r} is invalid: expected a date")
    clean_name = _required_text("name", name, _NAME_MAX)

    election = Election(
        country=country_code,
        type=election_type,
        date=date,
        name=clean_name,
        status=ElectionStatus.DRAFT,
    )
    session.add(election)
    _flush_or_duplicate(
        session,
        f"election {country_code}/{election_type.value}/{date.isoformat()} already exists",
    )
    return election


def _get_election(session: Session, election_id: int) -> Election:
    election = session.get(Election, election_id)
    if election is None:
        raise NotFoundError(f"election {election_id} not found")
    return election


def add_party(session: Session, *, election_id: int, name: str, short_name: str) -> Party:
    """Add a Party to an Election. Raises InvalidInputError, NotFoundError or DuplicateError."""
    clean_name = _required_text("name", name, _NAME_MAX)
    clean_short = _required_text("short name", short_name, _SHORT_NAME_MAX)
    election = _get_election(session, election_id)

    party = Party(election_id=election.id, name=clean_name, short_name=clean_short)
    session.add(party)
    _flush_or_duplicate(
        session,
        f"a party named {clean_name!r} or with short name {clean_short!r} "
        f"already exists in election {election_id}",
    )
    return party


def list_elections(session: Session) -> Sequence[Election]:
    """All Elections, ordered by date then id."""
    return session.scalars(select(Election).order_by(Election.date, Election.id)).all()


def list_parties(session: Session, election_id: int) -> Sequence[Party]:
    """The Parties of an Election in creation order. Raises NotFoundError."""
    _get_election(session, election_id)
    return session.scalars(
        select(Party).where(Party.election_id == election_id).order_by(Party.id)
    ).all()
