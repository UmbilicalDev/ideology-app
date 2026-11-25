"""``ideology pipeline run-v2`` and the v2 guards of the legacy commands (scenarios 1, 2, 8, 10).

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
from v2_fixtures import setup, v2_fake

from ideology_app import cli
from ideology_app.cli import main
from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.models import (
    DatasetVersion,
    PipelineRun,
    PipelineRunCall,
    PipelineRunStatus,
    Statement,
)

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
    assert report.stdout.endswith(
        "\nrewordings:\n"
        "status\tstatement\tai_text\ttext\treason\texplanation\n"
        f"applied\t1\t{HOUSING}\t{NEW_HOUSING}\t«Limitarse» confunde.\t"
        "Misma medida con palabras más sencillas.\n"
        f"rejected\t2\t{ECONOMY}\t{REJECTED}\tPrueba de rechazo.\t"
        "La nueva redacción cambia la medida.\n"
        "not_found\t\tEsta afirmación no existe.\tOtra.\tYa no está.\t\n"
    )
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
