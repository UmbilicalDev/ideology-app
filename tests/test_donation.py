"""donate-buymeacoffee: the ``DONATION_URL`` setting and ``GET /api/v1/donation``.

Fictitious profile only (``perfil_de_prueba``): no real Buy Me a Coffee
profile is ever written here. The vectors are shared with
``packages/core/test/domain/donation.test.ts``.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ideology_app.config import (
    DONATION_URL_WARNING,
    donation_url,
    parse_donation_url,
)
from ideology_app.main import create_app

PROFILE = "https://www.buymeacoffee.com/perfil_de_prueba"

ACCEPTED = [
    PROFILE,
    "https://buymeacoffee.com/perfil_de_prueba",
    "https://www.buymeacoffee.com/Perfil-2",
    "https://buymeacoffee.com/Perfil-2",
    "https://www.buymeacoffee.com/" + "a" * 64,
]

REFUSED = [
    "http://www.buymeacoffee.com/perfil_de_prueba",
    "http://buymeacoffee.com/perfil_de_prueba",
    "https://www.buymeacoffee.com/",
    "https://buymeacoffee.com/",
    "https://m.buymeacoffee.com/perfil",
    "https://wwwbuymeacoffee.com/perfil",
    "https://buymeacoffee.com.evil.test/perfil",
    "https://BuyMeACoffee.com/perfil",
    "https://www.buymeacoffee.com/perfil_de_prueba/",
    "https://www.buymeacoffee.com/a/b",
    "https://www.buymeacoffee.com/perfil?ref=x",
    "https://www.buymeacoffee.com/perfil#x",
    "https://WWW.BUYMEACOFFEE.COM/perfil",
    "https://www.buymeacoffee.com.evil.test/perfil",
    "https://www.buymeacoffee.com@evil.test/perfil",
    "https://www.buymeacoffee.com:443/perfil",
    "https://www.buymeacoffee.com/perfil%20x",
    "https://www.buymeacoffee.com/perfíl",
    "https://www.buymeacoffee.com/" + "a" * 65,
    "https://www.buymeacoffee.com/perfil\nx",
    "javascript:alert(1)",
]

LOGGER = "ideology_app.config"


# --- Parser ------------------------------------------------------------------


@pytest.mark.parametrize("value", ACCEPTED)
def test_accepted_vectors(value: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert parse_donation_url(value) == value
    assert caplog.records == []


def test_surrounding_spaces_are_trimmed(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert parse_donation_url(f"  {PROFILE}\t\n") == PROFILE
    assert caplog.records == []


@pytest.mark.parametrize("value", REFUSED)
def test_refused_vectors_hide_the_link_and_warn_once(
    value: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert parse_donation_url(value) is None
    assert [r.getMessage() for r in caplog.records] == [DONATION_URL_WARNING]
    assert caplog.records[0].levelno == logging.WARNING
    assert "DONATION_URL" in caplog.text
    # The fixed message never echoes the value (two vectors are prefixes of
    # the format text it names, so only the others can be checked by search).
    if value.strip() not in DONATION_URL_WARNING:
        assert value.strip() not in caplog.text


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_unset_or_blank_is_none_without_warning(
    blank: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert parse_donation_url(blank) is None
    assert caplog.records == []


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert donation_url() is None
    monkeypatch.setenv("DONATION_URL", f" {PROFILE} ")
    assert donation_url() == PROFILE


# --- GET /api/v1/donation ----------------------------------------------------------


MakeClient = Callable[..., TestClient]


@pytest.fixture
def make_client(db_url: str, tmp_path: Path) -> Iterator[MakeClient]:
    clients: list[TestClient] = []

    def make(donation: str | None = None) -> TestClient:
        client = TestClient(
            create_app(
                db_url,
                web_dist_dir=tmp_path / "no-dist",
                feedback_database_url=f"sqlite:///{tmp_path}/fb.db",
                donation_url=donation,
            )
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("value", [PROFILE, "https://buymeacoffee.com/perfil_de_prueba"])
def test_serves_the_configured_url(make_client: MakeClient, value: str) -> None:
    response = make_client(value).get("/api/v1/donation")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.text == f'{{"url":"{value}"}}'


def test_serves_null_when_unset(make_client: MakeClient) -> None:
    response = make_client().get("/api/v1/donation")
    assert response.status_code == 200
    assert response.json() == {"url": None}
    assert response.headers["cache-control"] == "public, max-age=60"


def test_serves_the_environment_setting(
    monkeypatch: pytest.MonkeyPatch, make_client: MakeClient
) -> None:
    monkeypatch.setenv("DONATION_URL", PROFILE)
    assert make_client().get("/api/v1/donation").json() == {"url": PROFILE}


def test_blank_parameter_is_unset_even_with_the_environment(
    monkeypatch: pytest.MonkeyPatch, make_client: MakeClient
) -> None:
    # An explicit value (even blank) wins over the environment, like LEGAL_*.
    monkeypatch.setenv("DONATION_URL", PROFILE)
    assert make_client("").get("/api/v1/donation").json() == {"url": None}


def test_etag_and_304(make_client: MakeClient) -> None:
    client = make_client(PROFILE)
    first = client.get("/api/v1/donation")
    etag = first.headers["etag"]
    again = client.get("/api/v1/donation", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "public, max-age=60"
    assert make_client().get("/api/v1/donation").headers["etag"] != etag


def test_ignores_query_strings(make_client: MakeClient) -> None:
    client = make_client(PROFILE)
    plain = client.get("/api/v1/donation")
    with_answers = client.get("/api/v1/donation", params={"answers": "1:2", "utm_source": "x"})
    assert with_answers.status_code == 200
    assert with_answers.content == plain.content


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_only_get_is_allowed(make_client: MakeClient, method: str) -> None:
    assert getattr(make_client(PROFILE), method)("/api/v1/donation").status_code == 405


@pytest.mark.parametrize(
    "value", ["https://www.buymeacoffee.com/perfil?ref=x", "javascript:alert(1)"]
)
def test_invalid_environment_value_does_not_stop_startup(
    monkeypatch: pytest.MonkeyPatch,
    make_client: MakeClient,
    caplog: pytest.LogCaptureFixture,
    value: str,
) -> None:
    monkeypatch.setenv("DONATION_URL", value)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        client = make_client()
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/donation").json() == {"url": None}
    warnings = [r for r in caplog.records if r.name == LOGGER]
    assert [r.getMessage() for r in warnings] == [DONATION_URL_WARNING]
    assert value not in caplog.text


def test_invalid_parameter_does_not_stop_startup(make_client: MakeClient) -> None:
    client = make_client("https://www.buymeacoffee.com:443/perfil")
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/donation").json() == {"url": None}


def test_sets_no_cookie(make_client: MakeClient) -> None:
    response = make_client(PROFILE).get("/api/v1/donation")
    assert "set-cookie" not in response.headers
