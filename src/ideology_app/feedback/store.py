"""The anonymous Voter feedback store (feedback-api).

A database of its own (``FEEDBACK_DATABASE_URL``), never the shared
``data/ideology.db`` nor the ``DATABASE_URL`` database. Its one table lives on
``FEEDBACK_METADATA``, not on ``models.Base.metadata``, so the shared-DB
migrations and ``alembic check`` never see it. Its schema changes only through
its own Alembic environment (``ideology_app.feedback:migrations``, version
table ``feedback_alembic_version``), applied by ``upgrade_schema`` when the app
starts and by ``ideology feedback upgrade`` (feedback-admin).

Stored per message: a surrogate id, the text, the origin screen and the UTC
time in whole seconds, plus the Operator's ``reviewed_at`` mark (Operator
data, not Voter data). Nothing else (no IP, user agent, cookie, Election,
Dataset Version, answers or honeypot value).

Depends only on ``config``, ``db.make_engine``, ``shared_db``, SQLAlchemy and
Alembic; never on ``models``.
"""

import datetime as dt
import os
from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, event
from sqlalchemy.engine import Connection, make_url

from ideology_app import config, shared_db
from ideology_app.db import make_engine

Origin = Literal["landing", "results"]
ORIGINS: tuple[Origin, ...] = ("landing", "results")

FEEDBACK_METADATA = sa.MetaData()

feedback_messages = sa.Table(
    "feedback_messages",
    FEEDBACK_METADATA,
    # A row counter, not Voter data.
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("message", sa.Text, nullable=False),
    sa.Column(
        "origin",
        sa.Enum(*ORIGINS, name="feedback_origin", native_enum=False, create_constraint=True),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    # The Operator's reviewed mark (feedback-admin, revision f0002); never Voter data.
    sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
)

SCRIPT_LOCATION = "ideology_app.feedback:migrations"
VERSION_TABLE = "feedback_alembic_version"
BASELINE_REVISION = "f0001"

Reviewed = Literal["all", "yes", "no"]

_EXAMPLE = f"use e.g. {config.DEFAULT_FEEDBACK_DATABASE_URL}"


class FeedbackStoreError(config.ConfigError):
    """``FEEDBACK_DATABASE_URL`` points at a database the feedback store must not use."""


@dataclass(frozen=True)
class FeedbackMessage:
    id: int
    message: str
    origin: str
    created_at: dt.datetime
    # UTC, whole seconds; ``None`` while unreviewed.
    reviewed_at: dt.datetime | None = None


def _not_own(target: str) -> FeedbackStoreError:
    return FeedbackStoreError(
        f"FEEDBACK_DATABASE_URL must point at its own database, not at {target}; {_EXAMPLE}"
    )


def _rendered(url: str) -> str | None:
    try:
        return make_url(url).render_as_string(hide_password=False)
    except Exception:  # unparsable: compared as never equal
        return None


def _same_file(a: os.PathLike[str], b: os.PathLike[str]) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:  # at least one of them does not exist
        return False


def check_separate(feedback_url: str, database_url: str) -> None:
    """Raise ``FeedbackStoreError`` unless ``feedback_url`` is a database of its own.

    Refused: the shared database (symlinks and hard links followed), the same
    file as ``database_url``, the same non-SQLite URL as ``database_url``, an
    in-memory SQLite database, and an unparsable URL. The message names the
    variable, never the URL or its password.
    """
    try:
        parsed = make_url(feedback_url)
    except Exception:
        raise FeedbackStoreError(
            f"FEEDBACK_DATABASE_URL is not a valid database URL; {_EXAMPLE}"
        ) from None
    feedback_path = shared_db.sqlite_path(feedback_url)
    if parsed.get_backend_name() == "sqlite" and feedback_path is None:
        raise FeedbackStoreError(
            f"FEEDBACK_DATABASE_URL must not be an in-memory database; {_EXAMPLE}"
        )
    shared = config.SHARED_DATABASE_PATH
    if shared_db.is_shared(feedback_url) or (
        feedback_path is not None and _same_file(feedback_path, shared)
    ):
        raise _not_own(str(shared))
    database_path = shared_db.sqlite_path(database_url)
    if feedback_path is not None and database_path is not None:
        if feedback_path.resolve() == database_path.resolve() or _same_file(
            feedback_path, database_path
        ):
            raise _not_own("the DATABASE_URL database")
        return
    rendered = _rendered(feedback_url)
    if rendered is not None and rendered == _rendered(database_url):
        raise _not_own("the DATABASE_URL database")


def _enable_secure_delete(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA secure_delete=ON")
    cursor.close()


def make_feedback_engine(url: str) -> Engine:
    """``db.make_engine`` plus, on SQLite, ``PRAGMA secure_delete=ON``.

    A deleted message's text is then overwritten in the file. PostgreSQL keeps
    dead tuples until VACUUM (see docs/risks-and-open-questions.md).
    """
    engine = make_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_secure_delete)
    return engine


def _alembic_config(connection: Connection | None = None, url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    if url is not None:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str | None:
    """The newest feedback-store revision (``f0002``)."""
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    """The revision in ``feedback_alembic_version``, or ``None``."""
    with engine.connect() as connection:
        return MigrationContext.configure(
            connection, opts={"version_table": VERSION_TABLE}
        ).get_current_revision()


def is_at_head(engine: Engine) -> bool:
    """True when the store is at the newest feedback-store revision."""
    return current_revision(engine) == head_revision()


def upgrade_schema(engine: Engine) -> None:
    """Bring the feedback store to the newest revision, keeping every message.

    In one connection: a store made before feedback-admin (``feedback_messages``
    without ``feedback_alembic_version``) is first stamped at ``f0001``; then
    ``upgrade head`` runs. A second call is a no-op.
    """
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        cfg = _alembic_config(connection=connection)
        if inspector.has_table(feedback_messages.name) and not inspector.has_table(VERSION_TABLE):
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")


def has_schema(engine: Engine) -> bool:
    """True when the database has the feedback table."""
    return sa.inspect(engine).has_table(feedback_messages.name)


def _utc_seconds(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        raise ValueError("feedback times must be timezone-aware")
    return moment.astimezone(dt.UTC).replace(microsecond=0)


def add_message(engine: Engine, message: str, origin: str, now: dt.datetime) -> None:
    """Store one message; ``now`` is kept in UTC, truncated to whole seconds."""
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {', '.join(ORIGINS)}")
    with engine.begin() as connection:
        connection.execute(
            feedback_messages.insert().values(
                message=message, origin=origin, created_at=_utc_seconds(now)
            )
        )


def _as_utc(value: dt.datetime) -> dt.datetime:
    # SQLite returns naive values; every stored value is UTC.
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _to_message(row: Any) -> FeedbackMessage:
    return FeedbackMessage(
        id=row.id,
        message=row.message,
        origin=row.origin,
        created_at=_as_utc(row.created_at),
        reviewed_at=_as_utc(row.reviewed_at) if row.reviewed_at is not None else None,
    )


def list_messages(engine: Engine, since: dt.datetime | None = None) -> list[FeedbackMessage]:
    """Messages with ``created_at >= since`` (all if ``None``), oldest first."""
    query = sa.select(feedback_messages).order_by(
        feedback_messages.c.created_at, feedback_messages.c.id
    )
    if since is not None:
        query = query.where(feedback_messages.c.created_at >= _utc_seconds(since))
    with engine.connect() as connection:
        rows = connection.execute(query).all()
    return [_to_message(row) for row in rows]


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)


def list_for_admin(
    engine: Engine,
    *,
    from_day: dt.date | None = None,
    to_day: dt.date | None = None,
    reviewed: Reviewed = "all",
    before_id: int | None = None,
    limit: int = 50,
) -> list[FeedbackMessage]:
    """At most ``limit`` messages, newest first (``id DESC``), for the admin page.

    ``from_day`` / ``to_day`` are inclusive UTC days; ``reviewed`` keeps all,
    only reviewed (``yes``) or only unreviewed (``no``) messages; ``before_id``
    pages on from the last id of the previous page.
    """
    table = feedback_messages
    query = sa.select(table).order_by(table.c.id.desc()).limit(limit)
    if from_day is not None:
        query = query.where(table.c.created_at >= _day_start(from_day))
    if to_day is not None:
        query = query.where(table.c.created_at < _day_start(to_day + dt.timedelta(days=1)))
    if reviewed == "yes":
        query = query.where(table.c.reviewed_at.is_not(None))
    elif reviewed == "no":
        query = query.where(table.c.reviewed_at.is_(None))
    if before_id is not None:
        query = query.where(table.c.id < before_id)
    with engine.connect() as connection:
        rows = connection.execute(query).all()
    return [_to_message(row) for row in rows]


def _get(connection: Connection, message_id: int) -> FeedbackMessage | None:
    row = connection.execute(
        sa.select(feedback_messages).where(feedback_messages.c.id == message_id)
    ).first()
    return _to_message(row) if row is not None else None


def mark_reviewed(engine: Engine, message_id: int, now: dt.datetime) -> FeedbackMessage | None:
    """Set ``reviewed_at`` to ``now`` (UTC, whole seconds) unless already set; ``None`` if unknown."""
    with engine.begin() as connection:
        connection.execute(
            feedback_messages.update()
            .where(feedback_messages.c.id == message_id, feedback_messages.c.reviewed_at.is_(None))
            .values(reviewed_at=_utc_seconds(now))
        )
        return _get(connection, message_id)


def clear_reviewed(engine: Engine, message_id: int) -> FeedbackMessage | None:
    """Clear ``reviewed_at``; ``None`` if the message does not exist."""
    with engine.begin() as connection:
        connection.execute(
            feedback_messages.update()
            .where(feedback_messages.c.id == message_id)
            .values(reviewed_at=None)
        )
        return _get(connection, message_id)


def delete_message(engine: Engine, message_id: int) -> bool:
    """Hard-delete one message; ``False`` if it does not exist."""
    with engine.begin() as connection:
        result = connection.execute(
            feedback_messages.delete().where(feedback_messages.c.id == message_id)
        )
        return result.rowcount == 1


__all__ = [
    "BASELINE_REVISION",
    "FEEDBACK_METADATA",
    "ORIGINS",
    "SCRIPT_LOCATION",
    "VERSION_TABLE",
    "FeedbackMessage",
    "FeedbackStoreError",
    "Origin",
    "Reviewed",
    "add_message",
    "check_separate",
    "clear_reviewed",
    "current_revision",
    "delete_message",
    "feedback_messages",
    "has_schema",
    "head_revision",
    "is_at_head",
    "list_for_admin",
    "list_messages",
    "make_feedback_engine",
    "mark_reviewed",
    "upgrade_schema",
]
