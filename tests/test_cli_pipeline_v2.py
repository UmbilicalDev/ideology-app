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
    assert "prompt_versions: proposal_positions=v1, statement_drafts=v1\n" in report.stdout
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

    assert "statement_selection: not recorded\nconstituencies: not recorded\n" in report.stdout


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
