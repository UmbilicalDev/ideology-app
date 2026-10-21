"""Import a Source Text Bundle into a database, and check a database against one.

``import_bundle`` builds the Election, its Parties and their ``parsed`` Source
Documents from a bundle that ``source_bundle.read_bundle`` already checked. It
is idempotent: an unchanged file is reported ``unchanged``; a changed file
registers a replacement row (the old row gets only ``replaced_by_id``, like a
URL re-fetch). Every conflict with the database is found before the first
write. Functions take a Session and never commit.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app import elections
from ideology_app.elections import ElectionsError, InvalidInputError
from ideology_app.models import (
    Election,
    Party,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentStatus,
)
from ideology_app.source_bundle import Bundle, BundleParty
from ideology_app.source_documents import set_parsed_pages, validate_url

FRESH_DATABASE_FIX = "import into a fresh database"


class BundleConflictError(ElectionsError):
    """The database disagrees with the bundle in a way an import must not override."""


class DocumentStatus(StrEnum):
    ADDED = "added"
    REPLACED = "replaced"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class PartyOutcome:
    """What the import did for one manifest Party (plain data, safe after the session)."""

    short_name: str
    party_id: int
    party_created: bool
    status: DocumentStatus
    document_id: int
    page_count: int
    replaced_document_id: int | None = None


@dataclass
class ImportReport:
    """The result of ``import_bundle``.

    ``new_documents`` are the added or replacing rows, still attached to the
    session (for the live trigger); ``left_alone`` the ``(short_name, id)`` of
    the Election's Parties that are not in the bundle.
    """

    slug: str
    election_id: int
    election_created: bool
    outcomes: list[PartyOutcome] = field(default_factory=list)
    left_alone: list[tuple[str, int]] = field(default_factory=list)
    new_documents: list[SourceDocument] = field(default_factory=list)

    def count(self, status: DocumentStatus) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is status)


def _find_election(session: Session, bundle: Bundle) -> Election | None:
    return session.scalars(
        select(Election).where(
            Election.country == bundle.country,
            Election.type == bundle.type,
            Election.date == bundle.date,
        )
    ).one_or_none()


def _current_parsed(session: Session, party_id: int) -> Sequence[SourceDocument]:
    return session.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.party_id == party_id,
            SourceDocument.status == SourceDocumentStatus.PARSED,
            SourceDocument.replaced_by_id.is_(None),
        )
        .order_by(SourceDocument.id)
    ).all()


def _checked_url(entry: BundleParty) -> str | None:
    url = entry.text.source_url
    if url is None:
        return None
    try:
        valid = validate_url(url)
    except InvalidInputError as exc:
        raise InvalidInputError(f"{entry.file}: source_url: {exc}") from None
    if valid != url:
        raise InvalidInputError(
            f"{entry.file}: source_url must not have leading or trailing whitespace"
        )
    return url


@dataclass
class _Plan:
    entry: BundleParty
    party: Party | None
    current: SourceDocument | None


def _plan(session: Session, bundle: Bundle, election: Election | None) -> list[_Plan]:
    """Check every manifest Party against the database. Writes nothing."""
    for entry in bundle.parties:
        _checked_url(entry)
    if election is None:
        return [_Plan(entry, None, None) for entry in bundle.parties]
    if election.name != bundle.name:
        raise BundleConflictError(
            f"election {bundle.slug} (id {election.id}) exists with name {election.name!r}, "
            f"but the bundle names it {bundle.name!r}; {FRESH_DATABASE_FIX}"
        )
    parties = {p.short_name: p for p in election.parties}
    by_name = {p.name: p for p in election.parties}
    plans: list[_Plan] = []
    for entry in bundle.parties:
        party = parties.get(entry.short_name)
        if party is None:
            other = by_name.get(entry.name)
            if other is not None:
                raise BundleConflictError(
                    f"party {entry.name!r} exists as {other.short_name} (id {other.id}), "
                    f"but the bundle names it {entry.short_name}; {FRESH_DATABASE_FIX}"
                )
            plans.append(_Plan(entry, None, None))
            continue
        if party.name != entry.name:
            raise BundleConflictError(
                f"party {entry.short_name} (id {party.id}) exists with name {party.name!r}, "
                f"but the bundle names it {entry.name!r}; {FRESH_DATABASE_FIX}"
            )
        current_rows = _current_parsed(session, party.id)
        not_bundle = [d for d in current_rows if d.bundle_file is None]
        if not_bundle:
            raise BundleConflictError(
                f"party {entry.short_name} (id {party.id}) has source document "
                f"{not_bundle[0].id}, which was not imported from a bundle; "
                f"{FRESH_DATABASE_FIX}"
            )
        if len(current_rows) > 1:
            raise BundleConflictError(
                f"party {entry.short_name} (id {party.id}) has {len(current_rows)} current "
                f"bundle documents ({', '.join(str(d.id) for d in current_rows)}); "
                f"{FRESH_DATABASE_FIX}"
            )
        current = current_rows[0] if current_rows else None
        if current is None or current.content_hash != entry.text.content_hash:
            same_bytes = session.scalars(
                select(SourceDocument.id).where(
                    SourceDocument.party_id == party.id,
                    SourceDocument.content_hash == entry.text.content_hash,
                )
            ).first()
            if same_bytes is not None:
                raise BundleConflictError(
                    f"party {entry.short_name} (id {party.id}): {entry.file} has the same "
                    f"content as older source document {same_bytes} (a reverted file); "
                    f"{FRESH_DATABASE_FIX}"
                )
        plans.append(_Plan(entry, party, current))
    return plans


def _new_document(party_id: int, entry: BundleParty) -> SourceDocument:
    url = entry.text.source_url
    document = SourceDocument(
        party_id=party_id,
        origin=SourceDocumentOrigin.URL if url is not None else SourceDocumentOrigin.UPLOAD,
        status=SourceDocumentStatus.REGISTERED,
        source_url=url,
        original_filename=entry.file,
        bundle_file=entry.file,
        content_hash=entry.text.content_hash,
    )
    set_parsed_pages(document, entry.text.pages)
    return document


def import_bundle(session: Session, bundle: Bundle) -> ImportReport:
    """Create or update ``bundle``'s Election, Parties and Source Documents. Never commits.

    Raises BundleConflictError (or InvalidInputError for a bad ``source_url``)
    before anything is written when the database conflicts with the bundle.
    """
    election = _find_election(session, bundle)
    plans = _plan(session, bundle, election)

    election_created = election is None
    if election is None:
        election = elections.create_election(
            session,
            country=bundle.country,
            type=bundle.type.value,
            date=bundle.date,
            name=bundle.name,
        )
    report = ImportReport(
        slug=bundle.slug, election_id=election.id, election_created=election_created
    )
    for plan in plans:
        entry = plan.entry
        party = plan.party
        party_created = party is None
        if party is None:
            party = elections.add_party(
                session, election_id=election.id, name=entry.name, short_name=entry.short_name
            )
        current = plan.current
        if current is not None and current.content_hash == entry.text.content_hash:
            report.outcomes.append(
                PartyOutcome(
                    entry.short_name, party.id, party_created, DocumentStatus.UNCHANGED,
                    current.id, current.page_count or 0,
                )
            )
            continue
        document = _new_document(party.id, entry)
        session.add(document)
        session.flush()
        if current is not None:
            current.replaced_by_id = document.id
            session.flush()
        report.new_documents.append(document)
        report.outcomes.append(
            PartyOutcome(
                entry.short_name,
                party.id,
                party_created,
                DocumentStatus.ADDED if current is None else DocumentStatus.REPLACED,
                document.id,
                len(entry.text.pages),
                replaced_document_id=None if current is None else current.id,
            )
        )
    listed = {entry.short_name for entry in bundle.parties}
    report.left_alone = [
        (p.short_name, p.id)
        for p in session.scalars(
            select(Party).where(Party.election_id == election.id).order_by(Party.id)
        )
        if p.short_name not in listed
    ]
    return report


def check_against_bundle(session: Session, bundle: Bundle) -> list[str]:
    """Every divergence between the database and ``bundle`` (empty: they match). Read-only."""
    election = _find_election(session, bundle)
    if election is None:
        return [f"election {bundle.slug} not found"]
    problems: list[str] = []
    if election.name != bundle.name:
        problems.append(
            f"election {bundle.slug} (id {election.id}): name {election.name!r} differs "
            f"from the bundle's {bundle.name!r}"
        )
    parties = {p.short_name: p for p in election.parties}
    for entry in bundle.parties:
        party = parties.get(entry.short_name)
        if party is None:
            problems.append(f"party {entry.short_name} not found")
            continue
        label = f"party {entry.short_name} (id {party.id})"
        if party.name != entry.name:
            problems.append(f"{label}: name {party.name!r} differs from {entry.name!r}")
        current_rows = _current_parsed(session, party.id)
        for document in current_rows:
            if document.bundle_file is None:
                problems.append(
                    f"{label}: source document {document.id} was not imported from a bundle"
                )
        bundle_rows = [d for d in current_rows if d.bundle_file is not None]
        if not bundle_rows:
            problems.append(f"{label}: no current source document for {entry.file}")
            continue
        if len(bundle_rows) > 1:
            problems.append(
                f"{label}: {len(bundle_rows)} current bundle documents "
                f"({', '.join(str(d.id) for d in bundle_rows)})"
            )
        for document in bundle_rows:
            problems.extend(_document_problems(label, document, entry))
    return problems


def _document_problems(label: str, document: SourceDocument, entry: BundleParty) -> list[str]:
    where = f"{label}: source document {document.id}"
    problems: list[str] = []
    if document.bundle_file != entry.file:
        problems.append(f"{where}: bundle_file {document.bundle_file!r} is not {entry.file!r}")
    if document.content_hash != entry.text.content_hash:
        problems.append(f"{where}: content_hash differs from the SHA-256 of {entry.file}")
    if document.source_url != entry.text.source_url:
        problems.append(f"{where}: source_url differs from {entry.file}")
    expected_pages = entry.text.pages
    if document.page_count != len(expected_pages):
        problems.append(
            f"{where}: page_count {document.page_count} differs from {len(expected_pages)}"
        )
    stored = [(page.page_number, page.text) for page in document.pages]
    if [number for number, _ in stored] != list(range(1, len(expected_pages) + 1)):
        problems.append(
            f"{where}: has {len(stored)} page rows, {entry.file} has {len(expected_pages)} pages"
        )
    for number, text in stored:
        if 1 <= number <= len(expected_pages) and text != expected_pages[number - 1]:
            problems.append(f"{where}: page {number} text differs from {entry.file}")
    return problems
