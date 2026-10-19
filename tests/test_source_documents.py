import datetime as dt
import hashlib
from pathlib import Path

import pytest
from pdf_factory import blank_pdf, encrypt_pdf, make_text_pdf
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app import elections, source_documents
from ideology_app.elections import DuplicateError, InvalidInputError, NotFoundError
from ideology_app.models import (
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentPage,
    SourceDocumentStatus,
)
from ideology_app.pdf_text import NO_TEXT_LAYER
from ideology_app.source_documents import add_uploaded_document, get_document, list_documents

TEXT_PAGES = [
    "Programa electoral\nSubir el salario mínimo por encima de la inflación.",
    "Página dos: educación pública (gratuita).",
]


@pytest.fixture
def parties(session: Session) -> tuple[int, int]:
    election = elections.create_election(
        session, country="ES", type="general", date=dt.date(2023, 7, 23), name="Generales 2023"
    )
    first = elections.add_party(session, election_id=election.id, name="Sumar", short_name="SUMAR")
    second = elections.add_party(
        session, election_id=election.id, name="Partido Popular", short_name="PP"
    )
    session.commit()
    return first.id, second.id


@pytest.fixture
def files_dir(tmp_path: Path) -> Path:
    return tmp_path / "stored"


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_text_pdf_is_parsed(session: Session, parties, files_dir: Path, tmp_path: Path) -> None:
    data = make_text_pdf(TEXT_PAGES)
    path = _write(tmp_path, "manifesto.pdf", data)

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )
    session.commit()

    expected_hash = hashlib.sha256(data).hexdigest()
    session.expire_all()
    stored = get_document(session, document.id)
    assert stored.origin is SourceDocumentOrigin.UPLOAD
    assert stored.status is SourceDocumentStatus.PARSED
    assert stored.original_filename == "manifesto.pdf"
    assert stored.page_count == 2
    assert stored.content_hash == expected_hash
    assert stored.failure_reason is None
    assert stored.created_at is not None
    assert [(p.page_number, p.text) for p in stored.pages] == [
        (1, TEXT_PAGES[0]),
        (2, TEXT_PAGES[1]),
    ]
    assert "mínimo" in stored.pages[0].text
    assert stored.stored_filename == f"{expected_hash}.pdf"
    assert (files_dir / f"{expected_hash}.pdf").read_bytes() == data
    assert [p.name for p in files_dir.iterdir()] == [f"{expected_hash}.pdf"]


@pytest.mark.parametrize(
    "data, reason, page_count",
    [
        (make_text_pdf([None, None]), NO_TEXT_LAYER, 2),
        (blank_pdf(), NO_TEXT_LAYER, 1),
        (encrypt_pdf(make_text_pdf(["x"]), "secret"), "PDF is encrypted", None),
    ],
    ids=["shapes-only", "blank", "encrypted"],
)
def test_unextractable_pdf_is_committed_as_failed(
    session: Session, parties, files_dir: Path, tmp_path: Path, data: bytes, reason: str,
    page_count: int | None,
) -> None:
    path = _write(tmp_path, "scan.pdf", data)

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )
    session.commit()

    session.expire_all()
    stored = get_document(session, document.id)
    assert stored.status is SourceDocumentStatus.FAILED
    assert stored.failure_reason == reason
    assert stored.page_count == page_count
    assert stored.content_hash == hashlib.sha256(data).hexdigest()
    assert stored.pages == []
    assert (files_dir / f"{stored.content_hash}.pdf").read_bytes() == data


@pytest.mark.parametrize(
    "data",
    [b"%PDF-1.4\ngarbage", make_text_pdf(TEXT_PAGES)[:400]],
    ids=["corrupt", "truncated"],
)
def test_unreadable_pdf_fails(
    session: Session, parties, files_dir: Path, tmp_path: Path, data: bytes
) -> None:
    path = _write(tmp_path, "broken.pdf", data)

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )

    assert document.status is SourceDocumentStatus.FAILED
    assert document.failure_reason.startswith("could not read PDF:")
    assert document.pages == []


def test_empty_password_pdf_is_parsed(
    session: Session, parties, files_dir: Path, tmp_path: Path
) -> None:
    path = _write(tmp_path, "open.pdf", encrypt_pdf(make_text_pdf(["abierto"]), ""))

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )

    assert document.status is SourceDocumentStatus.PARSED
    assert [p.text for p in document.pages] == ["abierto"]


def _assert_nothing_written(session: Session, files_dir: Path) -> None:
    session.rollback()
    assert _count(session, SourceDocument) == 0
    assert _count(session, SourceDocumentPage) == 0
    assert not files_dir.exists() or list(files_dir.iterdir()) == []


def test_unknown_party_is_rejected(session: Session, parties, files_dir: Path, tmp_path: Path) -> None:
    path = _write(tmp_path, "m.pdf", make_text_pdf(TEXT_PAGES))

    with pytest.raises(NotFoundError, match="party 999 not found"):
        add_uploaded_document(session, party_id=999, file_path=path, files_dir=files_dir)

    _assert_nothing_written(session, files_dir)


@pytest.mark.parametrize(
    "name, data, message",
    [
        ("missing.pdf", None, "not found"),
        ("empty.pdf", b"", "is empty"),
        ("notes.pdf", b"just some text\n", "is not a PDF"),
    ],
    ids=["missing", "empty", "not-a-pdf"],
)
def test_bad_file_is_rejected(
    session: Session, parties, files_dir: Path, tmp_path: Path, name: str,
    data: bytes | None, message: str,
) -> None:
    path = tmp_path / name
    if data is not None:
        path.write_bytes(data)

    with pytest.raises(InvalidInputError, match=message) as info:
        add_uploaded_document(session, party_id=parties[0], file_path=path, files_dir=files_dir)

    assert name in str(info.value)
    _assert_nothing_written(session, files_dir)


def test_directory_is_rejected(session: Session, parties, files_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="not found"):
        add_uploaded_document(
            session, party_id=parties[0], file_path=tmp_path, files_dir=files_dir
        )


def test_too_large_file_is_rejected(
    session: Session, parties, files_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_text_pdf(TEXT_PAGES)
    path = _write(tmp_path, "big.pdf", data)
    monkeypatch.setattr(source_documents, "MAX_UPLOAD_BYTES", len(data) - 1)

    with pytest.raises(InvalidInputError, match="too large"):
        add_uploaded_document(session, party_id=parties[0], file_path=path, files_dir=files_dir)

    _assert_nothing_written(session, files_dir)


def test_file_at_size_limit_is_accepted(
    session: Session, parties, files_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_text_pdf(TEXT_PAGES)
    path = _write(tmp_path, "edge.pdf", data)
    monkeypatch.setattr(source_documents, "MAX_UPLOAD_BYTES", len(data))

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )

    assert document.status is SourceDocumentStatus.PARSED


def test_default_limit_is_50_mib() -> None:
    assert source_documents.MAX_UPLOAD_BYTES == 50 * 1024 * 1024


def test_same_file_twice_for_same_party_is_a_duplicate(
    session: Session, parties, files_dir: Path, tmp_path: Path
) -> None:
    data = make_text_pdf(TEXT_PAGES)
    first_path = _write(tmp_path, "a.pdf", data)
    second_path = _write(tmp_path, "b.pdf", data)
    first = add_uploaded_document(
        session, party_id=parties[0], file_path=first_path, files_dir=files_dir
    )
    session.commit()
    first_id = first.id
    content_hash = hashlib.sha256(data).hexdigest()

    with pytest.raises(DuplicateError) as info:
        add_uploaded_document(
            session, party_id=parties[0], file_path=second_path, files_dir=files_dir
        )

    assert str(info.value) == (
        f"party {parties[0]} already has a source document with content hash {content_hash}"
    )
    # The session is still usable and nothing changed.
    assert [d.id for d in list_documents(session, parties[0])] == [first_id]
    assert _count(session, SourceDocumentPage) == 2
    assert list(files_dir.iterdir()) == [files_dir / f"{content_hash}.pdf"]


def test_same_file_for_another_party_shares_the_stored_file(
    session: Session, parties, files_dir: Path, tmp_path: Path
) -> None:
    data = make_text_pdf(TEXT_PAGES)
    path = _write(tmp_path, "m.pdf", data)

    first = add_uploaded_document(session, party_id=parties[0], file_path=path, files_dir=files_dir)
    second = add_uploaded_document(session, party_id=parties[1], file_path=path, files_dir=files_dir)
    session.commit()

    assert first.id != second.id
    assert first.content_hash == second.content_hash
    assert second.status is SourceDocumentStatus.PARSED
    assert list(files_dir.iterdir()) == [files_dir / f"{first.content_hash}.pdf"]


def test_existing_stored_file_is_not_overwritten(
    session: Session, parties, files_dir: Path, tmp_path: Path
) -> None:
    data = make_text_pdf(TEXT_PAGES)
    content_hash = hashlib.sha256(data).hexdigest()
    files_dir.mkdir()
    existing = files_dir / f"{content_hash}.pdf"
    existing.write_bytes(data)
    before = existing.stat().st_mtime_ns

    add_uploaded_document(
        session, party_id=parties[0], file_path=_write(tmp_path, "m.pdf", data), files_dir=files_dir
    )

    assert existing.stat().st_mtime_ns == before
    assert sorted(p.name for p in files_dir.iterdir()) == [f"{content_hash}.pdf"]


def test_long_filename_is_truncated(
    session: Session, parties, files_dir: Path, tmp_path: Path
) -> None:
    name = "m" * 250 + ".pdf"
    path = _write(tmp_path, name, make_text_pdf(TEXT_PAGES))

    document = add_uploaded_document(
        session, party_id=parties[0], file_path=path, files_dir=files_dir
    )

    assert document.original_filename == name[:255]


def test_list_and_get(session: Session, parties, files_dir: Path, tmp_path: Path) -> None:
    a = add_uploaded_document(
        session, party_id=parties[0], file_path=_write(tmp_path, "a.pdf", make_text_pdf(["a"])),
        files_dir=files_dir,
    )
    b = add_uploaded_document(
        session, party_id=parties[0], file_path=_write(tmp_path, "b.pdf", blank_pdf()),
        files_dir=files_dir,
    )
    session.commit()

    assert [d.id for d in list_documents(session, parties[0])] == [a.id, b.id]
    assert list_documents(session, parties[1]) == []
    with pytest.raises(NotFoundError, match="party 999 not found"):
        list_documents(session, 999)
    with pytest.raises(NotFoundError, match="source document 999 not found"):
        get_document(session, 999)
