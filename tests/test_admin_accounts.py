"""feedback-admin Decisions 1 and 3: the ADMIN_USERS format, scrypt hashes and authenticate.

Throwaway passwords and hashes made in the test only; never a real account.
"""

import hashlib
import unicodedata
from typing import Any

import pytest

from ideology_app.admin import accounts
from ideology_app.admin.accounts import (
    authenticate,
    hash_password,
    parse_admin_users,
    parse_hash,
    verify_password,
)
from ideology_app.config import ConfigError

PASSWORD = "contraseña-de-prueba"


@pytest.fixture(scope="module")
def prueba_hash() -> str:
    return hash_password(PASSWORD, log2_n=14)


def test_hash_format_and_defaults() -> None:
    encoded = hash_password(PASSWORD)
    parts = encoded.split(".")
    assert parts[:4] == ["scrypt", "15", "8", "1"]
    assert len(parts) == 6
    for forbidden in ("$", ":", ",", "="):
        assert forbidden not in encoded
    parsed = parse_hash(encoded)
    assert len(parsed.salt) == 16 and len(parsed.key) == 32
    assert verify_password(PASSWORD, encoded)
    assert not verify_password(PASSWORD + "x", encoded)
    # A new salt every time.
    assert hash_password(PASSWORD, log2_n=14) != hash_password(PASSWORD, log2_n=14)


def test_password_is_hashed_in_nfc() -> None:
    composed = "contraseña-ñandú"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    encoded = hash_password(decomposed, log2_n=14)
    assert verify_password(composed, encoded)


def test_hash_matches_hashlib_scrypt_directly() -> None:
    encoded = hash_password(PASSWORD, log2_n=14, r=8, p=1)
    parsed = parse_hash(encoded)
    expected = hashlib.scrypt(
        PASSWORD.encode(), salt=parsed.salt, n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32
    )
    assert parsed.key == expected


@pytest.mark.parametrize(
    "params",
    [
        "13.8.1",  # n too small
        "21.8.1",  # n too large
        "15.0.1",
        "15.17.1",
        "15.8.0",
        "15.8.5",
        "15.x.1",
    ],
)
def test_weak_or_bad_parameters_are_refused(params: str, prueba_hash: str) -> None:
    salt_key = ".".join(prueba_hash.split(".")[4:])
    with pytest.raises(ValueError):
        parse_hash(f"scrypt.{params}.{salt_key}")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "bcrypt.15.8.1.a.b",
        "scrypt.15.8.1.short.key",
        "scrypt.15.8.1",
        "scrypt.15.8.1.AAAAAAAAAAAAAAAAAAAAAA.AAAA=",
    ],
)
def test_malformed_hashes_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_hash(bad)


def test_parse_admin_users(prueba_hash: str) -> None:
    other = hash_password("otra-contraseña-larga", log2_n=14)
    assert parse_admin_users(None) == {}
    assert parse_admin_users("   ") == {}
    parsed = parse_admin_users(f"  prueba:{prueba_hash} , otra.cuenta_1-x:{other}  ")
    assert list(parsed) == ["prueba", "otra.cuenta_1-x"]
    assert verify_password(PASSWORD, parsed["prueba"])


@pytest.mark.parametrize(
    "template",
    [
        "prueba:not-a-hash",  # bad hash
        "Prueba:{h}",  # upper case
        "-prueba:{h}",  # leading punctuation
        "a" * 33 + ":{h}",  # too long
        "prueba{h}",  # no colon
        "prueba:{h},prueba:{h}",  # duplicate
        "prueba:{h},",  # empty entry
        "prueba:{h},,otra:{h}",
    ],
)
def test_malformed_admin_users_is_a_config_error_without_the_value(
    template: str, prueba_hash: str
) -> None:
    raw = template.format(h=prueba_hash)
    with pytest.raises(ConfigError) as info:
        parse_admin_users(raw)
    message = str(info.value)
    assert message.startswith("ADMIN_USERS entry ")
    assert prueba_hash not in message
    assert "prueba" not in message.lower().replace("admin_users", "")
    assert "not-a-hash" not in message


def test_error_names_the_entry_and_the_command(prueba_hash: str) -> None:
    with pytest.raises(ConfigError) as info:
        parse_admin_users(f"prueba:{prueba_hash},otra:bad")
    assert str(info.value) == (
        'ADMIN_USERS entry 2 is not <username>:<scrypt hash>; '
        'create one with "ideology admin hash-password"'
    )


# --- Scenario 2: authenticate takes the same path for both failures ----------


@pytest.fixture
def verify_spy(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    accounts._dummy_hash()  # made once per process, before counting
    calls: list[Any] = []
    real = accounts.verify_password

    def spy(password: str, encoded: Any) -> bool:
        calls.append(encoded)
        return real(password, encoded)

    monkeypatch.setattr(accounts, "verify_password", spy)
    return calls


@pytest.fixture
def scrypt_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    accounts._dummy_hash()
    calls: list[int] = []
    real = hashlib.scrypt

    def spy(*args: Any, **kwargs: Any) -> bytes:
        calls.append(kwargs["n"])
        return real(*args, **kwargs)

    monkeypatch.setattr(accounts.hashlib, "scrypt", spy)
    return calls


def test_authenticate_success_and_failures(
    prueba_hash: str, verify_spy: list[Any], scrypt_spy: list[int]
) -> None:
    users = parse_admin_users(f"prueba:{prueba_hash}")
    assert authenticate(users, "prueba", PASSWORD) == "prueba"
    assert len(verify_spy) == 1 and len(scrypt_spy) == 1
    assert authenticate(users, "prueba", "contraseña-mala") is None
    assert len(verify_spy) == 2 and len(scrypt_spy) == 2
    assert authenticate(users, "nadie", PASSWORD) is None
    assert len(verify_spy) == 3 and len(scrypt_spy) == 3
    # The unknown user is checked against the dummy hash with the default parameters.
    assert verify_spy[2] is accounts._dummy_hash()
    assert scrypt_spy[2] == 2**15


def test_authenticate_with_no_accounts_still_runs_one_verification(
    verify_spy: list[Any],
) -> None:
    assert authenticate({}, "prueba", PASSWORD) is None
    assert len(verify_spy) == 1


def test_authenticate_compares_every_username(
    prueba_hash: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    users = parse_admin_users(f"prueba:{prueba_hash},otra:{prueba_hash},tercera:{prueba_hash}")
    compared: list[bytes] = []
    real = accounts.hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        compared.append(a)
        return real(a, b)

    monkeypatch.setattr(accounts.hmac, "compare_digest", spy)
    authenticate(users, "prueba", PASSWORD)
    # Three usernames (no early exit) plus the key comparison.
    assert compared[:3] == [b"prueba", b"otra", b"tercera"]
    assert len(compared) == 4
