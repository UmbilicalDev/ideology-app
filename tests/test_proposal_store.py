"""Phase 3 on the database with the fake provider (proposal-extraction scenarios 1-8, 10, 11).

Every bundle is built in ``tmp_path``; the database is the temporary migrated
one. The ledger is read and written only through ``ingestion_ledger``.
"""

import dataclasses
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import DocumentSpec
from pipeline_fixtures import offline_guard
from proposal_fixtures import (
    PARTY_A,
    PARTY_B,
    SLUG_2027,
    TASK,
    big_pages,
    called_pages,
    fake,
    import_dir,
    item,
    keep_all,
    ledger_count,
    measure,
    party_labels,
    small_page,
    write_v2,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ideology_app import ingestion_ledger as ledgers
from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.models import (
    Proposal,
    ProposalExtraction,
    ProposalExtractionCall,
    ProposalExtractionStatus,
)
from ideology_app.proposals import store
from ideology_app.proposals.store import ProposalError, RunSummary
from ideology_app.source_bundle import read_bundle

DOC_A = DocumentSpec("a.md", "A", big_pages(3), ["A"])
DOC_SHARED = DocumentSpec("shared.md", "A", big_pages(2), ["A", "B"])


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def extract(
    engine: Engine, directory: Path, provider: Any, *, max_calls: int = 300, **kw: Any
) -> tuple[RunSummary, list[str]]:
    lines: list[str] = []
    plan = store.prepare_extraction(engine, directory, provider, **kw)
    summary = store.execute_plan(
        engine,
        provider,
        plan,
        max_calls=max_calls,
        echo=lambda line, err=False: lines.append(("E " if err else "") + line),
    )
    return summary, lines


def rows(engine: Engine, model: type[Any]) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            {c.name: getattr(r, c.name) for c in model.__table__.columns}
            for r in session.scalars(select(model).order_by(model.id))
        ]


def proposals(engine: Engine, content_hash: str) -> list[tuple[Any, ...]]:
    with Session(engine) as session:
        return [
            (p.ordinal, p.chunk_index, p.page, p.text, p.categories, p.tags)
            for p in store.load_proposals(session, content_hash)
        ]


def hash_of(directory: Path, file: str) -> str:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return ledger.document(file).content_hash


@pytest.fixture
def one_doc(tmp_path: Path, migrated_engine: Engine) -> Path:
    directory = write_v2(tmp_path, [PARTY_A], [DOC_A])
    import_dir(migrated_engine, directory)
    keep_all(directory, min_proposals=3)
    return directory


# --- Scenario 1 -------------------------------------------------------------------


def test_scenario_1_happy_path_stores_proposals_and_records_the_ledger(
    migrated_engine: Engine, one_doc: Path
) -> None:
    provider = fake()

    summary, lines = extract(migrated_engine, one_doc, provider)

    assert called_pages(provider) == [[1], [2], [3]]
    content_hash = hash_of(one_doc, "a.md")
    h12 = content_hash[:12]
    assert lines == [
        f"Document a.md ({h12}): chunk 1/3",
        f"Document a.md ({h12}): chunk 2/3",
        f"Document a.md ({h12}): chunk 3/3",
        f"Document a.md ({h12}): complete: 12 proposals (dropped: not_found 0, "
        "other_page 0, context_page 0, duplicate 0, no_letters 0)",
        "Ledger: a.md: 12 validated proposals",
        "Party A: proposals_extracted (12 proposals)",
    ]
    assert (summary.budget.new_calls, summary.budget.reused_calls) == (3, 0)
    assert summary.error is None and not summary.stopped and summary.failed == []
    stored = proposals(migrated_engine, content_hash)
    assert stored[:2] == [
        (1, 0, 1, measure(1, 1), ["housing"], ["vivienda"]),
        (2, 0, 1, measure(1, 2), ["housing"], ["vivienda"]),
    ]
    assert [(p[0], p[2]) for p in stored][-1] == (12, 3)
    [extraction] = rows(migrated_engine, ProposalExtraction)
    assert extraction["status"] is ProposalExtractionStatus.COMPLETE
    assert (extraction["llm_provider"], extraction["llm_model"]) == ("fake", "fake-model")
    assert (extraction["prompt_version"], extraction["check_version"]) == ("v1", "v1")
    assert (extraction["chunk_max_chars"], extraction["chunk_count"]) == (12_000, 3)
    assert extraction["validated_count"] == 12 and extraction["completed_at"] is not None
    calls = rows(migrated_engine, ProposalExtractionCall)
    assert [(c["chunk_index"], c["first_page"], c["last_page"]) for c in calls] == [
        (0, 1, 2),
        (1, 2, 3),
        (2, 3, 3),
    ]
    assert ledger_count(one_doc, "a.md") == 12
    assert party_labels(one_doc) == {"A": "proposals_extracted (12 proposals)"}
    ledger = ledgers.read_ledger(one_doc)
    assert ledger is not None
    with Session(migrated_engine) as session:
        assert store.ledger_count_problems(session, read_bundle(one_doc), ledger) == []


# --- Scenario 2 -------------------------------------------------------------------


def test_scenario_2_misquotes_are_dropped_and_reported(
    migrated_engine: Engine, one_doc: Path
) -> None:
    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        if "[página 1]\n" not in request.prompt:
            return {"proposals": []}
        return {
            "proposals": [
                item(measure(1, 1), 1),
                item("Medida inventada que el programa no contiene.", 1),
                item(measure(3, 1), 1),
                item(measure(2, 1), 2),
                item(measure(1, 1), 1),
                item("…", 1),
            ]
        }

    _, lines = extract(migrated_engine, one_doc, FakeProvider({TASK: respond}))

    content_hash = hash_of(one_doc, "a.md")
    assert lines[3] == (
        f"Document a.md ({content_hash[:12]}): complete: 1 proposals (dropped: not_found 1, "
        "other_page 1, context_page 1, duplicate 1, no_letters 1)"
    )
    assert [p[3] for p in proposals(migrated_engine, content_hash)] == [measure(1, 1)]
    [extraction] = rows(migrated_engine, ProposalExtraction)
    assert extraction["validated_count"] == 1
    assert extraction["report"]["dropped_counts"] == {
        "not_found": 1,
        "other_page": 1,
        "context_page": 1,
        "duplicate": 1,
        "no_letters": 1,
    }
    with Session(migrated_engine) as session:
        dropped = store.dropped_items(session, content_hash)
    assert dropped[1] == {
        "chunk": 0,
        "page": 1,
        "reason": "other_page",
        "found_on": 3,
        "text": measure(3, 1),
    }
    # 1 < N = 3: the threshold exclusion follows from the ledger count.
    assert party_labels(one_doc) == {"A": "excluded (too_few_proposals, 1 < 3)"}


# --- Scenario 4 and 11: resume and budget -----------------------------------------


def test_scenario_4_resume_after_an_llm_error_makes_no_repeated_call(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    doc = DocumentSpec("a.md", "A", big_pages(5), ["A"])
    directory = write_v2(tmp_path, [PARTY_A], [doc])
    import_dir(migrated_engine, directory)
    keep_all(directory)

    first = fake(fail_on_page=3)
    summary, _ = extract(migrated_engine, directory, first)

    assert summary.error == "document a.md: provider overloaded (529)"
    assert called_pages(first) == [[1], [2], [3]]
    assert len(rows(migrated_engine, ProposalExtractionCall)) == 2
    assert ledger_count(directory, "a.md") is None

    second = fake()
    summary, lines = extract(migrated_engine, directory, second)

    assert called_pages(second) == [[3], [4], [5]]
    assert (summary.budget.new_calls, summary.budget.reused_calls) == (3, 2)
    assert lines[0].endswith("resuming (2/5 chunks recorded)")
    resumed = proposals(migrated_engine, hash_of(directory, "a.md"))

    # The same document extracted without interruption in a fresh database.
    other = tmp_path / "other"
    other.mkdir()
    from ideology_app.db import make_engine, run_migrations

    url = f"sqlite:///{other / 'o.db'}"
    run_migrations(url)
    engine = make_engine(url)
    try:
        directory2 = write_v2(other, [PARTY_A], [doc])
        import_dir(engine, directory2)
        keep_all(directory2)
        extract(engine, directory2, fake())
        assert proposals(engine, hash_of(directory2, "a.md")) == resumed
    finally:
        engine.dispose()
    assert len(resumed) == 20


def test_scenario_11_budget_stops_cleanly_and_the_next_run_continues(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    doc = DocumentSpec("a.md", "A", big_pages(5), ["A"])
    directory = write_v2(tmp_path, [PARTY_A], [doc])
    import_dir(migrated_engine, directory)
    keep_all(directory)

    provider = fake()
    summary, _ = extract(migrated_engine, directory, provider, max_calls=2)

    assert summary.stopped and summary.error is None
    assert called_pages(provider) == [[1], [2]]
    assert [c["chunk_index"] for c in rows(migrated_engine, ProposalExtractionCall)] == [0, 1]
    [extraction] = rows(migrated_engine, ProposalExtraction)
    assert extraction["status"] is ProposalExtractionStatus.IN_PROGRESS

    provider = fake()
    summary, _ = extract(migrated_engine, directory, provider, max_calls=2)
    assert called_pages(provider) == [[3], [4]] and summary.stopped
    provider = fake()
    summary, _ = extract(migrated_engine, directory, provider, max_calls=2)
    assert called_pages(provider) == [[5]] and not summary.stopped
    assert ledger_count(directory, "a.md") == 20
    with Session(migrated_engine) as session:
        assert store.unfinished_extractions(session) == []


def test_unfinished_extractions_are_listed(tmp_path: Path, migrated_engine: Engine) -> None:
    doc = DocumentSpec("a.md", "A", big_pages(5), ["A"])
    directory = write_v2(tmp_path, [PARTY_A], [doc])
    import_dir(migrated_engine, directory)
    keep_all(directory)
    extract(migrated_engine, directory, fake(), max_calls=2)

    with Session(migrated_engine) as session:
        assert store.unfinished_extractions(session) == [
            store.UnfinishedExtraction(hash_of(directory, "a.md"), 2, 5)
        ]


# --- Scenario 5: finalize-only replay -----------------------------------------------


def test_scenario_5_every_call_recorded_but_not_finalized_completes_with_zero_calls(
    migrated_engine: Engine, one_doc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("killed before finalize")

    real = store._finalize
    monkeypatch.setattr(store, "_finalize", crash)
    with pytest.raises(RuntimeError):
        extract(migrated_engine, one_doc, fake())
    assert len(rows(migrated_engine, ProposalExtractionCall)) == 3
    assert rows(migrated_engine, Proposal) == []
    monkeypatch.setattr(store, "_finalize", real)

    replay = FakeProvider({})  # any call would fail: no response for the task
    summary, lines = extract(migrated_engine, one_doc, replay)

    assert replay.calls == [] and summary.error is None
    assert (summary.budget.new_calls, summary.budget.reused_calls) == (0, 3)
    assert "complete: 12 proposals" in lines[1]
    assert ledger_count(one_doc, "a.md") == 12


# --- Scenario 6: reuse --------------------------------------------------------------


def test_scenario_6_a_rerun_after_completion_makes_no_call(
    migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake())
    before = rows(migrated_engine, Proposal)

    again = FakeProvider({})
    summary, lines = extract(migrated_engine, one_doc, again)

    assert again.calls == [] and summary.budget.new_calls == 0
    assert lines == [
        f"Document a.md ({hash_of(one_doc, 'a.md')[:12]}): reused complete extraction "
        "(12 proposals)"
    ]
    assert rows(migrated_engine, Proposal) == before


def test_scenario_6_a_shared_file_is_extracted_once_for_both_parties(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_SHARED])
    import_dir(migrated_engine, directory)
    keep_all(directory, min_proposals=3)

    provider = fake()
    _, lines = extract(migrated_engine, directory, provider)

    assert called_pages(provider) == [[1], [2]]
    assert len(rows(migrated_engine, ProposalExtraction)) == 1
    assert lines[-3:] == [
        "Ledger: shared.md: 8 validated proposals",
        "Party A: proposals_extracted (8 proposals)",
        "Party B: proposals_extracted (8 proposals)",
    ]


def test_scenario_6_the_same_bytes_in_another_election_cost_zero_calls(
    tmp_path: Path, migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake())
    directory = write_v2(tmp_path, [PARTY_A], [DOC_A], slug=SLUG_2027, date=dt.date(2027, 5, 30))
    import_dir(migrated_engine, directory)
    keep_all(directory)
    assert hash_of(directory, "a.md") == hash_of(one_doc, "a.md")

    provider = FakeProvider({})
    summary, lines = extract(migrated_engine, directory, provider)

    assert provider.calls == [] and summary.error is None
    assert lines[0].endswith("reused complete extraction (12 proposals)")
    assert ledger_count(directory, "a.md") == 12
    assert len(rows(migrated_engine, ProposalExtraction)) == 1


# --- Scenario 7: a changed document ---------------------------------------------------


def test_scenario_7_a_changed_file_gets_a_new_extraction_and_the_old_one_stays(
    tmp_path: Path, migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake())
    old_hash = hash_of(one_doc, "a.md")
    before = (
        rows(migrated_engine, ProposalExtraction),
        rows(migrated_engine, ProposalExtractionCall),
        rows(migrated_engine, Proposal),
    )

    changed = dataclasses.replace(DOC_A, pages=big_pages(2, measures=3))
    write_v2(tmp_path, [PARTY_A], [changed])
    import_dir(migrated_engine, one_doc)
    ledgers.update_in_dir(one_doc)
    ledgers.review_in_dir(one_doc, "a.md", decision=ledgers.ReviewDecision.KEPT)
    new_hash = hash_of(one_doc, "a.md")
    assert new_hash != old_hash

    provider = fake(measures=3)
    extract(migrated_engine, one_doc, provider)

    assert called_pages(provider) == [[1], [2]]
    extractions = rows(migrated_engine, ProposalExtraction)
    assert [e["content_hash"] for e in extractions] == [old_hash, new_hash]
    assert extractions[0] == before[0][0]
    assert rows(migrated_engine, ProposalExtractionCall)[:3] == before[1]
    assert rows(migrated_engine, Proposal)[:12] == before[2]
    assert len(proposals(migrated_engine, new_hash)) == 6
    assert ledger_count(one_doc, "a.md") == 6


# --- Scenario 8: summed N -----------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "label"),
    [(3, "proposals_extracted (4 proposals)"), (5, "excluded (too_few_proposals, 4 < 5)")],
)
def test_scenario_8_the_threshold_uses_the_summed_count(
    tmp_path: Path, migrated_engine: Engine, n: int, label: str
) -> None:
    docs = [
        DocumentSpec("a1.md", "A", [small_page(1, 2)], ["A"]),
        DocumentSpec("a2.md", "A", ["Segundo programa. " + small_page(1, 2)], ["A"]),
    ]
    directory = write_v2(tmp_path, [PARTY_A], docs)
    import_dir(migrated_engine, directory)
    keep_all(directory, min_proposals=n)

    extract(migrated_engine, directory, fake(measures=2))

    assert [ledger_count(directory, f) for f in ("a1.md", "a2.md")] == [2, 2]
    assert party_labels(directory) == {"A": label}


def test_a_discarded_document_is_never_extracted(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    other = DocumentSpec("b.md", "B", [small_page(1, 2)], ["B"])
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, other])
    import_dir(migrated_engine, directory)
    ledgers.update_in_dir(directory)
    ledgers.review_in_dir(directory, "a.md", decision=ledgers.ReviewDecision.KEPT)
    ledgers.review_in_dir(
        directory, "b.md", decision=ledgers.ReviewDecision.DISCARDED, reason="not_a_manifesto"
    )

    provider = fake()
    extract(migrated_engine, directory, provider)

    assert called_pages(provider) == [[1], [2], [3]]
    with pytest.raises(ProposalError, match="b.md is discarded \\(not_a_manifesto\\)"):
        store.prepare_extraction(migrated_engine, directory, provider, file="b.md")


# --- Scenario 10: count check -------------------------------------------------------


def test_scenario_10_a_ledger_count_that_differs_from_the_database_is_reported(
    migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake())
    content_hash = hash_of(one_doc, "a.md")
    bundle = read_bundle(one_doc)

    def problems() -> list[str]:
        ledger = ledgers.read_ledger(one_doc)
        assert ledger is not None
        with Session(migrated_engine) as session:
            return store.ledger_count_problems(session, bundle, ledger)

    assert problems() == []
    ledgers.record_extraction_in_dir(
        one_doc, "a.md", content_hash=content_hash, validated_proposals=40
    )
    assert problems() == [
        f"document a.md: ledger records 40 validated proposals, the database has 12 for "
        f"{content_hash[:12]}..."
    ]
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("UPDATE proposal_extractions SET status = 'in_progress'"))
    assert problems() == [
        f"document a.md: ledger records 40 validated proposals but there is no complete "
        f"extraction for {content_hash[:12]}..."
    ]


def test_the_ledger_is_rerecorded_when_its_write_failed(
    migrated_engine: Engine, one_doc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ledgers, "record_extraction_in_dir", fail)
    with pytest.raises(OSError):
        extract(migrated_engine, one_doc, fake())
    monkeypatch.undo()
    offline_guard(monkeypatch)
    assert ledger_count(one_doc, "a.md") is None

    provider = FakeProvider({})
    _, lines = extract(migrated_engine, one_doc, provider)

    assert provider.calls == []
    assert lines[1:] == [
        "Ledger: a.md: 12 validated proposals",
        "Party A: proposals_extracted (12 proposals)",
    ]


# --- Pinning, restart and the documented checks -------------------------------------


def test_a_resume_is_pinned_to_provider_and_model(
    migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake(), max_calls=1)
    before = rows(migrated_engine, ProposalExtractionCall)
    other = fake(model="other-model")

    with pytest.raises(ProposalError) as raised:
        extract(migrated_engine, one_doc, other)

    assert str(raised.value) == (
        f"document a.md: extraction {hash_of(one_doc, 'a.md')[:12]}... is in progress with "
        "provider fake, model fake-model, prompt proposal_extraction v1 (chunks of 12000 "
        "characters); set LLM_PROVIDER/LLM_MODEL to match, or pass --restart a.md"
    )
    assert other.calls == [] and rows(migrated_engine, ProposalExtractionCall) == before


def test_restart_deletes_an_in_progress_extraction_and_refuses_a_complete_one(
    migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake(), max_calls=1)
    other = fake(model="other-model")

    summary, lines = extract(migrated_engine, one_doc, other, restart="a.md")

    assert lines[0].endswith("restarted (1 recorded calls deleted)")
    assert called_pages(other) == [[1], [2], [3]] and summary.error is None
    [extraction] = rows(migrated_engine, ProposalExtraction)
    assert extraction["llm_model"] == "other-model"
    with pytest.raises(ProposalError, match="is complete; --restart applies only"):
        store.prepare_extraction(migrated_engine, one_doc, other, restart="a.md")


def test_a_recorded_call_with_another_request_is_refused(
    migrated_engine: Engine, one_doc: Path
) -> None:
    extract(migrated_engine, one_doc, fake(), max_calls=1)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("UPDATE proposal_extraction_calls SET request_hash = 'x'"))
    provider = fake()

    with pytest.raises(ProposalError, match="or pass --restart a.md"):
        extract(migrated_engine, one_doc, provider)
    assert provider.calls == []


def test_a_document_that_is_not_imported_fails_and_the_others_continue(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    other = DocumentSpec("b.md", "B", [small_page(1, 2)], ["B"])
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, other])
    import_dir(migrated_engine, directory)
    changed = dataclasses.replace(DOC_A, pages=big_pages(1))
    write_v2(tmp_path, [PARTY_A, PARTY_B], [changed, other])  # a.md changed, not imported
    keep_all(directory)

    provider = fake(measures=2)
    summary, lines = extract(migrated_engine, directory, provider)

    missing = (
        f"document a.md: content_hash {hash_of(directory, 'a.md')[:12]}... is not imported; "
        f'run "ideology data import {directory}"'
    )
    assert lines[0] == f"E Error: {missing}"
    assert summary.failed == [missing]
    assert called_pages(provider) == [[1]]
    assert ledger_count(directory, "b.md") == 2


def test_status_rows(tmp_path: Path, migrated_engine: Engine) -> None:
    other = DocumentSpec("b.md", "B", [small_page(1, 2)], ["B"])
    directory = write_v2(tmp_path, [PARTY_A, PARTY_B], [DOC_A, other])
    import_dir(migrated_engine, directory)
    keep_all(directory)
    extract(migrated_engine, directory, fake(), file="a.md", max_calls=1)
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None

    with Session(migrated_engine) as session:
        status = store.status_rows(session, read_bundle(directory), ledger)

    assert [(r.file, r.state, r.chunks_done, r.chunk_count, r.validated, r.ledger) for r in status] == [
        ("a.md", "in_progress", 1, 3, None, None),
        ("b.md", "not_started", 0, 1, None, None),
    ]
