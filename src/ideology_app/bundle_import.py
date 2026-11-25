"""Import a Source Text Bundle into a database, and check a database against one.

``import_bundle`` builds the Election, its Parties and their ``parsed`` Source
Documents from a bundle that ``source_bundle.read_bundle`` already checked. It
is idempotent: an unchanged file is reported ``unchanged``; a changed file
registers a replacement row (the old row gets only ``replaced_by_id``, like a
URL re-fetch). Every conflict with the database is found before the first
write. The bundle is authoritative for its Parties' logos: each listed Party's
logo is made equal to the manifest's (no ``logo`` key clears it); Parties not
in the bundle are untouched, and a logo change never touches a Dataset Version
or queues a run. Functions take a Session and never commit.

A format-2 bundle (constituencies-and-candidatures) also declares candidatures
and document scopes: ``import_bundle`` and ``check_against_bundle`` dispatch on
``bundle.format``, and the format-1 paths are unchanged. In format 2 the
manifest is authoritative for the candidatures of every Party of the Election
(an unlisted Party loses its candidatures, its row and documents are left
alone) and for the scope of each listed Party's current document rows. One
Source Document row is created per Party x document (D1). Later features read
candidatures and scopes only through ``candidatures_by_party`` and
``document_scopes``.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ideology_app import elections
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.elections import ElectionsError, InvalidInputError
from ideology_app.models import (
    Candidature,
    Election,
    Party,
    SourceDocument,
    SourceDocumentConstituency,
    SourceDocumentOrigin,
    SourceDocumentStatus,
)
from ideology_app.party_logos import LogoChange
from ideology_app.source_bundle import (
    MANIFEST_NAME,
    Bundle,
    BundleDocument,
    BundleParty,
    SourceText,
    document_scope,
)
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
    logo_change: LogoChange = LogoChange.NONE
    logo_file: str | None = None
    logo_media_type: str | None = None
    logo_size: int | None = None


@dataclass(frozen=True)
class CandidatureOutcome:
    """What a format-2 import did for one manifest Party: its row, candidatures and logo."""

    short_name: str
    party_id: int
    party_created: bool
    constituencies: int
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    logo_change: LogoChange = LogoChange.NONE
    logo_file: str | None = None
    logo_media_type: str | None = None
    logo_size: int | None = None


@dataclass(frozen=True)
class DocumentOutcome:
    """What a format-2 import did for one Party x document row, and its scope."""

    file: str
    short_name: str
    party_id: int
    status: DocumentStatus
    document_id: int
    page_count: int
    scope: int
    scope_added: tuple[str, ...] = ()
    scope_removed: tuple[str, ...] = ()
    replaced_document_id: int | None = None


@dataclass
class ImportReport:
    """The result of ``import_bundle``.

    ``new_documents`` are the added or replacing rows, still attached to the
    session (for the live trigger); ``left_alone`` the ``(short_name, id)`` of
    the Election's Parties that are not in the bundle. Format 1 fills
    ``outcomes``; format 2 fills ``candidatures``, ``documents``,
    ``removed_candidatures`` (``(short_name, id, codes)`` of unlisted Parties
    that lost candidatures) and ``candidature_source_change``
    (``set``, ``changed`` or ``unchanged``).
    """

    slug: str
    election_id: int
    election_created: bool
    outcomes: list[PartyOutcome] = field(default_factory=list)
    left_alone: list[tuple[str, int]] = field(default_factory=list)
    new_documents: list[SourceDocument] = field(default_factory=list)
    format: int = 1
    candidature_source_change: str = "unchanged"
    candidatures: list[CandidatureOutcome] = field(default_factory=list)
    documents: list[DocumentOutcome] = field(default_factory=list)
    removed_candidatures: list[tuple[str, int, tuple[str, ...]]] = field(default_factory=list)

    def count(self, status: DocumentStatus) -> int:
        items = self.outcomes if self.format == 1 else self.documents
        return sum(1 for outcome in items if outcome.status is status)


def find_election(session: Session, bundle: Bundle) -> Election | None:
    """The Election a bundle describes (same country, type and date), or ``None``.

    The public read seam for later features (``proposal-extraction``).
    """
    return _find_election(session, bundle)


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
    assert entry.file is not None and entry.text is not None
    return _checked_text_url(entry.file, entry.text)


def _checked_text_url(file: str, text: SourceText) -> str | None:
    url = text.source_url
    if url is None:
        return None
    try:
        valid = validate_url(url)
    except InvalidInputError as exc:
        raise InvalidInputError(f"{file}: source_url: {exc}") from None
    if valid != url:
        raise InvalidInputError(
            f"{file}: source_url must not have leading or trailing whitespace"
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
    assert entry.file is not None and entry.text is not None
    return _new_text_document(party_id, entry.file, entry.text)


def _new_text_document(party_id: int, file: str, text: SourceText) -> SourceDocument:
    url = text.source_url
    document = SourceDocument(
        party_id=party_id,
        origin=SourceDocumentOrigin.URL if url is not None else SourceDocumentOrigin.UPLOAD,
        status=SourceDocumentStatus.REGISTERED,
        source_url=url,
        original_filename=file,
        bundle_file=file,
        content_hash=text.content_hash,
    )
    set_parsed_pages(document, text.pages)
    return document


def import_bundle(session: Session, bundle: Bundle) -> ImportReport:
    """Create or update ``bundle``'s Election, Parties and Source Documents. Never commits.

    Raises BundleConflictError (or InvalidInputError for a bad ``source_url``)
    before anything is written when the database conflicts with the bundle.
    A format-2 bundle also sets candidatures and document scopes
    (``_import_v2``).
    """
    if bundle.format == 2:
        return _import_v2(session, bundle)
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
        logo_fields = _set_logo(party, entry)
        current = plan.current
        assert entry.text is not None
        if current is not None and current.content_hash == entry.text.content_hash:
            report.outcomes.append(
                PartyOutcome(
                    entry.short_name, party.id, party_created, DocumentStatus.UNCHANGED,
                    current.id, current.page_count or 0, **logo_fields,
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
                **logo_fields,
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


def _set_logo(party: Party, entry: BundleParty) -> dict[str, Any]:
    logo = entry.logo.logo if entry.logo is not None else None
    return {
        "logo_change": elections.set_party_logo(party, logo),
        "logo_file": entry.logo.file if entry.logo is not None else None,
        "logo_media_type": logo.media_type if logo is not None else None,
        "logo_size": len(logo.data) if logo is not None else None,
    }


def check_against_bundle(session: Session, bundle: Bundle) -> list[str]:
    """Every divergence between the database and ``bundle`` (empty: they match). Read-only."""
    if bundle.format == 2:
        return _check_v2(session, bundle)
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
        problems.extend(_logo_problems(session, label, party.id, entry))
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
        assert entry.file is not None and entry.text is not None
        for document in bundle_rows:
            problems.extend(_document_problems(label, document, entry.file, entry.text))
    return problems


def _logo_problems(session: Session, label: str, party_id: int, entry: BundleParty) -> list[str]:
    data, media_type, sha256 = session.execute(
        select(Party.logo, Party.logo_media_type, Party.logo_sha256).where(Party.id == party_id)
    ).one()
    stored = data is not None or media_type is not None or sha256 is not None
    if entry.logo is None:
        return [f"{label}: has a logo but election.toml declares none"] if stored else []
    if not stored:
        return [f"{label}: no logo, election.toml declares {entry.logo.file}"]
    expected = entry.logo.logo
    if (
        data is None
        or sha256 != expected.sha256
        or media_type != expected.media_type
        or hashlib.sha256(data).hexdigest() != sha256
    ):
        return [f"{label}: logo differs from {entry.logo.file}"]
    return []


def _document_problems(
    label: str, document: SourceDocument, file: str, source_text: SourceText
) -> list[str]:
    where = f"{label}: source document {document.id}"
    problems: list[str] = []
    if document.bundle_file != file:
        problems.append(f"{where}: bundle_file {document.bundle_file!r} is not {file!r}")
    if document.content_hash != source_text.content_hash:
        problems.append(f"{where}: content_hash differs from the SHA-256 of {file}")
    if document.source_url != source_text.source_url:
        problems.append(f"{where}: source_url differs from {file}")
    expected_pages = source_text.pages
    if document.page_count != len(expected_pages):
        problems.append(
            f"{where}: page_count {document.page_count} differs from {len(expected_pages)}"
        )
    stored = [(page.page_number, page.text) for page in document.pages]
    if [number for number, _ in stored] != list(range(1, len(expected_pages) + 1)):
        problems.append(
            f"{where}: has {len(stored)} page rows, {file} has {len(expected_pages)} pages"
        )
    for number, text in stored:
        if 1 <= number <= len(expected_pages) and text != expected_pages[number - 1]:
            problems.append(f"{where}: page {number} text differs from {file}")
    return problems


# --- Format 2: candidatures and document scopes ----------------------------------


def candidatures_by_party(session: Session, election_id: int) -> dict[int, tuple[str, ...]]:
    """Party id -> the sorted Constituency codes it runs in, for ``election_id``. Read-only.

    Parties without candidatures (format-1 or legacy-only Parties) are absent.
    The seam for later features: they read candidatures only through here.
    """
    rows = session.execute(
        select(Candidature.party_id, Candidature.constituency_code)
        .join(Party, Party.id == Candidature.party_id)
        .where(Party.election_id == election_id)
        .order_by(Candidature.party_id, Candidature.constituency_code)
    ).all()
    result: dict[int, list[str]] = {}
    for party_id, code in rows:
        result.setdefault(party_id, []).append(code)
    return {party_id: tuple(codes) for party_id, codes in result.items()}


def document_scopes(session: Session, election_id: int) -> dict[int, tuple[str, ...]]:
    """Source Document id -> the sorted Constituency codes it applies to. Read-only.

    Covers every Source Document of ``election_id``'s Parties that has scope
    rows (current and replaced ones; a replaced row keeps its old scope).
    Rows without a scope (format-1 or legacy) are absent. The seam for later
    features: they read scopes only through here.
    """
    rows = session.execute(
        select(SourceDocumentConstituency.source_document_id, SourceDocumentConstituency.constituency_code)
        .join(SourceDocument, SourceDocument.id == SourceDocumentConstituency.source_document_id)
        .join(Party, Party.id == SourceDocument.party_id)
        .where(Party.election_id == election_id)
        .order_by(
            SourceDocumentConstituency.source_document_id,
            SourceDocumentConstituency.constituency_code,
        )
    ).all()
    result: dict[int, list[str]] = {}
    for document_id, code in rows:
        result.setdefault(document_id, []).append(code)
    return {document_id: tuple(codes) for document_id, codes in result.items()}


def _party_codes(session: Session, party_id: int) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(Candidature.constituency_code)
            .where(Candidature.party_id == party_id)
            .order_by(Candidature.constituency_code)
        )
    )


def _scope_codes(session: Session, document_id: int) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(SourceDocumentConstituency.constituency_code)
            .where(SourceDocumentConstituency.source_document_id == document_id)
            .order_by(SourceDocumentConstituency.constituency_code)
        )
    )


def _documents_of(bundle: Bundle, short_name: str) -> list[BundleDocument]:
    return [document for document in bundle.documents if short_name in document.parties]


def _checked_candidatures_url(bundle: Bundle) -> None:
    url = bundle.candidatures.url if bundle.candidatures is not None else None
    if url is None:
        return
    try:
        valid = validate_url(url)
    except InvalidInputError as exc:
        raise InvalidInputError(f"{MANIFEST_NAME}: [candidatures] url: {exc}") from None
    if valid != url:
        raise InvalidInputError(
            f"{MANIFEST_NAME}: [candidatures] url must not have leading or trailing whitespace"
        )


@dataclass
class _PlanV2:
    entry: BundleParty
    party: Party | None
    # bundle_file -> the Party's current bundle row for it (only listed files).
    current: dict[str, SourceDocument]


def _plan_v2(session: Session, bundle: Bundle, election: Election | None) -> list[_PlanV2]:
    """Check a format-2 bundle against the database. Writes nothing."""
    _checked_candidatures_url(bundle)
    for document in bundle.documents:
        _checked_text_url(document.file, document.text)
    if election is None:
        return [_PlanV2(entry, None, {}) for entry in bundle.parties]
    if election.name != bundle.name:
        raise BundleConflictError(
            f"election {bundle.slug} (id {election.id}) exists with name {election.name!r}, "
            f"but the bundle names it {bundle.name!r}; {FRESH_DATABASE_FIX}"
        )
    parties = {p.short_name: p for p in election.parties}
    by_name = {p.name: p for p in election.parties}
    plans: list[_PlanV2] = []
    for entry in bundle.parties:
        party = parties.get(entry.short_name)
        if party is None:
            other = by_name.get(entry.name)
            if other is not None:
                raise BundleConflictError(
                    f"party {entry.name!r} exists as {other.short_name} (id {other.id}), "
                    f"but the bundle names it {entry.short_name}; {FRESH_DATABASE_FIX}"
                )
            plans.append(_PlanV2(entry, None, {}))
            continue
        label = f"party {entry.short_name} (id {party.id})"
        if party.name != entry.name:
            raise BundleConflictError(
                f"{label} exists with name {party.name!r}, "
                f"but the bundle names it {entry.name!r}; {FRESH_DATABASE_FIX}"
            )
        current_rows = _current_parsed(session, party.id)
        not_bundle = [d for d in current_rows if d.bundle_file is None]
        if not_bundle:
            raise BundleConflictError(
                f"{label} has source document {not_bundle[0].id}, which was not imported "
                f"from a bundle; {FRESH_DATABASE_FIX}"
            )
        documents = {document.file: document for document in _documents_of(bundle, entry.short_name)}
        current: dict[str, SourceDocument] = {}
        for row in current_rows:
            assert row.bundle_file is not None
            if row.bundle_file not in documents:
                raise BundleConflictError(
                    f"{label} has current source document {row.id} from {row.bundle_file}, "
                    f"which {MANIFEST_NAME} no longer lists for it; discarding a manifesto "
                    "is a review decision, not a removal from the manifest"
                )
            if row.bundle_file in current:
                raise BundleConflictError(
                    f"{label} has more than one current source document for "
                    f"{row.bundle_file} ({current[row.bundle_file].id}, {row.id}); "
                    f"{FRESH_DATABASE_FIX}"
                )
            current[row.bundle_file] = row
        for file, document in documents.items():
            row = current.get(file)
            if row is not None and row.content_hash == document.text.content_hash:
                continue
            same_bytes = session.scalars(
                select(SourceDocument.id).where(
                    SourceDocument.party_id == party.id,
                    SourceDocument.content_hash == document.text.content_hash,
                )
            ).first()
            if same_bytes is not None:
                raise BundleConflictError(
                    f"{label}: {file} has the same content as older source document "
                    f"{same_bytes} (a reverted file); {FRESH_DATABASE_FIX}"
                )
        plans.append(_PlanV2(entry, party, current))
    return plans


def _set_candidatures(
    session: Session, party_id: int, codes: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Make the Party's candidatures equal to ``codes``; return (added, removed)."""
    stored = set(_party_codes(session, party_id))
    wanted = set(codes)
    added = tuple(sorted(wanted - stored))
    removed = tuple(sorted(stored - wanted))
    if removed:
        session.execute(
            delete(Candidature).where(
                Candidature.party_id == party_id,
                Candidature.constituency_code.in_(removed),
            )
        )
    for code in added:
        session.add(Candidature(party_id=party_id, constituency_code=code))
    session.flush()
    return added, removed


def _set_scope(
    session: Session, document_id: int, codes: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Make the Source Document's scope equal to ``codes``; return (added, removed)."""
    stored = set(_scope_codes(session, document_id))
    wanted = set(codes)
    added = tuple(sorted(wanted - stored))
    removed = tuple(sorted(stored - wanted))
    if removed:
        session.execute(
            delete(SourceDocumentConstituency).where(
                SourceDocumentConstituency.source_document_id == document_id,
                SourceDocumentConstituency.constituency_code.in_(removed),
            )
        )
    for code in added:
        session.add(
            SourceDocumentConstituency(source_document_id=document_id, constituency_code=code)
        )
    session.flush()
    return added, removed


def _import_v2(session: Session, bundle: Bundle) -> ImportReport:
    election = _find_election(session, bundle)
    plans = _plan_v2(session, bundle, election)

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
        slug=bundle.slug, election_id=election.id, election_created=election_created, format=2
    )
    source = bundle.candidatures
    assert source is not None
    stored_source = (election.candidatures_source, election.candidatures_source_url)
    if stored_source != (source.source, source.url):
        report.candidature_source_change = "set" if stored_source == (None, None) else "changed"
        election.candidatures_source = source.source
        election.candidatures_source_url = source.url
        session.flush()

    party_ids: dict[str, int] = {}
    for plan in plans:
        entry = plan.entry
        party = plan.party
        party_created = party is None
        if party is None:
            party = elections.add_party(
                session, election_id=election.id, name=entry.name, short_name=entry.short_name
            )
        party_ids[entry.short_name] = party.id
        logo_fields = _set_logo(party, entry)
        codes = entry.constituencies or ()
        added, removed = _set_candidatures(session, party.id, codes)
        report.candidatures.append(
            CandidatureOutcome(
                entry.short_name, party.id, party_created, len(codes), added, removed,
                **logo_fields,
            )
        )

    listed = {entry.short_name for entry in bundle.parties}
    for party in session.scalars(
        select(Party).where(Party.election_id == election.id).order_by(Party.id)
    ):
        if party.short_name in listed:
            continue
        report.left_alone.append((party.short_name, party.id))
        _, removed = _set_candidatures(session, party.id, ())
        if removed:
            report.removed_candidatures.append((party.short_name, party.id, removed))

    current_by_party = {plan.entry.short_name: plan.current for plan in plans}
    for document in bundle.documents:
        for short_name in document.parties:
            party_id = party_ids[short_name]
            scope = document_scope(bundle, document, short_name)
            current = current_by_party[short_name].get(document.file)
            if current is not None and current.content_hash == document.text.content_hash:
                scope_added, scope_removed = _set_scope(session, current.id, scope)
                report.documents.append(
                    DocumentOutcome(
                        document.file, short_name, party_id, DocumentStatus.UNCHANGED,
                        current.id, current.page_count or 0, len(scope),
                        scope_added, scope_removed,
                    )
                )
                continue
            row = _new_text_document(party_id, document.file, document.text)
            session.add(row)
            session.flush()
            if current is not None:
                current.replaced_by_id = row.id
                session.flush()
            scope_added, scope_removed = _set_scope(session, row.id, scope)
            report.new_documents.append(row)
            report.documents.append(
                DocumentOutcome(
                    document.file,
                    short_name,
                    party_id,
                    DocumentStatus.ADDED if current is None else DocumentStatus.REPLACED,
                    row.id,
                    len(document.text.pages),
                    len(scope),
                    scope_added,
                    scope_removed,
                    replaced_document_id=None if current is None else current.id,
                )
            )
    return report


def _check_v2(session: Session, bundle: Bundle) -> list[str]:
    election = _find_election(session, bundle)
    problems = _coverage_problems(bundle)
    if election is None:
        return [f"election {bundle.slug} not found", *problems]
    where = f"election {bundle.slug} (id {election.id})"
    if election.name != bundle.name:
        problems.insert(
            0, f"{where}: name {election.name!r} differs from the bundle's {bundle.name!r}"
        )
    source = bundle.candidatures
    assert source is not None
    if election.candidatures_source != source.source:
        problems.append(f"{where}: candidatures source differs from {MANIFEST_NAME}")
    if election.candidatures_source_url != source.url:
        problems.append(f"{where}: candidatures url differs from {MANIFEST_NAME}")
    stored_codes = candidatures_by_party(session, election.id)
    parties = {p.short_name: p for p in election.parties}
    for entry in bundle.parties:
        party = parties.get(entry.short_name)
        if party is None:
            problems.append(f"party {entry.short_name} not found")
            continue
        label = f"party {entry.short_name} (id {party.id})"
        if party.name != entry.name:
            problems.append(f"{label}: name {party.name!r} differs from {entry.name!r}")
        problems.extend(_logo_problems(session, label, party.id, entry))
        problems.extend(
            _codes_problem(
                f"{label}: candidatures differ",
                entry.constituencies or (),
                stored_codes.get(party.id, ()),
            )
        )
        documents = {d.file: d for d in _documents_of(bundle, entry.short_name)}
        current_rows = _current_parsed(session, party.id)
        rows_by_file: dict[str, list[SourceDocument]] = {}
        for row in current_rows:
            if row.bundle_file is None:
                problems.append(
                    f"{label}: source document {row.id} was not imported from a bundle"
                )
            elif row.bundle_file not in documents:
                problems.append(
                    f"{label}: current source document {row.id} from {row.bundle_file} is not "
                    f"listed for it in {MANIFEST_NAME}"
                )
            else:
                rows_by_file.setdefault(row.bundle_file, []).append(row)
        for file, document in documents.items():
            rows = rows_by_file.get(file, [])
            if not rows:
                problems.append(f"{label}: no current source document for {file}")
                continue
            if len(rows) > 1:
                problems.append(
                    f"{label}: {len(rows)} current bundle documents for {file} "
                    f"({', '.join(str(d.id) for d in rows)})"
                )
            scope = document_scope(bundle, document, entry.short_name)
            for row in rows:
                problems.extend(_document_problems(label, row, file, document.text))
                problems.extend(
                    _codes_problem(
                        f"{label}: source document {row.id}: scope differs",
                        scope,
                        _scope_codes(session, row.id),
                    )
                )
    listed = {entry.short_name for entry in bundle.parties}
    for party in election.parties:
        if party.short_name not in listed and party.id in stored_codes:
            problems.append(
                f"party {party.short_name} (id {party.id}) is not in {MANIFEST_NAME} but has "
                f"candidatures: {', '.join(stored_codes[party.id])}"
            )
    return problems


def _codes_problem(
    prefix: str, expected: Sequence[str], stored: Sequence[str]
) -> list[str]:
    missing = sorted(set(expected) - set(stored))
    extra = sorted(set(stored) - set(expected))
    if not missing and not extra:
        return []
    return [
        f"{prefix}: missing {', '.join(missing) or 'none'}; extra {', '.join(extra) or 'none'}"
    ]


def _coverage_problems(bundle: Bundle) -> list[str]:
    """Every Constituency in which no manifest Party runs (D4)."""
    covered = {code for entry in bundle.parties for code in entry.constituencies or ()}
    return [
        f"Constituency {code} ({name}) has no candidature in {MANIFEST_NAME}"
        for code, name in CONSTITUENCIES
        if code not in covered
    ]
