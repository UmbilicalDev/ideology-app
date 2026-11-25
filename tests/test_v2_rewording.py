"""Statement Rewording of a v2 run (statement-rewording scenarios 1-8).

The reader and ``apply_rewordings`` are tested on plain data; the run
scenarios use a scratch database and the v2 fixture (``ConstituencySettings(1,
1)``, so a run passes and is published). FakeProvider only; the offline guard
blocks every other LLM path. Bundles live in ``tmp_path``.
"""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import write_bundle
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from v2_fixtures import NOTE, PARTY_NAMES, STATEMENTS, REJECT_MARKER, setup, v2_fake

from ideology_app.config import ConstituencySettings, GenerationMode
from ideology_app.db import session_scope
from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionStatus,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunCall,
    PipelineRunStatus,
    Statement,
    StatementProposal,
    StatementRewording,
    ValidationResult,
)
from ideology_app.pipeline import get_run_report
from ideology_app.pipeline.generation import Usage
from ideology_app.pipeline.runs import RunOutcome, validate_run
from ideology_app.pipeline.v2 import (
    MAX_REWORDINGS,
    REWORDINGS_NAME,
    AppliedRewording,
    PoolDraft,
    RewordingEntry,
    RewordingFile,
    RewordingFileError,
    apply_rewordings,
    execute_v2_run,
    queue_v2_run,
    read_rewordings,
    rewording_summary,
)
from ideology_app.pipeline.v2 import run as v2_run
from ideology_app.source_bundle import read_bundle

LOW = ConstituencySettings(1, 1)
HOUSING = STATEMENTS["Vivienda"][0]  # "Debe limitarse el precio del alquiler de vivienda."
ECONOMY = STATEMENTS["Economía"][0]  # "Deben bajarse los impuestos a las empresas."
NEW_HOUSING = "Debe ponerse un tope al precio del alquiler de las viviendas."
NEW_ECONOMY = "Deben pagar menos impuestos las empresas."
REASON = "«Limitarse» se entiende como «restringirse» y confunde."
EQUIVALENT = "Misma medida con palabras más sencillas."
NOT_EQUIVALENT = "La nueva redacción cambia la medida."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def write_rewordings(directory: Path, entries: Sequence[tuple[str, str, str]]) -> Path:
    """Write ``statement-rewordings.toml`` (format 1) with ``(ai_text, text, reason)`` entries."""
    lines = ["format = 1"]
    for ai_text, text, reason in entries:
        lines += [
            "",
            "[[rewordings]]",
            f"ai_text = {json.dumps(ai_text, ensure_ascii=False)}",
            f"text = {json.dumps(text, ensure_ascii=False)}",
            f"reason = {json.dumps(reason, ensure_ascii=False)}",
        ]
    path = directory / REWORDINGS_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class NoCalls:
    """A provider that must never be called (replays)."""

    name, model = "fake", "fake-model"

    def generate(self, request: Any) -> Any:
        raise AssertionError(f"no call expected, got {request.task}")


# --- Reader (R1, scenario 4) -----------------------------------------------------------------


def test_no_file_means_no_rewordings(tmp_path: Path) -> None:
    assert read_rewordings(tmp_path) is None


def test_reads_a_valid_file_with_its_hash(tmp_path: Path) -> None:
    path = write_rewordings(tmp_path, [(HOUSING, NEW_HOUSING, REASON), (ECONOMY, NEW_ECONOMY, "R")])
    file = read_rewordings(tmp_path)
    assert file is not None
    assert file.path == path
    assert file.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert file.entries == (
        RewordingEntry(HOUSING, NEW_HOUSING, REASON),
        RewordingEntry(ECONOMY, NEW_ECONOMY, "R"),
    )
    (tmp_path / REWORDINGS_NAME).write_text("format = 1\n", encoding="utf-8")
    empty = read_rewordings(tmp_path)
    assert empty is not None and empty.entries == ()


ENTRY = '[[rewordings]]\nai_text = "A."\ntext = "B."\nreason = "R."\n'
BAD_FILES = [
    ("syntax", "format = 1\n[[rewordings]\n", ": invalid TOML: "),
    ("missing-format", ENTRY, ": missing key 'format'"),
    ("format-2", "format = 2\n" + ENTRY, ": format must be 1, got 2"),
    ("format-bool", "format = true\n" + ENTRY, ": format must be 1, got True"),
    ("extra-top-key", 'format = 1\nnote = "x"\n' + ENTRY, ": unknown key 'note'"),
    ("not-an-array", 'format = 1\nrewordings = "x"\n', ": rewordings must be an array of tables"),
    ("missing-key", 'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "B."\n',
     ":entry 1: missing key 'reason'"),
    ("extra-key", "format = 1\n" + ENTRY + 'statement = "3"\n', ":entry 1: unknown key 'statement'"),
    ("not-a-string", 'format = 1\n[[rewordings]]\nai_text = "A."\ntext = 3\nreason = "R."\n',
     ":entry 1: text must be a string"),
    ("blank-reason", 'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "B."\nreason = "  "\n',
     ":entry 1: reason must be 1..500 characters and not blank"),
    ("long-reason",
     f'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "B."\nreason = "{"r" * 501}"\n',
     ":entry 1: reason must be 1..500 characters and not blank"),
    ("long-text", f'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "{"t" * 301}"\nreason = "R"\n',
     ":entry 1: text must be 1..300 characters with a non-space character"),
    ("blank-text", 'format = 1\n[[rewordings]]\nai_text = "A."\ntext = " "\nreason = "R"\n',
     ":entry 1: text must be 1..300 characters with a non-space character"),
    ("long-ai-text",
     f'format = 1\n[[rewordings]]\nai_text = "{"a" * 301}"\ntext = "B."\nreason = "R"\n',
     ":entry 1: ai_text must be 1..300 characters"),
    ("same-text", 'format = 1\n[[rewordings]]\nai_text = "A."\ntext = "A."\nreason = "R"\n',
     ":entry 1: text is the same as ai_text"),
    ("repeated-ai-text",
     "format = 1\n" + ENTRY + '[[rewordings]]\nai_text = "a"\ntext = "C."\nreason = "R."\n',
     ":entry 2: same ai_text as entry 1"),
    ("too-many", "format = 1\n" + "".join(
        f'[[rewordings]]\nai_text = "A{k}."\ntext = "B."\nreason = "R."\n'
        for k in range(MAX_REWORDINGS + 1)
    ), f": {MAX_REWORDINGS + 1} rewordings, at most {MAX_REWORDINGS}"),
]


@pytest.mark.parametrize(("content", "message"), [b[1:] for b in BAD_FILES],
                         ids=[b[0] for b in BAD_FILES])
def test_each_bad_file_is_refused(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / REWORDINGS_NAME
    path.write_text(content, encoding="utf-8")
    with pytest.raises(RewordingFileError) as refused:
        read_rewordings(tmp_path)
    assert str(refused.value).startswith(f"{path}{message}"), str(refused.value)


def test_not_utf8_is_refused(tmp_path: Path) -> None:
    (tmp_path / REWORDINGS_NAME).write_bytes(b"format = 1\n# \xff\n")
    with pytest.raises(RewordingFileError, match="not UTF-8"):
        read_rewordings(tmp_path)


def test_at_most_max_entries_is_accepted(tmp_path: Path) -> None:
    write_rewordings(tmp_path, [(f"A{k}.", "B.", "R.") for k in range(MAX_REWORDINGS)])
    file = read_rewordings(tmp_path)
    assert file is not None and len(file.entries) == MAX_REWORDINGS


# --- apply_rewordings on plain data (R2, R4, R8) ---------------------------------------------


def _pool(*texts: str) -> tuple[PoolDraft, ...]:
    return tuple(PoolDraft(t, f"Nota de {t}", "housing", (k,)) for k, t in enumerate(texts, 1))


def _file(*entries: tuple[str, str, str]) -> RewordingFile:
    return RewordingFile(Path("b") / REWORDINGS_NAME, "ab" * 32, tuple(RewordingEntry(*e) for e in entries))


def _judge(verdicts: dict[str, bool] | None = None) -> FakeProvider:
    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        new = request.prompt.split("Nueva redacción:\n\n")[1].split("\n\n")[0]
        ok = (verdicts or {}).get(new, REJECT_MARKER not in new)
        return {"equivalent": ok, "explanation": EQUIVALENT if ok else NOT_EQUIVALENT}

    return FakeProvider({"statement_rewording_check": respond})


def test_entries_are_matched_by_normalised_ai_text_and_judged_in_pool_order() -> None:
    pool = _pool("Primera afirmación.", "Segunda afirmación.", "Tercera afirmación.")
    provider = _judge()
    usage = Usage()
    outcome = apply_rewordings(
        provider,
        pool,
        _file(
            ("TERCERA   afirmación", "La tercera, más clara.", "r3"),
            ("No existe.", "Otra.", "r0"),
            ("primera afirmacion.", "La primera CAMBIO.", "r1"),
        ),
        usage,
    )
    assert [r.prompt.split("\n\n")[1] for r in provider.calls] == [
        "Primera afirmación.", "Tercera afirmación.",
    ]
    assert usage.calls == 2
    assert dict(outcome.applied) == {2: AppliedRewording("La tercera, más clara.", "r3", EQUIVALENT)}
    assert outcome.report == {
        "version": "v2-rewording-1",
        "file": REWORDINGS_NAME,
        "sha256": "ab" * 32,
        "prompt_version": "v1",
        "entries": [
            {"status": "rejected", "statement": 1, "ai_text": "Primera afirmación.",
             "text": "La primera CAMBIO.", "reason": "r1", "explanation": NOT_EQUIVALENT},
            {"status": "applied", "statement": 3, "ai_text": "Tercera afirmación.",
             "text": "La tercera, más clara.", "reason": "r3", "explanation": EQUIVALENT},
            {"status": "not_found", "statement": None, "ai_text": "No existe.",
             "text": "Otra.", "reason": "r0", "explanation": None},
        ],
    }
    assert rewording_summary({"rewordings": outcome.report}) == (
        "1 applied, 1 rejected, 0 duplicate, 1 not found"
    )
    assert rewording_summary({}) is None and rewording_summary(None) is None


def test_duplicates_make_no_call() -> None:
    pool = _pool("Uno.", "Dos.", "Tres.")
    provider = _judge()
    outcome = apply_rewordings(
        provider,
        pool,
        _file(
            ("Uno.", "dos", "same as another AI text"),
            ("Dos.", "Nuevo texto.", "first"),
            ("Tres.", "NUEVO, texto", "same as an earlier new text"),
        ),
        Usage(),
    )
    assert [e["status"] for e in outcome.report["entries"]] == ["duplicate", "applied", "duplicate"]
    assert [e["explanation"] for e in outcome.report["entries"]] == [None, EQUIVALENT, None]
    assert len(provider.calls) == 1
    # A new text equal (normalised) to its own AI text is not a duplicate.
    own = apply_rewordings(_judge(), pool, _file(("Uno.", "uno", "punctuation")), Usage())
    assert own.report["entries"][0]["status"] == "applied"


def test_the_request_holds_only_the_ai_text_the_note_and_the_new_text() -> None:
    provider = _judge()
    apply_rewordings(provider, _pool("Uno."), _file(("Uno.", "Uno nuevo.", "MOTIVO-SECRETO")), Usage())
    (request,) = provider.calls
    assert "Uno." in request.prompt and "Nota de Uno." in request.prompt
    assert "Uno nuevo." in request.prompt
    assert "MOTIVO-SECRETO" not in request.prompt + request.system
    assert REWORDINGS_NAME not in request.prompt + request.system


# --- Runs (scenarios 1, 2, 3, 5, 6) ----------------------------------------------------------


def _queue(engine: Engine, **kwargs: Any) -> int:
    with session_scope(engine) as session:
        return queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED, **kwargs,
        ).id


def _run(engine: Engine, directory: Path, provider: Any, source: int | None = None) -> RunOutcome:
    run_id = _queue(
        engine, resumed_from_run_id=source, allow_finished_source=source is not None
    )
    return execute_v2_run(engine, run_id, provider, directory, constituency_settings=LOW)


def _statements(engine: Engine, version_id: int) -> list[tuple[Any, ...]]:
    with Session(engine) as session:
        return [
            (s.position, s.text, s.topic, s.context_note,
             tuple(session.scalars(select(StatementProposal.proposal_id)
                                   .where(StatementProposal.statement_id == s.id)
                                   .order_by(StatementProposal.rank))))
            for s in session.scalars(
                select(Statement).where(Statement.dataset_version_id == version_id)
                .order_by(Statement.position)
            )
        ]


def _positions(engine: Engine, version_id: int) -> list[tuple[Any, ...]]:
    """Every Position and its Evidence, keyed by Statement position and Party (no ids)."""
    with Session(engine) as session:
        rows = []
        for p, position in session.execute(
            select(PartyPosition, Statement.position)
            .join(Statement, PartyPosition.statement_id == Statement.id)
            .where(Statement.dataset_version_id == version_id)
            .order_by(Statement.position, PartyPosition.party_id)
        ):
            evidence = session.execute(
                select(PartyPositionProposal.rank, PartyPositionProposal.proposal_id,
                       PartyPositionProposal.source_document_id,
                       PartyPositionProposal.constituencies)
                .where(PartyPositionProposal.party_position_id == p.id)
                .order_by(PartyPositionProposal.rank)
            ).all()
            rows.append((position, p.party_id, p.value, p.evidence_source_document_id,
                         p.evidence_quote, p.evidence_page, p.evidence_url,
                         tuple(tuple(e) for e in evidence)))
        return rows


def _ranked(engine: Engine, version_id: int) -> list[tuple[str, int, int]]:
    with Session(engine) as session:
        return [
            (code, rank, position)
            for code, rank, position in session.execute(
                select(ConstituencyStatement.constituency_code, ConstituencyStatement.rank,
                       Statement.position)
                .join(Statement, ConstituencyStatement.statement_id == Statement.id)
                .where(ConstituencyStatement.dataset_version_id == version_id)
                .order_by(ConstituencyStatement.constituency_code, ConstituencyStatement.rank)
            )
        ]


def _rewordings(engine: Engine, version_id: int) -> list[tuple[Any, ...]]:
    with Session(engine) as session:
        return [
            (position, r.ai_text, r.reason, r.explanation)
            for r, position in session.execute(
                select(StatementRewording, Statement.position)
                .join(Statement, StatementRewording.statement_id == Statement.id)
                .where(Statement.dataset_version_id == version_id)
                .order_by(Statement.position)
            )
        ]


def _calls(engine: Engine, run_id: int) -> list[tuple[str, bool]]:
    with Session(engine) as session:
        return [
            (task, reused)
            for task, reused in session.execute(
                select(PipelineRunCall.task, PipelineRunCall.reused)
                .where(PipelineRunCall.pipeline_run_id == run_id)
                .order_by(PipelineRunCall.sequence)
            )
        ]


def _selection(engine: Engine, run_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        return dict(get_run_report(session, run_id).statement_selection or {})


def _status(engine: Engine, version_id: int) -> DatasetVersionStatus:
    with Session(engine) as session:
        version = session.get(DatasetVersion, version_id)
        assert version is not None
        return version.status


@pytest.fixture
def published(tmp_path: Path, migrated_engine: Engine) -> tuple[Path, RunOutcome]:
    """The fixture bundle and its passed, published first v2 run (no rewording file)."""
    directory = setup(tmp_path, migrated_engine)
    outcome = _run(migrated_engine, directory, v2_fake())
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    assert "rewordings" not in _selection(migrated_engine, outcome.run_id)
    return directory, outcome


def test_scenario_1_applied_rewording_makes_a_new_version_with_identical_positions(
    migrated_engine: Engine, published: tuple[Path, RunOutcome]
) -> None:
    directory, first = published
    v = first.dataset_version_id
    assert v is not None
    statements_v, positions_v, ranked_v = (
        _statements(migrated_engine, v), _positions(migrated_engine, v), _ranked(migrated_engine, v)
    )
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON)])
    provider = v2_fake()

    second = _run(migrated_engine, directory, provider, source=first.run_id)

    assert second.status is PipelineRunStatus.PASSED, second.failure_reason
    assert second.publish is not None and second.publish.published
    assert second.publish.superseded_dataset_version_id == v
    v2 = second.dataset_version_id
    assert v2 is not None and v2 != v
    # Only the equivalence call is new; every draft and position call is reused.
    assert [r.task for r in provider.calls] == ["statement_rewording_check"]
    calls = _calls(migrated_engine, second.run_id)
    assert [c for c in calls if not c[1]] == [("statement_rewording_check", False)]
    assert sum(reused for _, reused in calls) == 6
    # The new text at the same position; the AI text, reason and explanation stored.
    statements = _statements(migrated_engine, v2)
    assert statements[0] == (1, NEW_HOUSING, *statements_v[0][2:])
    assert statements[1:] == statements_v[1:]
    assert _rewordings(migrated_engine, v2) == [(1, HOUSING, REASON, EQUIVALENT)]
    # Positions, Evidence and the per-Constituency order equal the source version's.
    assert _positions(migrated_engine, v2) == positions_v
    assert _ranked(migrated_engine, v2) == ranked_v
    # The earlier version is untouched except its status.
    assert _statements(migrated_engine, v) == statements_v
    assert _positions(migrated_engine, v) == positions_v
    assert _rewordings(migrated_engine, v) == []
    assert _status(migrated_engine, v) is DatasetVersionStatus.SUPERSEDED
    assert _status(migrated_engine, v2) is DatasetVersionStatus.PUBLISHED
    selection = _selection(migrated_engine, second.run_id)
    assert selection["rewordings"]["entries"] == [
        {"status": "applied", "statement": 1, "ai_text": HOUSING, "text": NEW_HOUSING,
         "reason": REASON, "explanation": EQUIVALENT},
    ]
    assert selection["version"] == "v2-pool-1"
    with Session(migrated_engine) as session:
        results = session.scalars(
            select(ValidationResult).where(ValidationResult.pipeline_run_id == second.run_id)
        ).all()
    assert results[-1].check_name == "statement_rewording"
    assert all(r.passed for r in results)


def test_scenario_2_rejected_rewording_keeps_the_ai_text(
    migrated_engine: Engine, published: tuple[Path, RunOutcome]
) -> None:
    directory, first = published
    text = f"Debe {REJECT_MARKER} prohibirse el alquiler de vivienda."
    write_rewordings(directory, [(HOUSING, text, REASON)])

    second = _run(migrated_engine, directory, v2_fake(), source=first.run_id)

    assert second.status is PipelineRunStatus.PASSED, second.failure_reason
    assert second.dataset_version_id is not None
    assert _statements(migrated_engine, second.dataset_version_id) == _statements(
        migrated_engine, first.dataset_version_id
    )
    assert _rewordings(migrated_engine, second.dataset_version_id) == []
    assert _selection(migrated_engine, second.run_id)["rewordings"]["entries"] == [
        {"status": "rejected", "statement": 1, "ai_text": HOUSING, "text": text,
         "reason": REASON, "explanation": NOT_EQUIVALENT},
    ]


def test_scenario_3_duplicate_and_not_found_make_no_call(
    migrated_engine: Engine, published: tuple[Path, RunOutcome]
) -> None:
    directory, first = published
    write_rewordings(
        directory,
        [(HOUSING, ECONOMY.upper().rstrip("."), "Igual que otra."), ("No existe.", "Otra.", "R.")],
    )
    provider = v2_fake()

    second = _run(migrated_engine, directory, provider, source=first.run_id)

    assert second.status is PipelineRunStatus.PASSED, second.failure_reason
    assert provider.calls == []
    entries = _selection(migrated_engine, second.run_id)["rewordings"]["entries"]
    assert [(e["status"], e["statement"], e["ai_text"], e["explanation"]) for e in entries] == [
        ("duplicate", 1, HOUSING, None), ("not_found", None, "No existe.", None),
    ]
    assert _rewordings(migrated_engine, second.dataset_version_id) == []


def test_scenario_5_replay_of_the_rewording_run_makes_no_call(
    migrated_engine: Engine, published: tuple[Path, RunOutcome]
) -> None:
    directory, first = published
    write_rewordings(
        directory, [(HOUSING, NEW_HOUSING, REASON), (ECONOMY, NEW_ECONOMY, "Más claro.")]
    )
    second = _run(migrated_engine, directory, v2_fake(), source=first.run_id)
    assert second.status is PipelineRunStatus.PASSED, second.failure_reason

    replay = _run(migrated_engine, directory, NoCalls(), source=second.run_id)

    assert replay.status is PipelineRunStatus.PASSED, replay.failure_reason
    assert all(reused for _, reused in _calls(migrated_engine, replay.run_id))
    assert _statements(migrated_engine, replay.dataset_version_id) == _statements(
        migrated_engine, second.dataset_version_id
    )
    assert _rewordings(migrated_engine, replay.dataset_version_id) == _rewordings(
        migrated_engine, second.dataset_version_id
    )
    assert _positions(migrated_engine, replay.dataset_version_id) == _positions(
        migrated_engine, first.dataset_version_id
    )
    assert (
        _selection(migrated_engine, replay.run_id)["rewordings"]
        == _selection(migrated_engine, second.run_id)["rewordings"]
    )

    # An edited entry calls again only for itself.
    write_rewordings(
        directory, [(HOUSING, NEW_HOUSING, REASON), (ECONOMY, "Las empresas deben pagar menos "
                                                             "impuestos.", "Más claro.")]
    )
    provider = v2_fake()
    edited = _run(migrated_engine, directory, provider, source=replay.run_id)
    assert edited.status is PipelineRunStatus.PASSED, edited.failure_reason
    assert [r.task for r in provider.calls] == ["statement_rewording_check"]
    assert "Las empresas deben pagar menos impuestos." in provider.calls[0].prompt


def test_scenario_6_the_run_prompt_has_no_reason_or_party(
    migrated_engine: Engine, published: tuple[Path, RunOutcome]
) -> None:
    directory, first = published
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON)])
    provider = v2_fake()
    _run(migrated_engine, directory, provider, source=first.run_id)
    (request,) = provider.calls
    assert HOUSING in request.prompt and NOTE in request.prompt and NEW_HOUSING in request.prompt
    for forbidden in (REASON, *PARTY_NAMES, REWORDINGS_NAME, "[página"):
        assert forbidden not in request.prompt and forbidden not in request.system


def test_a_fresh_run_with_a_file_judges_after_positioning(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON)])
    provider = v2_fake()
    outcome = _run(migrated_engine, directory, provider)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    assert [r.task for r in provider.calls] == (
        ["statement_drafts"] * 2 + ["proposal_positions"] * 4 + ["statement_rewording_check"]
    )
    # The position requests list the AI text, never the new one.
    for request in provider.calls[2:6]:
        assert NEW_HOUSING not in request.prompt


def test_an_llm_error_in_the_check_fails_the_run_and_keeps_the_calls(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON)])
    failed = _run(migrated_engine, directory, v2_fake(fail_on_call=7))
    assert failed.status is PipelineRunStatus.FAILED
    assert failed.failure_reason == "provider overloaded (529)"
    assert len(_calls(migrated_engine, failed.run_id)) == 6
    provider = v2_fake()
    resumed = _run(migrated_engine, directory, provider, source=failed.run_id)
    assert resumed.status is PipelineRunStatus.PASSED, resumed.failure_reason
    assert [r.task for r in provider.calls] == ["statement_rewording_check"]


def test_the_budget_counts_one_call_per_entry(
    tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = setup(tmp_path, migrated_engine)
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON), ("No.", "Sí.", "R.")])
    monkeypatch.setattr(v2_run, "MAX_V2_CALLS_PER_RUN", 7)
    provider = v2_fake()
    outcome = _run(migrated_engine, directory, provider)
    assert outcome.failure_reason == "too many v2 calls planned: 8 (limit 7)"
    assert provider.calls == []


def test_a_file_made_invalid_after_queueing_fails_the_run(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    run_id = _queue(migrated_engine)
    (directory / REWORDINGS_NAME).write_text("format = 2\n", encoding="utf-8")
    provider = v2_fake()
    outcome = execute_v2_run(migrated_engine, run_id, provider, directory, constituency_settings=LOW)
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == (
        f"rewording file invalid: {directory / REWORDINGS_NAME}: format must be 1, got 2"
    )
    assert provider.calls == [] and _calls(migrated_engine, run_id) == []


# --- Tamper (scenario 7) ---------------------------------------------------------------------


@pytest.fixture
def validating(
    migrated_engine: Engine, published: tuple[Path, RunOutcome], monkeypatch: pytest.MonkeyPatch
) -> int:
    """A rewording run (Statement 1 reworded) left in ``validating``."""
    directory, first = published
    write_rewordings(directory, [(HOUSING, NEW_HOUSING, REASON)])
    held: dict[str, int] = {}

    def hold(engine: Engine, run_id: int, **kwargs: Any) -> RunOutcome:
        held["run_id"] = run_id
        return RunOutcome(run_id, PipelineRunStatus.VALIDATING, None, 0, None)

    monkeypatch.setattr(v2_run, "validate_run", hold)
    _run(migrated_engine, directory, v2_fake(), source=first.run_id)
    return held["run_id"]


def _version_of(engine: Engine, run_id: int) -> int:
    with Session(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None and run.dataset_version is not None
        return run.dataset_version.id


def _failed_entries(engine: Engine, run_id: int) -> list[tuple[str, str]]:
    with Session(engine) as session:
        return [
            (r.check_name, e.message)
            for r in session.scalars(
                select(ValidationResult).where(ValidationResult.pipeline_run_id == run_id)
            )
            for e in r.entries
        ]


def test_untampered_rewording_run_passes(migrated_engine: Engine, validating: int) -> None:
    outcome = validate_run(migrated_engine, validating, constituency_settings=LOW)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason


@pytest.mark.parametrize(
    ("statements", "messages"),
    [
        (["DELETE FROM statement_rewordings"],
         ["applied rewording of statement 1 is not stored"]),
        (["UPDATE statements SET text = 'Otro texto distinto.' WHERE id = {s1}"],
         ["statement 1 is reworded without an accepted equivalence check",
          "applied rewording of statement 1 is not stored"]),
        (["UPDATE statements SET text = 'Otro texto distinto.' WHERE id = {s1}",
          "DELETE FROM statement_rewordings"],
         ["applied rewording of statement 1 is not stored"]),
        (["UPDATE statement_rewordings SET ai_text = (SELECT text FROM statements "
          "WHERE id = {s1})"],
         ["statement 1 rewording keeps the AI text",
          "applied rewording of statement 1 is not stored"]),
        (["INSERT INTO statement_rewordings (statement_id, ai_text, reason, explanation) "
          "VALUES ({s2}, 'Texto de antes.', 'Sin comprobar.', 'Nada.')"],
         ["statement 2 is reworded without an accepted equivalence check"]),
        (["UPDATE statement_rewordings SET reason = 'Otro motivo.'"],
         ["statement 1 is reworded without an accepted equivalence check",
          "applied rewording of statement 1 is not stored"]),
        ("report", ["statement 1 is reworded without an accepted equivalence check",
                    "applied rewording of statement 1 is not stored"]),
    ],
    ids=["delete-row", "change-text", "change-text-delete-row", "row-keeps-ai-text",
         "row-without-check", "edit-row-reason", "edit-report-entry"],
)
def test_a_tampered_rewording_fails_the_check(
    migrated_engine: Engine, validating: int, statements: Any, messages: list[str]
) -> None:
    version = _version_of(migrated_engine, validating)
    with Session(migrated_engine) as session:
        ids = session.scalars(
            select(Statement.id).where(Statement.dataset_version_id == version)
            .order_by(Statement.position)
        ).all()
    with migrated_engine.begin() as conn:
        if statements == "report":
            selection = json.loads(
                conn.execute(sa.text("SELECT statement_selection FROM pipeline_runs WHERE id = :r"),
                             {"r": validating}).scalar_one()
            )
            selection["rewordings"]["entries"][0]["text"] = "Texto editado en el informe."
            conn.execute(
                sa.text("UPDATE pipeline_runs SET statement_selection = :s WHERE id = :r"),
                {"s": json.dumps(selection), "r": validating},
            )
        else:
            for statement in statements:
                conn.execute(sa.text(statement.format(s1=ids[0], s2=ids[1])))

    outcome = validate_run(migrated_engine, validating, constituency_settings=LOW)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: statement_rewording"
    assert _failed_entries(migrated_engine, validating) == [
        ("statement_rewording", m) for m in messages
    ]


def test_the_database_refuses_a_blank_reason(
    migrated_engine: Engine, validating: int
) -> None:
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(sa.text("UPDATE statement_rewordings SET reason = ' '"))


# --- Legacy (scenario 8) -------------------------------------------------------------------


def test_a_format_1_bundle_never_reads_the_file(tmp_path: Path) -> None:
    directory = write_bundle(tmp_path)
    (directory / REWORDINGS_NAME).write_text("not toml at all [[[", encoding="utf-8")
    bundle = read_bundle(directory)
    assert [p.file for p in bundle.parties] == ["pp.md", "psoe.md"]
