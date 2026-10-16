"""``ideology`` command-line interface for the Operator."""

from dataclasses import dataclass
from functools import update_wrapper
from typing import Any, Callable

import click
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from ideology_app import elections as service
from ideology_app import config
from ideology_app.db import is_initialised, make_engine, run_migrations, session_scope

NOT_INITIALISED = 'Database is not initialised; run "ideology db upgrade".'


@dataclass
class AppContext:
    url: str
    engine: Engine


def _safe_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # an unparsable URL is reported by SQLAlchemy later
        return "<invalid url>"


@click.group()
@click.option(
    "--database-url",
    envvar="DATABASE_URL",
    default=None,
    help="SQLAlchemy URL. Defaults to $DATABASE_URL, else sqlite:///ideology.db.",
)
@click.pass_context
def main(ctx: click.Context, database_url: str | None) -> None:
    """Operator commands for the ideology VAA."""
    url = database_url or config.database_url()
    try:
        engine = make_engine(url)
    except SQLAlchemyError as exc:
        raise click.ClickException(f"invalid database URL: {exc}") from exc
    except ImportError as exc:
        raise click.ClickException(f"database driver not installed: {exc}") from exc
    ctx.call_on_close(engine.dispose)
    ctx.obj = AppContext(url=url, engine=engine)


def requires_db(f: Callable[..., Any]) -> Callable[..., Any]:
    """Pass the AppContext and fail cleanly if the schema is not migrated."""

    @click.pass_obj
    def wrapper(app: AppContext, *args: Any, **kwargs: Any) -> Any:
        try:
            ready = is_initialised(app.engine)
        except SQLAlchemyError as exc:
            raise click.ClickException(f"cannot open database: {exc}") from exc
        if not ready:
            raise click.ClickException(NOT_INITIALISED)
        try:
            return f(app, *args, **kwargs)
        except service.ElectionsError as exc:
            raise click.ClickException(str(exc)) from exc

    return update_wrapper(wrapper, f)


def _print_rows(header: list[str], rows: list[list[object]]) -> None:
    click.echo("\t".join(header))
    for row in rows:
        click.echo("\t".join(str(value) for value in row))


@main.group()
def db() -> None:
    """Database schema commands."""


@db.command("upgrade")
@click.pass_obj
def db_upgrade(app: AppContext) -> None:
    """Apply all migrations up to head."""
    try:
        run_migrations(app.url)
    except SQLAlchemyError as exc:
        raise click.ClickException(f"migration failed: {exc}") from exc
    click.echo(f"Database at {_safe_url(app.url)} is at head")


@main.group()
def election() -> None:
    """Manage Elections."""


@election.command("create")
@click.option("--country", required=True, help="Two-letter country code, e.g. ES.")
@click.option("--type", "type_", required=True, help="Election type, e.g. general.")
@click.option("--date", required=True, type=click.DateTime(["%Y-%m-%d"]), help="YYYY-MM-DD.")
@click.option("--name", required=True, help="Display name.")
@requires_db
def election_create(app: AppContext, country: str, type_: str, date: Any, name: str) -> None:
    """Create a draft Election."""
    with session_scope(app.engine) as session:
        created = service.create_election(
            session, country=country, type=type_, date=date.date(), name=name
        )
        election_id = created.id
    click.echo(f"Created election {election_id}")


@election.command("list")
@requires_db
def election_list(app: AppContext) -> None:
    """List Elections."""
    with session_scope(app.engine) as session:
        rows: list[list[object]] = [
            [e.id, e.country, e.type.value, e.date.isoformat(), e.status.value, e.name]
            for e in service.list_elections(session)
        ]
    _print_rows(["id", "country", "type", "date", "status", "name"], rows)


@main.group()
def party() -> None:
    """Manage the Parties (ballot tickets) of an Election."""


@party.command("add")
@click.option("--election", "election_id", required=True, type=int, help="Election id.")
@click.option("--name", required=True, help="Full ballot-ticket name.")
@click.option("--short-name", required=True, help="Short name, e.g. PP.")
@requires_db
def party_add(app: AppContext, election_id: int, name: str, short_name: str) -> None:
    """Add a Party to an Election."""
    with session_scope(app.engine) as session:
        created = service.add_party(
            session, election_id=election_id, name=name, short_name=short_name
        )
        party_id = created.id
    click.echo(f"Created party {party_id}")


@party.command("list")
@click.option("--election", "election_id", required=True, type=int, help="Election id.")
@requires_db
def party_list(app: AppContext, election_id: int) -> None:
    """List the Parties of an Election in creation order."""
    with session_scope(app.engine) as session:
        rows: list[list[object]] = [
            [p.id, p.short_name, p.name] for p in service.list_parties(session, election_id)
        ]
    _print_rows(["id", "short_name", "name"], rows)
