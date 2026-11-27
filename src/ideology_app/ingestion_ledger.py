"""The Ingestion Ledger: per-Party ingestion state of a format-2 Election.

The ledger is a committed JSON file ``<bundle>/ingestion-ledger.json`` beside
``election.toml``. It records facts that only the Operator (or phase 3) can
decide, and stores a derived, checked summary next to them:

- facts: ``min_proposals`` (N), each document's phase-2 review (kept or
  discarded with a reason) and validated Proposal count, both for the
  document's current ``content_hash``, each ``no_manifesto`` exclusion, and
  per overlap (two kept documents of one Party whose scopes intersect) the
  conflict check written by ``conflicts detect`` and the Operator's decision,
  both for the pair's current content hashes (format 2, proposal-conflicts);
- derived: each Party's ``phase``, ``reason`` and ``proposals``, each
  document's ``parties``, and each overlap's files, Constituencies, joint
  manifesto and ``status``.

Every mutating function first rebuilds the ledger from the bundle
(``reconcile``): it drops stale facts (a changed file, a Party or file no
longer listed, a ``no_manifesto`` exclusion on a Party that now lists a
document) and reports each change as a line. The ledger is *up to date* when
its bytes equal what ``reconcile`` would write.

The file is written only by this module (through ``ideology ingestion`` and
``ideology conflicts decide`` commands, ``record_extraction_in_dir`` and
``record_conflict_check_in_dir``), never by hand. LLM output enters it only as
a conflict check recorded by ``conflicts detect``. Its bytes are canonical
(``render_ledger``) and the reader refuses anything else. A format-1 file is
still read (it has no conflicts); ``reconcile`` rewrites it as format 2.

The module is pure apart from reading and writing the ledger file: no
database, no clock, no LLM. See ``docs/specs/ingestion-ledger.md``.
"""

import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ideology_app.elections import ElectionsError, InvalidInputError
from ideology_app.source_bundle import (
    MANIFEST_NAME,
    Bundle,
    BundleDocument,
    document_scope,
    read_bundle,
)
from ideology_app.topic_catalog import TOPIC_CATALOG

LEDGER_NAME = "ingestion-ledger.json"
LEDGER_FORMAT = 2
READ_FORMATS = (1, 2)
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
_CONFLICT_KEYS = (
    "party", "files", "content_hashes", "constituencies", "joint", "check",
    "contradictions", "status", "prevails", "reason",
)
_CHECK_KEYS = ("provider", "model", "prompt_version", "calls")
_CONTRADICTION_KEYS = ("proposals", "category", "explanation")
_CODE_RE = re.compile(r"^[0-9]{2}$")
_CATEGORY_KEYS = frozenset(entry.key for entry in TOPIC_CATALOG)


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


class ConflictStatus(StrEnum):
    """Derived from the check, the joint manifesto and the decision; never set."""

    UNCHECKED = "unchecked"
    NO_CONTRADICTION = "no_contradiction"
    JOINT_MANIFESTO = "joint_manifesto"
    DECIDED = "decided"
    PENDING = "pending"


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
class ConflictCheck:
    """How an overlap was checked: the provider, model, prompt version and new calls."""

    provider: str
    model: str
    prompt_version: str
    calls: int


@dataclass(frozen=True)
class Contradiction:
    """Proposal ordinals in ``files[0]`` and ``files[1]`` that cannot both hold."""

    proposals: tuple[int, int]
    category: str
    explanation: str


@dataclass(frozen=True)
class ConflictEntry:
    """An overlap: two kept documents of ``party`` whose scopes intersect.

    ``files`` are sorted by name and ``content_hashes`` follow them. ``check``
    and ``contradictions`` are written only by ``record_conflict_check``;
    ``prevails``/``reason`` of a ``decided`` entry only by ``decide_conflict``.
    The rest is derived.
    """

    party: str
    files: tuple[str, str]
    content_hashes: tuple[str, str]
    constituencies: tuple[str, ...]
    joint: str | None = None
    check: ConflictCheck | None = None
    contradictions: tuple[Contradiction, ...] = ()
    status: ConflictStatus = ConflictStatus.UNCHECKED
    prevails: str | None = None
    reason: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.party, *self.files)

    @property
    def loser(self) -> str | None:
        """The file whose contradicting Proposals are set aside, or ``None``."""
        if self.prevails is None:
            return None
        return self.files[1] if self.prevails == self.files[0] else self.files[0]


@dataclass(frozen=True)
class Ledger:
    election: str
    min_proposals: int
    parties: tuple[PartyEntry, ...]
    documents: tuple[DocumentEntry, ...]
    conflicts: tuple[ConflictEntry, ...] = ()
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

    def conflict(self, party: str, files: Sequence[str]) -> ConflictEntry:
        """The overlap of ``party`` between the two ``files`` (any order). Raises KeyError."""
        key = (party, *sorted(files))
        for entry in self.conflicts:
            if entry.key == key:
                return entry
        raise KeyError(key)


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


def _conflict_obj(entry: ConflictEntry) -> dict[str, Any]:
    check = entry.check
    return {
        "party": entry.party,
        "files": list(entry.files),
        "content_hashes": list(entry.content_hashes),
        "constituencies": list(entry.constituencies),
        "joint": entry.joint,
        "check": None if check is None else {
            "provider": check.provider,
            "model": check.model,
            "prompt_version": check.prompt_version,
            "calls": check.calls,
        },
        "contradictions": [
            {
                "proposals": list(item.proposals),
                "category": item.category,
                "explanation": item.explanation,
            }
            for item in entry.contradictions
        ],
        "status": entry.status.value,
        "prevails": entry.prevails,
        "reason": entry.reason,
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
        "conflicts": [_conflict_obj(entry) for entry in ledger.conflicts],
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


def conflict_status(
    check: ConflictCheck | None,
    contradictions: Sequence[Contradiction],
    joint: str | None,
    decided: bool,
) -> ConflictStatus:
    """The derived status of an overlap (the one rule the reader and ``_derive`` share)."""
    if check is None:
        return ConflictStatus.UNCHECKED
    if not contradictions:
        return ConflictStatus.NO_CONTRADICTION
    if joint is not None:
        return ConflictStatus.JOINT_MANIFESTO
    if decided:
        return ConflictStatus.DECIDED
    return ConflictStatus.PENDING


def _string_pair(
    reader: _Reader, value: Any, where: str, pattern: re.Pattern[str], what: str
) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 2:
        raise reader.error(where, f"must be a list of two {what}s")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not pattern.match(item):
            raise reader.error(f"{where}[{index}]", f"invalid {what} {item!r}")
    return value[0], value[1]


def _conflict_check(reader: _Reader, raw: Any, where: str) -> ConflictCheck | None:
    if raw is None:
        return None
    entry = reader.keys(raw, _CHECK_KEYS, where)
    return ConflictCheck(
        reader.text(entry["provider"], f"{where}.provider"),
        reader.text(entry["model"], f"{where}.model"),
        reader.text(entry["prompt_version"], f"{where}.prompt_version"),
        reader.integer(entry["calls"], f"{where}.calls", 0),
    )


def _contradictions(
    reader: _Reader, raw: Any, where: str, counts: tuple[int | None, int | None]
) -> tuple[Contradiction, ...]:
    if not isinstance(raw, list):
        raise reader.error(where, "must be a list")
    items: list[Contradiction] = []
    for index, value in enumerate(raw):
        at = f"{where}[{index}]"
        entry = reader.keys(value, _CONTRADICTION_KEYS, at)
        proposals = entry["proposals"]
        if not isinstance(proposals, list) or len(proposals) != 2:
            raise reader.error(f"{at}.proposals", "must be a list of two Proposal ordinals")
        ordinals: list[int] = []
        for side, (ordinal, count) in enumerate(zip(proposals, counts, strict=True)):
            if count is None:
                raise reader.error(
                    f"{at}.proposals[{side}]", "its document has no validated Proposal count"
                )
            ordinals.append(reader.integer(ordinal, f"{at}.proposals[{side}]", 1, count))
        category = entry["category"]
        if not isinstance(category, str) or category not in _CATEGORY_KEYS:
            raise reader.error(f"{at}.category", f"unknown category {category!r}")
        explanation = entry["explanation"]
        if explanation is None:
            raise reader.error(f"{at}.explanation", "must be a string")
        problem = note_problem(explanation)
        if problem is not None:
            raise reader.error(f"{at}.explanation", problem)
        items.append(Contradiction((ordinals[0], ordinals[1]), category, explanation))
    pairs = [item.proposals for item in items]
    if pairs != sorted(set(pairs)):
        raise reader.error(where, "must be sorted by proposals, without a duplicate pair")
    return tuple(items)


def _conflict_entry(
    reader: _Reader,
    raw: Any,
    where: str,
    parties: set[str],
    documents: dict[str, DocumentEntry],
) -> ConflictEntry:
    entry = reader.keys(raw, _CONFLICT_KEYS, where)
    party = entry["party"]
    if party not in parties:
        raise reader.error(f"{where}.party", f"unknown party {party!r}")
    files = _string_pair(reader, entry["files"], f"{where}.files", _FILE_RE, "file name")
    if not files[0] < files[1]:
        raise reader.error(f"{where}.files", "must be two different files sorted by name")
    for index, file in enumerate(files):
        document = documents.get(file)
        if document is None:
            raise reader.error(f"{where}.files[{index}]", f"{file!r} is not in documents")
        if party not in document.parties:
            raise reader.error(f"{where}.files[{index}]", f"{file!r} is not a document of {party}")
    hashes = _string_pair(
        reader, entry["content_hashes"], f"{where}.content_hashes", _HEX64_RE, "content hash"
    )
    for index, (file, content_hash) in enumerate(zip(files, hashes, strict=True)):
        if documents[file].content_hash != content_hash:
            raise reader.error(
                f"{where}.content_hashes[{index}]", f"is not the content_hash of {file}"
            )
    codes = entry["constituencies"]
    if (
        not isinstance(codes, list)
        or not codes
        or not all(isinstance(code, str) and _CODE_RE.match(code) for code in codes)
        or codes != sorted(set(codes))
    ):
        raise reader.error(
            f"{where}.constituencies", "must be a non-empty sorted list of Constituency codes"
        )
    joint = entry["joint"]
    if joint is not None and joint not in files:
        raise reader.error(f"{where}.joint", "must be null or one of the files")
    check = _conflict_check(reader, entry["check"], f"{where}.check")
    counts = (documents[files[0]].proposals, documents[files[1]].proposals)
    contradictions = _contradictions(
        reader, entry["contradictions"], f"{where}.contradictions", counts
    )
    if check is None and contradictions:
        raise reader.error(f"{where}.contradictions", "must be empty without a check")
    status = reader.enum(entry["status"], ConflictStatus, f"{where}.status", "conflict status")
    prevails, reason = entry["prevails"], entry["reason"]
    expected = conflict_status(check, contradictions, joint, prevails is not None)
    if status is not expected:
        raise reader.error(f"{where}.status", f"must be {expected.value}, not {status.value}")
    if status is ConflictStatus.JOINT_MANIFESTO:
        if prevails != joint:
            raise reader.error(f"{where}.prevails", "must be the joint manifesto")
        if reason is not None:
            raise reader.error(f"{where}.reason", "must be null for joint_manifesto")
    elif status is ConflictStatus.DECIDED:
        if prevails not in files:
            raise reader.error(f"{where}.prevails", "must be one of the files")
        if reason is None:
            raise reader.error(f"{where}.reason", "is required when the status is decided")
        problem = note_problem(reason)
        if problem is not None:
            raise reader.error(f"{where}.reason", f"reason {problem}")
    else:
        if prevails is not None:
            raise reader.error(f"{where}.prevails", f"must be null when the status is {status.value}")
        if reason is not None:
            raise reader.error(f"{where}.reason", f"must be null when the status is {status.value}")
    return ConflictEntry(
        party, files, hashes, tuple(codes), joint, check, contradictions, status, prevails, reason
    )


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
    if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt not in READ_FORMATS:
        raise reader.error("format", f"unsupported ledger format {fmt!r} (expected 1 or 2)")
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
    raw_conflicts = top["conflicts"]
    if fmt == 1 and raw_conflicts != []:
        raise reader.error("conflicts", "must be empty in ledger format 1")
    if not isinstance(raw_conflicts, list):
        raise reader.error("conflicts", "must be a list")
    by_file = {document.file: document for document in documents}
    conflicts = tuple(
        _conflict_entry(reader, raw_conflict, f"conflicts[{index}]", seen, by_file)
        for index, raw_conflict in enumerate(raw_conflicts)
    )
    keys: set[tuple[str, str, str]] = set()
    for index, conflict in enumerate(conflicts):
        if conflict.key in keys:
            raise reader.error(
                f"conflicts[{index}]",
                f"duplicate overlap {conflict.party} {' + '.join(conflict.files)}",
            )
        keys.add(conflict.key)
    ledger = Ledger(election, min_proposals, parties, documents, conflicts, fmt)
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


type ConflictKey = tuple[str, str, str]


@dataclass(frozen=True)
class _CheckFact:
    content_hashes: tuple[str, str]
    check: ConflictCheck
    contradictions: tuple[Contradiction, ...]


@dataclass(frozen=True)
class _DecisionFact:
    content_hashes: tuple[str, str]
    prevails: str
    reason: str


@dataclass
class _Facts:
    """What commands record; everything else is derived from these and the bundle."""

    min_proposals: int
    reviews: dict[str, Review]
    counts: dict[str, int]
    no_manifesto: dict[str, str | None]
    checks: dict[ConflictKey, _CheckFact] = field(default_factory=dict)
    decisions: dict[ConflictKey, _DecisionFact] = field(default_factory=dict)


@dataclass(frozen=True)
class _Overlap:
    party: str
    files: tuple[str, str]
    content_hashes: tuple[str, str]
    constituencies: tuple[str, ...]
    joint: str | None

    @property
    def key(self) -> ConflictKey:
        return (self.party, *self.files)


def _require_format_2(bundle: Bundle) -> None:
    if bundle.format != 2:
        raise LedgerError(
            f"{bundle.path / MANIFEST_NAME}: the Ingestion Ledger needs a format-2 election.toml"
        )


def _documents_of(bundle: Bundle, short_name: str) -> list[BundleDocument]:
    return [document for document in bundle.documents if short_name in document.parties]


def _overlaps(bundle: Bundle, reviews: dict[str, Review]) -> list[_Overlap]:
    """Every overlap, by manifest Party then sorted file pair (pure, D1 ``document_scope``).

    Two documents of a Party reviewed ``kept`` whose scopes for that Party
    intersect. ``joint`` is the file when exactly one of the two lists the
    Party in ``joint_for``.
    """
    overlaps: list[_Overlap] = []
    for party in bundle.parties:
        short_name = party.short_name
        kept = [
            document
            for document in _documents_of(bundle, short_name)
            if (review := reviews.get(document.file)) is not None
            and review.decision is ReviewDecision.KEPT
        ]
        found: list[_Overlap] = []
        for i, first in enumerate(kept):
            for second in kept[i + 1:]:
                shared = set(document_scope(bundle, first, short_name)) & set(
                    document_scope(bundle, second, short_name)
                )
                if not shared:
                    continue
                a, b = sorted((first, second), key=lambda document: document.file)
                joints = [d.file for d in (a, b) if short_name in d.joint_for]
                found.append(
                    _Overlap(
                        short_name,
                        (a.file, b.file),
                        (a.text.content_hash, b.text.content_hash),
                        tuple(sorted(shared)),
                        joints[0] if len(joints) == 1 else None,
                    )
                )
        overlaps.extend(sorted(found, key=lambda overlap: overlap.files))
    return overlaps


def _conflict_entries(bundle: Bundle, facts: _Facts) -> tuple[ConflictEntry, ...]:
    entries: list[ConflictEntry] = []
    for overlap in _overlaps(bundle, facts.reviews):
        fact = facts.checks.get(overlap.key)
        if fact is not None and fact.content_hashes != overlap.content_hashes:
            fact = None
        decision = facts.decisions.get(overlap.key)
        if decision is not None and decision.content_hashes != overlap.content_hashes:
            decision = None
        check = None if fact is None else fact.check
        contradictions = () if fact is None else fact.contradictions
        status = conflict_status(check, contradictions, overlap.joint, decision is not None)
        prevails: str | None = None
        reason: str | None = None
        if status is ConflictStatus.JOINT_MANIFESTO:
            prevails = overlap.joint
        elif status is ConflictStatus.DECIDED:
            assert decision is not None
            prevails, reason = decision.prevails, decision.reason
        entries.append(
            ConflictEntry(
                overlap.party,
                overlap.files,
                overlap.content_hashes,
                overlap.constituencies,
                overlap.joint,
                check,
                contradictions,
                status,
                prevails,
                reason,
            )
        )
    return tuple(entries)


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
    return Ledger(
        bundle.slug,
        facts.min_proposals,
        tuple(parties),
        documents,
        _conflict_entries(bundle, facts),
    )


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


def conflict_label(entry: ConflictEntry | _Overlap | ConflictKey) -> str:
    """``UPN-PP pp.md + upn.md`` (the change-line prefix after ``Conflict``)."""
    party, first, second = entry if isinstance(entry, tuple) else entry.key
    return f"{party} {first} + {second}"


def codes_label(codes: Sequence[str]) -> str:
    return ", ".join(codes)


def _conflict_lines(old: Ledger, new: Ledger) -> Changes:
    """Overlaps added or removed, Constituencies, joint manifesto and status changes."""
    lines: Changes = []
    before = {entry.key: entry for entry in old.conflicts}
    after = {entry.key: entry for entry in new.conflicts}
    for entry in old.conflicts:
        if entry.key not in after:
            lines.append(f"Conflict {conflict_label(entry)}: removed (no longer an overlap)")
    for entry in new.conflicts:
        previous = before.get(entry.key)
        label = f"Conflict {conflict_label(entry)}"
        if previous is None:
            lines.append(
                f"{label} ({codes_label(entry.constituencies)}): added ({entry.status.value})"
            )
            continue
        if previous.constituencies != entry.constituencies:
            lines.append(
                f"{label}: constituencies {codes_label(previous.constituencies)} -> "
                f"{codes_label(entry.constituencies)}"
            )
        if previous.joint != entry.joint:
            lines.append(
                f"{label}: joint manifesto {previous.joint or 'none'} -> {entry.joint or 'none'}"
            )
        if previous.status is not entry.status:
            lines.append(f"{label}: {previous.status.value} -> {entry.status.value}")
    return lines


def _prune_conflicts(bundle: Bundle, facts: _Facts) -> Changes:
    """Drop conflict facts that no longer hold (C5) and say why.

    A fact is kept only while an overlap with the same Party and files exists
    and both content hashes are unchanged. A decision is also dropped once a
    joint manifesto prevails. A fact of a vanished overlap is dropped silently:
    ``_conflict_lines`` reports the removal.
    """
    lines: Changes = []
    overlaps = {overlap.key: overlap for overlap in _overlaps(bundle, facts.reviews)}
    current = {document.file: document.text.content_hash for document in bundle.documents}

    def changed(key: ConflictKey, hashes: tuple[str, str]) -> bool:
        return any(
            file in current and current[file] != content_hash
            for file, content_hash in zip(key[1:], hashes, strict=True)
        )

    for key, fact in list(facts.checks.items()):
        if changed(key, fact.content_hashes):
            lines.append(f"Conflict {conflict_label(key)}: check cleared (content changed)")
            del facts.checks[key]
        elif key not in overlaps or overlaps[key].content_hashes != fact.content_hashes:
            del facts.checks[key]
    for key, decision in list(facts.decisions.items()):
        overlap = overlaps.get(key)
        fact = facts.checks.get(key)
        if changed(key, decision.content_hashes):
            lines.append(f"Conflict {conflict_label(key)}: decision cleared (content changed)")
            del facts.decisions[key]
        elif overlap is None or overlap.content_hashes != decision.content_hashes:
            del facts.decisions[key]
        elif overlap.joint is not None:
            lines.append(
                f"Conflict {conflict_label(key)}: decision cleared "
                f"(joint manifesto {overlap.joint} prevails)"
            )
            del facts.decisions[key]
        elif fact is None or not fact.contradictions:
            del facts.decisions[key]
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
        {
            c.key: _CheckFact(c.content_hashes, c.check, c.contradictions)
            for c in ledger.conflicts
            if c.check is not None
        },
        {
            c.key: _DecisionFact(c.content_hashes, c.prevails, c.reason)
            for c in ledger.conflicts
            if c.status is ConflictStatus.DECIDED
            and c.prevails is not None
            and c.reason is not None
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
    if ledger.format != LEDGER_FORMAT:
        lines.append(f"Ledger: format {ledger.format} -> {LEDGER_FORMAT}")
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

    lines.extend(_prune_conflicts(bundle, facts))
    new = _derive(bundle, facts)
    lines.extend(_party_lines(ledger, new))
    lines.extend(_conflict_lines(ledger, new))
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
    lines.extend(_prune_conflicts(bundle, facts))
    new = _derive(bundle, facts)
    lines.extend(_party_lines(base, new))
    lines.extend(_conflict_lines(base, new))
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


def _clean_text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise LedgerError(f"{what} must be a string")
    problem = note_problem(value)
    if problem is not None:
        raise LedgerError(f"{what} {problem}")
    return value


def _overlap_of(bundle: Bundle, facts: _Facts, party: str, files: Sequence[str]) -> _Overlap:
    try:
        bundle.party(party)
    except KeyError:
        raise LedgerError(f"party {party!r} is not in {MANIFEST_NAME}") from None
    if len(files) != 2 or files[0] == files[1]:
        raise LedgerError("a conflict is between two different files")
    key = (party, *sorted(files))
    for overlap in _overlaps(bundle, facts.reviews):
        if overlap.key == key:
            return overlap
    raise LedgerError(
        f"party {party} has no overlap between {key[1]} and {key[2]} (two documents of the "
        "Party, both reviewed kept, whose Constituencies intersect)"
    )


def _checked_contradictions(
    facts: _Facts, overlap: _Overlap, contradictions: Sequence[Contradiction]
) -> tuple[Contradiction, ...]:
    counts = [facts.counts.get(file) for file in overlap.files]
    for file, count in zip(overlap.files, counts, strict=True):
        if count is None:
            raise LedgerError(
                f"document {file} has no validated Proposal count; extract its Proposals first"
            )
    items: list[Contradiction] = []
    for item in contradictions:
        pair = tuple(item.proposals)
        if len(pair) != 2:
            raise LedgerError("a contradiction names two Proposal ordinals")
        for ordinal, count, file in zip(pair, counts, overlap.files, strict=True):
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or not 1 <= ordinal <= (count or 0):
                raise LedgerError(
                    f"Proposal ordinal {ordinal!r} of {file} must be between 1 and {count}"
                )
        if item.category not in _CATEGORY_KEYS:
            raise LedgerError(f"unknown category {item.category!r}")
        explanation = _clean_text(item.explanation, "explanation")
        items.append(Contradiction((pair[0], pair[1]), item.category, explanation))
    pairs = [item.proposals for item in items]
    if len(set(pairs)) != len(pairs):
        raise LedgerError("a pair of Proposals is listed twice")
    return tuple(sorted(items, key=lambda item: item.proposals))


def record_conflict_check(
    bundle: Bundle,
    ledger: Ledger | None,
    party: str,
    files: Sequence[str],
    *,
    content_hashes: Sequence[str],
    check: ConflictCheck,
    contradictions: Sequence[Contradiction],
) -> tuple[Ledger, Changes]:
    """Record the conflict check of ``party``'s overlap between ``files`` (``conflicts detect``).

    ``files`` and ``content_hashes`` are in sorted-file order; each
    contradiction's ``proposals`` are the ordinals in ``files[0]`` and
    ``files[1]``. Refused for a stale hash, an ordinal above a document's
    ledger count, an unknown category or an invalid explanation. An overlap is
    checked once: recording the same check again changes nothing and a
    different one is refused (a content change clears the check, C5/C7).
    """
    _require_format_2(bundle)
    files = list(files)
    hashes = list(content_hashes)
    if len(hashes) != 2:
        raise LedgerError("content_hashes must name the two files' hashes")
    if sorted(files) != files:
        raise LedgerError("files must be sorted by name")
    if not isinstance(check, ConflictCheck):
        raise LedgerError("check must be a ConflictCheck")
    for what, value in (
        ("provider", check.provider), ("model", check.model),
        ("prompt_version", check.prompt_version),
    ):
        if not isinstance(value, str) or not value.strip():
            raise LedgerError(f"check {what} must be a non-empty string")
    if isinstance(check.calls, bool) or not isinstance(check.calls, int) or check.calls < 0:
        raise LedgerError("check calls must be an integer >= 0")

    def mutate(facts: _Facts) -> Changes:
        overlap = _overlap_of(bundle, facts, party, files)
        if tuple(hashes) != overlap.content_hashes:
            raise LedgerError(
                f"conflict {conflict_label(overlap)}: content hashes are stale "
                "(a document changed since the check started)"
            )
        items = _checked_contradictions(facts, overlap, contradictions)
        fact = _CheckFact(overlap.content_hashes, check, items)
        previous = facts.checks.get(overlap.key)
        if previous == fact:
            return []
        if previous is not None:
            raise LedgerError(f"conflict {conflict_label(overlap)} is already checked")
        facts.checks[overlap.key] = fact
        return [
            f"Conflict {conflict_label(overlap)}: checked ({len(items)} contradictions, "
            f"{check.calls} calls)"
        ]

    return _apply(bundle, ledger, mutate)


def decide_conflict(
    bundle: Bundle,
    ledger: Ledger | None,
    party: str,
    *,
    prevails: str,
    over: str,
    reason: str,
) -> tuple[Ledger, Changes]:
    """Record which of ``party``'s two overlapping documents prevails, and why.

    Only for a ``pending`` or ``decided`` overlap (checked, with
    contradictions and no single joint manifesto). Re-deciding overwrites the
    decision (C11). The reason is required: one line, at most 500 characters.
    """
    _require_format_2(bundle)
    if reason is None:
        raise LedgerError("a decision needs a reason")
    cleaned = _clean_text(reason.strip() if isinstance(reason, str) else reason, "reason")

    def mutate(facts: _Facts) -> Changes:
        overlap = _overlap_of(bundle, facts, party, [prevails, over])
        label = conflict_label(overlap)
        fact = facts.checks.get(overlap.key)
        if fact is None:
            raise LedgerError(
                f"conflict {label} is not checked yet; run \"ideology conflicts detect "
                f"{bundle.path}\" first"
            )
        if not fact.contradictions:
            raise LedgerError(f"conflict {label} has no contradiction; nothing to decide")
        if overlap.joint is not None:
            raise LedgerError(
                f"conflict {label}: the joint manifesto {overlap.joint} prevails automatically"
            )
        decision = _DecisionFact(overlap.content_hashes, prevails, cleaned)
        previous = facts.decisions.get(overlap.key)
        if previous == decision:
            return []
        facts.decisions[overlap.key] = decision
        line = f"Conflict {label}: {prevails} prevails over {over} ({cleaned})"
        if previous is not None:
            line += f" (was {previous.prevails}: {previous.reason})"
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


def pending_line(entry: ConflictEntry, bundle_dir: Path | str = "DIR") -> str:
    """Why ``entry`` blocks phase 4 and the command that unblocks it."""
    where = f"{entry.party}: {' + '.join(entry.files)} ({codes_label(entry.constituencies)})"
    if entry.status is ConflictStatus.UNCHECKED:
        return f'{where}: not checked; run "ideology conflicts detect {bundle_dir}"'
    return (
        f"{where}: {len(entry.contradictions)} contradictions; run \"ideology conflicts decide "
        f'{bundle_dir} {entry.party} --prevails FILE --over FILE --reason TEXT"'
    )


def pending_conflicts(ledger: Ledger, bundle_dir: Path | str = "DIR") -> tuple[str, ...]:
    """One line per overlap still ``unchecked`` or ``pending`` whose Party is not
    Excluded (C9). Read it on a derived ledger (``reconcile``) or an up-to-date one."""
    excluded = {party.short_name for party in ledger.parties if party.phase is Phase.EXCLUDED}
    return tuple(
        pending_line(entry, bundle_dir)
        for entry in ledger.conflicts
        if entry.status in (ConflictStatus.UNCHECKED, ConflictStatus.PENDING)
        and entry.party not in excluded
    )


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
    blockers.extend(
        f"conflict pending: {conflict}" for conflict in pending_conflicts(derived, bundle.path)
    )
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
    bundle_dir: Path,
    apply: Callable[[Bundle, Ledger | None], tuple[Ledger, Changes]],
    *,
    current: bool = False,
) -> tuple[Bundle, Ledger, Changes]:
    bundle = read_bundle(Path(bundle_dir))
    _require_format_2(bundle)
    old = read_ledger(bundle.path)
    if current:
        # Conflict facts are recorded only on the overlaps the Operator last saw.
        if old is None:
            raise LedgerError(
                f'no ingestion ledger yet; run "ideology ingestion update {bundle.path}"'
            )
        derived, lines = reconcile(bundle, old)
        if render_ledger(derived) != render_ledger(old):
            raise LedgerError(out_of_date_problem(bundle, lines))
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


def record_conflict_check_in_dir(
    bundle_dir: Path,
    party: str,
    files: Sequence[str],
    *,
    content_hashes: Sequence[str],
    check: ConflictCheck,
    contradictions: Sequence[Contradiction],
) -> tuple[Bundle, Ledger, Changes]:
    """``conflicts detect`` on disk: needs an up-to-date ledger; records and writes."""
    return _in_dir(
        bundle_dir,
        lambda b, l: record_conflict_check(
            b, l, party, files, content_hashes=content_hashes, check=check,
            contradictions=contradictions,
        ),
        current=True,
    )


def decide_conflict_in_dir(
    bundle_dir: Path, party: str, *, prevails: str, over: str, reason: str
) -> tuple[Bundle, Ledger, Changes]:
    """``conflicts decide`` on disk: needs an up-to-date ledger; records and writes."""
    return _in_dir(
        bundle_dir,
        lambda b, l: decide_conflict(b, l, party, prevails=prevails, over=over, reason=reason),
        current=True,
    )


__all__ = [
    "DEFAULT_MIN_PROPOSALS",
    "LEDGER_FORMAT",
    "LEDGER_NAME",
    "ConflictCheck",
    "ConflictEntry",
    "ConflictStatus",
    "Contradiction",
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
    "codes_label",
    "conflict_label",
    "conflict_status",
    "decide_conflict",
    "decide_conflict_in_dir",
    "ledger_problems",
    "listed_document",
    "next_step",
    "party_states",
    "pending_conflicts",
    "pending_line",
    "phase4_blockers",
    "read_ledger",
    "reconcile",
    "record_extraction",
    "record_conflict_check",
    "record_conflict_check_in_dir",
    "record_extraction_in_dir",
    "render_ledger",
    "require_phase4_ready",
    "review_label",
    "review_document",
    "set_no_manifesto",
    "write_ledger",
]
