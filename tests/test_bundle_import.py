"""Import a Source Text Bundle into a database (source-text-bundle Scenarios 4-7, 9, 10, 12)."""

import dataclasses
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import PP, PSOE, SLUG, PartySpec, write_bundle
from pdf_factory import make_text_pdf
from pipeline_fixtures import PAGES, fake_provider, offline_guard
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ideology_app.bundle_import import (
    BundleConflictError,
    DocumentStatus,
    check_against_bundle,
    import_bundle,
)
from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, add_party, create_election
from ideology_app.models import (
    Election,
    ElectionStatus,
    PartyPosition,
    PipelineRunSourceDocument,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentRole,
    SourceDocumentStatus,
)
from ideology_app.pipeline import execute_run, queue_run
from ideology_app.source_bundle import read_bundle
from ideology_app.source_documents import (
    add_uploaded_document,
    due_url_document_ids,
    refetch_url_document,
)

NOW = dt.datetime(2030, 1, 1, tzinfo=dt.UTC)
PSOE_V2 = dataclasses.replace(PSOE, pages=["Medidas nuevas de empleo.", "Otra página.", "Tres."])


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def _import(engine: Engine, directory: Path) -> Any:
    with session_scope(engine) as session:
        report = import_bundle(session, read_bundle(directory))
        report.new_documents = [d.id for d in report.new_documents]
    return report


def _snapshot(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    tables = ("elections", "parties", "source_documents", "source_document_pages", "pipeline_runs")
    with engine.connect() as conn:
        return {
            t: [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {t} ORDER BY 1"))]
            for t in tables
        }


# --- Scenario 4: import into an empty database --------------------------------


def test_import_into_an_empty_database(
    migrated_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_FILES_DIR", str(tmp_path / "stored"))
    directory = write_bundle(tmp_path / "data")

    report = _import(migrated_engine, directory)

    assert (report.slug, report.election_id, report.election_created) == (SLUG, 1, True)
    assert [(o.short_name, o.party_id, o.party_created, o.status, o.document_id, o.page_count)
            for o in report.outcomes] == [
        ("PP", 1, True, DocumentStatus.ADDED, 1, 3),
        ("PSOE", 2, True, DocumentStatus.ADDED, 2, 2),
    ]
    assert report.new_documents == [1, 2]
    with Session(migrated_engine) as s:
        election = s.get(Election, 1)
        assert election is not None
        assert (election.country, election.type.value, election.date, election.name,
                election.status) == ("ES", "general", dt.date(2023, 7, 23),
                                     "Elecciones generales 2023", ElectionStatus.DRAFT)
        assert [(p.id, p.short_name, p.name) for p in election.parties] == [
            (1, "PP", "Partido Popular"), (2, "PSOE", "Partido Socialista Obrero Español")
        ]
        pp, psoe = s.scalars(select(SourceDocument).order_by(SourceDocument.id)).all()
        assert (pp.origin, pp.source_url, psoe.origin, psoe.source_url) == (
            SourceDocumentOrigin.URL, "https://example.org/pp.pdf", SourceDocumentOrigin.UPLOAD, None
        )
        for document, spec in ((pp, PP), (psoe, PSOE)):
            data = (directory / spec.file).read_bytes()
            assert document.status is SourceDocumentStatus.PARSED
            assert document.bundle_file == document.original_filename == spec.file
            assert document.content_hash == hashlib.sha256(data).hexdigest()
            assert document.page_count == len(spec.pages)
            assert [(p.page_number, p.text) for p in document.pages] == list(
                enumerate(spec.pages, start=1)
            )
            assert document.stored_filename is None
            assert document.replaced_by_id is None and document.last_checked_at is None
    assert not (tmp_path / "stored").exists()


# --- Scenario 5: re-import is a no-op ------------------------------------------


def test_reimport_changes_nothing(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    before = _snapshot(migrated_engine)

    report = _import(migrated_engine, directory)

    assert [(o.status, o.party_created, o.document_id) for o in report.outcomes] == [
        (DocumentStatus.UNCHANGED, False, 1), (DocumentStatus.UNCHANGED, False, 2)
    ]
    assert report.new_documents == [] and not report.election_created
    assert _snapshot(migrated_engine) == before


# --- Scenario 6: a changed file registers a replacement -----------------------


def test_changed_file_registers_a_replacement(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    with Session(migrated_engine) as s:
        old_pages = [(p.page_number, p.text) for p in s.get(SourceDocument, 2).pages]
        old_hash = s.get(SourceDocument, 2).content_hash
    (directory / "psoe.md").write_bytes(PSOE_V2.content())

    report = _import(migrated_engine, directory)

    assert [(o.short_name, o.status, o.document_id, o.replaced_document_id)
            for o in report.outcomes] == [
        ("PP", DocumentStatus.UNCHANGED, 1, None),
        ("PSOE", DocumentStatus.REPLACED, 3, 2),
    ]
    assert report.new_documents == [3]
    with Session(migrated_engine) as s:
        old, new = s.get(SourceDocument, 2), s.get(SourceDocument, 3)
        assert old.replaced_by_id == 3
        assert old.content_hash == old_hash
        assert [(p.page_number, p.text) for p in old.pages] == old_pages
        assert (new.party_id, new.bundle_file, new.status, new.replaced_by_id) == (
            2, "psoe.md", SourceDocumentStatus.PARSED, None
        )
        assert [p.text for p in new.pages] == list(PSOE_V2.pages)


def test_next_run_reads_only_the_new_row_as_main(migrated_engine: Engine, tmp_path: Path) -> None:
    pa = PartySpec("PA", "Partido Alfa", "pa.md", PAGES[1])
    bb = PartySpec("BB", "Bloque Beta", "bb.md", ["Texto antiguo."])
    directory = write_bundle(tmp_path, [pa, bb])
    _import(migrated_engine, directory)
    (directory / "bb.md").write_bytes(dataclasses.replace(bb, pages=PAGES[2]).content())
    _import(migrated_engine, directory)

    provider = fake_provider()
    with session_scope(migrated_engine) as s:
        run_id = queue_run(
            s, 1, llm_provider=provider.name, llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    execute_run(migrated_engine, run_id, provider)

    with Session(migrated_engine) as s:
        inputs = s.execute(
            select(PipelineRunSourceDocument.source_document_id, PipelineRunSourceDocument.role)
            .where(PipelineRunSourceDocument.pipeline_run_id == run_id)
            .order_by(PipelineRunSourceDocument.source_document_id)
        ).all()
    assert inputs == [(1, SourceDocumentRole.MAIN), (3, SourceDocumentRole.MAIN)]
    assert all("Texto antiguo." not in call.prompt for call in provider.calls)


# --- Scenario 7: Evidence without a URL ---------------------------------------


def test_evidence_url_is_the_source_url_or_null(migrated_engine: Engine, tmp_path: Path) -> None:
    pa = PartySpec("PA", "Partido Alfa", "pa.md", PAGES[1], source_url="https://e.org/pa.pdf")
    bb = PartySpec("BB", "Bloque Beta", "bb.md", PAGES[2])
    _import(migrated_engine, write_bundle(tmp_path, [pa, bb]))
    provider = fake_provider()
    with session_scope(migrated_engine) as s:
        run_id = queue_run(
            s, 1, llm_provider=provider.name, llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id

    outcome = execute_run(migrated_engine, run_id, provider)

    assert outcome.status.value == "passed"
    with Session(migrated_engine) as s:
        urls = {
            (party_id, url)
            for party_id, url in s.execute(
                select(PartyPosition.party_id, PartyPosition.evidence_url).where(
                    PartyPosition.value.is_not(None)
                )
            )
        }
    assert urls == {(1, "https://e.org/pa.pdf"), (2, None)}


# --- Scenario 9: conflicts are refused, nothing changes ----------------------


def _seed_other(engine: Engine, *, election_name: str = "Elecciones generales 2023",
                parties: tuple[tuple[str, str], ...] = ()) -> None:
    with session_scope(engine) as s:
        election = create_election(
            s, country="ES", type="general", date=dt.date(2023, 7, 23), name=election_name
        )
        for short, name in parties:
            add_party(s, election_id=election.id, name=name, short_name=short)


@pytest.mark.parametrize(
    ("seed", "message"),
    [
        ({"election_name": "Generales 2023"},
         "election es-general-2023-07-23 (id 1) exists with name 'Generales 2023'"),
        ({"parties": (("PP", "Partido Popular de España"),)},
         "party PP (id 1) exists with name 'Partido Popular de España'"),
        ({"parties": (("PPE", "Partido Popular"),)},
         "party 'Partido Popular' exists as PPE (id 1), but the bundle names it PP"),
    ],
)
def test_name_conflicts_are_refused(
    migrated_engine: Engine, tmp_path: Path, seed: dict[str, Any], message: str
) -> None:
    _seed_other(migrated_engine, **seed)
    before = _snapshot(migrated_engine)
    with pytest.raises(BundleConflictError) as caught:
        _import(migrated_engine, write_bundle(tmp_path))
    assert message in str(caught.value)
    assert "import into a fresh database" in str(caught.value)
    assert _snapshot(migrated_engine) == before


def test_source_add_document_is_a_conflict(migrated_engine: Engine, tmp_path: Path) -> None:
    _seed_other(migrated_engine, parties=(("PP", "Partido Popular"),))
    pdf = tmp_path / "pp.pdf"
    pdf.write_bytes(make_text_pdf(["Programa."]))
    with session_scope(migrated_engine) as s:
        add_uploaded_document(s, party_id=1, file_path=pdf, files_dir=tmp_path / "stored")
    before = _snapshot(migrated_engine)

    with pytest.raises(BundleConflictError) as caught:
        _import(migrated_engine, write_bundle(tmp_path / "data"))

    assert str(caught.value) == (
        "party PP (id 1) has source document 1, which was not imported from a bundle; "
        "import into a fresh database"
    )
    assert _snapshot(migrated_engine) == before


def test_reverted_file_is_a_conflict(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    (directory / "psoe.md").write_bytes(PSOE_V2.content())
    _import(migrated_engine, directory)
    (directory / "psoe.md").write_bytes(PSOE.content())
    before = _snapshot(migrated_engine)

    with pytest.raises(BundleConflictError, match="same content as older source document 2"):
        _import(migrated_engine, directory)
    assert _snapshot(migrated_engine) == before


def test_parties_not_in_the_bundle_are_left_alone(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle(tmp_path, [PP])
    _import(migrated_engine, directory)
    with session_scope(migrated_engine) as s:
        add_party(s, election_id=1, name="Unión del Pueblo Navarro", short_name="UPN")

    report = _import(migrated_engine, directory)

    assert report.left_alone == [("UPN", 2)]


def test_invalid_source_url_is_refused_before_any_write(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    bad = dataclasses.replace(PP, source_url="ftp://example.org/pp.pdf")
    before = _snapshot(migrated_engine)
    with pytest.raises(InvalidInputError, match=r"pp.md: source_url: invalid URL"):
        _import(migrated_engine, write_bundle(tmp_path, [bad]))
    assert _snapshot(migrated_engine) == before


def test_a_url_document_becomes_an_upload_when_the_url_is_dropped(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    directory = write_bundle(tmp_path, [PP])
    _import(migrated_engine, directory)
    (directory / "pp.md").write_bytes(dataclasses.replace(PP, source_url=None).content())
    _import(migrated_engine, directory)
    with Session(migrated_engine) as s:
        new = s.get(SourceDocument, 2)
        assert (new.origin, new.source_url) == (SourceDocumentOrigin.UPLOAD, None)
        assert s.get(SourceDocument, 1).replaced_by_id == 2


def test_rebuild_from_scratch_gives_the_same_ids(tmp_path: Path) -> None:
    from ideology_app.db import make_engine, run_migrations

    directory = write_bundle(tmp_path / "data", [PSOE, PP])
    snapshots = []
    for name in ("a.db", "b.db"):
        url = f"sqlite:///{tmp_path / name}"
        run_migrations(url)
        engine = make_engine(url)
        try:
            _import(engine, directory)
            with engine.connect() as conn:
                snapshots.append(conn.execute(sa.text(
                    "SELECT p.id, p.short_name, d.id, d.content_hash FROM parties p "
                    "JOIN source_documents d ON d.party_id = p.id ORDER BY p.id"
                )).all())
        finally:
            engine.dispose()
    assert snapshots[0] == snapshots[1]
    assert [row[1] for row in snapshots[0]] == ["PSOE", "PP"]


# --- Scenario 10: bundle documents are never re-fetched -----------------------


def test_bundle_documents_are_never_refetched(migrated_engine: Engine, tmp_path: Path) -> None:
    _import(migrated_engine, write_bundle(tmp_path))

    def _no_fetch(url: str) -> bytes:
        raise AssertionError("a bundle document must not be fetched")

    with session_scope(migrated_engine) as s:
        assert due_url_document_ids(s, now=NOW, interval=dt.timedelta(hours=6)) == []
        with pytest.raises(InvalidInputError) as caught:
            refetch_url_document(s, 1, now=NOW, files_dir=tmp_path, fetch=_no_fetch)
    assert str(caught.value) == (
        "source document 1 was imported from a source text bundle; it is never re-fetched"
    )
    with Session(migrated_engine) as s:
        assert s.get(SourceDocument, 1).last_checked_at is None


# --- Scenario 12: the database is checked against the bundle -------------------


def test_check_matches_after_import(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    before = _snapshot(migrated_engine)
    with Session(migrated_engine) as s:
        assert check_against_bundle(s, read_bundle(directory)) == []
    assert _snapshot(migrated_engine) == before


def test_check_on_an_empty_database(migrated_engine: Engine, tmp_path: Path) -> None:
    with Session(migrated_engine) as s:
        assert check_against_bundle(s, read_bundle(write_bundle(tmp_path))) == [
            "election es-general-2023-07-23 not found"
        ]


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        ("UPDATE source_document_pages SET text = 'cambiado' "
         "WHERE source_document_id = 2 AND page_number = 2",
         "party PSOE (id 2): source document 2: page 2 text differs from psoe.md"),
        ("DELETE FROM source_document_pages WHERE source_document_id = 1 AND page_number = 3",
         "party PP (id 1): source document 1: has 2 page rows, pp.md has 3 pages"),
        ("UPDATE source_documents SET content_hash = '" + "0" * 64 + "' WHERE id = 1",
         "party PP (id 1): source document 1: content_hash differs from the SHA-256 of pp.md"),
        ("UPDATE source_documents SET page_count = 9 WHERE id = 1",
         "party PP (id 1): source document 1: page_count 9 differs from 3"),
        ("UPDATE parties SET name = 'Otro' WHERE id = 2",
         "party PSOE (id 2): name 'Otro' differs from 'Partido Socialista Obrero Español'"),
        ("UPDATE source_documents SET status = 'failed' WHERE id = 2",
         "party PSOE (id 2): no current source document for psoe.md"),
    ],
)
def test_check_finds_each_divergence(
    migrated_engine: Engine, tmp_path: Path, statement: str, problem: str
) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text(statement))
    with Session(migrated_engine) as s:
        assert check_against_bundle(s, read_bundle(directory)) == [problem]


def test_check_finds_a_replaced_file_and_a_source_add_document(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    directory = write_bundle(tmp_path)
    _import(migrated_engine, directory)
    (directory / "psoe.md").write_bytes(PSOE_V2.content())
    pdf = tmp_path / "anexo.pdf"
    pdf.write_bytes(make_text_pdf(["Anexo."]))
    with session_scope(migrated_engine) as s:
        add_uploaded_document(s, party_id=1, file_path=pdf, files_dir=tmp_path / "stored")
    with Session(migrated_engine) as s:
        problems = check_against_bundle(s, read_bundle(directory))
    assert problems == [
        "party PP (id 1): source document 3 was not imported from a bundle",
        "party PSOE (id 2): source document 2: content_hash differs from the SHA-256 of psoe.md",
        "party PSOE (id 2): source document 2: page_count 2 differs from 3",
        "party PSOE (id 2): source document 2: has 2 page rows, psoe.md has 3 pages",
        "party PSOE (id 2): source document 2: page 1 text differs from psoe.md",
        "party PSOE (id 2): source document 2: page 2 text differs from psoe.md",
    ]


def test_check_finds_a_missing_party(migrated_engine: Engine, tmp_path: Path) -> None:
    _import(migrated_engine, write_bundle(tmp_path / "one", [PP]))
    with Session(migrated_engine) as s:
        assert check_against_bundle(s, read_bundle(write_bundle(tmp_path / "two"))) == [
            "party PSOE not found"
        ]
