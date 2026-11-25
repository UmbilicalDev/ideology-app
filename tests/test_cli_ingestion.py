"""``ideology ingestion status|update|review|no-manifesto|gate`` (ingestion-ledger).

Exact output and exit codes. The commands need no database; scenario 9 checks
that they never touch one, in live Generation Mode too. Tests never call a
real LLM (offline guard) and build every bundle in ``tmp_path``.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import CandidatureSpec, DocumentSpec, write_bundle, write_bundle_v2
from click.testing import CliRunner, Result
from pipeline_fixtures import offline_guard

from ideology_app import ingestion_ledger as ledgers
from ideology_app.cli import main
from ideology_app.db import make_engine
from ideology_app.ingestion_ledger import LEDGER_NAME, NOT_CANONICAL
from ideology_app.source_bundle import read_bundle

PARTY_A = CandidatureSpec("A", "Partido A", "all")
PARTY_B = CandidatureSpec("B", "Partido B", ["28"])
PARTY_C = CandidatureSpec("C", "Partido C", ["08"])
DOC_A = DocumentSpec("a.md", "A", ["Programa de A.", ""], ["A", "B"])
DOC_B = DocumentSpec("b.md", "B", ["Programa de B."], ["B"])

NEXT_C = 'list a manifesto in [[documents]] or record "ingestion no-manifesto"'


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return write_bundle_v2(
        tmp_path / "data" / "elections", [PARTY_A, PARTY_B, PARTY_C], [DOC_A, DOC_B]
    )


def ingestion(*args: str | Path) -> Result:
    return CliRunner().invoke(main, ["ingestion", *map(str, args)])


def _footer(extracted: int, excluded: int, phase2: int, phase3: int, ready: bool) -> str:
    return (
        f"Parties: 3; extracted {extracted}, excluded {excluded}, "
        f"pending phase 2: {phase2}, pending phase 3: {phase3}\n"
        "Conflicts pending: 0\n"
        f"Phase 4: {'ready' if ready else 'blocked'}\n"
    )


def _record(directory: Path, file: str, count: int) -> None:
    content_hash = ledgers.listed_document(read_bundle(directory), file).text.content_hash
    ledgers.record_extraction_in_dir(
        directory, file, content_hash=content_hash, validated_proposals=count
    )


def test_status_and_gate_before_the_ledger_exists(directory: Path) -> None:
    status = ingestion("status", directory)

    assert status.exit_code == 0, status.output
    assert status.output == (
        f"Ingestion ledger {directory.name} (N = 30)\n"
        'Warning: no ingestion ledger yet; "ideology ingestion update" creates it\n'
        "A\tcandidature_declared\tnext: review a.md\n"
        "B\tcandidature_declared\tnext: review a.md, b.md\n"
        f"C\tcandidature_declared\tnext: {NEXT_C}\n" + _footer(0, 0, 3, 0, False)
    )
    gate = ingestion("gate", directory)
    assert gate.exit_code == 1
    assert gate.output == (
        f'Error: no ingestion ledger yet; run "ideology ingestion update {directory}"\n'
        "Error: party A: candidature_declared (next: review a.md)\n"
        "Error: party B: candidature_declared (next: review a.md, b.md)\n"
        f"Error: party C: candidature_declared (next: {NEXT_C})\n"
        "Phase 4: blocked (4 blockers)\n"
    )
    assert not (directory / LEDGER_NAME).exists()


def test_full_walk_through_the_commands(directory: Path) -> None:
    update = ingestion("update", directory)
    assert update.exit_code == 0, update.output
    assert update.output == (
        f"Created ingestion ledger {directory / LEDGER_NAME} (N = 30)\n"
        f"Ingestion ledger {directory.name} (N = 30)\n"
        "A\tcandidature_declared\tnext: review a.md\n"
        "B\tcandidature_declared\tnext: review a.md, b.md\n"
        f"C\tcandidature_declared\tnext: {NEXT_C}\n" + _footer(0, 0, 3, 0, False)
    )
    again = ingestion("update", directory)
    assert again.output.startswith("Ledger unchanged\nIngestion ledger ")

    show = ingestion("review", directory, "a.md")
    assert show.exit_code == 0, show.output
    assert show.output == (
        "Document a.md (parties A, B): 2 pages, 1 without text, 14 characters\n"
        "Review: not reviewed\n"
    )

    keep = ingestion("review", directory, "a.md", "--keep")
    assert keep.exit_code == 0, keep.output
    assert keep.output == (
        "Document a.md: kept\n"
        "Party A: candidature_declared -> manifesto_reviewed\n"
        "A\tmanifesto_reviewed\tnext: extract Proposals from a.md\n"
        "B\tcandidature_declared\tnext: review b.md\n"
    )

    discard = ingestion(
        "review", directory, "b.md", "--discard", "no-text-layer", "--note", "Escaneado"
    )
    assert discard.exit_code == 0, discard.output
    assert discard.output == (
        "Document b.md: discarded (no_text_layer)\n"
        "Party B: candidature_declared -> manifesto_reviewed\n"
        "B\tmanifesto_reviewed\tnext: extract Proposals from a.md\n"
    )
    assert ingestion("review", directory, "b.md").output.endswith(
        "Review: discarded (no_text_layer)\nNote: Escaneado\n"
    )

    none = ingestion("no-manifesto", directory, "C", "--note", "Sin programa a 26/11")
    assert none.exit_code == 0, none.output
    assert none.output == (
        "Party C: no_manifesto recorded\n"
        "Party C: candidature_declared -> excluded (no_manifesto)\n"
    )

    _record(directory, "a.md", 25)
    status = ingestion("status", directory)
    assert status.output == (
        f"Ingestion ledger {directory.name} (N = 30)\n"
        "A\texcluded\ttoo_few_proposals (25 < 30)\n"
        "B\texcluded\ttoo_few_proposals (25 < 30)\n"
        "C\texcluded\tno_manifesto: Sin programa a 26/11\n" + _footer(0, 3, 0, 0, True)
    )
    gate = ingestion("gate", directory)
    assert gate.exit_code == 0, gate.output
    assert gate.output == "Phase 4: ready (0 extracted, 3 excluded)\n"

    lower = ingestion("update", directory, "--min-proposals", "25")
    assert lower.exit_code == 0, lower.output
    assert lower.output.startswith(
        "N: 30 -> 25\n"
        "Party A: excluded (too_few_proposals, 25 < 30) -> proposals_extracted (25 proposals)\n"
        "Party B: excluded (too_few_proposals, 25 < 30) -> proposals_extracted (25 proposals)\n"
        f"Ingestion ledger {directory.name} (N = 25)\n"
        "A\tproposals_extracted\t25 proposals\n"
    )
    assert ingestion("gate", directory).output == "Phase 4: ready (2 extracted, 1 excluded)\n"


def test_discarded_at_review_detail(directory: Path) -> None:
    ingestion("review", directory, "a.md", "--discard", "not-a-manifesto")
    ingestion("review", directory, "b.md", "--discard", "incomplete")
    status = ingestion("status", directory)
    assert "A\texcluded\tdiscarded_at_review (a.md: not_a_manifesto)\n" in status.output
    assert (
        "B\texcluded\tdiscarded_at_review (a.md: not_a_manifesto; b.md: incomplete)\n"
        in status.output
    )


def test_refusals_change_nothing(directory: Path) -> None:
    assert ingestion("update", directory).exit_code == 0
    before = (directory / LEDGER_NAME).read_bytes()

    cases = [
        (("review", directory, "a.md", "--discard"), 2, "Option '--discard' requires an argument"),
        (("review", directory, "a.md", "--discard", "typo"), 2, "Invalid value for '--discard'"),
        (("review", directory, "a.md", "--keep", "--discard", "incomplete"), 2,
         "use either --keep or --discard, not both"),
        (("review", directory, "a.md", "--note", "x"), 2, "--note needs --keep or --discard"),
        (("review", directory, "z.md", "--keep"), 1,
         "Error: document 'z.md' is not listed in election.toml\n"),
        (("review", directory, "z.md"), 1, "Error: document 'z.md' is not listed"),
        (("review", directory, "a.md", "--keep", "--note", "a\nb"), 1,
         "Error: note must be a single line without control characters\n"),
        (("no-manifesto", directory, "A"), 1,
         "Error: party A lists documents (a.md); no_manifesto is only for a Party with no "
         "[[documents]]\n"),
        (("no-manifesto", directory, "C", "--undo"), 1,
         "Error: party C has no no_manifesto exclusion to undo\n"),
        (("update", directory, "--min-proposals", "0"), 2, "is not in the range 1<=x<=1000"),
    ]
    for args, code, message in cases:
        result = ingestion(*args)
        assert result.exit_code == code, (args, result.output)
        assert message in result.output, (args, result.output)
    assert (directory / LEDGER_NAME).read_bytes() == before


def test_changed_content_is_reported_then_cleared(directory: Path, tmp_path: Path) -> None:
    ingestion("review", directory, "a.md", "--keep")
    _record(directory, "a.md", 40)
    changed = DocumentSpec("a.md", "A", ["Programa nuevo de A."], ["A", "B"])
    write_bundle_v2(tmp_path / "data" / "elections", [PARTY_A, PARTY_B, PARTY_C], [changed, DOC_B])

    status = ingestion("status", directory)
    assert status.exit_code == 0
    assert status.output.startswith(
        f"Ingestion ledger {directory.name} (N = 30)\n"
        f'Warning: ledger is out of date; run "ideology ingestion update {directory}"\n'
        "A\tcandidature_declared\tnext: review a.md\n"
    )
    gate = ingestion("gate", directory)
    assert gate.exit_code == 1
    assert gate.output.startswith(
        "Error: ingestion ledger is out of date: Document a.md: review cleared (content changed) "
        f'(+2 more); run "ideology ingestion update {directory}"\n'
    )

    update = ingestion("update", directory)
    assert update.output.startswith(
        "Document a.md: review cleared (content changed)\n"
        "Document a.md: proposals cleared (content changed)\n"
        "Party A: proposals_extracted (40 proposals) -> candidature_declared\n"
        f"Ingestion ledger {directory.name} (N = 30)\n"
    )


def test_listing_a_document_clears_no_manifesto(directory: Path, tmp_path: Path) -> None:
    ingestion("no-manifesto", directory, "C")
    doc_c = DocumentSpec("c.md", "C", ["Programa de C."], ["C"])
    write_bundle_v2(
        tmp_path / "data" / "elections", [PARTY_A, PARTY_B, PARTY_C], [DOC_A, DOC_B, doc_c]
    )
    update = ingestion("update", directory)
    assert update.output.startswith(
        "Document c.md: added\n"
        "Party C: no_manifesto cleared (documents listed: c.md)\n"
        "Party C: excluded (no_manifesto) -> candidature_declared\n"
    )


def test_undo_no_manifesto(directory: Path) -> None:
    ingestion("no-manifesto", directory, "C")
    undo = ingestion("no-manifesto", directory, "C", "--undo")
    assert undo.exit_code == 0, undo.output
    assert undo.output == (
        "Party C: no_manifesto removed\n"
        "Party C: excluded (no_manifesto) -> candidature_declared\n"
    )


def test_an_invalid_ledger_is_reported_by_every_command(directory: Path) -> None:
    ingestion("update", directory)
    path = directory / LEDGER_NAME
    obj = json.loads(path.read_bytes())
    obj["parties"][1]["phase"] = "done"
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode())
    edited = path.read_bytes()
    message = f"Error: {path}: parties[1].phase: unknown phase 'done'\n"

    for args in (
        ("status", directory),
        ("gate", directory),
        ("update", directory),
        ("review", directory, "a.md"),
        ("review", directory, "a.md", "--keep"),
        ("no-manifesto", directory, "C"),
    ):
        result = ingestion(*args)
        assert result.exit_code == 1, (args, result.output)
        assert result.output.startswith(message), (args, result.output)
    assert ingestion("gate", directory).output == message + "Phase 4: blocked (1 blockers)\n"
    assert path.read_bytes() == edited

    path.unlink()
    ingestion("update", directory)
    path.write_bytes(path.read_bytes().replace(b"  ", b"\t", 1))
    status = ingestion("status", directory)
    assert status.exit_code == 1
    assert status.output == f"Error: {path}: line 2: {NOT_CANONICAL}\n"


def test_format_1_bundle_is_refused(tmp_path: Path) -> None:
    legacy = write_bundle(tmp_path / "data" / "elections")
    for args in (
        ("status", legacy),
        ("update", legacy),
        ("review", legacy, "pp.md"),
        ("review", legacy, "pp.md", "--keep"),
        ("no-manifesto", legacy, "PP"),
        ("gate", legacy),
    ):
        result = ingestion(*args)
        assert result.exit_code == 1, (args, result.output)
        assert result.output == (
            f"Error: {legacy / 'election.toml'}: the Ingestion Ledger needs a format-2 "
            "election.toml\n"
        ), args
    assert not (legacy / LEDGER_NAME).exists()


def test_bad_bundle_is_an_error(tmp_path: Path) -> None:
    result = ingestion("status", tmp_path / "missing")
    assert result.exit_code == 1
    assert "bundle directory not found" in result.output


# --- Scenario 9: no database, no run, live mode included ---------------------------------


def _snapshot(db_url: str) -> dict[str, list[tuple[Any, ...]]]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    sa.text("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
                )
            ]
            return {
                table: [tuple(r) for r in conn.execute(sa.text(f'SELECT * FROM "{table}"'))]
                for table in tables
            }
    finally:
        engine.dispose()


def test_live_mode_queues_nothing_and_the_database_is_unchanged(
    directory: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    assert runner.invoke(main, ["--database-url", db_url, "db", "upgrade"]).exit_code == 0
    imported = runner.invoke(main, ["--database-url", db_url, "data", "import", str(directory)])
    assert imported.exit_code == 0, imported.output
    before = _snapshot(db_url)
    assert before["pipeline_runs"] == []

    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("DATABASE_URL", db_url)
    for args in (
        ("update", directory),
        ("review", directory, "a.md", "--keep"),
        ("review", directory, "b.md", "--discard", "incomplete"),
        ("no-manifesto", directory, "C"),
        ("status", directory),
        ("gate", directory),
    ):
        result = runner.invoke(main, ["ingestion", *map(str, args)])
        assert result.exit_code in (0, 1), (args, result.output)
        assert "Pipeline Run" not in result.output and "queued" not in result.output

    assert _snapshot(db_url) == before


def test_commands_need_no_database(directory: Path, tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'absent.db'}"
    result = CliRunner().invoke(main, ["--database-url", url, "ingestion", "update", str(directory)])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "absent.db").exists()
