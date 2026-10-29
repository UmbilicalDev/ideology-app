"""Feedback stores as feedback-api made them, before feedback-admin (no migrations).

``make_legacy_store`` builds the pre-feature table from a private copy of its
old definition (``create_all``, no version table), so upgrade tests start from
exactly what an existing ``feedback.db`` holds. ``seed_legacy_store`` fills one
with varied messages for the browser walk.
"""

import datetime as dt
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

# A private copy of the feedback-api table: never import the current one here.
_LEGACY_METADATA = sa.MetaData()
_legacy_messages = sa.Table(
    "feedback_messages",
    _LEGACY_METADATA,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("message", sa.Text, nullable=False),
    sa.Column(
        "origin",
        sa.Enum("landing", "results", name="feedback_origin", native_enum=False, create_constraint=True),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

LegacyMessage = tuple[str, str, dt.datetime]


def make_legacy_store(path: str | Path, messages: Sequence[LegacyMessage]) -> None:
    """A SQLite feedback store at ``path`` with the pre-feature table and ``messages``.

    Each message is ``(text, origin, created_at)``; ``created_at`` must be UTC.
    """
    engine = sa.create_engine(f"sqlite:///{path}")
    try:
        _LEGACY_METADATA.create_all(engine)
        with engine.begin() as connection:
            for text, origin, created_at in messages:
                connection.execute(
                    _legacy_messages.insert().values(
                        message=text,
                        origin=origin,
                        created_at=created_at.astimezone(dt.UTC).replace(microsecond=0),
                    )
                )
    finally:
        engine.dispose()


_SAMPLES = (
    "Me ha parecido muy útil, gracias.",
    "Echo en falta afirmaciones sobre vivienda.\nY también sobre transporte público.",
    "La afirmación 7 es confusa: <b>no entiendo</b> qué se pregunta.",
    "¡Genial! 👍🏽 Lo he compartido con mi familia.",
    "Primera línea.\nSegunda línea.\n\nCuarta línea tras una vacía.",
    "Un mensaje largo para comprobar el ajuste de línea: "
    "palabrasmuylargassinespaciosquedebenpartirseparanodesbordarlatarjetaenmovil "
    "y después texto normal.",
)


def seed_legacy_store(path: str | Path, count: int = 60) -> None:
    """A legacy store with ``count`` messages spread over 10 days, both origins, ending today (UTC)."""
    end = dt.datetime.now(dt.UTC).replace(hour=20, minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=9, hours=12)
    step = (end - start) / max(count - 1, 1)
    messages = [
        (
            f"{_SAMPLES[i % len(_SAMPLES)]} (mensaje {i + 1})",
            "landing" if i % 3 else "results",
            start + step * i,
        )
        for i in range(count)
    ]
    make_legacy_store(path, messages)
