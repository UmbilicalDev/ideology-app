"""Pipeline Run checkpoint (pipeline-run-checkpoint) with the fake provider.

Scenarios 1-7 of docs/specs/pipeline-run-checkpoint.md. Every successful LLM
call is committed to ``pipeline_run_calls``; ``--resume-from`` reuses a stopped
run's identical calls. No API key, no network.
"""

import datetime as dt
from typing import Any

import pytest
from click.testing import CliRunner
from pipeline_fixtures import fake_provider, offline_guard, seed_election
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from ideology_app import cli
from ideology_app.cli import main
from ideology_app.config import GenerationMode
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.elections import InvalidInputError, NotFoundError, create_election
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest, LLMResult
from ideology_app.models import PipelineRun, PipelineRunCall, PipelineRunStatus, Statement
from ideology_app.pipeline import (
    CheckpointProvider,
    count_recorded_calls,
    execute_run,
    queue_run,
    request_hash,
)
from ideology_app.pipeline.prompts import CandidateList

# The default fake run: 2 candidate calls + 1 reduce, then 2 findings + 2 reduces.
DEFAULT_TASKS = [
    "statement_candidates",
    "statement_candidates",
    "generate_statements",
    "position_findings",
    "party_positions",
    "position_findings",
    "party_positions",
]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    seed_election(migrated_engine)
    return migrated_engine


class Stopping:
    """Delegates to a FakeProvider, then raises ``error`` on call number ``stop_at``."""

    def __init__(self, inner: FakeProvider, stop_at: int, error: BaseException) -> None:
        self.name = inner.name
        self.model = inner.model
        self._inner = inner
        self._stop_at = stop_at
        self._error = error
        self.count = 0

    def generate(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        self.count += 1
        if self.count == self._stop_at:
            raise self._error
        return self._inner.generate(request)


def queue(engine: Engine, provider: Any, resume_from: int | None = None) -> int:
    with session_scope(engine) as session:
        run = queue_run(
            session,
            1,
            llm_provider=provider.name,
            llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
            resumed_from_run_id=resume_from,
        )
        return run.id


def calls(engine: Engine, run_id: int) -> list[PipelineRunCall]:
    with Session(engine, expire_on_commit=False) as s:
        rows = list(
            s.scalars(
                select(PipelineRunCall)
                .where(PipelineRunCall.pipeline_run_id == run_id)
                .order_by(PipelineRunCall.sequence)
            )
        )
        s.expunge_all()
        return rows


def statements(engine: Engine, run_id: int) -> list[str]:
    with Session(engine) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None and run.dataset_version is not None
        return list(
            s.scalars(
                select(Statement.text)
                .where(Statement.dataset_version_id == run.dataset_version.id)
                .order_by(Statement.position)
            )
        )


def run_row(engine: Engine, run_id: int) -> PipelineRun:
    with Session(engine, expire_on_commit=False) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        s.expunge(run)
        return run


def stop_run(engine: Engine, stop_at: int) -> int:
    """A run whose provider fails on call ``stop_at``; it ends ``failed``."""
    provider = Stopping(fake_provider(), stop_at, LLMProviderError("usage limit beyond max wait"))
    run_id = queue(engine, provider)
    outcome = execute_run(engine, run_id, provider)
    assert outcome.status is PipelineRunStatus.FAILED
    return run_id


# Scenario 1
def test_every_call_is_recorded_in_order(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    rows = calls(seeded, run_id)
    assert [r.task for r in rows] == DEFAULT_TASKS
    assert [r.sequence for r in rows] == list(range(1, 8))
    assert not any(r.reused for r in rows)
    run = run_row(seeded, run_id)
    assert run.llm_calls == 7
    assert sum(r.input_tokens for r in rows) == run.input_tokens
    assert sum(r.output_tokens for r in rows) == run.output_tokens
    for row, request in zip(rows, provider.calls, strict=True):
        assert row.request_hash == request_hash("fake", "fake-model", request)
        assert row.output == request.schema.model_validate(row.output).model_dump(mode="json")


# Scenario 2
def test_a_failed_run_keeps_the_calls_it_made(seeded: Engine) -> None:
    run_id = stop_run(seeded, stop_at=4)

    assert [r.task for r in calls(seeded, run_id)] == DEFAULT_TASKS[:3]
    assert count_recorded_calls(seeded, run_id) == 3


# Scenario 3
@pytest.mark.parametrize("stop_at", [2, 3, 5, 7])
def test_resume_only_calls_the_provider_for_the_rest(seeded: Engine, stop_at: int) -> None:
    reference = fake_provider()
    reference_id = queue(seeded, reference)
    execute_run(seeded, reference_id, reference)
    stopped_id = stop_run(seeded, stop_at)

    provider = fake_provider()
    resumed_id = queue(seeded, provider, resume_from=stopped_id)
    outcome = execute_run(seeded, resumed_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    assert len(provider.calls) == 7 - (stop_at - 1)
    assert [c.task for c in provider.calls] == DEFAULT_TASKS[stop_at - 1 :]
    rows = calls(seeded, resumed_id)
    assert [r.task for r in rows] == DEFAULT_TASKS
    assert [r.reused for r in rows] == [True] * (stop_at - 1) + [False] * (8 - stop_at)
    assert all(r.input_tokens == r.output_tokens == 0 for r in rows if r.reused)
    run = run_row(seeded, resumed_id)
    assert run.resumed_from_run_id == stopped_id
    assert run.llm_calls == 7
    assert run.input_tokens == sum(r.input_tokens for r in rows if not r.reused)
    assert statements(seeded, resumed_id) == statements(seeded, reference_id)


def test_resume_chains_through_a_second_stop(seeded: Engine) -> None:
    first = stop_run(seeded, stop_at=3)
    second_provider = Stopping(fake_provider(), 3, LLMProviderError("stopped again"))
    second = queue(seeded, second_provider, resume_from=first)
    assert execute_run(seeded, second, second_provider).status is PipelineRunStatus.FAILED
    assert [r.reused for r in calls(seeded, second)] == [True, True, False, False]

    provider = fake_provider()
    third = queue(seeded, provider, resume_from=second)
    assert execute_run(seeded, third, provider).status is PipelineRunStatus.PASSED
    assert [c.task for c in provider.calls] == DEFAULT_TASKS[4:]


def test_without_resume_from_nothing_is_reused(seeded: Engine) -> None:
    stop_run(seeded, stop_at=5)
    provider = fake_provider()
    run_id = queue(seeded, provider)

    execute_run(seeded, run_id, provider)

    assert len(provider.calls) == 7
    assert not any(r.reused for r in calls(seeded, run_id))


# Scenario 4
def test_a_stored_output_that_no_longer_validates_is_a_miss(seeded: Engine) -> None:
    stopped_id = stop_run(seeded, stop_at=4)
    with session_scope(seeded) as session:
        session.execute(
            update(PipelineRunCall)
            .where(PipelineRunCall.pipeline_run_id == stopped_id, PipelineRunCall.sequence == 1)
            .values(output={"candidates": "not a list"})
        )
    provider = fake_provider()
    resumed_id = queue(seeded, provider, resume_from=stopped_id)

    execute_run(seeded, resumed_id, provider)

    assert [c.task for c in provider.calls][0] == "statement_candidates"
    assert len(provider.calls) == 7 - 2
    assert [r.reused for r in calls(seeded, resumed_id)][:3] == [False, True, True]


# Scenario 5
def test_resume_is_refused_for_an_unknown_run(seeded: Engine) -> None:
    with pytest.raises(NotFoundError, match="pipeline run 99 not found"):
        queue(seeded, fake_provider(), resume_from=99)


def test_resume_is_refused_for_another_model(seeded: Engine) -> None:
    stopped_id = stop_run(seeded, stop_at=3)
    with pytest.raises(InvalidInputError, match="used fake/fake-model, not fake/other"):
        queue(seeded, FakeProvider(model="other"), resume_from=stopped_id)


def test_resume_is_refused_for_another_election(seeded: Engine) -> None:
    stopped_id = stop_run(seeded, stop_at=3)
    with session_scope(seeded) as session:
        other = create_election(
            session, country="PT", type="general", date=dt.date(2024, 3, 10), name="Legislativas"
        )
        other_id = other.id
    with session_scope(seeded) as session:
        session.execute(
            update(PipelineRun).where(PipelineRun.id == stopped_id).values(election_id=other_id)
        )
    with pytest.raises(InvalidInputError, match=f"belongs to election {other_id}, not 1"):
        queue(seeded, fake_provider(), resume_from=stopped_id)


def test_resume_is_refused_for_a_run_with_a_dataset_version(seeded: Engine) -> None:
    provider = fake_provider()
    done = queue(seeded, provider)
    execute_run(seeded, done, provider)
    with pytest.raises(InvalidInputError, match="already has dataset version 1"):
        queue(seeded, fake_provider(), resume_from=done)


# Scenario 6
def test_a_run_killed_while_running_can_be_resumed(seeded: Engine) -> None:
    killed = Stopping(fake_provider(), 5, SystemExit(137))
    killed_id = queue(seeded, killed)
    with pytest.raises(SystemExit):
        execute_run(seeded, killed_id, killed)
    assert run_row(seeded, killed_id).status is PipelineRunStatus.RUNNING
    assert count_recorded_calls(seeded, killed_id) == 4

    provider = fake_provider()
    resumed_id = queue(seeded, provider, resume_from=killed_id)

    assert execute_run(seeded, resumed_id, provider).status is PipelineRunStatus.PASSED
    assert len(provider.calls) == 3


# Scenario 7 (CLI)
@pytest.fixture
def cli_db(db_url: str, monkeypatch: pytest.MonkeyPatch):
    run_migrations(db_url)
    engine = make_engine(db_url)
    try:
        seed_election(engine)
        yield db_url, engine
    finally:
        engine.dispose()


def invoke(db_url: str, *args: str):
    return CliRunner().invoke(main, ["--database-url", db_url, *args])


def test_cli_resume_from_and_report(cli_db, monkeypatch: pytest.MonkeyPatch) -> None:
    db_url, engine = cli_db
    stopping = Stopping(fake_provider(), 4, LLMProviderError("usage limit beyond max wait"))
    monkeypatch.setattr(cli, "_provider", lambda: stopping)
    first = invoke(db_url, "pipeline", "run", "--election", "1")
    assert first.exit_code == 1
    assert "Error: pipeline run 1 failed: usage limit beyond max wait" in first.output

    provider = fake_provider()
    monkeypatch.setattr(cli, "_provider", lambda: provider)
    second = invoke(db_url, "pipeline", "run", "--election", "1", "--resume-from", "1")

    assert second.exit_code == 0, second.output
    assert "Pipeline run 2: resuming from run 1 (3 recorded calls)" in second.output
    assert len(provider.calls) == 4
    report = invoke(db_url, "pipeline", "report", "--run", "2")
    assert "resumed_from: 1\n" in report.output
    assert "reused_calls: 3\n" in report.output
    assert "llm_calls: 7\n" in report.output
    first_report = invoke(db_url, "pipeline", "report", "--run", "1")
    assert "resumed_from: none\n" in first_report.output
    assert "reused_calls: 0\n" in first_report.output


def test_cli_refused_resume_creates_no_run(cli_db, monkeypatch: pytest.MonkeyPatch) -> None:
    db_url, engine = cli_db
    monkeypatch.setattr(cli, "_provider", lambda: fake_provider())

    result = invoke(db_url, "pipeline", "run", "--election", "1", "--resume-from", "7")

    assert result.exit_code == 1
    assert "pipeline run 7 not found" in result.output
    with Session(engine) as s:
        assert s.scalars(select(PipelineRun)).all() == []


# Behaviour 2: the hash covers everything that determines an answer.
def _hash_request(**changes: Any) -> LLMRequest[Any]:
    fields: dict[str, Any] = {
        "task": "statement_candidates",
        "system": "s",
        "prompt": "p",
        "schema": CandidateList,
        "max_tokens": 4096,
    }
    fields.update(changes)
    return LLMRequest(**fields)


def test_request_hash_is_stable_and_covers_every_input() -> None:
    from ideology_app.pipeline.prompts import FindingList

    base = request_hash("fake", "m", _hash_request())
    assert base == request_hash("fake", "m", _hash_request())
    variants = [
        request_hash("other", "m", _hash_request()),
        request_hash("fake", "m2", _hash_request()),
        request_hash("fake", "m", _hash_request(task="generate_statements")),
        request_hash("fake", "m", _hash_request(system="s2")),
        request_hash("fake", "m", _hash_request(prompt="p2")),
        request_hash("fake", "m", _hash_request(schema=FindingList)),
        request_hash("fake", "m", _hash_request(max_tokens=8192)),
    ]
    assert base not in variants
    assert len(set(variants)) == len(variants)


def test_recorded_calls_with_the_same_hash_are_reused_in_sequence_order(
    seeded: Engine,
) -> None:
    stopped_id = stop_run(seeded, stop_at=3)  # two statement_candidates calls recorded
    request = _hash_request()
    hash_ = request_hash("fake", "fake-model", request)
    with session_scope(seeded) as session:
        for sequence, text in ((1, "Primera propuesta."), (2, "Segunda propuesta.")):
            session.execute(
                update(PipelineRunCall)
                .where(
                    PipelineRunCall.pipeline_run_id == stopped_id,
                    PipelineRunCall.sequence == sequence,
                )
                .values(
                    request_hash=hash_,
                    output={"candidates": [{"text": text, "topic": "housing"}]},
                )
            )
    inner = fake_provider()
    new_id = queue(seeded, inner, resume_from=stopped_id)
    provider = CheckpointProvider(inner, seeded, new_id, resumed_from_run_id=stopped_id)

    first = provider.generate(request).output
    second = provider.generate(request).output

    assert [first.candidates[0].text, second.candidates[0].text] == [
        "Primera propuesta.",
        "Segunda propuesta.",
    ]
    assert inner.calls == []
