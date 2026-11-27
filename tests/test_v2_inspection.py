"""``pipeline.v2.inspection``: the read-only views of a stored v2 Dataset Version
(v2-run-inspection). FakeProvider only; bundles in ``tmp_path``."""

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session
from v2_fixtures import inspection_fake, one_proposal_slices, setup, v2_fake

from ideology_app.config import ConstituencySettings, GenerationMode
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.db import session_scope
from ideology_app.elections import NotFoundError
from ideology_app.models import PipelineRun
from ideology_app.pipeline.v2 import (
    ConstituencyTableRow,
    EvidenceRow,
    PartyRow,
    PartySides,
    SourceRow,
    constituency_rows,
    excerpt,
    execute_v2_run,
    party_rows,
    position_evidence,
    queue_v2_run,
    recorded_constituency_settings,
    source_no_stance,
    statement_sources,
)
from ideology_app.pipeline.v2 import positions as v2_positions

LOW = ConstituencySettings(1, 1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def _run(engine: Engine, directory: Path, provider: Any) -> int:
    with session_scope(engine) as session:
        run_id = queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    outcome = execute_v2_run(engine, run_id, provider, directory, constituency_settings=LOW)
    assert outcome.dataset_version_id is not None, outcome
    return outcome.dataset_version_id


def _selection(engine: Engine, run_id: int = 1) -> dict[str, Any]:
    with Session(engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None and run.statement_selection is not None
        return run.statement_selection


@pytest.fixture
def version(tmp_path: Path, migrated_engine: Engine) -> int:
    return _run(migrated_engine, setup(tmp_path, migrated_engine), v2_fake())


@pytest.fixture
def inspection_version(
    tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> int:
    monkeypatch.setattr(v2_positions, "position_slices", one_proposal_slices)
    return _run(migrated_engine, setup(tmp_path, migrated_engine), inspection_fake())


# --- pure helpers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Corto.", "Corto."),
        ("Dos\tlíneas\n\n y  espacios", "Dos líneas y espacios"),
        ("a" * 120, "a" * 120),
        ("a" * 121, "a" * 120 + "…"),
        ("a" * 118 + "\n\nb c", "a" * 118 + " b…"),
    ],
    ids=["short", "whitespace", "exactly-120", "cut", "cut-after-one-line"],
)
def test_excerpt(text: str, expected: str) -> None:
    assert excerpt(text) == expected


def test_recorded_constituency_settings() -> None:
    assert recorded_constituency_settings(None) is None
    assert recorded_constituency_settings({}) is None
    assert recorded_constituency_settings({"constituencies": {"rows": []}}) is None
    recorded = {
        "constituencies": {
            "settings": {
                "v2_min_statements": 3, "v2_min_party_sides": 1, "max_topic_share_percent": 30,
            }
        }
    }
    assert recorded_constituency_settings(recorded) == (ConstituencySettings(3, 1), 30)


# --- readers on a stored version -------------------------------------------------------


def test_party_rows(version: int, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        rows = party_rows(session, version, _selection(migrated_engine))
    assert rows == [
        PartyRow(1, "P", 5, True, 2, 0, None),
        PartyRow(2, "R", 3, False, 2, 0, None),
        PartyRow(3, "X", None, None, None, None, "no_manifesto"),
    ]


def test_constituency_rows_are_52_in_order(version: int, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        rows = constituency_rows(session, version, _selection(migrated_engine))
    assert rows is not None
    assert [(r.code, r.name) for r in rows] == list(CONSTITUENCIES)
    by_code = {r.code: r for r in rows}
    assert by_code["28"] == ConstituencyTableRow(
        code="28", name="Madrid", available=True, reason=None, parties=(1, 2), excluded=(3,),
        valid=2, lengths=(2,), party_sides=(PartySides(1, 2, 2), PartySides(2, 2, 2)),
        topic_max_share=(50,),
    )
    assert by_code["31"] == ConstituencyTableRow(
        code="31", name="Navarra", available=False, reason="fewer_than_two_parties",
        parties=(1,), excluded=(), valid=0, lengths=(), party_sides=(PartySides(1, 0, None),),
        topic_max_share=(),
    )


def test_constituency_rows_show_the_stored_valid_count(
    version: int, migrated_engine: Engine
) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE dataset_version_constituencies SET valid_statement_count = 7 "
                "WHERE constituency_code = '28'"
            )
        )
    with Session(migrated_engine) as session:
        rows = constituency_rows(session, version, _selection(migrated_engine))
    assert rows is not None
    assert {r.code: r.valid for r in rows}["28"] == 7


def test_constituency_rows_without_the_report_key(version: int, migrated_engine: Engine) -> None:
    selection = {k: v for k, v in _selection(migrated_engine).items() if k != "constituencies"}
    with Session(migrated_engine) as session:
        assert constituency_rows(session, version, selection) is None
        assert constituency_rows(session, version, None) is None


SOURCES = [
    (1, 1, 4, 1, "b.md", "Congelar el alquiler en la provincia."),
    (1, 2, 1, 1, "a.md", "Bajar el precio del alquiler en todo el país."),
    (1, 3, 6, 2, "r.md", "Liberalizar el suelo para construir más viviendas."),
    (1, 4, 3, 1, "a.md", "Construir más vivienda pública en alquiler."),
    (2, 1, 7, 2, "r.md", "Rebajar el impuesto de sociedades."),
    (2, 2, 8, 2, "r.md", "Eliminar el impuesto de patrimonio."),
    (2, 3, 2, 1, "a.md", "Subir el salario mínimo cada año."),
    (2, 4, 5, 1, "b.md", "Crear un banco público regional."),
]


def test_statement_sources(version: int, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        rows = statement_sources(session, version)
    assert rows == [
        SourceRow(statement, rank, proposal, party, file, 1, text)
        for statement, rank, proposal, party, file, text in SOURCES
    ]


def test_a_source_no_party_counts_gets_one_empty_row(
    version: int, migrated_engine: Engine
) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM dataset_version_proposals WHERE proposal_id = 6"))
    with Session(migrated_engine) as session:
        rows = statement_sources(session, version)
    assert rows[2] == SourceRow(
        1, 3, 6, None, None, 1, "Liberalizar el suelo para construir más viviendas."
    )


def test_position_evidence(version: int, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        rows = position_evidence(session, version, 1)
    assert rows == [
        EvidenceRow(1, 1, 2, 1, 1, "a.md", 1, ("28", "31"), True,
                    "Bajar el precio del alquiler en todo el país."),
        EvidenceRow(1, 1, 2, 2, 3, "a.md", 1, ("28", "31"), True,
                    "Construir más vivienda pública en alquiler."),
        EvidenceRow(1, 1, 2, 3, 4, "b.md", 1, ("28",), False,
                    "Congelar el alquiler en la provincia."),
        EvidenceRow(2, 1, -1, 1, 2, "a.md", 1, ("28", "31"), True,
                    "Subir el salario mínimo cada año."),
        EvidenceRow(2, 1, -1, 2, 5, "b.md", 1, ("28",), False,
                    "Crear un banco público regional."),
    ]


def test_position_evidence_refuses_an_unknown_party(version: int, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, pytest.raises(NotFoundError, match="party 99"):
        position_evidence(session, version, 99)


def test_no_stance_rows_and_source_parties(
    inspection_version: int, migrated_engine: Engine
) -> None:
    selection = _selection(migrated_engine)
    with Session(migrated_engine) as session:
        found = source_no_stance(session, inspection_version)
        evidence = position_evidence(session, inspection_version)
    assert found == [(1, 1), (1, 2)]
    assert len(found) == selection["positions"]["source_party_no_stance"]
    assert evidence[:2] == [
        EvidenceRow(1, 1, None, None, None, None, None, None, False, None),
        EvidenceRow(1, 2, None, None, None, None, None, None, False, None),
    ]


def test_source_no_stance_is_empty_when_every_party_sides(
    version: int, migrated_engine: Engine
) -> None:
    with Session(migrated_engine) as session:
        assert source_no_stance(session, version) == []
    assert _selection(migrated_engine)["positions"]["source_party_no_stance"] == 0


def test_the_readers_only_select(version: int, migrated_engine: Engine) -> None:
    selection = _selection(migrated_engine)
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(migrated_engine, "before_cursor_execute", record)
    try:
        with Session(migrated_engine) as session:
            party_rows(session, version, selection)
            constituency_rows(session, version, selection)
            source_no_stance(session, version)
            statement_sources(session, version)
            position_evidence(session, version)
            session.rollback()
    finally:
        event.remove(migrated_engine, "before_cursor_execute", record)
    assert statements
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements), statements
