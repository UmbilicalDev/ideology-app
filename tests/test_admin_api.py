"""feedback-admin Scenarios 1-8, 11 and 12 through the app: the Operator admin API and page.

Throwaway accounts made in the test (``prueba``); temporary SQLite files only.
"""

import datetime as dt
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from ideology_app.admin import accounts
from ideology_app.admin.accounts import hash_password
from ideology_app.admin.sessions import AdminSessionStore
from ideology_app.api import admin_routes
from ideology_app.config import ConfigError
from ideology_app.db import make_engine
from ideology_app.feedback.rate_limit import FeedbackRateLimiter
from ideology_app.feedback.store import add_message, mark_reviewed, upgrade_schema
from ideology_app.main import create_app

API = "/admin/api/v1"
PASSWORD = "contraseña-de-prueba"
ADMIN_HEADERS = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
    "x-content-type-options": "nosniff",
}
PAGE_HEADERS = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex, nofollow",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; font-src 'self' data:; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}
ADMIN_HTML = b"<!doctype html><title>Administraci\xc3\xb3n \xc2\xb7 IdeologiApp</title>admin"
VOTER_HTML = b"<!doctype html><title>IdeologiApp</title>voter"


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def prueba_hash() -> str:
    return hash_password(PASSWORD, log2_n=14)


@pytest.fixture
def feedback_path(tmp_path: Path) -> Path:
    return tmp_path / "fb.db"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "admin").mkdir(parents=True)
    (root / "index.html").write_bytes(VOTER_HTML)
    (root / "admin" / "index.html").write_bytes(ADMIN_HTML)
    return root


MakeClient = Callable[..., TestClient]


@pytest.fixture
def make_client(
    db_url: str, feedback_path: Path, dist: Path, prueba_hash: str
) -> Iterator[MakeClient]:
    clients: list[TestClient] = []

    def make(base_url: str = "https://testserver", admin_users: str | None = None) -> TestClient:
        users = f"prueba:{prueba_hash}" if admin_users is None else admin_users
        client = TestClient(
            create_app(
                db_url,
                web_dist_dir=dist,
                feedback_database_url=f"sqlite:///{feedback_path}",
                admin_users=users,
            ),
            base_url=base_url,
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: MakeClient) -> TestClient:
    return make_client()


def sign_in(client: TestClient, username: str = "prueba", password: str = PASSWORD, **kw: Any) -> httpx.Response:
    return client.post(f"{API}/session", json={"username": username, "password": password}, **kw)


def signed_in(client: TestClient) -> str:
    response = sign_in(client)
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def seed(path: Path, count: int, start: dt.datetime | None = None) -> None:
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade_schema(engine)
        start = start or dt.datetime(2026, 10, 20, 10, 0, tzinfo=dt.UTC)
        for i in range(count):
            add_message(engine, f"Mensaje {i + 1}", "landing" if i % 2 else "results", start + dt.timedelta(hours=6 * i))
    finally:
        engine.dispose()


def assert_admin_headers(response: httpx.Response) -> None:
    for name, value in ADMIN_HEADERS.items():
        assert response.headers.get(name) == value, (name, response.status_code)


def assert_cookie_cleared(response: httpx.Response, secure: bool = True) -> None:
    cookies = response.headers.get_list("set-cookie")
    expected = "ideology_admin=; Path=/admin/api; Max-Age=0; HttpOnly; SameSite=Strict"
    assert cookies == [expected + ("; Secure" if secure else "")]


# --- Scenario 1: sign in -----------------------------------------------------


def test_sign_in_sets_a_strict_cookie_and_opens_the_api(client: TestClient) -> None:
    response = sign_in(client)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"username", "csrf_token"}
    assert body["username"] == "prueba"
    assert_admin_headers(response)
    (cookie,) = response.headers.get_list("set-cookie")
    name_value, *attributes = cookie.split("; ")
    assert name_value.startswith("ideology_admin=") and len(name_value) > 50
    assert attributes == ["Path=/admin/api", "HttpOnly", "SameSite=Strict", "Secure"]
    assert "Max-Age" not in cookie and "Expires" not in cookie
    listed = client.get(f"{API}/feedback")
    assert listed.status_code == 200
    assert_admin_headers(listed)
    session = client.get(f"{API}/session")
    assert session.json() == body


@pytest.mark.parametrize("base_url", ["http://localhost", "http://127.0.0.1:8010", "http://[::1]:8010"])
def test_no_secure_flag_on_local_hosts(make_client: MakeClient, base_url: str) -> None:
    client = make_client(base_url=base_url)
    response = sign_in(client)
    assert response.status_code == 200
    (cookie,) = response.headers.get_list("set-cookie")
    assert cookie.endswith("; HttpOnly; SameSite=Strict")
    assert "Secure" not in cookie
    assert client.get(f"{API}/feedback").status_code == 200


def test_plain_http_on_a_real_host_still_gets_secure(make_client: MakeClient) -> None:
    client = make_client(base_url="http://example.org")
    response = sign_in(client)
    assert response.headers["set-cookie"].endswith("; Secure")


def test_sign_in_replaces_the_previous_session(client: TestClient) -> None:
    sign_in(client)
    old = client.cookies.get("ideology_admin")
    sign_in(client)
    new = client.cookies.get("ideology_admin")
    assert old and new and old != new
    client.cookies.clear()
    response = client.get(f"{API}/session", headers={"Cookie": f"ideology_admin={old}"})
    assert response.status_code == 401


# --- Scenario 2: wrong credentials --------------------------------------------


def test_wrong_password_and_unknown_user_look_the_same(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    accounts._dummy_hash()
    calls: list[Any] = []
    real = accounts.verify_password
    monkeypatch.setattr(accounts, "verify_password", lambda p, h: (calls.append(h), real(p, h))[1])
    wrong = sign_in(client, password="otra-contraseña")
    assert len(calls) == 1
    unknown = sign_in(client, username="nadie")
    assert len(calls) == 2
    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.json() == {
            "error": {"code": "invalid_credentials", "message": "Usuario o contraseña incorrectos."}
        }
        assert "set-cookie" not in response.headers
        assert_admin_headers(response)
    assert wrong.content == unknown.content


# --- Scenario 3: rate limit --------------------------------------------------


def test_sixth_attempt_is_429_before_scrypt_and_lifts_after_the_window(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    client.app.state.admin_sign_in_limiter = FeedbackRateLimiter(  # type: ignore[attr-defined]
        per_client=5, global_limit=30, window_seconds=900, clock=clock
    )
    for _ in range(4):
        assert sign_in(client, password="mala-contraseña").status_code == 401
    assert sign_in(client).status_code == 200  # the 5th, successful, counts too
    calls: list[Any] = []
    real = accounts.verify_password
    monkeypatch.setattr(accounts, "verify_password", lambda p, h: (calls.append(h), real(p, h))[1])
    limited = sign_in(client)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    assert_admin_headers(limited)
    assert calls == []
    clock.now += 900
    assert sign_in(client).status_code == 200
    assert len(calls) == 1


def test_invalid_bodies_do_not_count(client: TestClient) -> None:
    for _ in range(6):
        assert client.post(f"{API}/session", json={"username": "prueba"}).status_code == 422
    assert sign_in(client).status_code == 200


def test_global_cap_of_thirty_per_window() -> None:
    clock = Clock()
    limiter = FeedbackRateLimiter(per_client=5, global_limit=30, window_seconds=900, clock=clock)
    for i in range(30):
        assert limiter.check_and_consume(f"10.0.0.{i}") is None
    assert limiter.check_and_consume("10.0.1.1") == 900
    clock.now += 899
    assert limiter.check_and_consume("10.0.1.1") == 1
    clock.now += 1
    assert limiter.check_and_consume("10.0.1.1") is None


# --- Scenario 4: no admin configured -----------------------------------------


def test_no_admin_refuses_sign_in_and_every_route(make_client: MakeClient) -> None:
    client = make_client(admin_users="")
    response = sign_in(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_not_configured"
    assert "ADMIN_USERS" in response.json()["error"]["message"]
    assert "hash-password" in response.json()["error"]["message"]
    assert_admin_headers(response)
    for method, path in ROUTES_NEEDING_SESSION:
        other = client.request(method, path)
        assert other.status_code == 401, path
        assert other.json()["error"]["code"] == "admin_not_configured"
        assert_admin_headers(other)
        assert_cookie_cleared(other)


def test_no_admin_from_unset_environment(
    db_url: str, feedback_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADMIN_USERS", raising=False)
    with TestClient(
        create_app(db_url, feedback_database_url=f"sqlite:///{feedback_path}"),
        base_url="https://testserver",
    ) as client:
        assert sign_in(client).status_code == 503


def test_admin_users_from_environment(
    db_url: str, feedback_path: Path, monkeypatch: pytest.MonkeyPatch, prueba_hash: str
) -> None:
    monkeypatch.setenv("ADMIN_USERS", f"  prueba:{prueba_hash}  ")
    with TestClient(
        create_app(db_url, feedback_database_url=f"sqlite:///{feedback_path}"),
        base_url="https://testserver",
    ) as client:
        assert sign_in(client).status_code == 200


@pytest.mark.parametrize(
    "template",
    ["prueba:scrypt.15.8.1.bad.hash", "PRUEBA:{h}", "prueba:{h},prueba:{h}", "prueba:{h},,x:{h}"],
)
def test_malformed_admin_users_fails_startup(
    db_url: str, feedback_path: Path, prueba_hash: str, template: str
) -> None:
    raw = template.format(h=prueba_hash)
    app = create_app(db_url, feedback_database_url=f"sqlite:///{feedback_path}", admin_users=raw)
    with pytest.raises(ConfigError) as info:
        with TestClient(app):
            pass
    assert prueba_hash not in str(info.value)
    assert "bad.hash" not in str(info.value)
    # Startup stopped before the feedback store was created.
    assert not feedback_path.exists()


# --- Scenario 5: 401 everywhere ----------------------------------------------

ROUTES_NEEDING_SESSION = [
    ("GET", f"{API}/session"),
    ("DELETE", f"{API}/session"),
    ("GET", f"{API}/feedback"),
    ("POST", f"{API}/feedback/1/review"),
    ("DELETE", f"{API}/feedback/1/review"),
    ("DELETE", f"{API}/feedback/1"),
]


def _assert_all_401(client: TestClient, token: str | None = None) -> None:
    client.cookies.clear()
    for method, path in ROUTES_NEEDING_SESSION:
        headers = {"X-CSRF-Token": "x"}
        if token is not None:
            headers["Cookie"] = f"ideology_admin={token}"
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401, (method, path)
        assert response.json()["error"]["code"] == "not_signed_in"
        assert_admin_headers(response)
        assert_cookie_cleared(response)


def test_401_without_cookie_and_with_unknown_token(client: TestClient, feedback_path: Path) -> None:
    seed(feedback_path, 1)
    _assert_all_401(client)
    _assert_all_401(client, "not-a-real-token")
    # Nothing changed.
    with closing(sqlite3.connect(feedback_path)) as connection:
        assert connection.execute("SELECT COUNT(*), MAX(reviewed_at) FROM feedback_messages").fetchone() == (1, None)


def test_401_after_idle_and_absolute_expiry(client: TestClient) -> None:
    clock = Clock()
    client.app.state.admin_sessions = AdminSessionStore(clock=clock)  # type: ignore[attr-defined]
    signed_in(client)
    token = client.cookies["ideology_admin"]
    clock.now += 1801
    _assert_all_401(client, token)

    client.cookies.clear()
    signed_in(client)
    token = client.cookies["ideology_admin"]
    for _ in range(16):
        clock.now += 1800
        assert client.get(f"{API}/session").status_code == 200
    clock.now += 1
    _assert_all_401(client, token)


def test_sign_out_ends_the_session(client: TestClient) -> None:
    csrf = signed_in(client)
    token = client.cookies["ideology_admin"]
    response = client.delete(f"{API}/session", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert_admin_headers(response)
    assert_cookie_cleared(response)
    assert len(client.app.state.admin_sessions) == 0  # type: ignore[attr-defined]
    _assert_all_401(client, token)


# --- Scenario 6: CSRF --------------------------------------------------------

STATE_CHANGING = [
    ("DELETE", f"{API}/session"),
    ("POST", f"{API}/feedback/1/review"),
    ("DELETE", f"{API}/feedback/1/review"),
    ("DELETE", f"{API}/feedback/1"),
]


def _unchanged(feedback_path: Path) -> tuple[Any, ...]:
    with closing(sqlite3.connect(feedback_path)) as connection:
        return connection.execute("SELECT COUNT(*), MAX(reviewed_at) FROM feedback_messages").fetchone()


@pytest.mark.parametrize("method,path", STATE_CHANGING)
def test_missing_wrong_or_foreign_csrf_token_is_403(
    make_client: MakeClient, feedback_path: Path, method: str, path: str
) -> None:
    seed(feedback_path, 1)
    client = make_client()
    signed_in(client)
    other = make_client()
    other_csrf = signed_in(other)
    for headers in ({}, {"X-CSRF-Token": "wrong"}, {"X-CSRF-Token": other_csrf}):
        response = client.request(method, path, headers=headers)
        assert response.status_code == 403, headers
        assert response.json()["error"]["code"] == "csrf_failed"
        assert_admin_headers(response)
    assert _unchanged(feedback_path) == (1, None)
    assert client.get(f"{API}/session").status_code == 200  # still signed in


@pytest.mark.parametrize("method,path", STATE_CHANGING)
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": "https://testserver:8443"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_origin_state_change_is_403(
    client: TestClient, feedback_path: Path, method: str, path: str, headers: dict[str, str]
) -> None:
    seed(feedback_path, 1)
    csrf = signed_in(client)
    response = client.request(method, path, headers={"X-CSRF-Token": csrf, **headers})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert _unchanged(feedback_path) == (1, None)


@pytest.mark.parametrize(
    "headers", [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}]
)
def test_cross_origin_sign_in_is_403_before_anything_else(
    make_client: MakeClient, headers: dict[str, str]
) -> None:
    for client in (make_client(), make_client(admin_users="")):
        response = sign_in(client, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_failed"
        assert "set-cookie" not in response.headers


def test_same_origin_headers_are_accepted(client: TestClient) -> None:
    response = sign_in(
        client, headers={"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"}
    )
    assert response.status_code == 200
    csrf = response.json()["csrf_token"]
    out = client.delete(
        f"{API}/session", headers={"X-CSRF-Token": csrf, "Origin": "https://testserver", "Sec-Fetch-Site": "none"}
    )
    assert out.status_code == 204


def test_sign_in_media_type_size_and_shape(client: TestClient) -> None:
    plain = client.post(
        f"{API}/session",
        content=b'{"username":"prueba","password":"x"}',
        headers={"Content-Type": "text/plain"},
    )
    assert plain.status_code == 415
    assert_admin_headers(plain)
    big = client.post(
        f"{API}/session",
        content=b'{"username":"prueba","password":"' + b"a" * 5000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert big.status_code == 413
    for body in (
        {"username": "prueba"},
        {"username": "prueba", "password": PASSWORD, "extra": 1},
        {"username": 1, "password": PASSWORD},
        {"username": "u" * 65, "password": PASSWORD},
        {"username": "prueba", "password": "p" * 1025},
    ):
        response = client.post(f"{API}/session", json=body)
        assert response.status_code == 422, body
        assert_admin_headers(response)
        assert PASSWORD not in response.text
    invalid_json = client.post(
        f"{API}/session", content=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert invalid_json.status_code == 422


# --- Scenario 7: list and filter -------------------------------------------


def _seed_sixty(feedback_path: Path) -> None:
    # 60 messages, 6 hours apart, from 2026-10-20 10:00 UTC; every 4th reviewed.
    seed(feedback_path, 60)
    engine = make_engine(f"sqlite:///{feedback_path}")
    try:
        for message_id in range(1, 61, 4):
            mark_reviewed(engine, message_id, dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.UTC))
    finally:
        engine.dispose()


def test_list_pages_newest_first(client: TestClient, feedback_path: Path) -> None:
    _seed_sixty(feedback_path)
    signed_in(client)
    first = client.get(f"{API}/feedback").json()
    assert [m["id"] for m in first["messages"]] == list(range(60, 10, -1))
    assert first["next_before_id"] == 11
    second = client.get(f"{API}/feedback", params={"before_id": 11}).json()
    assert [m["id"] for m in second["messages"]] == list(range(10, 0, -1))
    assert second["next_before_id"] is None
    message = first["messages"][-1]
    assert list(message) == ["id", "message", "origin", "created_at", "reviewed_at"]
    assert message == {
        "id": 11,
        "message": "Mensaje 11",
        "origin": "results",
        "created_at": "2026-10-22T22:00:00Z",
        "reviewed_at": None,
    }
    reviewed = next(m for m in first["messages"] if m["id"] == 57)
    assert reviewed["reviewed_at"] == "2026-10-29T12:00:00Z"
    small = client.get(f"{API}/feedback", params={"limit": 100}).json()
    assert len(small["messages"]) == 60 and small["next_before_id"] is None


def test_filters_by_day_and_reviewed_state(client: TestClient, feedback_path: Path) -> None:
    _seed_sixty(feedback_path)
    signed_in(client)

    def ids(**params: Any) -> list[int]:
        body = client.get(f"{API}/feedback", params={"limit": 100, **params}).json()
        return [m["id"] for m in body["messages"]]

    # Message n is at 2026-10-20 10:00 UTC + 6 h * (n - 1): ids 4..11 fall on the 21st and 22nd.
    assert ids(**{"from": "2026-10-21", "to": "2026-10-22"}) == range10(4, 11)
    assert ids(**{"from": "2026-10-21", "to": "2026-10-21"}) == [7, 6, 5, 4]
    assert ids(**{"from": "2026-11-03"}) == [60, 59, 58, 57, 56]
    assert ids(**{"from": "2026-11-04"}) == [60]  # 2026-11-04 04:00 UTC
    assert ids(**{"from": "2026-11-05"}) == []
    assert ids(to="2026-10-20") == [3, 2, 1]
    assert ids(reviewed="yes") == list(range(57, 0, -4))
    assert ids(reviewed="no") == [i for i in range(60, 0, -1) if (i - 1) % 4]
    assert ids(reviewed="all") == list(range(60, 0, -1))
    assert ids(reviewed="yes", **{"from": "2026-10-21", "to": "2026-10-22"}) == [9, 5]


def range10(low: int, high: int) -> list[int]:
    return list(range(high, low - 1, -1))


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"reviewed": "maybe"},
        {"from": "2026-13-01"},
        {"to": "yesterday"},
        {"before_id": 0},
    ],
)
def test_bad_parameters_are_422(client: TestClient, params: dict[str, Any]) -> None:
    signed_in(client)
    response = client.get(f"{API}/feedback", params=params)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert_admin_headers(response)


def test_to_before_from_is_invalid_filter(client: TestClient) -> None:
    signed_in(client)
    response = client.get(f"{API}/feedback", params={"from": "2026-10-22", "to": "2026-10-21"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_filter"
    assert_admin_headers(response)


def test_bad_parameters_without_a_session_are_401(client: TestClient) -> None:
    response = client.get(f"{API}/feedback", params={"limit": 0})
    assert response.status_code == 401


# --- Scenario 8: mark, unmark, delete ----------------------------------------


def test_mark_keeps_the_first_time_and_unmark_clears_it(
    client: TestClient, feedback_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(feedback_path, 2)
    csrf = signed_in(client)
    headers = {"X-CSRF-Token": csrf}
    monkeypatch.setattr(
        admin_routes, "_now", lambda: dt.datetime(2026, 10, 29, 14, 5, 7, 999_999, tzinfo=dt.UTC)
    )
    marked = client.post(f"{API}/feedback/1/review", headers=headers)
    assert marked.status_code == 200
    assert_admin_headers(marked)
    assert marked.json()["reviewed_at"] == "2026-10-29T14:05:07Z"
    monkeypatch.setattr(admin_routes, "_now", lambda: dt.datetime(2026, 10, 30, tzinfo=dt.UTC))
    again = client.post(f"{API}/feedback/1/review", headers=headers)
    assert again.json()["reviewed_at"] == "2026-10-29T14:05:07Z"
    cleared = client.delete(f"{API}/feedback/1/review", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json() == {
        "id": 1,
        "message": "Mensaje 1",
        "origin": "results",
        "created_at": "2026-10-20T10:00:00Z",
        "reviewed_at": None,
    }
    # The other message was never touched.
    assert client.get(f"{API}/feedback").json()["messages"][0]["reviewed_at"] is None


def test_delete_is_a_hard_delete_and_overwrites_the_text(
    client: TestClient, feedback_path: Path
) -> None:
    secret = "texto-que-debe-desaparecer-" + "z" * 40
    seed(feedback_path, 3)
    engine = make_engine(f"sqlite:///{feedback_path}")
    try:
        add_message(engine, secret, "landing", dt.datetime(2026, 10, 28, tzinfo=dt.UTC))
    finally:
        engine.dispose()
    assert secret.encode() in feedback_path.read_bytes()
    csrf = signed_in(client)
    headers = {"X-CSRF-Token": csrf}
    response = client.delete(f"{API}/feedback/4", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    assert_admin_headers(response)
    for method, path in (
        ("POST", f"{API}/feedback/4/review"),
        ("DELETE", f"{API}/feedback/4/review"),
        ("DELETE", f"{API}/feedback/4"),
    ):
        gone = client.request(method, path, headers=headers)
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "feedback_not_found"
        assert_admin_headers(gone)
    assert [m["id"] for m in client.get(f"{API}/feedback").json()["messages"]] == [3, 2, 1]
    # secure_delete: the text is no longer anywhere in the file.
    assert secret.encode() not in feedback_path.read_bytes()


def test_unknown_id_is_404(client: TestClient) -> None:
    csrf = signed_in(client)
    for method, suffix in (("POST", "/review"), ("DELETE", "/review"), ("DELETE", "")):
        response = client.request(method, f"{API}/feedback/999{suffix}", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "feedback_not_found"


# --- Scenario 11: Voters untouched -----------------------------------------


def test_voter_routes_set_no_cookie_and_never_receive_the_admin_cookie(
    migrated_engine: Any, client: TestClient
) -> None:
    seen: list[httpx.Request] = []
    client.event_hooks = {"request": [seen.append], "response": []}
    for path in ("/", "/metodologia", "/api/v1/elections", "/health"):
        response = client.get(path)
        assert "set-cookie" not in response.headers, path
    posted = client.post("/api/v1/feedback", json={"message": "Hola", "origin": "landing"})
    assert posted.status_code == 201
    assert "set-cookie" not in posted.headers
    signed_in(client)
    seen.clear()
    client.get("/api/v1/elections")
    client.get("/")
    client.post("/api/v1/feedback", json={"message": "Otra", "origin": "results"})
    assert [r.url.path for r in seen] == ["/api/v1/elections", "/", "/api/v1/feedback"]
    assert all("cookie" not in r.headers for r in seen)
    seen.clear()
    client.get(f"{API}/session")
    assert "ideology_admin=" in seen[0].headers["cookie"]


def test_public_openapi_has_no_admin_path(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/admin")]


# --- Scenario 12: page serving -----------------------------------------------


@pytest.mark.parametrize("path", ["/admin", "/admin/"])
def test_admin_page_is_served_with_every_header(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert response.content == ADMIN_HTML
    assert response.headers["content-type"].startswith("text/html")
    for name, value in PAGE_HEADERS.items():
        assert response.headers[name] == value, name
    assert "set-cookie" not in response.headers
    head = client.head(path)
    assert head.status_code == 200
    for name, value in PAGE_HEADERS.items():
        assert head.headers[name] == value, name


@pytest.mark.parametrize(
    "path", ["/admin/index.html", "/admin/x", "/admin/api/v1/nope", "/admin/api", "/admin/assets/x.js"]
)
def test_other_admin_paths_are_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_voter_index_is_still_served(client: TestClient) -> None:
    for path in ("/", "/metodologia", "/resultados"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.content == VOTER_HTML


def test_admin_page_is_404_while_not_built(make_client: MakeClient, dist: Path) -> None:
    (dist / "admin" / "index.html").unlink()
    client = make_client()
    assert client.get("/admin").status_code == 404
    assert client.get("/").content == VOTER_HTML
