"""Source Documents registered by URL: service and CLI, with HTTP mocked."""

import datetime as dt
import hashlib
import http.client
import socket
import urllib.request
from pathlib import Path
from urllib.error import URLError

import pytest
from click.testing import CliRunner, Result
from http_fakes import FakeResponse, http_error
from pdf_factory import blank_pdf, encrypt_pdf, make_text_pdf
from pipeline_fixtures import LLM_ENV_VARS
from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app import http_fetch
from ideology_app.cli import NOT_INITIALISED, main
from ideology_app.db import run_migrations
from ideology_app.elections import (
    DuplicateError,
    InvalidInputError,
    NotFoundError,
    add_party,
    create_election,
)
from ideology_app.http_fetch import FetchError
from ideology_app.models import (
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentPage,
    SourceDocumentStatus,
)
from ideology_app.pdf_text import NO_TEXT_LAYER
from ideology_app.source_documents import add_uploaded_document, add_url_document

URL = "https://example.org/docs/programa%202023.pdf"
TEXT_PAGES = ["Programa electoral\nSubir el salario mínimo.", "Página dos: educación."]
TEXT_PDF = make_text_pdf(TEXT_PAGES)
HEADER = [
    "id", "origin", "status", "pages", "content_hash", "filename", "url", "failure_reason",
    "replaced_by", "bundle_file",
]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No socket can connect, and GENERATION_MODE / LLM_* from the shell are unset."""
    for name in LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is blocked in source URL tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class FakeOpen:
    """Stands in for ``http_fetch._open``: one outcome (bytes, error or factory) per URL."""

    def __init__(self) -> None:
        self.outcomes: dict[str, object] = {}
        self.calls: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> object:
        self.calls.append(request.full_url)
        outcome = self.outcomes[request.full_url]
        if callable(outcome):
            outcome = outcome()  # a fresh HTTPError per call, closed by fetch_url
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, bytes)
        return FakeResponse(outcome)


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> FakeOpen:
    fake = FakeOpen()
    monkeypatch.setattr(http_fetch, "_open", fake)
    return fake


@pytest.fixture
def files_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "stored"
    monkeypatch.setenv("SOURCE_FILES_DIR", str(path))
    return path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- Service -----------------------------------------------------------------


@pytest.fixture
def parties(session: Session) -> tuple[int, int]:
    election = create_election(
        session, country="ES", type="general", date=dt.date(2023, 7, 23), name="Generales 2023"
    )
    first = add_party(session, election_id=election.id, name="Sumar", short_name="SUMAR")
    second = add_party(session, election_id=election.id, name="Partido Popular", short_name="PP")
    session.commit()
    return first.id, second.id


def _add(session: Session, files_dir: Path, url: str = URL, party_id: int = 1) -> SourceDocument:
    document = add_url_document(session, party_id=party_id, url=url, files_dir=files_dir)
    session.commit()
    return document


def test_service_text_pdf_is_parsed(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[URL] = TEXT_PDF

    document = _add(session, files_dir)

    assert web.calls == [URL]
    assert document.origin is SourceDocumentOrigin.URL
    assert document.status is SourceDocumentStatus.PARSED
    assert document.source_url == URL
    assert document.original_filename == "programa 2023.pdf"
    assert document.page_count == 2
    assert document.content_hash == _sha(TEXT_PDF)
    assert document.failure_reason is None
    assert [p.text for p in document.pages] == TEXT_PAGES
    assert (files_dir / f"{_sha(TEXT_PDF)}.pdf").read_bytes() == TEXT_PDF


def test_service_url_is_stripped_and_stored_as_given(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[URL] = TEXT_PDF

    document = _add(session, files_dir, url=f"  {URL}\n")

    assert document.source_url == URL


@pytest.mark.parametrize(
    "url, filename",
    [
        ("https://example.org/", None),
        ("https://example.org", None),
        ("https://example.org/get?id=7", "get"),
        ("https://example.org/a/" + "n" * 300 + ".pdf", "n" * 255),
    ],
    ids=["root-slash", "no-path", "query", "long-name"],
)
def test_service_filename_from_url(
    session: Session,
    parties: tuple[int, int],
    web: FakeOpen,
    files_dir: Path,
    url: str,
    filename: str | None,
) -> None:
    web.outcomes[url] = TEXT_PDF

    assert _add(session, files_dir, url=url).original_filename == filename


@pytest.mark.parametrize(
    "outcome, reason",
    [
        (lambda: http_error(404, "Not Found"), "HTTP 404: Not Found"),
        (lambda: http_error(500, "Internal Server Error"), "HTTP 500: Internal Server Error"),
        (URLError("Name or service not known"), "could not fetch URL: Name or service not known"),
        (TimeoutError("timed out"), "could not fetch URL: TimeoutError: timed out"),
        (
            ConnectionResetError("reset"),
            "could not fetch URL: ConnectionResetError: reset",
        ),
        (
            http.client.IncompleteRead(b"", 9),
            "could not fetch URL: IncompleteRead: IncompleteRead(0 bytes read, 9 more expected)",
        ),
        (
            UnicodeEncodeError("ascii", "ñ", 0, 1, "ordinal not in range(128)"),
            "could not fetch URL: UnicodeEncodeError: 'ascii' codec can't encode character"
            " '\\xf1' in position 0: ordinal not in range(128)",
        ),
        (
            http.client.InvalidURL("nonnumeric port"),
            "could not fetch URL: InvalidURL: nonnumeric port",
        ),
        (ValueError("bad value"), "could not fetch URL: ValueError: bad value"),
        (b"", "response is empty"),
        (b"<!doctype html><title>Programa</title>", "response is not a PDF (it does not start with %PDF-)"),
    ],
    ids=[
        "404", "500", "dns", "timeout", "reset", "incomplete", "unicode", "invalid-url", "value",
        "empty", "html",
    ],
)
def test_service_download_failure_commits_failed_row(
    session: Session,
    parties: tuple[int, int],
    web: FakeOpen,
    files_dir: Path,
    outcome: object,
    reason: str,
) -> None:
    web.outcomes[URL] = outcome

    document = _add(session, files_dir)

    assert document.origin is SourceDocumentOrigin.URL
    assert document.status is SourceDocumentStatus.FAILED
    assert document.source_url == URL
    assert document.failure_reason == reason
    assert document.content_hash is None
    assert document.page_count is None
    assert document.original_filename is None
    assert document.pages == []
    assert not files_dir.exists()


NON_ASCII_URL = "https://example.org/programa-año.pdf"
NON_ASCII_WIRE_URL = "https://example.org/programa-a%C3%B1o.pdf"


def test_service_non_ascii_url_is_sent_encoded_and_stored_as_given(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[NON_ASCII_WIRE_URL] = TEXT_PDF

    document = _add(session, files_dir, url=NON_ASCII_URL)

    assert web.calls == [NON_ASCII_WIRE_URL]
    assert document.status is SourceDocumentStatus.PARSED
    assert document.source_url == NON_ASCII_URL
    assert document.original_filename == "programa-año.pdf"
    assert document.page_count == 2


def test_service_too_large_download(
    session: Session,
    parties: tuple[int, int],
    web: FakeOpen,
    files_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ideology_app.source_documents.MAX_UPLOAD_BYTES", 10)
    web.outcomes[URL] = TEXT_PDF

    document = _add(session, files_dir)

    assert document.status is SourceDocumentStatus.FAILED
    assert document.failure_reason == "response is too large (more than 10 bytes)"
    assert not files_dir.exists()


def test_service_default_cap_is_50_mib(
    session: Session,
    parties: tuple[int, int],
    files_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(request: urllib.request.Request, timeout: float) -> FakeResponse:
        return FakeResponse(b"%PDF-", headers={"Content-Length": str(50 * 1024 * 1024 + 1)})

    monkeypatch.setattr(http_fetch, "_open", fake_open)

    document = _add(session, files_dir)

    assert document.failure_reason == "response is too large (more than 52428800 bytes)"


@pytest.mark.parametrize(
    "data, reason_start",
    [
        (blank_pdf(2), NO_TEXT_LAYER),
        (TEXT_PDF[:400], "could not read PDF:"),
        (encrypt_pdf(TEXT_PDF, "secret"), "PDF is encrypted"),
    ],
    ids=["blank", "corrupt", "encrypted"],
)
def test_service_unparsable_pdf_is_stored_and_failed(
    session: Session,
    parties: tuple[int, int],
    web: FakeOpen,
    files_dir: Path,
    data: bytes,
    reason_start: str,
) -> None:
    web.outcomes[URL] = data

    document = _add(session, files_dir)

    assert document.status is SourceDocumentStatus.FAILED
    assert document.failure_reason is not None
    assert document.failure_reason.startswith(reason_start)
    assert document.content_hash == _sha(data)
    assert document.source_url == URL
    assert (files_dir / f"{_sha(data)}.pdf").read_bytes() == data
    if reason_start == NO_TEXT_LAYER:
        assert document.page_count == 2


@pytest.mark.parametrize(
    "url, why",
    [
        ("ftp://example.org/x.pdf", "only absolute http or https"),
        ("file:///etc/passwd", "only absolute http or https"),
        ("data:application/pdf,%25PDF-", "only absolute http or https"),
        ("example.org/x.pdf", "only absolute http or https"),
        ("//example.org/x.pdf", "only absolute http or https"),
        ("https://", "no host"),
        ("https:///x.pdf", "no host"),
        ("https://example.org/a b.pdf", "whitespace or control"),
        ("https://example.org/a\tb.pdf", "whitespace or control"),
        ("https://example.org/a\x00.pdf", "whitespace or control"),
        ("https://example.org/a\x7f.pdf", "whitespace or control"),
        ("https://example.org/a\x85.pdf", "whitespace or control"),
        ("https://example.org/a\x9f.pdf", "whitespace or control"),
        ("https://example.org/\udcff.pdf", "not valid UTF-8"),
        ("https://user:pw@example.org/x.pdf", "credentials"),
        ("https://user@example.org/x.pdf", "credentials"),
        ("https://example.org:99999/x.pdf", "out of range"),
        ("https://example.org/" + "a" * 2030 + ".pdf", "longer than 2048"),
        ("", "only absolute http or https"),
    ],
)
def test_service_invalid_url_is_rejected_before_fetch(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path, url: str, why: str
) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        add_url_document(session, party_id=1, url=url, files_dir=files_dir)

    assert str(excinfo.value).startswith("invalid URL")
    assert why in str(excinfo.value)
    assert web.calls == []
    session.rollback()
    assert session.scalars(select(SourceDocument)).all() == []
    assert not files_dir.exists()


def test_service_accepts_uppercase_scheme_and_max_length(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    url = "HTTP://example.org/" + "a" * (2048 - len("HTTP://example.org/") - 4) + ".pdf"
    assert len(url) == 2048
    web.outcomes[url] = TEXT_PDF

    document = _add(session, files_dir, url=url)

    assert document.status is SourceDocumentStatus.PARSED
    assert document.source_url == url


def test_service_unknown_party_is_rejected_before_fetch(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    with pytest.raises(NotFoundError, match="^party 999 not found$"):
        add_url_document(session, party_id=999, url=URL, files_dir=files_dir)
    assert web.calls == []


def test_service_fetch_is_injectable(
    session: Session, parties: tuple[int, int], files_dir: Path
) -> None:
    def fetch(url: str) -> bytes:
        raise FetchError("boom")

    document = add_url_document(session, party_id=1, url=URL, files_dir=files_dir, fetch=fetch)

    assert document.failure_reason == "boom"


def test_service_duplicate_content_for_same_party(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path, tmp_path: Path
) -> None:
    upload = tmp_path / "manifesto.pdf"
    upload.write_bytes(TEXT_PDF)
    add_uploaded_document(session, party_id=1, file_path=upload, files_dir=files_dir)
    session.commit()
    web.outcomes[URL] = TEXT_PDF

    with pytest.raises(DuplicateError) as excinfo:
        add_url_document(session, party_id=1, url=URL, files_dir=files_dir)

    assert str(excinfo.value) == (
        f"party 1 already has a source document with content hash {_sha(TEXT_PDF)}"
    )
    # The session is still usable, and nothing was added.
    assert len(session.scalars(select(SourceDocument)).all()) == 1
    other = _add(session, files_dir, party_id=2)
    assert other.status is SourceDocumentStatus.PARSED
    assert other.content_hash == _sha(TEXT_PDF)
    assert [p.name for p in files_dir.iterdir()] == [f"{_sha(TEXT_PDF)}.pdf"]
    assert session.scalars(select(SourceDocumentPage)).all() != []


def test_service_failed_downloads_do_not_collide(
    session: Session, parties: tuple[int, int], web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[URL] = lambda: http_error(404, "Not Found")

    first = _add(session, files_dir)
    second = _add(session, files_dir)

    assert (first.id, second.id) == (1, 2)
    assert first.content_hash is None and second.content_hash is None


# --- CLI ---------------------------------------------------------------------


@pytest.fixture
def run(db_url: str, files_dir: Path):
    runner = CliRunner()

    def _run(*args: str) -> Result:
        return runner.invoke(main, ["--database-url", db_url, *args])

    return _run


@pytest.fixture
def cli_parties(run) -> None:
    for args in (
        ("db", "upgrade"),
        ("election", "create", "--country", "ES", "--type", "general",
         "--date", "2023-07-23", "--name", "Generales 2023"),
        ("party", "add", "--election", "1", "--name", "Sumar", "--short-name", "SUMAR"),
        ("party", "add", "--election", "1", "--name", "Partido Popular", "--short-name", "PP"),
    ):
        result = run(*args)
        assert result.exit_code == 0, result.output


def _list_rows(run, party_id: str = "1") -> list[list[str]]:
    result = run("source", "list", "--party", party_id)
    assert result.exit_code == 0, result.output
    return [line.split("\t") for line in result.output.splitlines()]


def test_cli_url_text_pdf_is_parsed(run, cli_parties, web: FakeOpen, files_dir: Path) -> None:
    web.outcomes[URL] = TEXT_PDF

    result = run("source", "add", "--party", "1", "--url", URL)

    assert result.exit_code == 0, result.output
    assert result.output == "Created source document 1: parsed (2 pages)\n"
    assert (files_dir / f"{_sha(TEXT_PDF)}.pdf").read_bytes() == TEXT_PDF
    text = run("source", "text", "--document", "1")
    assert text.output == (
        "--- page 1 ---\nPrograma electoral\nSubir el salario mínimo.\n"
        "--- page 2 ---\nPágina dos: educación.\n"
    )


def test_cli_http_error_commits_failed_row(
    run, cli_parties, web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[URL] = lambda: http_error(404, "Not Found")

    result = run("source", "add", "--party", "1", "--url", URL)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Error: source document 1 failed: HTTP 404: Not Found\n"
    assert _list_rows(run) == [
        HEADER,
        ["1", "url", "failed", "", "", "", URL, "HTTP 404: Not Found", "", ""],
    ]
    assert not files_dir.exists()


@pytest.mark.parametrize(
    "outcome, reason",
    [
        (URLError("Name or service not known"), "could not fetch URL: Name or service not known"),
        (b"<html>hi</html>", "response is not a PDF (it does not start with %PDF-)"),
        (b"", "response is empty"),
    ],
    ids=["dns", "html", "empty"],
)
def test_cli_other_download_failures(
    run, cli_parties, web: FakeOpen, files_dir: Path, outcome: object, reason: str
) -> None:
    web.outcomes[URL] = outcome

    result = run("source", "add", "--party", "1", "--url", URL)

    assert result.exit_code == 1
    assert result.stderr == f"Error: source document 1 failed: {reason}\n"
    assert not files_dir.exists()


def test_cli_non_ascii_url_is_parsed(run, cli_parties, web: FakeOpen, files_dir: Path) -> None:
    web.outcomes[NON_ASCII_WIRE_URL] = TEXT_PDF

    result = run("source", "add", "--party", "1", "--url", NON_ASCII_URL)

    assert result.exit_code == 0, result.output
    assert result.stdout == "Created source document 1: parsed (2 pages)\n"
    assert web.calls == [NON_ASCII_WIRE_URL]


def test_cli_encoding_error_commits_failed_row(
    run, cli_parties, web: FakeOpen, files_dir: Path
) -> None:
    web.outcomes[URL] = UnicodeEncodeError("ascii", "ñ", 0, 1, "ordinal not in range(128)")

    result = run("source", "add", "--party", "1", "--url", URL)

    reason = (
        "could not fetch URL: UnicodeEncodeError: 'ascii' codec can't encode character"
        " '\\xf1' in position 0: ordinal not in range(128)"
    )
    assert result.exit_code == 1
    assert result.stderr == f"Error: source document 1 failed: {reason}\n"
    assert _list_rows(run) == [HEADER, ["1", "url", "failed", "", "", "", URL, reason, "", ""]]
    assert not files_dir.exists()


def test_cli_blank_pdf_from_url_fails(run, cli_parties, web: FakeOpen, files_dir: Path) -> None:
    data = blank_pdf(2)
    web.outcomes[URL] = data

    result = run("source", "add", "--party", "1", "--url", URL)

    assert result.exit_code == 1
    assert result.stderr == f"Error: source document 1 failed: {NO_TEXT_LAYER}\n"
    assert _list_rows(run)[1] == [
        "1", "url", "failed", "2", _sha(data), "programa 2023.pdf", URL, NO_TEXT_LAYER, "", ""
    ]
    assert (files_dir / f"{_sha(data)}.pdf").exists()


@pytest.mark.parametrize(
    "args, message",
    [
        (("--party", "999", "--url", URL), "Error: party 999 not found\n"),
        (("--party", "1", "--url", "ftp://example.org/x.pdf"), "Error: invalid URL"),
        (("--party", "1", "--url", "file:///etc/passwd"), "Error: invalid URL"),
        (("--party", "1", "--url", "https://user:pw@example.org/x.pdf"), "Error: invalid URL"),
        (("--party", "1", "--url", "https://example.org/\udcff.pdf"), "Error: invalid URL"),
    ],
    ids=["unknown-party", "ftp", "file", "credentials", "non-utf8"],
)
def test_cli_rejects_input_before_fetch(
    run, cli_parties, web: FakeOpen, files_dir: Path, args: tuple[str, ...], message: str
) -> None:
    result = run("source", "add", *args)

    assert result.exit_code == 1
    assert result.stderr.startswith(message)
    assert web.calls == []
    assert _list_rows(run) == [HEADER]
    assert not files_dir.exists()


@pytest.mark.parametrize("both", [True, False], ids=["both", "neither"])
def test_cli_requires_exactly_one_origin(
    run, cli_parties, web: FakeOpen, files_dir: Path, tmp_path: Path, both: bool
) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(TEXT_PDF)
    extra = ("--file", str(pdf), "--url", URL) if both else ()

    result = run("source", "add", "--party", "1", *extra)

    assert result.exit_code == 2
    assert "pass exactly one of --file or --url" in result.stderr
    assert web.calls == []
    assert _list_rows(run) == [HEADER]
    assert not files_dir.exists()


def test_cli_duplicate_and_other_party(
    run, cli_parties, web: FakeOpen, files_dir: Path, tmp_path: Path
) -> None:
    pdf = tmp_path / "manifesto.pdf"
    pdf.write_bytes(TEXT_PDF)
    assert run("source", "add", "--party", "1", "--file", str(pdf)).exit_code == 0
    web.outcomes[URL] = TEXT_PDF

    again = run("source", "add", "--party", "1", "--url", URL)
    other = run("source", "add", "--party", "2", "--url", URL)

    assert again.exit_code == 1
    assert again.stderr == (
        f"Error: party 1 already has a source document with content hash {_sha(TEXT_PDF)}\n"
    )
    assert len(_list_rows(run, "1")) == 2
    assert other.exit_code == 0, other.output
    assert other.output == "Created source document 2: parsed (2 pages)\n"
    assert [p.name for p in files_dir.iterdir()] == [f"{_sha(TEXT_PDF)}.pdf"]


def test_cli_list_shows_url_column(run, cli_parties, web: FakeOpen, tmp_path: Path) -> None:
    pdf = tmp_path / "manifesto.pdf"
    upload_data = make_text_pdf(["Otro programa"])
    pdf.write_bytes(upload_data)
    missing = "https://example.org/missing.pdf"
    web.outcomes[URL] = TEXT_PDF
    web.outcomes[missing] = lambda: http_error(404, "Not Found")
    run("source", "add", "--party", "1", "--url", URL)
    run("source", "add", "--party", "1", "--url", missing)
    run("source", "add", "--party", "1", "--file", str(pdf))

    assert _list_rows(run) == [
        HEADER,
        ["1", "url", "parsed", "2", _sha(TEXT_PDF), "programa 2023.pdf", URL, "", "", ""],
        ["2", "url", "failed", "", "", "", missing, "HTTP 404: Not Found", "", ""],
        ["3", "upload", "parsed", "1", _sha(upload_data), "manifesto.pdf", "", "", "", ""],
    ]


@pytest.mark.parametrize("revision", [None, "0001", "0002"])
def test_cli_url_requires_current_schema(
    db_url: str, files_dir: Path, web: FakeOpen, revision: str | None
) -> None:
    if revision:
        run_migrations(db_url, revision)

    result = CliRunner().invoke(
        main, ["--database-url", db_url, "source", "add", "--party", "1", "--url", URL]
    )

    assert result.exit_code == 1
    assert result.output == f"Error: {NOT_INITIALISED}\n"
    assert web.calls == []
    assert not files_dir.exists()
