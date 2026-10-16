import datetime as dt

import pytest
from sqlalchemy.orm import Session

from ideology_app import elections as svc
from ideology_app.models import ElectionStatus, ElectionType

D2023 = dt.date(2023, 7, 23)


def _election(session: Session, **overrides: object) -> int:
    fields: dict[str, object] = {
        "country": "es",
        "type": "general",
        "date": D2023,
        "name": "Elecciones generales 2023",
    }
    fields.update(overrides)
    return svc.create_election(session, **fields).id  # type: ignore[arg-type]


def test_create_and_list_election_with_parties(session: Session) -> None:
    election_id = _election(session, country=" es ")
    svc.add_party(session, election_id=election_id, name="Sumar", short_name="SUMAR")
    svc.add_party(session, election_id=election_id, name=" Partido Popular ", short_name="PP")
    session.commit()

    [election] = svc.list_elections(session)
    assert election.country == "ES"
    assert election.type is ElectionType.GENERAL
    assert election.date == D2023
    assert election.status is ElectionStatus.DRAFT
    assert election.name == "Elecciones generales 2023"

    parties = svc.list_parties(session, election_id)
    assert [(p.short_name, p.name) for p in parties] == [
        ("SUMAR", "Sumar"),
        ("PP", "Partido Popular"),
    ]
    assert [p.short_name for p in election.parties] == ["SUMAR", "PP"]


def test_elections_are_listed_by_date_then_id(session: Session) -> None:
    later = _election(session, date=dt.date(2023, 7, 23))
    earlier = _election(session, date=dt.date(2019, 11, 10))
    session.commit()

    assert [e.id for e in svc.list_elections(session)] == [earlier, later]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"country": "ESP"}, "country"),
        ({"country": "1A"}, "country"),
        ({"country": ""}, "country"),
        ({"type": "regional"}, "type"),
        ({"date": "23/07/2023"}, "date"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
    ],
)
def test_invalid_election_input_is_rejected(
    session: Session, overrides: dict[str, object], field: str
) -> None:
    with pytest.raises(svc.InvalidInputError, match=field):
        _election(session, **overrides)
    session.commit()
    assert svc.list_elections(session) == []


@pytest.mark.parametrize(
    ("name", "short_name", "field"),
    [("", "X", "name"), ("   ", "X", "name"), ("X", "", "short name"), ("X", " \t", "short name")],
)
def test_invalid_party_input_is_rejected(
    session: Session, name: str, short_name: str, field: str
) -> None:
    election_id = _election(session)
    session.commit()

    with pytest.raises(svc.InvalidInputError, match=field):
        svc.add_party(session, election_id=election_id, name=name, short_name=short_name)
    assert svc.list_parties(session, election_id) == []


def test_duplicate_election_is_rejected(session: Session) -> None:
    _election(session)
    session.commit()

    with pytest.raises(svc.DuplicateError, match="already exists"):
        _election(session, name="Another name")
    assert len(svc.list_elections(session)) == 1


@pytest.mark.parametrize(
    ("name", "short_name"), [("Sumar", "SMR"), ("Sumar coalición", "SUMAR")]
)
def test_duplicate_party_is_rejected(session: Session, name: str, short_name: str) -> None:
    election_id = _election(session)
    svc.add_party(session, election_id=election_id, name="Sumar", short_name="SUMAR")
    session.commit()

    with pytest.raises(svc.DuplicateError, match="already exists"):
        svc.add_party(session, election_id=election_id, name=name, short_name=short_name)
    assert [p.short_name for p in svc.list_parties(session, election_id)] == ["SUMAR"]


def test_same_party_name_in_another_election_is_allowed(session: Session) -> None:
    first = _election(session)
    second = _election(session, date=dt.date(2019, 11, 10))
    svc.add_party(session, election_id=first, name="Sumar", short_name="SUMAR")
    svc.add_party(session, election_id=second, name="Sumar", short_name="SUMAR")
    session.commit()

    assert len(svc.list_parties(session, second)) == 1


def test_unknown_election_raises_not_found(session: Session) -> None:
    with pytest.raises(svc.NotFoundError, match="election 999 not found"):
        svc.add_party(session, election_id=999, name="Sumar", short_name="SUMAR")
    with pytest.raises(svc.NotFoundError, match="election 999 not found"):
        svc.list_parties(session, 999)


def test_session_is_usable_after_duplicate_error(session: Session) -> None:
    _election(session)
    session.commit()
    with pytest.raises(svc.DuplicateError):
        _election(session)

    new_id = _election(session, date=dt.date(2019, 11, 10))
    session.commit()

    assert [e.id for e in svc.list_elections(session)] == [new_id, 1]
