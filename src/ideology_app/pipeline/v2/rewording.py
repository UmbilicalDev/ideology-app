"""Statement Rewordings of a v2 run (``statement-rewording``): the file, matching and the check.

The Operator commits ``<bundle>/statement-rewordings.toml`` beside
``election.toml`` (R1)::

    format = 1

    [[rewordings]]
    ai_text = "texto exacto de la IA"
    text = "nueva redacción"
    reason = "por qué la original confunde"

``read_rewordings`` reads and checks it (``None`` without a file).
``apply_rewordings`` runs after ``assign_positions`` and before Constituency
Selection (R3), so Positions and Evidence are computed on the AI text and a
``--reuse-from`` replay reuses every draft and position call. Each entry is
matched to the kept pool Statement whose ``normalize_for_match`` text equals
that of its ``ai_text`` (R2); then, in pool order of the matched Statement
and then the unmatched entries in file order (R4):

- ``not_found``: no kept Statement matches;
- ``duplicate``: the new text equals (normalised) the AI text of another kept
  Statement, or the text of an earlier matched entry that passed this check;
- otherwise one ``statement_rewording_check`` call: ``applied`` when the
  verdict is equivalent, else ``rejected``.

No status fails the run; an ``LLMError`` propagates like any LLM error. Only
the AI text, its Context Note and the new text reach the prompt: never the
reason, a Party, a file or a page. Pure apart from the injected provider.
"""

import hashlib
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ideology_app.elections import InvalidInputError
from ideology_app.llm.base import LLMProvider
from ideology_app.pipeline.generation import Usage
from ideology_app.pipeline.v2.pool import PoolDraft
from ideology_app.pipeline.v2.prompts import (
    STATEMENT_REWORDING_CHECK,
    RewordingVerdict,
    rewording_request,
)
from ideology_app.validation.evidence_quotes import normalize_for_match

REWORDINGS_NAME = "statement-rewordings.toml"
REWORDINGS_FORMAT = 1
MAX_REWORDINGS = 100
REPORT_KEY_VERSION = "v2-rewording-1"
TEXT_MAX = 300
REASON_MAX = 500

STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_DUPLICATE = "duplicate"
STATUS_NOT_FOUND = "not_found"
STATUSES = (STATUS_APPLIED, STATUS_REJECTED, STATUS_DUPLICATE, STATUS_NOT_FOUND)

_TOP_KEYS = frozenset({"format", "rewordings"})
_ENTRY_KEYS = ("ai_text", "text", "reason")


class RewordingFileError(InvalidInputError):
    """The rewording file is invalid: ``path: message`` or ``path:entry N: message``."""


@dataclass(frozen=True)
class RewordingEntry:
    """One ``[[rewordings]]`` entry as written by the Operator."""

    ai_text: str
    text: str
    reason: str


@dataclass(frozen=True)
class RewordingFile:
    """A read and checked rewording file: its path, the SHA-256 of its bytes, its entries."""

    path: Path
    sha256: str
    entries: tuple[RewordingEntry, ...]


@dataclass(frozen=True)
class AppliedRewording:
    """A rewording that passed the equivalence check: the new text, reason and explanation."""

    text: str
    reason: str
    explanation: str


@dataclass(frozen=True)
class RewordingOutcome:
    """``applied`` maps a 0-based pool index to its rewording; ``report`` is the R8 report."""

    applied: Mapping[int, AppliedRewording] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)


def _entry_error(path: Path, number: int, message: str) -> RewordingFileError:
    return RewordingFileError(f"{path}:entry {number}: {message}")


def _check_entry(path: Path, number: int, raw: object) -> RewordingEntry:
    if not isinstance(raw, dict):
        raise _entry_error(path, number, "must be a table")
    missing = [key for key in _ENTRY_KEYS if key not in raw]
    if missing:
        raise _entry_error(path, number, f"missing key {missing[0]!r}")
    extra = sorted(set(raw) - set(_ENTRY_KEYS))
    if extra:
        raise _entry_error(path, number, f"unknown key {extra[0]!r}")
    for key in _ENTRY_KEYS:
        if not isinstance(raw[key], str):
            raise _entry_error(path, number, f"{key} must be a string")
    ai_text, text, reason = raw["ai_text"], raw["text"], raw["reason"]
    if not 1 <= len(ai_text) <= TEXT_MAX:
        raise _entry_error(path, number, f"ai_text must be 1..{TEXT_MAX} characters")
    if not 1 <= len(text) <= TEXT_MAX or not text.strip():
        raise _entry_error(
            path, number, f"text must be 1..{TEXT_MAX} characters with a non-space character"
        )
    if not 1 <= len(reason) <= REASON_MAX or not reason.strip():
        raise _entry_error(
            path, number, f"reason must be 1..{REASON_MAX} characters and not blank"
        )
    if text == ai_text:
        raise _entry_error(path, number, "text is the same as ai_text")
    return RewordingEntry(ai_text=ai_text, text=text, reason=reason)


def read_rewordings(bundle_dir: Path) -> RewordingFile | None:
    """Read ``<bundle_dir>/statement-rewordings.toml``; ``None`` when there is no file.

    Raises ``RewordingFileError`` for a file that is not UTF-8 TOML, a
    top-level key other than ``format`` (required, ``1``) and ``rewordings``,
    an entry without exactly ``ai_text``, ``text`` and ``reason`` (strings),
    a ``text`` or ``ai_text`` outside 1..300 characters (``text`` with a
    non-space), a blank ``reason`` or one over 500 characters, ``text`` equal
    to ``ai_text``, two entries with the same normalised ``ai_text``, or more
    than ``MAX_REWORDINGS`` entries.
    """
    path = Path(bundle_dir) / REWORDINGS_NAME
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RewordingFileError(f"{path}: cannot be read ({exc.strerror or exc})") from exc
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RewordingFileError(f"{path}: not UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RewordingFileError(f"{path}: invalid TOML: {exc}") from exc
    extra = sorted(set(document) - _TOP_KEYS)
    if extra:
        raise RewordingFileError(f"{path}: unknown key {extra[0]!r}")
    if "format" not in document:
        raise RewordingFileError(f"{path}: missing key 'format'")
    version = document["format"]
    if isinstance(version, bool) or version != REWORDINGS_FORMAT:
        raise RewordingFileError(
            f"{path}: format must be {REWORDINGS_FORMAT}, got {version!r}"
        )
    raw_entries = document.get("rewordings", [])
    if not isinstance(raw_entries, list):
        raise RewordingFileError(f"{path}: rewordings must be an array of tables")
    if len(raw_entries) > MAX_REWORDINGS:
        raise RewordingFileError(
            f"{path}: {len(raw_entries)} rewordings, at most {MAX_REWORDINGS}"
        )
    entries: list[RewordingEntry] = []
    seen: dict[str, int] = {}
    for number, raw in enumerate(raw_entries, start=1):
        entry = _check_entry(path, number, raw)
        key = normalize_for_match(entry.ai_text)
        if key in seen:
            raise _entry_error(path, number, f"same ai_text as entry {seen[key]}")
        seen[key] = number
        entries.append(entry)
    return RewordingFile(path=path, sha256=hashlib.sha256(data).hexdigest(), entries=tuple(entries))


def _report_entry(
    status: str,
    statement: int | None,
    ai_text: str,
    entry: RewordingEntry,
    explanation: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "statement": statement,
        "ai_text": ai_text,
        "text": entry.text,
        "reason": entry.reason,
        "explanation": explanation,
    }


def apply_rewordings(
    provider: LLMProvider,
    statements: Sequence[PoolDraft],
    file: RewordingFile,
    usage: Usage,
) -> RewordingOutcome:
    """Match, pre-check and judge each entry of ``file`` against the kept pool (module docstring).

    ``statements`` is the filtered pool in pool order (texts unique under
    ``normalize_for_match``). The report's ``statement`` is the 1-based pool
    position (``None`` when not found) and its ``ai_text`` the pool's text
    when matched, else the file's. ``LLMError`` propagates; ``usage`` keeps the
    counts of the calls that succeeded.
    """
    index = {normalize_for_match(draft.text): i for i, draft in enumerate(statements)}
    matched: list[tuple[int, RewordingEntry]] = []
    unmatched: list[RewordingEntry] = []
    for entry in file.entries:
        found = index.get(normalize_for_match(entry.ai_text))
        if found is None:
            unmatched.append(entry)
        else:
            matched.append((found, entry))
    matched.sort(key=lambda item: item[0])
    applied: dict[int, AppliedRewording] = {}
    rows: list[dict[str, Any]] = []
    taken: set[str] = set()
    for i, entry in matched:
        draft = statements[i]
        key = normalize_for_match(entry.text)
        if (key in index and index[key] != i) or key in taken:
            rows.append(_report_entry(STATUS_DUPLICATE, i + 1, draft.text, entry))
            continue
        taken.add(key)
        result = provider.generate(rewording_request(draft.text, draft.context_note, entry.text))
        usage.record(result)
        verdict: RewordingVerdict = result.output
        if verdict.equivalent:
            applied[i] = AppliedRewording(entry.text, entry.reason, verdict.explanation)
            status = STATUS_APPLIED
        else:
            status = STATUS_REJECTED
        rows.append(_report_entry(status, i + 1, draft.text, entry, verdict.explanation))
    rows.extend(_report_entry(STATUS_NOT_FOUND, None, e.ai_text, e) for e in unmatched)
    return RewordingOutcome(
        applied=applied,
        report={
            "version": REPORT_KEY_VERSION,
            "file": file.path.name,
            "sha256": file.sha256,
            "prompt_version": STATEMENT_REWORDING_CHECK.version,
            "entries": rows,
        },
    )


def rewording_counts(report: Mapping[str, Any]) -> dict[str, int]:
    """How many report entries have each status, in ``STATUSES`` order."""
    counts = dict.fromkeys(STATUSES, 0)
    for entry in report.get("entries", ()):
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return counts


def rewording_summary(selection: Mapping[str, Any] | None) -> str | None:
    """``1 applied, 1 rejected, 0 duplicate, 1 not found``, or ``None`` without a rewording file."""
    if not selection or "rewordings" not in selection:
        return None
    counts = rewording_counts(selection["rewordings"])
    return (
        f"{counts[STATUS_APPLIED]} applied, {counts[STATUS_REJECTED]} rejected, "
        f"{counts[STATUS_DUPLICATE]} duplicate, {counts[STATUS_NOT_FOUND]} not found"
    )


__all__ = [
    "MAX_REWORDINGS",
    "REPORT_KEY_VERSION",
    "REWORDINGS_NAME",
    "STATUSES",
    "STATUS_APPLIED",
    "STATUS_DUPLICATE",
    "STATUS_NOT_FOUND",
    "STATUS_REJECTED",
    "AppliedRewording",
    "RewordingEntry",
    "RewordingFile",
    "RewordingFileError",
    "RewordingOutcome",
    "apply_rewordings",
    "read_rewordings",
    "rewording_counts",
    "rewording_summary",
]
