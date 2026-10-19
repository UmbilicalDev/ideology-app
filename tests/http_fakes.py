"""Fake HTTP responses for tests that patch ``ideology_app.http_fetch._open``."""

import io
from email.message import Message
from urllib.error import HTTPError


class FakeResponse:
    """A context-managed response with ``read(n)`` and ``headers``."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = io.BytesIO(body)
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self.closed = False
        self.reads = 0

    def read(self, n: int = -1) -> bytes:
        self.reads += 1
        return self._body.read(n)

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def http_error(code: int, reason: str, url: str = "https://example.org/x.pdf") -> HTTPError:
    """An HTTPError with an in-memory body, so closing it needs no socket."""
    return HTTPError(url, code, reason, Message(), io.BytesIO(b""))
