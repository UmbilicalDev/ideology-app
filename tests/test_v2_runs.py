"""The v2 Pipeline Run on a scratch database (statements-from-proposals scenarios 1-10, 12).

A run that should pass uses ``ConstituencySettings(1, 1)`` (``LOW``): with the
default minimums no Constituency of the fixture is available and the run fails
(constituency-selection-validation K8, covered in ``test_v2_selection``). A
passed v2 run is published (K12).

FakeProvider only; the offline guard blocks every other LLM path. Bundles live
in ``tmp_path`` (see ``v2_fixtures``).
"""

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from bundle_factory import DocumentSpec
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from v2_fixtures import (
    NOTE,
    PARTY_NAMES,
    STATEMENTS,
    drafts_responder,
    listed_statements,
    page,
    positions_responder,
    setup,
    v2_fake,
)

from ideology_app import ingestion_ledger as ledgers
from ideology_app.config import ConstituencySettings, GenerationMode
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.elections import InvalidInputError
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionProposal,
    DatasetVersionStatus,
    ModelGeneration,
    Party,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunCall,
    PipelineRunSourceDocument,
    PipelineRunStatus,
    Proposal,
    SourceDocumentRole,
    Statement,
    StatementProposal,
    ValidationResult,
)
from ideology_app.pipeline import (
    LEGACY_REFUSED_REASON,
    execute_run,
    find_unfinished_run,
    get_run_report,
    queue_run,
)
from ideology_app.pipeline.runs import _check_resumable
from ideology_app.pipeline.v2 import Phase4Error, execute_v2_run, load_phase4, queue_v2_run
from ideology_app.pipeline.v2 import run as v2_run

V2_CHECK_NAMES = [
    "evidence_quotes", "evidence_proposals", "statement_sources",
    "statement_uniqueness", "context_note", "constituency_snapshot",
    "constituency_validity", "constituency_availability", "constituency_order",
    "statement_rewording",
]
LOW = ConstituencySettings(1, 1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def _queue(engine: Engine, election_id: int = 1, **kwargs: Any) -> int:
    with session_scope(engine) as session:
        return queue_v2_run(
            session,
            election_id,
            llm_provider="fake",
            llm_model=kwargs.pop("model", "fake-model"),
            generation_mode=GenerationMode.PRECOMPUTED,
            **kwargs,
        ).id


def _run(
    engine: Engine,
    directory: Path,
    provider: Any,
    constituency_settings: ConstituencySettings = LOW,
    **kwargs: Any,
):
    run_id = _queue(engine, **kwargs)
    return execute_v2_run(
        engine, run_id, provider, directory, constituency_settings=constituency_settings
    )


def _count(engine: Engine, model: type) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def _party_ids(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {p.short_name: p.id for p in session.scalars(select(Party))}


def _dataset(engine: Engine, version_id: int) -> list[tuple[Any, ...]]:
    """Statements, sources, Positions and Evidence of a version, without ids."""
    with Session(engine) as session:
        rows: list[tuple[Any, ...]] = []
        for s in session.scalars(
            select(Statement).where(Statement.dataset_version_id == version_id)
            .order_by(Statement.position)
        ):
            sources = session.scalars(
                select(StatementProposal.proposal_id)
                .where(StatementProposal.statement_id == s.id).order_by(StatementProposal.rank)
            ).all()
            rows.append(("S", s.position, s.text, s.topic, s.context_note, tuple(sources)))
            for p in session.scalars(
                select(PartyPosition).where(PartyPosition.statement_id == s.id)
                .order_by(PartyPosition.party_id)
            ):
                evidence = session.execute(
                    select(
                        PartyPositionProposal.rank, PartyPositionProposal.proposal_id,
                        PartyPositionProposal.source_document_id,
                        PartyPositionProposal.constituencies,
                    )
                    .where(PartyPositionProposal.party_position_id == p.id)
                    .order_by(PartyPositionProposal.rank)
                ).all()
                rows.append(
                    ("P", s.position, p.party_id, p.value, p.evidence_source_document_id,
                     p.evidence_quote, p.evidence_page, p.evidence_url,
                     tuple(tuple(e) for e in evidence))
                )
        return rows


# --- Scenario 1: the gate -----------------------------------------------------------------


def _assert_nothing_written(engine: Engine) -> None:
    for model in (PipelineRun, PipelineRunCall, DatasetVersion, Statement):
        assert _count(engine, model) == 0, model


def test_gate_refuses_a_pending_party(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine, exclude_x=False)
    with Session(migrated_engine) as session, pytest.raises(Phase4Error) as refused:
        load_phase4(session, directory)
    assert refused.value.blockers == (
        'party X: candidature_declared (next: list a manifesto in [[documents]] or record '
        '"ingestion no-manifesto")',
    )
    _assert_nothing_written(migrated_engine)


def test_gate_refuses_unchecked_and_pending_conflicts(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine, detect=False)
    with Session(migrated_engine) as session, pytest.raises(Phase4Error) as refused:
        load_phase4(session, directory)
    assert refused.value.blockers[0].startswith("conflict pending: P: a.md + b.md (28): not checked")


def test_gate_refuses_a_pending_decision(tmp_path: Path, migrated_engine: Engine) -> None:
    flag = [{"a": 1, "b": 1, "explanation": "Se contradicen."}]
    directory = setup(tmp_path, migrated_engine, contradictions=flag)
    with Session(migrated_engine) as session, pytest.raises(Phase4Error) as refused:
        load_phase4(session, directory)
    assert "contradictions; run \"ideology conflicts decide" in refused.value.blockers[0]


def test_gate_refuses_an_out_of_date_ledger(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    changed = DocumentSpec("r.md", "R", [page("r.md") + " Más texto."], ["R"])
    (directory / "r.md").write_bytes(changed.content())
    with Session(migrated_engine) as session, pytest.raises(Phase4Error) as refused:
        load_phase4(session, directory)
    assert any("ingestion ledger is out of date" in b for b in refused.value.blockers)


def test_gate_refuses_a_count_mismatch(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM proposals WHERE id = (SELECT max(id) FROM proposals)"))
    with Session(migrated_engine) as session, pytest.raises(Phase4Error) as refused:
        load_phase4(session, directory)
    assert refused.value.blockers[0].startswith(
        "document r.md: ledger records 3 validated proposals, the database has 2"
    )


def test_gate_refuses_an_election_that_is_not_imported(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    other_url = f"sqlite:///{tmp_path}/other.db"
    run_migrations(other_url)
    other = make_engine(other_url)
    try:
        with Session(other) as session, pytest.raises(Phase4Error) as refused:
            load_phase4(session, directory)
    finally:
        other.dispose()
    assert str(refused.value).startswith("election es-general-2023-07-23 is not imported")
    assert refused.value.blockers == ()


def test_start_marks_the_run_failed_when_the_gate_closes(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    run_id = _queue(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM proposals WHERE id = (SELECT max(id) FROM proposals)"))
    provider = v2_fake()
    outcome = execute_v2_run(migrated_engine, run_id, provider, directory)
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason.startswith("phase 4 blocked: document r.md: ledger records 3")
    assert provider.calls == []
    assert _count(migrated_engine, PipelineRunSourceDocument) == 0


# --- Scenarios 2-4, 9: happy path, Evidence, against, neutrality ---------------------------


def test_happy_path_writes_and_publishes_a_v2_version(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    ids = _party_ids(migrated_engine)
    provider = v2_fake()

    outcome = _run(migrated_engine, directory, provider)

    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    assert outcome.model_generation is ModelGeneration.V2
    assert outcome.publish is not None and outcome.publish.published
    assert outcome.publish.published_dataset_version_id == outcome.dataset_version_id
    assert outcome.publish.superseded_dataset_version_id is None
    assert outcome.statement_count == 2
    assert outcome.position_count == 4  # P and R only; X is Excluded
    assert [r.task for r in provider.calls] == ["statement_drafts"] * 2 + ["proposal_positions"] * 4
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, outcome.run_id)
        assert run is not None
        assert run.model_generation is ModelGeneration.V2
        assert run.prompt_versions == {
            "statement_drafts": "v1", "proposal_positions": "v1", "statement_rewording_check": "v1",
        }
        assert run.anchor_dataset_version_id is None
        version = run.dataset_version
        assert version is not None
        assert version.model_generation is ModelGeneration.V2
        assert version.status is DatasetVersionStatus.PUBLISHED
        assert version.questionnaire_lengths is None
        assert session.get(type(run.election), run.election_id).status.value == "active"
        assert run.validation_settings is not None
        assert run.validation_settings["v2_min_statements"] == 1
        assert run.validation_settings["v2_min_party_sides"] == 1
        assert [r.check_name for r in session.scalars(select(ValidationResult))] == V2_CHECK_NAMES
        assert all(r.passed for r in session.scalars(select(ValidationResult)))
        documents = session.execute(
            select(PipelineRunSourceDocument.source_document_id, PipelineRunSourceDocument.role)
            .order_by(PipelineRunSourceDocument.source_document_id)
        ).all()
        assert documents == [
            (1, SourceDocumentRole.MAIN), (2, SourceDocumentRole.ADDITIONAL),
            (3, SourceDocumentRole.MAIN),
        ]
        texts = {p.id: p.text for p in session.scalars(select(Proposal))}
    rows = _dataset(migrated_engine, outcome.dataset_version_id)
    statements = [r for r in rows if r[0] == "S"]
    assert [(r[2], r[3], r[4]) for r in statements] == [
        (STATEMENTS["Vivienda"][0], "housing", NOTE),
        (STATEMENTS["Economía"][0], "economy", NOTE),
    ]
    # Sources in citation order = the bucket order (tags casefolded, hash, ordinal).
    assert [[texts[i] for i in r[5]] for r in statements] == [
        [
            "Congelar el alquiler en la provincia.",
            "Bajar el precio del alquiler en todo el país.",
            "Liberalizar el suelo para construir más viviendas.",
            "Construir más vivienda pública en alquiler.",
        ],
        [
            "Rebajar el impuesto de sociedades.",
            "Eliminar el impuesto de patrimonio.",
            "Subir el salario mínimo cada año.",
            "Crear un banco público regional.",
        ],
    ]
    positions = {(r[1], r[2]): r for r in rows if r[0] == "P"}
    assert set(positions) == {(1, ids["P"]), (1, ids["R"]), (2, ids["P"]), (2, ids["R"])}
    # P is in favour on housing (Bajar: +2), R against (Liberalizar: -1).
    p_housing, r_housing = positions[(1, ids["P"])], positions[(1, ids["R"])]
    assert (p_housing[3], r_housing[3]) == (2, -1)
    assert [texts[e[1]] for e in p_housing[8]] == [
        "Bajar el precio del alquiler en todo el país.",
        "Construir más vivienda pública en alquiler.",
        "Congelar el alquiler en la provincia.",
    ]
    # Rank 1 is mirrored; Evidence carries its Constituencies (b.md counts only in 28).
    assert p_housing[4:8] == (1, "Bajar el precio del alquiler en todo el país.", 1, None)
    assert [e[3] for e in p_housing[8]] == [["28", "31"], ["28", "31"], ["28"]]
    assert r_housing[8] == ((1, 6, 3, ["28"]),)
    # Party neutrality: no Party name, short name, file name or page marker in a prompt.
    for request in provider.calls:
        for name in (*PARTY_NAMES, "[página"):
            assert name not in request.prompt and name not in request.system


def _frozen(engine: Engine, version_id: int) -> list[tuple[Any, ...]]:
    with Session(engine) as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    DatasetVersionProposal.party_id,
                    DatasetVersionProposal.rank,
                    DatasetVersionProposal.proposal_id,
                    DatasetVersionProposal.source_document_id,
                    DatasetVersionProposal.constituencies,
                )
                .where(DatasetVersionProposal.dataset_version_id == version_id)
                .order_by(DatasetVersionProposal.party_id, DatasetVersionProposal.rank)
            )
        ]


def _expected_frozen(engine: Engine, directory: Path) -> list[tuple[Any, ...]]:
    with Session(engine) as session:
        phase4 = load_phase4(session, directory)
    return [
        (party.party_id, rank, p.proposal_id, p.source_document_id, list(p.constituencies))
        for party in phase4.parties
        for rank, p in enumerate(party.proposals, start=1)
    ]


def test_finish_freezes_every_counted_proposal_of_each_non_excluded_party(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    # public-dataset-api-v2 scenario 11 / A8: one row per PhaseProposal, counted order.
    directory = setup(tmp_path, migrated_engine)
    ids = _party_ids(migrated_engine)
    expected = _expected_frozen(migrated_engine, directory)

    outcome = _run(migrated_engine, directory, v2_fake())

    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    frozen = _frozen(migrated_engine, outcome.dataset_version_id)
    assert frozen == expected
    assert {row[0] for row in frozen} == {ids["P"], ids["R"]}  # X is Excluded
    with Session(migrated_engine) as session:
        texts = {p.id: p.text for p in session.scalars(select(Proposal))}
    assert [(texts[r[2]], r[4]) for r in frozen if r[0] == ids["P"]] == [
        ("Bajar el precio del alquiler en todo el país.", ["28", "31"]),
        ("Subir el salario mínimo cada año.", ["28", "31"]),
        ("Construir más vivienda pública en alquiler.", ["28", "31"]),
        ("Congelar el alquiler en la provincia.", ["28"]),
        ("Crear un banco público regional.", ["28"]),
    ]
    assert len([r for r in frozen if r[0] == ids["R"]]) == 3


def test_finish_freezes_the_counted_set_after_a_conflict_decision(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    # A set-aside Proposal is not frozen where it was set aside (here: anywhere).
    flag = [{"a": 1, "b": 1, "explanation": "Se contradicen."}]
    directory = setup(tmp_path, migrated_engine, contradictions=flag, decide=("a.md", "b.md"))
    expected = _expected_frozen(migrated_engine, directory)
    outcome = _run(migrated_engine, directory, v2_fake())
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    frozen = _frozen(migrated_engine, outcome.dataset_version_id)
    assert frozen == expected
    with Session(migrated_engine) as session:
        texts = {p.id: p.text for p in session.scalars(select(Proposal))}
    assert "Congelar el alquiler en la provincia." not in {texts[r[2]] for r in frozen}


def test_report_records_the_pool_and_partial_scope(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    ids = _party_ids(migrated_engine)
    outcome = _run(migrated_engine, directory, v2_fake())
    with Session(migrated_engine) as session:
        report = get_run_report(session, outcome.run_id)
    assert report.model_generation is ModelGeneration.V2
    selection = dict(report.statement_selection or {})
    constituencies = selection.pop("constituencies")
    assert constituencies["version"] == "v2-constituency-1"
    assert constituencies["available"] == 1
    assert constituencies["valid_nowhere"] == []
    assert selection == {
        "version": "v2-pool-1",
        "bundle": "es-general-2023-07-23",
        "parties": [
            {"party_id": ids["P"], "proposals": 5, "partial_scope": True},
            {"party_id": ids["R"], "proposals": 3, "partial_scope": False},
        ],
        "partial_scope_parties": [ids["P"]],
        "proposals": 8,
        "categories": [
            {"category": "housing", "proposals": 4, "calls": 1, "drafted": 1, "additions": 0},
            {"category": "economy", "proposals": 4, "calls": 1, "drafted": 1, "additions": 0},
        ],
        "filtered": [],
        "pool_size": 2,
        "positions": {
            "calls": 4, "sided": 4, "no_stance": 0, "slice_disagreements": [],
            "source_party_no_stance": 0,
        },
    }


def test_omitted_statement_is_no_stance_and_counted_as_source_party(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    ids = _party_ids(migrated_engine)
    # R takes no side on anything: every listed Statement is left out.
    stances = {
        "Bajar el precio del alquiler en todo el país.": 2,
        "Subir el salario mínimo cada año.": -1,
    }
    outcome = _run(migrated_engine, directory, v2_fake(positions=positions_responder(stances)))
    # Nothing separates P and R anywhere: no Constituency is available (K8), but the
    # version is written in full and the valid-nowhere Statements are kept (K7).
    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: constituency_availability"
    assert outcome.publish is None
    rows = _dataset(migrated_engine, outcome.dataset_version_id)
    r_rows = [r for r in rows if r[0] == "P" and r[2] == ids["R"]]
    assert [(r[3], r[4], r[8]) for r in r_rows] == [(None, None, ()), (None, None, ())]
    with Session(migrated_engine) as session:
        selection = get_run_report(session, outcome.run_id).statement_selection
    assert selection["positions"]["source_party_no_stance"] == 2
    assert selection["constituencies"]["valid_nowhere"] == [1, 2]


def test_empty_evidence_fails_the_run(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)

    def no_evidence(request: Any) -> dict[str, Any]:
        return {"positions": [{"statement": 1, "value": 1, "evidence": []}]}

    outcome = _run(migrated_engine, directory, v2_fake(positions=no_evidence))
    assert outcome.status is PipelineRunStatus.FAILED
    assert "does not match ProposalPositionList" in outcome.failure_reason
    assert _count(migrated_engine, DatasetVersion) == 0


# --- Scenario 5: conflicts and scope --------------------------------------------------------


def test_set_aside_proposals_are_not_in_the_party_prompt(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    flag = [{"a": 1, "b": 1, "explanation": "Se contradicen."}]
    directory = setup(tmp_path, migrated_engine, contradictions=flag, decide=("a.md", "b.md"))
    provider = v2_fake()
    outcome = _run(migrated_engine, directory, provider)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    # b.md applies only in 28, the overlap: both its contradicting Proposals are set aside.
    prompts = "\n".join(r.prompt for r in provider.calls)
    assert "Congelar el alquiler" not in prompts and "banco público regional" not in prompts
    with Session(migrated_engine) as session:
        selection = get_run_report(session, outcome.run_id).statement_selection
        documents = session.scalars(select(PipelineRunSourceDocument.source_document_id)).all()
    assert selection["partial_scope_parties"] == []
    assert sorted(documents) == [1, 3]


# --- Scenario 6: slices in a run ------------------------------------------------------------


def test_budget_refuses_before_any_call(
    tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = setup(tmp_path, migrated_engine)
    monkeypatch.setattr(v2_run, "MAX_V2_CALLS_PER_RUN", 5)
    provider = v2_fake()
    outcome = _run(migrated_engine, directory, provider)
    assert outcome.failure_reason == "too many v2 calls planned: 6 (limit 5)"
    assert provider.calls == [] and _count(migrated_engine, PipelineRunCall) == 0


# --- Scenario 7: the filter ------------------------------------------------------------------


def test_filtered_statements_get_no_position_calls(tmp_path: Path, migrated_engine: Engine) -> None:
    directory = setup(tmp_path, migrated_engine)
    drafts = drafts_responder(
        {
            "Vivienda": [
                "Debe limitarse el precio del alquiler de vivienda.",
                "Debe limitarse el precio del alquiler de vivienda",
            ],
            "Economía": ["Deben bajarse los impuestos a las empresas."],
        }
    )

    def bad_note(request: Any) -> dict[str, Any]:
        answer = drafts(request)
        if request.prompt.startswith("Tema: Economía"):
            answer["statements"].append(
                {"text": "Debe nacionalizarse la banca.", "context_note": "Una medida injusta "
                 "que afecta a todos los bancos del país.", "sources": [1]}
            )
        return answer

    provider = v2_fake(drafts=bad_note)
    outcome = _run(migrated_engine, directory, provider)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    listed = [s for r in provider.calls if r.task == "proposal_positions" for s in listed_statements(r)]
    assert "Debe nacionalizarse la banca." not in listed
    assert "Debe limitarse el precio del alquiler de vivienda" not in listed
    with Session(migrated_engine) as session:
        selection = get_run_report(session, outcome.run_id).statement_selection
    assert selection["filtered"] == [
        {"pool": 2, "status": "duplicate", "text": "Debe limitarse el precio del alquiler de vivienda"},
        {"pool": 4, "status": "context_invalid", "text": "Debe nacionalizarse la banca."},
    ]
    assert selection["pool_size"] == 2


# --- Scenario 8: resume and replay -----------------------------------------------------------


def test_resume_reuses_recorded_calls_and_reuse_replays_with_zero_calls(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    failed = _run(migrated_engine, directory, v2_fake(fail_on_call=4))
    assert failed.status is PipelineRunStatus.FAILED
    assert failed.failure_reason == "provider overloaded (529)"
    assert _count(migrated_engine, PipelineRunCall) == 3
    with Session(migrated_engine) as session:
        unfinished = find_unfinished_run(session, 1, "fake", "fake-model", ModelGeneration.V2)
        assert unfinished is not None and unfinished.run_id == failed.run_id
        assert find_unfinished_run(session, 1, generation=ModelGeneration.LEGACY) is None

    provider = v2_fake()
    resumed = _run(migrated_engine, directory, provider, resumed_from_run_id=failed.run_id)
    assert resumed.status is PipelineRunStatus.PASSED, resumed.failure_reason
    assert len(provider.calls) == 3  # only the rest

    class Raising:
        name, model = "fake", "fake-model"
        calls: list[Any] = []

        def generate(self, request: Any) -> Any:
            raise AssertionError("no call expected")

    replay = _run(
        migrated_engine, directory, Raising(), resumed_from_run_id=resumed.run_id,
        allow_finished_source=True,
    )
    assert replay.status is PipelineRunStatus.PASSED, replay.failure_reason
    assert _dataset(migrated_engine, replay.dataset_version_id) == _dataset(
        migrated_engine, resumed.dataset_version_id
    )


def test_resume_across_generations_is_refused(tmp_path: Path, migrated_engine: Engine) -> None:
    setup(tmp_path, migrated_engine)
    with session_scope(migrated_engine) as session:
        legacy = PipelineRun(
            election_id=1, status=PipelineRunStatus.FAILED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
        )
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id
    with session_scope(migrated_engine) as session:
        with pytest.raises(InvalidInputError, match="is a legacy run, not v2"):
            queue_v2_run(
                session, 1, llm_provider="fake", llm_model="fake-model",
                generation_mode=GenerationMode.PRECOMPUTED, resumed_from_run_id=legacy_id,
            )
    v2_id = _queue(migrated_engine)
    with Session(migrated_engine) as session:
        with pytest.raises(InvalidInputError, match="is a v2 run, not legacy"):
            _check_resumable(session, v2_id, 1, "fake", "fake-model")


# --- Scenario 10: legacy guards --------------------------------------------------------------


def test_legacy_run_is_refused_on_an_election_with_candidatures(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    setup(tmp_path, migrated_engine)
    with session_scope(migrated_engine) as session:
        with pytest.raises(InvalidInputError) as refused:
            queue_run(
                session, 1, llm_provider="fake", llm_model="fake-model",
                generation_mode=GenerationMode.PRECOMPUTED,
            )
    assert str(refused.value) == (
        'election 1 has candidatures (format 2); run "ideology pipeline run-v2 DIR"'
    )
    # A legacy run queued before (e.g. by the old live trigger) is failed when it starts.
    with session_scope(migrated_engine) as session:
        run = PipelineRun(
            election_id=1, status=PipelineRunStatus.QUEUED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.LIVE,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
        )
        session.add(run)
        session.flush()
        run_id = run.id
    provider = v2_fake()
    outcome = execute_run(migrated_engine, run_id, provider)
    assert (outcome.status, outcome.failure_reason) == (PipelineRunStatus.FAILED, LEGACY_REFUSED_REASON)
    assert provider.calls == []
    with Session(migrated_engine) as session:
        stored = session.get(PipelineRun, run_id)
        assert stored is not None and stored.failure_reason == "legacy run refused: election has candidatures"


def test_legacy_executor_refuses_a_queued_v2_run(tmp_path: Path, migrated_engine: Engine) -> None:
    setup(tmp_path, migrated_engine)
    run_id = _queue(migrated_engine)
    with pytest.raises(InvalidInputError, match="is a v2 run"):
        execute_run(migrated_engine, run_id, v2_fake())
    with Session(migrated_engine) as session:
        stored = session.get(PipelineRun, run_id)
        assert stored is not None and stored.status is PipelineRunStatus.QUEUED
