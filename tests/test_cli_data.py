"""``ideology source extract`` and ``ideology data import|check`` (source-text-bundle).

Scenarios 1, 2, 4, 5, 6, 8 and 12 through the CLI. Tests never call a real LLM
(offline guard) and build every PDF and bundle in ``tmp_path``.
"""

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import (
    PP,
    PSOE,
    SLUG,
    V2_DOCUMENTS,
    V2_PP,
    V2_PSC,
    V2_PSOE,
    V2_SMALL,
    V2_UPN,
    CandidatureSpec,
    manifest_text,
    write_bundle,
    write_bundle_v2,
)
from click.testing import CliRunner, Result
from pdf_factory import blank_pdf, encrypt_pdf, make_text_pdf
from pipeline_fixtures import offline_guard

from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.db import make_engine
from ideology_app.ingestion_ledger import LEDGER_NAME
from ideology_app.pdf_text import EXTRACTOR, NO_TEXT_LAYER, extract_pages
from ideology_app.source_bundle import parse_source_text

PSOE_V2 = dataclasses.replace(PSOE, pages=["Medidas nuevas de empleo.", "Otra página.", "Tres."])
SCENARIO_1_PAGES = ["Programa electoral\nVivienda.", None, "<!-- page 2 -->\n\\<!-- page 9 -->"]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    offline_guard(monkeypatch)
    monkeypatch.setenv("SOURCE_FILES_DIR", str(tmp_path / "stored"))


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def migrated(run) -> None:
    result = run("db", "upgrade")
    assert result.exit_code == 0, result.output


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return write_bundle(tmp_path / "data" / "elections")


def _snapshot(db_url: str) -> dict[str, list[tuple[Any, ...]]]:
    tables = ("elections", "parties", "source_documents", "source_document_pages", "pipeline_runs")
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return {
                t: [tuple(r) for r in conn.execute(sa.text(f"SELECT * FROM {t} ORDER BY 1"))]
                for t in tables
            }
    finally:
        engine.dispose()


# --- Scenario 1: extract a PDF -------------------------------------------------


def test_extract_writes_a_canonical_file(run, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(make_text_pdf(SCENARIO_1_PAGES))
    out = tmp_path / "pp.md"

    result = run("source", "extract", str(pdf), "--party", "PP",
                 "--url", "https://example.org/p.pdf", "--out", str(out))

    assert result.exit_code == 0, result.output
    data = out.read_bytes()
    assert result.output == f"Wrote {out}: 3 pages, {len(data)} bytes\n"
    parsed = parse_source_text(data, name="pp.md")
    assert list(parsed.pages) == extract_pages(pdf.read_bytes())
    assert parsed.pages[1] == ""
    assert (parsed.party, parsed.source_url, parsed.page_count, parsed.extractor) == (
        "PP", "https://example.org/p.pdf", 3, EXTRACTOR
    )
    assert parsed.pdf_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest()
    body = data.split(b"\n---\n", 1)[1]
    assert b"<!-- page 2 -->\n\n<!-- page 3 -->\n" in body
    assert b"\n\\<!-- page 2 -->\n\\\\<!-- page 9 -->\n" in body
    assert not (tmp_path / "test.db").exists()  # no database needed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifesto.pdf", "pp.md"]


def test_extract_without_url_has_no_url_line(run, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(make_text_pdf(["Texto."]))
    result = run("source", "extract", str(pdf), "--party", "PSOE", "--out", str(tmp_path / "x.md"))
    assert result.exit_code == 0, result.output
    data = (tmp_path / "x.md").read_bytes()
    assert b"source_url" not in data
    assert parse_source_text(data, name="x.md").source_url is None


def test_extract_force_overwrites(run, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(make_text_pdf(["Texto."]))
    out = tmp_path / "pp.md"
    out.write_bytes(b"old")
    result = run("source", "extract", str(pdf), "--party", "PP", "--out", str(out), "--force")
    assert result.exit_code == 0, result.output
    assert parse_source_text(out.read_bytes(), name="pp.md").pages == ("Texto.",)


# --- Scenario 2: extract refuses bad input and writes nothing -------------------


@pytest.mark.parametrize(
    ("content", "args", "message"),
    [
        (blank_pdf(2), (), NO_TEXT_LAYER),
        (encrypt_pdf(make_text_pdf(["Texto."]), "secret"), (), "PDF is encrypted"),
        (b"%PDF-1.4\nnot really a pdf", (), "could not read PDF"),
        (b"plain text", (), "is not a PDF"),
        (b"", (), "is empty"),
        (make_text_pdf(["Texto."]), ("--url", "ftp://example.org/p.pdf"), "invalid URL"),
        (make_text_pdf(["Texto."]), ("--url", "https://user:pw@example.org/p.pdf"),
         "must not contain credentials"),
        (make_text_pdf(["Texto."]), ("--party", " "), "party must not be empty"),
    ],
)
def test_extract_refuses_bad_input(
    run, tmp_path: Path, content: bytes, args: tuple[str, ...], message: str
) -> None:
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(content)
    out = tmp_path / "pp.md"
    party = () if "--party" in args else ("--party", "PP")

    result = run("source", "extract", str(pdf), *party, *args, "--out", str(out))

    assert result.exit_code == 1, result.output
    assert message in result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.pdf"]


def test_extract_missing_pdf(run, tmp_path: Path) -> None:
    result = run("source", "extract", str(tmp_path / "nope.pdf"), "--party", "PP",
                 "--out", str(tmp_path / "pp.md"))
    assert result.exit_code == 1 and "not found" in result.output
    assert list(tmp_path.iterdir()) == []


def test_extract_existing_out_without_force(run, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(make_text_pdf(["Texto."]))
    out = tmp_path / "pp.md"
    out.write_bytes(b"keep me")

    result = run("source", "extract", str(pdf), "--party", "PP", "--out", str(out))

    assert result.exit_code == 1
    assert f"Error: {out} exists; pass --force to overwrite" in result.output
    assert out.read_bytes() == b"keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["manifesto.pdf", "pp.md"]


def test_extract_into_a_missing_directory(run, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(make_text_pdf(["Texto."]))
    result = run("source", "extract", str(pdf), "--party", "PP",
                 "--out", str(tmp_path / "missing" / "pp.md"))
    assert result.exit_code == 1 and "not found" in result.output


# --- Scenarios 4 and 5: import, then re-import -------------------------------------


def test_import_then_reimport(run, migrated, bundle: Path, db_url: str, tmp_path: Path) -> None:
    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Party PP: created (id 1); source document 1: added (3 pages)\n"
        "Party PSOE: created (id 2); source document 2: added (2 pages)\n"
        f"Imported election {SLUG} (id 1): 2 added, 0 replaced, 0 unchanged\n"
    )
    assert not (tmp_path / "stored").exists()
    before = _snapshot(db_url)

    again = run("data", "import", str(bundle))

    assert again.exit_code == 0, again.output
    assert again.output == (
        "Party PP: exists (id 1); source document 1: unchanged\n"
        "Party PSOE: exists (id 2); source document 2: unchanged\n"
        f"Imported election {SLUG} (id 1): 0 added, 0 replaced, 2 unchanged\n"
    )
    assert _snapshot(db_url) == before

    listed = run("source", "list", "--party", "2")
    assert listed.exit_code == 0, listed.output
    header, row = (line.split("\t") for line in listed.output.splitlines())
    assert header[-1] == "bundle_file"
    assert (row[1], row[2], row[5], row[6], row[-1]) == ("upload", "parsed", "psoe.md", "", "psoe.md")


def test_live_reimport_queues_nothing(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    before = _snapshot(db_url)

    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert "Queued" not in result.output and "queued" not in result.output
    assert _snapshot(db_url) == before


# --- Scenario 6: a changed file registers a replacement ----------------------------


def test_replacement_in_precomputed_queues_nothing(
    run, migrated, bundle: Path, db_url: str
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    (bundle / "psoe.md").write_bytes(PSOE_V2.content())

    result = run("data", "import", str(bundle))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Party PP: exists (id 1); source document 1: unchanged\n"
        "Party PSOE: exists (id 2); source document 3: replaces source document 2 (3 pages)\n"
        f"Imported election {SLUG} (id 1): 0 added, 1 replaced, 1 unchanged\n"
    )
    assert _snapshot(db_url)["pipeline_runs"] == []


def test_live_import_queues_one_run_and_joins_it(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    first = run("data", "import", str(bundle))

    assert first.exit_code == 0, first.output
    assert first.output.endswith(
        f"Imported election {SLUG} (id 1): 2 added, 0 replaced, 0 unchanged\n"
        "Queued pipeline run 1 for election 1 (generation mode live)\n"
    )
    assert first.output.count("pipeline run") == 1
    (bundle / "psoe.md").write_bytes(PSOE_V2.content())

    second = run("data", "import", str(bundle))

    assert second.exit_code == 0, second.output
    assert second.output.endswith("Pipeline run 1 is already queued for election 1\n")
    runs = _snapshot(db_url)["pipeline_runs"]
    assert len(runs) == 1


def test_live_with_invalid_provider_writes_nothing(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    before = _snapshot(db_url)
    result = run("data", "import", str(bundle))
    assert result.exit_code == 1
    assert _snapshot(db_url) == before


# --- Scenario 8: malformed input imports nothing ---------------------------------


def _break_psoe_marker(directory: Path) -> None:
    data = (directory / "psoe.md").read_bytes()
    (directory / "psoe.md").write_bytes(data.replace(b"<!-- page 2 -->", b"<!-- page 3 -->"))


MALFORMED = {
    "missing manifest": lambda d: (d / "election.toml").unlink(),
    "bad TOML": lambda d: (d / "election.toml").write_text("format = = 1\n"),
    "duplicate short names": lambda d: (d / "election.toml").write_text(
        manifest_text([PP, dataclasses.replace(PSOE, short_name="PP")])
    ),
    "listed file missing": lambda d: (d / "psoe.md").unlink(),
    "unlisted file": lambda d: (d / "upn.md").write_bytes(PP.content()),
    "a pdf": lambda d: (d / "pp.pdf").write_bytes(b"%PDF-1.4"),
    "party mismatch": lambda d: (d / "psoe.md").write_bytes(
        dataclasses.replace(PSOE, short_name="PSC").content()
    ),
    "bad marker in a later file": _break_psoe_marker,
    "BOM": lambda d: (d / "psoe.md").write_bytes(b"\xef\xbb\xbf" + PSOE.content()),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
@pytest.mark.parametrize("prior_import", [False, True])
def test_malformed_bundle_imports_nothing(
    run, migrated, bundle: Path, db_url: str, case: str, prior_import: bool
) -> None:
    if prior_import:
        (bundle / "pp.md").write_bytes(dataclasses.replace(PP, pages=["Antes."]).content())
        assert run("data", "import", str(bundle)).exit_code == 0
        (bundle / "pp.md").write_bytes(PP.content())  # a change that would be imported
    before = _snapshot(db_url)
    MALFORMED[case](bundle)

    result = run("data", "import", str(bundle))

    assert result.exit_code == 1, result.output
    assert result.output.startswith(f"Error: {bundle}"), result.output
    assert result.output.count(":") >= 3
    assert _snapshot(db_url) == before


def test_slug_mismatch_imports_nothing(run, migrated, tmp_path: Path, db_url: str) -> None:
    directory = write_bundle(tmp_path, slug="es-general-2023")
    result = run("data", "import", str(directory))
    assert result.exit_code == 1
    assert "expected 'es-general-2023-07-23'" in result.output
    assert _snapshot(db_url)["elections"] == []


def test_database_phase_error_rolls_everything_back(
    run, migrated, bundle: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ideology_app import bundle_import
    from ideology_app.elections import InvalidInputError

    real = bundle_import.set_parsed_pages
    calls: list[int] = []

    def _fail_on_second(document: Any, pages: Any) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise InvalidInputError("simulated failure while writing")
        real(document, pages)

    monkeypatch.setattr(bundle_import, "set_parsed_pages", _fail_on_second)

    result = run("data", "import", str(bundle))

    assert result.exit_code == 1
    assert "simulated failure while writing" in result.output
    assert all(rows == [] for rows in _snapshot(db_url).values())


def test_conflict_with_a_source_add_document_imports_nothing(
    run, migrated, bundle: Path, db_url: str
) -> None:
    assert run("election", "create", "--country", "ES", "--type", "general",
               "--date", "2023-07-23", "--name", "Elecciones generales 2023").exit_code == 0
    assert run("party", "add", "--election", "1", "--name", "Partido Popular",
               "--short-name", "PP").exit_code == 0
    pdf = Path(db_url.removeprefix("sqlite:///")).parent / "old.pdf"
    pdf.write_bytes(make_text_pdf(["Programa antiguo."]))
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    before = _snapshot(db_url)

    result = run("data", "import", str(bundle))

    assert result.exit_code == 1
    assert "party PP (id 1) has source document 1" in result.output
    assert "import into a fresh database" in result.output
    assert _snapshot(db_url) == before


def test_left_alone_party_is_reported(run, migrated, bundle: Path) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    assert run("party", "add", "--election", "1", "--name", "Unión del Pueblo Navarro",
               "--short-name", "UPN").exit_code == 0
    result = run("data", "import", str(bundle))
    assert result.exit_code == 0, result.output
    assert "Party UPN (id 3) is not in the bundle; left unchanged\n" in result.output


def test_import_needs_a_migrated_database(run, bundle: Path) -> None:
    result = run("data", "import", str(bundle))
    assert result.exit_code == 1 and NOT_INITIALISED in result.output


# --- Scenario 12: data check ------------------------------------------------------


def test_check_matches_and_writes_nothing(run, migrated, bundle: Path, db_url: str) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    before = _snapshot(db_url)

    result = run("data", "check", str(bundle))

    assert result.exit_code == 0, result.output
    assert result.output == f"Database matches bundle {SLUG}: 2 documents\n"
    assert _snapshot(db_url) == before


def test_check_reports_a_changed_page(run, migrated, bundle: Path, db_url: str) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "UPDATE source_document_pages SET text = 'x' "
                "WHERE source_document_id = 1 AND page_number = 3"
            ))
    finally:
        engine.dispose()

    result = run("data", "check", str(bundle))

    assert result.exit_code == 1
    assert "party PP (id 1): source document 1: page 3 text differs from pp.md" in result.output
    assert f"database does not match bundle {SLUG}: 1 problems" in result.output


def test_check_reports_a_file_replaced_without_import(run, migrated, bundle: Path) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    (bundle / "psoe.md").write_bytes(PSOE_V2.content())
    result = run("data", "check", str(bundle))
    assert result.exit_code == 1
    assert "party PSOE (id 2): source document 2: content_hash differs" in result.output


def test_check_reports_a_source_add_document(
    run, migrated, bundle: Path, tmp_path: Path
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    pdf = tmp_path / "anexo.pdf"
    pdf.write_bytes(make_text_pdf(["Anexo."]))
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    result = run("data", "check", str(bundle))
    assert result.exit_code == 1
    assert "party PP (id 1): source document 3 was not imported from a bundle" in result.output


def test_check_on_an_empty_database(run, migrated, bundle: Path) -> None:
    result = run("data", "check", str(bundle))
    assert result.exit_code == 1
    assert f"election {SLUG} not found" in result.output


# --- Manifest format 2 (constituencies-and-candidatures) ----------------------------


def _sql(db_url: str, *statements: str) -> None:
    engine = make_engine(db_url)
    try:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


@pytest.fixture
def bundle_v2(tmp_path: Path) -> Path:
    return write_bundle_v2(tmp_path / "data" / "elections")


def test_format_2_import_reimport_and_check(run, migrated, bundle_v2: Path, db_url: str) -> None:
    result = run("data", "import", str(bundle_v2))

    assert result.exit_code == 0, result.output
    assert result.output == (
        "Party PP (id 1): created, 52 Constituencies (+52 -0)\n"
        "Party PSOE (id 2): created, 48 Constituencies (+48 -0)\n"
        "Party PSC (id 3): created, 4 Constituencies (+4 -0)\n"
        "Party UPN-PP (id 4): created, 1 Constituency (+1 -0)\n"
        "Party PACMA (id 5): created, 1 Constituency (+1 -0)\n"
        "Document pp.md for PP: added source document 1 (3 pages), scope 52 Constituencies "
        "(+52 -0)\n"
        "Document pp.md for UPN-PP: added source document 2 (3 pages), scope 1 Constituency "
        "(+1 -0)\n"
        "Document upn.md for UPN-PP: added source document 3 (1 pages), scope 1 Constituency "
        "(+1 -0)\n"
        "Document psoe.md for PSOE: added source document 4 (2 pages), scope 48 Constituencies "
        "(+48 -0)\n"
        "Document psoe.md for PSC: added source document 5 (2 pages), scope 4 Constituencies "
        "(+4 -0)\n"
        "Document psc.md for PSC: added source document 6 (1 pages), scope 1 Constituency "
        "(+1 -0)\n"
        "Candidatures source: set\n"
        f"Imported election {SLUG} (id 1): 5 parties, 106 candidatures (+106 -0), "
        "6 source documents: 6 added, 0 replaced, 0 unchanged\n"
    )

    small = CandidatureSpec("PACMA", "Partido Animalista", ["08", "28"])
    write_bundle_v2(bundle_v2.parent, [V2_PP, V2_PSOE, V2_PSC, V2_UPN, small], V2_DOCUMENTS)
    again = run("data", "import", str(bundle_v2))

    assert again.exit_code == 0, again.output
    assert "Party PACMA (id 5): exists, 2 Constituencies (+1 -0)\n" in again.output
    assert "Document psc.md for PSC: unchanged (source document 6), scope 1 Constituency " \
           "(+0 -0)\n" in again.output
    assert "Candidatures source: unchanged\n" in again.output
    assert again.output.endswith(
        f"Imported election {SLUG} (id 1): 5 parties, 107 candidatures (+1 -0), "
        "6 source documents: 0 added, 0 replaced, 6 unchanged\n"
    )
    before = _snapshot(db_url)

    check = run("data", "check", str(bundle_v2))

    assert check.exit_code == 0, check.output
    assert check.output == (
        f"Database matches bundle {SLUG}: 5 parties, 107 candidatures, 4 documents\n"
    )
    assert _snapshot(db_url) == before


def test_format_2_import_reports_unlisted_parties(run, migrated, bundle_v2: Path) -> None:
    assert run("data", "import", str(bundle_v2)).exit_code == 0
    write_bundle_v2(bundle_v2.parent, [V2_PP, V2_PSOE, V2_PSC, V2_UPN], V2_DOCUMENTS)

    result = run("data", "import", str(bundle_v2))

    assert result.exit_code == 0, result.output
    assert (
        "Party PACMA (id 5) is not in the bundle; candidatures removed (28); "
        "row and documents left unchanged\n"
    ) in result.output
    assert "4 parties, 105 candidatures (+0 -1)" in result.output


def test_format_2_check_reports_coverage_and_differences(
    run, migrated, tmp_path: Path, db_url: str
) -> None:
    psoe = CandidatureSpec("PSOE", "Partido Socialista Obrero Español",
                           [f"{n:02d}" for n in range(1, 51)])
    directory = write_bundle_v2(tmp_path / "data" / "elections", [psoe], [])
    assert run("data", "import", str(directory)).exit_code == 0
    _sql(db_url, "DELETE FROM candidatures WHERE constituency_code = '28'")

    result = run("data", "check", str(directory))

    assert result.exit_code == 1
    assert result.output == (
        "Error: Constituency 51 (Ceuta) has no candidature in election.toml\n"
        "Error: Constituency 52 (Melilla) has no candidature in election.toml\n"
        "Error: party PSOE (id 1): candidatures differ: missing 28; extra none\n"
        f"Error: database does not match bundle {SLUG}: 3 problems\n"
    )


def test_format_2_bad_constituency_fails_import_and_check(
    run, migrated, tmp_path: Path, db_url: str
) -> None:
    bad = dataclasses.replace(V2_SMALL, constituencies=["53"])
    directory = write_bundle_v2(
        tmp_path / "data" / "elections", [V2_PP, V2_PSOE, V2_PSC, V2_UPN, bad], V2_DOCUMENTS
    )
    for command in ("import", "check"):
        result = run("data", command, str(directory))
        assert result.exit_code == 1
        assert "election.toml:36: unknown Constituency '53'" in result.output
    assert _snapshot(db_url)["elections"] == []


def test_check_reports_a_seed_difference(run, migrated, bundle: Path, db_url: str) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    _sql(db_url, "UPDATE constituencies SET name = 'Gerona' WHERE code = '17'")

    result = run("data", "check", str(bundle))

    assert result.exit_code == 1
    assert result.output == (
        "Error: Constituency 17 is named 'Gerona' in the constituencies table, not 'Girona'\n"
        f"Error: database does not match bundle {SLUG}: 1 problems\n"
    )


def test_db_check_reports_seed_and_candidature_problems(
    run, migrated, bundle_v2: Path, db_url: str
) -> None:
    assert run("data", "import", str(bundle_v2)).exit_code == 0
    assert run("db", "check").output == "Safe to commit: yes\n"
    _sql(
        db_url,
        "DELETE FROM source_document_constituencies WHERE source_document_id = 6",
        "UPDATE constituencies SET name = 'Lérida' WHERE code = '25'",
    )

    result = run("db", "check")

    assert result.exit_code == 1
    assert result.output == (
        "Error: Constituency 25 is named 'Lérida' in the constituencies table, not 'Lleida'\n"
        f"Error: election 1 ({SLUG}): party PSC (id 3): source document 6: scope differs: "
        "missing 08; extra none\n"
        "Safe to commit: no\n"
    )


# --- Ingestion Ledger problems (ingestion-ledger, L8) ---------------------------------


def _ledger_cli(*args: str) -> Result:
    return CliRunner().invoke(main, ["ingestion", *args])


def test_format_2_check_reports_an_out_of_date_or_invalid_ledger(
    run, migrated, bundle_v2: Path
) -> None:
    assert run("data", "import", str(bundle_v2)).exit_code == 0
    assert _ledger_cli("update", str(bundle_v2)).exit_code == 0
    assert _ledger_cli("review", str(bundle_v2), "pp.md", "--keep").exit_code == 0
    ok = f"Database matches bundle {SLUG}: 5 parties, 106 candidatures, 4 documents\n"
    assert run("data", "check", str(bundle_v2)).output == ok
    assert run("db", "check").output == "Safe to commit: yes\n"

    # Pending Parties are not problems; an out-of-date ledger is.
    ledger = bundle_v2 / LEDGER_NAME
    obj = json.loads(ledger.read_bytes())
    obj["documents"][0]["content_hash"] = "0" * 64
    ledger.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode())
    out_of_date = (
        "ingestion ledger is out of date: Document pp.md: review cleared (content changed) "
        f'(+1 more); run "ideology ingestion update {bundle_v2}"'
    )

    check = run("data", "check", str(bundle_v2))
    assert check.exit_code == 1
    assert check.output == (
        f"Error: {out_of_date}\n"
        f"Error: ingestion ledger of bundle {SLUG} is not valid and up to date: 1 problems\n"
    )
    db_check = run("db", "check")
    assert db_check.exit_code == 1
    # db check reads the bundle under the relative ELECTIONS_DATA_DIR default.
    relative = out_of_date.replace(str(bundle_v2), f"data/elections/{SLUG}")
    assert db_check.output == (
        f"Error: election 1 ({SLUG}): {relative}\nSafe to commit: no\n"
    )

    obj["format"] = 2
    ledger.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode())
    invalid = f"{ledger}: format: unsupported ledger format 2 (expected 1)"
    assert run("data", "check", str(bundle_v2)).output == (
        f"Error: {invalid}\n"
        f"Error: ingestion ledger of bundle {SLUG} is not valid and up to date: 1 problems\n"
    )
    assert run("db", "check").output == (
        f"Error: election 1 ({SLUG}): data/elections/{SLUG}/{LEDGER_NAME}: format: "
        "unsupported ledger format 2 (expected 1)\nSafe to commit: no\n"
    )


def test_format_1_checks_never_read_a_stray_ledger(
    run, migrated, bundle: Path, db_url: str
) -> None:
    assert run("data", "import", str(bundle)).exit_code == 0
    (bundle / LEDGER_NAME).write_text("not a ledger", encoding="utf-8")

    check = run("data", "check", str(bundle))
    assert check.exit_code == 0, check.output
    assert check.output == f"Database matches bundle {SLUG}: 2 documents\n"
    assert run("db", "check").output == "Safe to commit: yes\n"
