"""Conflicts between manifestos of one Party: detection and how phase 4 applies them.

- ``merge_outputs`` (pure): maps each request's ``A``/``B`` numbers back to
  Proposal ordinals, keeps the first of each ``(ordinal_a, ordinal_b)`` pair
  with its category and explanation, and sorts by the pair.
- ``detect``: for each overlap of the Ingestion Ledger in order, asks the
  configured LLM per shared category and records the merged result with
  ``ingestion_ledger.record_conflict_check_in_dir`` after each overlap. It
  reads the database (Proposals by content hash) and never writes it.
- ``set_aside`` (pure) and ``counted_proposals``: the one read path for a
  Party's Proposals in phase 4. The losing document's contradicting
  Proposals are set aside only for that Party and only in the overlap
  Constituencies (C2). Proposals are never edited or deleted.

The ledger is read through ``store.read_phase3`` (up to date) and written
only through ``ingestion_ledger``. Depends on ``llm.base`` (never a concrete
provider), ``proposals.store``, ``proposals.conflict_prompts``,
``bundle_import`` and ``ingestion_ledger``. See ``docs/specs/proposal-conflicts.md``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ideology_app import ingestion_ledger as ledgers
from ideology_app.bundle_import import document_scopes, find_election
from ideology_app.elections import InvalidInputError
from ideology_app.llm.base import LLMError, LLMProvider
from ideology_app.models import Party, Proposal, SourceDocument, SourceDocumentStatus
from ideology_app.proposals.conflict_prompts import (
    PROPOSAL_CONFLICT_CHECK,
    ConflictProposal,
    ConflictRequest,
    ContradictionList,
    conflict_requests,
)
from ideology_app.proposals.store import DEFAULT_MAX_CALLS, load_proposals, read_phase3
from ideology_app.source_bundle import Bundle

type Echo = Callable[..., None]

_SET_ASIDE = (ledgers.ConflictStatus.JOINT_MANIFESTO, ledgers.ConflictStatus.DECIDED)
_BLOCKING = (ledgers.ConflictStatus.UNCHECKED, ledgers.ConflictStatus.PENDING)


class ConflictError(InvalidInputError):
    """Proposals cannot be read for phase 4, or conflicts cannot be detected as asked."""


def _no_echo(*args: Any, **kwargs: Any) -> None:
    return None


# --- Pure ---------------------------------------------------------------------------


def merge_outputs(
    requests: Sequence[ConflictRequest], outputs: Sequence[ContradictionList]
) -> tuple[ledgers.Contradiction, ...]:
    """The contradictions of every request, by ordinal pair, first one kept, sorted."""
    if len(requests) != len(outputs):
        raise ValueError(f"{len(requests)} requests but {len(outputs)} outputs")
    found: dict[tuple[int, int], ledgers.Contradiction] = {}
    for request, output in zip(requests, outputs, strict=True):
        for item in output.contradictions:
            pair = (request.ordinals_a[item.a - 1], request.ordinals_b[item.b - 1])
            if pair not in found:
                found[pair] = ledgers.Contradiction(pair, request.category, item.explanation)
    return tuple(found[pair] for pair in sorted(found))


def set_aside(ledger: ledgers.Ledger, short_name: str) -> dict[tuple[str, int], frozenset[str]]:
    """``(content_hash, ordinal)`` -> Constituencies where that Proposal does not count
    for ``short_name``: the losing file's contradicting Proposals of every
    ``joint_manifesto`` or ``decided`` overlap, over that overlap's Constituencies."""
    result: dict[tuple[str, int], set[str]] = {}
    for entry in ledger.conflicts:
        if entry.party != short_name or entry.status not in _SET_ASIDE:
            continue
        loser = entry.loser
        assert loser is not None
        side = entry.files.index(loser)
        for item in entry.contradictions:
            key = (entry.content_hashes[side], item.proposals[side])
            result.setdefault(key, set()).update(entry.constituencies)
    return {key: frozenset(codes) for key, codes in result.items()}


# --- Phase 4 read path ----------------------------------------------------------------


@dataclass(frozen=True)
class CountedProposal:
    """A Proposal that counts for a Party, and the Constituencies where it counts."""

    proposal: Proposal
    file: str
    content_hash: str
    source_document_id: int
    constituencies: tuple[str, ...]


def _source_row(
    session: Session, election_id: int, short_name: str, content_hash: str
) -> SourceDocument | None:
    return session.scalars(
        select(SourceDocument)
        .join(Party, Party.id == SourceDocument.party_id)
        .where(
            Party.election_id == election_id,
            Party.short_name == short_name,
            SourceDocument.content_hash == content_hash,
            SourceDocument.status == SourceDocumentStatus.PARSED,
            SourceDocument.replaced_by_id.is_(None),
        )
        .order_by(SourceDocument.id)
        .limit(1)
    ).one_or_none()


def counted_proposals(
    session: Session, bundle: Bundle, ledger: ledgers.Ledger, short_name: str
) -> list[CountedProposal]:
    """Every Proposal that counts for ``short_name`` in phase 4, with its Constituencies.

    For the Party's kept documents in ``[[documents]]`` order, each stored
    Proposal in ordinal order with the current Source Document row of
    ``(Party, content_hash)``. Its Constituencies are that row's scope
    (``bundle_import.document_scopes``) minus ``set_aside``; a Proposal left
    with none is omitted. Raises ``ConflictError`` while the Party has an
    unchecked or pending conflict, when a ledger count differs from the
    stored Proposals, or when a document is not imported.
    """
    blocking = [
        entry for entry in ledger.conflicts
        if entry.party == short_name and entry.status in _BLOCKING
    ]
    if blocking:
        raise ConflictError(
            f"party {short_name} has pending conflicts: "
            + "; ".join(ledgers.pending_line(entry, bundle.path) for entry in blocking)
        )
    election = find_election(session, bundle)
    if election is None:
        raise ConflictError(f'election {bundle.slug} is not imported; run "ideology data import"')
    scopes = document_scopes(session, election.id)
    aside = set_aside(ledger, short_name)
    counted: list[CountedProposal] = []
    for entry in ledger.documents:
        if short_name not in entry.parties:
            continue
        if entry.review is None or entry.review.decision is not ledgers.ReviewDecision.KEPT:
            continue
        proposals = load_proposals(session, entry.content_hash)
        if entry.proposals is None or len(proposals) != entry.proposals:
            raise ConflictError(
                f"document {entry.file}: ledger records {entry.proposals} validated proposals, "
                f"the database has {len(proposals)}"
            )
        row = _source_row(session, election.id, short_name, entry.content_hash)
        if row is None:
            raise ConflictError(
                f"document {entry.file} of party {short_name} is not imported; "
                f'run "ideology data import {bundle.path}"'
            )
        scope = scopes.get(row.id, ())
        for proposal in proposals:
            removed = aside.get((entry.content_hash, proposal.ordinal), frozenset())
            codes = tuple(code for code in scope if code not in removed)
            if codes:
                counted.append(
                    CountedProposal(proposal, entry.file, entry.content_hash, row.id, codes)
                )
    return counted


# --- Detection ----------------------------------------------------------------------


@dataclass
class DetectSummary:
    """The calls of one ``detect`` invocation and how it ended."""

    max_calls: int = DEFAULT_MAX_CALLS
    new_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failed: list[str] = field(default_factory=list)
    stopped: bool = False
    error: str | None = None
    pending: int = 0


def _side(proposals: Sequence[Proposal]) -> list[ConflictProposal]:
    return [ConflictProposal(p.ordinal, p.text, tuple(p.categories)) for p in proposals]


def outcome_label(entry: ledgers.ConflictEntry) -> str:
    """What a check found: ``no contradiction`` or ``n contradictions; ...``."""
    if entry.status is ledgers.ConflictStatus.UNCHECKED:
        return "not checked"
    if entry.status is ledgers.ConflictStatus.NO_CONTRADICTION:
        return "no contradiction"
    count = f"{len(entry.contradictions)} contradictions"
    if entry.status is ledgers.ConflictStatus.JOINT_MANIFESTO:
        return f"{count}; joint manifesto {entry.joint} prevails"
    if entry.status is ledgers.ConflictStatus.DECIDED:
        return f"{count}; decided: {entry.prevails} prevails"
    return f"{count}; pending Operator decision"


def _entry_label(entry: ledgers.ConflictEntry) -> str:
    return (
        f"Conflict {ledgers.conflict_label(entry)} "
        f"({ledgers.codes_label(entry.constituencies)})"
    )


def _reusable(
    ledger: ledgers.Ledger, entry: ledgers.ConflictEntry
) -> ledgers.ConflictEntry | None:
    for other in ledger.conflicts:
        if (
            other.key != entry.key
            and other.check is not None
            and other.content_hashes == entry.content_hashes
        ):
            return other
    return None


def _record(
    bundle: Bundle,
    entry: ledgers.ConflictEntry,
    check: ledgers.ConflictCheck,
    contradictions: Sequence[ledgers.Contradiction],
) -> ledgers.ConflictEntry:
    _, ledger, _ = ledgers.record_conflict_check_in_dir(
        bundle.path,
        entry.party,
        entry.files,
        content_hashes=entry.content_hashes,
        check=check,
        contradictions=contradictions,
    )
    return ledger.conflict(entry.party, entry.files)


def detect(
    engine: Engine,
    bundle_dir: Path,
    provider: LLMProvider,
    *,
    max_calls: int = DEFAULT_MAX_CALLS,
    echo: Echo = _no_echo,
) -> DetectSummary:
    """Check every unchecked overlap in ledger order and record each result.

    Skips an overlap of an Excluded Party and one already checked. Copies the
    check of another overlap with the same content-hash pair (same order) with
    0 calls (C8). An overlap whose documents' Proposals are not both complete
    is reported (``Error:``) and skipped. Stops before an overlap whose
    requests exceed the remaining ``max_calls``, and at the first
    ``LLMError`` (that overlap stays unchecked: the ledger is written after
    each overlap, never after each call). The database is only read.
    """
    bundle, ledger = read_phase3(bundle_dir)
    summary = DetectSummary(max_calls=max_calls)
    excluded = {p.short_name for p in ledger.parties if p.phase is ledgers.Phase.EXCLUDED}
    session = Session(engine)
    try:
        for key in [entry.key for entry in ledger.conflicts]:
            current = ledgers.read_ledger(bundle.path)
            assert current is not None
            entry = current.conflict(key[0], key[1:])
            label = _entry_label(entry)
            if entry.party in excluded:
                echo(f"{label}: skipped (Party {entry.party} excluded)")
                continue
            if entry.check is not None:
                echo(f"{label}: already checked; {outcome_label(entry)}")
                continue
            sides: list[list[ConflictProposal]] = []
            problem: str | None = None
            for file, content_hash in zip(entry.files, entry.content_hashes, strict=True):
                count = current.document(file).proposals
                proposals = load_proposals(session, content_hash)
                if count is None or len(proposals) != count:
                    problem = f"{label}: extract Proposals from {file} first"
                    break
                sides.append(_side(proposals))
            if problem is not None:
                echo(f"Error: {problem}", err=True)
                summary.failed.append(problem)
                continue
            source = _reusable(current, entry)
            if source is not None:
                assert source.check is not None
                check = ledgers.ConflictCheck(
                    source.check.provider, source.check.model, source.check.prompt_version, 0
                )
                recorded = _record(bundle, entry, check, source.contradictions)
                echo(f"{label}: reused check (Party {source.party}); {outcome_label(recorded)}")
                continue
            requests = conflict_requests(sides[0], sides[1])
            if summary.new_calls + len(requests) > max_calls:
                summary.stopped = True
                echo(f"Stopped before {label}; run again or raise --max-calls")
                break
            outputs: list[ContradictionList] = []
            try:
                for request in requests:
                    result = provider.generate(request.request)
                    summary.new_calls += 1
                    summary.input_tokens += result.input_tokens
                    summary.output_tokens += result.output_tokens
                    outputs.append(result.output)
            except LLMError as exc:
                summary.error = f"{label}: {exc}"
                break
            check = ledgers.ConflictCheck(
                provider.name, provider.model, PROPOSAL_CONFLICT_CHECK.version, len(requests)
            )
            recorded = _record(bundle, entry, check, merge_outputs(requests, outputs))
            echo(f"{label}: {outcome_label(recorded)}")
    finally:
        session.rollback()
        session.close()
    final = ledgers.read_ledger(bundle.path)
    assert final is not None
    summary.pending = len(ledgers.pending_conflicts(final, bundle.path))
    return summary


# --- Show -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ShownProposal:
    file: str
    ordinal: int
    page: int | None
    text: str | None


@dataclass(frozen=True)
class ShownContradiction:
    number: int
    category: str
    explanation: str
    a: ShownProposal
    b: ShownProposal


def show_rows(session: Session, entry: ledgers.ConflictEntry) -> list[ShownContradiction]:
    """Each contradiction of ``entry`` with both Proposals' page and text (read-only).

    A Proposal that is not stored (the database is behind the ledger) is
    shown with ``page`` and ``text`` ``None``.
    """
    by_side: list[dict[int, Proposal]] = [
        {p.ordinal: p for p in load_proposals(session, content_hash)}
        for content_hash in entry.content_hashes
    ]
    rows: list[ShownContradiction] = []
    for number, item in enumerate(entry.contradictions, start=1):
        shown: list[ShownProposal] = []
        for side, ordinal in enumerate(item.proposals):
            proposal = by_side[side].get(ordinal)
            shown.append(
                ShownProposal(
                    entry.files[side],
                    ordinal,
                    None if proposal is None else proposal.page,
                    None if proposal is None else proposal.text,
                )
            )
        rows.append(ShownContradiction(number, item.category, item.explanation, *shown))
    return rows


__all__ = [
    "ConflictError",
    "CountedProposal",
    "DetectSummary",
    "ShownContradiction",
    "ShownProposal",
    "counted_proposals",
    "detect",
    "merge_outputs",
    "outcome_label",
    "set_aside",
    "show_rows",
]
