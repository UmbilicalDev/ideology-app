"""live-mode-source-change-trigger Scenarios 1-7: the live trigger, at the service level."""

import datetime as dt
from pathlib import Path

import pytest
from pdf_factory import blank_pdf, make_text_pdf
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ideology_app import elections, llm
from ideology_app.config import GenerationMode, LLMSettings
from ideology_app.db import session_scope
from ideology_app.elections import DuplicateError
from ideology_app.http_fetch import FetchError
from ideology_app.models import (
    DatasetVersion,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    SourceDocumentStatus,
)
from ideology_app.pipeline import (
    PROMPT_VERSIONS,
    QUEUE_ON_SOURCE_CHANGE,
    SourceChangeOutcome,
    list_queued_run_ids,
    queue_run,
    queue_run_for_source_change,
    queues_on_source_change,
)
from ideology_app.pipeline import triggers
from ideology_app.source_documents import add_uploaded_document, add_url_document

LIVE = GenerationMode.LIVE
PRECOMPUTED = GenerationMode.PRECOMPUTED
SETTINGS = LLMSettings(provider="fake", model="fake-model")
URL = "https://example.org/programa.pdf"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)

    def _no_provider(*args: object, **kwargs: object) -> None:
        raise AssertionError("the trigger must never build an LLM provider")

    monkeypatch.setattr(llm, "build_provider", _no_provider)
    monkeypatch.setattr("ideology_app.cli.build_provider", _no_provider)


@pytest.fixture
def files_dir(tmp_path: Path) -> Path:
    return tmp_path / "stored"


def _pdf(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_bytes(make_text_pdf([text, "Segunda página."]))
    return path


@pytest.fixture
def setup(migrated_engine: Engine) -> dict[str, int]:
    """Election 1 with Parties A and B, Election 2 with Party C (no documents)."""
    with session_scope(migrated_engine) as session:
        ids: dict[str, int] = {}
        for key, year in (("e1", 2023), ("e2", 2027)):
            election = elections.create_election(
                session, country="ES", type="general", date=dt.date(year, 7, 23),
                name=f"Generales {year}",
            )
            ids[key] = election.id
        for key, election_key in (("a", "e1"), ("b", "e1"), ("c", "e2")):
            party = elections.add_party(
                session, election_id=ids[election_key], name=f"Partido {key}", short_name=key
            )
            ids[key] = party.id
    return ids


def _add(
    engine: Engine,
    party_id: int,
    path: Path,
    files_dir: Path,
    mode: GenerationMode,
    llm_settings: LLMSettings | None = SETTINGS,
) -> SourceChangeOutcome:
    """``source add --file`` minus the CLI: add and trigger in one transaction."""
    with session_scope(engine) as session:
        document = add_uploaded_document(
            session, party_id=party_id, file_path=path, files_dir=files_dir
        )
        return queue_run_for_source_change(
            session, document, generation_mode=mode, llm=llm_settings
        )


def _runs(engine: Engine) -> list[PipelineRun]:
    with Session(engine) as s:
        runs = list(s.scalars(select(PipelineRun).order_by(PipelineRun.id)))
        s.expunge_all()
        return runs


def _count(engine: Engine, model: type) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(model)) or 0


def _set_status(engine: Engine, run_id: int, status: PipelineRunStatus) -> None:
    with session_scope(engine) as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        run.status = status


# Scenario 1


def test_live_new_uploaded_document_queues_a_run(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    outcome = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE
    )

    runs = _runs(migrated_engine)
    assert len(runs) == 1
    run = runs[0]
    assert outcome == SourceChangeOutcome(setup["e1"], run.id, True)
    assert run.election_id == setup["e1"]
    assert run.status is PipelineRunStatus.QUEUED
    assert run.generation_mode is LIVE
    assert (run.llm_provider, run.llm_model) == ("fake", "fake-model")
    assert run.prompt_versions == PROMPT_VERSIONS
    assert (run.llm_calls, run.input_tokens, run.output_tokens) == (0, 0, 0)
    assert run.started_at is None
    assert _count(migrated_engine, DatasetVersion) == 0


def test_live_new_url_document_queues_a_run(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path
) -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return make_text_pdf(["Programa por URL."])

    with session_scope(migrated_engine) as session:
        document = add_url_document(
            session, party_id=setup["a"], url=URL, files_dir=files_dir, fetch=fetch
        )
        outcome = queue_run_for_source_change(
            session, document, generation_mode=LIVE, llm=SETTINGS
        )

    assert fetched == [URL]
    runs = _runs(migrated_engine)
    assert len(runs) == 1
    assert outcome == SourceChangeOutcome(setup["e1"], runs[0].id, True)
    assert runs[0].status is PipelineRunStatus.QUEUED
    assert runs[0].generation_mode is LIVE


# Scenario 2


def test_live_same_hash_is_a_duplicate_and_queues_nothing(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    pdf = _pdf(tmp_path, "a.pdf", "Programa A.")
    first = _add(migrated_engine, setup["a"], pdf, files_dir, PRECOMPUTED)
    assert first.run_id is None

    with pytest.raises(DuplicateError):
        _add(migrated_engine, setup["a"], pdf, files_dir, LIVE)

    assert _count(migrated_engine, SourceDocument) == 1
    assert _count(migrated_engine, PipelineRun) == 0


def test_live_same_bytes_for_another_party_queues_a_run(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    pdf = _pdf(tmp_path, "a.pdf", "Programa común.")
    _add(migrated_engine, setup["a"], pdf, files_dir, PRECOMPUTED)

    outcome = _add(migrated_engine, setup["b"], pdf, files_dir, LIVE)

    assert outcome.newly_queued is True
    assert _count(migrated_engine, PipelineRun) == 1


# Scenario 3


def test_precomputed_new_document_queues_nothing(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    outcome = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir,
        PRECOMPUTED, None,
    )

    assert outcome == SourceChangeOutcome(setup["e1"], None, False)
    assert _count(migrated_engine, PipelineRun) == 0
    assert _count(migrated_engine, SourceDocument) == 1


# Scenario 4


def test_live_blank_pdf_queues_nothing(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    blank = tmp_path / "scan.pdf"
    blank.write_bytes(blank_pdf(2))

    outcome = _add(migrated_engine, setup["a"], blank, files_dir, LIVE)

    assert outcome == SourceChangeOutcome(setup["e1"], None, False)
    assert _count(migrated_engine, PipelineRun) == 0
    with Session(migrated_engine) as s:
        assert s.scalars(select(SourceDocument.status)).all() == [SourceDocumentStatus.FAILED]


def test_live_failed_fetch_queues_nothing(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path
) -> None:
    def fetch(url: str) -> bytes:
        raise FetchError("HTTP 404: Not Found")

    with session_scope(migrated_engine) as session:
        document = add_url_document(
            session, party_id=setup["a"], url=URL, files_dir=files_dir, fetch=fetch
        )
        outcome = queue_run_for_source_change(
            session, document, generation_mode=LIVE, llm=SETTINGS
        )

    assert outcome == SourceChangeOutcome(setup["e1"], None, False)
    assert _count(migrated_engine, PipelineRun) == 0


# Scenario 5


def test_second_document_joins_the_queued_run(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    first = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE
    )
    second = _add(
        migrated_engine, setup["b"], _pdf(tmp_path, "b.pdf", "Programa B."), files_dir, LIVE
    )

    assert first.newly_queued is True
    assert second == SourceChangeOutcome(setup["e1"], first.run_id, False)
    assert [r.status for r in _runs(migrated_engine)] == [PipelineRunStatus.QUEUED]


def test_queued_run_of_another_election_does_not_coalesce(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    first = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE
    )
    other = _add(
        migrated_engine, setup["c"], _pdf(tmp_path, "c.pdf", "Programa C."), files_dir, LIVE
    )

    assert other.newly_queued is True
    assert other.election_id == setup["e2"]
    assert other.run_id != first.run_id
    with Session(migrated_engine) as s:
        assert list_queued_run_ids(s) == [first.run_id, other.run_id]
        assert list_queued_run_ids(s, setup["e2"]) == [other.run_id]


@pytest.mark.parametrize(
    "in_flight", [PipelineRunStatus.RUNNING, PipelineRunStatus.VALIDATING]
)
def test_in_flight_run_does_not_suppress_queuing(
    migrated_engine: Engine,
    setup: dict[str, int],
    files_dir: Path,
    tmp_path: Path,
    in_flight: PipelineRunStatus,
) -> None:
    first = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE
    )
    assert first.run_id is not None
    _set_status(migrated_engine, first.run_id, in_flight)

    second = _add(
        migrated_engine, setup["b"], _pdf(tmp_path, "b.pdf", "Programa B."), files_dir, LIVE
    )
    third = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a2.pdf", "Programa A v2."), files_dir, LIVE
    )

    assert second.newly_queued is True
    assert second.run_id != first.run_id
    assert third == SourceChangeOutcome(setup["e1"], second.run_id, False)
    assert [r.status for r in _runs(migrated_engine)] == [in_flight, PipelineRunStatus.QUEUED]


@pytest.mark.parametrize("finished", [PipelineRunStatus.PASSED, PipelineRunStatus.FAILED])
def test_finished_run_does_not_suppress_queuing(
    migrated_engine: Engine,
    setup: dict[str, int],
    files_dir: Path,
    tmp_path: Path,
    finished: PipelineRunStatus,
) -> None:
    first = _add(
        migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE
    )
    assert first.run_id is not None
    _set_status(migrated_engine, first.run_id, finished)

    second = _add(
        migrated_engine, setup["b"], _pdf(tmp_path, "b.pdf", "Programa B."), files_dir, LIVE
    )

    assert second.newly_queued is True
    assert _count(migrated_engine, PipelineRun) == 2


def test_coalesces_onto_the_lowest_id_queued_run(
    session: Session, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    document = add_uploaded_document(
        session, party_id=setup["a"], file_path=_pdf(tmp_path, "a.pdf", "A."), files_dir=files_dir
    )
    # Two queued runs can exist (e.g. queued before this feature); join the oldest.
    older = queue_run(session, setup["e1"], llm_provider="fake", llm_model="fake-model",
                      generation_mode=LIVE)
    queue_run(session, setup["e1"], llm_provider="fake", llm_model="fake-model",
              generation_mode=LIVE)

    outcome = queue_run_for_source_change(session, document, generation_mode=LIVE, llm=SETTINGS)

    assert outcome == SourceChangeOutcome(setup["e1"], older.id, False)


# Scenario 6


def test_trigger_failure_rolls_back_the_document(
    migrated_engine: Engine,
    setup: dict[str, int],
    files_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("queue failed")

    monkeypatch.setattr(triggers, "queue_run", _boom)

    with pytest.raises(RuntimeError, match="queue failed"):
        _add(migrated_engine, setup["a"], _pdf(tmp_path, "a.pdf", "Programa A."), files_dir, LIVE)

    assert _count(migrated_engine, SourceDocument) == 0
    assert _count(migrated_engine, PipelineRun) == 0


def test_trigger_does_not_commit(
    migrated_engine: Engine, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    with Session(migrated_engine) as session:
        document = add_uploaded_document(
            session, party_id=setup["a"], file_path=_pdf(tmp_path, "a.pdf", "A."),
            files_dir=files_dir,
        )
        outcome = queue_run_for_source_change(
            session, document, generation_mode=LIVE, llm=SETTINGS
        )
        assert outcome.newly_queued is True
        session.rollback()

    assert _count(migrated_engine, SourceDocument) == 0
    assert _count(migrated_engine, PipelineRun) == 0


def test_live_without_llm_settings_is_a_programming_error(
    session: Session, setup: dict[str, int], files_dir: Path, tmp_path: Path
) -> None:
    document = add_uploaded_document(
        session, party_id=setup["a"], file_path=_pdf(tmp_path, "a.pdf", "A."), files_dir=files_dir
    )

    with pytest.raises(ValueError, match="needs LLM settings"):
        queue_run_for_source_change(session, document, generation_mode=LIVE, llm=None)

    assert session.scalar(select(func.count()).select_from(PipelineRun)) == 0


# Scenario 7


def test_mode_table_covers_every_generation_mode() -> None:
    assert set(QUEUE_ON_SOURCE_CHANGE) == set(GenerationMode)
    assert queues_on_source_change(LIVE) is True
    assert queues_on_source_change(PRECOMPUTED) is False


def test_list_queued_run_ids_unknown_election(session: Session) -> None:
    with pytest.raises(elections.NotFoundError):
        list_queued_run_ids(session, 999)
