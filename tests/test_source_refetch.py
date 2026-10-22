"""live-mode-url-refetch: the re-fetch service, with a stub fetch and a fixed clock.

Scenarios 1-3, 5, 6 and 9 at the service level (the CLI is in
``tests/test_cli_source_refetch.py``). No test opens a socket or calls an LLM.
"""

import datetime as dt
import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from pdf_factory import blank_pdf, make_text_pdf
from pipeline_fixtures import offline_guard
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app.config import GenerationMode, LLMSettings
from ideology_app.elections import (
    InvalidInputError,
    NotFoundError,
    add_party,
    create_election,
)
from ideology_app.http_fetch import FetchError
from ideology_app.models import PipelineRun, PipelineRunStatus, SourceDocument
from ideology_app.models import SourceDocumentStatus as Status
from ideology_app.pdf_text import NO_TEXT_LAYER
from ideology_app.pipeline import queue_run_for_source_change
from ideology_app.source_documents import (
    RefetchResult,
    add_uploaded_document,
    add_url_document,
    due_url_document_ids,
    refetch_url_document,
)

URL = "https://example.org/docs/programa.pdf"
OTHER_URL = "https://example.org/otro/anexo.pdf"
V1 = make_text_pdf(["Programa electoral: vivienda.", "Sanidad pública."])
V2 = make_text_pdf(["Programa electoral actualizado: vivienda.", "Sanidad.", "Empleo."])
T0 = dt.datetime(2026, 10, 20, 6, 0, tzinfo=dt.UTC)
SIX_HOURS = dt.timedelta(hours=6)
LIVE = LLMSettings(provider="fake", model="fake-model")


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def files_dir(tmp_path: Path) -> Path:
    return tmp_path / "stored"


class Web:
    """A stub ``fetch``: one outcome (bytes or FetchError) per URL, calls recorded."""

    def __init__(self) -> None:
        self.outcomes: dict[str, bytes | FetchError] = {}
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        outcome = self.outcomes[url]
        if isinstance(outcome, FetchError):
            raise outcome
        return outcome


@pytest.fixture
def web() -> Web:
    return Web()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def party(session: Session) -> int:
    election = create_election(
        session, country="ES", type="general", date=dt.date(2027, 7, 23), name="Generales 2027"
    )
    first = add_party(session, election_id=election.id, name="Partido Alfa", short_name="PA")
    add_party(session, election_id=election.id, name="Bloque Beta", short_name="BB")
    session.commit()
    return first.id


def _add_url(
    session: Session,
    files_dir: Path,
    *,
    party_id: int = 1,
    url: str = URL,
    data: bytes = V1,
    created_at: dt.datetime = T0,
) -> int:
    document = add_url_document(
        session, party_id=party_id, url=url, files_dir=files_dir, fetch=lambda _u: data
    )
    document.created_at = created_at
    session.commit()
    return document.id


def _refetch(
    session: Session, document_id: int, web: Web, files_dir: Path, now: dt.datetime
):
    outcome = refetch_url_document(
        session, document_id, now=now, files_dir=files_dir, fetch=web
    )
    session.commit()
    return outcome


def _doc(session: Session, document_id: int) -> SourceDocument:
    session.expire_all()
    document = session.get(SourceDocument, document_id)
    assert document is not None
    return document


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    return value.replace(tzinfo=dt.UTC) if value and value.tzinfo is None else value


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _pages(document: SourceDocument) -> list[tuple[int, str]]:
    return [(p.page_number, p.text) for p in document.pages]


# Scenario 1: changed content -> new row, old row replaced, run queued in live


def test_changed_content_registers_a_replacement_and_queues_in_live(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    old_id = _add_url(session, files_dir)
    old_pages = _pages(_doc(session, old_id))
    web.outcomes[URL] = V2
    now = T0 + SIX_HOURS

    outcome = refetch_url_document(session, old_id, now=now, files_dir=files_dir, fetch=web)
    assert outcome.result is RefetchResult.REPLACED
    assert outcome.replacement is not None
    trigger = queue_run_for_source_change(
        session, outcome.replacement, generation_mode=GenerationMode.LIVE, llm=LIVE
    )
    new_id = outcome.replacement.id
    session.commit()

    assert web.calls == [URL]
    new = _doc(session, new_id)
    assert new_id > old_id
    assert (new.party_id, new.origin.value, new.status, new.source_url) == (
        party, "url", Status.PARSED, URL
    )
    assert new.content_hash == _sha(V2)
    assert new.original_filename == "programa.pdf"
    assert new.page_count == 3
    assert [t for _, t in _pages(new)][0] == "Programa electoral actualizado: vivienda."
    assert new.replaced_by_id is None
    assert _aware(new.last_checked_at) == now
    assert (files_dir / f"{_sha(V2)}.pdf").read_bytes() == V2

    old = _doc(session, old_id)
    assert old.replaced_by_id == new_id
    assert old.content_hash == _sha(V1)
    assert old.status is Status.PARSED
    assert _pages(old) == old_pages
    assert _aware(old.last_checked_at) == now
    assert (files_dir / f"{_sha(V1)}.pdf").read_bytes() == V1

    assert trigger.newly_queued and trigger.run_id is not None
    runs = session.scalars(select(PipelineRun)).all()
    assert [(r.id, r.status) for r in runs] == [(trigger.run_id, PipelineRunStatus.QUEUED)]


def test_changed_content_in_precomputed_queues_nothing(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    old_id = _add_url(session, files_dir)
    web.outcomes[URL] = V2

    outcome = refetch_url_document(
        session, old_id, now=T0 + SIX_HOURS, files_dir=files_dir, fetch=web
    )
    assert outcome.replacement is not None
    trigger = queue_run_for_source_change(
        session, outcome.replacement, generation_mode=GenerationMode.PRECOMPUTED, llm=None
    )
    session.commit()

    assert trigger.run_id is None
    assert _doc(session, old_id).replaced_by_id == outcome.document_id + 1
    assert _count(session, PipelineRun) == 0


# Scenario 2: same content -> only last_checked_at


def test_same_content_records_only_the_check_time(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    old_id = _add_url(session, files_dir)
    before = _doc(session, old_id)
    snapshot = (before.content_hash, before.page_count, _pages(before), before.status)
    stored = sorted(p.name for p in files_dir.iterdir())
    web.outcomes[URL] = V1
    now = T0 + SIX_HOURS

    outcome = _refetch(session, old_id, web, files_dir, now)

    assert outcome.result is RefetchResult.UNCHANGED
    assert outcome.replacement is None and outcome.reason is None
    after = _doc(session, old_id)
    assert (after.content_hash, after.page_count, _pages(after), after.status) == snapshot
    assert after.replaced_by_id is None
    assert _aware(after.last_checked_at) == now
    assert _count(session, SourceDocument) == 1
    assert _count(session, PipelineRun) == 0
    assert sorted(p.name for p in files_dir.iterdir()) == stored


# Scenario 3: due rule with a controlled clock


def test_due_rule_counts_from_created_then_from_the_last_check(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    doc_id = _add_url(session, files_dir)

    def due(now: dt.datetime, interval: dt.timedelta = SIX_HOURS) -> list[int]:
        return due_url_document_ids(session, now=now, interval=interval)

    assert due(T0 + dt.timedelta(hours=5, minutes=59)) == []
    assert due(T0 + SIX_HOURS) == [doc_id]
    assert due(T0 + dt.timedelta(hours=1), dt.timedelta(hours=1)) == [doc_id]

    web.outcomes[URL] = V1
    t1 = T0 + dt.timedelta(hours=7)
    _refetch(session, doc_id, web, files_dir, t1)

    assert due(t1 + dt.timedelta(hours=5, minutes=59)) == []
    assert due(t1 + SIX_HOURS) == [doc_id]


def test_due_accepts_naive_and_aware_stored_values(
    session: Session, party: int, files_dir: Path
) -> None:
    doc_id = _add_url(session, files_dir, created_at=T0.replace(tzinfo=None))

    assert due_url_document_ids(session, now=T0 + SIX_HOURS, interval=SIX_HOURS) == [doc_id]


def test_only_current_parsed_url_documents_are_due(
    session: Session, party: int, web: Web, files_dir: Path, tmp_path: Path
) -> None:
    url_id = _add_url(session, files_dir)
    upload = tmp_path / "subido.pdf"
    upload.write_bytes(make_text_pdf(["Documento subido."]))
    upload_doc = add_uploaded_document(
        session, party_id=party, file_path=upload, files_dir=files_dir
    )
    upload_doc.created_at = T0
    failed = add_url_document(
        session,
        party_id=party,
        url=OTHER_URL,
        files_dir=files_dir,
        fetch=lambda _u: (_ for _ in ()).throw(FetchError("HTTP 404: Not Found")),
    )
    failed.created_at = T0
    session.commit()
    assert failed.status is Status.FAILED

    later = T0 + dt.timedelta(days=1)
    assert due_url_document_ids(session, now=later, interval=SIX_HOURS) == [url_id]

    web.outcomes[URL] = V2
    replacement_id = _refetch(session, url_id, web, files_dir, later).replacement.id
    # The replaced row is never due again; its replacement counts from its check.
    much_later = later + dt.timedelta(days=1)
    assert due_url_document_ids(session, now=much_later, interval=SIX_HOURS) == [
        replacement_id
    ]
    with pytest.raises(InvalidInputError, match="not a current parsed URL document"):
        refetch_url_document(session, url_id, now=much_later, files_dir=files_dir, fetch=web)
    with pytest.raises(InvalidInputError, match="not a current parsed URL document"):
        refetch_url_document(
            session, upload_doc.id, now=much_later, files_dir=files_dir, fetch=web
        )
    with pytest.raises(NotFoundError, match="source document 99 not found"):
        refetch_url_document(session, 99, now=much_later, files_dir=files_dir, fetch=web)


def test_a_bundle_url_document_is_never_due_nor_refetched(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    """source-text-bundle Scenario 10: a URL row imported from a bundle is never fetched."""
    url_id = _add_url(session, files_dir)
    _doc(session, url_id).bundle_file = "pa.md"
    session.commit()

    much_later = T0 + dt.timedelta(days=365)
    assert due_url_document_ids(session, now=much_later, interval=SIX_HOURS) == []
    with pytest.raises(InvalidInputError) as caught:
        refetch_url_document(session, url_id, now=much_later, files_dir=files_dir, fetch=web)
    assert str(caught.value) == (
        f"source document {url_id} was imported from a source text bundle; "
        "it is never re-fetched"
    )
    assert web.calls == []
    assert _doc(session, url_id).last_checked_at is None


def test_refetch_with_an_interval_refuses_a_document_not_due(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    doc_id = _add_url(session, files_dir)

    with pytest.raises(InvalidInputError, match="not due"):
        refetch_url_document(
            session,
            doc_id,
            now=T0 + dt.timedelta(hours=1),
            files_dir=files_dir,
            fetch=web,
            interval=SIX_HOURS,
        )
    assert web.calls == []


# Scenario 5: failures keep the old document


FAILURES: dict[str, tuple[Callable[[], bytes | FetchError], str]] = {
    "http-404": (lambda: FetchError("HTTP 404: Not Found"), "HTTP 404: Not Found"),
    "not-pdf": (
        lambda: b"<html>moved</html>",
        "response is not a PDF (it does not start with %PDF-)",
    ),
    "no-text-layer": (lambda: blank_pdf(2), NO_TEXT_LAYER),
}


@pytest.mark.parametrize("case", FAILURES, ids=list(FAILURES))
def test_failure_keeps_the_old_document_and_writes_only_the_check_time(
    session: Session, party: int, web: Web, files_dir: Path, case: str
) -> None:
    make, reason = FAILURES[case]
    doc_id = _add_url(session, files_dir)
    before = _doc(session, doc_id)
    snapshot = (before.content_hash, before.page_count, _pages(before), before.status)
    stored = sorted(p.name for p in files_dir.iterdir())
    web.outcomes[URL] = make()
    now = T0 + SIX_HOURS

    outcome = _refetch(session, doc_id, web, files_dir, now)

    assert outcome.result is RefetchResult.FAILED
    assert outcome.reason == reason
    assert outcome.replacement is None
    after = _doc(session, doc_id)
    assert (after.content_hash, after.page_count, _pages(after), after.status) == snapshot
    assert after.replaced_by_id is None and after.failure_reason is None
    assert _aware(after.last_checked_at) == now
    assert _count(session, SourceDocument) == 1
    assert _count(session, PipelineRun) == 0
    assert sorted(p.name for p in files_dir.iterdir()) == stored


def test_an_invalid_stored_url_is_a_failure_without_fetching(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    doc_id = _add_url(session, files_dir)
    _doc(session, doc_id).source_url = "https://user:secret@example.org/programa.pdf"
    session.commit()

    outcome = _refetch(session, doc_id, web, files_dir, T0 + SIX_HOURS)

    assert outcome.result is RefetchResult.FAILED
    assert outcome.reason is not None and "must not contain credentials" in outcome.reason
    assert web.calls == []
    assert _aware(_doc(session, doc_id).last_checked_at) == T0 + SIX_HOURS


# Scenario 6: the fetched bytes match another document of the same Party


def test_reverted_content_is_reported_as_a_duplicate(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    d1 = _add_url(session, files_dir)
    web.outcomes[URL] = V2
    d2 = _refetch(session, d1, web, files_dir, T0 + SIX_HOURS).replacement.id
    web.outcomes[URL] = V1
    now = T0 + 2 * SIX_HOURS

    outcome = _refetch(session, d2, web, files_dir, now)

    assert outcome.result is RefetchResult.DUPLICATE
    assert outcome.duplicate_of_id == d1
    assert _count(session, SourceDocument) == 2
    assert _doc(session, d2).replaced_by_id is None
    assert _doc(session, d1).replaced_by_id == d2
    assert _aware(_doc(session, d2).last_checked_at) == now
    assert _count(session, PipelineRun) == 0


def test_content_of_an_upload_of_the_same_party_is_a_duplicate(
    session: Session, party: int, web: Web, files_dir: Path, tmp_path: Path
) -> None:
    doc_id = _add_url(session, files_dir)
    upload = tmp_path / "v2.pdf"
    upload.write_bytes(V2)
    upload_id = add_uploaded_document(
        session, party_id=party, file_path=upload, files_dir=files_dir
    ).id
    session.commit()
    web.outcomes[URL] = V2

    outcome = _refetch(session, doc_id, web, files_dir, T0 + SIX_HOURS)

    assert (outcome.result, outcome.duplicate_of_id) == (RefetchResult.DUPLICATE, upload_id)
    assert _doc(session, doc_id).replaced_by_id is None


def test_same_bytes_in_another_party_are_a_normal_replacement(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    _add_url(session, files_dir, party_id=2, url=OTHER_URL, data=V2)
    doc_id = _add_url(session, files_dir)
    web.outcomes[URL] = V2

    outcome = _refetch(session, doc_id, web, files_dir, T0 + SIX_HOURS)

    assert outcome.result is RefetchResult.REPLACED


# Scenario 9: scope and atomicity


def test_election_filter(session: Session, party: int, files_dir: Path) -> None:
    doc_id = _add_url(session, files_dir)
    other = create_election(
        session, country="ES", type="general", date=dt.date(2031, 7, 23), name="Generales 2031"
    )
    gamma = add_party(session, election_id=other.id, name="Partido Gamma", short_name="PG")
    session.commit()
    other_doc = _add_url(session, files_dir, party_id=gamma.id, url=OTHER_URL)
    now = T0 + SIX_HOURS

    assert due_url_document_ids(session, now=now, interval=SIX_HOURS) == [doc_id, other_doc]
    assert due_url_document_ids(session, now=now, interval=SIX_HOURS, election_id=1) == [doc_id]
    assert due_url_document_ids(
        session, now=now, interval=SIX_HOURS, election_id=other.id
    ) == [other_doc]
    with pytest.raises(NotFoundError, match="election 9 not found"):
        due_url_document_ids(session, now=now, interval=SIX_HOURS, election_id=9)


def test_rollback_keeps_neither_the_replacement_nor_the_marker(
    session: Session, party: int, web: Web, files_dir: Path
) -> None:
    doc_id = _add_url(session, files_dir)
    web.outcomes[URL] = V2

    outcome = refetch_url_document(
        session, doc_id, now=T0 + SIX_HOURS, files_dir=files_dir, fetch=web
    )
    assert outcome.result is RefetchResult.REPLACED
    session.rollback()

    assert _count(session, SourceDocument) == 1
    old = _doc(session, doc_id)
    assert old.replaced_by_id is None and old.last_checked_at is None
