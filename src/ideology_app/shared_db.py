"""The shared database: one SQLite file committed at ``data/ideology.db`` (shared-database).

Every developer opens the same file, so run ids, Dataset Version ids and
recorded LLM calls agree on every machine. This module only recognises that
file and checks it is safe to commit; it never invokes git and never writes.

Depends only on ``config`` and SQLAlchemy's URL parser.
"""

from pathlib import Path
from urllib.parse import quote, unquote

from sqlalchemy.engine import make_url

from ideology_app import config

# SQLite's rollback journal and WAL files. One next to the DB means a writer
# is active or crashed mid-write, so the file alone is not complete.
SIDECARS = ("-journal", "-wal", "-shm")

_SQLITE_MAGIC = b"SQLite format 3\x00"
_HEADER_SIZE = 100
# Header bytes 18 and 19 (file format write / read version): 1 = rollback
# journal (``delete`` and the other non-WAL modes), 2 = WAL.
_ROLLBACK_JOURNAL = 1

MISSING_SHARED = (
    "no database at {path}; pull it, or build it with \"ideology db upgrade\" "
    "and \"ideology data import <bundle dir>\""
)


def sqlite_path(url: str) -> Path | None:
    """The file of a SQLite URL, or ``None`` (another backend, in-memory, or unparsable)."""
    try:
        parsed = make_url(url)
    except Exception:  # an unparsable URL is reported by SQLAlchemy elsewhere
        return None
    if parsed.get_backend_name() != "sqlite":
        return None
    database = parsed.database
    if not database or database == ":memory:":
        return None
    if str(parsed.query.get("uri", "")).lower() == "true" and database.startswith("file:"):
        database = unquote(database.removeprefix("file:").split("?", 1)[0])
        if not database or database == ":memory:" or "mode=memory" in str(parsed.query):
            return None
    return Path(database)


def is_shared(url: str) -> bool:
    """True when ``url`` is SQLite and its file resolves to ``config.SHARED_DATABASE_PATH``."""
    path = sqlite_path(url)
    if path is None:
        return False
    return path.resolve() == config.SHARED_DATABASE_PATH.resolve()


def sidecar_paths(path: Path) -> list[Path]:
    """The journal / WAL files of ``path`` that exist."""
    return [
        candidate
        for candidate in (path.with_name(path.name + suffix) for suffix in SIDECARS)
        if candidate.exists()
    ]


def file_checks(path: Path) -> list[str]:
    """Problems found without opening the database: sidecars, then the header's journal mode.

    Read-only: it only lists the directory and reads the first 100 bytes.
    """
    problems = [
        f"{sidecar.name} exists: a writer is active or crashed mid-write; stop every "
        "ideology process, then run any read command once so SQLite rolls back"
        for sidecar in sidecar_paths(path)
    ]
    with path.open("rb") as handle:
        header = handle.read(_HEADER_SIZE)
    if len(header) < _HEADER_SIZE or not header.startswith(_SQLITE_MAGIC):
        problems.append(f"{path} is not a SQLite database")
        return problems
    if header[18] != _ROLLBACK_JOURNAL or header[19] != _ROLLBACK_JOURNAL:
        problems.append(
            f"journal mode is not delete (header bytes 18-19 are {header[18]}, {header[19]}); "
            "the committed database must use the rollback journal"
        )
    return problems


def read_only_url(path: Path) -> str:
    """A SQLAlchemy URL that opens ``path`` read-only (``mode=ro``): no write, no file created."""
    # Quoted twice: SQLAlchemy decodes the URL once, then SQLite decodes the
    # ``file:`` URI, so a space, ``#`` or ``?`` in the path survives both.
    return f"sqlite:///file:{quote(quote(str(Path(path).resolve())))}?mode=ro&uri=true"


__all__ = [
    "MISSING_SHARED",
    "SIDECARS",
    "file_checks",
    "is_shared",
    "read_only_url",
    "sidecar_paths",
    "sqlite_path",
]
