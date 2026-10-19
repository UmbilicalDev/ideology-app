"""Pipeline Run service with a temporary SQLite database and the fake provider.

Covers Scenarios 1, 2, 3 (party-blind), 5 and 6.
"""

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa
from pipeline_fixtures import (
    PAGES,
    PARTIES,
    add_parsed_document,
    fake_provider,
    offline_guard,
    seed_election,
    statements_payload,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError, add_party, create_election
from ideology_app.llm import FakeProvider, LLMOutputError, LLMProviderError, LLMRequest
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentPage,
    SourceDocumentStatus,
    Statement,
)
from ideology_app.pipeline import (
    MAX_LLM_CALLS_PER_RUN,
    NO_CANDIDATES_REASON,
    RunOutcome,
    execute_run,
    get_dataset_version,
    list_runs,
    queue_run,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    seed_election(migrated_engine)
    return migrated_engine


def queue(engine: Engine, provider: FakeProvider | None = None, election_id: int = 1) -> int:
    provider = provider or fake_provider()
    with session_scope(engine) as session:
        run = queue_run(
            session,
            election_id,
            llm_provider=provider.name,
            llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        )
        return run.id


def counts(engine: Engine) -> tuple[int, int, int]:
    with Session(engine) as s:
        return (
            s.scalar(select(func.count()).select_from(PipelineRun)) or 0,
            s.scalar(select(func.count()).select_from(DatasetVersion)) or 0,
            s.scalar(select(func.count()).select_from(Statement)) or 0,
        )


def read_run(engine: Engine, run_id: int) -> PipelineRun:
    with Session(engine, expire_on_commit=False) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        s.expunge(run)
        return run


# Scenario 1: happy path


def test_happy_path_creates_candidate_dataset_version(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.VALIDATING
    assert outcome.statement_count == 30
    assert outcome.failure_reason is None
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.VALIDATING
    assert run.llm_provider == "fake"
    assert run.llm_model == "fake-model"
    assert run.generation_mode is GenerationMode.PRECOMPUTED
    assert run.prompt_versions == {"statement_candidates": "v1", "generate_statements": "v1"}
    assert run.llm_calls == 3
    in_tokens = sum(len(f"{c.system} {c.prompt}".split()) for c in provider.calls)
    assert run.input_tokens == in_tokens
    assert run.output_tokens > 0
    assert run.failure_reason is None
    assert run.started_at is not None and run.generation_finished_at is not None
    assert run.created_at <= run.started_at <= run.generation_finished_at

    with Session(seeded) as s:
        versions = s.scalars(select(DatasetVersion)).all()
        assert len(versions) == 1
        version = versions[0]
        assert version.id == outcome.dataset_version_id
        assert version.election_id == 1
        assert version.pipeline_run_id == run_id
        assert version.status is DatasetVersionStatus.CANDIDATE
        expected = statements_payload()["statements"]
        assert [(st.position, st.text, st.topic) for st in version.statements] == [
            (i, e["text"], e["topic"]) for i, e in enumerate(expected, start=1)
        ]


def test_failed_document_is_not_sent(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        s.add(SourceDocumentPage(source_document_id=3, page_number=1, text="TEXTO-FALLIDO"))
    provider = fake_provider()
    execute_run(seeded, queue(seeded, provider), provider)

    prompts = [c.prompt for c in provider.calls if c.task == "statement_candidates"]
    assert len(prompts) == 2
    assert all("TEXTO-FALLIDO" not in p for p in prompts)
    assert PAGES[1][0] in prompts[0] and PAGES[2][1] in prompts[1]


def test_statements_are_stored_as_returned_even_if_odd(seeded: Engine) -> None:
    odd = {
        "statements": [
            {"text": "Repetida.", "topic": "economy"},
            {"text": "Repetida.", "topic": "economy"},
            {"text": " Bajar el IVA y subir el IRPF. ", "topic": "taxation"},
        ]
    }
    provider = fake_provider(generate_statements=odd)
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    assert outcome.status is PipelineRunStatus.VALIDATING
    with Session(seeded) as s:
        version = get_dataset_version(s, outcome.dataset_version_id or 0)
        assert [(st.position, st.text) for st in version.statements] == [
            (1, "Repetida."),
            (2, "Repetida."),
            (3, " Bajar el IVA y subir el IRPF. "),
        ]


# Scenario 2: lifecycle is observable


def test_lifecycle_is_observable(seeded: Engine) -> None:
    seen: dict[str, Any] = {}

    def _generate(request: LLMRequest[Any]) -> dict[str, Any]:
        with Session(seeded) as s:
            run = s.get(PipelineRun, seen["run_id"])
            assert run is not None
            seen["status_during_call"] = run.status
            seen["started_at"] = run.started_at
            seen["versions_during_call"] = s.scalar(
                select(func.count()).select_from(DatasetVersion)
            )
        return statements_payload()

    provider = fake_provider(generate_statements=_generate)
    run_id = queue(seeded, provider)
    seen["run_id"] = run_id

    queued = read_run(seeded, run_id)
    assert queued.status is PipelineRunStatus.QUEUED
    assert queued.started_at is None
    assert queued.llm_calls == 0 and queued.input_tokens == 0 and queued.output_tokens == 0

    outcome = execute_run(seeded, run_id, provider)

    assert seen["status_during_call"] is PipelineRunStatus.RUNNING
    assert seen["started_at"] is not None
    assert seen["versions_during_call"] == 0
    assert outcome.status is PipelineRunStatus.VALIDATING
    assert read_run(seeded, run_id).status is PipelineRunStatus.VALIDATING


# Scenario 3: party-blind and deterministic


def test_prompts_never_contain_party_names(seeded: Engine) -> None:
    provider = fake_provider()
    execute_run(seeded, queue(seeded, provider), provider)

    assert provider.calls
    for request in provider.calls:
        for name, short in PARTIES:
            for value in (name, short):
                assert value not in request.system
                assert value not in request.prompt


def test_two_runs_on_the_same_input_send_identical_requests(seeded: Engine) -> None:
    first, second = fake_provider(), fake_provider()
    execute_run(seeded, queue(seeded, first), first)
    execute_run(seeded, queue(seeded, second), second)
    assert first.calls == second.calls
    assert [c.task for c in first.calls] == [
        "statement_candidates",
        "statement_candidates",
        "generate_statements",
    ]
    # Exact duplicate candidates (same 3 per chunk) appear once in the reduce prompt.
    reduce_prompt = first.calls[-1].prompt
    assert reduce_prompt.count("Propuesta candidata número 0.") == 1


def test_chunks_follow_party_then_document_order(migrated_engine: Engine) -> None:
    seed_election(migrated_engine, with_failed_document=False)
    with session_scope(migrated_engine) as s:
        add_parsed_document(s, party_id=1, document_id=7, pages=["Documento siete."])
    provider = fake_provider()
    execute_run(migrated_engine, queue(migrated_engine, provider), provider)
    prompts = [c.prompt for c in provider.calls if c.task == "statement_candidates"]
    assert len(prompts) == 3
    assert PAGES[1][0] in prompts[0]
    assert "Documento siete." in prompts[1]
    assert PAGES[2][0] in prompts[2]


# Scenario 5: generation failure


def _assert_failed(engine: Engine, outcome: RunOutcome, reason: str, calls: int) -> PipelineRun:
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.dataset_version_id is None
    assert outcome.statement_count == 0
    assert outcome.failure_reason == reason
    run = read_run(engine, outcome.run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == reason
    assert run.generation_finished_at is not None
    assert run.llm_calls == calls
    assert counts(engine)[1:] == (0, 0)
    return run


def test_schema_mismatch_fails_the_run(seeded: Engine) -> None:
    provider = fake_provider(generate_statements={"statements": [{"text": "x", "topic": "?"}]})
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    run = _assert_failed(
        seeded,
        outcome,
        "FakeProvider response for task 'generate_statements' does not match "
        "StatementSet: 1 validation error(s)",
        calls=2,
    )
    assert run.input_tokens == sum(
        len(f"{c.system} {c.prompt}".split()) for c in provider.calls[:2]
    )
    assert run.output_tokens > 0


def test_provider_error_fails_the_run_and_cuts_long_reasons(seeded: Engine) -> None:
    def _boom(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMProviderError("APIStatusError (HTTP 529) " + "x" * 600)

    provider = fake_provider(statement_candidates=_boom)
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    run = _assert_failed(
        seeded, outcome, ("APIStatusError (HTTP 529) " + "x" * 600)[:500], calls=0
    )
    assert len(run.failure_reason or "") == 500
    assert run.input_tokens == 0 and run.output_tokens == 0


def test_output_error_on_a_candidates_call_fails_the_run(seeded: Engine) -> None:
    def _bad(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMOutputError("refused")

    provider = fake_provider(statement_candidates=_bad)
    _assert_failed(seeded, execute_run(seeded, queue(seeded, provider), provider), "refused", 0)


def test_no_candidates_fails_the_run(seeded: Engine) -> None:
    provider = fake_provider(statement_candidates={"candidates": []})
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    run = _assert_failed(seeded, outcome, NO_CANDIDATES_REASON, calls=2)
    assert run.input_tokens > 0


def test_too_many_chunks_fails_before_any_call(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        add_parsed_document(
            s, party_id=1, document_id=10, pages=["x" * 39_000] * (MAX_LLM_CALLS_PER_RUN - 2)
        )
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    # 198 chunks for document 10 plus one per seeded document = 200 chunks.
    _assert_failed(seeded, outcome, "too many chunks: 200 (limit 199)", calls=0)
    assert provider.calls == []


def test_unexpected_error_fails_the_run_and_is_reraised(seeded: Engine) -> None:
    def _crash(request: LLMRequest[Any]) -> dict[str, Any]:
        raise KeyError("boom")

    provider = fake_provider(generate_statements=_crash)
    run_id = queue(seeded, provider)
    with pytest.raises(KeyError):
        execute_run(seeded, run_id, provider)
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == "unexpected error: KeyError"
    assert run.llm_calls == 2
    assert counts(seeded)[1:] == (0, 0)


# Scenario 6: preconditions


def test_queue_run_unknown_election(migrated_engine: Engine) -> None:
    with pytest.raises(NotFoundError, match="^election 9 not found$"):
        queue(migrated_engine, election_id=9)
    assert counts(migrated_engine) == (0, 0, 0)


def test_queue_run_without_parsed_documents(migrated_engine: Engine) -> None:
    seed_election(migrated_engine)
    with session_scope(migrated_engine) as s:
        s.execute(
            sa.update(SourceDocument)
            .where(SourceDocument.status == SourceDocumentStatus.PARSED)
            .values(status=SourceDocumentStatus.FAILED)
        )
    with pytest.raises(InvalidInputError, match="^election 1 has no parsed source documents$"):
        queue(migrated_engine)
    assert counts(migrated_engine) == (0, 0, 0)


def test_queue_run_ignores_parsed_documents_of_other_elections(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        create_election(s, country="ES", type="general", date=dt.date(2019, 11, 10), name="2019")
        add_party(s, election_id=2, name="Otro", short_name="OT")
    with pytest.raises(InvalidInputError):
        queue(seeded, election_id=2)


def test_execute_run_rejects_a_run_that_is_not_queued(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    execute_run(seeded, run_id, provider)
    before = read_run(seeded, run_id)

    again = fake_provider()
    with pytest.raises(InvalidInputError, match="is validating, expected queued"):
        execute_run(seeded, run_id, again)
    assert again.calls == []
    after = read_run(seeded, run_id)
    assert (after.status, after.started_at, after.llm_calls) == (
        before.status,
        before.started_at,
        before.llm_calls,
    )
    assert counts(seeded) == (1, 1, 30)


@pytest.mark.parametrize(
    "other", [FakeProvider(model="other-model"), type("P", (FakeProvider,), {"name": "x"})()]
)
def test_execute_run_rejects_a_different_provider_or_model(
    seeded: Engine, other: FakeProvider
) -> None:
    run_id = queue(seeded)
    with pytest.raises(InvalidInputError, match="was queued for fake/fake-model"):
        execute_run(seeded, run_id, other)
    assert other.calls == []
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.QUEUED
    assert run.started_at is None


def test_execute_run_unknown_run(migrated_engine: Engine) -> None:
    with pytest.raises(NotFoundError, match="^pipeline run 5 not found$"):
        execute_run(migrated_engine, 5, fake_provider())


# Listing


def test_list_runs_and_get_dataset_version(seeded: Engine) -> None:
    ok = fake_provider()
    execute_run(seeded, queue(seeded, ok), ok)
    bad = fake_provider(statement_candidates={"candidates": []})
    execute_run(seeded, queue(seeded, bad), bad)

    with Session(seeded) as s:
        runs = list_runs(s, 1)
        assert [(r.id, r.status) for r in runs] == [
            (1, PipelineRunStatus.VALIDATING),
            (2, PipelineRunStatus.FAILED),
        ]
        assert runs[0].dataset_version is not None
        assert runs[1].dataset_version is None
        with pytest.raises(NotFoundError, match="^election 9 not found$"):
            list_runs(s, 9)
        with pytest.raises(NotFoundError, match="^dataset version 9 not found$"):
            get_dataset_version(s, 9)


def test_deleting_the_election_cascades(seeded: Engine) -> None:
    provider = fake_provider()
    execute_run(seeded, queue(seeded, provider), provider)
    assert counts(seeded) == (1, 1, 30)
    with seeded.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
    assert counts(seeded) == (0, 0, 0)
