"""The phase-4 gate of a v2 run and the Proposals it reads (statements-from-proposals).

``load_phase4`` is the one place a v2 run reads its input. In this order it:

1. ``ingestion_ledger.require_phase4_ready`` (every Party Extracted or
   Excluded, no pending conflict, the ledger up to date);
2. finds the imported Election (``bundle_import.find_election``);
3. refuses on any ``proposals.store.ledger_count_problems``;
4. for each Party of ``party_states`` with phase ``proposals_extracted``,
   matched by short name to its Party row with candidatures, reads its
   Proposals only through ``proposals.conflicts.counted_proposals``.

Every refusal raises ``Phase4Error`` (an ``InvalidInputError``) with the
blocker lines kept, and nothing is written. The result is plain data (no ORM
objects), so it can be used after the session closes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ideology_app import ingestion_ledger as ledgers
from ideology_app.bundle_import import candidatures_by_party, find_election
from ideology_app.elections import ElectionsError, InvalidInputError
from ideology_app.models import Party, SourceDocument
from ideology_app.proposals.conflicts import counted_proposals
from ideology_app.proposals.store import ledger_count_problems
from ideology_app.source_bundle import read_bundle


class Phase4Error(InvalidInputError):
    """A v2 run cannot start. ``blockers`` holds one line per reason (may be empty)."""

    def __init__(self, message: str, blockers: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.blockers: tuple[str, ...] = tuple(blockers)


@dataclass(frozen=True)
class PhaseProposal:
    """A Proposal that counts for a Party, as plain data.

    ``source_document_id`` is the Party's current Source Document row for the
    Proposal's document, ``source_url`` that row's URL, and ``constituencies``
    the codes where the Proposal counts for the Party (``counted_proposals``).
    """

    proposal_id: int
    content_hash: str
    ordinal: int
    page: int
    text: str
    categories: tuple[str, ...]
    tags: tuple[str, ...]
    file: str
    source_document_id: int
    source_url: str | None
    constituencies: tuple[str, ...]


@dataclass(frozen=True)
class Phase4Party:
    """A non-Excluded Party and its counted Proposals, in ``counted_proposals`` order."""

    party_id: int
    short_name: str
    proposals: tuple[PhaseProposal, ...]

    @property
    def document_ids(self) -> tuple[int, ...]:
        """The Source Document rows its Proposals come from, in ``[[documents]]`` order."""
        return tuple(dict.fromkeys(p.source_document_id for p in self.proposals))


@dataclass(frozen=True)
class Phase4Input:
    """What a v2 run reads: the Election, and its non-Excluded Parties by id."""

    election_id: int
    slug: str
    parties: tuple[Phase4Party, ...]
    document_ids: tuple[int, ...]


def load_phase4(session: Session, bundle_dir: Path) -> Phase4Input:
    """Check the phase-4 gate of ``bundle_dir`` and read its counted Proposals. Read-only.

    Raises ``Phase4Error`` for every refusal (see the module docstring).
    """
    try:
        ledger = ledgers.require_phase4_ready(Path(bundle_dir))
    except ledgers.Phase4Blocked as exc:
        raise Phase4Error(str(exc), exc.blockers) from None
    except ElectionsError as exc:
        raise Phase4Error(str(exc)) from None
    bundle = read_bundle(Path(bundle_dir))
    election = find_election(session, bundle)
    if election is None:
        raise Phase4Error(
            f'election {bundle.slug} is not imported; run "ideology data import {bundle.path}"'
        )
    problems = ledger_count_problems(session, bundle, ledger)
    if problems:
        raise Phase4Error(f"proposal counts differ: {problems[0]}", problems)
    with_candidatures = candidatures_by_party(session, election.id)
    rows = {
        party.short_name: party
        for party in session.scalars(select(Party).where(Party.election_id == election.id))
        if party.id in with_candidatures
    }
    parties: list[Phase4Party] = []
    for state in ledgers.party_states(bundle, ledger):
        if state.phase is not ledgers.Phase.PROPOSALS_EXTRACTED:
            continue
        party = rows.get(state.short_name)
        if party is None:
            raise Phase4Error(
                f"party {state.short_name} has no candidatures in election {election.id}; "
                f'run "ideology data import {bundle.path}"'
            )
        try:
            counted = counted_proposals(session, bundle, ledger, state.short_name)
        except ElectionsError as exc:
            raise Phase4Error(str(exc)) from None
        urls = dict(
            session.execute(
                select(SourceDocument.id, SourceDocument.source_url).where(
                    SourceDocument.id.in_({c.source_document_id for c in counted})
                )
            ).all()
        )
        parties.append(
            Phase4Party(
                party_id=party.id,
                short_name=state.short_name,
                proposals=tuple(
                    PhaseProposal(
                        proposal_id=c.proposal.id,
                        content_hash=c.content_hash,
                        ordinal=c.proposal.ordinal,
                        page=c.proposal.page,
                        text=c.proposal.text,
                        categories=tuple(c.proposal.categories),
                        tags=tuple(c.proposal.tags),
                        file=c.file,
                        source_document_id=c.source_document_id,
                        source_url=urls.get(c.source_document_id),
                        constituencies=c.constituencies,
                    )
                    for c in counted
                ),
            )
        )
    parties.sort(key=lambda p: p.party_id)
    documents = sorted({d for p in parties for d in p.document_ids})
    return Phase4Input(election.id, bundle.slug, tuple(parties), tuple(documents))


__all__ = ["Phase4Error", "Phase4Input", "Phase4Party", "PhaseProposal", "load_phase4"]
