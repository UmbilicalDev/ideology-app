"""``ideology pipeline run|list|statements`` with the fake provider (Scenario 7)."""

from typing import Any

import pytest
from click.testing import CliRunner, Result
from pipeline_fixtures import fake_provider, offline_guard, seed_election, statements_payload
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.db import make_engine, run_migrations
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.models import PipelineRun

RUN_HEADER = (
    "id\tstatus\tprovider\tmodel\tmode\tdataset_version\tstatements\t"
    "llm_calls\tinput_tokens\toutput_tokens\tfailure_reason"
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def seeded(db_url: str) -> None:
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        seed_election(engine)
    finally:
        engine.dispose()


@pytest.fixture
def use_fake(monkeypatch: pytest.MonkeyPatch):
    def _use(provider: FakeProvider) -> FakeProvider:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


def run_count(db_url: str) -> int:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            return s.scalar(select(func.count()).select_from(PipelineRun)) or 0
    finally:
        engine.dispose()


def test_run_list_and_statements(run, seeded, use_fake) -> None:
    provider = use_fake(fake_provider())

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 0, result.output
    assert result.output == "Pipeline run 1: validating (dataset version 1, 30 statements)\n"
    assert len(provider.calls) == 3

    listed = run("pipeline", "list", "--election", "1")
    assert listed.exit_code == 0, listed.output
    lines = listed.output.splitlines()
    assert lines[0] == RUN_HEADER
    assert len(lines) == 2
    row = lines[1].split("\t")
    in_tokens = sum(len(f"{c.system} {c.prompt}".split()) for c in provider.calls)
    assert row[:9] == [
        "1", "validating", "fake", "fake-model", "precomputed", "1", "30", "3", str(in_tokens)
    ]
    assert int(row[9]) > 0
    assert row[10] == ""

    statements = run("pipeline", "statements", "--dataset-version", "1")
    assert statements.exit_code == 0, statements.output
    lines = statements.output.splitlines()
    assert lines[0] == "position\ttopic\ttext"
    expected = statements_payload()["statements"]
    assert lines[1:] == [f"{i}\t{e['topic']}\t{e['text']}" for i, e in enumerate(expected, 1)]


def test_live_generation_mode_is_recorded(run, seeded, use_fake, monkeypatch) -> None:
    use_fake(fake_provider())
    monkeypatch.setenv("GENERATION_MODE", "live")
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[4] == "live"


def test_failed_run_is_committed_and_reported(run, seeded, use_fake) -> None:
    use_fake(fake_provider(statement_candidates={"candidates": []}))

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Error: pipeline run 1 failed: "
        "no statement candidates were found in the source documents\n"
    )
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1] == "failed"
    assert row[5:8] == ["", "", "2"]
    assert row[10] == "no statement candidates were found in the source documents"


def test_provider_is_closed(run, seeded, use_fake) -> None:
    closed: list[bool] = []

    class ClosingFake(FakeProvider):
        def close(self) -> None:
            closed.append(True)

    provider = ClosingFake(
        {
            "statement_candidates": fake_provider().responses["statement_candidates"],
            "generate_statements": statements_payload(),
        }
    )
    use_fake(provider)
    assert run("pipeline", "run", "--election", "1").exit_code == 0
    assert closed == [True]


def test_fake_from_config_has_no_responses_and_fails(run, seeded, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == (
        "Error: pipeline run 1 failed: "
        "FakeProvider has no response for task 'statement_candidates'\n"
    )
    assert len(run("pipeline", "list", "--election", "1").output.splitlines()) == 2


def test_anthropic_without_key_fails_the_run_offline(run, seeded, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 failed: ANTHROPIC_API_KEY is not set\n"
    row = run("pipeline", "list", "--election", "1").output.splitlines()[1].split("\t")
    assert row[1:5] == ["failed", "anthropic", "claude-sonnet-5-5", "precomputed"]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("LLM_PROVIDER", "Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, fake\n"),
        (
            "GENERATION_MODE",
            "Error: Invalid GENERATION_MODE 'bogus'; supported values: precomputed, live\n",
        ),
    ],
)
def test_bad_config_creates_no_run(run, seeded, db_url, monkeypatch, name, message) -> None:
    monkeypatch.setenv(name, "bogus")

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == message
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("pipeline", "run", "--election", "9"), "Error: election 9 not found\n"),
        (("pipeline", "list", "--election", "9"), "Error: election 9 not found\n"),
        (
            ("pipeline", "statements", "--dataset-version", "9"),
            "Error: dataset version 9 not found\n",
        ),
    ],
    ids=["run", "list", "statements"],
)
def test_not_found(run, seeded, use_fake, db_url, args, message) -> None:
    provider = use_fake(fake_provider())

    result = run(*args)

    assert result.exit_code == 1
    assert result.stderr == message
    assert provider.calls == []
    assert run_count(db_url) == 0


def test_election_without_parsed_documents(run, use_fake, db_url) -> None:
    use_fake(fake_provider())
    for args in (
        ("db", "upgrade"),
        ("election", "create", "--country", "ES", "--type", "general",
         "--date", "2023-07-23", "--name", "Generales 2023"),
    ):
        assert run(*args).exit_code == 0

    result = run("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.stderr == "Error: election 1 has no parsed source documents\n"
    assert run_count(db_url) == 0


@pytest.mark.parametrize(
    "revision",
    [None, "0001", "0002", "0003"],
    ids=["not-migrated", "at-0001", "at-0002", "at-0003"],
)
@pytest.mark.parametrize(
    "args",
    [
        ("pipeline", "run", "--election", "1"),
        ("pipeline", "list", "--election", "1"),
        ("pipeline", "statements", "--dataset-version", "1"),
    ],
    ids=["run", "list", "statements"],
)
def test_requires_current_schema(
    db_url: str, use_fake, revision: str | None, args: tuple[str, ...]
) -> None:
    provider = use_fake(fake_provider())
    if revision:
        run_migrations(db_url, revision)

    result = CliRunner().invoke(main, ["--database-url", db_url, *args])

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert provider.calls == []


def test_real_provider_seam_uses_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("LLM_MODEL", "m1")
    provider: Any = cli._provider()
    assert isinstance(provider, FakeProvider)
    assert (provider.name, provider.model) == ("fake", "m1")


def test_failing_generate_call_reports_reason(run, seeded, use_fake) -> None:
    def _boom(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMProviderError("APIConnectionError")

    use_fake(fake_provider(generate_statements=_boom))
    result = run("pipeline", "run", "--election", "1")
    assert result.exit_code == 1
    assert result.stderr == "Error: pipeline run 1 failed: APIConnectionError\n"
