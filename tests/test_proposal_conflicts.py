"""``proposals.conflicts`` (proposal-conflicts scenarios 3-6, 9): detect, set aside, read.

FakeProvider only (the offline guard blocks every real LLM path). Detection
reads the database and writes only the ledger: the SQLite file is compared
byte for byte around every ``detect``.
"""

import dataclasses
import hashlib
from pathlib import Path

import pytest
from conflict_fixtures import EXPLANATION, FLAG, collector, conflict_fake, extract_all, setup
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app import ingestion_ledger as ledgers
from ideology_app.ingestion_ledger import ConflictStatus, Contradiction, Phase4Blocked
from ideology_app.proposals import conflicts
from ideology_app.proposals.conflict_prompts import ContradictionList, conflict_requests
from ideology_app.proposals.conflict_prompts import ConflictProposal as CP
from ideology_app.proposals.store import load_proposals
from ideology_app.source_bundle import read_bundle


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def _db_bytes(db_url: str) -> str:
    return hashlib.sha256(Path(db_url.removeprefix("sqlite:///")).read_bytes()).hexdigest()


def _detect(engine: Engine, directory: Path, provider, db_url: str, **kwargs):
    before = _db_bytes(db_url)
    lines, echo = collector()
    summary = conflicts.detect(engine, directory, provider, echo=echo, **kwargs)
    assert _db_bytes(db_url) == before, "detect must not write the database"
    return summary, lines


def _ledger(directory: Path) -> ledgers.Ledger:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return ledger


# --- Pure merge ---------------------------------------------------------------------------


def test_merge_maps_numbers_to_ordinals_dedupes_and_sorts() -> None:
    side_a = [CP(4, "a4", ("housing", "economy")), CP(9, "a9", ("housing",))]
    side_b = [CP(2, "b2", ("housing", "economy")), CP(5, "b5", ("economy",))]
    requests = conflict_requests(side_a, side_b)
    assert [(r.category, r.ordinals_a, r.ordinals_b) for r in requests] == [
        ("housing", (4, 9), (2,)), ("economy", (4,), (2, 5)),
    ]
    outputs = [
        ContradictionList.model_validate({"contradictions": [
            {"a": 2, "b": 1, "explanation": "Primera."}, {"a": 1, "b": 1, "explanation": "Vivienda."},
        ]}),
        ContradictionList.model_validate({"contradictions": [
            {"a": 1, "b": 1, "explanation": "Repetida."}, {"a": 1, "b": 2, "explanation": "Otra."},
        ]}),
    ]
    assert conflicts.merge_outputs(requests, outputs) == (
        Contradiction((4, 2), "housing", "Vivienda."),
        Contradiction((4, 5), "economy", "Otra."),
        Contradiction((9, 2), "housing", "Primera."),
    )
    with pytest.raises(ValueError):
        conflicts.merge_outputs(requests, outputs[:1])


# --- Scenario 3: no contradiction ----------------------------------------------------------


def test_detect_without_contradiction_opens_the_gate(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    with pytest.raises(Phase4Blocked):
        ledgers.require_phase4_ready(directory)
    provider = conflict_fake()

    summary, lines = _detect(migrated_engine, directory, provider, db_url)

    assert lines == ["Conflict P a.md + b.md (28): no contradiction"]
    assert (summary.new_calls, summary.pending, summary.error, summary.failed) == (2, 0, None, [])
    entry = _ledger(directory).conflicts[0]
    assert entry.status is ConflictStatus.NO_CONTRADICTION
    assert entry.check == ledgers.ConflictCheck("fake", "fake-model", "v1", 2)
    ledgers.require_phase4_ready(directory)


# --- Scenario 4: flagged ----------------------------------------------------------------------


def test_detect_flags_once_and_shows_no_names(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    provider = conflict_fake([FLAG])

    summary, lines = _detect(migrated_engine, directory, provider, db_url)

    assert lines == ["Conflict P a.md + b.md (28): 1 contradictions; pending Operator decision"]
    assert len(provider.calls) == 2  # housing and economy
    assert [r.prompt.splitlines()[0] for r in provider.calls] == ["Tema: Vivienda", "Tema: Economía"]
    for request in provider.calls:
        for name in ("Partido P", "a.md", "b.md", "[página", "P:"):
            assert name not in request.prompt and name not in request.system
    entry = _ledger(directory).conflicts[0]
    assert entry.contradictions == (Contradiction((1, 2), "housing", EXPLANATION),)
    assert entry.status is ConflictStatus.PENDING
    assert summary.pending == 1
    with pytest.raises(Phase4Blocked) as blocked:
        ledgers.require_phase4_ready(directory)
    assert blocked.value.blockers == (
        f'conflict pending: P: a.md + b.md (28): 1 contradictions; run "ideology conflicts '
        f'decide {directory} P --prevails FILE --over FILE --reason TEXT"',
    )


# --- Scenario 5: joint manifesto --------------------------------------------------------------


def test_joint_manifesto_prevails_after_detection(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine, joint=["b.md"])
    _, lines = _detect(migrated_engine, directory, conflict_fake([FLAG]), db_url)
    assert lines == [
        "Conflict P a.md + b.md (28): 1 contradictions; joint manifesto b.md prevails"
    ]
    ledger = ledgers.require_phase4_ready(directory)
    assert ledger.conflicts[0].status is ConflictStatus.JOINT_MANIFESTO
    assert conflicts.set_aside(ledger, "P") == {
        (ledger.conflicts[0].content_hashes[0], 1): frozenset({"28"})
    }


# --- Scenario 6: decide and apply ------------------------------------------------------------


def _rows(session: Session, directory: Path, party: str = "P") -> list[tuple[str, int, tuple[str, ...]]]:
    bundle = read_bundle(directory)
    ledger = _ledger(directory)
    return [
        (c.file, c.proposal.ordinal, c.constituencies)
        for c in conflicts.counted_proposals(session, bundle, ledger, party)
    ]


def test_decision_sets_aside_only_the_losing_contradicting_proposal(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    _detect(migrated_engine, directory, conflict_fake([FLAG]), db_url)
    bundle = read_bundle(directory)
    with Session(migrated_engine) as session:
        with pytest.raises(conflicts.ConflictError, match="party P has pending conflicts: P: "):
            conflicts.counted_proposals(session, bundle, _ledger(directory), "P")
        before = [(p.id, p.ordinal, p.text) for h in _hashes(directory) for p in load_proposals(session, h)]

    ledgers.decide_conflict_in_dir(directory, "P", prevails="a.md", over="b.md", reason="Nacional.")
    ledgers.require_phase4_ready(directory)
    with Session(migrated_engine) as session:
        assert _rows(session, directory) == [
            ("a.md", 1, ("28", "31")), ("a.md", 2, ("28", "31")), ("a.md", 3, ("28", "31")),
            ("b.md", 1, ("28",)),  # b.md #2 contradicts a.md #1 in 28, its only Constituency
        ]
        counted = conflicts.counted_proposals(session, bundle, _ledger(directory), "P")
        assert {c.content_hash for c in counted} == set(_hashes(directory))
        assert all(c.source_document_id > 0 for c in counted)

    ledgers.decide_conflict_in_dir(directory, "P", prevails="b.md", over="a.md", reason="Regional.")
    with Session(migrated_engine) as session:
        assert _rows(session, directory) == [
            ("a.md", 1, ("31",)),  # set aside in 28 only
            ("a.md", 2, ("28", "31")), ("a.md", 3, ("28", "31")),
            ("b.md", 1, ("28",)), ("b.md", 2, ("28",)),
        ]
        after = [(p.id, p.ordinal, p.text) for h in _hashes(directory) for p in load_proposals(session, h)]
    assert after == before


def _hashes(directory: Path) -> list[str]:
    return list(_ledger(directory).conflicts[0].content_hashes)


def test_counted_proposals_without_conflicts_and_its_refusals(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    _detect(migrated_engine, directory, conflict_fake(), db_url)
    bundle = read_bundle(directory)
    ledger = _ledger(directory)
    with Session(migrated_engine) as session:
        assert len(_rows(session, directory)) == 5
        assert conflicts.set_aside(ledger, "P") == {}
        wrong = dataclasses.replace(
            ledger,
            documents=tuple(
                dataclasses.replace(d, proposals=9) if d.file == "b.md" else d
                for d in ledger.documents
            ),
        )
        with pytest.raises(conflicts.ConflictError, match="b.md: ledger records 9 validated"):
            conflicts.counted_proposals(session, bundle, wrong, "P")


# --- Scenario 9: reuse and budget --------------------------------------------------------------


def test_rerun_and_shared_hash_pair_make_no_new_calls(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine, shared=True)
    provider = conflict_fake([FLAG])

    summary, lines = _detect(migrated_engine, directory, provider, db_url)

    assert lines == [
        "Conflict P a.md + b.md (28): 1 contradictions; pending Operator decision",
        "Conflict Q a.md + b.md (28): reused check (Party P); 1 contradictions; pending "
        "Operator decision",
    ]
    assert summary.new_calls == len(provider.calls) == 2
    p_entry, q_entry = _ledger(directory).conflicts
    assert q_entry.check == ledgers.ConflictCheck("fake", "fake-model", "v1", 0)
    assert q_entry.contradictions == p_entry.contradictions

    summary, lines = _detect(migrated_engine, directory, provider, db_url)
    assert summary.new_calls == 0 and len(provider.calls) == 2
    assert lines == [
        "Conflict P a.md + b.md (28): already checked; 1 contradictions; pending Operator decision",
        "Conflict Q a.md + b.md (28): already checked; 1 contradictions; pending Operator decision",
    ]


def test_budget_stops_before_an_entry(tmp_path: Path, migrated_engine: Engine, db_url: str) -> None:
    directory = setup(tmp_path, migrated_engine)
    ledger_before = (directory / ledgers.LEDGER_NAME).read_bytes()
    provider = conflict_fake([FLAG])

    summary, lines = _detect(migrated_engine, directory, provider, db_url, max_calls=1)

    assert lines == ["Stopped before Conflict P a.md + b.md (28); run again or raise --max-calls"]
    assert (summary.stopped, summary.new_calls, len(provider.calls)) == (True, 0, 0)
    assert (directory / ledgers.LEDGER_NAME).read_bytes() == ledger_before


def test_llm_error_leaves_the_entry_unchecked(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    ledger_before = (directory / ledgers.LEDGER_NAME).read_bytes()
    provider = conflict_fake([FLAG], fail_on_call=2)

    summary, lines = _detect(migrated_engine, directory, provider, db_url)

    assert summary.error == "Conflict P a.md + b.md (28): provider overloaded (529)"
    assert (summary.new_calls, len(provider.calls), lines) == (1, 2, [])
    assert (directory / ledgers.LEDGER_NAME).read_bytes() == ledger_before
    assert _ledger(directory).conflicts[0].status is ConflictStatus.UNCHECKED


# --- Scenario 7: detect before extraction, excluded Party ---------------------------------------


def test_detect_before_extraction_reports_and_skips(
    tmp_path: Path, migrated_engine: Engine, db_url: str
) -> None:
    directory = setup(tmp_path, migrated_engine, extract=False)
    provider = conflict_fake()
    summary, lines = _detect(migrated_engine, directory, provider, db_url)
    assert lines == [
        "Error-stream: Error: Conflict P a.md + b.md (28): extract Proposals from a.md first"
    ]
    assert summary.failed and summary.pending == 1 and provider.calls == []

    extract_all(migrated_engine, directory)
    summary, _ = _detect(migrated_engine, directory, provider, db_url)
    assert (summary.failed, summary.pending, summary.new_calls) == ([], 0, 2)


def test_excluded_party_is_skipped(tmp_path: Path, migrated_engine: Engine, db_url: str) -> None:
    directory = setup(tmp_path, migrated_engine, min_proposals=10)  # P: 5 < 10
    provider = conflict_fake()
    summary, lines = _detect(migrated_engine, directory, provider, db_url)
    assert lines == ["Conflict P a.md + b.md (28): skipped (Party P excluded)"]
    assert (summary.pending, provider.calls) == (0, [])
    ledgers.require_phase4_ready(directory)


def test_show_rows(tmp_path: Path, migrated_engine: Engine, db_url: str) -> None:
    directory = setup(tmp_path, migrated_engine)
    _detect(migrated_engine, directory, conflict_fake([FLAG]), db_url)
    entry = _ledger(directory).conflicts[0]
    with Session(migrated_engine) as session:
        (row,) = conflicts.show_rows(session, entry)
    assert (row.number, row.category, row.explanation) == (1, "housing", EXPLANATION)
    assert (row.a.file, row.a.ordinal, row.a.page) == ("a.md", 1, 1)
    assert row.a.text is not None and row.a.text.startswith("Medida 1 de la página 1")
    assert (row.b.file, row.b.ordinal, row.b.page) == ("b.md", 2, 1)
