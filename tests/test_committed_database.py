"""The committed shared database ``data/ideology.db`` (shared-database, Scenario 7).

Opened read-only (``mode=ro``) by absolute path, since the conftest chdirs to
``tmp_path``. A migration PR that does not upgrade and commit the file makes
this test fail. Nothing here may write to the committed file.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from ideology_app import elections, shared_db, source_bundle
from ideology_app.bundle_import import check_against_bundle
from ideology_app.db import head_revision
from ideology_app.models import Party, SourceDocument

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED = REPO_ROOT / "data" / "ideology.db"
BUNDLES = REPO_ROOT / "data" / "elections"
SLUG_2023 = "es-general-2023-07-23"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    assert COMMITTED.is_file(), f"{COMMITTED} is missing"
    # Read-only before opening: no sidecar, rollback-journal header.
    assert shared_db.file_checks(COMMITTED) == []
    eng = create_engine(shared_db.read_only_url(COMMITTED))
    try:
        yield eng
    finally:
        eng.dispose()


def test_is_read_only(engine: Engine) -> None:
    with engine.connect() as conn:
        with pytest.raises(Exception, match="readonly"):
            conn.exec_driver_sql("CREATE TABLE never_written (x)")


def test_journal_mode_and_integrity(engine: Engine) -> None:
    header = COMMITTED.read_bytes()[:100]
    assert header[18:20] == b"\x01\x01"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "delete"
        assert [r[0] for r in conn.exec_driver_sql("PRAGMA integrity_check")] == ["ok"]


def test_is_at_migration_head(engine: Engine) -> None:
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    assert current == head_revision(), (
        "data/ideology.db is behind the newest migration; run "
        '"DATABASE_URL=sqlite:///data/ideology.db ideology db upgrade" and commit it'
    )


def test_every_election_with_a_bundle_matches_it(engine: Engine) -> None:
    with Session(engine) as session:
        checked = 0
        for election in elections.list_elections(session):
            slug = source_bundle.bundle_slug(election, BUNDLES)
            if slug is None:
                continue
            bundle = source_bundle.read_bundle(BUNDLES / slug)
            assert check_against_bundle(session, bundle) == [], slug
            checked += 1
        session.rollback()
    assert checked >= 1


def test_the_2023_election(engine: Engine) -> None:
    bundle = source_bundle.read_bundle(BUNDLES / SLUG_2023)
    with Session(engine) as session:
        matches = [
            e
            for e in elections.list_elections(session)
            if source_bundle.election_slug_for(e) == SLUG_2023
        ]
        assert len(matches) == 1
        election = matches[0]
        parties = session.scalars(
            select(Party).where(Party.election_id == election.id).order_by(Party.id)
        ).all()
        assert len(parties) == 9
        assert [p.short_name for p in parties] == [p.short_name for p in bundle.parties]
        by_short = {p.short_name: p for p in parties}
        for entry in bundle.parties:
            document = session.scalars(
                select(SourceDocument).where(
                    SourceDocument.party_id == by_short[entry.short_name].id,
                    SourceDocument.replaced_by_id.is_(None),
                )
            ).one()
            assert [page.text for page in document.pages] == list(entry.text.pages)
        session.rollback()

