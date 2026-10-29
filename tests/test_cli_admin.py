"""feedback-admin Decision 2 and Scenario 10: ``ideology admin hash-password``.

Throwaway passwords only. The command opens no database.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from ideology_app.admin.accounts import parse_admin_users, verify_password
from ideology_app.cli import main

PASSWORD = "contraseña-de-prueba"


def run(*args: str, input: str) -> Result:
    return CliRunner().invoke(main, list(args), input=input)


def test_prints_one_hash_that_verifies(tmp_path: Path) -> None:
    result = run("admin", "hash-password", input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("scrypt.15.8.1.")
    assert verify_password(PASSWORD, lines[0])
    assert PASSWORD not in result.output
    # No database file was opened or created.
    assert list(tmp_path.iterdir()) == []


def test_username_prints_an_admin_users_entry() -> None:
    result = run("admin", "hash-password", "--username", "prueba", input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 0, result.output
    (entry,) = result.stdout.splitlines()
    assert entry.startswith("prueba:scrypt.")
    accounts = parse_admin_users(entry)
    assert verify_password(PASSWORD, accounts["prueba"])


def test_short_password_is_refused() -> None:
    result = run("admin", "hash-password", input="pw\npw\n")
    assert result.exit_code == 1
    assert "12 to 1024 characters" in result.output
    assert "scrypt." not in result.stdout


def test_long_password_is_refused() -> None:
    long = "a" * 1025
    result = run("admin", "hash-password", input=f"{long}\n{long}\n")
    assert result.exit_code == 1


def test_length_counts_code_points() -> None:
    twelve = "ñ" * 12  # 24 UTF-8 bytes, 12 code points
    result = run("admin", "hash-password", input=f"{twelve}\n{twelve}\n")
    assert result.exit_code == 0, result.output
    assert verify_password(twelve, result.stdout.strip())


def test_mismatch_asks_again() -> None:
    result = run(
        "admin",
        "hash-password",
        input=f"{PASSWORD}\notra-contraseña\n{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert "do not match" in result.output.lower() or "don't match" in result.output.lower()
    assert verify_password(PASSWORD, result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name", ["Miguel", "-x", "a b", "x" * 33, ""])
def test_invalid_username_is_a_usage_error(name: str) -> None:
    result = run("admin", "hash-password", "--username", name, input=f"{PASSWORD}\n{PASSWORD}\n")
    assert result.exit_code == 2
    assert "scrypt." not in result.output
