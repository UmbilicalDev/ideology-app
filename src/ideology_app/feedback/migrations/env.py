"""Alembic environment of the feedback store (feedback-admin).

Separate from the shared database environment (``ideology_app:migrations``):
its own scripts, its own version table (``feedback_alembic_version``) and
``FEEDBACK_METADATA``, never ``models.Base.metadata``. Applied by
``ideology_app.feedback.store.upgrade_schema``, which passes its connection in
``config.attributes["connection"]``; otherwise the URL in the config is used.
"""

from alembic import context

from ideology_app.db import make_engine
from ideology_app.feedback.store import FEEDBACK_METADATA, VERSION_TABLE

config = context.config
target_metadata = FEEDBACK_METADATA


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        render_as_batch=True,
        **kwargs,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("the feedback migrations need a connection or sqlalchemy.url")
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            _configure(connection=conn)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
