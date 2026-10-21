"""Domain service for Source Documents (Party manifestos).

Functions take a Session and leave committing to the caller, like
``ideology_app.elections``. Uploaded and downloaded files are stored content-addressed as
``<files_dir>/<content_hash>.pdf`` and are never overwritten or edited.
"""

import datetime as dt
import hashlib
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ideology_app import http_fetch
from ideology_app.elections import DuplicateError, InvalidInputError, NotFoundError
from ideology_app.models import (
    Election,
    Party,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentPage,
    SourceDocumentStatus,
)
from ideology_app.pdf_text import PdfTextError, extract_pages

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PDF_MAGIC = b"%PDF-"
_FILENAME_MAX = 255
MAX_SOURCE_URL_LENGTH = 2048
_URL_SCHEMES = frozenset({"http", "https"})


def _get_party(session: Session, party_id: int) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise NotFoundError(f"party {party_id} not found")
    return party


def read_pdf_file(file_path: Path) -> bytes:
    """The bytes of a PDF on disk. Raises InvalidInputError (missing, empty, too big, not a PDF)."""
    if not file_path.is_file():
        raise InvalidInputError(f"file {str(file_path)!r} not found")
    size = file_path.stat().st_size
    if size == 0:
        raise InvalidInputError(f"file {str(file_path)!r} is empty")
    if size > MAX_UPLOAD_BYTES:
        raise InvalidInputError(
            f"file {str(file_path)!r} is too large: {size} bytes "
            f"(maximum {MAX_UPLOAD_BYTES} bytes)"
        )
    with file_path.open("rb") as handle:
        if handle.read(len(PDF_MAGIC)) != PDF_MAGIC:
            raise InvalidInputError(
                f"file {str(file_path)!r} is not a PDF (it does not start with %PDF-)"
            )
        handle.seek(0)
        return handle.read()


def _store_file(files_dir: Path, name: str, data: bytes) -> None:
    """Write ``data`` to ``files_dir/name`` atomically unless it already exists."""
    files_dir.mkdir(parents=True, exist_ok=True)
    target = files_dir / name
    if target.exists():
        return
    fd, tmp_name = tempfile.mkstemp(dir=files_dir, prefix=".upload-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def add_uploaded_document(
    session: Session, *, party_id: int, file_path: Path, files_dir: Path
) -> SourceDocument:
    """Register a PDF for a Party, store it and extract its page text.

    Returns the document in ``parsed`` or ``failed`` state. Raises
    NotFoundError, InvalidInputError or DuplicateError before anything is
    written.
    """
    party = _get_party(session, party_id)
    data = read_pdf_file(Path(file_path))
    content_hash = hashlib.sha256(data).hexdigest()

    document = SourceDocument(
        party_id=party.id,
        origin=SourceDocumentOrigin.UPLOAD,
        status=SourceDocumentStatus.REGISTERED,
        original_filename=Path(file_path).name[:_FILENAME_MAX],
        content_hash=content_hash,
    )
    session.add(document)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(
            f"party {party_id} already has a source document with content hash {content_hash}"
        ) from exc

    return _store_and_parse(session, document, data, Path(files_dir))


def _store_and_parse(
    session: Session, document: SourceDocument, data: bytes, files_dir: Path
) -> SourceDocument:
    """Store ``data`` content-addressed, then extract its pages.

    ``document`` is already flushed with its ``content_hash``. It ends in
    ``parsed`` or ``failed``.
    """
    _store_file(files_dir, f"{document.content_hash}.pdf", data)
    document.status = SourceDocumentStatus.FETCHED

    try:
        pages = extract_pages(data)
    except PdfTextError as exc:
        document.status = SourceDocumentStatus.FAILED
        document.failure_reason = exc.reason
        document.page_count = exc.page_count
    else:
        set_parsed_pages(document, pages)
    session.flush()
    return document


def set_parsed_pages(document: SourceDocument, pages: Sequence[str]) -> None:
    """Attach the extracted ``pages`` (1-based) and mark ``document`` ``parsed``."""
    document.pages = [
        SourceDocumentPage(page_number=number, text=text)
        for number, text in enumerate(pages, start=1)
    ]
    document.page_count = len(pages)
    document.status = SourceDocumentStatus.PARSED


def validate_url(url: str) -> str:
    """Return the stripped URL, or raise InvalidInputError before any fetch."""
    url = url.strip()

    def invalid(why: str) -> InvalidInputError:
        shown = url if len(url) <= 100 else url[:100] + "..."
        return InvalidInputError(f"invalid URL {shown!r}: {why}")

    if len(url) > MAX_SOURCE_URL_LENGTH:
        raise invalid(f"longer than {MAX_SOURCE_URL_LENGTH} characters")
    if any(ch <= " " or "\x7f" <= ch <= "\x9f" for ch in url):
        raise invalid("it contains whitespace or control characters")
    try:
        url.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise invalid("it is not valid UTF-8") from exc
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        parts.port  # raises ValueError for a port that is not a number in range
        has_credentials = parts.username is not None or parts.password is not None
    except ValueError as exc:
        raise invalid(str(exc)) from exc
    if parts.scheme.lower() not in _URL_SCHEMES:
        raise invalid("only absolute http or https URLs are allowed")
    if not hostname:
        raise invalid("it has no host")
    if has_credentials:
        raise invalid("it must not contain credentials")
    return url


def _filename_from_url(url: str) -> str | None:
    segment = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    return segment[:_FILENAME_MAX] or None


def _default_fetch(url: str) -> bytes:
    return http_fetch.fetch_url(url, max_bytes=MAX_UPLOAD_BYTES)


def add_url_document(
    session: Session,
    *,
    party_id: int,
    url: str,
    files_dir: Path,
    fetch: Callable[[str], bytes] | None = None,
) -> SourceDocument:
    """Register a manifesto URL for a Party: download it once, store and parse it.

    Raises NotFoundError or InvalidInputError before anything is fetched, and
    DuplicateError (after a rollback) when the Party already has this content.
    A failed download returns a ``failed`` row with no content hash or file.
    """
    party = _get_party(session, party_id)
    url = validate_url(url)
    fetch = fetch or _default_fetch

    try:
        data = fetch(url)
        if not data.startswith(PDF_MAGIC):
            raise http_fetch.FetchError("response is not a PDF (it does not start with %PDF-)")
    except http_fetch.FetchError as exc:
        document = SourceDocument(
            party_id=party.id,
            origin=SourceDocumentOrigin.URL,
            status=SourceDocumentStatus.FAILED,
            source_url=url,
            failure_reason=exc.reason,
        )
        session.add(document)
        session.flush()
        return document

    content_hash = hashlib.sha256(data).hexdigest()
    document = SourceDocument(
        party_id=party.id,
        origin=SourceDocumentOrigin.URL,
        status=SourceDocumentStatus.REGISTERED,
        source_url=url,
        original_filename=_filename_from_url(url),
        content_hash=content_hash,
    )
    session.add(document)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateError(
            f"party {party_id} already has a source document with content hash {content_hash}"
        ) from exc
    return _store_and_parse(session, document, data, Path(files_dir))


def list_documents(session: Session, party_id: int) -> Sequence[SourceDocument]:
    """The Source Documents of a Party in id order. Raises NotFoundError."""
    _get_party(session, party_id)
    return session.scalars(
        select(SourceDocument)
        .where(SourceDocument.party_id == party_id)
        .order_by(SourceDocument.id)
    ).all()


def get_document(session: Session, document_id: int) -> SourceDocument:
    """One Source Document. Raises NotFoundError."""
    document = session.get(SourceDocument, document_id)
    if document is None:
        raise NotFoundError(f"source document {document_id} not found")
    return document


# --- Periodic re-fetch of URL documents (``ideology source refetch``) ---------


class RefetchResult(StrEnum):
    """What one re-fetch of a URL Source Document found."""

    UNCHANGED = "unchanged"  # same bytes: only last_checked_at was written
    REPLACED = "replaced"  # new bytes: a new row replaces the document
    DUPLICATE = "duplicate"  # bytes of another document of the same Party
    FAILED = "failed"  # download, PDF or URL problem: only last_checked_at


@dataclass(frozen=True)
class RefetchOutcome:
    """The result of ``refetch_url_document``.

    ``replacement`` is the new row (``replaced`` only, still attached to the
    session); ``duplicate_of_id`` the matching document (``duplicate`` only);
    ``reason`` the failure cause (``failed`` only).
    """

    document_id: int
    result: RefetchResult
    replacement: SourceDocument | None = None
    duplicate_of_id: int | None = None
    reason: str | None = None


def _as_utc(value: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; they are stored in UTC."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def _is_due(
    last_checked_at: dt.datetime | None,
    created_at: dt.datetime,
    *,
    now: dt.datetime,
    interval: dt.timedelta,
) -> bool:
    return _as_utc(last_checked_at or created_at) <= now - interval


def _is_current_parsed_url(document: SourceDocument) -> bool:
    return (
        document.origin is SourceDocumentOrigin.URL
        and document.status is SourceDocumentStatus.PARSED
        and document.replaced_by_id is None
        and document.bundle_file is None
    )


def due_url_document_ids(
    session: Session,
    *,
    now: dt.datetime,
    interval: dt.timedelta,
    election_id: int | None = None,
) -> list[int]:
    """Ids (ascending) of current parsed URL documents last checked at least ``interval`` ago.

    A document never checked counts from its ``created_at``. With
    ``election_id`` only that Election's Parties are considered (NotFoundError
    if it does not exist). Upload, bundle, ``failed`` and replaced documents are never
    due.
    """
    query = select(
        SourceDocument.id, SourceDocument.last_checked_at, SourceDocument.created_at
    ).where(
        SourceDocument.origin == SourceDocumentOrigin.URL,
        SourceDocument.status == SourceDocumentStatus.PARSED,
        SourceDocument.replaced_by_id.is_(None),
        # Bundle rows change only through a committed file and ``data import``.
        SourceDocument.bundle_file.is_(None),
    )
    if election_id is not None:
        if session.get(Election, election_id) is None:
            raise NotFoundError(f"election {election_id} not found")
        query = query.join(Party, SourceDocument.party_id == Party.id).where(
            Party.election_id == election_id
        )
    rows = session.execute(query.order_by(SourceDocument.id)).all()
    return [
        document_id
        for document_id, last_checked_at, created_at in rows
        if _is_due(last_checked_at, created_at, now=now, interval=interval)
    ]


def refetch_url_document(
    session: Session,
    document_id: int,
    *,
    now: dt.datetime,
    files_dir: Path,
    fetch: Callable[[str], bytes] | None = None,
    interval: dt.timedelta | None = None,
) -> RefetchOutcome:
    """Download a current parsed URL document again and record what changed. Never commits.

    Always sets ``last_checked_at = now``. New bytes (a text PDF whose hash no
    document of the Party has) become a new ``parsed`` row for the same Party
    and URL, and the old row gets ``replaced_by_id``; its hash, pages and file
    never change. The fetch and page extraction happen before any row is
    inserted, so a failure writes only ``last_checked_at``.

    Raises NotFoundError for an unknown id, InvalidInputError when the row is
    not a current parsed URL document (or, with ``interval``, is no longer
    due), and DuplicateError if the per-Party content hash is hit in a race.
    A row imported from a Source Text Bundle is never re-fetched
    (InvalidInputError).
    """
    document = session.scalars(
        select(SourceDocument).where(SourceDocument.id == document_id).with_for_update()
    ).one_or_none()
    if document is None:
        raise NotFoundError(f"source document {document_id} not found")
    if document.bundle_file is not None:
        raise InvalidInputError(
            f"source document {document_id} was imported from a source text bundle; "
            "it is never re-fetched"
        )
    if not _is_current_parsed_url(document):
        raise InvalidInputError(
            f"source document {document_id} is not a current parsed URL document"
        )
    if interval is not None and not _is_due(
        document.last_checked_at, document.created_at, now=now, interval=interval
    ):
        raise InvalidInputError(f"source document {document_id} is not due for re-fetch")

    document.last_checked_at = now

    def failed(reason: str) -> RefetchOutcome:
        session.flush()
        return RefetchOutcome(document_id, RefetchResult.FAILED, reason=reason)

    assert document.source_url is not None  # the CHECK for origin = url
    try:
        url = validate_url(document.source_url)
    except InvalidInputError as exc:
        return failed(str(exc))
    fetch = fetch or _default_fetch
    try:
        data = fetch(url)
        if not data.startswith(PDF_MAGIC):
            raise http_fetch.FetchError("response is not a PDF (it does not start with %PDF-)")
    except http_fetch.FetchError as exc:
        return failed(exc.reason)

    content_hash = hashlib.sha256(data).hexdigest()
    if content_hash == document.content_hash:
        session.flush()
        return RefetchOutcome(document_id, RefetchResult.UNCHANGED)
    duplicate_of_id = session.scalar(
        select(SourceDocument.id)
        .where(
            SourceDocument.party_id == document.party_id,
            SourceDocument.content_hash == content_hash,
        )
        .order_by(SourceDocument.id)
        .limit(1)
    )
    if duplicate_of_id is not None:
        session.flush()
        return RefetchOutcome(
            document_id, RefetchResult.DUPLICATE, duplicate_of_id=duplicate_of_id
        )
    try:
        pages = extract_pages(data)
    except PdfTextError as exc:
        return failed(exc.reason)

    replacement = SourceDocument(
        party_id=document.party_id,
        origin=SourceDocumentOrigin.URL,
        status=SourceDocumentStatus.REGISTERED,
        source_url=document.source_url,
        original_filename=_filename_from_url(document.source_url),
        content_hash=content_hash,
        last_checked_at=now,
    )
    session.add(replacement)
    try:
        session.flush()
    except IntegrityError as exc:
        raise DuplicateError(
            f"party {document.party_id} already has a source document "
            f"with content hash {content_hash}"
        ) from exc
    _store_file(Path(files_dir), f"{content_hash}.pdf", data)
    set_parsed_pages(replacement, pages)
    document.replaced_by_id = replacement.id
    session.flush()
    return RefetchOutcome(document_id, RefetchResult.REPLACED, replacement=replacement)
