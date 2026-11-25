"""Constituency Selection of a v2 run (constituency-selection-validation scenarios 1, 2, 5-7, 9, 10).

``select_constituencies`` on plain data, and v2 runs on a scratch database
with the canned v2 fake (``v2_fixtures``). FakeProvider only; the offline
guard blocks every other LLM path.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from v2_fixtures import STATEMENTS, positions_responder, setup, v2_fake

from ideology_app.config import ConstituencySettings, GenerationMode, ValidationSettings
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.db import session_scope
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    DatasetVersionStatus,
    Election,
    ModelGeneration,
    Party,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunCall,
    PipelineRunStatus,
    Statement,
)
from ideology_app.pipeline.v2 import (
    EvidenceRef,
    ExcludedParty,
    Phase4Input,
    PoolDraft,
    V2Position,
    constituency_summary,
    dataset_version_problems,
    execute_v2_run,
    load_phase4,
    queue_v2_run,
    select_constituencies,
)

LOW = ConstituencySettings(1, 1)
CODES = [code for code, _ in CONSTITUENCIES]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


# --- Plain data --------------------------------------------------------------------------


def _draft(category: str = "housing", n: int = 1) -> PoolDraft:
    return PoolDraft(f"Afirmación {n}.", "Nota.", category, (n,))


def _position(value: int | None, codes: tuple[str, ...] = ("28", "31")) -> V2Position:
    if value is None:
        return V2Position(None)
    return V2Position(value, (EvidenceRef(1, 1, codes, 1, "texto", None),))


def _phase4(
    candidatures: dict[int, tuple[str, ...]], excluded: tuple[ExcludedParty, ...] = ()
) -> Phase4Input:
    return Phase4Input(1, "slug", (), (), candidatures=candidatures, excluded=excluded)


def _select(statements, positions, phase4, settings=LOW, share: int = 30):
    return select_constituencies(statements, positions, phase4, share, settings)


def test_s5_statement_is_valid_in_28_but_not_31() -> None:
    # Scenario 2: Party 2's only Evidence counts in 28; in 31 nobody is against.
    statements = [_draft()]
    positions = {1: [_position(1)], 2: [_position(-1, ("28",))]}
    selection = _select(statements, positions, _phase4({1: ("28", "31"), 2: ("28", "31")}))
    rows = {row.code: row for row in selection.rows}
    assert rows["28"].available and rows["28"].valid_statement_count == 1
    assert rows["31"].unavailable_reason == "too_few_statements"
    assert rows["31"].valid_statement_count == 0
    assert selection.statements_by_code == {"28": (1,)}


def test_low_coverage_constituency_is_unavailable_and_another_stays_available() -> None:
    # Scenario 5 (pure part): in 31 Party 3 takes a side on 4 of 6 valid Statements.
    statements = [_draft(n=k) for k in range(1, 7)]
    positions = {
        1: [_position(1) for _ in range(6)],
        2: [_position(-1) for _ in range(6)],
        3: [_position(1 if k < 4 else None) for k in range(6)],
    }
    phase4 = _phase4({1: ("28", "31"), 2: ("28", "31"), 3: ("31",)})
    selection = _select(statements, positions, phase4, ConstituencySettings(1, 5))
    rows = {row.code: row for row in selection.rows}
    assert rows["28"].available and rows["28"].offered_lengths == (6,)
    assert rows["31"].unavailable_reason == "low_party_coverage"
    assert rows["31"].detail == {"parties": [{"party_id": 3, "sides": 4}], "minimum": 5}
    assert rows["31"].offered_lengths == () and "31" not in selection.statements_by_code
    report_31 = next(r for r in selection.report["rows"] if r["code"] == "31")
    assert report_31["party_sides"] == [
        {"party_id": 1, "sides": 6, "first_length_sides": None},
        {"party_id": 2, "sides": 6, "first_length_sides": None},
        {"party_id": 3, "sides": 4, "first_length_sides": None},
    ]


def test_valid_nowhere_and_excluded_snapshot() -> None:
    statements = [_draft(n=1), _draft("economy", 2)]
    positions = {1: [_position(1), _position(1)], 2: [_position(-1), _position(None)]}
    phase4 = _phase4(
        {1: ("28",), 2: ("28",), 3: ("08", "28")},
        (ExcludedParty(3, "X", "discarded_at_review"),),
    )
    selection = _select(statements, positions, phase4)
    assert selection.report["valid_nowhere"] == [2]
    assert [(c.party_id, c.code, c.excluded_reason) for c in selection.snapshot] == [
        (1, "28", None), (2, "28", None), (3, "08", "discarded_at_review"),
        (3, "28", "discarded_at_review"),
    ]
    row_28 = next(r for r in selection.report["rows"] if r["code"] == "28")
    assert (row_28["parties"], row_28["excluded"]) == ([1, 2], [3])
    row_08 = next(r for r in selection.report["rows"] if r["code"] == "08")
    assert (row_08["parties"], row_08["excluded"]) == ([], [3])
    assert next(r for r in selection.rows if r.code == "08").detail == {"parties": 0}


def _random_case(seed: int) -> tuple[list[PoolDraft], dict[int, list[V2Position]], Phase4Input]:
    import random

    rng = random.Random(seed)
    parties = [1, 2, 3, 4, 5]
    candidatures = {p: tuple(sorted(rng.sample(["08", "28", "31", "41"], rng.randint(1, 4))))
                    for p in parties}
    topics = ["housing", "economy", "health", "education"]
    statements = [_draft(rng.choice(topics), k) for k in range(1, 41)]
    positions = {
        p: [
            _position(rng.choice([-2, -1, 0, 1, 2, None]),
                      tuple(sorted(rng.sample(candidatures[p], rng.randint(1, len(candidatures[p]))))))
            for _ in statements
        ]
        for p in parties
    }
    return statements, positions, _phase4(candidatures)


def test_relabelling_parties_gives_the_same_rows_and_determinism() -> None:
    # Scenario 7.
    statements, positions, phase4 = _random_case(3)
    settings = ConstituencySettings(3, 2)
    original = _select(statements, positions, phase4, settings)
    relabel = {1: 50, 2: 20, 3: 40, 4: 10, 5: 30}
    relabelled = _select(
        statements,
        {relabel[p]: v for p, v in positions.items()},
        _phase4({relabel[p]: c for p, c in phase4.candidatures.items()}),
        settings,
    )
    assert relabelled.statements_by_code == original.statements_by_code
    for a, b in zip(original.rows, relabelled.rows, strict=True):
        assert (a.code, a.available, a.unavailable_reason, a.valid_statement_count,
                a.offered_lengths) == (b.code, b.available, b.unavailable_reason,
                                       b.valid_statement_count, b.offered_lengths)
        if a.unavailable_reason == "low_party_coverage":
            assert sorted((relabel[x["party_id"]], x["sides"]) for x in a.detail["parties"]) == [
                (x["party_id"], x["sides"]) for x in b.detail["parties"]
            ]
    assert sorted((relabel[c.party_id], c.code) for c in original.snapshot) == [
        (c.party_id, c.code) for c in relabelled.snapshot
    ]
    assert original.report["valid_nowhere"] == relabelled.report["valid_nowhere"]
    again = _select(statements, positions, phase4, settings)
    assert again == original
    assert json.dumps(again.report, sort_keys=True) == json.dumps(original.report, sort_keys=True)
    assert len(original.rows) == 52 and [r.code for r in original.rows] == CODES


# --- The gate snapshot -------------------------------------------------------------------


def _ids(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {p.short_name: p.id for p in session.scalars(select(Party))}


def test_load_phase4_copies_candidatures_and_excluded_reasons(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    ids = _ids(migrated_engine)
    with Session(migrated_engine) as session:
        phase4 = load_phase4(session, directory)
    assert dict(phase4.candidatures) == {
        ids["P"]: ("28", "31"), ids["R"]: ("28",), ids["X"]: ("28",)
    }
    assert phase4.excluded == (ExcludedParty(ids["X"], "X", "no_manifesto"),)
    assert [p.party_id for p in phase4.parties] == [ids["P"], ids["R"]]


# --- v2 runs on a scratch database -------------------------------------------------------


def _queue(engine: Engine, source: int | None = None) -> int:
    with session_scope(engine) as session:
        return queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED, resumed_from_run_id=source,
            allow_finished_source=source is not None,
        ).id


def _run(engine: Engine, directory: Path, provider: Any, settings: ConstituencySettings,
         source: int | None = None):
    return execute_v2_run(
        engine, _queue(engine, source), provider, directory, constituency_settings=settings
    )


class _NoCalls:
    name, model = "fake", "fake-model"

    def generate(self, request: Any) -> Any:
        raise AssertionError("no call expected")


def _stored(engine: Engine, version_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        positions = {
            s.id: s.position
            for s in session.scalars(select(Statement).where(Statement.dataset_version_id == version_id))
        }
        rows = {
            r.constituency_code: (
                r.available, r.unavailable_reason, r.valid_statement_count,
                r.offered_lengths, r.detail,
            )
            for r in session.scalars(
                select(DatasetVersionConstituency)
                .where(DatasetVersionConstituency.dataset_version_id == version_id)
            )
        }
        snapshot = [
            (c.party_id, c.constituency_code, c.excluded_reason)
            for c in session.scalars(
                select(DatasetVersionCandidature)
                .where(DatasetVersionCandidature.dataset_version_id == version_id)
                .order_by(DatasetVersionCandidature.party_id,
                          DatasetVersionCandidature.constituency_code)
            )
        ]
        ranked: dict[str, list[tuple[int, int]]] = {}
        for c in session.scalars(
            select(ConstituencyStatement)
            .where(ConstituencyStatement.dataset_version_id == version_id)
            .order_by(ConstituencyStatement.constituency_code, ConstituencyStatement.rank)
        ):
            ranked.setdefault(c.constituency_code, []).append((c.rank, positions[c.statement_id]))
    return {"rows": rows, "snapshot": snapshot, "ranked": ranked}


def test_scenario_1_two_constituencies_one_unavailable(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    ids = _ids(migrated_engine)

    outcome = _run(migrated_engine, directory, v2_fake(), LOW)

    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    assert outcome.publish is not None and outcome.publish.published
    stored = _stored(migrated_engine, outcome.dataset_version_id)
    assert len(stored["rows"]) == 52 and sorted(stored["rows"]) == CODES
    # 28: P (in favour on housing, against on economy) against R on both, pool order.
    assert stored["rows"]["28"] == (True, None, 2, [2], None)
    assert stored["ranked"] == {"28": [(1, 1), (2, 2)]}
    assert stored["rows"]["31"] == (False, "fewer_than_two_parties", 0, [], {"parties": 1})
    for code in CODES:
        if code not in ("28", "31"):
            assert stored["rows"][code] == (False, "fewer_than_two_parties", 0, [], {"parties": 0})
    assert stored["snapshot"] == [
        (ids["P"], "28", None), (ids["P"], "31", None), (ids["R"], "28", None),
        (ids["X"], "28", "no_manifesto"),
    ]
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, outcome.run_id)
        assert run is not None and run.dataset_version is not None
        assert run.dataset_version.status is DatasetVersionStatus.PUBLISHED
        report = run.statement_selection["constituencies"]
        assert report["settings"] == {
            "v2_min_statements": 1, "v2_min_party_sides": 1, "max_topic_share_percent": 30,
        }
        assert report["available"] == 1 and len(report["unavailable"]) == 51
        assert report["valid_nowhere"] == []
        row_28 = next(r for r in report["rows"] if r["code"] == "28")
        assert row_28 == {
            "code": "28", "parties": [ids["P"], ids["R"]], "excluded": [ids["X"]], "valid": 2,
            "lengths": [2],
            "party_sides": [
                {"party_id": ids["P"], "sides": 2, "first_length_sides": 2},
                {"party_id": ids["R"], "sides": 2, "first_length_sides": 2},
            ],
            "topic_max_share": [50],
        }
        # Flat: every ValidationSettings key, then the two v2 minimums.
        assert list(run.validation_settings) == [
            *ValidationSettings.__dataclass_fields__, "v2_min_statements", "v2_min_party_sides",
        ]
        assert run.validation_settings["v2_min_statements"] == 1
        assert run.validation_settings["v2_min_party_sides"] == 1
        summary = constituency_summary(session, outcome.dataset_version_id)
        assert dataset_version_problems(session) == []
    assert summary is not None and summary.startswith("1 available, 51 unavailable (01 fewer")
    assert summary.endswith("; 0 statements valid in no available constituency")
    with Session(migrated_engine) as session:
        texts = session.scalars(
            select(Statement.text)
            .join(ConstituencyStatement, ConstituencyStatement.statement_id == Statement.id)
            .order_by(ConstituencyStatement.rank)
        ).all()
    assert texts == [STATEMENTS["Vivienda"][0], STATEMENTS["Economía"][0]]


def test_scenario_6_none_available_fails_and_publishes_nothing(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)

    outcome = _run(migrated_engine, directory, v2_fake(), ConstituencySettings())

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason == "validation failed: constituency_availability"
    assert outcome.publish is None
    stored = _stored(migrated_engine, outcome.dataset_version_id)
    assert stored["rows"]["28"] == (
        False, "too_few_statements", 2, [], {"statements": 2, "minimum": 10}
    )
    assert stored["ranked"] == {}
    with Session(migrated_engine) as session:
        version = session.get(DatasetVersion, outcome.dataset_version_id)
        assert version is not None and version.status is DatasetVersionStatus.CANDIDATE
        assert session.get(Election, 1).status.value == "draft"
        entries = [
            e.message for r in session.get(PipelineRun, outcome.run_id).validation_results
            if r.check_name == "constituency_availability" for e in r.entries
        ]
    assert entries == ["no constituency is available"]


def test_scenario_5_low_coverage_with_another_available_passes(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    # R takes a side only on housing: 28 has one valid Statement and R one side there.
    stances = {
        "Bajar el precio del alquiler en todo el país.": 2,
        "Liberalizar el suelo para construir más viviendas.": -1,
        "Subir el salario mínimo cada año.": -1,
    }
    provider = v2_fake(positions=positions_responder(stances))

    outcome = _run(migrated_engine, directory, provider, ConstituencySettings(1, 2))

    # The only Constituency with two Parties is below the coverage minimum: run fails.
    assert outcome.status is PipelineRunStatus.FAILED
    stored = _stored(migrated_engine, outcome.dataset_version_id)
    assert stored["rows"]["28"][1] == "low_party_coverage"
    assert stored["rows"]["28"][4]["parties"] == [
        {"party_id": p, "sides": 1} for p in sorted(_ids(migrated_engine)[s] for s in ("P", "R"))
    ]
    assert outcome.failure_reason == "validation failed: constituency_availability"


def test_scenario_9_replay_follows_new_thresholds_with_zero_calls(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    first = _run(migrated_engine, directory, v2_fake(), LOW)
    assert first.status is PipelineRunStatus.PASSED and first.publish.published

    strict = _run(migrated_engine, directory, _NoCalls(), ConstituencySettings(3, 1), first.run_id)
    assert strict.status is PipelineRunStatus.FAILED
    assert _stored(migrated_engine, strict.dataset_version_id)["rows"]["28"][:2] == (
        False, "too_few_statements"
    )

    exact = _run(migrated_engine, directory, _NoCalls(), ConstituencySettings(2, 2), first.run_id)
    assert exact.status is PipelineRunStatus.PASSED, exact.failure_reason
    assert exact.publish is not None and exact.publish.published
    assert exact.publish.superseded_dataset_version_id == first.dataset_version_id
    with Session(migrated_engine) as session:
        statuses = {
            v.id: v.status for v in session.scalars(select(DatasetVersion).order_by(DatasetVersion.id))
        }
        # Every call of the replays is a reused recording (the provider raises on a call).
        calls = [
            session.scalar(
                select(func.count()).select_from(PipelineRunCall).where(
                    PipelineRunCall.pipeline_run_id == r, ~PipelineRunCall.reused
                )
            )
            for r in (strict.run_id, exact.run_id)
        ]
    assert statuses == {
        first.dataset_version_id: DatasetVersionStatus.SUPERSEDED,
        strict.dataset_version_id: DatasetVersionStatus.CANDIDATE,
        exact.dataset_version_id: DatasetVersionStatus.PUBLISHED,
    }
    assert calls == [0, 0]


def test_v2_publish_supersedes_a_published_legacy_version(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    with session_scope(migrated_engine) as session:
        legacy = PipelineRun(
            election_id=1, status=PipelineRunStatus.PASSED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
        )
        session.add(legacy)
        session.flush()
        version = DatasetVersion(
            election_id=1, pipeline_run_id=legacy.id, status=DatasetVersionStatus.PUBLISHED
        )
        session.add(version)
        session.flush()
        legacy_version = version.id

    outcome = _run(migrated_engine, directory, v2_fake(), LOW)

    assert outcome.publish is not None and outcome.publish.published
    assert outcome.publish.superseded_dataset_version_id == legacy_version
    with Session(migrated_engine) as session:
        assert session.get(DatasetVersion, legacy_version).model_generation is ModelGeneration.LEGACY
        assert dataset_version_problems(session) == []


def test_dataset_version_problems_reports_bad_rows(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    outcome = _run(migrated_engine, directory, v2_fake(), LOW)
    version = outcome.dataset_version_id
    with session_scope(migrated_engine) as session:
        session.execute(
            DatasetVersionConstituency.__table__.delete().where(
                DatasetVersionConstituency.constituency_code == "05"
            )
        )
        session.execute(
            ConstituencyStatement.__table__.delete().where(ConstituencyStatement.rank == 2)
        )
        legacy = PipelineRun(
            election_id=1, status=PipelineRunStatus.PASSED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
        )
        session.add(legacy)
        session.flush()
        old = DatasetVersion(election_id=1, pipeline_run_id=legacy.id)
        session.add(old)
        session.flush()
        session.add(
            DatasetVersionCandidature(
                dataset_version_id=old.id, party_id=1, constituency_code="28"
            )
        )
        old_id = old.id
    with Session(migrated_engine) as session:
        assert dataset_version_problems(session) == [
            f"dataset version {version} has 51 constituency rows, expected one for each of "
            "the 52 constituencies",
            f"dataset version {version}, constituency 28: ranks are not 1..2",
            f"dataset version {old_id} (legacy) has 1 rows in dataset_version_candidatures",
        ]


# --- public-dataset-api-v2 A8: frozen counted Proposals in db check -------------------------


def test_db_check_reports_a_legacy_version_with_frozen_proposals(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    outcome = _run(migrated_engine, directory, v2_fake(), LOW)
    with session_scope(migrated_engine) as session:
        frozen = session.scalars(select(DatasetVersionProposal).limit(1)).one()
        legacy = PipelineRun(
            election_id=1, status=PipelineRunStatus.PASSED, llm_provider="fake",
            llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
            prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
        )
        session.add(legacy)
        session.flush()
        old = DatasetVersion(election_id=1, pipeline_run_id=legacy.id)
        session.add(old)
        session.flush()
        session.add(
            DatasetVersionProposal(
                dataset_version_id=old.id, party_id=frozen.party_id, rank=1,
                proposal_id=frozen.proposal_id, source_document_id=frozen.source_document_id,
                constituencies=["28"],
            )
        )
        old_id = old.id
    with Session(migrated_engine) as session:
        assert dataset_version_problems(session) == [
            f"dataset version {old_id} (legacy) has 1 rows in dataset_version_proposals"
        ]
    assert outcome.dataset_version_id != old_id


def test_db_check_reports_a_v2_version_without_frozen_proposals(
    tmp_path: Path, migrated_engine: Engine
) -> None:
    directory = setup(tmp_path, migrated_engine)
    version = _run(migrated_engine, directory, v2_fake(), LOW).dataset_version_id
    with session_scope(migrated_engine) as session:
        session.execute(DatasetVersionProposal.__table__.delete())
    with Session(migrated_engine) as session:
        assert dataset_version_problems(session) == [
            f"dataset version {version} has no frozen counted proposals"
        ]


@pytest.mark.parametrize("tamper", ["missing", "codes"])
def test_db_check_reports_evidence_not_frozen_with_the_same_constituencies(
    tmp_path: Path, migrated_engine: Engine, tamper: str
) -> None:
    directory = setup(tmp_path, migrated_engine)
    version = _run(migrated_engine, directory, v2_fake(), LOW).dataset_version_id
    with Session(migrated_engine) as session:
        evidence = session.scalars(
            select(PartyPositionProposal).order_by(PartyPositionProposal.id).limit(1)
        ).one()
        party_id = session.scalar(
            select(DatasetVersionProposal.party_id).where(
                DatasetVersionProposal.proposal_id == evidence.proposal_id
            ).limit(1)
        )
        proposal_id = evidence.proposal_id
    with session_scope(migrated_engine) as session:
        target = DatasetVersionProposal.__table__.c
        where = (target.party_id == party_id) & (target.proposal_id == proposal_id)
        if tamper == "missing":
            session.execute(DatasetVersionProposal.__table__.delete().where(where))
        else:
            session.execute(
                DatasetVersionProposal.__table__.update().where(where).values(
                    constituencies=["01"]
                )
            )
    with Session(migrated_engine) as session:
        assert dataset_version_problems(session) == [
            f"dataset version {version}: evidence proposal {proposal_id} of party {party_id} "
            "is not frozen with the same constituencies"
        ]
