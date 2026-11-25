"""v2 Party Positions: one ``proposal_positions`` call per Party x category (S4, S12).

Pure apart from the injected provider. For each non-Excluded Party (by id) and
each category with pool Statements (catalog order), one call is made when the
Party has counted Proposals carrying that category among their 1-3
categories. The call lists the category's Statements (``[k] text``) and those
Proposals (``P1..Pm``, text only, in ``counted_proposals`` order); its schema
bounds every Evidence number to that Party's own list, so a Position can only
cite the Party's own Proposals. A Statement left out, a category without the
Party's Proposals (no call) or a Party without Proposals is ``no stance``.

When the Party's Proposals of one category exceed
``POSITION_SLICE_MAX_CHARS`` they are sliced, one call each. A Statement
positioned in several slices keeps the first slice's value and the union of
the Evidence in slice order when every slice gives the same side (in favour,
against or 0); otherwise it is ``no stance`` and recorded as a
``slice_disagreement``.

No Party id, name or file reaches a prompt.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ideology_app.llm.base import LLMProvider
from ideology_app.pipeline.generation import GenerationError, Usage
from ideology_app.pipeline.v2.gate import Phase4Party, PhaseProposal
from ideology_app.pipeline.v2.pool import CATEGORY_ORDER, PoolDraft
from ideology_app.pipeline.v2.prompts import (
    PROPOSAL_POSITIONS,
    ProposalPositionList,
    position_request,
)

POSITION_SLICE_MAX_CHARS = 60_000


@dataclass(frozen=True)
class EvidenceRef:
    """An Evidence Proposal of a Position, with what ``_finish_v2`` stores and mirrors."""

    proposal_id: int
    source_document_id: int
    constituencies: tuple[str, ...]
    page: int
    text: str
    source_url: str | None


@dataclass(frozen=True)
class V2Position:
    """A Party's Position on one pool Statement; ``value`` None is ``no stance``."""

    value: int | None
    evidence: tuple[EvidenceRef, ...] = ()


NO_STANCE = V2Position(None)


def category_proposals(party: Phase4Party, category: str) -> list[PhaseProposal]:
    """The Party's counted Proposals that carry ``category``, in counted order."""
    return [p for p in party.proposals if category in p.categories]


def position_slices(
    proposals: Sequence[PhaseProposal], max_chars: int = POSITION_SLICE_MAX_CHARS
) -> list[list[PhaseProposal]]:
    """``proposals`` in order, cut into slices of at most ``max_chars`` of text."""
    slices: list[list[PhaseProposal]] = []
    current: list[PhaseProposal] = []
    size = 0
    for proposal in proposals:
        if current and size + len(proposal.text) > max_chars:
            slices.append(current)
            current, size = [], 0
        current.append(proposal)
        size += len(proposal.text)
    if current:
        slices.append(current)
    return slices


def plan_position_calls(
    parties: Iterable[Phase4Party], categories: Iterable[str] = CATEGORY_ORDER
) -> int:
    """The most ``proposal_positions`` calls for ``categories`` (all 18 by default)."""
    wanted = tuple(categories)
    return sum(
        len(position_slices(category_proposals(party, category)))
        for party in parties
        for category in wanted
    )


def _ref(proposal: PhaseProposal) -> EvidenceRef:
    return EvidenceRef(
        proposal_id=proposal.proposal_id,
        source_document_id=proposal.source_document_id,
        constituencies=proposal.constituencies,
        page=proposal.page,
        text=proposal.text,
        source_url=proposal.source_url,
    )


def _side(value: int) -> int:
    return (value > 0) - (value < 0)


def _merge(answers: Sequence[tuple[int, tuple[EvidenceRef, ...]]]) -> V2Position | None:
    """The merged Position of several slices, or ``None`` when their sides differ."""
    if len({_side(value) for value, _ in answers}) > 1:
        return None
    evidence: dict[int, EvidenceRef] = {}
    for _, refs in answers:
        for ref in refs:
            evidence.setdefault(ref.proposal_id, ref)
    return V2Position(answers[0][0], tuple(evidence.values()))


@dataclass(frozen=True)
class PositionOutcome:
    """Every Party's Positions in pool order, keyed by Party id, and the report part."""

    positions: dict[int, list[V2Position]]
    report: dict[str, Any]


def assign_positions(
    provider: LLMProvider,
    statements: Sequence[PoolDraft],
    parties: Sequence[Phase4Party],
    usage: Usage,
) -> PositionOutcome:
    """A Position for every pool Statement x non-Excluded Party (module docstring).

    Raises ``GenerationError`` when an answer repeats a Statement. Out-of-range
    numbers or an empty ``evidence`` fail their call (``LLMOutputError``).
    ``LLMError`` propagates; ``usage`` keeps the counts of the calls that succeeded.
    """
    by_category: dict[str, list[int]] = {}
    for index, statement in enumerate(statements):
        by_category.setdefault(statement.category, []).append(index)
    calls = 0
    disagreements: list[dict[str, Any]] = []
    positions: dict[int, list[V2Position]] = {}
    for party in sorted(parties, key=lambda p: p.party_id):
        own = [NO_STANCE] * len(statements)
        for category in CATEGORY_ORDER:
            indexes = by_category.get(category)
            proposals = category_proposals(party, category)
            if not indexes or not proposals:
                continue
            texts = [statements[i].text for i in indexes]
            answers: dict[int, list[tuple[int, tuple[EvidenceRef, ...]]]] = {}
            for slice_ in position_slices(proposals):
                result = provider.generate(
                    position_request(category, texts, [p.text for p in slice_])
                )
                usage.record(result)
                calls += 1
                output: ProposalPositionList = result.output
                seen: set[int] = set()
                for item in output.positions:
                    if item.statement in seen:
                        raise GenerationError(
                            f"{PROPOSAL_POSITIONS.task} repeated statement {item.statement}"
                        )
                    seen.add(item.statement)
                    refs = {}
                    for number in item.evidence:
                        proposal = slice_[number - 1]
                        refs.setdefault(proposal.proposal_id, _ref(proposal))
                    answers.setdefault(item.statement, []).append(
                        (item.value, tuple(refs.values()))
                    )
            for number, given in answers.items():
                index = indexes[number - 1]
                merged = _merge(given)
                if merged is None:
                    disagreements.append(
                        {
                            "party_id": party.party_id,
                            "category": category,
                            "pool": index + 1,
                            "values": [value for value, _ in given],
                        }
                    )
                    continue
                own[index] = merged
        positions[party.party_id] = own
    sided = sum(1 for own in positions.values() for p in own if p.value is not None)
    total = sum(len(own) for own in positions.values())
    source_no_stance = 0
    for party in parties:
        counted = {p.proposal_id for p in party.proposals}
        for index, statement in enumerate(statements):
            if positions[party.party_id][index].value is None and counted.intersection(
                statement.sources
            ):
                source_no_stance += 1
    return PositionOutcome(
        positions,
        {
            "calls": calls,
            "sided": sided,
            "no_stance": total - sided,
            "slice_disagreements": disagreements,
            "source_party_no_stance": source_no_stance,
        },
    )


__all__ = [
    "NO_STANCE",
    "POSITION_SLICE_MAX_CHARS",
    "EvidenceRef",
    "PositionOutcome",
    "V2Position",
    "assign_positions",
    "category_proposals",
    "plan_position_calls",
    "position_slices",
]
