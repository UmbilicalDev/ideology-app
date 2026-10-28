"""The anonymous Voter feedback store (feedback-api).

A database of its own (``FEEDBACK_DATABASE_URL``), never the shared
``data/ideology.db`` nor the ``DATABASE_URL`` database. Its one table lives on
``FEEDBACK_METADATA``, not on ``models.Base.metadata``, so the shared-DB
migrations and ``alembic check`` never see it; ``create_schema`` creates it
with ``create_all`` when the app starts. The first change to this schema must
add its own Alembic environment that stamps the existing table.

Stored per message: a surrogate id, the text, the origin screen and the UTC
time in whole seconds. Nothing else (no IP, user agent, cookie, Election,
Dataset Version, answers or honeypot value).

Depends only on ``config``, ``shared_db`` and SQLAlchemy; never on ``models``.
"""

import datetime as dt
import os
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from ideology_app import config, shared_db

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
)

_EXAMPLE = f"use e.g. {config.DEFAULT_FEEDBACK_DATABASE_URL}"


class FeedbackStoreError(config.ConfigError):
    """``FEEDBACK_DATABASE_URL`` points at a database the feedback store must not use."""


@dataclass(frozen=True)
class FeedbackMessage:
    id: int
    message: str
    origin: str
    created_at: dt.datetime


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


def create_schema(engine: Engine) -> None:
    """Create the feedback table if it does not exist (``create_all``, checkfirst)."""
    FEEDBACK_METADATA.create_all(engine)


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


def list_messages(engine: Engine, since: dt.datetime | None = None) -> list[FeedbackMessage]:
    """Messages with ``created_at >= since`` (all if ``None``), oldest first."""
    query = sa.select(feedback_messages).order_by(
        feedback_messages.c.created_at, feedback_messages.c.id
    )
    if since is not None:
        query = query.where(feedback_messages.c.created_at >= _utc_seconds(since))
    with engine.connect() as connection:
        rows = connection.execute(query).all()
    return [
        FeedbackMessage(
            id=row.id,
            message=row.message,
            origin=row.origin,
            # SQLite returns naive values; every stored value is UTC.
            created_at=(
                row.created_at.replace(tzinfo=dt.UTC)
                if row.created_at.tzinfo is None
                else row.created_at.astimezone(dt.UTC)
            ),
        )
        for row in rows
    ]


__all__ = [
    "FEEDBACK_METADATA",
    "ORIGINS",
    "FeedbackMessage",
    "FeedbackStoreError",
    "Origin",
    "add_message",
    "check_separate",
    "create_schema",
    "feedback_messages",
    "has_schema",
    "list_messages",
]
