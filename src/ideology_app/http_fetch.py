"""HTTP download of Source Document URLs (stdlib ``urllib`` only).

This is the only module that does HTTP for Source Documents. It opens only
``http``/``https`` URLs (redirects included) and never retries. Tests replace
``_open``, the single seam, so no test opens a socket.
"""

import http.client
import string
import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit

FETCH_TIMEOUT_SECONDS = 60
USER_AGENT = "ideology-app/0.1 (+manifesto fetch)"
_CHUNK_SIZE = 1024 * 1024
_REASON_MAX = 500

# Only the handlers needed for http/https: no file:, ftp: or data: handler, so
# those URLs (and redirects to them) fail with "unknown url type".
_OPENER = urllib.request.OpenerDirector()
for _handler in (
    urllib.request.ProxyHandler(),
    urllib.request.UnknownHandler(),
    urllib.request.HTTPHandler(),
    urllib.request.HTTPSHandler(),
    urllib.request.HTTPDefaultErrorHandler(),
    urllib.request.HTTPRedirectHandler(),
    urllib.request.HTTPErrorProcessor(),
):
    _OPENER.add_handler(_handler)


class FetchError(Exception):
    """A download that failed; ``reason`` is a short, human-readable cause."""

    def __init__(self, reason: str) -> None:
        self.reason = reason[:_REASON_MAX]
        super().__init__(self.reason)


def _ascii_url(url: str) -> str:
    """Return ``url`` in a form ``http.client`` can send.

    Non-ASCII characters in the path, query and fragment are UTF-8
    percent-encoded; every ASCII character (existing ``%XX`` escapes included)
    is left as is. A non-ASCII hostname is IDNA-encoded. An all-ASCII URL is
    returned unchanged.
    """
    if url.isascii():
        return url
    parts = urlsplit(url)
    netloc = parts.netloc
    if not netloc.isascii():
        host = (parts.hostname or "").encode("idna").decode("ascii")
        netloc = host if parts.port is None else f"{host}:{parts.port}"

    def encode(component: str) -> str:
        return quote(component, safe=string.punctuation)

    return urlunsplit(
        (parts.scheme, netloc, encode(parts.path), encode(parts.query), encode(parts.fragment))
    )


def _open(request: urllib.request.Request, timeout: float) -> Any:
    """Open ``request``. The single test seam: tests monkeypatch this."""
    return _OPENER.open(request, timeout=timeout)


def _too_large(max_bytes: int) -> FetchError:
    return FetchError(f"response is too large (more than {max_bytes} bytes)")


def _read_body(response: Any, max_bytes: int) -> bytes:
    headers = getattr(response, "headers", None)
    length = headers.get("Content-Length") if headers is not None else None
    if length is not None and length.strip().isdigit() and int(length) > max_bytes:
        raise _too_large(max_bytes)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(url: str, *, max_bytes: int) -> bytes:
    """Download ``url`` and return its body. Raises FetchError on any failure.

    The request goes to ``_ascii_url(url)``; callers keep ``url`` as given.
    """
    try:
        request = urllib.request.Request(_ascii_url(url), headers={"User-Agent": USER_AGENT})
        with _open(request, FETCH_TIMEOUT_SECONDS) as response:
            data = _read_body(response, max_bytes)
    except FetchError:
        raise
    except HTTPError as exc:
        try:
            raise FetchError(f"HTTP {exc.code}: {exc.reason}") from None
        finally:
            exc.close()
    except URLError as exc:
        raise FetchError(f"could not fetch URL: {exc.reason}") from None
    except (http.client.HTTPException, OSError) as exc:  # TimeoutError is an OSError
        raise FetchError(f"could not fetch URL: {type(exc).__name__}: {exc}") from None
    except ValueError as exc:  # UnicodeError, http.client.InvalidURL, unknown url type
        raise FetchError(f"could not fetch URL: {type(exc).__name__}: {exc}") from None
    if not data:
        raise FetchError("response is empty")
    return data
