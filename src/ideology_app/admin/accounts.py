"""Operator accounts: the ``ADMIN_USERS`` format and scrypt password hashes (feedback-admin).

``ADMIN_USERS`` is a comma-separated list of ``username:hash`` entries, where
the hash is ``scrypt.<log2 n>.<r>.<p>.<salt>.<key>`` with a 16-byte salt and a
32-byte key in base64url without padding. The format has no ``$``, ``:`` or
``,``, so the value needs no quoting. Passwords are hashed as the UTF-8 bytes
of their NFC form. Errors never echo the value.
"""

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from ideology_app.config import ConfigError

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")

DEFAULT_LOG2_N = 15
DEFAULT_R = 8
DEFAULT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32
# hashlib's default maxmem (32 MiB) is too small for n = 2**15, r = 8.
MAXMEM = 64 * 1024 * 1024
LOG2_N_RANGE = range(14, 21)
R_RANGE = range(1, 17)
P_RANGE = range(1, 5)

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

HASH_HINT = 'create one with "ideology admin hash-password"'


@dataclass(frozen=True)
class ScryptHash:
    log2_n: int
    r: int
    p: int
    salt: bytes
    key: bytes


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _password_bytes(password: str) -> bytes:
    return unicodedata.normalize("NFC", password).encode("utf-8")


def _maxmem(log2_n: int, r: int) -> int:
    # scrypt needs about 128 * r * n bytes; leave head room for the larger accepted parameters.
    return max(MAXMEM, 256 * r * (1 << log2_n))


def _derive(password: str, parsed: ScryptHash) -> bytes:
    return hashlib.scrypt(
        _password_bytes(password),
        salt=parsed.salt,
        n=1 << parsed.log2_n,
        r=parsed.r,
        p=parsed.p,
        maxmem=_maxmem(parsed.log2_n, parsed.r),
        dklen=KEY_BYTES,
    )


def format_hash(parsed: ScryptHash) -> str:
    return ".".join(
        [
            "scrypt",
            str(parsed.log2_n),
            str(parsed.r),
            str(parsed.p),
            _b64encode(parsed.salt),
            _b64encode(parsed.key),
        ]
    )


def parse_hash(text: str) -> ScryptHash:
    """Parse ``scrypt.<log2 n>.<r>.<p>.<salt>.<key>``; ``ValueError`` if malformed or too weak."""
    parts = text.split(".")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise ValueError("not a scrypt hash")
    numbers = parts[1:4]
    if not all(re.fullmatch(r"[0-9]{1,2}", n) for n in numbers):
        raise ValueError("bad scrypt parameters")
    log2_n, r, p = (int(n) for n in numbers)
    if log2_n not in LOG2_N_RANGE or r not in R_RANGE or p not in P_RANGE:
        raise ValueError("scrypt parameters out of range")
    salt = _b64decode(parts[4])
    key = _b64decode(parts[5])
    if len(salt) != SALT_BYTES or len(key) != KEY_BYTES:
        raise ValueError("bad salt or key length")
    return ScryptHash(log2_n=log2_n, r=r, p=p, salt=salt, key=key)


def hash_password(
    password: str, *, log2_n: int = DEFAULT_LOG2_N, r: int = DEFAULT_R, p: int = DEFAULT_P
) -> str:
    """A new salted scrypt hash of ``password`` in the ``ADMIN_USERS`` format."""
    salt = secrets.token_bytes(SALT_BYTES)
    partial = ScryptHash(log2_n=log2_n, r=r, p=p, salt=salt, key=b"")
    return format_hash(
        ScryptHash(log2_n=log2_n, r=r, p=p, salt=salt, key=_derive(password, partial))
    )


def verify_password(password: str, encoded: str | ScryptHash) -> bool:
    """True when ``password`` matches; runs scrypt once and compares in constant time."""
    parsed = parse_hash(encoded) if isinstance(encoded, str) else encoded
    return hmac.compare_digest(_derive(password, parsed), parsed.key)


def is_valid_username(username: str) -> bool:
    return USERNAME_RE.fullmatch(username) is not None


def parse_admin_users(raw: str | None) -> dict[str, ScryptHash]:
    """Parse ``ADMIN_USERS``. Unset or blank -> no account. Malformed -> ``ConfigError``.

    The message names the entry number, never the value.
    """
    if raw is None or not raw.strip():
        return {}
    accounts: dict[str, ScryptHash] = {}
    for number, entry in enumerate(raw.split(","), start=1):
        entry = entry.strip()
        problem = f"ADMIN_USERS entry {number} is not <username>:<scrypt hash>; {HASH_HINT}"
        username, sep, encoded = entry.partition(":")
        if not sep or not is_valid_username(username):
            raise ConfigError(problem)
        try:
            parsed = parse_hash(encoded)
        except ValueError:
            raise ConfigError(problem) from None
        if username in accounts:
            raise ConfigError(f"ADMIN_USERS entry {number} repeats a username")
        accounts[username] = parsed
    return accounts


@lru_cache(maxsize=1)
def _dummy_hash() -> ScryptHash:
    """Made once per process with the default parameters, for unknown usernames."""
    return parse_hash(hash_password(secrets.token_urlsafe(16)))


def authenticate(accounts: Mapping[str, ScryptHash], username: str, password: str) -> str | None:
    """The username when the credentials match, else ``None``.

    Compares ``username`` with every account (no early exit), then runs exactly
    one scrypt verification: against the matched hash, or against a dummy hash
    when the username is unknown, so both failures take the same path.
    """
    given = username.encode("utf-8")
    matched: str | None = None
    for name in accounts:
        if hmac.compare_digest(name.encode("utf-8"), given):
            matched = name
    target = accounts[matched] if matched is not None else _dummy_hash()
    ok = verify_password(password, target)
    return matched if ok and matched is not None else None


__all__ = [
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "ScryptHash",
    "authenticate",
    "hash_password",
    "is_valid_username",
    "parse_admin_users",
    "parse_hash",
    "verify_password",
]
