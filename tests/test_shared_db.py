"""One committed SQLite database for all Elections (shared-database).

Scenarios 1-6 of docs/specs/shared-database.md. Every test builds its own
``data/ideology.db`` under ``tmp_path`` (the conftest chdirs there), so the
shared path resolves inside the test directory and the committed file is
never touched. The fake provider only; no network.
"""

import datetime as dt
import hashlib
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory
from bundle_factory import PartySpec, manifest_text, write_bundle
from click.testing import CliRunner, Result
from fastapi.testclient import TestClient
from pipeline_fixtures import PAGES, fake_provider, findings_response, offline_guard
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session

from ideology_app import cli, config, shared_db
from ideology_app.cli import main
from ideology_app.config import GenerationMode
from ideology_app.db import alembic_config, make_engine, run_migrations, session_scope
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest, LLMResult
from ideology_app.main import create_app
from ideology_app.models import (
    Election,
    ElectionStatus,
    PipelineRun,
    PipelineRunCall,
    PipelineRunStatus,
    SourceDocumentPage,
    Statement,
)
from ideology_app.pipeline import find_unfinished_run, queue_run

SHARED_URL = "sqlite:///data/ideology.db"
SLUG_2023 = "es-general-2023-07-23"
SLUG_2027 = "es-general-2027-05-30"
DATE_2027 = dt.date(2027, 5, 30)

# Page text equals the pipeline fixtures' seeded pages, so the default fake
# findings give the two Parties opposite values and the run passes Validation.
ALFA = PartySpec("PA", "Partido Alfa", "pa.md", PAGES[1])
BETA = PartySpec("BB", "Bloque Beta", "bb.md", PAGES[2])
PARTIES = (ALFA, BETA)

PROMPT_START = "Database data/ideology.db is shared through git."
REFUSAL = "refusing to generate on the shared database without confirmation; pass --yes"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)
    monkeypatch.delenv("ELECTIONS_DATA_DIR", raising=False)


def invoke(*args: str, url: str = SHARED_URL, input: str | None = None) -> Result:
    return CliRunner().invoke(main, ["--database-url", url, *args], input=input)


def ok(result: Result) -> Result:
    assert result.exit_code == 0, result.output
    return result


def write_bundles(root: Path, *, second: bool = False) -> None:
    """Bundles under ``root/data/elections``: 2023, and with ``second`` also 2027."""
    elections = root / "data" / "elections"
    write_bundle(elections, PARTIES, slug=SLUG_2023)
    if second:
        write_bundle(
            elections,
            PARTIES,
            slug=SLUG_2027,
            manifest=manifest_text(PARTIES, date=DATE_2027, name="Elecciones generales 2027"),
        )


def build_shared(root: Path, *, second: bool = False) -> None:
    """``root/data/ideology.db`` built like the committed one: upgrade, then import."""
    write_bundles(root, second=second)
    ok(invoke("db", "upgrade"))
    ok(invoke("data", "import", f"data/elections/{SLUG_2023}"))
    if second:
        ok(invoke("data", "import", f"data/elections/{SLUG_2027}"))


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    """The shared DB with Elections 1 (2023) and 2 (2027) in ``tmp_path``."""
    build_shared(tmp_path, second=True)
    return tmp_path / "data" / "ideology.db"


@pytest.fixture
def engine(shared: Path) -> Iterator[Engine]:
    eng = make_engine(f"sqlite:///{shared}")
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def use_provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], Any]:
    def _use(provider: Any) -> Any:
        monkeypatch.setattr(cli, "_provider", lambda: provider)
        return provider

    return _use


@pytest.fixture
def interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)


class Stopping:
    """Delegates to a FakeProvider, then raises on call number ``stop_at``."""

    def __init__(self, inner: FakeProvider, stop_at: int) -> None:
        self.name = inner.name
        self.model = inner.model
        self._inner = inner
        self._stop_at = stop_at
        self.count = 0

    def generate(self, request: LLMRequest[Any]) -> LLMResult[Any]:
        self.count += 1
        if self.count == self._stop_at:
            raise LLMProviderError("usage limit beyond max wait")
        return self._inner.generate(request)


def runs(engine: Engine) -> list[tuple[int, int, PipelineRunStatus]]:
    with Session(engine) as s:
        return [
            (r.id, r.election_id, r.status)
            for r in s.scalars(select(PipelineRun).order_by(PipelineRun.id))
        ]


def run_count(path: Path) -> int:
    eng = make_engine(f"sqlite:///{path}")
    try:
        with Session(eng) as s:
            return s.scalar(select(func.count()).select_from(PipelineRun)) or 0
    finally:
        eng.dispose()


def stop_run(use_provider: Callable[[Any], Any], election: int = 1, stop_at: int = 4) -> None:
    """A CLI run on the shared DB whose provider fails on call ``stop_at``."""
    use_provider(Stopping(fake_provider(), stop_at))
    result = invoke("pipeline", "run", "--election", str(election), "--yes")
    assert result.exit_code == 1, result.output
    assert "failed" in result.output


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Scenario 1: selection and web --------------------------------------------


def test_shared_url_detection(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    assert shared_db.is_shared(SHARED_URL)
    assert shared_db.is_shared(f"sqlite:///{tmp_path}/data/ideology.db")
    assert shared_db.is_shared(f"sqlite:///{tmp_path}/data/../data/ideology.db")
    assert shared_db.is_shared(shared_db.read_only_url(tmp_path / "data" / "ideology.db"))
    assert not shared_db.is_shared(f"sqlite:///{tmp_path}/test.db")
    assert not shared_db.is_shared(f"sqlite:///{tmp_path}/other/data/ideology.db")
    assert not shared_db.is_shared("sqlite://")
    assert not shared_db.is_shared("sqlite:///:memory:")
    assert not shared_db.is_shared("postgresql://u@h/data/ideology.db")
    assert not shared_db.is_shared("not a url")


def test_default_url_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.database_url() == "sqlite:///ideology.db"
    assert config.SHARED_DATABASE_PATH == Path("data/ideology.db")
    assert not shared_db.is_shared(config.database_url())


def test_cli_marks_the_shared_database(
    shared: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []

    @main.command("_probe")
    @cli.click.pass_obj
    def _probe(app: cli.AppContext) -> None:
        seen.append(app.shared)

    try:
        ok(invoke("_probe"))
        ok(invoke("_probe", url=db_url))
        monkeypatch.setenv("DATABASE_URL", SHARED_URL)
        ok(CliRunner().invoke(main, ["_probe"]))
    finally:
        main.commands.pop("_probe")
    assert seen == [True, False, True]


def test_read_only_url_opens_without_writing(tmp_path: Path) -> None:
    odd = tmp_path / "a b#c?d"
    odd.mkdir()
    path = odd / "x.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    assert shared_db.sqlite_path(shared_db.read_only_url(path)) == path

    eng = create_engine(shared_db.read_only_url(path))
    try:
        with eng.connect() as c:
            assert c.exec_driver_sql("SELECT count(*) FROM t").scalar() == 0
            with pytest.raises(Exception, match="readonly"):
                c.exec_driver_sql("INSERT INTO t VALUES (1)")
    finally:
        eng.dispose()
    missing = tmp_path / "missing.db"
    eng = create_engine(shared_db.read_only_url(missing))
    try:
        with pytest.raises(Exception, match="unable to open"):
            eng.connect()
    finally:
        eng.dispose()
    assert not missing.exists()


def test_web_server_lists_every_election(shared: Path, engine: Engine) -> None:
    with session_scope(engine) as s:
        s.execute(update(Election).values(status=ElectionStatus.ACTIVE))

    with TestClient(create_app(SHARED_URL, web_dist_dir=shared.parent / "no-dist")) as client:
        body = client.get("/api/v1/elections").json()

    assert sorted(e["id"] for e in body["elections"]) == [1, 2]
    assert {e["name"] for e in body["elections"]} == {
        "Elecciones generales 2023",
        "Elecciones generales 2027",
    }


# --- Scenario 2: missing shared file ------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("pipeline", "list", "--election", "1"),
        ("election", "list"),
        ("data", "import", f"data/elections/{SLUG_2023}"),
        ("pipeline", "run", "--election", "1", "--yes"),
    ],
)
def test_missing_shared_file_is_not_created(tmp_path: Path, args: tuple[str, ...]) -> None:
    (tmp_path / "data").mkdir()
    result = invoke(*args)

    assert result.exit_code == 1
    assert result.output == (
        "Error: no database at data/ideology.db; pull it, or build it with "
        '"ideology db upgrade" and "ideology data import <bundle dir>"\n'
    )
    assert not (tmp_path / "data" / "ideology.db").exists()


def test_missing_non_shared_file_keeps_the_old_message(db_url: str) -> None:
    result = invoke("election", "list", url=db_url)
    assert result.exit_code == 1
    assert "not initialised" in result.output


def test_db_upgrade_creates_the_shared_file(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    ok(invoke("db", "upgrade"))
    assert (tmp_path / "data" / "ideology.db").is_file()
    assert ok(invoke("election", "list")).output.startswith("id\t")


# --- Scenario 3: confirmation -------------------------------------------------


def test_run_without_yes_refuses_non_interactively(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    provider = use_provider(fake_provider())
    before = sha(shared)

    result = invoke("pipeline", "run", "--election", "1")

    assert result.exit_code == 1
    assert result.output == f"Error: {REFUSAL}\n"
    assert runs(engine) == []
    assert provider.calls == []
    assert sha(shared) == before


@pytest.mark.usefixtures("interactive")
def test_answering_no_aborts(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    provider = use_provider(fake_provider())

    result = invoke("pipeline", "run", "--election", "1", input="n\n")

    assert result.exit_code == 1
    assert result.output == (
        "Database data/ideology.db is shared through git.\n"
        "One active run at a time: generate only if you pulled the latest commit of this\n"
        "database and nobody else is generating on it (any Election).\n"
        "Continue? [y/N]: n\n"
        "Aborted!\n"
    )
    assert runs(engine) == []
    assert provider.calls == []


@pytest.mark.usefixtures("interactive")
@pytest.mark.parametrize("answer", ["", "x\nn"])
def test_default_answer_is_no(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any], answer: str
) -> None:
    use_provider(fake_provider())
    result = invoke("pipeline", "run", "--election", "1", input=f"{answer}\n")
    assert result.exit_code == 1
    assert runs(engine) == []


@pytest.mark.usefixtures("interactive")
def test_answering_yes_runs(engine: Engine, use_provider: Callable[[Any], Any]) -> None:
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", input="y\n"))

    assert result.output.startswith(PROMPT_START)
    assert "Pipeline run 1: passed" in result.output
    assert runs(engine) == [(1, 1, PipelineRunStatus.PASSED)]


def test_yes_skips_the_prompt(engine: Engine, use_provider: Callable[[Any], Any]) -> None:
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", "--yes"))

    assert PROMPT_START not in result.output
    assert runs(engine) == [(1, 1, PipelineRunStatus.PASSED)]


def queue_two(engine: Engine) -> None:
    with session_scope(engine) as s:
        for election_id in (1, 2):
            queue_run(
                s,
                election_id,
                llm_provider="fake",
                llm_model="fake-model",
                generation_mode=GenerationMode.LIVE,
            )


def test_run_queued_refuses_without_yes(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    queue_two(engine)
    provider = use_provider(fake_provider())

    result = invoke("pipeline", "run-queued")

    assert result.exit_code == 1
    assert result.output == f"Error: {REFUSAL}\n"
    assert [r[2] for r in runs(engine)] == [PipelineRunStatus.QUEUED] * 2
    assert provider.calls == []


@pytest.mark.usefixtures("interactive")
def test_run_queued_answer_no_and_yes(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    queue_two(engine)
    use_provider(fake_provider())

    refused = invoke("pipeline", "run-queued", input="n\n")
    assert refused.exit_code == 1
    assert refused.output.endswith("Aborted!\n")
    assert [r[2] for r in runs(engine)] == [PipelineRunStatus.QUEUED] * 2

    result = ok(invoke("pipeline", "run-queued", input="y\n"))
    assert result.output.startswith(PROMPT_START)
    assert [r[2] for r in runs(engine)] == [PipelineRunStatus.PASSED] * 2


def test_run_queued_with_yes(engine: Engine, use_provider: Callable[[Any], Any]) -> None:
    queue_two(engine)
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run-queued", "--yes"))

    assert PROMPT_START not in result.output
    assert [r[2] for r in runs(engine)] == [PipelineRunStatus.PASSED] * 2


def test_run_queued_with_nothing_queued_does_not_prompt(
    shared: Path, use_provider: Callable[[Any], Any]
) -> None:
    use_provider(fake_provider())
    result = ok(invoke("pipeline", "run-queued"))
    assert result.output == "No queued pipeline runs\n"


def test_a_non_shared_database_never_prompts(
    tmp_path: Path, db_url: str, use_provider: Callable[[Any], Any]
) -> None:
    write_bundles(tmp_path)
    ok(invoke("db", "upgrade", url=db_url))
    ok(invoke("data", "import", f"data/elections/{SLUG_2023}", url=db_url))
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", url=db_url))

    assert PROMPT_START not in result.output
    assert "Pipeline run 1: passed" in result.output


# --- Scenario 4: unfinished run -----------------------------------------------


def unfinished_message(run_id: int, status: str, calls: int) -> str:
    return (
        f"election 1 has an unfinished run {run_id} ({status}, {calls} recorded calls); "
        f"resume it with --resume-from {run_id}, or pass --fresh to start from zero"
    )


def test_unfinished_run_is_refused_on_the_shared_database(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider)
    provider = use_provider(fake_provider())
    before = sha(shared)

    result = invoke("pipeline", "run", "--election", "1", "--yes")

    assert result.exit_code == 1
    assert result.output == f"Error: {unfinished_message(1, 'failed', 3)}\n"
    assert runs(engine) == [(1, 1, PipelineRunStatus.FAILED)]
    assert provider.calls == []
    assert sha(shared) == before


def test_the_guard_comes_before_the_prompt(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider)
    use_provider(fake_provider())
    result = invoke("pipeline", "run", "--election", "1")
    assert result.exit_code == 1
    assert "--resume-from 1" in result.output
    assert len(runs(engine)) == 1


def test_fresh_starts_from_zero(engine: Engine, use_provider: Callable[[Any], Any]) -> None:
    stop_run(use_provider)
    provider = use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", "--fresh", "--yes"))

    assert "Pipeline run 2: passed" in result.output
    assert len(provider.calls) == 7
    with Session(engine) as s:
        assert s.get(PipelineRun, 2).resumed_from_run_id is None  # type: ignore[union-attr]


def test_fresh_with_resume_from_is_a_usage_error(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    use_provider(fake_provider())
    result = invoke(
        "pipeline", "run", "--election", "1", "--fresh", "--resume-from", "1", "--yes"
    )
    assert result.exit_code == 2
    assert "pass at most one of --fresh or --resume-from" in result.output
    assert runs(engine) == []


def test_resume_from_is_not_blocked(engine: Engine, use_provider: Callable[[Any], Any]) -> None:
    stop_run(use_provider)
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", "--resume-from", "1", "--yes"))

    assert "resuming from run 1 (3 recorded calls)" in result.output


def test_another_election_is_not_blocked(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider, election=1)
    use_provider(fake_provider())

    ok(invoke("pipeline", "run", "--election", "2", "--yes"))

    assert runs(engine) == [
        (1, 1, PipelineRunStatus.FAILED),
        (2, 2, PipelineRunStatus.PASSED),
    ]


def test_a_non_shared_database_warns_and_runs(
    tmp_path: Path, db_url: str, use_provider: Callable[[Any], Any]
) -> None:
    write_bundles(tmp_path)
    ok(invoke("db", "upgrade", url=db_url))
    ok(invoke("data", "import", f"data/elections/{SLUG_2023}", url=db_url))
    use_provider(Stopping(fake_provider(), 4))
    assert invoke("pipeline", "run", "--election", "1", url=db_url).exit_code == 1
    use_provider(fake_provider())

    result = ok(invoke("pipeline", "run", "--election", "1", url=db_url))

    assert f"Warning: {unfinished_message(1, 'failed', 3)}" in result.output
    assert "Pipeline run 2: passed" in result.output

    fresh = ok(invoke("pipeline", "run", "--election", "1", "--fresh", url=db_url))
    assert "Warning" not in fresh.output


def test_a_killed_run_gives_the_running_wording(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider)
    with session_scope(engine) as s:
        s.execute(update(PipelineRun).values(status=PipelineRunStatus.RUNNING))
    use_provider(fake_provider())

    result = invoke("pipeline", "run", "--election", "1", "--yes")

    assert result.exit_code == 1
    assert result.output == (
        f"Error: {unfinished_message(1, 'running', 3)}; "
        "if another developer is generating, stop; a killed run also stays running\n"
    )
    assert len(runs(engine)) == 1


def test_a_finished_run_or_another_model_gives_no_guard(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    use_provider(fake_provider())
    ok(invoke("pipeline", "run", "--election", "1", "--yes"))  # run 1: passed, has a version
    ok(invoke("pipeline", "run", "--election", "1", "--yes"))  # no guard: run 2
    stop_run(use_provider)  # run 3: failed
    with session_scope(engine) as s:
        s.execute(update(PipelineRun).where(PipelineRun.id == 3).values(llm_model="other"))

    ok(invoke("pipeline", "run", "--election", "1", "--yes"))

    assert [r[2] for r in runs(engine)] == [
        PipelineRunStatus.PASSED,
        PipelineRunStatus.PASSED,
        PipelineRunStatus.FAILED,
        PipelineRunStatus.PASSED,
    ]


def test_a_run_that_failed_validation_gives_no_guard(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    # Every Party agrees everywhere: statement_separation fails, the version stays.
    use_provider(fake_provider(position_findings=findings_response(value=1)))
    result = invoke("pipeline", "run", "--election", "1", "--yes")
    assert result.exit_code == 1
    assert "pipeline checks --run 1" in result.output
    with Session(engine) as s:
        run = s.get(PipelineRun, 1)
        assert run is not None and run.status is PipelineRunStatus.FAILED
        assert run.dataset_version is not None
        assert find_unfinished_run(s, 1, "fake", "fake-model") is None
    use_provider(fake_provider())
    ok(invoke("pipeline", "run", "--election", "1", "--yes"))


def test_find_unfinished_run_skips_runs_without_calls(
    engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider)
    use_provider(Stopping(fake_provider(), 1))  # run 2: fails on its first call
    assert invoke("pipeline", "run", "--election", "1", "--fresh", "--yes").exit_code == 1
    with Session(engine) as s:
        found = find_unfinished_run(s, 1, "fake", "fake-model")
        assert found is not None
        assert (found.run_id, found.status, found.recorded_calls) == (
            1,
            PipelineRunStatus.FAILED,
            3,
        )
        assert find_unfinished_run(s, 1) == found
        assert find_unfinished_run(s, 1, "fake", "other") is None
        assert find_unfinished_run(s, 1, "anthropic", "fake-model") is None
        assert find_unfinished_run(s, 2) is None


# --- Scenario 5: another machine ----------------------------------------------


def calls_of(path: Path, run_id: int) -> list[tuple[int, str, str, bool]]:
    eng = make_engine(f"sqlite:///{path}")
    try:
        with Session(eng) as s:
            return [
                (c.sequence, c.task, c.request_hash, c.reused)
                for c in s.scalars(
                    select(PipelineRunCall)
                    .where(PipelineRunCall.pipeline_run_id == run_id)
                    .order_by(PipelineRunCall.sequence)
                )
            ]
    finally:
        eng.dispose()


def statements_of(path: Path, run_id: int) -> list[str]:
    eng = make_engine(f"sqlite:///{path}")
    try:
        with Session(eng) as s:
            run = s.get(PipelineRun, run_id)
            assert run is not None and run.dataset_version is not None
            return list(
                s.scalars(
                    select(Statement.text)
                    .where(Statement.dataset_version_id == run.dataset_version.id)
                    .order_by(Statement.position)
                )
            )
    finally:
        eng.dispose()


def test_resume_on_another_machine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_provider: Callable[[Any], Any]
) -> None:
    machine_a, machine_b, reference = tmp_path / "a", tmp_path / "b", tmp_path / "ref"
    for root in (machine_a, reference):
        root.mkdir()
        monkeypatch.chdir(root)
        build_shared(root)
    monkeypatch.chdir(reference)
    use_provider(fake_provider())
    ok(invoke("pipeline", "run", "--election", "1", "--yes"))

    monkeypatch.chdir(machine_a)
    stop_run(use_provider, stop_at=4)
    shutil.copytree(machine_a / "data", machine_b / "data")

    monkeypatch.chdir(machine_b)
    provider = use_provider(fake_provider())
    result = ok(invoke("pipeline", "run", "--election", "1", "--resume-from", "1", "--yes"))

    assert "Pipeline run 2: resuming from run 1 (3 recorded calls)" in result.output
    assert "Pipeline run 2: passed" in result.output
    db_a, db_b = machine_a / "data" / "ideology.db", machine_b / "data" / "ideology.db"
    assert len(provider.calls) == 4
    assert [c[3] for c in calls_of(db_b, 2)] == [True] * 3 + [False] * 4
    assert calls_of(db_b, 1) == calls_of(db_a, 1)
    assert [c[2] for c in calls_of(db_b, 2)][:3] == [c[2] for c in calls_of(db_a, 1)]
    assert run_count(db_a) == 1 and run_count(db_b) == 2
    assert statements_of(db_b, 2) == statements_of(reference / "data" / "ideology.db", 1)


# --- Scenario 6: db check -----------------------------------------------------


def check(url: str = SHARED_URL) -> Result:
    return invoke("db", "check", url=url)


def test_check_a_fresh_shared_database(shared: Path) -> None:
    before = sha(shared)
    result = ok(check())
    assert result.output == "Safe to commit: yes\n"
    assert sha(shared) == before
    assert shared_db.sidecar_paths(shared) == []


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_check_refuses_a_sidecar(shared: Path, suffix: str) -> None:
    sidecar = shared.with_name(shared.name + suffix)
    sidecar.write_bytes(b"")
    before = sha(shared)

    result = check()

    assert result.exit_code == 1
    assert f"Error: ideology.db{suffix} exists: a writer is active" in result.output
    assert result.output.endswith("Safe to commit: no\n")
    assert sha(shared) == before
    assert sidecar.read_bytes() == b""


def test_check_refuses_wal_mode(shared: Path, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch.db"
    shutil.copyfile(shared, scratch)
    conn = sqlite3.connect(scratch)
    assert conn.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    conn.close()
    assert shared_db.sidecar_paths(scratch) == []
    before = sha(scratch)

    result = check(f"sqlite:///{scratch}")

    assert result.exit_code == 1
    assert "Error: journal mode is not delete (header bytes 18-19 are 2, 2)" in result.output
    assert "Safe to commit: no" in result.output
    assert sha(scratch) == before
    assert shared_db.sidecar_paths(scratch) == []


def test_check_refuses_a_database_behind_head(tmp_path: Path, db_url: str) -> None:
    script = ScriptDirectory.from_config(alembic_config(db_url))
    head = script.get_current_head()
    assert head is not None
    previous = script.get_revision(head).down_revision
    assert isinstance(previous, str)
    run_migrations(db_url, previous)
    before = sha(tmp_path / "test.db")

    result = check(db_url)

    assert result.exit_code == 1
    assert (
        f"Error: schema is at migration {previous}, not head {head}; "
        'run "ideology db upgrade"'
    ) in result.output
    assert sha(tmp_path / "test.db") == before


def test_check_refuses_an_edited_page(shared: Path, engine: Engine) -> None:
    with session_scope(engine) as s:
        s.execute(
            update(SourceDocumentPage)
            .where(SourceDocumentPage.source_document_id == 1)
            .where(SourceDocumentPage.page_number == 2)
            .values(text="Texto editado a mano.")
        )
    engine.dispose()
    before = sha(shared)

    result = check()

    assert result.exit_code == 1
    assert f"Error: election 1 ({SLUG_2023}): party PA (id 1)" in result.output
    assert SLUG_2027 not in result.output
    assert result.output.endswith("Safe to commit: no\n")
    assert sha(shared) == before


def test_check_reports_an_election_without_a_bundle(shared: Path) -> None:
    ok(
        invoke(
            "election", "create", "--country", "PT", "--type", "general",
            "--date", "2026-01-18", "--name", "Eleições",
        )
    )
    result = ok(check())
    assert result.output == (
        "election 3: no committed bundle; text not checked\nSafe to commit: yes\n"
    )


def test_check_honours_elections_data_dir(
    shared: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELECTIONS_DATA_DIR", str(tmp_path / "elsewhere"))
    result = ok(check())
    assert "election 1: no committed bundle; text not checked" in result.output
    assert "election 2: no committed bundle; text not checked" in result.output


def test_check_lists_unfinished_runs(
    shared: Path, engine: Engine, use_provider: Callable[[Any], Any]
) -> None:
    stop_run(use_provider, election=2)
    result = ok(check())
    assert result.output == (
        "election 2, run 1: failed, 3 recorded calls; resume with --resume-from 1\n"
        "Safe to commit: yes\n"
    )

    with session_scope(engine) as s:
        s.execute(update(PipelineRun).values(status=PipelineRunStatus.RUNNING))
    engine.dispose()
    result = ok(check())
    assert result.output == (
        "election 2, run 1: running, 3 recorded calls; resume with --resume-from 1; "
        "commit only if no ideology process is still running it\n"
        "Safe to commit: yes\n"
    )


def test_check_refuses_a_non_sqlite_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # No PostgreSQL driver is installed; the command must not need one.
    monkeypatch.setattr(cli, "make_engine", lambda url: create_engine("sqlite://"))
    result = check("postgresql://u@localhost/ideology")
    assert result.exit_code == 1
    assert result.output == "Error: db check supports SQLite databases only\n"


def test_check_a_missing_file(tmp_path: Path) -> None:
    result = check(f"sqlite:///{tmp_path}/nope.db")
    assert result.exit_code == 1
    assert "no database at" in result.output
    assert not (tmp_path / "nope.db").exists()


def test_check_refuses_a_file_that_is_not_sqlite(tmp_path: Path) -> None:
    (tmp_path / "junk.db").write_bytes(b"not a database" * 20)
    result = check(f"sqlite:///{tmp_path}/junk.db")
    assert result.exit_code == 1
    assert "is not a SQLite database" in result.output
