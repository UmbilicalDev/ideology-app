"""Domain service for Source Documents (Party manifestos).

Functions take a Session and leave committing to the caller, like
``ideology_app.elections``. Uploaded files are stored content-addressed as
``<files_dir>/<content_hash>.pdf`` and are never overwritten or edited.
"""

import hashlib
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ideology_app.elections import DuplicateError, InvalidInputError, NotFoundError
from ideology_app.models import (
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


def _get_party(session: Session, party_id: int) -> Party:
    party = session.get(Party, party_id)
    if party is None:
        raise NotFoundError(f"party {party_id} not found")
    return party


def _read_pdf_file(file_path: Path) -> bytes:
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
    data = _read_pdf_file(Path(file_path))
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

    _store_file(Path(files_dir), f"{content_hash}.pdf", data)
    document.status = SourceDocumentStatus.FETCHED

    try:
        pages = extract_pages(data)
    except PdfTextError as exc:
        document.status = SourceDocumentStatus.FAILED
        document.failure_reason = exc.reason
        document.page_count = exc.page_count
    else:
        document.pages = [
            SourceDocumentPage(page_number=number, text=text)
            for number, text in enumerate(pages, start=1)
        ]
        document.page_count = len(pages)
        document.status = SourceDocumentStatus.PARSED
    session.flush()
    return document


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
