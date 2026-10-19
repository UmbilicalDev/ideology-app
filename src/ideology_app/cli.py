"""``ideology`` command-line interface for the Operator."""

from dataclasses import dataclass
from functools import update_wrapper
from pathlib import Path
from typing import Any, Callable

import click
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from ideology_app import elections as service
from ideology_app import config
from ideology_app import pipeline as pipelines
from ideology_app import source_documents as sources
from ideology_app.db import is_initialised, make_engine, run_migrations, session_scope
from ideology_app.llm import LLMProvider, build_provider
from ideology_app.models import PipelineRunStatus, SourceDocumentStatus

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
        click.echo("\t".join("" if value is None else str(value) for value in row))


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


@main.group()
def source() -> None:
    """Manage Source Documents."""


@source.command("add")
@click.option("--party", "party_id", required=True, type=int, help="Party id.")
@click.option(
    "--file",
    "file_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="PDF manifesto to attach.",
)
@click.option("--url", default=None, help="Manifesto PDF URL to fetch.")
@requires_db
def source_add(app: AppContext, party_id: int, file_path: Path | None, url: str | None) -> None:
    """Attach a PDF (from a file or a URL) to a Party and extract its text page by page."""
    if (file_path is None) == (url is None):
        raise click.UsageError("pass exactly one of --file or --url")
    with session_scope(app.engine) as session:
        if url is not None:
            document = sources.add_url_document(
                session, party_id=party_id, url=url, files_dir=config.source_files_dir()
            )
        else:
            assert file_path is not None
            document = sources.add_uploaded_document(
                session,
                party_id=party_id,
                file_path=file_path,
                files_dir=config.source_files_dir(),
            )
        document_id = document.id
        status = document.status
        page_count = document.page_count
        reason = document.failure_reason
    # The failed row is committed above; report it as an error afterwards.
    if status is SourceDocumentStatus.FAILED:
        raise click.ClickException(f"source document {document_id} failed: {reason}")
    click.echo(f"Created source document {document_id}: {status.value} ({page_count} pages)")


@source.command("list")
@click.option("--party", "party_id", required=True, type=int, help="Party id.")
@requires_db
def source_list(app: AppContext, party_id: int) -> None:
    """List the Source Documents of a Party."""
    with session_scope(app.engine) as session:
        rows: list[list[object]] = [
            [
                d.id,
                d.origin.value,
                d.status.value,
                d.page_count,
                d.content_hash,
                d.original_filename,
                d.source_url,
                d.failure_reason,
            ]
            for d in sources.list_documents(session, party_id)
        ]
    _print_rows(
        ["id", "origin", "status", "pages", "content_hash", "filename", "url", "failure_reason"],
        rows,
    )


@source.command("text")
@click.option("--document", "document_id", required=True, type=int, help="Source Document id.")
@click.option("--page", type=int, default=None, help="Print only this page (1-based).")
@requires_db
def source_text(app: AppContext, document_id: int, page: int | None) -> None:
    """Print the extracted text of a Source Document, page by page."""
    with session_scope(app.engine) as session:
        document = sources.get_document(session, document_id)
        pages = [(p.page_number, p.text) for p in document.pages]
    if page is not None:
        pages = [(number, text) for number, text in pages if number == page]
        if not pages:
            raise click.ClickException(
                f"page {page} of source document {document_id} not found"
            )
    for number, text in pages:
        click.echo(f"--- page {number} ---")
        click.echo(text)


def _provider() -> LLMProvider:
    """The configured LLM provider. Tests patch this seam to inject a fake."""
    return build_provider(config.llm_settings())


@main.group()
def pipeline() -> None:
    """Run the AI pipeline and inspect its Pipeline Runs."""


@pipeline.command("run")
@click.option("--election", "election_id", required=True, type=int, help="Election id.")
@requires_db
def pipeline_run(app: AppContext, election_id: int) -> None:
    """Generate a candidate Dataset Version of Statements for an Election."""
    try:
        mode = config.generation_mode()
        provider = _provider()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        with session_scope(app.engine) as session:
            run = pipelines.queue_run(
                session,
                election_id,
                llm_provider=provider.name,
                llm_model=provider.model,
                generation_mode=mode,
            )
            run_id = run.id
        outcome = pipelines.execute_run(app.engine, run_id, provider)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    # The failed run is committed above; report it as an error afterwards.
    if outcome.status is PipelineRunStatus.FAILED:
        raise click.ClickException(
            f"pipeline run {outcome.run_id} failed: {outcome.failure_reason}"
        )
    click.echo(
        f"Pipeline run {outcome.run_id}: {outcome.status.value} "
        f"(dataset version {outcome.dataset_version_id}, "
        f"{outcome.statement_count} statements)"
    )


@pipeline.command("list")
@click.option("--election", "election_id", required=True, type=int, help="Election id.")
@requires_db
def pipeline_list(app: AppContext, election_id: int) -> None:
    """List the Pipeline Runs of an Election."""
    with session_scope(app.engine) as session:
        rows: list[list[object]] = []
        for r in pipelines.list_runs(session, election_id):
            version = r.dataset_version
            rows.append(
                [
                    r.id,
                    r.status.value,
                    r.llm_provider,
                    r.llm_model,
                    r.generation_mode.value,
                    version.id if version else None,
                    len(version.statements) if version else None,
                    r.llm_calls,
                    r.input_tokens,
                    r.output_tokens,
                    r.failure_reason,
                ]
            )
    _print_rows(
        [
            "id",
            "status",
            "provider",
            "model",
            "mode",
            "dataset_version",
            "statements",
            "llm_calls",
            "input_tokens",
            "output_tokens",
            "failure_reason",
        ],
        rows,
    )


@pipeline.command("statements")
@click.option(
    "--dataset-version", "dataset_version_id", required=True, type=int, help="Dataset Version id."
)
@requires_db
def pipeline_statements(app: AppContext, dataset_version_id: int) -> None:
    """List the Statements of a Dataset Version in order."""
    with session_scope(app.engine) as session:
        version = pipelines.get_dataset_version(session, dataset_version_id)
        rows: list[list[object]] = [[s.position, s.topic, s.text] for s in version.statements]
    _print_rows(["position", "topic", "text"], rows)
