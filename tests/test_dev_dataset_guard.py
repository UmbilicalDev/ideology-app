"""dev-dataset S4: ``ideology dev seed`` refuses the shared database and production settings.

Every refusal exits 1 with an ``Error:`` line naming the rule and writes
nothing: the tmp cwd's listing and hashes are equal before and after. The
repository's real ``data/ideology.db`` keeps its hash.
"""

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from dev_dataset_fixtures import sha256, snapshot
from pipeline_fixtures import offline_guard

from ideology_app.cli import main
from ideology_app.dev_dataset import content

REPO_SHARED = Path(__file__).resolve().parents[1] / "data" / "ideology.db"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    """A tmp cwd holding ``data/ideology.db`` (a small SQLite file)."""
    path = tmp_path / "data" / "ideology.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE elections (id INTEGER)")
    conn.close()
    return path


def _refused(tmp_path: Path, args: list[str], rule: str, env: dict[str, str] | None = None) -> str:
    before = snapshot(tmp_path)
    result = CliRunner().invoke(main, [*args, "dev", "seed"], env=env)
    assert result.exit_code == 1, result.output
    assert result.output.startswith("Error: "), result.output
    assert f"rule {rule}" in result.output, result.output
    assert snapshot(tmp_path) == before
    return result.output


def test_refuses_the_shared_database(tmp_path: Path, shared: Path) -> None:
    output = _refused(tmp_path, ["--database-url", "sqlite:///data/ideology.db"], "b")
    assert "unset DATABASE_URL" in output


def test_refuses_the_shared_database_from_the_environment(tmp_path: Path, shared: Path) -> None:
    _refused(tmp_path, [], "b", env={"DATABASE_URL": "sqlite:///data/ideology.db"})


def test_refuses_a_symlink_and_a_hard_link(tmp_path: Path, shared: Path) -> None:
    (tmp_path / "data" / "link.db").symlink_to(shared)
    os.link(shared, tmp_path / "data" / "hard.db")
    _refused(tmp_path, ["--database-url", "sqlite:///data/link.db"], "b")
    _refused(tmp_path, ["--database-url", "sqlite:///data/hard.db"], "b")


def test_refuses_any_ideology_db(tmp_path: Path) -> None:
    _refused(tmp_path, ["--database-url", f"sqlite:///{tmp_path}/somewhere/ideology.db"], "c")
    # The production container's URL.
    _refused(tmp_path, ["--database-url", "sqlite:////app/data/ideology.db"], "c")


def test_refuses_the_real_shared_database_by_absolute_path(tmp_path: Path) -> None:
    if not REPO_SHARED.is_file():
        pytest.skip("no committed data/ideology.db in this checkout")
    before = sha256(REPO_SHARED)
    _refused(tmp_path, ["--database-url", f"sqlite:///{REPO_SHARED}"], "c")
    assert sha256(REPO_SHARED) == before


@pytest.mark.parametrize("url", ["postgresql://u@h/db", "sqlite://", "sqlite:///:memory:", "::"])
def test_refuses_non_sqlite_file_urls(tmp_path: Path, url: str) -> None:
    output = _refused(tmp_path, ["--database-url", url], "a")
    assert "the dev dataset is built only in a SQLite file" in output


def test_refuses_an_existing_database_that_is_not_a_dev_seed(tmp_path: Path) -> None:
    path = tmp_path / "data" / "dev" / "dev.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE elections (country, type, date, name)")
        conn.execute("INSERT INTO elections VALUES ('ES', 'general', '2023-07-23', 'Real')")
    conn.close()
    _refused(tmp_path, [], "d")
    path.write_bytes(b"")
    _refused(tmp_path, [], "d")
    path.write_bytes(b"not a database at all")
    _refused(tmp_path, [], "d")


def test_refuses_a_foreign_bundle_directory(tmp_path: Path) -> None:
    root = tmp_path / "data" / "dev" / "dev-bundle"
    (root / "es-general-2023-07-23").mkdir(parents=True)
    _refused(tmp_path, [], "e")
    shutil.rmtree(root / "es-general-2023-07-23")
    (root / "notes.txt").write_text("x")
    _refused(tmp_path, [], "e")
    (root / "notes.txt").unlink()
    (root / content.SLUG).write_text("a file, not a bundle")
    _refused(tmp_path, [], "e")


def test_refuses_a_bundle_directory_that_is_a_link(tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "data" / "dev").mkdir(parents=True)
    (tmp_path / "data" / "dev" / "dev-bundle").symlink_to(tmp_path / "elsewhere")
    _refused(tmp_path, [], "e")
