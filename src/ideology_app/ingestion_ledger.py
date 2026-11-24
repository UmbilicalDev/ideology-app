"""The Ingestion Ledger: per-Party ingestion state of a format-2 Election.

The ledger is a committed JSON file ``<bundle>/ingestion-ledger.json`` beside
``election.toml``. It records facts that only the Operator (or phase 3) can
decide, and stores a derived, checked summary next to them:

- facts: ``min_proposals`` (N), each document's phase-2 review (kept or
  discarded with a reason) and validated Proposal count, both for the
  document's current ``content_hash``, and each ``no_manifesto`` exclusion;
- derived: each Party's ``phase``, ``reason`` and ``proposals``, and each
  document's ``parties``.

Every mutating function first rebuilds the ledger from the bundle
(``reconcile``): it drops stale facts (a changed file, a Party or file no
longer listed, a ``no_manifesto`` exclusion on a Party that now lists a
document) and reports each change as a line. The ledger is *up to date* when
its bytes equal what ``reconcile`` would write.

The file is written only by this module (through ``ideology ingestion``
commands and ``record_extraction_in_dir``), never by hand or by AI. Its bytes
are canonical (``render_ledger``) and the reader refuses anything else.

The module is pure apart from reading and writing the ledger file: no
database, no clock, no LLM. See ``docs/specs/ingestion-ledger.md``.
"""

import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ideology_app.elections import ElectionsError, InvalidInputError
from ideology_app.source_bundle import (
    MANIFEST_NAME,
    Bundle,
    BundleDocument,
    read_bundle,
)

LEDGER_NAME = "ingestion-ledger.json"
LEDGER_FORMAT = 1
DEFAULT_MIN_PROPOSALS = 30
MIN_PROPOSALS_RANGE = (1, 1000)
MAX_LEDGER_BYTES = 5 * 1024 * 1024
NOTE_MAX = 500
NOT_CANONICAL = (
    'not in canonical form (written by "ideology ingestion" commands, never edited)'
)

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.md$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_TOP_KEYS = ("format", "election", "min_proposals", "parties", "documents", "conflicts")
_PARTY_KEYS = ("short_name", "phase", "reason", "note", "proposals")
_DOCUMENT_KEYS = ("file", "content_hash", "parties", "review", "proposals")
_REVIEW_KEYS = ("decision", "reason", "note")


class Phase(StrEnum):
    CANDIDATURE_DECLARED = "candidature_declared"
    MANIFESTO_REVIEWED = "manifesto_reviewed"
    PROPOSALS_EXTRACTED = "proposals_extracted"
    EXCLUDED = "excluded"


class ExclusionReason(StrEnum):
    NO_MANIFESTO = "no_manifesto"
    DISCARDED_AT_REVIEW = "discarded_at_review"
    TOO_FEW_PROPOSALS = "too_few_proposals"


class ReviewDecision(StrEnum):
    KEPT = "kept"
    DISCARDED = "discarded"


class DiscardReason(StrEnum):
    NO_TEXT_LAYER = "no_text_layer"
    NOT_A_MANIFESTO = "not_a_manifesto"
    INCOMPLETE = "incomplete"


class LedgerError(InvalidInputError):
    """The ledger file is malformed, or a ledger operation is refused."""


class Phase4Blocked(ElectionsError):
    """Phase 4 (Statement generation) cannot start; ``blockers`` says why."""

    def __init__(self, blockers: Sequence[str]) -> None:
        self.blockers: tuple[str, ...] = tuple(blockers)
        more = f" (+{len(self.blockers) - 1} more)" if len(self.blockers) > 1 else ""
        first = self.blockers[0] if self.blockers else "blocked"
        super().__init__(f"phase 4 is blocked: {first}{more}")


@dataclass(frozen=True)
class Review:
    """The Operator's phase-2 decision on a document (for its ``content_hash``)."""

    decision: ReviewDecision
    reason: DiscardReason | None = None
    note: str | None = None


@dataclass(frozen=True)
class DocumentEntry:
    """A ``[[documents]]`` file: its current hash, Parties, review and Proposal count."""

    file: str
    content_hash: str
    parties: tuple[str, ...]
    review: Review | None = None
    proposals: int | None = None


@dataclass(frozen=True)
class PartyEntry:
    """A Party's derived state. ``note`` is set only with ``no_manifesto``."""

    short_name: str
    phase: Phase
    reason: ExclusionReason | None = None
    note: str | None = None
    proposals: int | None = None


@dataclass(frozen=True)
class Ledger:
    election: str
    min_proposals: int
    parties: tuple[PartyEntry, ...]
    documents: tuple[DocumentEntry, ...]
    conflicts: tuple[()] = ()
    format: int = LEDGER_FORMAT

    def party(self, short_name: str) -> PartyEntry:
        """The entry of ``short_name``. Raises KeyError."""
        for entry in self.parties:
            if entry.short_name == short_name:
                return entry
        raise KeyError(short_name)

    def document(self, file: str) -> DocumentEntry:
        """The entry of ``file``. Raises KeyError."""
        for entry in self.documents:
            if entry.file == file:
                return entry
        raise KeyError(file)


Changes = list[str]


# --- Rendering ------------------------------------------------------------------


def _review_obj(review: Review | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "decision": review.decision.value,
        "reason": None if review.reason is None else review.reason.value,
        "note": review.note,
    }


def render_ledger(ledger: Ledger) -> bytes:
    """The canonical bytes of ``ledger`` (the only form the reader accepts)."""
    obj = {
        "format": ledger.format,
        "election": ledger.election,
        "min_proposals": ledger.min_proposals,
        "parties": [
            {
                "short_name": party.short_name,
                "phase": party.phase.value,
                "reason": None if party.reason is None else party.reason.value,
                "note": party.note,
                "proposals": party.proposals,
            }
            for party in ledger.parties
        ],
        "documents": [
            {
                "file": document.file,
                "content_hash": document.content_hash,
                "parties": list(document.parties),
                "review": _review_obj(document.review),
                "proposals": document.proposals,
            }
            for document in ledger.documents
        ],
        "conflicts": list(ledger.conflicts),
    }
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# --- Reading --------------------------------------------------------------------


def ledger_path(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / LEDGER_NAME


def note_problem(note: Any) -> str | None:
    """Why ``note`` is not a valid note (``None`` is valid), or ``None``."""
    if note is None:
        return None
    if not isinstance(note, str):
        return "must be a string or null"
    if not note.strip():
        return "must not be empty"
    if note != note.strip():
        return "must not have leading or trailing whitespace"
    if _CONTROL_RE.search(note):
        return "must be a single line without control characters"
    if len(note) > NOTE_MAX:
        return f"must be at most {NOTE_MAX} characters"
    return None


class _Reader:
    def __init__(self, path: Path) -> None:
        self.path = path

    def error(self, where: str, problem: str) -> LedgerError:
        return LedgerError(f"{self.path}: {where}: {problem}")

    def keys(self, value: Any, keys: Sequence[str], where: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise self.error(where, "must be an object")
        unknown = [key for key in value if key not in keys]
        if unknown:
            raise self.error(where, f"unknown key {unknown[0]!r}")
        missing = [key for key in keys if key not in value]
        if missing:
            raise self.error(where, f"missing key {missing[0]!r}")
        return value

    def integer(self, value: Any, where: str, minimum: int, maximum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise self.error(where, "must be an integer")
        if value < minimum or (maximum is not None and value > maximum):
            bound = f"between {minimum} and {maximum}" if maximum is not None else f">= {minimum}"
            raise self.error(where, f"must be {bound}")
        return value

    def optional_count(self, value: Any, where: str) -> int | None:
        return None if value is None else self.integer(value, where, 0)

    def enum(self, value: Any, kind: type[StrEnum], where: str, what: str) -> Any:
        if isinstance(value, str):
            try:
                return kind(value)
            except ValueError:
                pass
        raise self.error(where, f"unknown {what} {value!r}")

    def optional_enum(self, value: Any, kind: type[StrEnum], where: str, what: str) -> Any:
        return None if value is None else self.enum(value, kind, where, what)

    def note(self, value: Any, where: str) -> str | None:
        problem = note_problem(value)
        if problem is not None:
            raise self.error(where, f"note {problem}")
        return value

    def text(self, value: Any, where: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise self.error(where, "must be a non-empty string")
        return value


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


def _party_entry(reader: _Reader, raw: Any, where: str) -> PartyEntry:
    entry = reader.keys(raw, _PARTY_KEYS, where)
    short_name = reader.text(entry["short_name"], f"{where}.short_name")
    phase = reader.enum(entry["phase"], Phase, f"{where}.phase", "phase")
    reason = reader.optional_enum(
        entry["reason"], ExclusionReason, f"{where}.reason", "exclusion reason"
    )
    if (phase is Phase.EXCLUDED) != (reason is not None):
        raise reader.error(
            f"{where}.reason",
            "is required when the phase is excluded" if reason is None
            else f"must be null when the phase is {phase.value}",
        )
    note = reader.note(entry["note"], f"{where}.note")
    if note is not None and reason is not ExclusionReason.NO_MANIFESTO:
        raise reader.error(f"{where}.note", "is only allowed with reason no_manifesto")
    proposals = reader.optional_count(entry["proposals"], f"{where}.proposals")
    counted = phase is Phase.PROPOSALS_EXTRACTED or reason is ExclusionReason.TOO_FEW_PROPOSALS
    if counted != (proposals is not None):
        raise reader.error(
            f"{where}.proposals",
            "is required for proposals_extracted and too_few_proposals" if counted
            else "must be null unless proposals_extracted or too_few_proposals",
        )
    return PartyEntry(short_name, phase, reason, note, proposals)


def _review(reader: _Reader, raw: Any, where: str) -> Review | None:
    if raw is None:
        return None
    entry = reader.keys(raw, _REVIEW_KEYS, where)
    decision = reader.enum(entry["decision"], ReviewDecision, f"{where}.decision", "decision")
    reason = reader.optional_enum(
        entry["reason"], DiscardReason, f"{where}.reason", "discard reason"
    )
    if decision is ReviewDecision.DISCARDED and reason is None:
        raise reader.error(f"{where}.reason", "is required when the decision is discarded")
    if decision is ReviewDecision.KEPT and reason is not None:
        raise reader.error(f"{where}.reason", "must be null when the decision is kept")
    note = reader.note(entry["note"], f"{where}.note")
    return Review(decision, reason, note)


def _document_entry(reader: _Reader, raw: Any, where: str) -> DocumentEntry:
    entry = reader.keys(raw, _DOCUMENT_KEYS, where)
    file = entry["file"]
    if not isinstance(file, str) or not _FILE_RE.match(file):
        raise reader.error(f"{where}.file", f"invalid file name {file!r}")
    content_hash = entry["content_hash"]
    if not isinstance(content_hash, str) or not _HEX64_RE.match(content_hash):
        raise reader.error(f"{where}.content_hash", "must be 64 lowercase hex characters")
    parties = entry["parties"]
    if not isinstance(parties, list) or not parties:
        raise reader.error(f"{where}.parties", "must be a non-empty list of short names")
    for index, short_name in enumerate(parties):
        reader.text(short_name, f"{where}.parties[{index}]")
    if len(set(parties)) != len(parties):
        raise reader.error(f"{where}.parties", "has a duplicate short name")
    review = _review(reader, entry["review"], f"{where}.review")
    proposals = reader.optional_count(entry["proposals"], f"{where}.proposals")
    if proposals is not None and (review is None or review.decision is not ReviewDecision.KEPT):
        raise reader.error(f"{where}.proposals", "must be null unless the review is kept")
    return DocumentEntry(file, content_hash, tuple(parties), review, proposals)


def _first_difference_line(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    index = next((i for i in range(limit) if a[i] != b[i]), limit)
    return a[:index].count(b"\n") + 1


def parse_ledger(data: bytes, *, path: Path, slug: str) -> Ledger:
    """Parse and check ledger bytes. Raises LedgerError (``<path>: <where>: <problem>``)."""
    reader = _Reader(path)
    if len(data) > MAX_LEDGER_BYTES:
        raise reader.error("file", f"is larger than {MAX_LEDGER_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = data[: exc.start].count(b"\n") + 1
        raise reader.error(f"line {line}", "invalid UTF-8") from None
    try:
        raw = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise reader.error(f"line {exc.lineno}", f"invalid JSON: {exc.msg}") from None
    except ValueError as exc:
        raise reader.error("file", f"invalid JSON: {exc}") from None
    top = reader.keys(raw, _TOP_KEYS, "$")
    fmt = top["format"]
    if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt != LEDGER_FORMAT:
        raise reader.error("format", f"unsupported ledger format {fmt!r} (expected {LEDGER_FORMAT})")
    election = top["election"]
    if election != slug:
        raise reader.error("election", f"{election!r} is not this bundle's election {slug!r}")
    min_proposals = reader.integer(top["min_proposals"], "min_proposals", *MIN_PROPOSALS_RANGE)
    if not isinstance(top["parties"], list):
        raise reader.error("parties", "must be a list")
    parties = tuple(
        _party_entry(reader, raw_party, f"parties[{index}]")
        for index, raw_party in enumerate(top["parties"])
    )
    seen: set[str] = set()
    for index, party in enumerate(parties):
        if party.short_name in seen:
            raise reader.error(
                f"parties[{index}].short_name", f"duplicate short name {party.short_name!r}"
            )
        seen.add(party.short_name)
    if not isinstance(top["documents"], list):
        raise reader.error("documents", "must be a list")
    documents = tuple(
        _document_entry(reader, raw_document, f"documents[{index}]")
        for index, raw_document in enumerate(top["documents"])
    )
    files: set[str] = set()
    for index, document in enumerate(documents):
        if document.file in files:
            raise reader.error(f"documents[{index}].file", f"duplicate file {document.file!r}")
        files.add(document.file)
    conflicts = top["conflicts"]
    if conflicts != []:
        raise reader.error("conflicts", f"must be empty in ledger format {LEDGER_FORMAT}")
    ledger = Ledger(election, min_proposals, parties, documents)
    canonical = render_ledger(ledger)
    if canonical != data:
        raise reader.error(f"line {_first_difference_line(data, canonical)}", NOT_CANONICAL)
    return ledger


def read_ledger(bundle_dir: Path) -> Ledger | None:
    """The ledger in ``bundle_dir``, or ``None`` when there is no file. Raises LedgerError.

    The expected ``election`` is the directory name (``read_bundle`` requires
    it to be the slug).
    """
    directory = Path(bundle_dir)
    path = ledger_path(directory)
    if not path.is_symlink() and not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise LedgerError(f"{path}: file: must be a regular file")
    if path.stat().st_size > MAX_LEDGER_BYTES:
        raise LedgerError(f"{path}: file: is larger than {MAX_LEDGER_BYTES} bytes")
    return parse_ledger(path.read_bytes(), path=path, slug=directory.resolve().name)


def write_ledger(bundle_dir: Path, ledger: Ledger) -> None:
    """Write ``ledger`` atomically (a dot-prefixed temp file, then ``os.replace``)."""
    directory = Path(bundle_dir)
    content = render_ledger(ledger)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".ingestion-ledger-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp_name, 0o666 & ~umask)
        os.replace(tmp_name, ledger_path(directory))
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# --- Deriving -------------------------------------------------------------------


@dataclass
class _Facts:
    """What commands record; everything else is derived from these and the bundle."""

    min_proposals: int
    reviews: dict[str, Review]
    counts: dict[str, int]
    no_manifesto: dict[str, str | None]


def _require_format_2(bundle: Bundle) -> None:
    if bundle.format != 2:
        raise LedgerError(
            f"{bundle.path / MANIFEST_NAME}: the Ingestion Ledger needs a format-2 election.toml"
        )


def _documents_of(bundle: Bundle, short_name: str) -> list[BundleDocument]:
    return [document for document in bundle.documents if short_name in document.parties]


def _derive(bundle: Bundle, facts: _Facts) -> Ledger:
    documents = tuple(
        DocumentEntry(
            document.file,
            document.text.content_hash,
            document.parties,
            facts.reviews.get(document.file),
            facts.counts.get(document.file),
        )
        for document in bundle.documents
    )
    by_file = {entry.file: entry for entry in documents}
    parties: list[PartyEntry] = []
    for party in bundle.parties:
        short_name = party.short_name
        own = [by_file[d.file] for d in _documents_of(bundle, short_name)]
        if not own:
            if short_name in facts.no_manifesto:
                parties.append(
                    PartyEntry(
                        short_name, Phase.EXCLUDED, ExclusionReason.NO_MANIFESTO,
                        facts.no_manifesto[short_name],
                    )
                )
            else:
                parties.append(PartyEntry(short_name, Phase.CANDIDATURE_DECLARED))
            continue
        if any(entry.review is None for entry in own):
            parties.append(PartyEntry(short_name, Phase.CANDIDATURE_DECLARED))
            continue
        kept = [entry for entry in own if entry.review.decision is ReviewDecision.KEPT]  # type: ignore[union-attr]
        if not kept:
            parties.append(
                PartyEntry(short_name, Phase.EXCLUDED, ExclusionReason.DISCARDED_AT_REVIEW)
            )
            continue
        if any(entry.proposals is None for entry in kept):
            parties.append(PartyEntry(short_name, Phase.MANIFESTO_REVIEWED))
            continue
        total = sum(entry.proposals or 0 for entry in kept)
        if total >= facts.min_proposals:
            parties.append(
                PartyEntry(short_name, Phase.PROPOSALS_EXTRACTED, proposals=total)
            )
        else:
            parties.append(
                PartyEntry(
                    short_name, Phase.EXCLUDED, ExclusionReason.TOO_FEW_PROPOSALS,
                    proposals=total,
                )
            )
    return Ledger(bundle.slug, facts.min_proposals, tuple(parties), documents)


def state_label(party: PartyEntry, min_proposals: int) -> str:
    """A Party's state in change lines, e.g. ``excluded (too_few_proposals, 20 < 30)``."""
    if party.phase is Phase.PROPOSALS_EXTRACTED:
        return f"{party.phase.value} ({party.proposals} proposals)"
    if party.phase is Phase.EXCLUDED and party.reason is not None:
        if party.reason is ExclusionReason.TOO_FEW_PROPOSALS:
            return f"excluded (too_few_proposals, {party.proposals} < {min_proposals})"
        return f"excluded ({party.reason.value})"
    return party.phase.value


def _party_lines(old: Ledger, new: Ledger) -> Changes:
    lines: Changes = []
    before = {party.short_name: party for party in old.parties}
    for party in new.parties:
        previous = before.get(party.short_name)
        if previous is None:
            continue
        old_label = state_label(previous, old.min_proposals)
        new_label = state_label(party, new.min_proposals)
        if old_label != new_label:
            lines.append(f"Party {party.short_name}: {old_label} -> {new_label}")
    return lines


def _check_min_proposals(value: Any) -> int:
    low, high = MIN_PROPOSALS_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise LedgerError(f"min_proposals must be an integer between {low} and {high}")
    return value


def _facts_from(ledger: Ledger) -> _Facts:
    return _Facts(
        ledger.min_proposals,
        {d.file: d.review for d in ledger.documents if d.review is not None},
        {d.file: d.proposals for d in ledger.documents if d.proposals is not None},
        {
            p.short_name: p.note
            for p in ledger.parties
            if p.reason is ExclusionReason.NO_MANIFESTO
        },
    )


def _reconcile(
    bundle: Bundle, ledger: Ledger | None, min_proposals: int | None = None
) -> tuple[Ledger, _Facts, Changes]:
    _require_format_2(bundle)
    if min_proposals is not None:
        _check_min_proposals(min_proposals)
    if ledger is None:
        facts = _Facts(min_proposals or DEFAULT_MIN_PROPOSALS, {}, {}, {})
        path = ledger_path(bundle.path)
        return (
            _derive(bundle, facts),
            facts,
            [f"Created ingestion ledger {path} (N = {facts.min_proposals})"],
        )
    if ledger.election != bundle.slug:
        raise LedgerError(
            f"{ledger_path(bundle.path)}: election: {ledger.election!r} is not this bundle's "
            f"election {bundle.slug!r}"
        )
    lines: Changes = []
    facts = _facts_from(ledger)
    if min_proposals is not None and min_proposals != facts.min_proposals:
        lines.append(f"N: {facts.min_proposals} -> {min_proposals}")
        facts.min_proposals = min_proposals

    manifest_parties = {party.short_name for party in bundle.parties}
    old_parties = {party.short_name for party in ledger.parties}
    for party in bundle.parties:
        if party.short_name not in old_parties:
            lines.append(f"Party {party.short_name}: added")
    for party in ledger.parties:
        if party.short_name not in manifest_parties:
            lines.append(f"Party {party.short_name}: removed (not in {MANIFEST_NAME})")
            facts.no_manifesto.pop(party.short_name, None)

    current = {document.file: document for document in bundle.documents}
    old_documents = {document.file: document for document in ledger.documents}
    for document in bundle.documents:
        if document.file not in old_documents:
            lines.append(f"Document {document.file}: added")
    for entry in ledger.documents:
        document = current.get(entry.file)
        if document is None:
            lines.append(f"Document {entry.file}: removed (not in {MANIFEST_NAME})")
            facts.reviews.pop(entry.file, None)
            facts.counts.pop(entry.file, None)
            continue
        if entry.content_hash != document.text.content_hash:
            dropped = False
            if facts.reviews.pop(entry.file, None) is not None:
                lines.append(f"Document {entry.file}: review cleared (content changed)")
                dropped = True
            if facts.counts.pop(entry.file, None) is not None:
                lines.append(f"Document {entry.file}: proposals cleared (content changed)")
                dropped = True
            if not dropped:
                lines.append(f"Document {entry.file}: content changed")
        if entry.parties != document.parties:
            lines.append(
                f"Document {entry.file}: parties {', '.join(entry.parties)} -> "
                f"{', '.join(document.parties)}"
            )

    for short_name in list(facts.no_manifesto):
        listed = [d.file for d in _documents_of(bundle, short_name)]
        if listed:
            lines.append(
                f"Party {short_name}: no_manifesto cleared (documents listed: {', '.join(listed)})"
            )
            del facts.no_manifesto[short_name]

    new = _derive(bundle, facts)
    lines.extend(_party_lines(ledger, new))
    if not lines and render_ledger(new) != render_ledger(ledger):
        lines.append(f"Ledger: entries reordered to follow {MANIFEST_NAME}")
    return new, facts, lines


def reconcile(
    bundle: Bundle, ledger: Ledger | None, *, min_proposals: int | None = None
) -> tuple[Ledger, Changes]:
    """Rebuild ``ledger`` (or create it when ``None``) from ``bundle``.

    Drops stale facts and returns the change lines (empty when up to date).
    ``min_proposals`` sets N (1..1000). Raises LedgerError for a format-1 bundle.
    """
    new, _, lines = _reconcile(bundle, ledger, min_proposals)
    return new, lines


def _apply(
    bundle: Bundle, ledger: Ledger | None, mutate: Callable[[_Facts], Changes]
) -> tuple[Ledger, Changes]:
    base, facts, lines = _reconcile(bundle, ledger)
    lines.extend(mutate(facts))
    new = _derive(bundle, facts)
    lines.extend(_party_lines(base, new))
    return new, lines


def listed_document(bundle: Bundle, file: str) -> BundleDocument:
    """The ``[[documents]]`` entry of ``file``. Raises LedgerError when it is not listed."""
    for document in bundle.documents:
        if document.file == file:
            return document
    raise LedgerError(f"document {file!r} is not listed in {MANIFEST_NAME}")


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise LedgerError("note must be a string")
    stripped = note.strip()
    problem = note_problem(stripped)
    if problem is not None:
        raise LedgerError(f"note {problem}")
    return stripped


def review_label(review: Review | None) -> str:
    """``not reviewed``, ``kept`` or ``discarded (<reason>)``."""
    if review is None:
        return "not reviewed"
    if review.decision is ReviewDecision.DISCARDED and review.reason is not None:
        return f"discarded ({review.reason.value})"
    return review.decision.value


# --- Operations -----------------------------------------------------------------


def review_document(
    bundle: Bundle,
    ledger: Ledger | None,
    file: str,
    *,
    decision: ReviewDecision | str,
    reason: DiscardReason | str | None = None,
    note: str | None = None,
) -> tuple[Ledger, Changes]:
    """Record the phase-2 review of ``file`` (it applies to every Party that lists it).

    A discard needs a reason and clears the document's Proposal count;
    re-reviewing overwrites the decision.
    """
    _require_format_2(bundle)
    listed_document(bundle, file)
    try:
        decision = ReviewDecision(decision)
    except ValueError:
        raise LedgerError(f"unknown review decision {decision!r}") from None
    if reason is not None:
        try:
            reason = DiscardReason(reason)
        except ValueError:
            raise LedgerError(f"unknown discard reason {reason!r}") from None
    if decision is ReviewDecision.DISCARDED and reason is None:
        raise LedgerError("a discarded document needs a reason")
    if decision is ReviewDecision.KEPT and reason is not None:
        raise LedgerError("a kept document takes no discard reason")
    review = Review(decision, reason, _clean_note(note))

    def mutate(facts: _Facts) -> Changes:
        previous = facts.reviews.get(file)
        if previous == review:
            return []
        facts.reviews[file] = review
        line = f"Document {file}: {review_label(review)}"
        if previous is not None:
            line += f" (was {review_label(previous)})"
        lines = [line]
        if decision is ReviewDecision.DISCARDED and facts.counts.pop(file, None) is not None:
            lines.append(f"Document {file}: proposals cleared (discarded)")
        return lines

    return _apply(bundle, ledger, mutate)


def set_no_manifesto(
    bundle: Bundle,
    ledger: Ledger | None,
    short_name: str,
    *,
    note: str | None = None,
    undo: bool = False,
) -> tuple[Ledger, Changes]:
    """Exclude ``short_name`` for having no manifesto (L6), or with ``undo`` remove that.

    Refused while the Party lists a document in ``[[documents]]``.
    """
    _require_format_2(bundle)
    try:
        bundle.party(short_name)
    except KeyError:
        raise LedgerError(f"party {short_name!r} is not in {MANIFEST_NAME}") from None
    cleaned = _clean_note(note)
    if undo and note is not None:
        raise LedgerError("--note cannot be used with --undo")
    listed = [document.file for document in _documents_of(bundle, short_name)]
    if not undo and listed:
        raise LedgerError(
            f"party {short_name} lists documents ({', '.join(listed)}); no_manifesto is only "
            "for a Party with no [[documents]]"
        )

    def mutate(facts: _Facts) -> Changes:
        if undo:
            if short_name not in facts.no_manifesto:
                raise LedgerError(f"party {short_name} has no no_manifesto exclusion to undo")
            del facts.no_manifesto[short_name]
            return [f"Party {short_name}: no_manifesto removed"]
        if short_name in facts.no_manifesto:
            if facts.no_manifesto[short_name] == cleaned:
                return []
            facts.no_manifesto[short_name] = cleaned
            return [f"Party {short_name}: no_manifesto note updated"]
        facts.no_manifesto[short_name] = cleaned
        return [f"Party {short_name}: no_manifesto recorded"]

    return _apply(bundle, ledger, mutate)


def record_extraction(
    bundle: Bundle,
    ledger: Ledger | None,
    file: str,
    *,
    content_hash: str,
    validated_proposals: int,
) -> tuple[Ledger, Changes]:
    """Phase-3 interface: record the validated Proposal count of ``file`` at ``content_hash``.

    ``proposal-extraction`` calls it once per document ``content_hash`` when
    its extraction is complete. The Party's phase follows from the counts and
    N (L7); extraction never sets a phase. Recording again overwrites the count.
    """
    _require_format_2(bundle)
    document = listed_document(bundle, file)
    if content_hash != document.text.content_hash:
        raise LedgerError(
            f"document {file}: content_hash {str(content_hash)[:12]}... is stale "
            f"(the bundle's file is {document.text.content_hash[:12]}...)"
        )
    if isinstance(validated_proposals, bool) or not isinstance(validated_proposals, int):
        raise LedgerError(f"document {file}: validated_proposals must be an integer")
    if validated_proposals < 0:
        raise LedgerError(f"document {file}: validated_proposals must be >= 0")

    def mutate(facts: _Facts) -> Changes:
        review = facts.reviews.get(file)
        if review is None or review.decision is not ReviewDecision.KEPT:
            raise LedgerError(
                f"document {file} is {review_label(review)}; Proposals are recorded only "
                "for a document reviewed kept"
            )
        previous = facts.counts.get(file)
        if previous == validated_proposals:
            return []
        facts.counts[file] = validated_proposals
        line = f"Document {file}: {validated_proposals} validated proposals"
        if previous is not None:
            line += f" (was {previous})"
        return [line]

    return _apply(bundle, ledger, mutate)


# --- Reading the state ----------------------------------------------------------


def party_states(bundle: Bundle, ledger: Ledger | None) -> tuple[PartyEntry, ...]:
    """Every manifest Party's derived state, in manifest order (the read path for
    ``ingestion-guide`` and ``constituency-selection-validation``)."""
    return reconcile(bundle, ledger)[0].parties


def next_step(bundle: Bundle, ledger: Ledger, short_name: str) -> str | None:
    """What a pending Party needs next, or ``None`` when it is Extracted or Excluded."""
    party = ledger.party(short_name)
    if party.phase in (Phase.PROPOSALS_EXTRACTED, Phase.EXCLUDED):
        return None
    files = [d.file for d in _documents_of(bundle, short_name)]
    if not files:
        return 'list a manifesto in [[documents]] or record "ingestion no-manifesto"'
    entries = [ledger.document(file) for file in files]
    unreviewed = [entry.file for entry in entries if entry.review is None]
    if unreviewed:
        return f"review {', '.join(unreviewed)}"
    uncounted = [
        entry.file
        for entry in entries
        if entry.review is not None
        and entry.review.decision is ReviewDecision.KEPT
        and entry.proposals is None
    ]
    return f"extract Proposals from {', '.join(uncounted)}"


def pending_conflicts(ledger: Ledger) -> tuple[str, ...]:
    """Conflicts still to decide (always ``()`` in ledger format 1; ``proposal-conflicts``)."""
    return ()


def out_of_date_problem(bundle: Bundle, lines: Changes) -> str:
    more = f" (+{len(lines) - 1} more)" if len(lines) > 1 else ""
    return (
        f"ingestion ledger is out of date: {lines[0]}{more}; "
        f'run "ideology ingestion update {bundle.path}"'
    )


def ledger_problems(bundle: Bundle) -> list[str]:
    """``data check`` / ``db check`` problems (L8): an invalid or out-of-date ledger.

    Empty for a format-1 bundle (its ledger is never read) and when there is
    no file. Pending Parties are not problems.
    """
    if bundle.format != 2:
        return []
    try:
        ledger = read_ledger(bundle.path)
    except LedgerError as exc:
        return [str(exc)]
    if ledger is None:
        return []
    new, lines = reconcile(bundle, ledger)
    if render_ledger(new) == render_ledger(ledger):
        return []
    return [out_of_date_problem(bundle, lines)]


def phase4_blockers(bundle: Bundle, ledger: Ledger | None) -> list[str]:
    """Why phase 4 cannot start; empty when every Party is Extracted or Excluded,
    the ledger exists and is up to date, and no conflict is pending."""
    blockers: list[str] = []
    if ledger is None:
        blockers.append(
            f'no ingestion ledger yet; run "ideology ingestion update {bundle.path}"'
        )
    derived, lines = reconcile(bundle, ledger)
    if ledger is not None and render_ledger(derived) != render_ledger(ledger):
        blockers.append(out_of_date_problem(bundle, lines))
    for party in derived.parties:
        step = next_step(bundle, derived, party.short_name)
        if step is not None:
            blockers.append(f"party {party.short_name}: {party.phase.value} (next: {step})")
    if ledger is not None:
        blockers.extend(f"conflict pending: {conflict}" for conflict in pending_conflicts(ledger))
    return blockers


def require_phase4_ready(bundle_dir: Path) -> Ledger:
    """The ledger when phase 4 may start. Raises Phase4Blocked (or BundleError)."""
    bundle = read_bundle(Path(bundle_dir))
    _require_format_2(bundle)
    try:
        ledger = read_ledger(bundle.path)
    except LedgerError as exc:
        raise Phase4Blocked([str(exc)]) from None
    blockers = phase4_blockers(bundle, ledger)
    if blockers:
        raise Phase4Blocked(blockers)
    assert ledger is not None
    return ledger


# --- Directory wrappers (read the bundle and ledger, apply, write) ----------------


def _in_dir(
    bundle_dir: Path, apply: Callable[[Bundle, Ledger | None], tuple[Ledger, Changes]]
) -> tuple[Bundle, Ledger, Changes]:
    bundle = read_bundle(Path(bundle_dir))
    _require_format_2(bundle)
    old = read_ledger(bundle.path)
    new, lines = apply(bundle, old)
    if old is None or render_ledger(new) != render_ledger(old):
        write_ledger(bundle.path, new)
    return bundle, new, lines


def update_in_dir(
    bundle_dir: Path, *, min_proposals: int | None = None
) -> tuple[Bundle, Ledger, Changes]:
    return _in_dir(
        bundle_dir, lambda b, l: reconcile(b, l, min_proposals=min_proposals)
    )


def review_in_dir(
    bundle_dir: Path,
    file: str,
    *,
    decision: ReviewDecision | str,
    reason: DiscardReason | str | None = None,
    note: str | None = None,
) -> tuple[Bundle, Ledger, Changes]:
    return _in_dir(
        bundle_dir,
        lambda b, l: review_document(b, l, file, decision=decision, reason=reason, note=note),
    )


def no_manifesto_in_dir(
    bundle_dir: Path, short_name: str, *, note: str | None = None, undo: bool = False
) -> tuple[Bundle, Ledger, Changes]:
    return _in_dir(
        bundle_dir, lambda b, l: set_no_manifesto(b, l, short_name, note=note, undo=undo)
    )


def record_extraction_in_dir(
    bundle_dir: Path, file: str, *, content_hash: str, validated_proposals: int
) -> tuple[PartyEntry, ...]:
    """Phase-3 interface on disk: record and write; return the affected Parties after it."""
    bundle, ledger, _ = _in_dir(
        bundle_dir,
        lambda b, l: record_extraction(
            b, l, file, content_hash=content_hash, validated_proposals=validated_proposals
        ),
    )
    affected = listed_document(bundle, file).parties
    return tuple(ledger.party(short_name) for short_name in affected)


__all__ = [
    "DEFAULT_MIN_PROPOSALS",
    "LEDGER_FORMAT",
    "LEDGER_NAME",
    "DiscardReason",
    "DocumentEntry",
    "ExclusionReason",
    "Ledger",
    "LedgerError",
    "PartyEntry",
    "Phase",
    "Phase4Blocked",
    "Review",
    "ReviewDecision",
    "ledger_problems",
    "listed_document",
    "next_step",
    "party_states",
    "pending_conflicts",
    "phase4_blockers",
    "read_ledger",
    "reconcile",
    "record_extraction",
    "record_extraction_in_dir",
    "render_ledger",
    "require_phase4_ready",
    "review_label",
    "review_document",
    "set_no_manifesto",
    "write_ledger",
]
