"""The four per-Constituency checks (constituency-selection-validation scenario 8).

Each test leaves a v2 run in ``validating`` (``validate_run`` is held back),
edits one stored row of its Dataset Version (in the test only) and checks that
``validate_run`` fails with exactly that check's name. FakeProvider only.
"""

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from v2_fixtures import setup, v2_fake

from ideology_app.config import ConstituencySettings, GenerationMode
from ideology_app.db import session_scope
from ideology_app.models import PipelineRun, PipelineRunStatus
from ideology_app.pipeline.runs import RunOutcome, validate_run
from ideology_app.pipeline.v2 import execute_v2_run, queue_v2_run
from ideology_app.pipeline.v2 import run as v2_run
from ideology_app.validation import ValidationInput
from ideology_app.validation.constituencies import (
    check_constituency_availability,
    check_constituency_order,
    check_constituency_snapshot,
    check_constituency_validity,
)

LOW = ConstituencySettings(1, 1)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def validating(tmp_path: Path, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> int:
    """A v2 run of the fixture left in ``validating`` (28 available, 2 Statements)."""
    directory = setup(tmp_path, migrated_engine)
    held: dict[str, Any] = {}

    def hold(engine: Engine, run_id: int, **kwargs: Any) -> RunOutcome:
        held["run_id"] = run_id
        return RunOutcome(run_id, PipelineRunStatus.VALIDATING, None, 0, None)

    monkeypatch.setattr(v2_run, "validate_run", hold)
    with session_scope(migrated_engine) as session:
        run_id = queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    execute_v2_run(migrated_engine, run_id, v2_fake(), directory, constituency_settings=LOW)
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None and run.status is PipelineRunStatus.VALIDATING
    return held["run_id"]


def _tamper(engine: Engine, *statements: str) -> None:
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(sa.text(statement))


def test_untampered_run_passes_every_check(migrated_engine: Engine, validating: int) -> None:
    outcome = validate_run(migrated_engine, validating, constituency_settings=LOW)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    assert outcome.publish is not None and outcome.publish.published


@pytest.mark.parametrize(
    ("name", "statements", "message"),
    [
        (
            "constituency_snapshot",
            ("DELETE FROM dataset_version_constituencies WHERE constituency_code = '05'",),
            "constituency rows: 51 stored, expected one per seeded constituency "
            "(missing: 05; unexpected or repeated: none)",
        ),
        (
            "constituency_validity",
            (
                "INSERT INTO constituency_statements (dataset_version_id, constituency_code, "
                "rank, statement_id) VALUES (1, '31', 1, 1)",
            ),
            "constituency 31: unavailable but lists 1 statements",
        ),
        (
            "constituency_availability",
            (
                "UPDATE dataset_version_constituencies SET valid_statement_count = 5 "
                "WHERE constituency_code = '31'",
            ),
            "constituency 31: valid_statement_count is 5, expected 0",
        ),
        (
            "constituency_order",
            (
                "UPDATE constituency_statements SET rank = 3 WHERE rank = 1",
                "UPDATE constituency_statements SET rank = 1 WHERE rank = 2",
                "UPDATE constituency_statements SET rank = 2 WHERE rank = 3",
            ),
            "constituency 28: rank 1 differs from the priority order "
            "(stored position 2, expected position 1)",
        ),
    ],
    ids=["snapshot", "validity", "availability", "order"],
)
def test_a_tampered_row_fails_that_check(
    migrated_engine: Engine,
    validating: int,
    name: str,
    statements: tuple[str, ...],
    message: str,
) -> None:
    _tamper(migrated_engine, *statements)

    outcome = validate_run(migrated_engine, validating, constituency_settings=LOW)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failed_checks == (name,)
    assert outcome.publish is None
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, validating)
        assert run is not None
        entries = [
            e.message for r in run.validation_results if r.check_name == name for e in r.entries
        ]
    assert entries == [message]


def test_more_snapshot_and_availability_failures(
    migrated_engine: Engine, validating: int
) -> None:
    _tamper(
        migrated_engine,
        # P (party 1) marked Excluded although it has Positions.
        "UPDATE dataset_version_candidatures SET excluded_reason = 'no_manifesto' "
        "WHERE party_id = 1 AND constituency_code = '31'",
        # X (party 3) with two different reasons.
        "INSERT INTO dataset_version_candidatures VALUES (1, 3, '08', 'too_few_proposals')",
        # Evidence counting where its Party does not run.
        "UPDATE party_position_proposals SET constituencies = '[\"28\", \"41\"]' "
        "WHERE id = (SELECT min(id) FROM party_position_proposals)",
        "UPDATE dataset_version_constituencies SET available = 0, "
        "unavailable_reason = 'too_few_statements', offered_lengths = '[]' "
        "WHERE constituency_code = '28'",
    )
    outcome = validate_run(migrated_engine, validating, constituency_settings=LOW)
    assert set(outcome.failed_checks) >= {"constituency_snapshot", "constituency_availability"}
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, validating)
        assert run is not None
        messages = {r.check_name: [e.message for e in r.entries] for r in run.validation_results}
    assert "party 1 has positions but is excluded" in messages["constituency_snapshot"]
    assert (
        "party 3 has different excluded reasons on its candidature rows"
        in messages["constituency_snapshot"]
    )
    assert any("counts in 41, where party" in m for m in messages["constituency_snapshot"])
    assert "no constituency is available" in messages["constituency_availability"]


def test_checks_pass_on_empty_legacy_shaped_input_except_k8() -> None:
    data = ValidationInput(statements=(), positions=(), party_ids=())
    assert [e.message for e in check_constituency_snapshot(data)] == [
        "constituency rows: 0 stored, expected one per seeded constituency (missing: "
        + ", ".join(f"{k:02d}" for k in range(1, 53))
        + "; unexpected or repeated: none)"
    ]
    assert check_constituency_validity(data) == []
    assert check_constituency_order(data) == []
    assert [e.message for e in check_constituency_availability(data)] == [
        "no constituency is available"
    ]


def test_validate_run_reads_the_minimums_from_the_environment_for_v2_only(
    migrated_engine: Engine, validating: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "0")
    from ideology_app.config import ConfigError

    with pytest.raises(ConfigError):
        validate_run(migrated_engine, validating)
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, validating)
        assert run is not None and run.status is PipelineRunStatus.VALIDATING
        assert run.validation_settings is None
    monkeypatch.setenv("VALIDATION_V2_MIN_STATEMENTS", "2")
    monkeypatch.setenv("VALIDATION_V2_MIN_PARTY_SIDES", "2")
    outcome = validate_run(migrated_engine, validating)
    assert outcome.status is PipelineRunStatus.PASSED, outcome.failure_reason
    with Session(migrated_engine) as session:
        run = session.get(PipelineRun, validating)
        assert run is not None and run.validation_settings is not None
        assert run.validation_settings["v2_min_statements"] == 2
