"""``ideology`` command-line interface for the Operator."""

import datetime as dt
import hashlib
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from functools import update_wrapper
from pathlib import Path
from typing import Any, Callable

import click
from alembic.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ideology_app import bundle_import
from ideology_app import elections as service
from ideology_app import config
from ideology_app import pipeline as pipelines
from ideology_app import shared_db
from ideology_app import source_bundle
from ideology_app import source_documents as sources
from ideology_app.pdf_text import EXTRACTOR, PdfTextError, extract_pages
from ideology_app.db import (
    head_revision,
    is_initialised,
    make_engine,
    run_migrations,
    session_scope,
)
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
    # The URL is the committed data/ideology.db (shared-database).
    shared: bool = False


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
    ctx.obj = AppContext(url=url, engine=engine, shared=shared_db.is_shared(url))


def requires_db(f: Callable[..., Any]) -> Callable[..., Any]:
    """Pass the AppContext and fail cleanly if the schema is not migrated."""

    @click.pass_obj
    def wrapper(app: AppContext, *args: Any, **kwargs: Any) -> Any:
        # Never let a command create an empty, committable shared file.
        if app.shared and not config.SHARED_DATABASE_PATH.exists():
            raise click.ClickException(
                shared_db.MISSING_SHARED.format(path=config.SHARED_DATABASE_PATH)
            )
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


def _now() -> dt.datetime:
    """The current time (UTC). Tests patch this seam to control the clock."""
    return dt.datetime.now(dt.UTC)


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


@db.command("check")
@click.pass_obj
def db_check(app: AppContext) -> None:
    """Check that a SQLite database file is safe to commit. Read-only.

    In order: no -journal/-wal/-shm file next to it, journal mode delete,
    integrity_check ok, schema at head, and every Election with a committed
    bundle (ELECTIONS_DATA_DIR) matching it. Unfinished runs are listed as
    information. Ends with "Safe to commit: yes" (exit 0) or one line per
    failed check and "Safe to commit: no" (exit 1).
    """
    path = shared_db.sqlite_path(app.url)
    if path is None:
        raise click.ClickException("db check supports SQLite databases only")
    if not path.is_file():
        raise click.ClickException(f"no database at {path}")
    problems = shared_db.file_checks(path)
    if problems:
        problems.append("the database was not opened; the remaining checks did not run")
    else:
        problems = _open_checks(path)
    if problems:
        for problem in problems:
            click.echo(f"Error: {problem}", err=True)
        click.echo("Safe to commit: no")
        raise click.exceptions.Exit(1)
    click.echo("Safe to commit: yes")


def _open_checks(path: Path) -> list[str]:
    """The checks that open ``path`` read-only (``mode=ro``); info lines are printed."""
    problems: list[str] = []
    engine = make_engine(shared_db.read_only_url(path))
    try:
        with engine.connect() as conn:
            integrity = [row[0] for row in conn.exec_driver_sql("PRAGMA integrity_check")]
            current = MigrationContext.configure(conn).get_current_revision()
        if integrity != ["ok"]:
            problems.append(f"integrity_check failed: {'; '.join(map(str, integrity))[:500]}")
        head = head_revision()
        if current != head:
            problems.append(
                f"schema is at migration {current or 'none'}, not head {head}; "
                'run "ideology db upgrade"'
            )
            return problems
        session = Session(engine)
        try:
            problems.extend(_bundle_and_run_checks(session))
        finally:
            session.rollback()
            session.close()
    except SQLAlchemyError as exc:
        problems.append(f"cannot read the database: {exc}")
    finally:
        engine.dispose()
    return problems


def _bundle_and_run_checks(session: Session) -> list[str]:
    problems: list[str] = []
    root = config.elections_data_dir()
    for election in service.list_elections(session):
        slug = source_bundle.bundle_slug(election, root)
        if slug is None:
            click.echo(f"election {election.id}: no committed bundle; text not checked")
        else:
            try:
                bundle = source_bundle.read_bundle(root / slug)
            except service.ElectionsError as exc:
                problems.append(f"election {election.id} ({slug}): bad bundle: {exc}")
            else:
                problems.extend(
                    f"election {election.id} ({slug}): {problem}"
                    for problem in bundle_import.check_against_bundle(session, bundle)
                )
        unfinished = pipelines.find_unfinished_run(session, election.id)
        if unfinished is not None:
            line = (
                f"election {election.id}, run {unfinished.run_id}: "
                f"{unfinished.status.value}, {unfinished.recorded_calls} recorded calls; "
                f"resume with --resume-from {unfinished.run_id}"
            )
            if unfinished.status is PipelineRunStatus.RUNNING:
                line += "; commit only if no ideology process is still running it"
            click.echo(line)
    return problems


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
    _echo_trigger(trigger, mode)


def _echo_trigger(trigger: pipelines.SourceChangeOutcome, mode: config.GenerationMode) -> None:
    """Print what the live trigger did (nothing when no run was queued or joined)."""
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


@source.command("refetch")
@click.option(
    "--election", "election_id", type=int, default=None, help="Only this Election's documents."
)
@requires_db
def source_refetch(app: AppContext, election_id: int | None) -> None:
    """Download again every current URL Source Document whose last check is due.

    Due means checked (or, if never checked, created) at least
    SOURCE_REFETCH_INTERVAL_HOURS ago (default 6). Changed bytes register a new
    Source Document that replaces the old one (which stays for the Evidence of
    older Dataset Versions); in live Generation Mode that also queues a
    Pipeline Run. A failed download keeps the old document; the next document
    is still checked and the exit code is 1. Run one re-fetch at a time.
    """
    # Resolve the configuration before any fetch or write.
    try:
        interval = config.source_refetch_interval()
        mode = config.generation_mode()
        llm = config.llm_settings() if pipelines.queues_on_source_change(mode) else None
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    now = _now()
    files_dir = config.source_files_dir()
    with session_scope(app.engine) as session:
        document_ids = sources.due_url_document_ids(
            session, now=now, interval=interval, election_id=election_id
        )
    if not document_ids:
        click.echo("No source documents due for re-fetch")
        return
    failures = 0
    for document_id in document_ids:
        trigger = None
        try:
            # One transaction per document: the replacement, the old row's
            # replaced_by_id and the run it queues commit together.
            with session_scope(app.engine) as session:
                outcome = sources.refetch_url_document(
                    session, document_id, now=now, files_dir=files_dir, interval=interval
                )
                replacement = outcome.replacement
                if replacement is not None:
                    trigger = pipelines.queue_run_for_source_change(
                        session, replacement, generation_mode=mode, llm=llm
                    )
                    replacement_id = replacement.id
                    page_count = replacement.page_count
        except service.ElectionsError as exc:
            failures += 1
            click.echo(f"Error: source document {document_id}: {exc}", err=True)
            continue
        result = outcome.result
        if result is sources.RefetchResult.FAILED:
            failures += 1
            click.echo(f"Error: source document {document_id}: {outcome.reason}", err=True)
        elif result is sources.RefetchResult.UNCHANGED:
            click.echo(f"Source document {document_id}: unchanged")
        elif result is sources.RefetchResult.DUPLICATE:
            click.echo(
                f"Source document {document_id}: content matches source document "
                f"{outcome.duplicate_of_id} of the same party; nothing changed"
            )
        else:
            click.echo(
                f"Source document {document_id}: replaced by source document "
                f"{replacement_id} ({page_count} pages)"
            )
            assert trigger is not None
            _echo_trigger(trigger, mode)
    if failures:
        raise click.ClickException(
            f"{failures} of {len(document_ids)} source documents could not be re-fetched"
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
                d.replaced_by_id,
                d.bundle_file,
            ]
            for d in sources.list_documents(session, party_id)
        ]
    _print_rows(
        [
            "id",
            "origin",
            "status",
            "pages",
            "content_hash",
            "filename",
            "url",
            "failure_reason",
            "replaced_by",
            "bundle_file",
        ],
        rows,
    )


@source.command("extract")
@click.argument("pdf", type=click.Path(path_type=Path))
@click.option("--party", "party", required=True, help="Party short name, e.g. PP.")
@click.option(
    "--out",
    "out",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Source Text file to write, e.g. data/elections/<slug>/pp.md.",
)
@click.option("--url", default=None, help="Public URL of the PDF (Evidence links to it).")
@click.option("--force", is_flag=True, help="Overwrite --out if it exists.")
def source_extract(pdf: Path, party: str, out: Path, url: str | None, force: bool) -> None:
    """Extract a manifesto PDF into a Source Text file (no database needed).

    The file holds each page's text exactly as extracted, under
    "<!-- page N -->" markers, with front matter that records the PDF's
    SHA-256 and the extractor. Commit it to a Source Text Bundle and import it
    with "ideology data import"; never edit it by hand.
    """
    try:
        if not party.strip():
            raise service.InvalidInputError("party must not be empty")
        if party != party.strip():
            raise service.InvalidInputError(
                "party must not have leading or trailing whitespace"
            )
        source_url = sources.validate_url(url) if url is not None else None
        if out.exists() and not force:
            raise service.InvalidInputError(f"{out} exists; pass --force to overwrite")
        if not out.parent.is_dir():
            raise service.InvalidInputError(f"directory {str(out.parent)!r} not found")
        data = sources.read_pdf_file(pdf)
        try:
            pages = extract_pages(data)
        except PdfTextError as exc:
            raise service.InvalidInputError(f"{pdf}: {exc.reason}") from None
        content = source_bundle.serialise_source_text(
            party=party,
            source_url=source_url,
            pdf_sha256=hashlib.sha256(data).hexdigest(),
            extractor=EXTRACTOR,
            pages=pages,
        )
        # Never write a file that would not import.
        source_bundle.parse_source_text(content, name=str(out))
    except service.ElectionsError as exc:
        raise click.ClickException(str(exc)) from exc
    _write_atomically(out, content)
    click.echo(f"Wrote {out}: {len(pages)} pages, {len(content)} bytes")


def _write_atomically(path: Path, content: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".extract-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        # mkstemp creates the file 0600; give it the usual mode (0666 minus umask).
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp_name, 0o666 & ~umask)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


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


@main.group()
def data() -> None:
    """Shared election data (Source Text Bundles under data/elections/<slug>/)."""


@data.command("import")
@click.argument("directory", type=click.Path(path_type=Path))
@requires_db
def data_import(app: AppContext, directory: Path) -> None:
    """Import a Source Text Bundle: its Election, Parties and parsed Source Documents.

    Idempotent: unchanged files are left alone; a changed file registers a
    Source Document that replaces the Party's previous one (which stays for
    the Evidence of older Dataset Versions). The whole bundle is checked
    before the first write, and everything is written in one transaction. In
    live Generation Mode an added or replacing document queues a Pipeline Run.
    """
    # Resolve the configuration before any write.
    try:
        mode = config.generation_mode()
        llm = config.llm_settings() if pipelines.queues_on_source_change(mode) else None
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    bundle = source_bundle.read_bundle(directory)
    trigger = None
    with session_scope(app.engine) as session:
        report = bundle_import.import_bundle(session, bundle)
        # Same transaction: the documents and the run they queue commit together.
        for document in report.new_documents:
            outcome = pipelines.queue_run_for_source_change(
                session, document, generation_mode=mode, llm=llm
            )
            if outcome.run_id is not None and trigger is None:
                trigger = outcome
    for item in report.outcomes:
        party_part = (
            f"Party {item.short_name}: {'created' if item.party_created else 'exists'} "
            f"(id {item.party_id})"
        )
        if item.status is bundle_import.DocumentStatus.ADDED:
            document_part = (
                f"source document {item.document_id}: added ({item.page_count} pages)"
            )
        elif item.status is bundle_import.DocumentStatus.REPLACED:
            document_part = (
                f"source document {item.document_id}: replaces source document "
                f"{item.replaced_document_id} ({item.page_count} pages)"
            )
        else:
            document_part = f"source document {item.document_id}: unchanged"
        click.echo(f"{party_part}; {document_part}")
    for short_name, party_id in report.left_alone:
        click.echo(f"Party {short_name} (id {party_id}) is not in the bundle; left unchanged")
    click.echo(
        f"Imported election {report.slug} (id {report.election_id}): "
        f"{report.count(bundle_import.DocumentStatus.ADDED)} added, "
        f"{report.count(bundle_import.DocumentStatus.REPLACED)} replaced, "
        f"{report.count(bundle_import.DocumentStatus.UNCHANGED)} unchanged"
    )
    if trigger is not None:
        _echo_trigger(trigger, mode)


@data.command("check")
@click.argument("directory", type=click.Path(path_type=Path))
@requires_db
def data_check(app: AppContext, directory: Path) -> None:
    """Check that the database holds exactly a Source Text Bundle's text. Read-only.

    Exits 1 and prints one line per divergence (a missing Election, Party or
    document, a different content hash or page text, or a Party document that
    was not imported from the bundle).
    """
    bundle = source_bundle.read_bundle(directory)
    session = Session(app.engine)
    try:
        problems = bundle_import.check_against_bundle(session, bundle)
        documents = len(bundle.parties)
    finally:
        session.rollback()
        session.close()
    if problems:
        for problem in problems:
            click.echo(f"Error: {problem}", err=True)
        raise click.ClickException(
            f"database does not match bundle {bundle.slug}: {len(problems)} problems"
        )
    click.echo(f"Database matches bundle {bundle.slug}: {documents} documents")


def _provider() -> LLMProvider:
    """The configured LLM provider. Tests patch this seam to inject a fake."""
    return build_provider(config.llm_settings())


def _close(provider: LLMProvider) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        close()


def _stdin_is_interactive() -> bool:
    """True when stdin is a terminal. Tests patch this seam to answer the prompt."""
    return sys.stdin.isatty()


SHARED_PROMPT = (
    "Database {path} is shared through git.\n"
    "One active run at a time: generate only if you pulled the latest commit of this\n"
    "database and nobody else is generating on it (any Election)."
)


def _confirm_shared(app: AppContext, yes: bool) -> None:
    """On the shared database, ask before generating; ``--yes`` skips it. No write.

    Without ``--yes`` a non-interactive stdin refuses instead of blocking, and
    answering no aborts (exit 1).
    """
    if not app.shared or yes:
        return
    if not _stdin_is_interactive():
        raise click.ClickException(
            "refusing to generate on the shared database without confirmation; pass --yes"
        )
    click.echo(SHARED_PROMPT.format(path=config.SHARED_DATABASE_PATH.as_posix()))
    click.confirm("Continue?", default=False, abort=True)


def _guard_unfinished(
    app: AppContext, election_id: int, provider: LLMProvider, fresh: bool
) -> None:
    """Refuse (shared database) or warn (any other) when the Election has an unfinished run."""
    if fresh:
        return
    session = Session(app.engine)
    try:
        unfinished = pipelines.find_unfinished_run(
            session, election_id, provider.name, provider.model
        )
    finally:
        session.rollback()
        session.close()
    if unfinished is None:
        return
    message = (
        f"election {election_id} has an unfinished run {unfinished.run_id} "
        f"({unfinished.status.value}, {unfinished.recorded_calls} recorded calls); "
        f"resume it with --resume-from {unfinished.run_id}, or pass --fresh to start from zero"
    )
    if unfinished.status is PipelineRunStatus.RUNNING:
        message += "; if another developer is generating, stop; a killed run also stays running"
    if app.shared:
        raise click.ClickException(message)
    click.echo(f"Warning: {message}", err=True)


@main.group()
def pipeline() -> None:
    """Run the AI pipeline and inspect its Pipeline Runs."""


@pipeline.command("run")
@click.option("--election", "election_id", required=True, type=int, help="Election id.")
@click.option(
    "--resume-from",
    "resume_from",
    type=int,
    default=None,
    help="Reuse the recorded LLM calls of this earlier run (same election, provider "
    "and model) and only call the LLM for the rest.",
)
@click.option(
    "--fresh",
    is_flag=True,
    help="Start from zero even though the election has an unfinished run.",
)
@click.option("--yes", is_flag=True, help="Do not ask for confirmation on the shared database.")
@requires_db
def pipeline_run(
    app: AppContext, election_id: int, resume_from: int | None, fresh: bool, yes: bool
) -> None:
    """Generate Statements and Party Positions, validate them and publish on pass.

    Every successful LLM call is recorded as it returns, so a run that stops
    halfway can be resumed with ``--resume-from``. Without it, an unfinished
    run of the election (running or failed, no dataset version, same provider
    and model) is refused on the shared database and warned about elsewhere;
    ``--fresh`` starts from zero anyway.
    """
    if fresh and resume_from is not None:
        raise click.UsageError("pass at most one of --fresh or --resume-from")
    try:
        mode = config.generation_mode()
        settings = config.validation_settings()
        provider = _provider()
    except config.ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    try:
        if resume_from is None:
            _guard_unfinished(app, election_id, provider, fresh)
        _confirm_shared(app, yes)
        with session_scope(app.engine) as session:
            run = pipelines.queue_run(
                session,
                election_id,
                llm_provider=provider.name,
                llm_model=provider.model,
                generation_mode=mode,
                resumed_from_run_id=resume_from,
            )
            run_id = run.id
        if resume_from is not None:
            click.echo(
                f"Pipeline run {run_id}: resuming from run {resume_from} "
                f"({pipelines.count_recorded_calls(app.engine, resume_from)} recorded calls)"
            )
        outcome = pipelines.execute_run(app.engine, run_id, provider, settings)
    finally:
        _close(provider)
    # The failed run is committed above; report it as an error afterwards.
    _raise_if_failed(outcome)
    _echo_passed(outcome)


@pipeline.command("run-queued")
@click.option(
    "--election", "election_id", type=int, default=None, help="Only this Election's runs."
)
@click.option("--yes", is_flag=True, help="Do not ask for confirmation on the shared database.")
@requires_db
def pipeline_run_queued(app: AppContext, election_id: int | None, yes: bool) -> None:
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
        _confirm_shared(app, yes)
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
        _close(provider)
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
        (
            "resumed_from",
            "none" if report.resumed_from_run_id is None else report.resumed_from_run_id,
        ),
        ("reused_calls", report.reused_calls),
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
