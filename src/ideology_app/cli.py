"""``ideology`` command-line interface for the Operator."""

import datetime as dt
import re
from collections.abc import Sequence
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
from ideology_app.models import (
    DatasetVersionStatus,
    PipelineRunStatus,
    SourceDocumentStatus,
    ValidationResult,
)

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
    # Resolve the configuration before any write.
    try:
        mode = config.generation_mode()
        llm = config.llm_settings() if pipelines.queues_on_source_change(mode) else None
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
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
        # Same transaction: the document and the run it queues commit together.
        trigger = pipelines.queue_run_for_source_change(
            session, document, generation_mode=mode, llm=llm
        )
        document_id = document.id
        status = document.status
        page_count = document.page_count
        reason = document.failure_reason
    # The failed row is committed above; report it as an error afterwards.
    if status is SourceDocumentStatus.FAILED:
        raise click.ClickException(f"source document {document_id} failed: {reason}")
    click.echo(f"Created source document {document_id}: {status.value} ({page_count} pages)")
    if trigger.run_id is None:
        return
    if trigger.newly_queued:
        click.echo(
            f"Queued pipeline run {trigger.run_id} for election {trigger.election_id} "
            f"(generation mode {mode.value})"
        )
    else:
        click.echo(
            f"Pipeline run {trigger.run_id} is already queued "
            f"for election {trigger.election_id}"
        )


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
    """Generate Statements and Party Positions, validate them and publish on pass."""
    try:
        mode = config.generation_mode()
        settings = config.validation_settings()
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
        outcome = pipelines.execute_run(app.engine, run_id, provider, settings)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    # The failed run is committed above; report it as an error afterwards.
    _raise_if_failed(outcome)
    _echo_passed(outcome)


@pipeline.command("run-queued")
@click.option(
    "--election", "election_id", type=int, default=None, help="Only this Election's runs."
)
@requires_db
def pipeline_run_queued(app: AppContext, election_id: int | None) -> None:
    """Execute every queued Pipeline Run in id order, one at a time, in the foreground.

    Runs are queued by "ideology source add" in live Generation Mode. A run
    that fails is reported and the next one still executes; the exit code is 1
    if any failed. Run one executor at a time.
    """
    try:
        settings = config.validation_settings()
        provider = _provider()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    failures = 0
    try:
        with session_scope(app.engine) as session:
            run_ids = pipelines.list_queued_run_ids(session, election_id)
        if not run_ids:
            click.echo("No queued pipeline runs")
            return
        for run_id in run_ids:
            try:
                outcome = pipelines.execute_run(app.engine, run_id, provider, settings)
            except service.ElectionsError as exc:
                failures += 1
                click.echo(f"Error: {exc}", err=True)
                continue
            if outcome.status is PipelineRunStatus.FAILED:
                failures += 1
                click.echo(f"Error: {_failure_message(outcome)}", err=True)
                continue
            _echo_passed(outcome)
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
    if failures:
        raise click.ClickException(
            f"{failures} of {len(run_ids)} queued pipeline runs failed"
        )


def _echo_passed(outcome: pipelines.RunOutcome) -> None:
    """Print a finished run's summary line and what publishing did."""
    click.echo(
        f"Pipeline run {outcome.run_id}: {outcome.status.value} "
        f"(dataset version {outcome.dataset_version_id}, "
        f"{outcome.statement_count} statements, {outcome.position_count} party positions)"
    )
    _echo_publish(outcome)


def _echo_publish(outcome: pipelines.RunOutcome) -> None:
    """Say whether a ``passed`` run's Dataset Version was published."""
    publish = outcome.publish
    if publish is None:
        return
    if publish.published:
        line = (
            f"Published dataset version {publish.published_dataset_version_id} "
            f"for election {publish.election_id}"
        )
        if publish.superseded_dataset_version_id is not None:
            line += f" (superseded dataset version {publish.superseded_dataset_version_id})"
    else:
        line = (
            f"Not published: dataset version {publish.published_dataset_version_id} "
            f"of newer pipeline run {publish.published_run_id} is published "
            f"for election {publish.election_id}"
        )
    click.echo(line)


def _raise_if_failed(outcome: pipelines.RunOutcome) -> None:
    """Report a committed ``failed`` run as an error, pointing at its checks if any failed."""
    if outcome.status is not PipelineRunStatus.FAILED:
        return
    raise click.ClickException(_failure_message(outcome))


def _failure_message(outcome: pipelines.RunOutcome) -> str:
    message = f"pipeline run {outcome.run_id} failed: {outcome.failure_reason}"
    if outcome.failed_checks:
        message += f'; see "ideology pipeline checks --run {outcome.run_id}"'
    return message


@pipeline.command("validate")
@click.option("--run", "run_id", required=True, type=int, help="Pipeline Run id.")
@requires_db
def pipeline_validate(app: AppContext, run_id: int) -> None:
    """Validate a run left in ``validating`` (needs no LLM provider)."""
    try:
        settings = config.validation_settings()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    outcome = pipelines.validate_run(app.engine, run_id, settings=settings)
    _raise_if_failed(outcome)
    click.echo(f"Pipeline run {outcome.run_id}: {outcome.status.value}")
    _echo_publish(outcome)


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


def _one_line(text: str | None) -> str | None:
    """Show each whitespace run (tabs, newlines) as one space. Display only."""
    return None if text is None else re.sub(r"\s+", " ", text)


@pipeline.command("positions")
@click.option(
    "--dataset-version", "dataset_version_id", required=True, type=int, help="Dataset Version id."
)
@click.option("--party", "party_id", type=int, default=None, help="Only this Party id.")
@requires_db
def pipeline_positions(app: AppContext, dataset_version_id: int, party_id: int | None) -> None:
    """List the Party Positions of a Dataset Version with their Evidence."""
    with session_scope(app.engine) as session:
        rows: list[list[object]] = [
            [
                p.statement.position,
                p.party_id,
                p.engine_value,
                p.evidence_source_document_id,
                p.evidence_page,
                p.evidence_url,
                _one_line(p.evidence_quote),
            ]
            for p in pipelines.list_positions(session, dataset_version_id, party_id)
        ]
    _print_rows(["statement", "party", "value", "document", "page", "url", "quote"], rows)


CHECKS_HEADER = ["check", "result", "statement", "party", "message"]


def _check_rows(results: Sequence[ValidationResult]) -> list[list[object]]:
    """One row per passed check or per report entry (read inside the session)."""
    rows: list[list[object]] = []
    for result in results:
        label = "passed" if result.passed else "failed"
        if result.passed or not result.entries:
            rows.append([result.check_name, label, None, None, None])
        for entry in result.entries:
            rows.append(
                [
                    result.check_name,
                    label,
                    entry.statement.position if entry.statement else None,
                    entry.party_id,
                    _one_line(entry.message),
                ]
            )
    return rows


@pipeline.command("checks")
@click.option("--run", "run_id", required=True, type=int, help="Pipeline Run id.")
@requires_db
def pipeline_checks(app: AppContext, run_id: int) -> None:
    """List a run's Validation results: one row per passed check or per report entry."""
    with session_scope(app.engine) as session:
        rows = _check_rows(pipelines.list_validation_results(session, run_id))
    _print_rows(CHECKS_HEADER, rows)


NOT_RECORDED = "not recorded"


def _timestamp(value: dt.datetime | None) -> str:
    return NOT_RECORDED if value is None else value.isoformat(timespec="seconds")


def _duration(report: pipelines.RunReport) -> str:
    """Generation time, from ``started_at`` to ``generation_finished_at``."""
    if report.started_at is None or report.generation_finished_at is None:
        return NOT_RECORDED
    seconds = (report.generation_finished_at - report.started_at).total_seconds()
    return f"{seconds:.1f} s (generation)"


def _publication(report: pipelines.RunReport) -> str:
    """Whether the run's Dataset Version is live, and which version is."""
    election = report.election_id
    if report.live_dataset_version_id is None:
        live = "none"
    else:
        live = (
            f"dataset version {report.live_dataset_version_id} "
            f"of pipeline run {report.live_run_id}"
        )
    status = report.dataset_version_status
    if status is None:
        if report.status is PipelineRunStatus.FAILED:
            return "none: the run failed before a dataset version was created"
        return "none: the run has not produced a dataset version yet"
    if status is DatasetVersionStatus.PUBLISHED:
        return f"published: live for election {election}"
    if status is DatasetVersionStatus.SUPERSEDED:
        return f"superseded: live for election {election}: {live}"
    if report.status is PipelineRunStatus.VALIDATING:
        return (
            "not published: awaiting Validation "
            f'(run "ideology pipeline validate --run {report.run_id}")'
        )
    if report.status is PipelineRunStatus.FAILED:
        return f"not published: the run failed; live for election {election}: {live}"
    return (
        "not published: the run passed but its dataset version was kept candidate; "
        f"live for election {election}: {live}"
    )


def _sorted_pairs(values: dict[str, Any] | None) -> str:
    if values is None:
        return NOT_RECORDED
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


@pipeline.command("report")
@click.option("--run", "run_id", required=True, type=int, help="Pipeline Run id.")
@requires_db
def pipeline_report(app: AppContext, run_id: int) -> None:
    """Show one Pipeline Run: what it used, its usage, timing, publication and checks.

    Read-only; needs no LLM provider or API key.
    """
    with session_scope(app.engine) as session:
        report = pipelines.get_run_report(session, run_id)
        rows = _check_rows(report.results)
    # Usage is stored as zeros until generation finishes; zeros would mislead.
    usage_recorded = report.generation_finished_at is not None

    def usage(value: int) -> object:
        return value if usage_recorded else NOT_RECORDED

    version = report.dataset_version_id
    lines: list[tuple[str, object]] = [
        ("pipeline run", report.run_id),
        ("election", report.election_id),
        ("status", report.status.value),
        (
            "failure_reason",
            "none" if report.failure_reason is None else _one_line(report.failure_reason),
        ),
        ("provider", report.llm_provider),
        ("model", report.llm_model),
        ("generation_mode", report.generation_mode.value),
        ("prompt_versions", _sorted_pairs(report.prompt_versions)),
        ("created_at", _timestamp(report.created_at)),
        ("started_at", _timestamp(report.started_at)),
        ("generation_finished_at", _timestamp(report.generation_finished_at)),
        ("validated_at", _timestamp(report.validated_at)),
        ("duration", _duration(report)),
        ("llm_calls", usage(report.llm_calls)),
        ("input_tokens", usage(report.input_tokens)),
        ("output_tokens", usage(report.output_tokens)),
        ("cost", "not estimated (no price table)"),
        ("validation_settings", _sorted_pairs(report.validation_settings)),
        ("dataset_version", "none" if version is None else version),
        (
            "dataset_version_status",
            "none" if report.dataset_version_status is None
            else report.dataset_version_status.value,
        ),
        ("statements", "none" if report.statement_count is None else report.statement_count),
        ("publication", _publication(report)),
    ]
    for key, value in lines:
        click.echo(f"{key}: {value}")
    click.echo("")
    click.echo("validation report:")
    _print_rows(CHECKS_HEADER, rows)
