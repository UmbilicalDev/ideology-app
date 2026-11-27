"""Fixed timestamps and the logical dump hash of a dev database (dev-dataset, D3).

``normalise_timestamps`` sets every non-NULL ``DateTime`` column of the main
schema to ``SEED_INSTANT``: they are wall-clock audit fields, not AI output,
and nothing orders by them. ``dump_sha256`` hashes ``sqlite3``'s ``iterdump``
lines joined with ``\\n``, each ``CREATE TABLE`` in canonical form
(``canonical_statement``).

Why canonical: migration ``0003`` recreates ``source_documents`` with Alembic's
batch mode, which writes that table's constraints in an order that follows
in-process object addresses; the same code gives a different order for a
different database path length or after other work in the process. The
schema is the same, only the text differs, so the hash sorts the element
lines of each ``CREATE TABLE`` body. Data rows are hashed exactly as dumped.
"""

import datetime as dt
import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import quote

import sqlalchemy as sa
from sqlalchemy import Engine

from ideology_app.models import Base

SEED_INSTANT = dt.datetime(2031, 5, 1, 10, 0, tzinfo=dt.UTC)


def normalise_timestamps(engine: Engine) -> int:
    """Set every non-NULL ``DateTime`` value to ``SEED_INSTANT``; return the rows touched."""
    touched = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            for column in table.columns:
                if isinstance(column.type, sa.DateTime):
                    result = conn.execute(
                        sa.update(table).where(column.is_not(None)).values({column.name: SEED_INSTANT})
                    )
                    touched += result.rowcount or 0
    return touched


def canonical_statement(statement: str) -> str:
    """A ``CREATE TABLE`` statement with its column and constraint lines sorted;
    any other statement unchanged."""
    if not statement.startswith("CREATE TABLE"):
        return statement
    lines = statement.split("\n")
    if len(lines) < 3 or lines[-1] not in (")", ");"):
        return statement
    elements = sorted(line.strip().rstrip(",").strip() for line in lines[1:-1])
    return "\n".join([lines[0], *(f"\t{line}" for line in elements), lines[-1]])


def dump_sha256(path: Path) -> str:
    """SHA-256 of the logical dump of the SQLite file at ``path`` (opened read-only)."""
    uri = f"file:{quote(str(Path(path).resolve()))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        dump = "\n".join(canonical_statement(line) for line in conn.iterdump())
    finally:
        conn.close()
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


__all__ = ["SEED_INSTANT", "canonical_statement", "dump_sha256", "normalise_timestamps"]
