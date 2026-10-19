"""Engine, session and migration helpers.

Callers own every Engine they create and must call ``engine.dispose()``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from ideology_app.config import database_url


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def make_engine(url: str | None = None) -> Engine:
    """Create an Engine; SQLite connections get ``PRAGMA foreign_keys=ON``."""
    engine = create_engine(url or database_url())
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a Session that commits on success and rolls back on error."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


SCRIPT_LOCATION = "ideology_app:migrations"


def alembic_config(url: str | None = None, **kwargs: Any) -> Config:
    """Build an Alembic Config in code that points at the package migrations."""
    cfg = Config(**kwargs)
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    # ConfigParser interpolation treats '%' specially (e.g. URL-encoded passwords).
    cfg.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    return cfg


def run_migrations(url: str | None = None, revision: str = "head") -> None:
    """Upgrade the database at ``url`` to ``revision``."""
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str | None, revision: str) -> None:
    """Downgrade the database at ``url`` to ``revision``."""
    command.downgrade(alembic_config(url), revision)


def is_initialised(engine: Engine) -> bool:
    """True when the database is at the newest migration (the script head)."""
    script_config = Config()
    script_config.set_main_option("script_location", SCRIPT_LOCATION)
    head = ScriptDirectory.from_config(script_config).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current is not None and current == head
