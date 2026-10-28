"""feedback-api Scenarios 1-7 through the app: ``POST /api/v1/feedback``.

Temporary SQLite files only (the conftest chdirs into tmp_path); no network.
"""

import datetime as dt
import json
import sqlite3
from contextlib import closing
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event

from ideology_app.api import feedback_routes
from ideology_app.feedback.rate_limit import FeedbackRateLimiter
from ideology_app.feedback.store import FeedbackStoreError
from ideology_app.main import create_app
from test_feedback_message import VECTORS

URL = "/api/v1/feedback"
RECEIVED = {"status": "received"}


@pytest.fixture
def feedback_path(tmp_path: Path) -> Path:
    return tmp_path / "fb.db"


@pytest.fixture
def client(db_url: str, feedback_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_url, feedback_database_url=f"sqlite:///{feedback_path}")) as c:
        yield c


def rows(path: Path) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT id, message, origin, created_at FROM feedback_messages ORDER BY id"
        ).fetchall()


def post(client: TestClient, body: Any, **kwargs: Any) -> Any:
    return client.post(URL, json=body, **kwargs)


# --- Scenario 1 ------------------------------------------------------------


def test_stored_trimmed_with_utc_whole_seconds_and_no_main_db_statement(
    db_url: str, feedback_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        feedback_routes, "_now", lambda: dt.datetime(2026, 10, 5, 9, 8, 7, 654_321, tzinfo=dt.UTC)
    )
    app = create_app(db_url, feedback_database_url=f"sqlite:///{feedback_path}")
    with TestClient(app) as client:
        main_engine: Engine = app.state.engine
        statements: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            statements.append(statement)

        event.listen(main_engine, "before_cursor_execute", record)
        try:
            response = post(client, {"message": "  Muy útil 👍\n", "origin": "results"})
        finally:
            event.remove(main_engine, "before_cursor_execute", record)

    assert response.status_code == 201
    assert response.json() == RECEIVED
    assert response.headers["cache-control"] == "no-store"
    assert statements == []
    assert rows(feedback_path) == [(1, "Muy útil 👍", "results", "2026-10-05 09:08:07.000000")]
    # The shared-DB file is not even created by a POST.
    assert not Path(db_url.removeprefix("sqlite:///")).exists()


def test_response_has_no_id_and_openapi_declares_the_body(client: TestClient) -> None:
    for _ in range(2):
        assert post(client, {"message": "hola", "origin": "landing"}).json() == RECEIVED
    operation = client.get("/api/openapi.json").json()["paths"][URL]["post"]
    assert operation["operationId"] == "sendFeedback"
    body = operation["requestBody"]
    assert body["required"] is True
    schema = body["content"]["application/json"]["schema"]
    assert schema["required"] == ["message", "origin"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"message", "origin", "website"}


# --- Scenario 2 ------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), VECTORS, ids=[repr(v[0])[:24] for v in VECTORS])
def test_rule_vectors(
    client: TestClient, feedback_path: Path, raw: str, expected: str
) -> None:
    client.app.state.feedback_rate_limiter = FeedbackRateLimiter()  # type: ignore[attr-defined]
    if raw == "\ud800":
        # json.dumps escapes a lone surrogate as \ud800; pydantic refuses it.
        response = client.post(
            URL, content=b'{"message":"\\ud800","origin":"landing"}',
            headers={"Content-Type": "application/json"},
        )
    else:
        response = post(client, {"message": raw, "origin": "landing"})
    if expected in ("control_character", "empty", "too_long"):
        assert response.status_code == 422, response.text
        assert response.headers["cache-control"] == "no-store"
        assert rows(feedback_path) == []
    else:
        assert response.status_code == 201, response.text
        assert [r[1] for r in rows(feedback_path)] == [expected]


# --- Scenario 3 ------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"message": "hola", "origin": "landing", "answers": "abc"},
        {"message": "hola", "origin": "admin"},
        {"message": 5, "origin": "landing"},
        {"message": ["hola"], "origin": "landing"},
        {"message": "hola"},
        {"origin": "landing"},
        {"message": "hola", "origin": "landing", "website": 1},
        [],
        "hola",
        None,
        1,
    ],
)
def test_bad_shape_is_422_and_stores_nothing(
    client: TestClient, feedback_path: Path, body: Any
) -> None:
    response = client.post(
        URL, content=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.headers["cache-control"] == "no-store"
    assert rows(feedback_path) == []


def test_invalid_json_is_422_in_fastapi_shape(client: TestClient, feedback_path: Path) -> None:
    for content in (b"{bad", b"", b'{"message":"hola","origin":"landing"', "\xff".encode("latin-1")):
        response = client.post(URL, content=content, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail[0]["loc"][0] == "body"
    assert rows(feedback_path) == []


def test_422_detail_names_the_rule(client: TestClient) -> None:
    response = post(client, {"message": "a\tb", "origin": "landing"})
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "message"]
    assert "control characters other than newline" in detail[0]["msg"]


# --- Scenario 4 ------------------------------------------------------------


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded", "application/jsonx"])
def test_wrong_media_type_is_415(
    client: TestClient, feedback_path: Path, content_type: str | None
) -> None:
    headers = {} if content_type is None else {"Content-Type": content_type}
    response = client.post(URL, content=b'{"message":"hola","origin":"landing"}', headers=headers)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert response.headers["cache-control"] == "no-store"
    assert rows(feedback_path) == []


def test_media_type_is_case_insensitive_with_parameters(client: TestClient, feedback_path: Path) -> None:
    response = client.post(
        URL,
        content=b'{"message":"hola","origin":"landing"}',
        headers={"Content-Type": "Application/JSON; charset=utf-8"},
    )
    assert response.status_code == 201
    assert len(rows(feedback_path)) == 1


def _big_body() -> bytes:
    body = json.dumps({"message": "x" * 8960, "origin": "landing"}).encode()
    assert len(body) > 8192
    return body


def test_oversized_body_with_content_length_is_413(client: TestClient, feedback_path: Path) -> None:
    response = client.post(URL, content=_big_body()[:9000], headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {
        "error": {"code": "payload_too_large", "message": "The body must be at most 8192 bytes."}
    }
    assert response.headers["cache-control"] == "no-store"
    assert rows(feedback_path) == []


def test_oversized_chunked_body_is_413(client: TestClient, feedback_path: Path) -> None:
    body = _big_body()

    def chunks() -> Iterator[bytes]:
        for start in range(0, len(body), 1000):
            yield body[start : start + 1000]

    response = client.post(URL, content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert rows(feedback_path) == []


def test_worst_case_valid_body_fits(client: TestClient, feedback_path: Path) -> None:
    body = json.dumps({"message": "😀" * 500, "origin": "results", "website": ""}).encode()
    assert len(body) < 8192
    response = client.post(URL, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 201
    assert rows(feedback_path)[0][1] == "😀" * 500


# --- Scenario 5 ------------------------------------------------------------


def test_rate_limit_429_with_retry_after(client: TestClient, feedback_path: Path) -> None:
    for i in range(5):
        assert post(client, {"message": f"m{i}", "origin": "landing"}).status_code == 201
    response = post(client, {"message": "sixth", "origin": "landing"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["cache-control"] == "no-store"
    retry_after = response.headers["retry-after"]
    assert retry_after.isdigit() and int(retry_after) >= 1
    assert [r[1] for r in rows(feedback_path)] == ["m0", "m1", "m2", "m3", "m4"]


def test_rate_limit_lifts_after_the_window(client: TestClient, feedback_path: Path) -> None:
    now = [0.0]
    client.app.state.feedback_rate_limiter = FeedbackRateLimiter(clock=lambda: now[0])  # type: ignore[attr-defined]
    for _ in range(5):
        assert post(client, {"message": "x", "origin": "landing"}).status_code == 201
    assert post(client, {"message": "x", "origin": "landing"}).headers["retry-after"] == "600"
    now[0] = 600
    assert post(client, {"message": "y", "origin": "landing"}).status_code == 201


def test_422_and_415_consume_no_budget(client: TestClient, feedback_path: Path) -> None:
    for _ in range(10):
        assert post(client, {"message": "", "origin": "landing"}).status_code == 422
        assert client.post(URL, content=b"{}", headers={"Content-Type": "text/plain"}).status_code == 415
    for _ in range(5):
        assert post(client, {"message": "ok", "origin": "landing"}).status_code == 201
    assert len(rows(feedback_path)) == 5


# --- Scenario 6 ------------------------------------------------------------


def test_honeypot_is_accepted_and_discarded_but_counts(client: TestClient, feedback_path: Path) -> None:
    for website in ("http://spam", "  x  "):
        response = post(client, {"message": "buy", "origin": "landing", "website": website})
        assert response.status_code == 201
        assert response.json() == RECEIVED
    assert rows(feedback_path) == []
    for website in ("", " \u3000", None):
        body: dict[str, Any] = {"message": "real", "origin": "results"}
        if website is not None:
            body["website"] = website
        assert post(client, body).status_code == 201
    assert [r[1] for r in rows(feedback_path)] == ["real", "real", "real"]
    # 2 honeypot hits + 3 stored = 5: the sixth is limited.
    assert post(client, {"message": "real", "origin": "results"}).status_code == 429


def test_stored_row_never_holds_request_metadata(client: TestClient, feedback_path: Path) -> None:
    post(
        client,
        {"message": "hola", "origin": "landing"},
        headers={"User-Agent": "agent-xyz", "Cookie": "c=cookie-xyz"},
    )
    with closing(sqlite3.connect(feedback_path)) as connection:
        dump = "\n".join(connection.iterdump())
    for needle in ("agent-xyz", "cookie-xyz", "testclient", "127.0.0.1"):
        assert needle not in dump


# --- Scenario 7 ------------------------------------------------------------


@pytest.fixture
def shared_file(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "ideology.db"
    path.parent.mkdir()
    sqlite3.connect(path).close()
    return path


def _refused_urls(tmp_path: Path, shared_file: Path, db_url: str) -> list[str]:
    link = tmp_path / "link.db"
    link.symlink_to(shared_file)
    return ["sqlite:///data/ideology.db", f"sqlite:///{link}", db_url, "sqlite://"]


def test_startup_refuses_a_feedback_store_that_is_not_its_own(
    tmp_path: Path, shared_file: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = shared_file.read_bytes()
    mtime = shared_file.stat().st_mtime_ns
    for url in _refused_urls(tmp_path, shared_file, db_url):
        for via_env in (False, True):
            if via_env:
                monkeypatch.setenv("FEEDBACK_DATABASE_URL", url)
                app = create_app(db_url)
            else:
                monkeypatch.delenv("FEEDBACK_DATABASE_URL", raising=False)
                app = create_app(db_url, feedback_database_url=url)
            with pytest.raises(FeedbackStoreError, match="FEEDBACK_DATABASE_URL must"):
                with TestClient(app):
                    pass
    assert shared_file.read_bytes() == before
    assert shared_file.stat().st_mtime_ns == mtime
    assert not (tmp_path / "feedback.db").exists()
    assert not Path(db_url.removeprefix("sqlite:///")).exists()


def test_default_store_is_feedback_db_in_the_current_directory(tmp_path: Path, db_url: str) -> None:
    with TestClient(create_app(db_url)) as client:
        assert post(client, {"message": "hola", "origin": "landing"}).status_code == 201
    assert [r[1] for r in rows(tmp_path / "feedback.db")] == ["hola"]


def test_other_methods_are_not_allowed(client: TestClient) -> None:
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)(URL).status_code == 405
    # GET falls through to the web catch-all, which never serves /api/ paths.
    response = client.get(URL)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}

