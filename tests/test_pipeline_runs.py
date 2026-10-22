"""Pipeline Run service with a temporary SQLite database and the fake provider.

Statement generation (pipeline-generate-statements Scenarios 1, 2, 3, 5, 6) and
Party Position extraction at the run level (pipeline-extract-positions
Scenarios 1, 3, 4, 6, 7 and 8). Since validation-evidence-quotes a run that
generates successfully is validated too, so the default fakes end ``passed``.
Since validation-party-coverage the default fake gives every Party a stance on
every Statement; tests that build a sparse run on purpose pass
``ValidationSettings(0)`` or expect ``party_coverage`` to fail.
"""

import datetime as dt
from typing import Any

import pytest
import sqlalchemy as sa
from pipeline_fixtures import (
    PAGES,
    PARTIES,
    add_parsed_document,
    candidate_lines,
    chunk_pages,
    fake_provider,
    offline_guard,
    positions_response,
    seed_election,
    statements_payload,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode, ValidationSettings
from ideology_app.db import session_scope
from ideology_app.elections import InvalidInputError, NotFoundError, add_party, create_election
from ideology_app.llm import FakeProvider, LLMOutputError, LLMProviderError, LLMRequest
from ideology_app.models import (
    NO_STANCE,
    DatasetVersion,
    DatasetVersionStatus,
    PartyPosition,
    PipelineRun,
    PipelineRunCall,
    PipelineRunSourceDocument,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentPage,
    SourceDocumentRole,
    SourceDocumentStatus,
    Statement,
)
from ideology_app.pipeline import (
    INTERRUPTED_REASON,
    MAX_LLM_CALLS_PER_RUN,
    MAX_POSITION_CALLS_PER_RUN,
    NO_CANDIDATES_REASON,
    RunOutcome,
    execute_run,
    get_dataset_version,
    list_positions,
    list_runs,
    list_validation_results,
    queue_run,
    validate_run,
)
from ideology_app.pipeline import positions as positions_module
from ideology_app.pipeline import runs as runs_module


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


def position_rows(engine: Engine) -> list[PartyPosition]:
    with Session(engine, expire_on_commit=False) as s:
        rows = s.scalars(select(PartyPosition).order_by(PartyPosition.id)).all()
        s.expunge_all()
        return list(rows)


def run_documents(engine: Engine, run_id: int) -> dict[int, SourceDocumentRole]:
    with Session(engine) as s:
        rows = s.scalars(
            select(PipelineRunSourceDocument).where(
                PipelineRunSourceDocument.pipeline_run_id == run_id
            )
        ).all()
        return {r.source_document_id: r.role for r in rows}


def read_run(engine: Engine, run_id: int) -> PipelineRun:
    with Session(engine, expire_on_commit=False) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        s.expunge(run)
        return run


# Scenario 1: happy path


def test_happy_path_creates_and_publishes_dataset_version(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    # pipeline-coverage-selection: a 50-Statement pool where every Statement ties,
    # so the selection is pool Statements 1..35 (max_statements).
    assert outcome.statement_count == 35
    assert outcome.failure_reason is None
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.PASSED
    assert run.llm_provider == "fake"
    assert run.llm_model == "fake-model"
    assert run.generation_mode is GenerationMode.PRECOMPUTED
    assert run.prompt_versions == {
        "statement_candidates": "v1",
        "generate_statements": "v4",
        "position_findings": "v3",
        "party_positions": "v2",
    }
    assert run.llm_calls == 7
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
        # auto-publish-dataset-version: the run passed, so its version is Published.
        assert version.status is DatasetVersionStatus.PUBLISHED
        expected = statements_payload()["statements"][:35]
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
    odd = statements_payload()
    odd["statements"][0]["text"] = "Repetida."
    odd["statements"][1]["text"] = "  REPETIDA  "
    odd["statements"][2]["text"] = " Bajar el IVA y subir el IRPF. "
    provider = fake_provider(generate_statements=odd)
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    # The selection leaves out the later duplicate (pipeline-coverage-selection);
    # the Statements it keeps are stored exactly as returned, never edited.
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    with Session(seeded) as s:
        version = get_dataset_version(s, outcome.dataset_version_id or 0)
        texts = [st.text for st in version.statements]
    assert texts[:2] == ["Repetida.", " Bajar el IVA y subir el IRPF. "]
    assert "  REPETIDA  " not in texts
    report = read_run(seeded, outcome.run_id).statement_selection
    assert report is not None
    assert report["pool"][1]["status"] == "duplicate"
    assert report["pool"][1]["duplicate_of"] == 1


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
    assert outcome.status is PipelineRunStatus.PASSED
    assert read_run(seeded, run_id).status is PipelineRunStatus.PASSED


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
        "position_findings",
        "party_positions",
        "position_findings",
        "party_positions",
    ]
    # Exact duplicate candidates (same 3 per chunk) appear once in the reduce prompt.
    reduce_prompt = first.calls[2].prompt
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
    assert position_rows(engine) == []
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
    with pytest.raises(InvalidInputError, match="is passed, expected queued"):
        execute_run(seeded, run_id, again)
    assert again.calls == []
    after = read_run(seeded, run_id)
    assert (after.status, after.started_at, after.llm_calls) == (
        before.status,
        before.started_at,
        before.llm_calls,
    )
    assert counts(seeded) == (1, 1, 35)


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
            (1, PipelineRunStatus.PASSED),
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
    assert counts(seeded) == (1, 1, 35)
    with seeded.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
    assert counts(seeded) == (0, 0, 0)


# pipeline-extract-positions Scenario 1: a position for every Statement x Party


def _scenario1_findings(request: LLMRequest[Any]) -> dict[str, Any]:
    pages = dict(chunk_pages(request))
    if pages.get(1) == PAGES[1][0]:
        return {
            "findings": [
                {"statement": 1, "value": 2, "quote": PAGES[1][0], "page": 1},
                {"statement": 2, "value": -1, "quote": PAGES[1][1], "page": 2},
            ]
        }
    return {"findings": [{"statement": 1, "value": -2, "quote": PAGES[2][0], "page": 1}]}


def _scenario1_positions(request: LLMRequest[Any]) -> dict[str, Any]:
    if candidate_lines(request)[0]["quote"] == PAGES[1][0]:
        return {
            "positions": [
                {"statement": 1, "value": 2, "evidence": 1},
                {"statement": 2, "value": -1, "evidence": 2},
            ]
        }
    return {"positions": [{"statement": 1, "value": -2, "evidence": 1}]}


def test_positions_happy_path_stores_every_statement_party_pair(seeded: Engine) -> None:
    provider = fake_provider(
        position_findings=_scenario1_findings, party_positions=_scenario1_positions
    )
    run_id = queue(seeded, provider)

    # A sparse run on purpose: coverage is not what this test checks. Only
    # Statement 1 separates the Parties, so the selection fills up to
    # min_statements (25) with non-separating ones (2..25), statement_separation
    # fails, and the Dataset Version and its rows are kept.
    outcome = execute_run(seeded, run_id, provider, ValidationSettings(0))

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: statement_separation"
    assert outcome.statement_count == 25
    assert outcome.position_count == 50
    run = read_run(seeded, run_id)
    assert run.prompt_versions == {
        "statement_candidates": "v1",
        "generate_statements": "v4",
        "position_findings": "v3",
        "party_positions": "v2",
    }
    assert [c.task for c in provider.calls] == [
        "statement_candidates",
        "statement_candidates",
        "generate_statements",
        "position_findings",
        "party_positions",
        "position_findings",
        "party_positions",
    ]
    assert run.llm_calls == 3 + 2 + 2
    assert run.input_tokens == sum(len(f"{c.system} {c.prompt}".split()) for c in provider.calls)
    assert run_documents(seeded, run_id) == {
        1: SourceDocumentRole.MAIN,
        2: SourceDocumentRole.MAIN,
    }

    with Session(seeded) as s:
        statements = s.scalars(select(Statement).order_by(Statement.position)).all()
        assert len(statements) == 25
        rows = s.scalars(select(PartyPosition)).all()
        assert len(rows) == 50
        assert {(r.statement_id, r.party_id) for r in rows} == {
            (st.id, party) for st in statements for party in (1, 2)
        }
        by_key = {(r.statement.position, r.party_id): r for r in rows}
        expected = {
            (1, 1): (2, 1, PAGES[1][0], 1),
            (2, 1): (-1, 1, PAGES[1][1], 2),
            (1, 2): (-2, 2, PAGES[2][0], 1),
        }
        for key, row in by_key.items():
            got = (row.value, row.evidence_source_document_id, row.evidence_quote,
                   row.evidence_page)
            if key in expected:
                assert got == expected[key], key
                assert row.evidence_url is None
                assert row.engine_value == expected[key][0]
            else:
                assert got == (None, None, None, None), key
                assert row.evidence_url is None
                assert row.engine_value == NO_STANCE


def test_quotes_are_stored_exactly_as_returned(seeded: Engine) -> None:
    # pipeline-verified-findings: a quote with odd case and whitespace is still
    # on its page, so it is kept and stored exactly as returned; an invented
    # quote is discarded at extraction and never stored.
    odd: dict[int, str] = {}

    def _findings(request: LLMRequest[Any]) -> dict[str, Any]:
        text = dict(chunk_pages(request))[2]
        quote = "  " + text.upper().replace(" ", "\t ", 1).replace(" ", "\n  ", 2) + "  "
        odd[len(odd) + 1] = quote
        return {
            "findings": [
                {"statement": 3, "value": 0, "quote": quote, "page": 2},
                {"statement": 4, "value": 1, "quote": "Texto que no está.", "page": 1},
            ]
        }

    provider = fake_provider(
        position_findings=_findings, party_positions=_positions((3, 0, 1), (4, 1, 2))
    )
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    # Each Party covers 1 of 25 Statements and no Statement separates them, so
    # coverage and separation fail; evidence_quotes passes.
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failed_checks == ("party_coverage", "statement_separation")
    stances = [r for r in position_rows(seeded) if r.value is not None]
    assert [(r.party_id, r.value, r.evidence_quote, r.evidence_page) for r in stances] == [
        (1, 0, odd[1], 2),
        (2, 0, odd[2], 2),
    ]
    assert all(r.evidence_quote != "Texto que no está." for r in position_rows(seeded))
    findings = read_run(seeded, outcome.run_id).statement_selection["findings"]
    assert (findings["checked"], findings["discarded"], findings["cleared"]) == (4, 2, 2)
    assert [(i["party_id"], i["reason"], i["cleared"]) for i in findings["items"]] == [
        (1, "not_found", [4]),
        (2, "not_found", [4]),
    ]


# pipeline-verified-findings Scenarios 1, 5 and 6 (run level)

SLIP = "Propuestas sobre sanidades pública."  # PAGES[1][1] says "sanidad"


def _slip_for_party1(request: LLMRequest[Any]) -> dict[str, Any]:
    """Every page as a finding (Statement n = page n); Party 1's page 2 slipped."""
    pages = chunk_pages(request)
    party1 = pages[0][1] == PAGES[1][0]
    value = 1 if party1 else -1
    return {
        "findings": [
            {
                "statement": number,
                "value": value,
                "quote": SLIP if party1 and number == 2 else text,
                "page": number,
            }
            for number, text in pages
        ]
    }


SLIP_ITEM = {
    "party_id": 1,
    "document_id": 1,
    "page": 2,
    "statement": 2,
    "value": 1,
    "reason": "not_found",
    "found_on": None,
    "cleared": [2],
    "quote": SLIP,
}


def test_slipped_finding_is_discarded_recorded_and_never_stored(seeded: Engine) -> None:
    provider = fake_provider(position_findings=_slip_for_party1)
    run_id = queue(seeded, provider)
    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    selection = read_run(seeded, run_id).statement_selection
    assert selection["findings"] == {
        "version": "v1",
        "checked": 4,
        "discarded": 1,
        "cleared": 1,
        "parties": [
            {"party_id": 1, "findings": 2, "discarded": 1, "cleared": 1},
            {"party_id": 2, "findings": 2, "discarded": 0, "cleared": 0},
        ],
        "items": [SLIP_ITEM],
    }
    assert all(r.evidence_quote != SLIP for r in position_rows(seeded))
    # The request is unchanged: the reduce still lists the slipped candidate.
    reduce = [c for c in provider.calls if c.task == "party_positions"]
    assert [c["quote"] for c in candidate_lines(reduce[0])] == [PAGES[1][0], SLIP]
    # Scenario 6: the selection saw verified findings only.
    pool = selection["pool"]
    assert pool[1]["values"][0] is None
    assert all(entry["values"][0] is not None for entry in pool if entry["pool"] != 2)
    party1 = selection["parties"][0]
    assert party1["pool_stances"] == selection["pool_size"] - 1


class _Raising:
    """A provider with the fake's name and model that fails on any call."""

    name = "fake"
    model = "fake-model"

    def generate(self, request: LLMRequest[Any]) -> Any:
        raise AssertionError(f"unexpected LLM call: {request.task}")


def _calls(engine: Engine, run_id: int) -> list[tuple[str, str, bool]]:
    with Session(engine) as s:
        rows = s.scalars(
            select(PipelineRunCall)
            .where(PipelineRunCall.pipeline_run_id == run_id)
            .order_by(PipelineRunCall.sequence)
        ).all()
        return [(r.task, r.request_hash, r.reused) for r in rows]


def test_reuse_from_replays_every_call_with_the_same_findings_record(seeded: Engine) -> None:
    # Scenario 5: the slipped finding changes no request, so a --reuse-from
    # replay reuses every call and never reaches the provider.
    first = fake_provider(position_findings=_slip_for_party1)
    source = queue(seeded, first)
    finished = execute_run(seeded, source, first)
    assert finished.dataset_version_id is not None

    with session_scope(seeded) as session:
        replay = queue_run(
            session,
            1,
            llm_provider="fake",
            llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED,
            resumed_from_run_id=source,
            allow_finished_source=True,
        ).id
    outcome = execute_run(seeded, replay, _Raising())

    recorded, replayed = _calls(seeded, source), _calls(seeded, replay)
    assert len(replayed) == len(recorded) == len(first.calls)
    assert all(reused for _, _, reused in replayed)
    assert [h for _, h, _ in replayed] == [h for _, h, _ in recorded]
    assert (outcome.status, outcome.failure_reason, outcome.statement_count) == (
        finished.status,
        finished.failure_reason,
        finished.statement_count,
    )
    assert outcome.position_count == finished.position_count
    a = read_run(seeded, source).statement_selection
    b = read_run(seeded, replay).statement_selection
    assert b == a
    assert b["findings"]["items"] == [SLIP_ITEM]


# Scenario 2 (run level): document roles and evidence from an additional document


def test_document_roles_are_recorded_and_additional_evidence_is_kept(
    migrated_engine: Engine,
) -> None:
    seed_election(migrated_engine)
    with session_scope(migrated_engine) as s:
        add_parsed_document(
            s, party_id=1, document_id=4, pages=["Anexo uno.", "Anexo dos.", "Anexo tres."]
        )
    # Without fill, so only Statements with a finding of their own get a stance.
    provider = fake_provider(party_positions=positions_response())
    run_id = queue(migrated_engine, provider)

    outcome = execute_run(migrated_engine, run_id, provider, ValidationSettings(0))

    # Sparse on purpose, so Statements 3..25 do not separate the Parties.
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: statement_separation"
    assert run_documents(migrated_engine, run_id) == {
        1: SourceDocumentRole.MAIN,
        2: SourceDocumentRole.MAIN,
        4: SourceDocumentRole.ADDITIONAL,
    }
    findings = [c for c in provider.calls if c.task == "position_findings"]
    assert len(findings) == 3
    assert PAGES[1][0] in findings[0].prompt and "Anexo uno." in findings[1].prompt
    with Session(migrated_engine) as s:
        party1 = list_positions(s, outcome.dataset_version_id or 0, 1)
        evidence = {p.statement.position: (p.evidence_source_document_id, p.evidence_quote)
                    for p in party1 if p.value is not None}
    # Statements 1 and 2 cite the main document (listed first); 3 exists only in document 4.
    assert evidence == {1: (1, PAGES[1][0]), 2: (1, PAGES[1][1]), 3: (4, "Anexo tres.")}


# Scenario 3: URL documents carry the URL locator


def test_url_documents_store_the_url_with_the_evidence(migrated_engine: Engine) -> None:
    seed_election(migrated_engine, with_failed_document=False)
    with session_scope(migrated_engine) as s:
        s.execute(
            sa.update(SourceDocument)
            .where(SourceDocument.id == 2)
            .values(origin=SourceDocumentOrigin.URL, source_url="https://example.org/programa.pdf")
        )
    provider = fake_provider()
    execute_run(migrated_engine, queue(migrated_engine, provider), provider)

    stances = {
        (r.party_id, r.evidence_page): r.evidence_url
        for r in position_rows(migrated_engine)
        if r.value is not None
    }
    assert stances == {
        (1, 1): None,
        (1, 2): None,
        (2, 1): "https://example.org/programa.pdf",
        (2, 2): "https://example.org/programa.pdf",
    }


# Scenario 4 (run level): no findings or no documents -> no stance, no reduce


def _no_party2_findings(request: LLMRequest[Any]) -> dict[str, Any]:
    pages = dict(chunk_pages(request))
    if pages.get(1) == PAGES[2][0]:
        return {"findings": []}
    return {"findings": [{"statement": 1, "value": 1, "quote": PAGES[1][0], "page": 1}]}


def _assert_party2_has_no_stance(engine: Engine, outcome: RunOutcome) -> None:
    # A Party with no stance at all fails coverage, and then no Statement
    # separates the two Parties; the run keeps every row.
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: party_coverage, statement_separation"
    assert outcome.failed_checks == ("party_coverage", "statement_separation")
    assert outcome.position_count == 50
    with Session(engine) as s:
        version = s.get(DatasetVersion, outcome.dataset_version_id)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        assert [
            (r.check_name, r.passed, [(e.statement_id, e.party_id, e.message) for e in r.entries])
            for r in list_validation_results(s, outcome.run_id)
        ] == [
            ("evidence_quotes", True, []),
            (
                "party_coverage",
                False,
                [(None, 2, "party 2 has positions on 0 of 25 statements (0%); minimum is 50%")],
            ),
            (
                "statement_separation",
                False,
                [
                    (st.id, None,
                     f"statement {st.position} does not separate parties: "
                     "only party 1 has a stance (value 1)")
                    for st in s.scalars(
                        select(Statement)
                        .where(Statement.dataset_version_id == outcome.dataset_version_id)
                        .order_by(Statement.position)
                    )
                ],
            ),
            ("statement_uniqueness", True, []),
            ("statement_count", True, []),
            ("topic_spread", True, []),
        ]
    rows = position_rows(engine)
    party2 = [r for r in rows if r.party_id == 2]
    assert len(party2) == 25
    assert all(
        (r.value, r.evidence_source_document_id, r.evidence_quote, r.evidence_page,
         r.evidence_url) == (None, None, None, None, None)
        for r in party2
    )
    # The default fake fills Party 1's one finding into every Statement.
    assert [r.value for r in rows if r.party_id == 1 and r.value is not None] == [1] * 25


def test_party_without_findings_gets_no_stance_and_no_reduce(seeded: Engine) -> None:
    provider = fake_provider(position_findings=_no_party2_findings)
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    _assert_party2_has_no_stance(seeded, outcome)
    tasks = [c.task for c in provider.calls]
    assert tasks.count("position_findings") == 2
    assert tasks.count("party_positions") == 1
    assert read_run(seeded, outcome.run_id).llm_calls == 6


def test_party_without_documents_gets_no_stance_and_no_calls(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        s.execute(
            sa.update(SourceDocument)
            .where(SourceDocument.id == 2)
            .values(status=SourceDocumentStatus.FAILED)
        )
    provider = fake_provider(position_findings=_no_party2_findings)
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    _assert_party2_has_no_stance(seeded, outcome)
    tasks = [c.task for c in provider.calls]
    assert tasks.count("position_findings") == 1
    assert tasks.count("party_positions") == 1
    assert run_documents(seeded, outcome.run_id) == {1: SourceDocumentRole.MAIN}


# Scenario 5 (run level): party-blind and deterministic across every task


def test_position_prompts_are_party_blind_and_deterministic(seeded: Engine) -> None:
    first, second = fake_provider(), fake_provider()
    execute_run(seeded, queue(seeded, first), first)
    execute_run(seeded, queue(seeded, second), second)

    assert first.calls == second.calls
    assert {c.task for c in first.calls} == {
        "statement_candidates", "generate_statements", "position_findings", "party_positions"
    }
    for request in first.calls:
        for name, short in PARTIES:
            for value in (name, short):
                assert value not in request.system
                assert value not in request.prompt
    statements = statements_payload()["statements"]
    listed = "\n".join(f"[{n}] {st['text']}" for n, st in enumerate(statements, start=1))
    for request in first.calls:
        if request.task in ("position_findings", "party_positions"):
            assert listed in request.prompt


# Scenario 6 (run level): invalid LLM output fails the run with no Dataset Version


def _findings_with(**change: Any) -> Any:
    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        finding = {"statement": 1, "value": 1, "quote": "Cita.", "page": 1} | change
        return {"findings": [finding]}

    return _respond


def _positions(*choices: tuple[int, int, int]) -> dict[str, Any]:
    return {
        "positions": [{"statement": s, "value": v, "evidence": e} for s, v, e in choices]
    }


def _raise(exc: Exception) -> Any:
    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        raise exc

    return _respond


@pytest.mark.parametrize(
    ("overrides", "reason", "calls"),
    [
        # Since pipeline-output-bounds the schema rejects unknown numbers, so the
        # call fails (and is not counted) instead of a GenerationError after it.
        (
            {"position_findings": _findings_with(statement=51)},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"position_findings": _findings_with(statement=101)},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"party_positions": _positions((51, 1, 1))},
            "FakeProvider response for task 'party_positions' does not match "
            "PositionList: 1 validation error(s)",
            4,
        ),
        (
            {"party_positions": _positions((4, 1, 1), (4, -1, 2))},
            "party_positions repeated statement 4",
            5,
        ),
        (
            {"party_positions": _positions((1, 1, 3))},
            "FakeProvider response for task 'party_positions' does not match "
            "PositionList: 1 validation error(s)",
            4,
        ),
        (
            {"party_positions": _positions((1, 3, 1))},
            "FakeProvider response for task 'party_positions' does not match "
            "PositionList: 1 validation error(s)",
            4,
        ),
        (
            {"position_findings": _findings_with(value=3)},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"position_findings": _findings_with(quote="")},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"position_findings": _findings_with(quote="x" * 501)},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"position_findings": _findings_with(page=0)},
            "FakeProvider response for task 'position_findings' does not match "
            "FindingList: 1 validation error(s)",
            3,
        ),
        (
            {"position_findings": _raise(LLMProviderError("APIStatusError (HTTP 529)"))},
            "APIStatusError (HTTP 529)",
            3,
        ),
        (
            {"party_positions": _raise(LLMProviderError("APIConnectionError"))},
            "APIConnectionError",
            4,
        ),
    ],
    ids=[
        "finding-unknown-statement",
        "finding-statement-101",
        "position-unknown-statement",
        "position-repeated-statement",
        "position-unknown-evidence",
        "position-value-3",
        "finding-value-3",
        "finding-empty-quote",
        "finding-long-quote",
        "finding-page-0",
        "findings-provider-error",
        "positions-provider-error",
    ],
)
def test_invalid_position_output_fails_the_run(
    seeded: Engine, overrides: dict[str, Any], reason: str, calls: int
) -> None:
    provider = fake_provider(**overrides)
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    run = _assert_failed(seeded, outcome, reason, calls)
    assert outcome.position_count == 0
    assert run.input_tokens == sum(
        len(f"{c.system} {c.prompt}".split()) for c in provider.calls[:calls]
    )
    assert run_documents(seeded, outcome.run_id) == {
        1: SourceDocumentRole.MAIN,
        2: SourceDocumentRole.MAIN,
    }


def test_long_position_failure_reason_is_cut(seeded: Engine) -> None:
    provider = fake_provider(party_positions=_raise(LLMProviderError("x" * 600)))
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    _assert_failed(seeded, outcome, "x" * 500, 4)


# Scenario 7: the call budget is checked before any LLM call


def test_position_call_budget_is_checked_before_any_call(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_POSITION_CALLS_PER_RUN == 300
    monkeypatch.setattr(positions_module, "MAX_POSITION_CALLS_PER_RUN", 3)
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    # 2 chunks plus one reduce per Party with documents = 4 calls.
    _assert_failed(seeded, outcome, "too many position extraction calls: 4 (limit 3)", 0)
    assert provider.calls == []


def test_position_call_budget_uses_the_real_limit(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        # Pages over half the chunk limit: one chunk each.
        add_parsed_document(s, party_id=1, document_id=10, pages=["x" * 20_001] * 297)
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    # 297 + 2 chunks, plus 2 reduces = 301 calls.
    _assert_failed(seeded, outcome, "too many position extraction calls: 301 (limit 300)", 0)
    assert provider.calls == []


def test_position_call_budget_at_the_limit_is_allowed(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(positions_module, "MAX_POSITION_CALLS_PER_RUN", 4)
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    assert outcome.status is PipelineRunStatus.PASSED


# Scenario 8: lifecycle and interruption


def test_run_is_running_during_position_extraction(seeded: Engine) -> None:
    seen: dict[str, Any] = {}
    default = fake_provider().responses["position_findings"]

    def _findings(request: LLMRequest[Any]) -> Any:
        with Session(seeded) as s:
            run = s.get(PipelineRun, seen["run_id"])
            assert run is not None
            seen["status"] = run.status
            seen["versions"] = s.scalar(select(func.count()).select_from(DatasetVersion))
            seen["statements"] = s.scalar(select(func.count()).select_from(Statement))
            seen["documents"] = s.scalar(
                select(func.count()).select_from(PipelineRunSourceDocument)
            )
        return default(request)

    provider = fake_provider(position_findings=_findings)
    seen["run_id"] = queue(seeded, provider)
    outcome = execute_run(seeded, seen["run_id"], provider)

    assert (seen["status"], seen["versions"], seen["statements"], seen["documents"]) == (
        PipelineRunStatus.RUNNING, 0, 0, 2
    )
    assert outcome.status is PipelineRunStatus.PASSED


@pytest.mark.parametrize("task", ["position_findings", "party_positions", "generate_statements"])
def test_keyboard_interrupt_marks_the_run_failed_and_reraises(seeded: Engine, task: str) -> None:
    def _interrupt(request: LLMRequest[Any]) -> dict[str, Any]:
        raise KeyboardInterrupt

    provider = fake_provider(**{task: _interrupt})
    run_id = queue(seeded, provider)
    with pytest.raises(KeyboardInterrupt):
        execute_run(seeded, run_id, provider)

    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == INTERRUPTED_REASON == "interrupted"
    assert run.generation_finished_at is not None
    assert run.llm_calls == len(provider.calls) - 1
    assert counts(seeded)[1:] == (0, 0)
    assert position_rows(seeded) == []


def test_unexpected_error_in_positions_fails_the_run_and_is_reraised(seeded: Engine) -> None:
    provider = fake_provider(party_positions=_raise(KeyError("boom")))
    run_id = queue(seeded, provider)
    with pytest.raises(KeyError):
        execute_run(seeded, run_id, provider)
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.FAILED
    assert run.failure_reason == "unexpected error: KeyError"
    assert run.llm_calls == 4
    assert position_rows(seeded) == []


# list_positions


def test_list_positions_orders_and_filters(seeded: Engine) -> None:
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    version_id = outcome.dataset_version_id or 0

    with Session(seeded) as s:
        rows = list_positions(s, version_id)
        assert [(p.statement.position, p.party_id) for p in rows] == [
            (n, party) for n in range(1, 36) for party in (1, 2)
        ]
        assert [p.party_id for p in list_positions(s, version_id, 2)] == [2] * 35
        with pytest.raises(NotFoundError, match="^dataset version 9 not found$"):
            list_positions(s, 9)
        with pytest.raises(NotFoundError, match="^party 9 not found$"):
            list_positions(s, version_id, 9)


def test_list_positions_rejects_a_party_of_another_election(seeded: Engine) -> None:
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider)
    with session_scope(seeded) as s:
        create_election(s, country="ES", type="general", date=dt.date(2019, 11, 10), name="2019")
        party = add_party(s, election_id=2, name="Otro", short_name="OT")
        other = party.id
    with Session(seeded) as s:
        with pytest.raises(NotFoundError, match=f"^party {other} not found$"):
            list_positions(s, outcome.dataset_version_id or 0, other)


def test_deleting_the_election_cascades_to_positions(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    execute_run(seeded, run_id, provider)
    assert len(position_rows(seeded)) == 70
    with seeded.begin() as conn:
        conn.execute(sa.text("DELETE FROM elections"))
    assert position_rows(seeded) == []
    assert run_documents(seeded, run_id) == {}


# live-mode-url-refetch Scenario 8: only current documents are read, and a
# re-fetched main manifesto stays main.


def test_replaced_documents_are_not_read_and_the_main_role_survives(
    migrated_engine: Engine,
) -> None:
    seed_election(migrated_engine, with_failed_document=False)
    with session_scope(migrated_engine) as s:
        # Document 1 (Party 1's main manifesto) is a URL document.
        s.execute(
            sa.text(
                "UPDATE source_documents SET origin = 'url', "
                "source_url = 'https://example.org/alfa.pdf' WHERE id = 1"
            )
        )
        add_parsed_document(s, party_id=1, document_id=4, pages=["Anexo uno."])
        add_parsed_document(
            s,
            party_id=1,
            document_id=5,
            pages=["Programa nuevo sobre vivienda.", "Programa nuevo sobre sanidad."],
            source_url="https://example.org/alfa.pdf",
        )
        s.flush()
        s.get(SourceDocument, 1).replaced_by_id = 5
    provider = fake_provider(party_positions=positions_response())
    run_id = queue(migrated_engine, provider)

    outcome = execute_run(migrated_engine, run_id, provider, ValidationSettings(0))

    assert outcome.dataset_version_id is not None
    assert run_documents(migrated_engine, run_id) == {
        5: SourceDocumentRole.MAIN,
        2: SourceDocumentRole.MAIN,
        4: SourceDocumentRole.ADDITIONAL,
    }
    findings = [c for c in provider.calls if c.task == "position_findings"]
    prompts = "\n".join(c.prompt for c in provider.calls)
    for text in PAGES[1]:
        assert text not in prompts
    # Party 1's chunks: the replacement (main) first, then the additional document.
    assert "Programa nuevo sobre vivienda." in findings[0].prompt
    assert "Anexo uno." in findings[1].prompt


def test_queue_run_finds_parsed_input_after_a_replacement(migrated_engine: Engine) -> None:
    seed_election(migrated_engine, with_failed_document=False)
    with session_scope(migrated_engine) as s:
        add_parsed_document(s, party_id=1, document_id=5, pages=["Nuevo."])
        s.get(SourceDocument, 1).replaced_by_id = 5

    run_id = queue(migrated_engine)

    assert read_run(migrated_engine, run_id).status is PipelineRunStatus.QUEUED


# pipeline-output-bounds / pipeline-coverage-selection: the pool size is
# bounded at generation (pool_bounds of the run's ValidationSettings).


@pytest.mark.parametrize("count", [20, 44, 61])
def test_out_of_range_statement_count_fails_before_any_position_call(
    seeded: Engine, count: int
) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    _assert_failed(
        seeded,
        outcome,
        "FakeProvider response for task 'generate_statements' does not match "
        "StatementSet: 1 validation error(s)",
        calls=2,
    )
    assert [c.task for c in provider.calls] == ["statement_candidates"] * 2 + [
        "generate_statements"
    ]


def test_env_statement_range_drives_generation_and_validation(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VALIDATION_MIN_STATEMENTS", "36")
    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "40")
    provider = fake_provider()
    outcome = execute_run(seeded, queue(seeded, provider), provider, None)

    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    # The selection keeps max_statements of the 50-Statement pool.
    assert outcome.statement_count == 40
    reduce = next(c for c in provider.calls if c.task == "generate_statements")
    bounds = reduce.schema.model_json_schema()["properties"]["statements"]
    assert (bounds["minItems"], bounds["maxItems"]) == (45, 60)
    assert "(como mínimo 45 y como máximo 60)" in reduce.prompt
    run = read_run(seeded, outcome.run_id)
    assert run.validation_settings["min_statements"] == 36
    assert run.validation_settings["max_statements"] == 40
    assert run.statement_selection["settings"] == run.validation_settings
    with Session(seeded) as s:
        checks = {r.check_name: r.passed for r in list_validation_results(s, outcome.run_id)}
    assert checks["statement_count"] is True

    monkeypatch.setenv("VALIDATION_MAX_STATEMENTS", "50")
    narrow = fake_provider(generate_statements=statements_payload(48))
    failed = execute_run(seeded, queue(seeded, narrow), narrow, None)
    assert failed.status is PipelineRunStatus.FAILED
    assert failed.failure_reason == (
        "FakeProvider response for task 'generate_statements' does not match "
        "StatementSet: 1 validation error(s)"
    )
    assert failed.dataset_version_id is None


# pipeline-coverage-selection: the Dataset Version holds only the selection.

# Party 1 agrees everywhere; Party 2 disagrees on odd Statements and agrees on
# even ones (which then do not separate); nobody has a stance on multiples of 3.
# Evidence alternates between each Party's two candidates (pages 1 and 2).


def _selection_findings(request: LLMRequest[Any]) -> dict[str, Any]:
    return {
        "findings": [
            {"statement": page, "value": 1, "quote": text, "page": page}
            for page, text in chunk_pages(request)
        ]
    }


def _selection_value(party_id: int, n: int) -> int | None:
    if n % 3 == 0:
        return None
    if party_id == 1:
        return 1
    return -1 if n % 2 else 1


def _selection_positions(request: LLMRequest[Any]) -> dict[str, Any]:
    party_id = 1 if candidate_lines(request)[0]["quote"] == PAGES[1][0] else 2
    numbers = [int(line.split("]")[0][1:]) for line in request.prompt.split("\n")
               if line.startswith("[") and line[1:2].isdigit()]
    return {
        "positions": [
            {"statement": n, "value": _selection_value(party_id, n), "evidence": 1 + n % 2}
            for n in sorted(set(numbers))
            if _selection_value(party_id, n) is not None
        ]
    }


def test_dataset_version_holds_only_selected_statements(seeded: Engine) -> None:
    pool = statements_payload()
    provider = fake_provider(
        generate_statements=pool,
        position_findings=_selection_findings,
        party_positions=_selection_positions,
    )
    outcome = execute_run(seeded, queue(seeded, provider), provider, ValidationSettings(0))

    report = read_run(seeded, outcome.run_id).statement_selection
    assert report is not None
    selected = [e["pool"] for e in report["pool"] if e["status"] == "selected"]
    assert selected == sorted(selected)
    assert [e["position"] for e in report["pool"] if e["status"] == "selected"] == list(
        range(1, len(selected) + 1)
    )
    # Only separating Statements (odd, not a multiple of 3) are tier 1.
    tier1 = [n for n in range(1, 51) if n % 2 and n % 3]
    assert [e["pool"] for e in report["pool"] if e["tier"] == 1] == tier1
    # 17 separate; 8 non-separating ones fill up to min_statements.
    assert len(selected) == 25 and set(tier1) <= set(selected)
    assert outcome.statement_count == 25
    assert outcome.position_count == 50
    with Session(seeded) as s:
        version = get_dataset_version(s, outcome.dataset_version_id or 0)
        statements = list(version.statements)
        assert [(st.position, st.text, st.topic) for st in statements] == [
            (i, pool["statements"][n - 1]["text"], pool["statements"][n - 1]["topic"])
            for i, n in enumerate(selected, start=1)
        ]
        rows = list_positions(s, version.id)
        got = {
            (p.statement.position, p.party_id): (
                p.value, p.evidence_source_document_id, p.evidence_quote, p.evidence_page,
                p.evidence_url,
            )
            for p in rows
        }
    assert len(got) == 50
    for position, n in enumerate(selected, start=1):
        for party_id in (1, 2):
            value = _selection_value(party_id, n)
            page = 1 + n % 2
            expected = (
                (None, None, None, None, None)
                if value is None
                else (value, party_id, PAGES[party_id][page - 1], page, None)
            )
            assert got[(position, party_id)] == expected, (position, n, party_id)


def test_llm_call_count_unchanged(migrated_engine: Engine) -> None:
    seed_election(migrated_engine)
    with session_scope(migrated_engine) as s:
        add_parsed_document(s, party_id=1, document_id=4, pages=["Anexo uno."])
    provider = fake_provider()
    outcome = execute_run(migrated_engine, queue(migrated_engine, provider), provider)

    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    chunks, parties = 3, 2
    tasks = [c.task for c in provider.calls]
    assert tasks.count("statement_candidates") == chunks
    assert tasks.count("generate_statements") == 1
    assert tasks.count("position_findings") == chunks
    assert tasks.count("party_positions") == parties
    assert read_run(migrated_engine, outcome.run_id).llm_calls == chunks + 1 + chunks + parties
    # Every position request lists the whole pool, not the selection.
    pool = statements_payload()["statements"]
    listed = "\n".join(f"[{n}] {st['text']}" for n, st in enumerate(pool, start=1))
    for request in provider.calls:
        if request.task in ("position_findings", "party_positions"):
            assert listed + "\n\n" in request.prompt


def test_selection_stored_in_finish_commit(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
        execute_run(seeded, run_id, provider, ValidationSettings())

    # Before Validation: the run is validating, with its version and its selection.
    run = read_run(seeded, run_id)
    assert run.status is PipelineRunStatus.VALIDATING
    report = run.statement_selection
    assert report is not None
    assert report["version"] == "v1"
    assert report["pool_size"] == 50 and report["selected_count"] == 35
    assert report["count_rule"] == "coverage_met"
    assert report["projected_failures"] == []
    assert report["party_ids"] == [1, 2]
    assert counts(seeded) == (1, 1, 35)

    outcome = validate_run(seeded, run_id, settings=ValidationSettings())
    assert outcome.status is PipelineRunStatus.PASSED
    # Validation never changes the stored selection.
    assert read_run(seeded, run_id).statement_selection == report


@pytest.mark.parametrize("count", [44, 61])
def test_failed_generation_stores_no_selection(seeded: Engine, count: int) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    outcome = execute_run(seeded, queue(seeded, provider), provider)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.dataset_version_id is None
    assert read_run(seeded, outcome.run_id).statement_selection is None
    assert "position_findings" not in [c.task for c in provider.calls]
