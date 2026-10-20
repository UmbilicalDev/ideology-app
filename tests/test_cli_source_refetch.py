"""live-mode-url-refetch Scenarios 1-7 and 9 through ``ideology source refetch``.

HTTP is mocked at ``http_fetch._open`` and the clock at ``cli._now``; no test
opens a socket, needs an API key or calls an LLM.
"""

import datetime as dt
import hashlib
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from http_fakes import FakeResponse, http_error
from pdf_factory import blank_pdf, make_text_pdf
from pipeline_fixtures import offline_guard
from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app import cli, http_fetch
from ideology_app.cli import main
from ideology_app.db import make_engine
from ideology_app.elections import InvalidInputError
from ideology_app.llm import FakeProvider
from ideology_app.models import PipelineRun, PipelineRunStatus, SourceDocument
from ideology_app.pdf_text import NO_TEXT_LAYER
from ideology_app.pipeline import runs as runs_module

URL_A = "https://example.org/alfa/programa.pdf"
URL_B = "https://example.org/beta/programa.pdf"
V1_A = make_text_pdf(["Alfa: vivienda.", "Alfa: sanidad."])
V2_A = make_text_pdf(["Alfa actualizado: vivienda.", "Alfa: sanidad.", "Alfa: empleo."])
V1_B = make_text_pdf(["Beta: impuestos."])
V2_B = make_text_pdf(["Beta actualizado: impuestos.", "Beta: educación."])
T0 = dt.datetime(2026, 10, 20, 6, 0, tzinfo=dt.UTC)
SIX_HOURS = dt.timedelta(hours=6)
NOTHING_DUE = "No source documents due for re-fetch\n"


class FakeOpen:
    """Stands in for ``http_fetch._open``: one outcome per URL, calls recorded."""

    def __init__(self) -> None:
        self.outcomes: dict[str, Any] = {}
        self.calls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> object:
        self.calls.append(request.full_url)
        outcome = self.outcomes[request.full_url]
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    offline_guard(monkeypatch)
    monkeypatch.delenv("SOURCE_REFETCH_INTERVAL_HOURS", raising=False)
    monkeypatch.setenv("SOURCE_FILES_DIR", str(tmp_path / "stored"))


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> FakeOpen:
    fake = FakeOpen()
    monkeypatch.setattr(http_fetch, "_open", fake)
    return fake


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    def _set(now: dt.datetime) -> None:
        monkeypatch.setattr(cli, "_now", lambda: now)

    return _set


@pytest.fixture
def run(db_url: str):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "fake")


def _ok(result: Result) -> Result:
    assert result.exit_code == 0, (result.output, result.stderr)
    return result


def _set_created(db_url: str, at: dt.datetime) -> None:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            for d in s.scalars(select(SourceDocument)):
                d.created_at = at
            s.commit()
    finally:
        engine.dispose()


@pytest.fixture
def seeded(run, web: FakeOpen, db_url: str) -> None:
    """Election 1 with Parties 1 and 2; URL documents 1 (Party 1) and 2 (Party 2) at T0.

    Registered in precomputed mode, so no run exists yet.
    """
    _ok(run("db", "upgrade"))
    _ok(run("election", "create", "--country", "ES", "--type", "general",
            "--date", "2027-07-23", "--name", "Generales 2027"))
    _ok(run("party", "add", "--election", "1", "--name", "Partido Alfa", "--short-name", "PA"))
    _ok(run("party", "add", "--election", "1", "--name", "Bloque Beta", "--short-name", "BB"))
    web.outcomes[URL_A] = V1_A
    web.outcomes[URL_B] = V1_B
    _ok(run("source", "add", "--party", "1", "--url", URL_A))
    _ok(run("source", "add", "--party", "2", "--url", URL_B))
    _set_created(db_url, T0)
    web.calls.clear()


def _documents(db_url: str) -> list[tuple[Any, ...]]:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            return [
                (d.id, d.party_id, d.status.value, d.content_hash, d.replaced_by_id,
                 d.source_url, d.page_count)
                for d in s.scalars(select(SourceDocument).order_by(SourceDocument.id))
            ]
    finally:
        engine.dispose()


def _last_checked(db_url: str, document_id: int) -> dt.datetime | None:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            value = s.get(SourceDocument, document_id).last_checked_at
    finally:
        engine.dispose()
    return value.replace(tzinfo=dt.UTC) if value and value.tzinfo is None else value


def _runs(db_url: str) -> list[tuple[int, PipelineRunStatus, str]]:
    engine = make_engine(db_url)
    try:
        with Session(engine) as s:
            return [
                (r.id, r.status, r.generation_mode.value)
                for r in s.scalars(select(PipelineRun).order_by(PipelineRun.id))
            ]
    finally:
        engine.dispose()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stored(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "stored").iterdir())


# Scenario 1: changed content -> replacement + run queued (live)


def test_changed_content_replaces_and_queues_a_run(
    run, seeded, live, web: FakeOpen, clock, db_url: str, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    monkeypatch.setattr(cli, "_provider", lambda: provider)
    web.outcomes[URL_A] = V2_A
    now = T0 + SIX_HOURS
    clock(now)

    result = _ok(run("source", "refetch"))

    assert result.output == (
        "Source document 1: replaced by source document 3 (3 pages)\n"
        "Queued pipeline run 1 for election 1 (generation mode live)\n"
        "Source document 2: unchanged\n"
    )
    assert web.calls == [URL_A, URL_B]
    assert _documents(db_url) == [
        (1, 1, "parsed", _sha(V1_A), 3, URL_A, 2),
        (2, 2, "parsed", _sha(V1_B), None, URL_B, 1),
        (3, 1, "parsed", _sha(V2_A), None, URL_A, 3),
    ]
    assert _last_checked(db_url, 1) == now and _last_checked(db_url, 3) == now
    assert _stored(tmp_path) == sorted(f"{_sha(d)}.pdf" for d in (V1_A, V1_B, V2_A))
    assert _runs(db_url) == [(1, PipelineRunStatus.QUEUED, "live")]
    assert provider.calls == []  # queuing never calls an LLM
    assert _ok(run("source", "text", "--document", "1")).output.startswith(
        "--- page 1 ---\nAlfa: vivienda.\n"
    )
    listed = _ok(run("source", "list", "--party", "1")).output.splitlines()
    assert listed[0].split("\t")[-1] == "replaced_by"
    assert [line.split("\t")[-1] for line in listed[1:]] == ["3", ""]


# Scenario 2: same content -> nothing but the check time


def test_same_content_changes_nothing(
    run, seeded, live, web: FakeOpen, clock, db_url: str, tmp_path: Path
) -> None:
    before = _documents(db_url)
    stored = _stored(tmp_path)
    now = T0 + SIX_HOURS
    clock(now)

    result = _ok(run("source", "refetch"))

    assert result.output == "Source document 1: unchanged\nSource document 2: unchanged\n"
    assert _documents(db_url) == before
    assert _stored(tmp_path) == stored
    assert _runs(db_url) == []
    assert _last_checked(db_url, 1) == now


# Scenario 3: not due -> not fetched


def test_not_due_is_not_fetched(run, seeded, web: FakeOpen, clock) -> None:
    clock(T0 + dt.timedelta(hours=5, minutes=59))

    assert _ok(run("source", "refetch")).output == NOTHING_DUE
    assert web.calls == []

    clock(T0 + SIX_HOURS)
    assert _ok(run("source", "refetch")).output.count("unchanged") == 2
    assert web.calls == [URL_A, URL_B]

    # Checked at T0 + 6h: the next check is due at T0 + 12h.
    web.calls.clear()
    clock(T0 + dt.timedelta(hours=11, minutes=59))
    assert _ok(run("source", "refetch")).output == NOTHING_DUE
    clock(T0 + dt.timedelta(hours=12))
    assert _ok(run("source", "refetch")).output.count("unchanged") == 2
    assert web.calls == [URL_A, URL_B]


def test_interval_comes_from_the_environment(
    run, seeded, web: FakeOpen, clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock(T0 + dt.timedelta(hours=1))
    assert _ok(run("source", "refetch")).output == NOTHING_DUE

    monkeypatch.setenv("SOURCE_REFETCH_INTERVAL_HOURS", "1")
    assert _ok(run("source", "refetch")).output.count("unchanged") == 2


# Scenario 4: invalid interval


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "6h"])
def test_invalid_interval_exits_before_any_fetch(
    run, seeded, web: FakeOpen, clock, db_url: str, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("SOURCE_REFETCH_INTERVAL_HOURS", raw)
    clock(T0 + dt.timedelta(days=1))

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stderr == (
        f"Error: Invalid SOURCE_REFETCH_INTERVAL_HOURS {raw!r}; expected a positive integer\n"
    )
    assert web.calls == []
    assert _last_checked(db_url, 1) is None


# Scenario 5: failures keep the old document, the rest is still processed


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (lambda: http_error(404, "Not Found", URL_A), "HTTP 404: Not Found"),
        (b"<html>moved</html>", "response is not a PDF (it does not start with %PDF-)"),
        (blank_pdf(2), NO_TEXT_LAYER),
    ],
    ids=["http-404", "not-pdf", "no-text-layer"],
)
def test_failure_keeps_the_document_and_continues(
    run, seeded, live, web: FakeOpen, clock, db_url: str, tmp_path: Path,
    outcome: object, reason: str,
) -> None:
    web.outcomes[URL_A] = outcome
    web.outcomes[URL_B] = V2_B
    stored = _stored(tmp_path)
    now = T0 + SIX_HOURS
    clock(now)

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stdout == (
        "Source document 2: replaced by source document 3 (2 pages)\n"
        "Queued pipeline run 1 for election 1 (generation mode live)\n"
    )
    assert result.stderr == (
        f"Error: source document 1: {reason}\n"
        "Error: 1 of 2 source documents could not be re-fetched\n"
    )
    assert _documents(db_url) == [
        (1, 1, "parsed", _sha(V1_A), None, URL_A, 2),
        (2, 2, "parsed", _sha(V1_B), 3, URL_B, 1),
        (3, 2, "parsed", _sha(V2_B), None, URL_B, 2),
    ]
    assert _last_checked(db_url, 1) == now
    assert _stored(tmp_path) == sorted([*stored, f"{_sha(V2_B)}.pdf"])
    assert _runs(db_url) == [(1, PipelineRunStatus.QUEUED, "live")]


def test_failure_only_queues_nothing(
    run, seeded, live, web: FakeOpen, clock, db_url: str
) -> None:
    web.outcomes[URL_A] = lambda: http_error(500, "Server Error", URL_A)
    web.outcomes[URL_B] = lambda: http_error(404, "Not Found", URL_B)
    clock(T0 + SIX_HOURS)

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.endswith("Error: 2 of 2 source documents could not be re-fetched\n")
    assert _runs(db_url) == []
    assert [d[4] for d in _documents(db_url)] == [None, None]


# Scenario 6: duplicate hash


def test_reverted_content_is_reported_as_a_duplicate(
    run, seeded, live, web: FakeOpen, clock, db_url: str
) -> None:
    web.outcomes[URL_A] = V2_A
    clock(T0 + SIX_HOURS)
    _ok(run("source", "refetch"))
    web.outcomes[URL_A] = V1_A
    clock(T0 + 2 * SIX_HOURS)

    result = _ok(run("source", "refetch"))

    assert result.output == (
        "Source document 2: unchanged\n"
        "Source document 3: content matches source document 1 of the same party; "
        "nothing changed\n"
    )
    assert [d[:5] for d in _documents(db_url)] == [
        (1, 1, "parsed", _sha(V1_A), 3),
        (2, 2, "parsed", _sha(V1_B), None),
        (3, 1, "parsed", _sha(V2_A), None),
    ]
    assert _runs(db_url) == [(1, PipelineRunStatus.QUEUED, "live")]


# Scenario 7: coalescing, precomputed and config errors


def test_two_changes_coalesce_into_one_queued_run(
    run, seeded, live, web: FakeOpen, clock, db_url: str
) -> None:
    web.outcomes[URL_A] = V2_A
    web.outcomes[URL_B] = V2_B
    clock(T0 + SIX_HOURS)

    result = _ok(run("source", "refetch"))

    assert result.output == (
        "Source document 1: replaced by source document 3 (3 pages)\n"
        "Queued pipeline run 1 for election 1 (generation mode live)\n"
        "Source document 2: replaced by source document 4 (2 pages)\n"
        "Pipeline run 1 is already queued for election 1\n"
    )
    assert _runs(db_url) == [(1, PipelineRunStatus.QUEUED, "live")]


def test_precomputed_replaces_without_queuing(
    run, seeded, web: FakeOpen, clock, db_url: str
) -> None:
    web.outcomes[URL_A] = V2_A
    clock(T0 + SIX_HOURS)

    result = _ok(run("source", "refetch"))

    assert result.output == (
        "Source document 1: replaced by source document 3 (3 pages)\n"
        "Source document 2: unchanged\n"
    )
    assert _documents(db_url)[0][4] == 3
    assert _runs(db_url) == []


def test_live_with_a_bad_provider_exits_before_any_fetch(
    run, seeded, web: FakeOpen, clock, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "live")
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    clock(T0 + SIX_HOURS)

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: Invalid LLM_PROVIDER 'bogus'")
    assert web.calls == []
    assert _last_checked(db_url, 1) is None


def test_bad_generation_mode_exits_before_any_fetch(
    run, seeded, web: FakeOpen, clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENERATION_MODE", "sometimes")
    clock(T0 + SIX_HOURS)

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stderr.startswith("Error: Invalid GENERATION_MODE 'sometimes'")
    assert web.calls == []


# Scenario 9: scope and atomicity


def test_election_filter_and_unknown_election(
    run, seeded, web: FakeOpen, clock, db_url: str
) -> None:
    url_c = "https://example.org/gamma/programa.pdf"
    _ok(run("election", "create", "--country", "ES", "--type", "general",
            "--date", "2031-07-23", "--name", "Generales 2031"))
    _ok(run("party", "add", "--election", "2", "--name", "Partido Gamma", "--short-name", "PG"))
    web.outcomes[url_c] = make_text_pdf(["Gamma."])
    _ok(run("source", "add", "--party", "3", "--url", url_c))
    _set_created(db_url, T0)
    web.calls.clear()
    clock(T0 + SIX_HOURS)

    assert _ok(run("source", "refetch", "--election", "2")).output == (
        "Source document 3: unchanged\n"
    )
    assert web.calls == [url_c]

    unknown = run("source", "refetch", "--election", "9")
    assert unknown.exit_code == 1
    assert unknown.stderr == "Error: election 9 not found\n"
    assert web.calls == [url_c]


def test_upload_and_failed_documents_are_never_fetched(
    run, seeded, web: FakeOpen, clock, db_url: str, tmp_path: Path
) -> None:
    upload = tmp_path / "subido.pdf"
    upload.write_bytes(make_text_pdf(["Documento subido."]))
    _ok(run("source", "add", "--party", "1", "--file", str(upload)))
    missing = "https://example.org/alfa/missing.pdf"
    web.outcomes[missing] = lambda: http_error(404, "Not Found", missing)
    assert run("source", "add", "--party", "1", "--url", missing).exit_code == 1
    _set_created(db_url, T0)
    web.calls.clear()
    clock(T0 + dt.timedelta(days=2))

    result = _ok(run("source", "refetch"))

    assert web.calls == [URL_A, URL_B]
    assert result.output == "Source document 1: unchanged\nSource document 2: unchanged\n"


def test_trigger_failure_rolls_back_the_replacement(
    run, seeded, live, web: FakeOpen, clock, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise InvalidInputError("queue refused")

    monkeypatch.setattr("ideology_app.pipeline.triggers.queue_run", refuse)
    web.outcomes[URL_A] = V2_A
    before = _documents(db_url)
    clock(T0 + SIX_HOURS)

    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stdout == "Source document 2: unchanged\n"
    assert result.stderr == (
        "Error: source document 1: queue refused\n"
        "Error: 1 of 2 source documents could not be re-fetched\n"
    )
    assert _documents(db_url) == before
    assert _last_checked(db_url, 1) is None
    assert _runs(db_url) == []
    assert runs_module.queue_run is not refuse  # only the trigger's import was patched


def test_nothing_due_on_a_fresh_database(run, web: FakeOpen, clock) -> None:
    _ok(run("db", "upgrade"))
    clock(T0)

    assert _ok(run("source", "refetch")).output == NOTHING_DUE
    assert web.calls == []


def test_refetch_needs_a_migrated_database(run) -> None:
    result = run("source", "refetch")

    assert result.exit_code == 1
    assert result.stderr == f"Error: {cli.NOT_INITIALISED}\n"

