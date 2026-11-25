"""``ideology conflicts detect|list|show|decide`` (proposal-conflicts scenarios 2-7, 9, 12).

Exact output and exit codes. ``cli._provider`` is patched to a FakeProvider;
the offline guard blocks every other LLM path. Bundles live in ``tmp_path``.
"""

from pathlib import Path
from typing import Any

import pytest
from bundle_factory import write_bundle
from click.testing import CliRunner, Result
from conflict_fixtures import EXPLANATION, FLAG, P, conflict_fake, documents, setup
from pipeline_fixtures import offline_guard
from proposal_fixtures import measure, write_v2
from sqlalchemy import Engine

from ideology_app import cli
from ideology_app import ingestion_ledger as ledgers
from ideology_app.cli import main
from ideology_app.ingestion_ledger import LEDGER_NAME


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


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


@pytest.fixture
def directory(tmp_path: Path, migrated_engine: Engine) -> Path:
    return setup(tmp_path, migrated_engine)


def _tokens(result: Result) -> str:
    line = next(line for line in result.output.splitlines() if line.startswith("Calls:"))
    return line


def test_detect_list_show_decide(run, use, directory: Path) -> None:
    provider = use(conflict_fake([FLAG]))

    gate = run("ingestion", "gate", directory)
    assert gate.exit_code == 1
    assert f'Error: conflict pending: P: a.md + b.md (28): not checked; run "ideology conflicts ' \
           f'detect {directory}"' in gate.output

    result = run("conflicts", "detect", directory)
    assert result.exit_code == 0, result.output
    input_tokens = sum(len(f"{r.system} {r.prompt}".split()) for r in provider.calls)
    assert result.output == (
        "Conflict P a.md + b.md (28): 1 contradictions; pending Operator decision\n"
        f"{_tokens(result)}\n"
        "Conflicts pending: 1\n"
    )
    assert _tokens(result).startswith(f"Calls: 2 new; input_tokens {input_tokens}, output_tokens ")

    listed = run("conflicts", "list", directory)
    assert listed.exit_code == 0
    assert listed.output == "P\ta.md + b.md\t28\tpending\t1\t-\t-\nConflicts: 1; pending 1\n"

    shown = run("conflicts", "show", directory, "P", "b.md", "a.md")
    assert shown.exit_code == 0, shown.output
    assert shown.output == (
        "Conflict P a.md + b.md (28): 1 contradictions; pending Operator decision\n"
        f"#1 [housing] {EXPLANATION}\n"
        f"A a.md p.1 #1: {measure(1, 1)}\n"
        f"B b.md p.1 #2: {measure(1, 2)}\n"
    )

    status = run("ingestion", "status", directory)
    assert "Conflicts pending: 1\nPhase 4: blocked\n" in status.output

    decided = run(
        "conflicts", "decide", directory, "P", "--prevails", "a.md", "--over", "b.md",
        "--reason", "El programa nacional es posterior.",
    )
    assert decided.exit_code == 0, decided.output
    assert decided.output == (
        "Conflict P a.md + b.md: a.md prevails over b.md (El programa nacional es posterior.)\n"
        "Conflict P a.md + b.md: pending -> decided\n"
        "P\ta.md + b.md\t28\tdecided\t1\ta.md\tEl programa nacional es posterior.\n"
    )
    assert run("conflicts", "show", directory, "P", "a.md", "b.md").output.endswith(
        "Prevails: a.md (El programa nacional es posterior.)\n"
    )
    gate = run("ingestion", "gate", directory)
    assert gate.exit_code == 0, gate.output
    assert gate.output == "Phase 4: ready (1 extracted, 0 excluded)\n"

    rerun = run("conflicts", "detect", directory)
    assert rerun.output == (
        "Conflict P a.md + b.md (28): already checked; 1 contradictions; decided: a.md prevails\n"
        "Calls: 0 new; input_tokens 0, output_tokens 0\n"
        "Conflicts pending: 0\n"
    )
    assert len(provider.calls) == 2


def test_decide_refusals_keep_the_ledger_byte_identical(run, use, directory: Path) -> None:
    path = directory / LEDGER_NAME
    before = path.read_bytes()

    def refused(*args: str, error: str, code: int = 1) -> None:
        result = run("conflicts", "decide", directory, *args)
        assert result.exit_code == code, result.output
        assert error in result.output, result.output
        assert path.read_bytes() == current

    current = before
    full = ("--prevails", "a.md", "--over", "b.md", "--reason", "Motivo.")
    refused("P", *full, error=(
        f'Error: conflict P a.md + b.md is not checked yet; run "ideology conflicts detect '
        f'{directory}" first'
    ))
    use(conflict_fake())
    assert run("conflicts", "detect", directory).exit_code == 0
    current = path.read_bytes()
    refused("P", *full, error="Error: conflict P a.md + b.md has no contradiction; nothing to decide")
    refused("Z", *full, error="Error: party 'Z' is not in election.toml")
    refused("P", "--prevails", "a.md", "--over", "c.md", "--reason", "x",
            error="Error: party P has no overlap between a.md and c.md")
    refused("P", "--prevails", "a.md", "--over", "b.md",
            error="Missing option '--reason'", code=2)
    refused("P", "--prevails", "a.md", "--over", "b.md", "--reason", "dos\nlíneas",
            error="Error: reason must be a single line")


def test_out_of_date_ledger_is_refused_and_reported(
    run, use, tmp_path: Path, directory: Path
) -> None:
    use(conflict_fake([FLAG]))
    assert run("conflicts", "detect", directory).exit_code == 0
    # This small bundle misses candidatures in most Constituencies, so data check
    # always exits 1 here; only its ledger line is checked.
    assert "ingestion ledger" not in run("data", "check", directory).output

    write_v2(tmp_path, [P], documents(joint=["b.md"]))  # only joint_for changes
    path = directory / LEDGER_NAME
    before = path.read_bytes()
    out_of_date = (
        "ingestion ledger is out of date: Conflict P a.md + b.md: joint manifesto none -> b.md "
        f'(+1 more); run "ideology ingestion update {directory}"'
    )
    decided = run("conflicts", "decide", directory, "P", "--prevails", "a.md", "--over", "b.md",
                  "--reason", "Motivo.")
    assert (decided.exit_code, decided.output) == (1, f"Error: {out_of_date}\n")
    detected = run("conflicts", "detect", directory)
    assert (detected.exit_code, detected.output) == (1, f"Error: {out_of_date}\n")
    assert path.read_bytes() == before

    check = run("data", "check", directory)
    assert check.exit_code == 1
    assert f"Error: {out_of_date}\n" in check.output

    update = run("ingestion", "update", directory)
    assert update.output.startswith(
        "Conflict P a.md + b.md: joint manifesto none -> b.md\n"
        "Conflict P a.md + b.md: pending -> joint_manifesto\n"
    )
    assert "ingestion ledger" not in run("data", "check", directory).output
    assert run("ingestion", "gate", directory).exit_code == 0


def test_detect_before_extraction_exits_1(
    run, use, tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine, extract=False)
    provider = use(conflict_fake())
    result = run("conflicts", "detect", directory)
    assert result.exit_code == 1
    assert result.output == (
        "Error: Conflict P a.md + b.md (28): extract Proposals from a.md first\n"
        "Calls: 0 new; input_tokens 0, output_tokens 0\n"
        "Conflicts pending: 1\n"
        "Error: 1 overlaps not checked\n"
    )
    assert provider.calls == []


def test_budget_and_llm_error_through_the_cli(run, use, directory: Path) -> None:
    use(conflict_fake([FLAG]))
    stopped = run("conflicts", "detect", directory, "--max-calls", "1")
    assert stopped.exit_code == 0
    assert stopped.output == (
        "Stopped before Conflict P a.md + b.md (28); run again or raise --max-calls\n"
        "Calls: 0 new; input_tokens 0, output_tokens 0\n"
        "Conflicts pending: 1\n"
    )
    use(conflict_fake([FLAG], fail_on_call=1))
    failed = run("conflicts", "detect", directory)
    assert failed.exit_code == 1
    assert failed.output == (
        "Calls: 0 new; input_tokens 0, output_tokens 0\n"
        "Conflicts pending: 1\n"
        "Error: Conflict P a.md + b.md (28): provider overloaded (529)\n"
    )


def test_format_1_bundle_is_refused(run, use, tmp_path: Path, migrated_engine: Engine) -> None:
    legacy = write_bundle(tmp_path / "legacy")
    use(conflict_fake())
    message = "the Ingestion Ledger needs a format-2 election.toml"
    for args in (
        ("detect", legacy),
        ("list", legacy),
        ("show", legacy, "PP", "pp.md", "psoe.md"),
        ("decide", legacy, "PP", "--prevails", "pp.md", "--over", "psoe.md", "--reason", "x"),
    ):
        result = run("conflicts", *args)
        assert result.exit_code == 1, result.output
        assert message in result.output
    assert not (legacy / LEDGER_NAME).exists()


def test_show_unknown_overlap(run, directory: Path) -> None:
    result = run("conflicts", "show", directory, "P", "a.md", "z.md")
    assert (result.exit_code, result.output) == (
        1, "Error: party P has no overlap between a.md and z.md\n"
    )


def test_list_without_ledger_and_with_unchecked(run, tmp_path: Path, directory: Path) -> None:
    listed = run("conflicts", "list", directory)
    assert listed.output == "P\ta.md + b.md\t28\tunchecked\t0\t-\t-\nConflicts: 1; pending 1\n"
    assert ledgers.read_ledger(directory) is not None
