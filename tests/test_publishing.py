"""auto-publish-dataset-version Scenarios 1-7: publishing a passed run's Dataset Version.

Temporary SQLite databases, ``FakeProvider`` only, sockets blocked, no API key.
"""

import threading
import time
from typing import Any

import pytest
from pipeline_fixtures import findings_response, fake_provider, offline_guard, seed_election
from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.llm import FakeProvider
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    PipelineRun,
    PipelineRunStatus,
    ValidationResult,
)
from ideology_app.pipeline import (
    PublishOutcome,
    execute_run,
    get_dataset_version,
    get_published_dataset_version,
    list_positions,
    publishing,
    queue_run,
    validate_run,
)
from ideology_app.pipeline import runs as runs_module

CHECK_COUNT = 6


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    seed_election(migrated_engine)
    return migrated_engine


def queue(engine: Engine, provider: FakeProvider) -> int:
    with session_scope(engine) as session:
        return queue_run(
            session,
            1,
            llm_provider=provider.name,
            llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id


def generate(engine: Engine, run_id: int, provider: FakeProvider) -> None:
    """Run generation only, leaving the run ``validating`` with a candidate version."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runs_module, "validate_run", lambda engine, run_id, **kwargs: None)
        execute_run(engine, run_id, provider)
    assert run_status(engine, run_id) is PipelineRunStatus.VALIDATING


def validating_run(engine: Engine, provider: FakeProvider | None = None) -> int:
    provider = provider or fake_provider()
    run_id = queue(engine, provider)
    generate(engine, run_id, provider)
    return run_id


def failing_provider() -> FakeProvider:
    """Both Parties agree everywhere: fails ``statement_separation``.

    (A count outside the range fails at generation, and the selection leaves out
    duplicates and topics over the cap, so a Validation failure needs one the
    selection cannot fix.)
    """
    return fake_provider(position_findings=findings_response(value=1))


def run_status(engine: Engine, run_id: int) -> PipelineRunStatus:
    with Session(engine) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        return run.status


def version_of(engine: Engine, run_id: int) -> int:
    with Session(engine) as s:
        found = s.scalar(
            select(DatasetVersion.id).where(DatasetVersion.pipeline_run_id == run_id)
        )
        assert found is not None
        return found


def statuses(engine: Engine) -> dict[int, DatasetVersionStatus]:
    with Session(engine) as s:
        return {v.id: v.status for v in s.scalars(select(DatasetVersion))}


def election_status(engine: Engine, election_id: int = 1) -> ElectionStatus:
    with Session(engine) as s:
        election = s.get(Election, election_id)
        assert election is not None
        return election.status


def published_count(engine: Engine, election_id: int = 1) -> int:
    with Session(engine) as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(
                    DatasetVersion.election_id == election_id,
                    DatasetVersion.status == DatasetVersionStatus.PUBLISHED,
                )
            )
            or 0
        )


def published_id(engine: Engine, election_id: int = 1) -> int | None:
    with Session(engine) as s:
        version = get_published_dataset_version(s, election_id)
        return None if version is None else version.id


def result_count(engine: Engine, run_id: int) -> int:
    with Session(engine) as s:
        return (
            s.scalar(
                select(func.count())
                .select_from(ValidationResult)
                .where(ValidationResult.pipeline_run_id == run_id)
            )
            or 0
        )


def snapshot(engine: Engine, dataset_version_id: int) -> tuple[Any, ...]:
    """Everything a reader sees of a Dataset Version (except its status)."""
    with Session(engine) as s:
        version = get_dataset_version(s, dataset_version_id)
        statements = [(st.id, st.position, st.text, st.topic) for st in version.statements]
        positions = [
            (
                p.id,
                p.statement_id,
                p.party_id,
                p.value,
                p.evidence_source_document_id,
                p.evidence_quote,
                p.evidence_page,
                p.evidence_url,
            )
            for p in list_positions(s, dataset_version_id)
        ]
        return (
            version.id,
            version.election_id,
            version.pipeline_run_id,
            version.created_at,
            statements,
            positions,
        )


# Scenario 1: the first passing run publishes


def test_first_passing_run_publishes_through_execute_run(seeded: Engine) -> None:
    provider = fake_provider()
    run_id = queue(seeded, provider)
    assert election_status(seeded) is ElectionStatus.DRAFT
    assert published_id(seeded) is None

    outcome = execute_run(seeded, run_id, provider)

    assert outcome.status is PipelineRunStatus.PASSED
    version_id = outcome.dataset_version_id
    assert version_id is not None
    assert outcome.publish == PublishOutcome(
        election_id=1,
        published=True,
        superseded_dataset_version_id=None,
        published_dataset_version_id=version_id,
        published_run_id=run_id,
    )
    assert statuses(seeded) == {version_id: DatasetVersionStatus.PUBLISHED}
    assert published_id(seeded) == version_id
    assert election_status(seeded) is ElectionStatus.ACTIVE
    assert result_count(seeded, run_id) == CHECK_COUNT


def test_first_passing_run_publishes_through_validate_run(seeded: Engine) -> None:
    run_id = validating_run(seeded)
    version_id = version_of(seeded, run_id)
    assert statuses(seeded) == {version_id: DatasetVersionStatus.CANDIDATE}

    outcome = validate_run(seeded, run_id)

    assert outcome.status is PipelineRunStatus.PASSED
    assert outcome.publish == PublishOutcome(
        election_id=1,
        published=True,
        superseded_dataset_version_id=None,
        published_dataset_version_id=version_id,
        published_run_id=run_id,
    )
    assert statuses(seeded) == {version_id: DatasetVersionStatus.PUBLISHED}
    assert election_status(seeded) is ElectionStatus.ACTIVE
    assert result_count(seeded, run_id) == CHECK_COUNT


def test_archived_election_stays_archived(seeded: Engine) -> None:
    with session_scope(seeded) as s:
        s.execute(update(Election).values(status=ElectionStatus.ARCHIVED))
    provider = fake_provider()

    outcome = execute_run(seeded, queue(seeded, provider), provider)

    assert outcome.publish is not None and outcome.publish.published
    assert published_id(seeded) == outcome.dataset_version_id
    assert election_status(seeded) is ElectionStatus.ARCHIVED


# Scenario 2: the next passing run supersedes; the superseded version stays readable


def test_next_passing_run_supersedes(seeded: Engine) -> None:
    first = fake_provider()
    v1 = execute_run(seeded, queue(seeded, first), first).dataset_version_id
    assert v1 is not None
    before = snapshot(seeded, v1)
    second = fake_provider()
    run2 = queue(seeded, second)

    outcome = execute_run(seeded, run2, second)

    v2 = outcome.dataset_version_id
    assert v2 is not None and v2 != v1
    assert outcome.publish == PublishOutcome(
        election_id=1,
        published=True,
        superseded_dataset_version_id=v1,
        published_dataset_version_id=v2,
        published_run_id=run2,
    )
    assert statuses(seeded) == {
        v1: DatasetVersionStatus.SUPERSEDED,
        v2: DatasetVersionStatus.PUBLISHED,
    }
    assert published_count(seeded) == 1
    assert published_id(seeded) == v2
    assert election_status(seeded) is ElectionStatus.ACTIVE
    assert snapshot(seeded, v1) == before
    assert len(before[4]) == 35 and len(before[5]) == 70


# Scenario 3: a failing run changes nothing about publication


def test_failing_run_keeps_the_published_version(seeded: Engine) -> None:
    first = fake_provider()
    v1 = execute_run(seeded, queue(seeded, first), first).dataset_version_id
    provider = failing_provider()
    run2 = queue(seeded, provider)

    outcome = execute_run(seeded, run2, provider)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.failure_reason is not None
    assert outcome.failure_reason.startswith("validation failed: ")
    assert outcome.failed_checks == ("statement_separation",)
    assert outcome.publish is None
    v2 = outcome.dataset_version_id
    assert v1 is not None and v2 is not None
    assert statuses(seeded) == {
        v1: DatasetVersionStatus.PUBLISHED,
        v2: DatasetVersionStatus.CANDIDATE,
    }
    assert election_status(seeded) is ElectionStatus.ACTIVE
    assert run_status(seeded, run2) is PipelineRunStatus.FAILED


def test_failing_first_run_publishes_nothing(seeded: Engine) -> None:
    provider = failing_provider()

    outcome = execute_run(seeded, queue(seeded, provider), provider)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.publish is None
    assert outcome.dataset_version_id is not None
    assert statuses(seeded) == {outcome.dataset_version_id: DatasetVersionStatus.CANDIDATE}
    assert published_id(seeded) is None
    assert election_status(seeded) is ElectionStatus.DRAFT


def test_failing_validate_run_keeps_the_published_version(seeded: Engine) -> None:
    first = fake_provider()
    v1 = execute_run(seeded, queue(seeded, first), first).dataset_version_id
    run2 = validating_run(seeded, failing_provider())

    outcome = validate_run(seeded, run2)

    assert outcome.status is PipelineRunStatus.FAILED
    assert outcome.publish is None
    assert published_id(seeded) == v1
    assert statuses(seeded)[version_of(seeded, run2)] is DatasetVersionStatus.CANDIDATE


# Scenario 4: publish order is the Pipeline Run id


def test_older_run_passing_after_newer_is_not_published(seeded: Engine) -> None:
    provider_a, provider_b = fake_provider(), fake_provider()
    run_a = queue(seeded, provider_a)
    run_b = queue(seeded, provider_b)
    assert run_a < run_b

    outcome_b = execute_run(seeded, run_b, provider_b)
    outcome_a = execute_run(seeded, run_a, provider_a)

    assert outcome_a.status is PipelineRunStatus.PASSED
    assert run_status(seeded, run_a) is PipelineRunStatus.PASSED
    v_a, v_b = outcome_a.dataset_version_id, outcome_b.dataset_version_id
    assert v_a is not None and v_b is not None
    assert outcome_a.publish == PublishOutcome(
        election_id=1,
        published=False,
        superseded_dataset_version_id=None,
        published_dataset_version_id=v_b,
        published_run_id=run_b,
    )
    assert statuses(seeded) == {
        v_a: DatasetVersionStatus.CANDIDATE,
        v_b: DatasetVersionStatus.PUBLISHED,
    }
    assert election_status(seeded) is ElectionStatus.ACTIVE


def test_newer_run_passing_after_older_supersedes(seeded: Engine) -> None:
    provider_a, provider_b = fake_provider(), fake_provider()
    run_a = queue(seeded, provider_a)
    run_b = queue(seeded, provider_b)

    v_a = execute_run(seeded, run_a, provider_a).dataset_version_id
    outcome_b = execute_run(seeded, run_b, provider_b)

    assert outcome_b.publish is not None
    assert outcome_b.publish.published
    assert outcome_b.publish.superseded_dataset_version_id == v_a
    assert statuses(seeded) == {
        v_a: DatasetVersionStatus.SUPERSEDED,
        outcome_b.dataset_version_id: DatasetVersionStatus.PUBLISHED,
    }


def test_older_run_publishes_when_newer_run_failed(seeded: Engine) -> None:
    provider_a, provider_b = fake_provider(), failing_provider()
    run_a = queue(seeded, provider_a)
    run_b = queue(seeded, provider_b)

    outcome_b = execute_run(seeded, run_b, provider_b)
    outcome_a = execute_run(seeded, run_a, provider_a)

    assert outcome_b.status is PipelineRunStatus.FAILED
    assert outcome_a.publish == PublishOutcome(
        election_id=1,
        published=True,
        superseded_dataset_version_id=None,
        published_dataset_version_id=outcome_a.dataset_version_id or 0,
        published_run_id=run_a,
    )
    assert statuses(seeded) == {
        outcome_a.dataset_version_id: DatasetVersionStatus.PUBLISHED,
        outcome_b.dataset_version_id: DatasetVersionStatus.CANDIDATE,
    }


def test_older_run_publishes_while_newer_run_is_unfinished(seeded: Engine) -> None:
    provider_a, provider_b = fake_provider(), fake_provider()
    run_a = queue(seeded, provider_a)
    run_b = queue(seeded, provider_b)
    generate(seeded, run_b, provider_b)

    outcome_a = execute_run(seeded, run_a, provider_a)
    assert outcome_a.publish is not None and outcome_a.publish.published

    outcome_b = validate_run(seeded, run_b)
    assert outcome_b.publish is not None
    assert outcome_b.publish.superseded_dataset_version_id == outcome_a.dataset_version_id
    assert published_id(seeded) == outcome_b.dataset_version_id


def test_supersede_when_the_newer_run_has_the_lower_version_id(seeded: Engine) -> None:
    """Version ids follow finish order: B (newer run) finished generating first.

    Publishing B's lower-id version over A's must flush the supersede first, or
    the unit of work would publish B before superseding A and hit the index.
    """
    provider_a, provider_b = fake_provider(), fake_provider()
    run_a = queue(seeded, provider_a)
    run_b = queue(seeded, provider_b)
    generate(seeded, run_b, provider_b)
    generate(seeded, run_a, provider_a)
    v_a, v_b = version_of(seeded, run_a), version_of(seeded, run_b)
    assert v_b < v_a

    assert validate_run(seeded, run_a).publish == PublishOutcome(
        election_id=1, published=True, published_dataset_version_id=v_a, published_run_id=run_a
    )
    outcome_b = validate_run(seeded, run_b)

    assert outcome_b.publish == PublishOutcome(
        election_id=1,
        published=True,
        superseded_dataset_version_id=v_a,
        published_dataset_version_id=v_b,
        published_run_id=run_b,
    )
    assert statuses(seeded) == {
        v_a: DatasetVersionStatus.SUPERSEDED,
        v_b: DatasetVersionStatus.PUBLISHED,
    }


# Scenario 5: atomic rollback


def test_publish_error_rolls_everything_back(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = fake_provider()
    v1 = execute_run(seeded, queue(seeded, first), first).dataset_version_id
    run2 = validating_run(seeded)
    v2 = version_of(seeded, run2)
    real = publishing.publish_dataset_version
    seen: list[PublishOutcome] = []

    def _publish_then_fail(session: Session, version: DatasetVersion) -> PublishOutcome:
        seen.append(real(session, version))
        raise RuntimeError("boom after publishing")

    monkeypatch.setattr(publishing, "publish_dataset_version", _publish_then_fail)

    with pytest.raises(RuntimeError, match="boom after publishing"):
        validate_run(seeded, run2)

    assert seen and seen[0].superseded_dataset_version_id == v1
    assert statuses(seeded) == {
        v1: DatasetVersionStatus.PUBLISHED,
        v2: DatasetVersionStatus.CANDIDATE,
    }
    assert election_status(seeded) is ElectionStatus.ACTIVE
    assert result_count(seeded, run2) == 0
    with Session(seeded) as s:
        run = s.get(PipelineRun, run2)
        assert run is not None
        assert run.status is PipelineRunStatus.FAILED
        assert run.failure_reason == "unexpected error: RuntimeError"


def test_publish_error_on_first_publish_keeps_election_draft(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = validating_run(seeded)
    real = publishing.publish_dataset_version

    def _publish_then_fail(session: Session, version: DatasetVersion) -> PublishOutcome:
        real(session, version)
        raise RuntimeError("boom")

    monkeypatch.setattr(publishing, "publish_dataset_version", _publish_then_fail)

    with pytest.raises(RuntimeError):
        validate_run(seeded, run_id)

    assert published_id(seeded) is None
    assert election_status(seeded) is ElectionStatus.DRAFT
    assert run_status(seeded, run_id) is PipelineRunStatus.FAILED


def test_publish_refuses_a_version_that_is_not_candidate(seeded: Engine) -> None:
    provider = fake_provider()
    version_id = execute_run(seeded, queue(seeded, provider), provider).dataset_version_id
    with Session(seeded) as s:
        version = s.get(DatasetVersion, version_id)
        assert version is not None
        with pytest.raises(ValueError, match="expected candidate"):
            publishing.publish_dataset_version(s, version)


# Scenario 6: concurrent finishers on SQLite


@pytest.mark.parametrize("x_is", ["lower", "higher"])
def test_concurrent_finishers_publish_exactly_one(
    seeded: Engine, monkeypatch: pytest.MonkeyPatch, x_is: str
) -> None:
    low = validating_run(seeded)
    high = validating_run(seeded)
    run_x, run_y = (low, high) if x_is == "lower" else (high, low)
    real = publishing.publish_dataset_version
    x_published = threading.Event()
    release = threading.Event()

    def _held(session: Session, version: DatasetVersion) -> PublishOutcome:
        outcome = real(session, version)
        if threading.current_thread().name == "X":
            x_published.set()
            release.wait(timeout=10)
        return outcome

    monkeypatch.setattr(publishing, "publish_dataset_version", _held)
    errors: list[BaseException] = []
    outcomes: dict[str, Any] = {}

    def _validate(name: str, run_id: int) -> None:
        try:
            outcomes[name] = validate_run(seeded, run_id)
        except BaseException as exc:  # recorded and asserted below
            errors.append(exc)

    x = threading.Thread(target=_validate, args=("X", run_x), name="X")
    y = threading.Thread(target=_validate, args=("Y", run_y), name="Y")
    x.start()
    assert x_published.wait(timeout=10)
    y.start()
    time.sleep(0.3)
    assert y.is_alive()  # Y waits for X's write lock
    release.set()
    x.join(timeout=10)
    y.join(timeout=10)

    assert not x.is_alive() and not y.is_alive()
    assert errors == []
    assert run_status(seeded, low) is PipelineRunStatus.PASSED
    assert run_status(seeded, high) is PipelineRunStatus.PASSED
    v_low, v_high = version_of(seeded, low), version_of(seeded, high)
    assert published_count(seeded) == 1
    assert published_id(seeded) == v_high
    expected_low = (
        DatasetVersionStatus.SUPERSEDED if x_is == "lower" else DatasetVersionStatus.CANDIDATE
    )
    assert statuses(seeded) == {v_low: expected_low, v_high: DatasetVersionStatus.PUBLISHED}


# Scenario 7: database backstop and the lock statement


def test_partial_index_rejects_a_second_published_version(seeded: Engine) -> None:
    first, second = fake_provider(), failing_provider()
    v1 = execute_run(seeded, queue(seeded, first), first).dataset_version_id
    v2 = execute_run(seeded, queue(seeded, second), second).dataset_version_id

    with pytest.raises(IntegrityError):
        with session_scope(seeded) as s:
            s.execute(
                update(DatasetVersion)
                .where(DatasetVersion.id == v2)
                .values(status=DatasetVersionStatus.PUBLISHED)
            )

    assert statuses(seeded) == {
        v1: DatasetVersionStatus.PUBLISHED,
        v2: DatasetVersionStatus.CANDIDATE,
    }


def test_lock_statement_is_for_update_on_postgresql() -> None:
    sql = str(publishing.election_lock_statement(1).compile(dialect=postgresql.dialect()))

    assert sql.endswith("FOR UPDATE")
    assert "FROM elections" in sql
    assert "WHERE elections.id = " in sql
