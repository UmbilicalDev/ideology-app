"""The HTTP fetch adapter, with ``http_fetch._open`` mocked (offline)."""

import http.client
import socket
import urllib.request
from urllib.error import URLError

import pytest
from http_fakes import FakeResponse, http_error

from ideology_app import http_fetch
from ideology_app.http_fetch import FetchError, fetch_url

URL = "https://example.org/docs/programa.pdf"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No socket can connect."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is blocked in HTTP fetch tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _serve(monkeypatch: pytest.MonkeyPatch, outcome: object) -> list[tuple[object, float]]:
    """Patch ``_open`` to return or raise ``outcome``; return the recorded calls."""
    calls: list[tuple[object, float]] = []

    def fake_open(request: urllib.request.Request, timeout: float) -> object:
        calls.append((request, timeout))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(http_fetch, "_open", fake_open)
    return calls


def test_returns_body_and_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(b"%PDF-1.4 body")
    calls = _serve(monkeypatch, response)

    assert fetch_url(URL, max_bytes=100) == b"%PDF-1.4 body"

    [(request, timeout)] = calls
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == URL
    assert request.get_header("User-agent") == http_fetch.USER_AGENT
    assert timeout == http_fetch.FETCH_TIMEOUT_SECONDS == 60
    assert response.closed


@pytest.mark.parametrize(
    "url, sent",
    [
        ("https://example.org/programa-año.pdf", "https://example.org/programa-a%C3%B1o.pdf"),
        ("https://example.org/programa-a%C3%B1o.pdf", "https://example.org/programa-a%C3%B1o.pdf"),
        (
            "https://example.org/a%20b/ñ.pdf?q=año&x=%41",
            "https://example.org/a%20b/%C3%B1.pdf?q=a%C3%B1o&x=%41",
        ),
        ("http://bücher.example:8080/x.pdf", "http://xn--bcher-kva.example:8080/x.pdf"),
        ("https://example.org/p.pdf?a=1&b=[2]", "https://example.org/p.pdf?a=1&b=[2]"),
    ],
    ids=["non-ascii-path", "already-encoded", "mixed-path-query", "idna-host", "ascii-untouched"],
)
def test_request_url_is_ascii(monkeypatch: pytest.MonkeyPatch, url: str, sent: str) -> None:
    calls = _serve(monkeypatch, FakeResponse(b"%PDF-1.4"))

    assert fetch_url(url, max_bytes=100) == b"%PDF-1.4"

    [(request, _)] = calls
    assert request.full_url == sent


def test_unencodable_host_is_a_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, FakeResponse(b"%PDF-1.4"))

    with pytest.raises(FetchError, match=r"^could not fetch URL: Unicode\w*Error: .*label too long"):
        fetch_url("https://" + "ñ" * 70 + ".example/x.pdf", max_bytes=100)
    assert calls == []


def test_reads_in_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_fetch, "_CHUNK_SIZE", 4)
    response = FakeResponse(b"%PDF-0123456789")
    _serve(monkeypatch, response)

    assert fetch_url(URL, max_bytes=100) == b"%PDF-0123456789"
    assert response.reads == 5  # 4 chunks + EOF


@pytest.mark.parametrize("code, reason", [(404, "Not Found"), (500, "Internal Server Error")])
def test_http_error_is_reported_and_closed(
    monkeypatch: pytest.MonkeyPatch, code: int, reason: str
) -> None:
    error = http_error(code, reason)
    _serve(monkeypatch, error)

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=100)

    assert excinfo.value.reason == f"HTTP {code}: {reason}"
    assert str(excinfo.value) == f"HTTP {code}: {reason}"
    assert error.fp is None or error.fp.closed


@pytest.mark.parametrize(
    "error, reason",
    [
        (URLError("Name or service not known"), "could not fetch URL: Name or service not known"),
        (TimeoutError("timed out"), "could not fetch URL: TimeoutError: timed out"),
        (
            ConnectionResetError("reset by peer"),
            "could not fetch URL: ConnectionResetError: reset by peer",
        ),
        (
            http.client.IncompleteRead(b"%PDF-", 10),
            "could not fetch URL: IncompleteRead: IncompleteRead(5 bytes read, 10 more expected)",
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
    ],
    ids=[
        "url-error", "timeout", "connection-reset", "incomplete-read", "unicode-encode",
        "invalid-url", "value-error",
    ],
)
def test_network_errors(monkeypatch: pytest.MonkeyPatch, error: BaseException, reason: str) -> None:
    _serve(monkeypatch, error)

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=100)

    assert excinfo.value.reason == reason


def test_error_while_reading_body(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(FakeResponse):
        def read(self, n: int = -1) -> bytes:
            raise http.client.IncompleteRead(b"", 3)

    response = Broken(b"")
    _serve(monkeypatch, response)

    with pytest.raises(FetchError, match="^could not fetch URL: IncompleteRead"):
        fetch_url(URL, max_bytes=100)
    assert response.closed


def test_content_length_over_limit_is_rejected_before_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(b"%PDF-", headers={"Content-Length": "11"})
    _serve(monkeypatch, response)

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=10)

    assert excinfo.value.reason == "response is too large (more than 10 bytes)"
    assert response.reads == 0
    assert response.closed


@pytest.mark.parametrize("length", [None, "5", "not-a-number"])
def test_streamed_body_over_limit_is_rejected(
    monkeypatch: pytest.MonkeyPatch, length: str | None
) -> None:
    monkeypatch.setattr(http_fetch, "_CHUNK_SIZE", 4)
    headers = {"Content-Length": length} if length else None
    _serve(monkeypatch, FakeResponse(b"%PDF-123456", headers=headers))

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=10)

    assert excinfo.value.reason == "response is too large (more than 10 bytes)"


def test_body_at_limit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, FakeResponse(b"%PDF-12345", headers={"Content-Length": "10"}))

    assert fetch_url(URL, max_bytes=10) == b"%PDF-12345"


def test_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, FakeResponse(b""))

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=10)

    assert excinfo.value.reason == "response is empty"


def test_reason_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, URLError("x" * 1000))

    with pytest.raises(FetchError) as excinfo:
        fetch_url(URL, max_bytes=10)

    assert len(excinfo.value.reason) == 500
    assert excinfo.value.reason.startswith("could not fetch URL: xxx")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.org/x.pdf", "data:application/pdf,%25PDF-"]
)
def test_opener_rejects_non_http_schemes(url: str) -> None:
    with pytest.raises(URLError, match="unknown url type"):
        http_fetch._OPENER.open(url, timeout=1)


def test_opener_handlers_are_http_only() -> None:
    # ProxyHandler registers itself only when *_PROXY variables are set.
    names = {type(h).__name__ for h in http_fetch._OPENER.handlers}
    assert {"HTTPHandler", "HTTPSHandler", "HTTPRedirectHandler"} <= names
    assert set(http_fetch._OPENER.handle_open) <= {"http", "https", "unknown"}
    assert names <= {
        "ProxyHandler",
        "UnknownHandler",
        "HTTPHandler",
        "HTTPSHandler",
        "HTTPDefaultErrorHandler",
        "HTTPRedirectHandler",
        "HTTPErrorProcessor",
    }


def test_redirect_to_file_url_is_refused() -> None:
    handler = urllib.request.HTTPRedirectHandler()
    request = urllib.request.Request(URL)
    headers = http.client.HTTPMessage()
    headers["Location"] = "file:///etc/passwd"
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        handler.http_error_302(request, None, 302, "Found", headers)
    excinfo.value.close()
    assert "not allowed" in str(excinfo.value)
