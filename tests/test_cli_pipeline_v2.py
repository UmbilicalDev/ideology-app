"""``ideology pipeline run-v2`` and the v2 guards of the legacy commands (scenarios 1, 2, 8, 10),
and the v2-run-inspection commands (report sections, ``--run``, ``--sources``, ``--evidence``,
``run-queued`` skip, ``validate`` with recorded settings).

Exact output and exit codes. ``cli._provider`` is patched to a FakeProvider;
the offline guard blocks every other LLM path. Bundles live in ``tmp_path``.
"""

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from click.testing import CliRunner, Result
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from v2_fixtures import inspection_fake, one_proposal_slices, setup, v2_fake

from ideology_app import cli
from ideology_app.cli import main
from ideology_app.config import ConstituencySettings, GenerationMode
from ideology_app.constituencies import CONSTITUENCIES as CONSTITUENCY_NAMES
from ideology_app.db import session_scope
from ideology_app.models import (
    DatasetVersion,
    ModelGeneration,
    PipelineRun,
    PipelineRunCall,
    PipelineRunStatus,
    Statement,
)
from ideology_app.pipeline import v2 as pipelines_v2
from ideology_app.pipeline.v2 import positions as v2_positions
from ideology_app.pipeline.v2 import run as v2_run_module

UNAVAILABLE = ", ".join(
    f"{code:02d} fewer_than_two_parties" for code in range(1, 53) if code != 28
)
CONSTITUENCIES = (
    f"1 available, 51 unavailable ({UNAVAILABLE}); "
    "0 statements valid in no available constituency"
)
PASSED = (
    "Pipeline run {run}: passed (dataset version {version}, 2 statements, "
    "4 party positions)\n"
    "Published dataset version {version} for election 1{superseded}\n"
    f"Constituencies: {CONSTITUENCIES}\n"
)
WARNING = "Warning: pool of 2 statements is below the 200 target\n"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)
    # The fixture's one available Constituency (28) has 2 valid Statements.
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "1")
    monkeypatch.setenv("VALIDATION_V2_MIN_PARTY_SIDES", "1")


@pytest.fixture
def run(db_url: str):
    def _run(*args: str | Path) -> Result:
        return CliRunner().invoke(main, ["--database-url", db_url, *map(str, args)])

    return _run


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: Any) -> Any:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


def _count(engine: Engine, model: type) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_gate_refusal_writes_nothing(run, use, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine, exclude_x=False)
    provider = use(v2_fake())

    result = run("pipeline", "run-v2", directory)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        'Error: party X: candidature_declared (next: list a manifesto in [[documents]] or '
        'record "ingestion no-manifesto")\n'
    )
    assert provider.calls == []
    for model in (PipelineRun, PipelineRunCall, DatasetVersion, Statement):
        assert _count(migrated_engine, model) == 0


def test_not_imported_is_one_error_line(run, use, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    other = tmp_path / "other.db"
    upgrade = CliRunner().invoke(main, ["--database-url", f"sqlite:///{other}", "db", "upgrade"])
    assert upgrade.exit_code == 0

    result = CliRunner().invoke(
        main, ["--database-url", f"sqlite:///{other}", "pipeline", "run-v2", str(directory)]
    )

    assert result.exit_code == 1
    assert result.stderr == (
        f'Error: election es-general-2023-07-23 is not imported; run "ideology data import '
        f'{directory}"\n'
    )


def test_run_passes_publishes_and_replays_with_zero_calls(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    provider = use(v2_fake())

    first = run("pipeline", "run-v2", directory)

    assert first.exit_code == 0, first.output
    assert first.stdout == PASSED.format(run=1, version=1, superseded="")
    assert first.stderr == WARNING
    assert len(provider.calls) == 6

    replay_provider = use(v2_fake())
    replay = run("pipeline", "run-v2", directory, "--reuse-from", "1")
    assert replay.exit_code == 0, replay.output
    assert replay.stdout == (
        "Pipeline run 2: reusing identical calls of run 1 (6 recorded calls)\n"
        + PASSED.format(run=2, version=2, superseded=" (superseded dataset version 1)")
    )
    assert replay_provider.calls == []

    report = run("pipeline", "report", "--run", "2")
    assert report.exit_code == 0, report.output
    assert (
        "statement_selection: v2 pool 2 statements from 8 proposals (0 filtered), "
        "4 position calls\n" in report.stdout
    )
    assert "statement_agenda" not in report.stdout and "statement pool:" not in report.stdout
    assert (
        "prompt_versions: proposal_positions=v1, statement_drafts=v1, "
        "statement_rewording_check=v1\n" in report.stdout
    )
    assert f"\nconstituencies: {CONSTITUENCIES}\nrewordings: none\n" in report.stdout
    assert "\nrewordings:\n" not in report.stdout
    assert "dataset_version_status: published\n" in report.stdout
    assert f"\nconstituencies: {CONSTITUENCIES}\n" in report.stdout
    assert "constituency_order\tpassed" in report.stdout
    assert "evidence_proposals\tpassed" in report.stdout


def test_resume_after_a_failure(run, use, tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake(fail_on_call=4))
    failed = run("pipeline", "run-v2", directory)
    assert failed.exit_code == 1
    assert failed.stderr == "Error: pipeline run 1 failed: provider overloaded (529)\n"

    provider = use(v2_fake())
    again = run("pipeline", "run-v2", directory)
    assert again.exit_code == 0, again.output
    assert again.stderr.startswith(
        "Warning: election 1 has an unfinished run 1 (failed, 3 recorded calls); resume it "
        "with --resume-from 1"
    )
    assert len(provider.calls) == 6

    provider = use(v2_fake())
    resumed = run("pipeline", "run-v2", directory, "--resume-from", "1")
    assert resumed.exit_code == 0, resumed.output
    assert resumed.stdout.startswith("Pipeline run 3: resuming from run 1 (3 recorded calls)\n")
    assert len(provider.calls) == 3


def test_legacy_commands_refuse_an_election_with_candidatures(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    setup(tmp_path, migrated_engine)
    use(v2_fake())

    legacy = run("pipeline", "run", "--election", "1")
    assert legacy.exit_code == 1
    assert legacy.stderr == (
        'Error: election 1 has candidatures (format 2); run "ideology pipeline run-v2 DIR"\n'
    )
    assert _count(migrated_engine, PipelineRun) == 0

    with session_scope(migrated_engine) as session:
        session.add(
            PipelineRun(
                election_id=1, status=PipelineRunStatus.QUEUED, llm_provider="fake",
                llm_model="fake-model", generation_mode=GenerationMode.LIVE,
                prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
            )
        )
    queued = run("pipeline", "run-queued")
    assert queued.exit_code == 1
    assert queued.stderr == (
        "Error: pipeline run 1 failed: legacy run refused: election has candidatures\n"
        "Error: 1 of 1 queued pipeline runs failed\n"
    )


# --- constituency-selection-validation: defaults, settings, report, db check -----------------


def test_default_minimums_fail_the_run_and_publish_nothing(
    run, use, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = setup(tmp_path, migrated_engine)
    monkeypatch.delenv("VALIDATION_V2_MIN_STATEMENTS")
    monkeypatch.delenv("VALIDATION_V2_MIN_PARTY_SIDES")
    use(v2_fake())

    result = run("pipeline", "run-v2", directory)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: pipeline run 1 failed: validation failed: constituency_availability; "
        'see "ideology pipeline checks --run 1"\n'
    )
    report = run("pipeline", "report", "--run", "1")
    assert "dataset_version_status: candidate\n" in report.stdout
    assert (
        "\nconstituencies: 0 available, 52 unavailable (01 fewer_than_two_parties, "
        in report.stdout
    )
    assert "28 too_few_statements" in report.stdout
    assert "; 2 statements valid in no available constituency\n" in report.stdout
    checks = run("pipeline", "checks", "--run", "1")
    assert "no constituency is available" in checks.stdout


@pytest.mark.parametrize("name", ["VALIDATION_V2_MIN_STATEMENTS", "VALIDATION_V2_MIN_PARTY_SIDES"])
def test_an_invalid_minimum_is_an_error_before_anything_is_written(
    run, use, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    monkeypatch.setenv(name, "1.5")
    provider = use(v2_fake())

    result = run("pipeline", "run-v2", directory)

    assert result.exit_code == 1
    assert result.stderr == f"Error: Invalid {name} '1.5'; expected a positive integer\n"
    assert provider.calls == [] and _count(migrated_engine, PipelineRun) == 0


def test_report_without_a_dataset_version_says_not_recorded(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake(fail_on_call=1))
    assert run("pipeline", "run-v2", directory).exit_code == 1

    report = run("pipeline", "report", "--run", "1")

    assert (
        "statement_selection: not recorded\nconstituencies: not recorded\nrewordings: none\n"
        in report.stdout
    )


def test_db_check_reports_inconsistent_constituency_rows(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    # The fixture bundle covers 2 of 52 Constituencies, so db check has other errors;
    # only the Constituency row lines matter here.
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0
    line = (
        "Error: dataset version 1 has 51 constituency rows, expected one for each of the 52 "
        "constituencies\n"
    )
    assert "dataset version" not in run("db", "check").stderr

    with migrated_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM dataset_version_constituencies WHERE constituency_code = '52'")
        )
    bad = run("db", "check")
    assert bad.exit_code == 1
    assert bad.stderr.endswith(line)
    assert bad.stdout.endswith("Safe to commit: no\n")


# --- statement-rewording: the rewording file through the CLI (scenarios 1-4, R11) ------------

HOUSING = "Debe limitarse el precio del alquiler de vivienda."
ECONOMY = "Deben bajarse los impuestos a las empresas."
NEW_HOUSING = "Debe ponerse un tope al precio del alquiler de las viviendas."
REJECTED = "Deben subirse los impuestos CAMBIO a las empresas."
REWORDINGS = (
    "format = 1\n\n"
    "[[rewordings]]\n"
    f'ai_text = "{ECONOMY}"\n'
    f'text = "{REJECTED}"\n'
    'reason = "Prueba de rechazo."\n\n'
    "[[rewordings]]\n"
    f'ai_text = "{HOUSING}"\n'
    f'text = "{NEW_HOUSING}"\n'
    'reason = "«Limitarse» confunde."\n\n'
    "[[rewordings]]\n"
    'ai_text = "Esta afirmación no existe."\n'
    'text = "Otra."\n'
    'reason = "Ya no está."\n'
)


def test_rewording_run_prints_the_file_summary_and_warnings(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0
    (directory / "statement-rewordings.toml").write_text(REWORDINGS, encoding="utf-8")
    provider = use(v2_fake())

    result = run("pipeline", "run-v2", directory, "--reuse-from", "1")

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "Pipeline run 2: reusing identical calls of run 1 (6 recorded calls)\n"
        "Rewordings: statement-rewordings.toml (3 entries)\n"
        + PASSED.format(run=2, version=2, superseded=" (superseded dataset version 1)")
        + "Rewordings: 1 applied, 1 rejected, 0 duplicate, 1 not found\n"
    )
    assert result.stderr == (
        f'Warning: rewording of "{ECONOMY}": rejected: La nueva redacción cambia la medida.\n'
        'Warning: rewording of "Esta afirmación no existe.": not_found\n'
        + WARNING
    )
    assert [r.task for r in provider.calls] == ["statement_rewording_check"] * 2

    report = run("pipeline", "report", "--run", "2")
    assert report.exit_code == 0, report.output
    assert "\nrewordings: 1 applied, 1 rejected, 0 duplicate, 1 not found\n" in report.stdout
    assert (
        "\nrewordings:\n"
        "status\tstatement\tai_text\ttext\treason\texplanation\n"
        f"applied\t1\t{HOUSING}\t{NEW_HOUSING}\t«Limitarse» confunde.\t"
        "Misma medida con palabras más sencillas.\n"
        f"rejected\t2\t{ECONOMY}\t{REJECTED}\tPrueba de rechazo.\t"
        "La nueva redacción cambia la medida.\n"
        "not_found\t\tEsta afirmación no existe.\tOtra.\tYa no está.\t\n"
        "\nparties:\n"
    ) in report.stdout
    statements = run("pipeline", "statements", "--dataset-version", "2")
    assert NEW_HOUSING in statements.stdout and HOUSING not in statements.stdout

    replay_provider = use(v2_fake())
    replay = run("pipeline", "run-v2", directory, "--reuse-from", "2")
    assert replay.exit_code == 0, replay.output
    assert replay.stdout.startswith(
        "Pipeline run 3: reusing identical calls of run 2 (8 recorded calls)\n"
        "Rewordings: statement-rewordings.toml (3 entries)\n"
    )
    assert replay_provider.calls == []


ENTRY = '[[rewordings]]\nai_text = "A."\ntext = "B."\nreason = "R."\n'


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('format = 1\n[[rewordings]]\nai_text = "A."\ntext = "B."\n',
         ":entry 1: missing key 'reason'"),
        ("format = 1\n" + ENTRY + 'extra = "x"\n', ":entry 1: unknown key 'extra'"),
        ("format = 2\n" + ENTRY, ": format must be 1, got 2"),
        ('format = 1\n[[rewordings]]\nai_text = "A."\ntext = "B."\nreason = " "\n',
         ":entry 1: reason must be 1..500 characters and not blank"),
        (f'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "{"t" * 301}"\nreason = "R."\n',
         ":entry 1: text must be 1..300 characters with a non-space character"),
        ('format = 1\n[[rewordings]]\nai_text = "A."\ntext = "A."\nreason = "R."\n',
         ":entry 1: text is the same as ai_text"),
        ("format = 1\n" + ENTRY + ENTRY, ":entry 2: same ai_text as entry 1"),
        ("format = 1\n[[rewordings]\n", ": invalid TOML: "),
    ],
    ids=["missing-key", "extra-key", "format-2", "blank-reason", "long-text", "same-text",
         "repeated-ai-text", "syntax"],
)
def test_a_bad_rewording_file_is_one_error_and_writes_nothing(
    run, use, tmp_path: Path, migrated_engine: Engine, content: str, message: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    path = directory / "statement-rewordings.toml"
    path.write_text(content, encoding="utf-8")
    provider = use(v2_fake())

    result = run("pipeline", "run-v2", directory)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"Error: {path}{message}")
    assert result.stderr.count("\n") == 1
    assert provider.calls == []
    for model in (PipelineRun, PipelineRunCall, DatasetVersion, Statement):
        assert _count(migrated_engine, model) == 0


def test_data_check_ignores_the_rewording_file(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    before = run("data", "check", directory)
    (directory / "statement-rewordings.toml").write_text(REWORDINGS, encoding="utf-8")
    after = run("data", "check", directory)
    assert (after.exit_code, after.stdout, after.stderr) == (
        before.exit_code, before.stdout, before.stderr
    )


# --- v2-run-inspection: report sections, sources, Evidence, run-queued, validate ----------

CHECK_ROWS = "".join(
    f"{name}\tpassed\t\t\t\n"
    for name in (
        "evidence_quotes", "evidence_proposals", "statement_sources", "statement_uniqueness",
        "context_note", "constituency_snapshot", "constituency_validity",
        "constituency_availability", "constituency_order", "statement_rewording",
    )
)


def _constituency_table(rows: dict[str, str]) -> str:
    """The ``constituencies:`` section: ``rows`` by code, every other code unavailable
    with nobody running."""
    lines = [
        rows.get(code, f"{code}\t{name}\tno\tfewer_than_two_parties\t\t\t0\t\t\t")
        for code, name in CONSTITUENCY_NAMES
    ]
    return (
        "\nconstituencies:\n"
        "code\tname\tavailable\treason\tparties\texcluded\tvalid\tlengths\tparty_sides\t"
        "topic_max_share\n" + "".join(f"{line}\n" for line in lines)
    )


def _from(stdout: str, key: str) -> str:
    """``stdout`` from the line starting with ``key`` (timestamps come before it)."""
    return stdout[stdout.index(f"\n{key}") + 1:]


def test_v2_report_shows_the_pool_report_and_the_52_rows(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0

    report = run("pipeline", "report", "--run", "1")

    assert report.exit_code == 0, report.output
    assert report.stderr == ""
    assert _from(report.stdout, "statement_selection:") == (
        "statement_selection: v2 pool 2 statements from 8 proposals (0 filtered), "
        "4 position calls\n"
        "positions: 4 calls, 4 sided, 0 no stance, 0 slice disagreements, "
        "0 source-party no stance\n"
        f"constituencies: {CONSTITUENCIES}\n"
        "rewordings: none\n"
        "publication: published: live for election 1\n"
        "\nvalidation report:\n"
        "check\tresult\tstatement\tparty\tmessage\n"
        + CHECK_ROWS
        + "\nparties:\n"
        "party\tshort_name\tproposals\tpartial_scope\tsided\tno_stance\texcluded\n"
        "1\tP\t5\tyes\t2\t0\t\n"
        "2\tR\t3\tno\t2\t0\t\n"
        "3\tX\t\t\t\t\tno_manifesto\n"
        "\ncategories:\n"
        "category\tproposals\tcalls\tdrafted\tadditions\n"
        "housing\t4\t1\t1\t0\n"
        "economy\t4\t1\t1\t0\n"
        + _constituency_table(
            {
                "28": "28\tMadrid\tyes\t\t1,2\t3\t2\t2\t1:2/2 2:2/2\t50",
                "31": "31\tNavarra\tno\tfewer_than_two_parties\t1\t\t0\t\t1:0\t",
            }
        )
    )
    table = report.stdout.split("\nconstituencies:\n")[1].splitlines()[1:]
    assert [line.split("\t")[0] for line in table] == [c for c, _ in CONSTITUENCY_NAMES]


def test_v2_report_lists_filtered_disagreements_and_source_parties_with_no_stance(
    run, use, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v2_positions, "position_slices", one_proposal_slices)
    directory = setup(tmp_path, migrated_engine)
    use(inspection_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0

    report = run("pipeline", "report", "--run", "1")

    assert report.exit_code == 0, report.output
    assert (
        "statement_selection: v2 pool 2 statements from 8 proposals (1 filtered), "
        "8 position calls\n"
        "positions: 8 calls, 2 sided, 2 no stance, 1 slice disagreements, "
        "2 source-party no stance\n"
    ) in report.stdout
    assert _from(report.stdout, "parties:") == (
        "parties:\n"
        "party\tshort_name\tproposals\tpartial_scope\tsided\tno_stance\texcluded\n"
        "1\tP\t5\tyes\t1\t1\t\n"
        "2\tR\t3\tno\t1\t1\t\n"
        "3\tX\t\t\t\t\tno_manifesto\n"
        "\ncategories:\n"
        "category\tproposals\tcalls\tdrafted\tadditions\n"
        "housing\t4\t1\t1\t0\n"
        "economy\t4\t1\t2\t0\n"
        "\nfiltered statements:\n"
        "drafted\tstatus\ttext\n"
        "3\tduplicate\tDebe limitarse el precio del alquiler de vivienda.\n"
        "\nslice disagreements:\n"
        "statement\tparty\tcategory\tvalues\n"
        "1\t1\thousing\t2/-1/2\n"
        "\nsource parties with no stance:\n"
        "statement\tparty\n"
        "1\t1\n"
        "1\t2\n"
        + _constituency_table(
            {
                "28": "28\tMadrid\tyes\t\t1,2\t3\t1\t1\t1:1/1 2:1/1\t100",
                "31": "31\tNavarra\tno\tfewer_than_two_parties\t1\t\t0\t\t1:0\t",
            }
        )
    )


def test_v2_report_without_a_dataset_version_is_unchanged(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake(fail_on_call=1))
    assert run("pipeline", "run-v2", directory).exit_code == 1

    report = run("pipeline", "report", "--run", "1")

    assert report.exit_code == 0, report.output
    assert _from(report.stdout, "statement_selection:") == (
        "statement_selection: not recorded\n"
        "constituencies: not recorded\n"
        "rewordings: none\n"
        "publication: none: the run failed before a dataset version was created\n"
        "\nvalidation report:\n"
        "check\tresult\tstatement\tparty\tmessage\n"
    )


def test_v2_report_of_an_older_report_skips_the_missing_sections(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0
    with Session(migrated_engine) as session:
        selection = session.get(PipelineRun, 1).statement_selection
    older = {k: v for k, v in selection.items() if k not in ("constituencies", "rewordings")}
    with migrated_engine.begin() as conn:
        conn.execute(
            sa.update(PipelineRun).where(PipelineRun.id == 1).values(statement_selection=older)
        )

    report = run("pipeline", "report", "--run", "1")

    assert report.exit_code == 0, report.output
    assert "\nparties:\n" in report.stdout and "\ncategories:\n" in report.stdout
    assert "\nconstituencies:\n" not in report.stdout
    assert report.stdout.endswith("economy\t4\t1\t1\t0\n")


SOURCES_OUT = (
    "statement\trank\tproposal\tparty\tfile\tpage\texcerpt\n"
    "1\t1\t4\t1\tb.md\t1\tCongelar el alquiler en la provincia.\n"
    "1\t2\t1\t1\ta.md\t1\tBajar el precio del alquiler en todo el país.\n"
    "1\t3\t6\t2\tr.md\t1\tLiberalizar el suelo para construir más viviendas.\n"
    "1\t4\t3\t1\ta.md\t1\tConstruir más vivienda pública en alquiler.\n"
    "2\t1\t7\t2\tr.md\t1\tRebajar el impuesto de sociedades.\n"
    "2\t2\t8\t2\tr.md\t1\tEliminar el impuesto de patrimonio.\n"
    "2\t3\t2\t1\ta.md\t1\tSubir el salario mínimo cada año.\n"
    "2\t4\t5\t1\tb.md\t1\tCrear un banco público regional.\n"
)
EVIDENCE_HEADER = "statement\tparty\tvalue\trank\tproposal\tfile\tpage\tconstituencies\texcerpt\n"


def test_statement_sources_and_run_selection(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    use(v2_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0

    sources = run("pipeline", "statements", "--run", "1", "--sources")
    assert (sources.exit_code, sources.stdout, sources.stderr) == (0, SOURCES_OUT, "")
    by_version = run("pipeline", "statements", "--dataset-version", "1", "--sources")
    assert by_version.stdout == SOURCES_OUT

    for command in ("statements", "positions"):
        by_run = run("pipeline", command, "--run", "1")
        plain = run("pipeline", command, "--dataset-version", "1")
        assert by_run.exit_code == plain.exit_code == 0
        assert by_run.stdout == plain.stdout and by_run.stderr == plain.stderr == ""


def test_position_evidence(
    run, use, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(v2_positions, "position_slices", one_proposal_slices)
    directory = setup(tmp_path, migrated_engine)
    use(inspection_fake())
    assert run("pipeline", "run-v2", directory).exit_code == 0

    evidence = run("pipeline", "positions", "--run", "1", "--evidence")

    assert evidence.exit_code == 0, evidence.output
    assert evidence.stderr == ""
    assert evidence.stdout == (
        EVIDENCE_HEADER
        + "1\t1\t\t\t\t\t\t\t\n"
        "1\t2\t\t\t\t\t\t\t\n"
        "2\t1\t-1\t1\t2\ta.md\t1\tall\tSubir el salario mínimo cada año.\n"
        "2\t1\t-1\t2\t5\tb.md\t1\t28\tCrear un banco público regional.\n"
        "2\t2\t2\t1\t7\tr.md\t1\tall\tRebajar el impuesto de sociedades.\n"
        "2\t2\t2\t2\t8\tr.md\t1\tall\tEliminar el impuesto de patrimonio.\n"
    )
    party = run("pipeline", "positions", "--dataset-version", "1", "--evidence", "--party", "2")
    assert party.stdout == (
        EVIDENCE_HEADER
        + "1\t2\t\t\t\t\t\t\t\n"
        "2\t2\t2\t1\t7\tr.md\t1\tall\tRebajar el impuesto de sociedades.\n"
        "2\t2\t2\t2\t8\tr.md\t1\tall\tEliminar el impuesto de patrimonio.\n"
    )
    unknown = run("pipeline", "positions", "--run", "1", "--evidence", "--party", "9")
    assert (unknown.exit_code, unknown.stdout, unknown.stderr) == (
        1, "", "Error: party 9 not found\n"
    )


def _legacy_version(engine: Engine) -> None:
    """A legacy run 1 with an empty legacy Dataset Version 1 (election 1)."""
    with session_scope(engine) as session:
        run = PipelineRun(
            election_id=1, status=PipelineRunStatus.FAILED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
            failure_reason="validation failed: x",
        )
        session.add(run)
        session.flush()
        session.add(DatasetVersion(election_id=1, pipeline_run_id=run.id))


@pytest.mark.parametrize(
    ("args", "code", "stderr"),
    [
        (("statements",), 2, "pass exactly one of --dataset-version or --run"),
        (("positions", "--dataset-version", "1", "--run", "1"), 2,
         "pass exactly one of --dataset-version or --run"),
        (("statements", "--run", "9"), 1, "Error: pipeline run 9 not found\n"),
        (("positions", "--run", "9", "--evidence"), 1, "Error: pipeline run 9 not found\n"),
        (("statements", "--run", "2"), 1, "Error: pipeline run 2 has no dataset version\n"),
        (("statements", "--run", "1", "--sources"), 1,
         "Error: dataset version 1 is a legacy dataset version; --sources needs a v2 one\n"),
        (("positions", "--dataset-version", "1", "--evidence"), 1,
         "Error: dataset version 1 is a legacy dataset version; --evidence needs a v2 one\n"),
    ],
    ids=["neither", "both", "unknown-run", "unknown-run-evidence", "no-version",
         "legacy-sources", "legacy-evidence"],
)
def test_selection_and_flag_errors(
    run, migrated_engine: Engine, args: tuple[str, ...], code: int, stderr: str
) -> None:
    created = run(
        "election", "create", "--country", "ES", "--type", "general", "--date", "2023-07-23",
        "--name", "Elecciones",
    )
    assert created.exit_code == 0, created.output
    _legacy_version(migrated_engine)
    with session_scope(migrated_engine) as session:
        session.add(
            PipelineRun(
                election_id=1, status=PipelineRunStatus.FAILED, llm_provider="fake",
                llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
                prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
                model_generation=ModelGeneration.V2, failure_reason="x",
            )
        )
    before = _count(migrated_engine, PipelineRun), _count(migrated_engine, DatasetVersion)

    result = run("pipeline", *args)

    assert result.exit_code == code
    assert result.stdout == ""
    if code == 2:
        assert result.stderr.endswith(f"\nError: {stderr}\n")
    else:
        assert result.stderr == stderr
    after = _count(migrated_engine, PipelineRun), _count(migrated_engine, DatasetVersion)
    assert after == before


SKIPPED = (
    "Warning: pipeline run {run} is a queued v2 run and was skipped; "
    'start a new one with "ideology pipeline run-v2 DIR"\n'
)


def _queue_by_hand(engine: Engine, election_id: int, generation: ModelGeneration) -> int:
    """A ``queued`` run, as ``run-v2`` leaves it when interrupted before starting."""
    with session_scope(engine) as session:
        queued = PipelineRun(
            election_id=election_id, status=PipelineRunStatus.QUEUED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.LIVE, prompt_versions={},
            llm_calls=0, input_tokens=0, output_tokens=0, model_generation=generation,
        )
        session.add(queued)
        session.flush()
        return queued.id


def _status(engine: Engine, run_id: int) -> PipelineRunStatus:
    with Session(engine) as session:
        found = session.get(PipelineRun, run_id)
        assert found is not None
        return found.status


def test_run_queued_skips_a_queued_v2_run(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    setup(tmp_path, migrated_engine)
    provider = use(v2_fake())
    queued = _queue_by_hand(migrated_engine, 1, ModelGeneration.V2)

    result = run("pipeline", "run-queued")

    assert (result.exit_code, result.stdout, result.stderr) == (
        0, "No queued pipeline runs\n", SKIPPED.format(run=queued)
    )
    assert provider.calls == []
    assert _status(migrated_engine, queued) is PipelineRunStatus.QUEUED
    assert _count(migrated_engine, DatasetVersion) == 0


def test_run_queued_executes_only_the_legacy_run(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    setup(tmp_path, migrated_engine)
    use(v2_fake())
    v2_run_id = _queue_by_hand(migrated_engine, 1, ModelGeneration.V2)
    legacy = _queue_by_hand(migrated_engine, 1, ModelGeneration.LEGACY)

    result = run("pipeline", "run-queued")

    # The legacy run is refused on a format-2 Election, as before this feature.
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        SKIPPED.format(run=v2_run_id)
        + f"Error: pipeline run {legacy} failed: legacy run refused: election has candidatures\n"
        "Error: 1 of 1 queued pipeline runs failed\n"
    )
    assert _status(migrated_engine, v2_run_id) is PipelineRunStatus.QUEUED
    assert _status(migrated_engine, legacy) is PipelineRunStatus.FAILED


def test_run_queued_election_filters_the_skipped_runs(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    setup(tmp_path, migrated_engine)
    use(v2_fake())
    created = run(
        "election", "create", "--country", "ES", "--type", "general", "--date", "2027-01-01",
        "--name", "Otra",
    )
    assert created.exit_code == 0, created.output
    queued = _queue_by_hand(migrated_engine, 2, ModelGeneration.V2)

    other = run("pipeline", "run-queued", "--election", "1")
    assert (other.exit_code, other.stdout, other.stderr) == (0, "No queued pipeline runs\n", "")
    this = run("pipeline", "run-queued", "--election", "2")
    assert (this.exit_code, this.stdout, this.stderr) == (
        0, "No queued pipeline runs\n", SKIPPED.format(run=queued)
    )


def test_validate_uses_the_run_recorded_constituency_settings(
    run, use, tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = setup(tmp_path, migrated_engine)
    with session_scope(migrated_engine) as session:
        run_id = pipelines_v2.queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    with monkeypatch.context() as patched:
        # Leave the run in ``validating``, as after a crash before Validation.
        patched.setattr(v2_run_module, "validate_run", lambda *args, **kwargs: None)
        pipelines_v2.execute_v2_run(
            migrated_engine, run_id, v2_fake(), directory,
            constituency_settings=ConstituencySettings(2, 1),
        )
    assert _status(migrated_engine, run_id) is PipelineRunStatus.VALIDATING
    # The environment would make constituency 28 unavailable (2 valid Statements).
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "5")
    monkeypatch.setenv("VALIDATION_V2_MIN_PARTY_SIDES", "5")
    monkeypatch.setenv("VALIDATION_MAX_TOPIC_SHARE_PERCENT", "50")

    result = run("pipeline", "validate", "--run", str(run_id))

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert result.stdout == (
        "Using the run's recorded constituency settings: max_topic_share_percent=30, "
        "v2_min_party_sides=1, v2_min_statements=2\n"
        f"Pipeline run {run_id}: passed\n"
        f"Published dataset version 1 for election 1\n"
    )
    with Session(migrated_engine) as session:
        validated = session.get(PipelineRun, run_id)
        assert validated is not None and validated.validation_settings is not None
        recorded = {
            k: validated.validation_settings[k]
            for k in ("max_topic_share_percent", "v2_min_party_sides", "v2_min_statements")
        }
    assert recorded == {
        "max_topic_share_percent": 30, "v2_min_party_sides": 1, "v2_min_statements": 2,
    }
    assert "constituency_availability\tpassed" in run("pipeline", "checks", "--run", "1").stdout
