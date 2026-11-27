"""``ideology ingestion next`` (ingestion-guide): one state per step, the walk, read-only.

T1 one state per step code, T2 the walk from a missing directory to
``generate-statements``, T3 planned calls, T4 read-only (checked on every
``next`` call by the ``nxt`` fixture: the bundle and database bytes, no
created file, SQLite only ``mode=ro``, no provider built), T5 ``Note:`` lines,
T6 the template, T7 docs in step with ``STEPS``, T8 the committed format-1
bundle. FakeProvider only; every bundle and database lives in ``tmp_path``
(the dev seed is copied first).
"""

import datetime as dt
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from bundle_factory import CandidatureSpec, DocumentSpec, manifest_v2_text, write_bundle_v2
from click.testing import CliRunner, Result
from dev_dataset_fixtures import sha256, snapshot
from pipeline_fixtures import offline_guard
from proposal_fixtures import PARTY_A, big_pages, fake, import_dir, keep_all, write_v2
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session
from v2_fixtures import P, R, documents, extraction_fake, setup, v2_fake

import ideology_app.llm as llm_module
from ideology_app import cli, ingestion_next
from ideology_app import ingestion_ledger as ledgers
from ideology_app.cli import main
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.models import PipelineRun, PipelineRunStatus
from ideology_app.pipeline.v2 import load_phase4, plan_calls
from ideology_app.pipeline.v2.gate import Phase4Error
from ideology_app.proposals import conflicts, store
from ideology_app.shared_db import sqlite_path
from ideology_app.source_bundle import BundleError, read_bundle, serialise_source_text

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "docs" / "templates" / "election-format-2.toml"
GUIDE = REPO / "docs" / "ingestion-guide.md"
SKILL = REPO / ".agents" / "skills" / "ingestion-guide" / "SKILL.md"
SLUG_2030 = "es-general-2030-06-02"
DATE_2030 = dt.date(2030, 6, 2)
X_ALL = CandidatureSpec("X", "Partido X", "all")
FLAG = [{"a": 1, "b": 1, "explanation": "Se contradicen."}]
CODES_1_50 = [f"{n:02d}" for n in range(1, 51)]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


# --- Running next, with the read-only checks of T4 -----------------------------------------


@dataclass
class Next:
    stdout: str
    keys: dict[str, list[str]]
    missing: list[str]

    @property
    def step(self) -> str:
        return self.keys["Step"][0]

    def one(self, key: str) -> str:
        values = self.keys[key]
        assert len(values) == 1, (key, values)
        return values[0]


def parse(stdout: str) -> tuple[dict[str, list[str]], list[str]]:
    keys: dict[str, list[str]] = {}
    missing: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("  "):
            missing.append(line[2:])
            continue
        if line.startswith("Missing ("):
            count = int(re.fullmatch(r"Missing \((\d+)\):", line).group(1))  # type: ignore[union-attr]
            keys["Missing"] = [str(count)]
            continue
        key, sep, value = line.partition(": ")
        assert sep, line
        keys.setdefault(key, []).append(value)
    assert int(keys["Missing"][0]) == len(missing)
    return keys, missing


KEY_ORDER = ["Bundle", "Database", "Phase", "Step", "Missing", "File", "Format", "Command",
             "LLM", "Shared database", "Note", "Then"]


def _boom(*args: object, **kwargs: object) -> None:
    raise AssertionError("ingestion next must not build an LLM provider")


def _db_file(url: str | None) -> Path | None:
    return sqlite_path(url or "sqlite:///ideology.db")


@pytest.fixture
def nxt(tmp_path: Path) -> Callable[..., Next]:
    """Run ``ingestion next`` and check T4 around it (exit 0, nothing written)."""

    def _next(directory: Path, url: str | None) -> Next:
        directory = Path(directory)
        watched = directory if directory.exists() else directory.parent
        before = snapshot(watched) if watched.exists() else None
        database = _db_file(url)
        db_before = sha256(database) if database is not None and database.exists() else None
        urls: list[str] = []
        real = ingestion_next.make_engine

        def recording(engine_url: str | None = None) -> Engine:
            assert engine_url is not None
            urls.append(engine_url)
            return real(engine_url)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ingestion_next, "make_engine", recording)
            mp.setattr(cli, "_provider", _boom)
            mp.setattr(cli, "build_provider", _boom)
            mp.setattr(llm_module, "build_provider", _boom)
            args = [] if url is None else ["--database-url", url]
            result: Result = CliRunner().invoke(main, [*args, "ingestion", "next", str(directory)])
        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        if before is None:
            assert not watched.exists()
        else:
            assert snapshot(watched) == before
        if not directory.exists():
            assert not directory.is_symlink()
        if database is not None:
            if db_before is None:
                assert not database.exists(), "a missing SQLite file must not be created"
            else:
                assert sha256(database) == db_before
                for suffix in ("-journal", "-wal", "-shm"):
                    assert not database.with_name(database.name + suffix).exists()
        for engine_url in urls:
            if engine_url.startswith("sqlite") and _db_file(engine_url) is not None:
                assert "mode=ro" in engine_url, engine_url
        keys, missing = parse(result.stdout)
        order = [key for key in KEY_ORDER if key in keys]
        seen = list(dict.fromkeys(line.partition(":")[0].split(" (")[0]
                                  for line in result.stdout.splitlines() if not line.startswith("  ")))
        assert seen == order
        assert keys["Bundle"] == [str(directory)]
        assert keys["Then"] == [f"ideology ingestion next {directory}"]
        assert keys["Step"][0] in ingestion_next.STEPS
        return Next(result.stdout, keys, missing)

    return _next


def assert_step(result: Next, code: str) -> None:
    assert result.step == code, result.stdout


def cli_ok(*args: str | Path, url: str | None = None) -> Result:
    prefix = [] if url is None else ["--database-url", url]
    result = CliRunner().invoke(main, [*prefix, *map(str, args)])
    assert result.exit_code == 0, result.output
    return result


def url_for(tmp_path: Path, name: str = "test.db") -> str:
    return f"sqlite:///{tmp_path}/{name}"


# --- Bundles for phases 1 and 2 ------------------------------------------------------------


def bundle_2030(root: Path, parties, docs=()) -> Path:  # type: ignore[no-untyped-def]
    manifest = manifest_v2_text(parties, docs, date=DATE_2030, name="Elecciones generales 2030")
    return write_bundle_v2(root, parties, docs, slug=SLUG_2030, manifest=manifest)


def reviewed_bundle(root: Path) -> Path:
    directory = bundle_2030(root, [CandidatureSpec("P", "Partido P", "all")],
                            [DocumentSpec("a.md", "P", ["Una medida."], ["P"])])
    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision=ledgers.ReviewDecision.KEPT)
    return directory


# --- T1 / Phase 1 ------------------------------------------------------------------------------


def test_create_bundle_directory_prints_the_command_and_creates_nothing(
    nxt, tmp_path: Path
) -> None:
    directory = tmp_path / "elections" / SLUG_2030
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "create-bundle-directory")
    assert result.one("Phase") == "1 (candidatures)"
    assert result.missing == [f"bundle directory {directory}"]
    assert result.one("File") == str(directory)
    assert "<country>-<type>-<date>" in result.one("Format")
    assert "es-general-2030-06-02" in result.one("Format")
    assert result.one("Command") == (
        f"mkdir -p {directory} && cp docs/templates/election-format-2.toml "
        f"{directory}/election.toml"
    )
    assert result.one("LLM") == "no"
    assert "Note" not in result.keys
    assert not (tmp_path / "elections").exists()
    assert not (tmp_path / "test.db").exists()


def test_a_directory_name_that_is_not_a_slug_gets_a_note(nxt, tmp_path: Path) -> None:
    result = nxt(tmp_path / "my-election", None)
    assert_step(result, "create-bundle-directory")
    assert "is not <country>-<type>-<date>" in result.one("Note")


def test_write_manifest(nxt, tmp_path: Path) -> None:
    directory = tmp_path / SLUG_2030
    directory.mkdir()
    result = nxt(directory, None)
    assert_step(result, "write-manifest")
    assert result.one("Command") == (
        f"cp docs/templates/election-format-2.toml {directory}/election.toml"
    )
    assert result.one("File") == f"{directory}/election.toml"


def test_template_lists_every_placeholder_line_and_is_refused(nxt, tmp_path: Path) -> None:
    """T6 and scenario 2."""
    directory = tmp_path / SLUG_2030
    directory.mkdir()
    shutil.copyfile(TEMPLATE, directory / "election.toml")
    text = TEMPLATE.read_text(encoding="utf-8")
    expected = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.split("\n"), start=1)
        if "<<" in line
    ]
    assert len(expected) == text.count("<<") == len(FILLED) == 12

    result = nxt(directory, None)

    assert_step(result, "fill-manifest-placeholders")
    assert result.missing == expected
    formats = "\n".join(result.keys["Format"])
    for part in ("[candidatures]", "[[parties]]", '"all"', "INE codes",
                 "ideology constituency list", "[[documents]]"):
        assert part in formats
    assert "ideology constituency list" in result.keys["Command"]
    with pytest.raises(BundleError, match="invalid TOML"):
        read_bundle(directory)


FILLED = {
    "<<PAIS>>": '"ES"',
    "<<TIPO>>": '"general"',
    "<<FECHA>>": "2030-06-02",
    "<<NOMBRE_ELECCION>>": '"Elecciones generales 2030"',
    "<<FUENTE_BOE>>": '"BOE ficticio"',
    "<<URL_BOE>>": '"https://example.org/boe"',
    "<<SIGLAS_1>>": '"SIGLAS1"',
    "<<NOMBRE_1>>": '"Partido Uno"',
    "<<CIRCUNSCRIPCIONES_1>>": '"all"',
    "<<SIGLAS_2>>": '"SIGLAS2"',
    "<<NOMBRE_2>>": '"Partido Dos"',
    "<<CIRCUNSCRIPCIONES_2>>": '["08", "17", "25", "43"]',
}


def test_filled_template_is_accepted_with_and_without_a_document(tmp_path: Path) -> None:
    """T6: every placeholder replaced; then the first commented [[documents]] block."""
    text = TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in FILLED.items():
        text = text.replace(placeholder, value)
    assert "<<" not in text
    directory = tmp_path / SLUG_2030
    directory.mkdir()
    (directory / "election.toml").write_text(text, encoding="utf-8")
    bundle = read_bundle(directory)
    assert bundle.format == 2
    assert [p.short_name for p in bundle.parties] == ["SIGLAS1", "SIGLAS2"]
    assert bundle.documents == ()

    block = (
        '# [[documents]]\n# file = "siglas1.md"\n'
        '# parties = ["SIGLAS1", "SIGLAS2"]  # un programa compartido por varias candidaturas\n'
    )
    assert block in text
    text = text.replace(block, "\n".join(line[2:] for line in block.splitlines()) + "\n")
    (directory / "election.toml").write_text(text, encoding="utf-8")
    (directory / "siglas1.md").write_bytes(
        serialise_source_text(
            party="SIGLAS1", source_url="https://example.org/siglas1.pdf", pdf_sha256="0" * 64,
            extractor="pypdf 0.0-test", pages=["Programa ficticio."],
        )
    )
    bundle = read_bundle(directory)
    assert [(d.file, d.parties) for d in bundle.documents] == [
        ("siglas1.md", ("SIGLAS1", "SIGLAS2"))
    ]


def test_fix_manifest_prints_the_bundle_error(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(tmp_path, [X_ALL])
    (directory / "stray.md").write_text("x", encoding="utf-8")
    result = nxt(directory, None)
    assert_step(result, "fix-manifest")
    assert result.missing == [f"{directory}/stray.md:1: file is not listed in election.toml"]
    assert any("[[documents]]" in line for line in result.keys["Format"])


def test_committed_format_1_bundle_asks_for_format_2(nxt, tmp_path: Path) -> None:
    """T8: the committed 2023 bundle; its bytes are unchanged (checked by nxt)."""
    directory = REPO / "data" / "elections" / "es-general-2023-07-23"
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "convert-to-format-2")
    assert result.missing == ["election.toml is format 1 (one file per Party, no candidatures)"]
    assert "v2 needs manifest format 2" in result.keys["Format"][0]


def test_declare_candidatures_lists_the_uncovered_constituencies(nxt, tmp_path: Path) -> None:
    """Scenario 3."""
    directory = bundle_2030(tmp_path, [CandidatureSpec("P", "Partido P", CODES_1_50)])
    result = nxt(directory, None)
    assert_step(result, "declare-candidatures")
    assert result.missing == ["51 Ceuta", "52 Melilla"]
    assert result.one("File") == f"{directory}/election.toml ([[parties]] constituencies)"
    assert any("BOE proclamation" in line for line in result.keys["Format"])
    assert result.keys["Command"] == ["ideology constituency list"]


# --- T1 / Phase 2 ------------------------------------------------------------------------------


def test_provide_manifestos_per_party(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(
        tmp_path,
        [CandidatureSpec("P", "Partido P", "all"), CandidatureSpec("ONIX-CAT", "Ónix", ["08"])],
    )
    result = nxt(directory, None)
    assert_step(result, "provide-manifestos")
    assert result.missing == [
        "P (Partido P): no [[documents]] entry and no no-manifesto decision; runs in 52 "
        "Constituencies",
        "ONIX-CAT (Ónix): no [[documents]] entry and no no-manifesto decision; runs in 1 "
        "Constituency",
    ]
    assert result.keys["Command"][0] == (
        f"ideology source extract PDF --party P --out {directory}/p.md --url URL"
    )
    assert result.keys["Command"][2] == (
        f"or: ideology ingestion no-manifesto {directory} P --note NOTE"
    )
    assert result.one("LLM") == "no"


def test_a_no_manifesto_decision_clears_provide_manifestos(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(
        tmp_path,
        [CandidatureSpec("P", "Partido P", "all"), CandidatureSpec("Q", "Partido Q", ["28"])],
        [DocumentSpec("a.md", "P", ["Una medida."], ["P"])],
    )
    ledgers.no_manifesto_in_dir(directory, "Q", note="No publicado.")
    result = nxt(directory, None)
    assert_step(result, "review-manifestos")


def test_repair_ledger(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(tmp_path, [CandidatureSpec("P", "Partido P", "all")])
    (directory / "ingestion-ledger.json").write_text("{\n", encoding="utf-8")
    result = nxt(directory, None)
    assert_step(result, "repair-ledger")
    assert str(directory / "ingestion-ledger.json") in result.missing[0]
    assert result.keys["Command"][-1] == f"ideology ingestion update {directory}"


def test_update_ledger_when_missing_and_when_out_of_date(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(tmp_path, [CandidatureSpec("P", "Partido P", "all")],
                            [DocumentSpec("a.md", "P", ["Una medida."], ["P"])])
    result = nxt(directory, None)
    assert_step(result, "update-ledger")
    assert result.missing[0] == "no ingestion ledger yet"
    assert result.one("Command") == f"ideology ingestion update {directory}"
    assert "writes the ledger" in result.one("Shared database")

    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision=ledgers.ReviewDecision.KEPT)
    (directory / "a.md").write_bytes(
        DocumentSpec("a.md", "P", ["Otra medida."], ["P"]).content()
    )
    stale = nxt(directory, None)
    assert_step(stale, "update-ledger")
    assert stale.missing[0] == "the ledger is out of date"
    assert len(stale.missing) > 1


def test_review_manifestos_lists_pages_and_characters(nxt, tmp_path: Path) -> None:
    directory = bundle_2030(
        tmp_path,
        [CandidatureSpec("P", "Partido P", "all"), CandidatureSpec("Q", "Partido Q", ["28"])],
        [DocumentSpec("a.md", "P", ["Una medida.", "", "Dos."], ["P", "Q"])],
    )
    ledgers.update_in_dir(directory)
    result = nxt(directory, None)
    assert_step(result, "review-manifestos")
    assert result.missing == ["a.md (parties P, Q): 3 pages, 1 without text, 15 characters"]
    assert result.keys["Command"] == [
        f"ideology ingestion review {directory} a.md",
        f"ideology ingestion review {directory} a.md --keep",
        f"ideology ingestion review {directory} a.md --discard REASON --note NOTE",
    ]


# --- T1 / Phase 3 ------------------------------------------------------------------------------


def test_create_database_when_the_file_is_missing(nxt, tmp_path: Path) -> None:
    directory = reviewed_bundle(tmp_path)
    result = nxt(directory, url_for(tmp_path, "scratch.db"))
    assert_step(result, "create-database")
    assert result.one("Phase") == "3 (proposals)"
    assert result.missing == [f"no database at {tmp_path}/scratch.db"]
    assert result.one("Command") == "ideology db upgrade"
    assert result.one("Database") == f"sqlite:///{tmp_path}/scratch.db (read-only)"


def test_create_database_with_the_default_url_creates_no_file(nxt, tmp_path: Path) -> None:
    directory = reviewed_bundle(tmp_path)
    result = nxt(directory, None)
    assert_step(result, "create-database")
    assert result.missing == ["no database at ideology.db"]
    assert not (tmp_path / "ideology.db").exists()


def test_create_database_on_a_missing_shared_file_says_restore(nxt, tmp_path: Path) -> None:
    directory = reviewed_bundle(tmp_path)
    result = nxt(directory, "sqlite:///data/ideology.db")
    assert_step(result, "create-database")
    assert result.one("Database") == "sqlite:///data/ideology.db (shared, read-only)"
    assert "restore it from git" in result.missing[0]
    assert "git pull" in result.one("Command")
    assert not (tmp_path / "data").exists()


def test_create_database_when_the_file_is_not_initialised(nxt, tmp_path: Path) -> None:
    directory = reviewed_bundle(tmp_path)
    (tmp_path / "empty.db").write_bytes(b"")
    result = nxt(directory, url_for(tmp_path, "empty.db"))
    assert_step(result, "create-database")
    assert result.missing == ["the database is not initialised (no migration applied)"]


def test_upgrade_database(nxt, tmp_path: Path) -> None:
    directory = reviewed_bundle(tmp_path)
    url = url_for(tmp_path)
    run_migrations(url, "0020")
    result = nxt(directory, url)
    assert_step(result, "upgrade-database")
    assert result.missing == ["the schema is at migration 0020, the code's head is 0021"]
    assert result.one("Command") == "ideology db upgrade"


def test_import_bundle(nxt, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = reviewed_bundle(tmp_path)
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "import-bundle")
    assert result.missing == [f"election {SLUG_2030} not found"]
    assert result.keys["Command"] == [
        f"ideology data import {directory}", f"ideology data check {directory}"
    ]
    assert result.one("Shared database") == (
        "no; this command writes the database on the Database: line"
    )


def test_import_bundle_on_the_shared_database_asks_for_the_three_confirmations(
    nxt, tmp_path: Path
) -> None:
    directory = reviewed_bundle(tmp_path)
    (tmp_path / "data").mkdir()
    run_migrations("sqlite:///data/ideology.db")
    result = nxt(directory, "sqlite:///data/ideology.db")
    assert_step(result, "import-bundle")
    shared = result.one("Shared database")
    for part in ("git status --short", "nobody else is generating",
                 "no ideology process or server has the file open", "--yes", "db check"):
        assert part in shared


def test_the_committed_shared_file_is_only_read(nxt, tmp_path: Path) -> None:
    """The repo's data/ideology.db, by absolute path: opened mode=ro, bytes unchanged."""
    directory = reviewed_bundle(tmp_path)
    shared = REPO / "data" / "ideology.db"
    before = sha256(shared)
    result = nxt(directory, f"sqlite:///{shared}")
    assert_step(result, "import-bundle")
    assert sha256(shared) == before


def _extraction_bundle(tmp_path: Path, engine: Engine) -> Path:
    directory = write_v2(tmp_path, [PARTY_A], [DocumentSpec("a.md", "A", big_pages(3), ["A"])])
    import_dir(engine, directory)
    keep_all(directory, min_proposals=1)
    return directory


def test_extract_proposals_counts_the_remaining_chunks(
    nxt, tmp_path: Path, migrated_engine: Engine
) -> None:
    """T3: the planned calls equal the remaining status_rows chunks."""
    directory = _extraction_bundle(tmp_path, migrated_engine)
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "extract-proposals")
    with Session(migrated_engine) as session:
        bundle = read_bundle(directory)
        rows = store.status_rows(session, bundle, ledgers.read_ledger(directory))
    remaining = sum(row.chunk_count - row.chunks_done for row in rows)
    assert remaining == 3
    assert result.missing == ["a.md: not_started, 0/3 chunks (3 calls)"]
    assert result.one("Command") == f"ideology proposals extract {directory} --max-calls 3"
    assert result.one("LLM") == (
        "yes; provider anthropic, model claude-sonnet-5-5 (LLM_PROVIDER / LLM_MODEL); "
        "planned calls 3; cost: docs/ingestion-guide.md, section Costes"
    )


def test_extract_proposals_shows_an_unconfigured_provider(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _extraction_bundle(tmp_path, migrated_engine)
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "extract-proposals")
    assert result.one("LLM").startswith("not configured: Invalid LLM_PROVIDER 'nope'")
    assert "planned calls 3" in result.one("LLM")


def test_in_progress_extraction_shows_its_pinned_model_and_a_note(
    nxt, tmp_path: Path, migrated_engine: Engine
) -> None:
    """T3 (pinned provider) and T5 (in-progress extraction note)."""
    directory = _extraction_bundle(tmp_path, migrated_engine)
    provider = fake(fail_on_page=2, model="pinned-model")
    plan = store.prepare_extraction(migrated_engine, directory, provider)
    summary = store.execute_plan(migrated_engine, provider, plan)
    assert summary.error is not None

    result = nxt(directory, url_for(tmp_path))

    assert_step(result, "extract-proposals")
    assert result.missing == ["a.md: in_progress, 1/3 chunks (2 calls)"]
    assert result.one("LLM").startswith(
        "yes; provider fake, model pinned-model (pinned by the in-progress extraction"
    )
    assert "planned calls 2;" in result.one("LLM")
    assert any(
        re.fullmatch(r"proposal extraction [0-9a-f]{12}: in_progress, 1/3 chunks; .*", note)
        for note in result.keys["Note"]
    )


def test_fix_proposal_counts(nxt, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine, parties=(P, R, X_ALL))
    content_hash = read_bundle(directory).documents[2].text.content_hash
    ledgers.record_extraction_in_dir(
        directory, "r.md", content_hash=content_hash, validated_proposals=99
    )
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "fix-proposal-counts")
    assert result.missing == [
        f"document r.md: ledger records 99 validated proposals, the database has 3 for "
        f"{content_hash[:12]}..."
    ]
    assert result.one("Command") == f"ideology proposals extract {directory}"
    assert result.one("LLM").startswith("no (0 calls")


def test_check_conflicts_plans_the_detect_calls(
    nxt, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine, parties=(P, R, X_ALL), detect=False)
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "check-conflicts")
    assert result.missing == ["P a.md + b.md (28): not checked (2 calls)"]
    assert result.one("Command") == f"ideology conflicts detect {directory} --max-calls 2"
    assert "planned calls 2;" in result.one("LLM")
    assert result.one("Shared database") == (
        "no; this command writes the ledger, not the database"
    )

    from conflict_fixtures import conflict_fake

    provider = conflict_fake()
    conflicts.detect(migrated_engine, directory, provider)
    assert len(provider.calls) == 2


def test_decide_conflicts(nxt, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine, parties=(P, R, X_ALL), contradictions=FLAG)
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "decide-conflicts")
    entry = ledgers.read_ledger(directory).conflict("P", ["a.md", "b.md"])  # type: ignore[union-attr]
    assert result.missing == [f"P a.md + b.md (28): {len(entry.contradictions)} contradictions"]
    assert result.keys["Command"] == [
        f"ideology conflicts show {directory} P a.md b.md",
        f"ideology conflicts decide {directory} P --prevails FILE --over FILE --reason REASON",
    ]
    assert result.one("LLM") == "no"


# --- T1 / Phase 4 ------------------------------------------------------------------------------


@pytest.fixture
def v2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "1")
    monkeypatch.setenv("VALIDATION_V2_MIN_PARTY_SIDES", "1")


def _ready(tmp_path: Path, engine: Engine) -> Path:
    return setup(tmp_path, engine, parties=(P, R, X_ALL))


def test_phase4_blocked_from_the_ledger_and_from_load_phase4(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback: unreachable once the earlier steps pass, so both sources are forced."""
    directory = _ready(tmp_path, migrated_engine)
    monkeypatch.setattr(
        ingestion_next.ledgers, "phase4_blockers", lambda bundle, ledger: ["party Z: forced"]
    )
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "phase4-blocked")
    assert result.missing == ["party Z: forced"]
    assert result.keys["Command"] == [
        f"ideology ingestion gate {directory}", f"ideology ingestion status {directory}"
    ]
    monkeypatch.undo()
    offline_guard(monkeypatch)

    def refuse(session: Session, bundle_dir: Path) -> None:
        raise Phase4Error("proposal counts differ: x", ["document r.md: forced"])

    monkeypatch.setattr(ingestion_next, "load_phase4", refuse)
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "phase4-blocked")
    assert result.missing == ["document r.md: forced"]


def test_generate_statements_plans_the_calls(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, v2_env: None
) -> None:
    """T3: the planned calls equal plan_calls; a real run stays within them."""
    directory = _ready(tmp_path, migrated_engine)
    with Session(migrated_engine) as session:
        planned = plan_calls(load_phase4(session, directory))
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "generate-statements")
    assert result.one("Phase") == "4 (statements)"
    assert result.missing == [f"no v2 Pipeline Run with a Dataset Version for {read_bundle(directory).slug}"]
    assert result.one("Command") == f"ideology pipeline run-v2 {directory}"
    assert f"planned calls at most {planned};" in result.one("LLM")
    assert any("caffeinate -is" in note for note in result.keys["Note"])

    provider = v2_fake()
    monkeypatch.setattr(cli, "_provider", lambda: provider)
    cli_ok("pipeline", "run-v2", directory, url=url_for(tmp_path))
    assert 0 < len(provider.calls) <= planned


def _failed_run(
    root: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch, url: str
) -> Path:
    directory = _ready(root, engine)
    monkeypatch.setattr(cli, "_provider", lambda: v2_fake(fail_on_call=4))
    result = CliRunner().invoke(main, ["--database-url", url, "pipeline", "run-v2",
                                       str(directory)])
    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 failed: provider overloaded (529)\n"
    return directory


def test_resume_run(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, v2_env: None
) -> None:
    """Scenario 6, with the running warning."""
    directory = _failed_run(tmp_path, migrated_engine, monkeypatch, url_for(tmp_path))
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "resume-run")
    assert result.missing == [
        "run 1: failed, 3 recorded calls, no Dataset Version",
        "failure: provider overloaded (529)",
    ]
    assert result.one("Command") == (
        f"LLM_PROVIDER=fake LLM_MODEL=fake-model ideology pipeline run-v2 {directory} "
        "--resume-from 1"
    )
    assert result.one("LLM").startswith("yes; provider fake, model fake-model (run 1's)")
    assert result.keys["Note"] == [
        "run 1 used provider fake (scripted, e.g. the dev dataset): a replay from the CLI has "
        "no answers for new calls and fails; reseed the dev dataset instead"
    ]

    with session_scope(migrated_engine) as session:
        session.execute(update(PipelineRun).values(status=PipelineRunStatus.RUNNING))
    running = nxt(directory, url_for(tmp_path))
    assert_step(running, "resume-run")
    assert running.keys["Note"][0].startswith("run 1 is running: it may be active on another")


def test_another_elections_unfinished_run_is_a_note(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, v2_env: None
) -> None:
    """T5: one active run at a time, any Election."""
    _failed_run(tmp_path / "one", migrated_engine, monkeypatch, url_for(tmp_path))
    other = reviewed_bundle(tmp_path / "two")
    result = nxt(other, url_for(tmp_path))
    assert_step(result, "import-bundle")
    assert result.keys["Note"] == [
        "election 1 has an unfinished run 1 (failed, 3 recorded calls); one active run at a "
        "time: do not generate while it may be running"
    ]


def test_read_failed_run(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario 7: default minimums fail Validation with a candidate Dataset Version."""
    directory = _ready(tmp_path, migrated_engine)
    monkeypatch.setattr(cli, "_provider", lambda: v2_fake())
    failed = CliRunner().invoke(main, ["--database-url", url_for(tmp_path), "pipeline", "run-v2",
                                       str(directory)])
    assert failed.exit_code == 1
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "read-failed-run")
    assert result.missing == [
        "run 1 failed Validation: validation failed: constituency_availability"
    ]
    assert result.keys["Command"][:2] == [
        "ideology pipeline checks --run 1", "ideology pipeline report --run 1"
    ]


# --- T1 / done and rewording on a copy of the dev seed --------------------------------------


@pytest.fixture
def dev_copy(dev_seed: Any, tmp_path: Path) -> tuple[Path, str]:
    """A copy of the session dev seed: (bundle directory, database URL)."""
    root = tmp_path / "dev"
    shutil.copytree(dev_seed.database.parent, root)
    return root / "dev-bundle" / dev_seed.bundle.name, f"sqlite:///{root}/dev.db"


def test_done_on_the_dev_dataset(nxt, dev_copy: tuple[Path, str]) -> None:
    """Scenario 8 (done)."""
    directory, url = dev_copy
    result = nxt(directory, url)
    assert_step(result, "done")
    assert result.missing == []
    assert result.keys["Note"][:3] == [
        "Dataset Version 1 (published), run 1",
        "Constituencies: 51 available, 1 unavailable (52 fewer_than_two_parties); 0 statements "
        "valid in no available constituency",
        "Rewordings: 1 applied, 0 rejected, 0 duplicate, 0 not found",
    ]
    assert result.keys["Command"] == [
        "ideology pipeline report --run 1",
        "ideology pipeline statements --run 1",
        "ideology db check",
    ]
    assert "statement-rewordings.toml: format = 1" in result.keys["Format"][0]
    assert result.one("LLM") == "no"


def test_reword_statements_when_the_file_is_edited_removed_or_added(
    nxt, dev_copy: tuple[Path, str]
) -> None:
    """Scenario 8 (rewording): one planned call per new or changed entry (a recorded check
    of the same AI text and wording is reused by --reuse-from)."""
    directory, url = dev_copy
    rewordings = directory / "statement-rewordings.toml"
    original = rewordings.read_text(encoding="utf-8")
    rewordings.write_text(
        original
        + '\n[[rewordings]]\nai_text = "Otra afirmación."\ntext = "Otra redacción."\n'
        'reason = "Confunde."\n',
        encoding="utf-8",
    )
    edited = nxt(directory, url)
    assert_step(edited, "reword-statements")
    assert edited.missing == ["statement-rewordings.toml changed after run 1 (2 entries)"]
    assert edited.one("Command") == (
        f"LLM_PROVIDER=fake LLM_MODEL=dev-dataset-1 ideology pipeline run-v2 {directory} "
        "--reuse-from 1"
    )
    assert "planned calls 1 (one per new or changed entry) if nothing in phases 1-3 changed " \
        "since run 1; up to " in edited.one("LLM")
    assert any(note.startswith("run 1 used provider fake") for note in edited.keys["Note"])
    assert "writes the database" in edited.one("Shared database")

    rewordings.unlink()
    removed = nxt(directory, url)
    assert_step(removed, "reword-statements")
    assert removed.missing == ["statement-rewordings.toml was removed after run 1 (0 entries)"]
    assert "planned calls 0 (one per new or changed entry)" in removed.one("LLM")

    rewordings.write_text(original.replace("cuántos días", "cuantos días"), encoding="utf-8")
    changed = nxt(directory, url)
    assert_step(changed, "reword-statements")
    assert "planned calls 1 (one per new or changed entry)" in changed.one("LLM")

    rewordings.write_text("format = 2\n", encoding="utf-8")
    invalid = nxt(directory, url)
    assert_step(invalid, "reword-statements")
    assert invalid.missing == [f"{rewordings}: format must be 1, got 2"]


def test_reword_planned_calls_match_a_real_replay(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, v2_env: None
) -> None:
    """The reword-statements bound equals the new calls of the --reuse-from replay."""
    directory = _ready(tmp_path, migrated_engine)
    entry = (
        '[[rewordings]]\nai_text = "{ai}"\ntext = "{text}"\nreason = "Confunde."\n'
    )
    first = entry.format(ai="Debe limitarse el precio del alquiler de vivienda.",
                         text="Hay que poner un límite al precio del alquiler.")
    (directory / "statement-rewordings.toml").write_text("format = 1\n\n" + first, encoding="utf-8")
    provider = v2_fake()
    monkeypatch.setattr(cli, "_provider", lambda: provider)
    cli_ok("pipeline", "run-v2", directory, url=url_for(tmp_path))
    assert_step(nxt(directory, url_for(tmp_path)), "done")

    second = entry.format(ai="Deben bajarse los impuestos a las empresas.",
                          text="Hay que bajar los impuestos a las empresas.")
    (directory / "statement-rewordings.toml").write_text(
        "format = 1\n\n" + first + "\n" + second, encoding="utf-8"
    )
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "reword-statements")
    assert "planned calls 1 (one per new or changed entry)" in result.one("LLM")
    replay = v2_fake()
    monkeypatch.setattr(cli, "_provider", lambda: replay)
    cli_ok("pipeline", "run-v2", directory, "--reuse-from", "1", url=url_for(tmp_path))
    assert len(replay.calls) == 1
    assert_step(nxt(directory, url_for(tmp_path)), "done")


def test_reword_upper_bound_covers_a_replay_after_a_phase3_change(
    nxt, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, v2_env: None
) -> None:
    """Validator M1: a re-decided conflict (not detected, G10) makes the replay a full run;
    the printed upper bound still covers its real calls."""
    directory = setup(tmp_path, migrated_engine, parties=(P, R, X_ALL), contradictions=FLAG,
                      decide=("a.md", "b.md"))
    monkeypatch.setattr(cli, "_provider", lambda: v2_fake())
    cli_ok("pipeline", "run-v2", directory, url=url_for(tmp_path))
    ledgers.decide_conflict_in_dir(directory, "P", prevails="b.md", over="a.md",
                                   reason="Redecidido.")
    assert_step(nxt(directory, url_for(tmp_path)), "done")  # G10: not detected
    (directory / "statement-rewordings.toml").write_text(
        'format = 1\n\n[[rewordings]]\nai_text = "Deben bajarse los impuestos a las '
        'empresas."\ntext = "Hay que bajar los impuestos a las empresas."\n'
        'reason = "Confunde."\n',
        encoding="utf-8",
    )
    result = nxt(directory, url_for(tmp_path))
    assert_step(result, "reword-statements")
    match = re.search(r"planned calls 1 \(one per new or changed entry\) if nothing in phases "
                      r"1-3 changed since run 1; up to (\d+) otherwise", result.one("LLM"))
    assert match is not None, result.one("LLM")
    upper = int(match.group(1))
    assert any("otherwise this replay is a full run" in note for note in result.keys["Note"])
    replay = v2_fake()
    monkeypatch.setattr(cli, "_provider", lambda: replay)
    cli_ok("pipeline", "run-v2", directory, "--reuse-from", "1", url=url_for(tmp_path))
    assert 1 < len(replay.calls) <= upper


# --- T2: the walk ------------------------------------------------------------------------------


def test_walk_from_an_empty_election_to_generate_statements(
    nxt, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "elections"
    directory = root / SLUG_2030
    url = url_for(tmp_path, "dry.db")
    codes: list[str] = []

    def step() -> Next:
        result = nxt(directory, url)
        codes.append(result.step)
        return result

    step()
    directory.mkdir(parents=True)
    step()
    shutil.copyfile(TEMPLATE, directory / "election.toml")
    step()
    p = CandidatureSpec("P", "Partido P", CODES_1_50)
    r = CandidatureSpec("R", "Partido R", ["51", "52"])
    bundle_2030(root, [p])
    assert step().missing == ["51 Ceuta", "52 Melilla"]
    bundle_2030(root, [p, r])
    step()
    bundle_2030(root, [p, r], documents())
    step()
    cli_ok("ingestion", "update", directory, "--min-proposals", "1")
    step()
    for file in ("a.md", "b.md", "r.md"):
        cli_ok("ingestion", "review", directory, file, "--keep")
    step()
    cli_ok("db", "upgrade", url=url)
    step()
    cli_ok("data", "import", directory, url=url)
    extract = step()
    provider = extraction_fake()
    monkeypatch.setattr(cli, "_provider", lambda: provider)
    cli_ok("proposals", "extract", directory, url=url)
    assert f"planned calls {len(provider.calls)};" in extract.one("LLM")
    check = step()
    from conflict_fixtures import conflict_fake

    detector = conflict_fake(FLAG)
    monkeypatch.setattr(cli, "_provider", lambda: detector)
    cli_ok("conflicts", "detect", directory, url=url)
    assert f"planned calls {len(detector.calls)};" in check.one("LLM")
    step()
    cli_ok("conflicts", "decide", directory, "P", "--prevails", "a.md", "--over", "b.md",
           "--reason", "Decidido por el Operador.")
    step()

    assert codes == [
        "create-bundle-directory",
        "write-manifest",
        "fill-manifest-placeholders",
        "declare-candidatures",
        "provide-manifestos",
        "update-ledger",
        "review-manifestos",
        "create-database",
        "import-bundle",
        "extract-proposals",
        "check-conflicts",
        "decide-conflicts",
        "generate-statements",
    ]


# --- T7: docs in step with STEPS ----------------------------------------------------------------


def test_steps_are_unique_and_each_is_reached_by_a_test() -> None:
    assert len(set(ingestion_next.STEPS)) == len(ingestion_next.STEPS) == 23
    source = Path(__file__).read_text(encoding="utf-8")
    for code in ingestion_next.STEPS:
        assert re.search(rf'assert_step\(\w+, "{re.escape(code)}"\)', source), code


@pytest.mark.parametrize("path", [GUIDE, SKILL], ids=["guide", "skill"])
def test_every_step_code_is_documented(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for code in ingestion_next.STEPS:
        assert f"`{code}`" in text, (path.name, code)


def test_the_skill_states_the_hard_rules() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: ingestion-guide\ndescription: ")
    for phrase in (
        "Never invent data",
        "¿Apruebo el gasto?",
        "one invocation",
        "git status --short",
        "nobody else is generating",
        "no `ideology` process or server has the file open",
        "--yes",
        "Never run git",
        "Never edit AI output",
        "ideology ingestion next",
    ):
        assert phrase in text, phrase
    openai = SKILL.parent / "agents" / "openai.yaml"
    assert "$ingestion-guide" in openai.read_text(encoding="utf-8")


def test_the_guide_is_in_spanish_and_has_the_cost_table() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for phrase in ("## Costes", "225", "80–240", "245–410", "comprobar antes de usar",
                   "ideology ingestion next", "Nunca"):
        assert phrase in text, phrase
