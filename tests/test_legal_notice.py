"""legal-privacy-page: the ``LEGAL_*`` settings, ``GET /api/v1/legal-notice`` and no cookies.

Fictitious values only: no real name, NIF, address or email is ever written here.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from ideology_app.config import (
    ConfigError,
    LegalHolder,
    LegalNoticeSettings,
    legal_notice_settings,
    parse_legal_notice,
)
from ideology_app.main import create_app

HOLDERS = "Persona Uno;Persona Dos"
EMAIL = "contacto@ideologiapp.test"
# Fictitious NIFs with valid control letters: 0 % 23 -> T, 1 % 23 -> R.
NIF = "00000000T;00000001R"
ADDRESS = "Calle Ficticia 1, 00000 Ciudad"
VOTER_HTML = b"<!doctype html><title>IdeologiApp</title>voter"

CONFIGURED = LegalNoticeSettings(
    holders=(LegalHolder("Persona Uno", "00000000T"), LegalHolder("Persona Dos", "00000001R")),
    contact_email=EMAIL,
    address=ADDRESS,
)


# --- Parser ------------------------------------------------------------------


def test_parses_every_value_trimmed() -> None:
    parsed = parse_legal_notice(
        "  Persona Uno ; Persona Dos ", f" {EMAIL} ", " 00000000t ; 00000001R ", f"  {ADDRESS} "
    )
    assert parsed == CONFIGURED


def test_optional_values_unset() -> None:
    parsed = parse_legal_notice(HOLDERS, EMAIL)
    assert parsed.holders == (LegalHolder("Persona Uno"), LegalHolder("Persona Dos"))
    assert parsed.contact_email == EMAIL
    assert parsed.address is None


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_unset_or_blank_is_not_configured(blank: str | None) -> None:
    assert parse_legal_notice(blank, blank, blank, blank) == LegalNoticeSettings()


def test_nie_and_ten_holders_are_accepted() -> None:
    names = ";".join(f"Persona {i}" for i in range(10))
    assert len(parse_legal_notice(names, None).holders) == 10
    # NIE: X -> 0, so X0000000 checks as 0 -> T; Y0000000 as 10000000 -> 10000000 % 23.
    letter = "TRWAGMYFPDXBNJZSQVHLCKE"[10_000_000 % 23]
    parsed = parse_legal_notice("Persona Uno;Persona Dos", None, f"X0000000T;Y0000000{letter}")
    assert [h.nif for h in parsed.holders] == ["X0000000T", f"Y0000000{letter}"]


def test_a_name_of_120_code_points_is_accepted() -> None:
    name = "ñ" * 120
    assert parse_legal_notice(name, None).holders == (LegalHolder(name),)


@pytest.mark.parametrize(
    ("kwargs", "variable", "secret"),
    [
        ({"contact_email": "no-es-un-correo"}, "LEGAL_CONTACT_EMAIL", "no-es-un-correo"),
        ({"contact_email": "a b@ideologiapp.test"}, "LEGAL_CONTACT_EMAIL", "a b@"),
        ({"contact_email": "contacto@example.com"}, "LEGAL_CONTACT_EMAIL", "contacto@example"),
        ({"contact_email": "contacto@EXAMPLE.org"}, "LEGAL_CONTACT_EMAIL", "contacto@EXAMPLE"),
        ({"contact_email": "contacto@mail.example.net"}, "LEGAL_CONTACT_EMAIL", "mail.example"),
        ({"contact_email": "a" * 250 + "@x.test"}, "LEGAL_CONTACT_EMAIL", "aaaa@x.test"),
        ({"contact_email": "<contacto@ideologiapp.test>"}, "LEGAL_CONTACT_EMAIL", "contacto@"),
        ({"holders": HOLDERS, "nif": "00000000A;00000001R"}, "LEGAL_NIF", "00000000A"),
        ({"holders": HOLDERS, "nif": "0000000T;00000001R"}, "LEGAL_NIF", "0000000T"),
        ({"nif": "00000000T"}, "LEGAL_NIF", "00000000T"),
        ({"holders": HOLDERS, "nif": "00000000T"}, "LEGAL_NIF", "00000000T"),
        ({"holders": "Persona Uno", "nif": "00000000T;00000001R"}, "LEGAL_NIF", "00000001R"),
        ({"holders": "Persona <Uno>"}, "LEGAL_HOLDERS", "Persona"),
        ({"holders": "Persona\u0007Uno"}, "LEGAL_HOLDERS", "Persona"),
        ({"holders": "Persona Uno;;Persona Dos"}, "LEGAL_HOLDERS", "Persona Uno"),
        ({"holders": ";".join(f"Persona {i}" for i in range(11))}, "LEGAL_HOLDERS", "Persona 1"),
        ({"holders": "ñ" * 121}, "LEGAL_HOLDERS", "ñññ"),
        ({"address": "Calle\nFicticia"}, "LEGAL_ADDRESS", "Calle"),
        ({"address": "x" * 301}, "LEGAL_ADDRESS", "xxxx"),
    ],
)
def test_malformed_values_raise_config_error_without_the_value(
    kwargs: dict[str, str], variable: str, secret: str
) -> None:
    args: dict[str, Any] = {"holders": None, "contact_email": None, **kwargs}
    with pytest.raises(ConfigError) as info:
        parse_legal_notice(**args)
    message = str(info.value)
    assert variable in message
    assert secret not in message


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert legal_notice_settings() == LegalNoticeSettings()
    monkeypatch.setenv("LEGAL_HOLDERS", HOLDERS)
    monkeypatch.setenv("LEGAL_CONTACT_EMAIL", EMAIL)
    monkeypatch.setenv("LEGAL_NIF", NIF)
    monkeypatch.setenv("LEGAL_ADDRESS", ADDRESS)
    assert legal_notice_settings() == CONFIGURED


# --- App startup ---------------------------------------------------------------


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_bytes(VOTER_HTML)
    return root


MakeClient = Callable[..., TestClient]


@pytest.fixture
def make_client(db_url: str, tmp_path: Path, dist: Path) -> Iterator[MakeClient]:
    clients: list[TestClient] = []

    def make(legal_notice: LegalNoticeSettings | None = None) -> TestClient:
        client = TestClient(
            create_app(
                db_url,
                web_dist_dir=dist,
                feedback_database_url=f"sqlite:///{tmp_path}/fb.db",
                legal_notice=legal_notice,
            )
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LEGAL_CONTACT_EMAIL", "contacto-sin-dominio"),
        ("LEGAL_NIF", "00000000A;00000001R"),
        ("LEGAL_NIF", "00000000T"),
    ],
)
def test_malformed_environment_fails_startup(
    monkeypatch: pytest.MonkeyPatch, db_url: str, tmp_path: Path, variable: str, value: str
) -> None:
    monkeypatch.setenv("LEGAL_HOLDERS", HOLDERS)
    monkeypatch.setenv(variable, value)
    feedback = tmp_path / "fb.db"
    app = create_app(db_url, feedback_database_url=f"sqlite:///{feedback}")
    with pytest.raises(ConfigError) as info:
        with TestClient(app):
            pass
    assert variable in str(info.value)
    assert value not in str(info.value)
    # Startup stopped before the feedback store was created.
    assert not feedback.exists()


def test_nif_without_holders_fails_startup(
    monkeypatch: pytest.MonkeyPatch, db_url: str, tmp_path: Path
) -> None:
    monkeypatch.setenv("LEGAL_NIF", "00000000T")
    app = create_app(db_url, feedback_database_url=f"sqlite:///{tmp_path}/fb.db")
    with pytest.raises(ConfigError, match="LEGAL_NIF"):
        with TestClient(app):
            pass


# --- GET /api/v1/legal-notice ------------------------------------------------------


def test_serves_the_configured_notice(make_client: MakeClient) -> None:
    response = make_client(CONFIGURED).get("/api/v1/legal-notice")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.text == (
        '{"holders":[{"name":"Persona Uno","nif":"00000000T"},'
        '{"name":"Persona Dos","nif":"00000001R"}],'
        '"contact_email":"contacto@ideologiapp.test",'
        '"address":"Calle Ficticia 1, 00000 Ciudad"}'
    )


def test_serves_the_environment_settings(
    monkeypatch: pytest.MonkeyPatch, make_client: MakeClient
) -> None:
    monkeypatch.setenv("LEGAL_HOLDERS", HOLDERS)
    monkeypatch.setenv("LEGAL_CONTACT_EMAIL", EMAIL)
    body = make_client().get("/api/v1/legal-notice").json()
    assert body == {
        "holders": [{"name": "Persona Uno", "nif": None}, {"name": "Persona Dos", "nif": None}],
        "contact_email": EMAIL,
        "address": None,
    }


def test_serves_the_empty_notice_when_nothing_is_configured(make_client: MakeClient) -> None:
    response = make_client().get("/api/v1/legal-notice")
    assert response.status_code == 200
    assert response.json() == {"holders": [], "contact_email": None, "address": None}


def test_etag_and_304(make_client: MakeClient) -> None:
    client = make_client(CONFIGURED)
    first = client.get("/api/v1/legal-notice")
    etag = first.headers["etag"]
    again = client.get("/api/v1/legal-notice", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
    assert again.headers["cache-control"] == "public, max-age=60"
    # The empty notice has another ETag.
    assert make_client().get("/api/v1/legal-notice").headers["etag"] != etag


def test_ignores_query_strings(make_client: MakeClient) -> None:
    client = make_client(CONFIGURED)
    plain = client.get("/api/v1/legal-notice")
    with_answers = client.get("/api/v1/legal-notice", params={"answers": "1:2"})
    assert with_answers.content == plain.content


def test_public_routes_set_no_cookie(migrated_engine: Engine, make_client: MakeClient) -> None:
    client = make_client(CONFIGURED)
    for path in (
        "/",
        "/legal",
        "/metodologia",
        "/api/v1/elections",
        "/api/v1/legal-notice",
        "/health",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "set-cookie" not in response.headers, path
    posted = client.post("/api/v1/feedback", json={"message": "Hola", "origin": "landing"})
    assert posted.status_code == 201
    assert "set-cookie" not in posted.headers
