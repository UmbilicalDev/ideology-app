"""Import a Source Text Bundle into a database (source-text-bundle Scenarios 4-7, 9, 10, 12)."""

import dataclasses
import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import (
    BOE_SOURCE,
    BOE_URL,
    DOC_PSC,
    DOC_PSOE,
    PP,
    PSOE,
    SLUG,
    V2_DOCUMENTS,
    V2_PARTIES,
    V2_PP,
    V2_PSC,
    V2_PSOE,
    V2_SMALL,
    V2_UPN,
    CandidatureSpec,
    DocumentSpec,
    PartySpec,
    manifest_v2_text,
    write_bundle,
    write_bundle_v2,
)
from pdf_factory import make_text_pdf
from pipeline_fixtures import PAGES, fake_provider, offline_guard
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ideology_app.bundle_import import (
    BundleConflictError,
    DocumentStatus,
    candidatures_by_party,
    check_against_bundle,
    document_scopes,
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


# --- Manifest format 2: candidatures and document scopes ----------------------------
# (constituencies-and-candidatures Scenarios 4-8)

ALL = tuple(f"{n:02d}" for n in range(1, 53))
CATALONIA = ("08", "17", "25", "43")
NOT_CATALONIA = tuple(code for code in ALL if code not in CATALONIA)
V2_TABLES = ("elections", "parties", "source_documents", "source_document_pages",
             "pipeline_runs", "candidatures", "source_document_constituencies")


def _snapshot_v2(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    with engine.connect() as conn:
        return {
            t: [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {t} ORDER BY 1, 2"))]
            for t in V2_TABLES
        }


def _state(engine: Engine) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    with Session(engine) as s:
        return candidatures_by_party(s, 1), document_scopes(s, 1)


def _check(engine: Engine, directory: Path) -> list[str]:
    with Session(engine) as s:
        return check_against_bundle(s, read_bundle(directory))


def test_format_2_import_into_an_empty_database(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)

    report = _import(migrated_engine, directory)

    assert (report.format, report.election_created, report.candidature_source_change) == (
        2, True, "set"
    )
    assert report.outcomes == [] and report.left_alone == []
    assert [(c.short_name, c.party_id, c.party_created, c.constituencies, len(c.added),
             c.removed) for c in report.candidatures] == [
        ("PP", 1, True, 52, 52, ()),
        ("PSOE", 2, True, 48, 48, ()),
        ("PSC", 3, True, 4, 4, ()),
        ("UPN-PP", 4, True, 1, 1, ()),
        ("PACMA", 5, True, 1, 1, ()),
    ]
    assert [(d.file, d.short_name, d.status, d.document_id, d.scope, d.scope_removed)
            for d in report.documents] == [
        ("pp.md", "PP", DocumentStatus.ADDED, 1, 52, ()),
        ("pp.md", "UPN-PP", DocumentStatus.ADDED, 2, 1, ()),
        ("upn.md", "UPN-PP", DocumentStatus.ADDED, 3, 1, ()),
        ("psoe.md", "PSOE", DocumentStatus.ADDED, 4, 48, ()),
        ("psoe.md", "PSC", DocumentStatus.ADDED, 5, 4, ()),
        ("psc.md", "PSC", DocumentStatus.ADDED, 6, 1, ()),
    ]
    assert report.new_documents == [1, 2, 3, 4, 5, 6]
    candidatures, scopes = _state(migrated_engine)
    assert candidatures == {1: ALL, 2: NOT_CATALONIA, 3: CATALONIA, 4: ("31",), 5: ("28",)}
    assert scopes == {1: ALL, 2: ("31",), 3: ("31",), 4: NOT_CATALONIA, 5: CATALONIA, 6: ("08",)}
    with Session(migrated_engine) as s:
        election = s.get(Election, 1)
        assert (election.candidatures_source, election.candidatures_source_url) == (
            BOE_SOURCE, BOE_URL
        )
        rows = s.scalars(select(SourceDocument).order_by(SourceDocument.id)).all()
        assert [(d.party_id, d.bundle_file) for d in rows] == [
            (1, "pp.md"), (4, "pp.md"), (4, "upn.md"), (2, "psoe.md"), (3, "psoe.md"),
            (3, "psc.md"),
        ]
        # D1: one row per Party x document, sharing the file and its hash.
        assert rows[0].content_hash == rows[1].content_hash
        assert rows[0].content_hash == hashlib.sha256(PP.content()).hexdigest()
        assert [p.text for p in rows[1].pages] == list(PP.pages)
        assert all(d.status is SourceDocumentStatus.PARSED for d in rows)
    assert _check(migrated_engine, directory) == []


def test_format_2_reimport_changes_nothing(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    before = _snapshot_v2(migrated_engine)

    report = _import(migrated_engine, directory)

    assert report.candidature_source_change == "unchanged"
    assert all(not c.added and not c.removed and not c.party_created
               for c in report.candidatures)
    assert {d.status for d in report.documents} == {DocumentStatus.UNCHANGED}
    assert all(not d.scope_added and not d.scope_removed for d in report.documents)
    assert report.new_documents == []
    assert _snapshot_v2(migrated_engine) == before


def test_format_2_party_without_documents_and_no_documents_at_all(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    directory = write_bundle_v2(tmp_path, documents=[])
    report = _import(migrated_engine, directory)
    assert report.documents == [] and len(report.candidatures) == 5
    assert _state(migrated_engine)[1] == {}
    assert _check(migrated_engine, directory) == []


def test_candidature_and_scope_changes(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    psc = dataclasses.replace(V2_PSC, constituencies=["08", "17", "25"])
    small = dataclasses.replace(V2_SMALL, constituencies=["08", "28"])
    doc_psc = dataclasses.replace(DOC_PSC, constituencies=["08", "17"])
    parties = [V2_PP, V2_PSOE, psc, V2_UPN, small]
    documents = [d for d in V2_DOCUMENTS if d.file != "psc.md"] + [doc_psc]
    write_bundle_v2(tmp_path, parties, documents)
    before = _snapshot_v2(migrated_engine)

    report = _import(migrated_engine, directory)

    assert [(c.short_name, c.added, c.removed) for c in report.candidatures] == [
        ("PP", (), ()), ("PSOE", (), ()), ("PSC", (), ("43",)), ("UPN-PP", (), ()),
        ("PACMA", ("08",), ()),
    ]
    assert [(d.document_id, d.status, d.scope_added, d.scope_removed)
            for d in report.documents] == [
        (1, DocumentStatus.UNCHANGED, (), ()),
        (2, DocumentStatus.UNCHANGED, (), ()),
        (3, DocumentStatus.UNCHANGED, (), ()),
        (4, DocumentStatus.UNCHANGED, (), ()),
        (5, DocumentStatus.UNCHANGED, (), ("43",)),
        (6, DocumentStatus.UNCHANGED, ("17",), ()),
    ]
    candidatures, scopes = _state(migrated_engine)
    assert candidatures[3] == ("08", "17", "25") and candidatures[5] == ("08", "28")
    assert scopes[5] == ("08", "17", "25") and scopes[6] == ("08", "17")
    after = _snapshot_v2(migrated_engine)
    # No Source Document, page or run changes for a candidature or scope change alone.
    for table in ("elections", "parties", "source_documents", "source_document_pages",
                  "pipeline_runs"):
        assert after[table] == before[table], table
    assert _check(migrated_engine, directory) == []


def test_a_changed_file_gets_a_replacement_with_the_new_scope(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    psoe_v2 = dataclasses.replace(DOC_PSOE, pages=["Medidas nuevas."])
    psc = dataclasses.replace(V2_PSC, constituencies=["08", "17", "25"])
    documents = [psoe_v2 if d.file == "psoe.md" else d for d in V2_DOCUMENTS]
    write_bundle_v2(tmp_path, [V2_PP, V2_PSOE, psc, V2_UPN, V2_SMALL], documents)

    report = _import(migrated_engine, directory)

    replaced = [(d.short_name, d.document_id, d.replaced_document_id, d.scope, d.scope_added)
                for d in report.documents if d.status is DocumentStatus.REPLACED]
    assert replaced == [("PSOE", 7, 4, 48, NOT_CATALONIA), ("PSC", 8, 5, 3, ("08", "17", "25"))]
    assert report.new_documents == [7, 8]
    _, scopes = _state(migrated_engine)
    # The old rows keep their old scope (Evidence of older Dataset Versions).
    assert scopes[4] == NOT_CATALONIA and scopes[5] == CATALONIA
    assert scopes[7] == NOT_CATALONIA and scopes[8] == ("08", "17", "25")
    with Session(migrated_engine) as s:
        assert (s.get(SourceDocument, 4).replaced_by_id, s.get(SourceDocument, 5).replaced_by_id) == (
            7, 8
        )
    assert _check(migrated_engine, directory) == []


def test_a_party_removed_from_the_manifest_loses_only_its_candidatures(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    write_bundle_v2(tmp_path, [V2_PP, V2_PSOE, V2_PSC, V2_UPN], V2_DOCUMENTS)
    before = _snapshot_v2(migrated_engine)

    report = _import(migrated_engine, directory)

    assert report.left_alone == [("PACMA", 5)]
    assert report.removed_candidatures == [("PACMA", 5, ("28",))]
    candidatures, _ = _state(migrated_engine)
    assert 5 not in candidatures
    after = _snapshot_v2(migrated_engine)
    assert after["parties"] == before["parties"]
    assert after["source_documents"] == before["source_documents"]
    assert _check(migrated_engine, directory) == []


def test_live_mode_queues_only_for_documents(
    migrated_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ideology_app.config import llm_settings
    from ideology_app.pipeline import queue_run_for_source_change

    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    directory = write_bundle_v2(tmp_path)

    def _live_import() -> list[int | None]:
        with session_scope(migrated_engine) as s:
            report = import_bundle(s, read_bundle(directory))
            return [
                queue_run_for_source_change(
                    s, d, generation_mode=GenerationMode.LIVE, llm=llm_settings()
                ).run_id
                for d in report.new_documents
            ]

    assert set(_live_import()) == {1}
    small = dataclasses.replace(V2_SMALL, constituencies=["08", "28"])
    write_bundle_v2(tmp_path, [V2_PP, V2_PSOE, V2_PSC, V2_UPN, small], V2_DOCUMENTS)
    assert _live_import() == []


# --- Scenario 6: legacy format-1 rows reused by a format-2 manifest (D2) ---------------


def _publish_version(engine: Engine) -> None:
    from ideology_app.models import (
        DatasetVersion,
        DatasetVersionStatus,
        PipelineRun,
        PipelineRunStatus,
        Statement,
    )

    with session_scope(engine) as s:
        s.get(Election, 1).status = ElectionStatus.ACTIVE
        s.add(PipelineRun(id=1, election_id=1, status=PipelineRunStatus.PASSED,
                          llm_provider="fake", llm_model="fake-model",
                          generation_mode=GenerationMode.PRECOMPUTED, prompt_versions={}))
        s.flush()
        s.add(DatasetVersion(id=1, election_id=1, pipeline_run_id=1,
                             status=DatasetVersionStatus.PUBLISHED,
                             created_at=dt.datetime(2026, 11, 1, 8, 0, 0)))
        s.flush()
        s.add(Statement(id=1, dataset_version_id=1, position=1, text="Primera.", topic="housing"))
        s.flush()
        s.add_all([
            PartyPosition(statement_id=1, party_id=1, value=2, evidence_source_document_id=1,
                          evidence_quote="Propuestas sobre vivienda y alquiler.",
                          evidence_page=1, evidence_url="https://example.org/pp.pdf"),
            PartyPosition(statement_id=1, party_id=2, value=-1, evidence_source_document_id=2,
                          evidence_quote="Medidas fiscales y de empleo.", evidence_page=1),
        ])


def test_legacy_rows_are_reused_and_the_dataset_version_is_unchanged(
    migrated_engine: Engine, db_url: str, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient
    from logo_factory import svg

    from ideology_app.main import create_app

    logo = ("logos/pp.svg", svg())
    legacy = write_bundle(tmp_path, [dataclasses.replace(PP, logo=logo), PSOE])
    _import(migrated_engine, legacy)
    _publish_version(migrated_engine)
    with TestClient(create_app(db_url)) as client:
        version_before = client.get("/api/v1/dataset-versions/1")
        logo_before = client.get("/api/v1/parties/1/logo")
    assert version_before.status_code == 200 and logo_before.status_code == 200
    assert b'"logo_url"' in version_before.content
    parties_before = _snapshot_v2(migrated_engine)["parties"]
    documents_before = _snapshot_v2(migrated_engine)["source_documents"]

    # The same directory becomes a format-2 bundle: PP and PSOE reused, UPN-PP and
    # PSC new; pp.md and psoe.md keep their bytes (DocumentSpec == PartySpec content).
    parties = [CandidatureSpec("PP", "Partido Popular", "all", logo=logo),
               V2_PSOE, V2_PSC, V2_UPN]
    report = _import(migrated_engine, write_bundle_v2(tmp_path, parties, V2_DOCUMENTS))

    assert [(c.short_name, c.party_id, c.party_created) for c in report.candidatures] == [
        ("PP", 1, False), ("PSOE", 2, False), ("PSC", 3, True), ("UPN-PP", 4, True)
    ]
    assert [(d.file, d.short_name, d.status, d.document_id) for d in report.documents] == [
        ("pp.md", "PP", DocumentStatus.UNCHANGED, 1),
        ("pp.md", "UPN-PP", DocumentStatus.ADDED, 3),
        ("upn.md", "UPN-PP", DocumentStatus.ADDED, 4),
        ("psoe.md", "PSOE", DocumentStatus.UNCHANGED, 2),
        ("psoe.md", "PSC", DocumentStatus.ADDED, 5),
        ("psc.md", "PSC", DocumentStatus.ADDED, 6),
    ]
    after = _snapshot_v2(migrated_engine)
    assert after["parties"][:2] == parties_before
    assert after["source_documents"][:2] == documents_before
    _, scopes = _state(migrated_engine)
    assert scopes[1] == ALL and scopes[2] == NOT_CATALONIA
    with TestClient(create_app(db_url)) as client:
        version_after = client.get("/api/v1/dataset-versions/1")
        logo_after = client.get("/api/v1/parties/1/logo")
    assert version_after.content == version_before.content
    assert (logo_after.status_code, logo_after.content) == (
        logo_before.status_code, logo_before.content
    )
    assert _check(migrated_engine, legacy) == []


def test_a_legacy_party_left_out_stays_without_candidatures(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    _import(migrated_engine, write_bundle(tmp_path, [PP, PSOE]))
    documents = [DocumentSpec("pp.md", "PP", PP.pages, ["PP"], source_url=PP.source_url)]
    directory = write_bundle_v2(tmp_path, [CandidatureSpec("PP", "Partido Popular", "all")],
                                documents)
    (directory / "psoe.md").unlink()

    report = _import(migrated_engine, directory)

    assert report.left_alone == [("PSOE", 2)] and report.removed_candidatures == []
    candidatures, scopes = _state(migrated_engine)
    assert candidatures == {1: ALL} and scopes == {1: ALL}
    assert _check(migrated_engine, directory) == []


# --- Scenario 7: refusals before any write ------------------------------------------


def _refused(engine: Engine, directory: Path, error: type[Exception], message: str) -> None:
    before = _snapshot_v2(engine)
    with pytest.raises(error) as caught:
        _import(engine, directory)
    assert message in str(caught.value), str(caught.value)
    assert _snapshot_v2(engine) == before


@pytest.mark.parametrize(
    ("seed", "message"),
    [
        ({"parties": (("PSC", "Socialistes"),)},
         "party PSC (id 1) exists with name 'Socialistes', but the bundle names it "
         "'Partit dels Socialistes de Catalunya'; import into a fresh database"),
        ({"parties": (("PSC-PSOE", "Partit dels Socialistes de Catalunya"),)},
         "party 'Partit dels Socialistes de Catalunya' exists as PSC-PSOE (id 1), but the "
         "bundle names it PSC"),
        ({"election_name": "Generales 2023"},
         "election es-general-2023-07-23 (id 1) exists with name 'Generales 2023'"),
    ],
)
def test_format_2_name_conflicts_are_refused(
    migrated_engine: Engine, tmp_path: Path, seed: dict[str, Any], message: str
) -> None:
    _seed_other(migrated_engine, **seed)
    _refused(migrated_engine, write_bundle_v2(tmp_path), BundleConflictError, message)


def test_format_2_non_bundle_row_is_refused(migrated_engine: Engine, tmp_path: Path) -> None:
    _seed_other(migrated_engine, parties=(("PP", "Partido Popular"),))
    pdf = tmp_path / "pp.pdf"
    pdf.write_bytes(make_text_pdf(["Programa."]))
    with session_scope(migrated_engine) as s:
        add_uploaded_document(s, party_id=1, file_path=pdf, files_dir=tmp_path / "stored")
    _refused(migrated_engine, write_bundle_v2(tmp_path / "b"), BundleConflictError,
             "party PP (id 1) has source document 1, which was not imported from a bundle")


def test_a_document_no_longer_listed_is_refused(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    (directory / "psc.md").unlink()
    write_bundle_v2(tmp_path, V2_PARTIES, [d for d in V2_DOCUMENTS if d.file != "psc.md"])
    _refused(migrated_engine, directory, BundleConflictError,
             "party PSC (id 3) has current source document 6 from psc.md, which "
             "election.toml no longer lists for it")


def test_a_legacy_document_left_out_for_a_listed_party_is_refused(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    _import(migrated_engine, write_bundle(tmp_path, [PP, PSOE]))
    directory = write_bundle_v2(tmp_path, [V2_PP, V2_PSOE], [])
    for file in ("pp.md", "psoe.md"):
        (directory / file).unlink()
    _refused(migrated_engine, directory, BundleConflictError,
             "party PP (id 1) has current source document 1 from pp.md")


def test_format_2_reverted_file_is_refused(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    changed = dataclasses.replace(DOC_PSC, pages=["Nuevo programa."])
    write_bundle_v2(tmp_path, V2_PARTIES, [d for d in V2_DOCUMENTS if d.file != "psc.md"]
                    + [changed])
    _import(migrated_engine, directory)
    write_bundle_v2(tmp_path)
    _refused(migrated_engine, directory, BundleConflictError,
             "party PSC (id 3): psc.md has the same content as older source document 6 "
             "(a reverted file)")


def test_bad_candidatures_url_is_refused(migrated_engine: Engine, tmp_path: Path) -> None:
    manifest = manifest_v2_text(url="ftp://www.boe.es/x")
    _refused(migrated_engine, write_bundle_v2(tmp_path, manifest=manifest), InvalidInputError,
             "election.toml: [candidatures] url: invalid URL 'ftp://www.boe.es/x'")


def test_bad_document_source_url_is_refused(migrated_engine: Engine, tmp_path: Path) -> None:
    bad = dataclasses.replace(DOC_PSC, source_url="ftp://example.org/psc.pdf")
    documents = [d for d in V2_DOCUMENTS if d.file != "psc.md"] + [bad]
    _refused(migrated_engine, write_bundle_v2(tmp_path, V2_PARTIES, documents),
             InvalidInputError, "psc.md: source_url: invalid URL")


# --- Scenario 8: checks report candidature and scope problems -------------------------


def test_check_reports_missing_coverage(migrated_engine: Engine, tmp_path: Path) -> None:
    pp = CandidatureSpec("PP", "Partido Popular", [c for c in ALL if c not in ("51", "52")])
    directory = write_bundle_v2(tmp_path, [pp], [])
    _import(migrated_engine, directory)
    assert _check(migrated_engine, directory) == [
        "Constituency 51 (Ceuta) has no candidature in election.toml",
        "Constituency 52 (Melilla) has no candidature in election.toml",
    ]


def test_check_on_an_empty_database_v2(migrated_engine: Engine, tmp_path: Path) -> None:
    assert _check(migrated_engine, write_bundle_v2(tmp_path)) == [
        "election es-general-2023-07-23 not found"
    ]


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        ("DELETE FROM candidatures WHERE party_id = 3 AND constituency_code = '25'",
         "party PSC (id 3): candidatures differ: missing 25; extra none"),
        ("INSERT INTO candidatures VALUES (5, '08'), (5, '17')",
         "party PACMA (id 5): candidatures differ: missing none; extra 08, 17"),
        ("INSERT INTO source_document_constituencies VALUES (6, '17')",
         "party PSC (id 3): source document 6: scope differs: missing none; extra 17"),
        ("DELETE FROM source_document_constituencies WHERE source_document_id = 2",
         "party UPN-PP (id 4): source document 2: scope differs: missing 31; extra none"),
        ("UPDATE elections SET candidatures_source = 'BOE'",
         "election es-general-2023-07-23 (id 1): candidatures source differs from "
         "election.toml"),
        ("UPDATE elections SET candidatures_source_url = NULL",
         "election es-general-2023-07-23 (id 1): candidatures url differs from election.toml"),
        ("INSERT INTO parties (election_id, name, short_name) VALUES (1, 'Otro', 'OT'); "
         "INSERT INTO candidatures VALUES (6, '28')",
         "party OT (id 6) is not in election.toml but has candidatures: 28"),
    ],
)
def test_check_finds_each_v2_divergence(
    migrated_engine: Engine, tmp_path: Path, statement: str, problem: str
) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    with migrated_engine.begin() as conn:
        for part in statement.split("; "):
            conn.execute(sa.text(part))
    assert _check(migrated_engine, directory) == [problem]


def test_check_finds_an_unlisted_current_row(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("UPDATE source_documents SET bundle_file = 'otro.md' WHERE id = 6"))
    assert _check(migrated_engine, directory) == [
        "party PSC (id 3): current source document 6 from otro.md is not listed for it in "
        "election.toml",
        "party PSC (id 3): no current source document for psc.md",
    ]


def test_check_finds_a_changed_v2_file(migrated_engine: Engine, tmp_path: Path) -> None:
    directory = write_bundle_v2(tmp_path)
    _import(migrated_engine, directory)
    (directory / "upn.md").write_bytes(
        dataclasses.replace(DocumentSpec("upn.md", "UPN-PP", ["Otro."], ["UPN-PP"])).content()
    )
    assert _check(migrated_engine, directory) == [
        "party UPN-PP (id 4): source document 3: content_hash differs from the SHA-256 of upn.md",
        "party UPN-PP (id 4): source document 3: page 1 text differs from upn.md",
    ]
