"""``ideology proposals extract|status|list`` (proposal-extraction scenarios 1, 9-11).

Exact output and exit codes. ``cli._provider`` is patched to a FakeProvider;
the offline guard blocks every other LLM path. Bundles live in ``tmp_path``.
"""

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import DocumentSpec, write_bundle
from click.testing import CliRunner, Result
from pipeline_fixtures import offline_guard
from proposal_fixtures import (
    PARTY_A,
    PARTY_B,
    big_pages,
    called_pages,
    fake,
    keep_all,
    ledger_count,
    measure,
    small_page,
    write_v2,
)

from ideology_app import cli
from ideology_app import ingestion_ledger as ledgers
from ideology_app.cli import main
from ideology_app.db import make_engine
from ideology_app.llm import FakeProvider

DOC_A = DocumentSpec("a.md", "A", big_pages(5), ["A"])
DOC_B = DocumentSpec("b.md", "B", [small_page(1, 2)], ["B"])
TABLES = ("proposal_extractions", "proposal_extraction_calls", "proposals")


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def run(db_url: str):
    def _run(*args: str | Path, url: str | None = None) -> Result:
        return CliRunner().invoke(main, ["--database-url", url or db_url, *map(str, args)])

    return _run


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: Any) -> Any:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


@pytest.fixture
def directory(tmp_path: Path, run) -> Path:
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, DOC_B])
    assert run("db", "upgrade").exit_code == 0
    assert run("data", "import", directory).exit_code == 0
    keep_all(directory, min_proposals=3)
    return directory


def _h(directory: Path, file: str) -> str:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return ledger.document(file).content_hash


def _counts(db_url: str) -> dict[str, int]:
    engine = make_engine(db_url)
    try:
        with engine.connect() as conn:
            return {t: conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one() for t in TABLES}
    finally:
        engine.dispose()


def _tokens(provider: FakeProvider) -> int:
    return sum(len(f"{r.system} {r.prompt}".split()) for r in provider.calls)


def test_scenario_1_extract_output(run, use, directory: Path) -> None:
    provider = use(fake(measures=2))

    result = run("proposals", "extract", directory)

    assert result.exit_code == 0, result.output
    a, b = _h(directory, "a.md")[:12], _h(directory, "b.md")[:12]
    none = "not_found 0, other_page 0, context_page 0, duplicate 0, no_letters 0"
    assert result.output == (
        "".join(f"Document a.md ({a}): chunk {i}/5\n" for i in range(1, 6))
        + f"Document a.md ({a}): complete: 10 proposals (dropped: {none})\n"
        "Ledger: a.md: 10 validated proposals\n"
        "Party A: proposals_extracted (10 proposals)\n"
        f"Document b.md ({b}): chunk 1/1\n"
        f"Document b.md ({b}): complete: 2 proposals (dropped: {none})\n"
        "Ledger: b.md: 2 validated proposals\n"
        "Party B: excluded (too_few_proposals, 2 < 3)\n"
        f"Calls: 6 new, 0 reused; input_tokens {_tokens(provider)}, output_tokens "
    ) + result.output.rsplit("output_tokens ", 1)[1]
    assert result.output.rsplit("output_tokens ", 1)[1].strip().isdigit()
    assert len(provider.calls) == 6

    rerun = run("proposals", "extract", directory)
    assert rerun.output == (
        f"Document a.md ({a}): reused complete extraction (10 proposals)\n"
        f"Document b.md ({b}): reused complete extraction (2 proposals)\n"
        "Calls: 0 new, 0 reused; input_tokens 0, output_tokens 0\n"
    )
    assert len(provider.calls) == 6

    status = run("proposals", "status", directory)
    assert status.exit_code == 0
    assert status.output == f"a.md\t{a}\tcomplete\t5/5\t10\t10\nb.md\t{b}\tcomplete\t1/1\t2\t2\n"

    listing = run("proposals", "list", directory, "--file", "b.md")
    assert listing.output == (
        f"1\t1\thousing\tvivienda\t{measure(1, 1)}\n2\t1\thousing\tvivienda\t{measure(1, 2)}\n"
    )
    assert run("proposals", "list", directory, "--file", "b.md", "--dropped").output == ""


def test_list_shows_text_on_one_line_and_dropped_items(run, use, directory: Path) -> None:
    def respond(request: Any) -> dict[str, Any]:
        return {
            "proposals": [
                {"text": "Medida 1 de la página 1:\nse propone", "page": 1,
                 "categories": ["economy", "taxation"], "tags": ["iva", "luz"]},
                {"text": "Nada de esto.", "page": 1, "categories": ["health"], "tags": []},
            ]
        }

    use(FakeProvider({"proposal_extraction": respond}))
    assert run("proposals", "extract", directory, "--file", "b.md").exit_code == 0

    assert run("proposals", "list", directory, "--file", "b.md").output == (
        "1\t1\teconomy,taxation\tiva,luz\tMedida 1 de la página 1: se propone\n"
    )
    assert run("proposals", "list", directory, "--file", "b.md", "--dropped").output == (
        "1\t1\tnot_found\t\tNada de esto.\n"
    )
    missing = run("proposals", "list", directory, "--file", "a.md")
    assert missing.exit_code == 1
    assert missing.output == (
        f"Error: document a.md: no complete extraction for {_h(directory, 'a.md')[:12]}...\n"
    )


def test_scenario_11_max_calls_stops_cleanly(run, use, directory: Path) -> None:
    provider = use(fake())

    result = run("proposals", "extract", directory, "--file", "a.md", "--max-calls", "2")

    assert result.exit_code == 0, result.output
    assert called_pages(provider) == [[1], [2]]
    lines = result.output.splitlines()
    assert lines[-2] == "Stopped after 2 calls; run again to continue"
    assert lines[-1].startswith("Calls: 2 new, 0 reused; ")

    nxt = use(fake())
    result = run("proposals", "extract", directory, "--file", "a.md", "--max-calls", "2")
    assert called_pages(nxt) == [[3], [4]]
    assert result.output.splitlines()[0].endswith("resuming (2/5 chunks recorded)")
    a = _h(directory, "a.md")[:12]
    assert run("proposals", "status", directory).output == (
        f"a.md\t{a}\tin_progress\t4/5\t-\t-\n"
        f"b.md\t{_h(directory, 'b.md')[:12]}\tnot_started\t0/1\t-\t-\n"
    )
    assert run("proposals", "extract", directory, "--max-calls", "0").exit_code == 2


def test_scenario_4_llm_error_exits_1_and_keeps_progress(run, use, directory: Path, db_url: str) -> None:
    use(fake(fail_on_page=3))

    result = run("proposals", "extract", directory)

    assert result.exit_code == 1
    *_, calls, error = result.output.splitlines()
    assert calls.startswith("Calls: 2 new, 0 reused; input_tokens ")
    assert error == "Error: document a.md: provider overloaded (529)"
    assert _counts(db_url) == {"proposal_extractions": 1, "proposal_extraction_calls": 2, "proposals": 0}


# --- Scenario 9: refusals ---------------------------------------------------------


def _refused(run, use, db_url: str, *args: str | Path) -> Result:
    provider = use(fake())
    before = _counts(db_url)
    result = run("proposals", "extract", *args)
    assert result.exit_code == 1, result.output
    assert provider.calls == []
    assert _counts(db_url) == before
    return result


def test_refuses_a_format_1_bundle(tmp_path: Path, run, use, db_url: str) -> None:
    assert run("db", "upgrade").exit_code == 0
    bundle = write_bundle(tmp_path / "v1")
    result = _refused(run, use, db_url, bundle)
    assert result.output == (
        f"Error: {bundle}/election.toml: the Ingestion Ledger needs a format-2 election.toml\n"
    )
    for command in (("status", bundle), ("list", bundle, "--file", "pp.md")):
        refused = run("proposals", *command)
        assert refused.exit_code == 1 and "needs a format-2 election.toml" in refused.output


def test_refuses_a_missing_or_out_of_date_ledger(
    tmp_path: Path, run, use, db_url: str, directory: Path
) -> None:
    (directory / ledgers.LEDGER_NAME).unlink()
    result = _refused(run, use, db_url, directory)
    assert result.output == (
        f'Error: no ingestion ledger yet; run "ideology ingestion update {directory}"\n'
    )
    keep_all(directory)
    write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, DocumentSpec("b.md", "B", ["Otro."], ["B"])])
    result = _refused(run, use, db_url, directory)
    assert result.output.startswith(
        "Error: ingestion ledger is out of date: Document b.md: review cleared (content changed)"
    )
    assert run("proposals", "status", directory).exit_code == 1


def test_refuses_a_non_kept_or_unlisted_file(run, use, db_url: str, directory: Path) -> None:
    ledgers.review_in_dir(
        directory, "b.md", decision=ledgers.ReviewDecision.DISCARDED, reason="incomplete"
    )
    result = _refused(run, use, db_url, directory, "--file", "b.md")
    assert result.output == (
        "Error: document b.md is discarded (incomplete); only a document reviewed kept "
        "is extracted\n"
    )
    result = _refused(run, use, db_url, directory, "--file", "c.md")
    assert result.output == "Error: document 'c.md' is not listed in election.toml\n"


def test_a_document_that_is_not_imported_fails_without_a_call(
    tmp_path: Path, run, use, db_url: str
) -> None:
    assert run("db", "upgrade").exit_code == 0
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, DOC_B])
    keep_all(directory)

    result = _refused(run, use, db_url, directory, "--file", "b.md")

    assert result.output == (
        f"Error: document b.md: content_hash {_h(directory, 'b.md')[:12]}... is not imported; "
        f'run "ideology data import {directory}"\n'
        "Calls: 0 new, 0 reused; input_tokens 0, output_tokens 0\n"
        "Error: 1 documents not extracted\n"
    )


def test_refuses_a_resume_with_another_model_and_restart_of_a_complete_one(
    run, use, db_url: str, directory: Path
) -> None:
    use(fake())
    assert run("proposals", "extract", directory, "--max-calls", "1").exit_code == 0

    use(fake(model="other"))
    other_before = _counts(db_url)
    other = run("proposals", "extract", directory)
    assert other.exit_code == 1
    assert other.output == (
        f"Error: document a.md: extraction {_h(directory, 'a.md')[:12]}... is in progress with "
        "provider fake, model fake-model, prompt proposal_extraction v1 (chunks of 12000 "
        "characters); set LLM_PROVIDER/LLM_MODEL to match, or pass --restart a.md\n"
    )
    assert _counts(db_url) == other_before

    provider = use(fake(measures=2))
    assert run("proposals", "extract", directory, "--file", "b.md").exit_code == 0
    restart = run("proposals", "extract", directory, "--restart", "b.md")
    assert restart.exit_code == 1
    assert restart.output == (
        f"Error: document b.md: extraction {_h(directory, 'b.md')[:12]}... is complete; "
        "--restart applies only to an in-progress extraction\n"
    )
    assert len(provider.calls) == 1

    before = _counts(db_url)
    outside = run("proposals", "extract", directory, "--file", "b.md", "--restart", "a.md")
    assert outside.exit_code == 1
    assert outside.output == "Error: --restart a.md must name the selected document (--file b.md)\n"
    assert _counts(db_url) == before
    assert len(provider.calls) == 1


def test_refuses_the_shared_database_without_yes(tmp_path: Path, use) -> None:
    shared = "sqlite:///data/ideology.db"

    def invoke(*args: str | Path) -> Result:
        return CliRunner().invoke(main, ["--database-url", shared, *map(str, args)])

    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, DOC_B])
    assert invoke("db", "upgrade").exit_code == 0
    assert invoke("data", "import", directory).exit_code == 0
    keep_all(directory)
    provider = use(fake())

    result = invoke("proposals", "extract", directory)

    assert result.exit_code == 1
    assert result.output == (
        "Error: refusing to generate on the shared database without confirmation; pass --yes\n"
    )
    assert provider.calls == [] and ledger_count(directory, "a.md") is None
    ok = invoke("proposals", "extract", directory, "--yes", "--file", "b.md")
    assert ok.exit_code == 0, ok.output
    assert ledger_count(directory, "b.md") == 2


def test_the_provider_comes_from_configuration(
    run, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    result = run("proposals", "extract", directory)
    assert result.exit_code == 1 and "nope" in result.output


# --- Scenario 10: the count check in status, data check and db check ------------------


def test_scenario_10_a_changed_ledger_count_is_reported(
    run, use, db_url: str, directory: Path
) -> None:
    use(fake(measures=2))
    assert run("proposals", "extract", directory).exit_code == 0
    slug = directory.name
    assert run("data", "check", directory).output == (
        f"Database matches bundle {slug}: 2 parties, 53 candidatures, 2 documents\n"
    )
    assert run("db", "check").output == "Safe to commit: yes\n"

    ledgers.record_extraction_in_dir(
        directory, "b.md", content_hash=_h(directory, "b.md"), validated_proposals=7
    )
    problem = (
        "document b.md: ledger records 7 validated proposals, the database has 2 for "
        f"{_h(directory, 'b.md')[:12]}..."
    )

    status = run("proposals", "status", directory)
    assert status.exit_code == 1
    assert status.output.endswith(f"b.md\t{_h(directory, 'b.md')[:12]}\tcomplete\t1/1\t2\t7\nError: {problem}\n")
    check = run("data", "check", directory)
    assert check.exit_code == 1
    assert check.output == (
        f"Error: {problem}\n"
        f"Error: ingestion ledger proposal counts of bundle {slug} do not match the stored "
        "Proposals: 1 problems\n"
    )
    db_check = run("db", "check")
    assert db_check.exit_code == 1
    assert db_check.output == f"Error: election 1 ({slug}): {problem}\nSafe to commit: no\n"


def test_db_check_lists_an_unfinished_extraction(run, use, directory: Path) -> None:
    use(fake())
    assert run("proposals", "extract", directory, "--max-calls", "2").exit_code == 0

    assert run("db", "check").output == (
        f"proposal extraction {_h(directory, 'a.md')[:12]}: in_progress, 2/5 chunks\n"
        "Safe to commit: yes\n"
    )
