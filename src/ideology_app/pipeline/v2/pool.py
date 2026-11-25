"""The v2 Statement Pool: buckets, slices, ``statement_drafts`` calls and the filter.

Pure apart from the injected provider (S1-S3 of statements-from-proposals):

- ``draft_buckets``: every counted Proposal, distinct by id over all
  non-Excluded Parties, goes into the bucket of its main category
  (``categories[0]``); buckets in topic-catalog order. Inside a bucket the
  order is ``(tags casefolded, or ("\\uffff",) without tags; content_hash;
  ordinal)``, stable across machines (no database ids) and keeps similar
  Proposals together.
- ``draft_slices``: a bucket cut in order into slices of at most
  ``DRAFT_SLICE_MAX_CHARS`` characters of Proposal text (a longer Proposal is
  a slice by itself).
- ``build_pool``: one ``statement_drafts`` call per slice, sequential per
  category; each call lists the category's Statements drafted so far
  (``S1..Sm``) and may extend their sources (``additions``). The cited
  Proposals are each Statement's source Proposals, in citation order
  (duplicates dropped, first kept). Pool order: category order, call order,
  draft order. Statement text and Context Note are never edited.
- ``filter_pool``: party-blind and deterministic; leaves out Statements whose
  Context Note fails ``check_context_note`` (``context_invalid``) and exact
  duplicates (``check_statement_uniqueness``, first copy kept), with the run's
  ``ValidationSettings``. It is not Statement Selection.

No Party id, name or file reaches a prompt.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ideology_app.config import ValidationSettings
from ideology_app.llm.base import LLMProvider
from ideology_app.pipeline.generation import Usage
from ideology_app.pipeline.v2.gate import Phase4Party
from ideology_app.pipeline.v2.prompts import DraftInput, DraftSet, draft_request
from ideology_app.topic_catalog import TOPIC_CATALOG
from ideology_app.validation.base import StatementRow, ValidationInput
from ideology_app.validation.context_note import check_context_note
from ideology_app.validation.statement_uniqueness import check_statement_uniqueness

DRAFT_SLICE_MAX_CHARS = 40_000
POOL_TARGET = 200
STATUS_CONTEXT_INVALID = "context_invalid"
STATUS_DUPLICATE = "duplicate"
_NO_TAGS = ("￿",)

CATEGORY_ORDER: tuple[str, ...] = tuple(entry.key for entry in TOPIC_CATALOG)


@dataclass(frozen=True)
class PoolProposal:
    """A counted Proposal as the pool sees it (no Party)."""

    proposal_id: int
    content_hash: str
    ordinal: int
    text: str
    categories: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class PoolDraft:
    """A drafted Statement: text and note as returned, its category and source Proposal ids."""

    text: str
    context_note: str
    category: str
    sources: tuple[int, ...]


@dataclass(frozen=True)
class DraftPool:
    """The drafted pool in pool order and the per-category report."""

    statements: tuple[PoolDraft, ...]
    categories: tuple[dict[str, Any], ...]
    proposals: int


@dataclass(frozen=True)
class FilteredPool:
    """The Statements that go on to positioning, and the ones left out (report rows)."""

    statements: tuple[PoolDraft, ...]
    filtered: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def pool_proposals(parties: Iterable[Phase4Party]) -> list[PoolProposal]:
    """Every counted Proposal once (by id), in first-seen order."""
    seen: dict[int, PoolProposal] = {}
    for party in parties:
        for p in party.proposals:
            if p.proposal_id not in seen:
                seen[p.proposal_id] = PoolProposal(
                    p.proposal_id, p.content_hash, p.ordinal, p.text, p.categories, p.tags
                )
    return list(seen.values())


def _sort_key(proposal: PoolProposal) -> tuple[tuple[str, ...], str, int]:
    tags = tuple(tag.casefold() for tag in proposal.tags) or _NO_TAGS
    return (tags, proposal.content_hash, proposal.ordinal)


def draft_buckets(proposals: Iterable[PoolProposal]) -> dict[str, list[PoolProposal]]:
    """Main category -> its Proposals in bucket order; categories in catalog order.

    Raises ``ValueError`` for a main category outside the catalog.
    """
    buckets: dict[str, list[PoolProposal]] = {}
    for proposal in proposals:
        main = proposal.categories[0]
        if main not in CATEGORY_ORDER:
            raise ValueError(f"proposal {proposal.proposal_id}: unknown category {main!r}")
        buckets.setdefault(main, []).append(proposal)
    return {
        category: sorted(buckets[category], key=_sort_key)
        for category in CATEGORY_ORDER
        if category in buckets
    }


def draft_slices(
    bucket: Sequence[PoolProposal], max_chars: int = DRAFT_SLICE_MAX_CHARS
) -> list[list[PoolProposal]]:
    """``bucket`` cut in order into slices of at most ``max_chars`` of Proposal text."""
    slices: list[list[PoolProposal]] = []
    current: list[PoolProposal] = []
    size = 0
    for proposal in bucket:
        length = len(proposal.text)
        if current and size + length > max_chars:
            slices.append(current)
            current, size = [], 0
        current.append(proposal)
        size += length
    if current:
        slices.append(current)
    return slices


def plan_draft_calls(parties: Iterable[Phase4Party]) -> int:
    """The exact number of ``statement_drafts`` calls ``build_pool`` makes."""
    return sum(len(draft_slices(b)) for b in draft_buckets(pool_proposals(parties)).values())


@dataclass
class _Draft:
    text: str
    context_note: str
    sources: list[int]


def _ids(numbers: Sequence[int], slice_: Sequence[PoolProposal]) -> list[int]:
    return list(dict.fromkeys(slice_[n - 1].proposal_id for n in numbers))


def build_pool(
    provider: LLMProvider,
    parties: Sequence[Phase4Party],
    usage: Usage,
    settings: ValidationSettings,
) -> DraftPool:
    """Draft the Statement Pool from the counted Proposals of ``parties`` (module docstring).

    ``LLMError`` propagates; ``usage`` keeps the counts of the calls that succeeded.
    """
    proposals = pool_proposals(parties)
    statements: list[PoolDraft] = []
    report: list[dict[str, Any]] = []
    for category, bucket in draft_buckets(proposals).items():
        drafts: list[_Draft] = []
        calls = additions = 0
        for slice_ in draft_slices(bucket):
            request = draft_request(
                category,
                [DraftInput(p.text, p.tags) for p in slice_],
                [d.text for d in drafts],
                settings,
            )
            result = provider.generate(request)
            usage.record(result)
            calls += 1
            output: DraftSet = result.output
            # Additions first refer to the Statements listed in this request.
            for addition in output.additions:
                target = drafts[addition.statement - 1]
                for proposal_id in _ids(addition.sources, slice_):
                    if proposal_id not in target.sources:
                        target.sources.append(proposal_id)
                        additions += 1
            for item in output.statements:
                drafts.append(_Draft(item.text, item.context_note, _ids(item.sources, slice_)))
        statements.extend(
            PoolDraft(d.text, d.context_note, category, tuple(d.sources)) for d in drafts
        )
        report.append(
            {
                "category": category,
                "proposals": len(bucket),
                "calls": calls,
                "drafted": len(drafts),
                "additions": additions,
            }
        )
    return DraftPool(tuple(statements), tuple(report), len(proposals))


def filter_pool(pool: Sequence[PoolDraft], settings: ValidationSettings) -> FilteredPool:
    """Leave out invalid Context Notes, then exact duplicates (first copy kept)."""
    rows = tuple(
        StatementRow(id=n, position=n, text=d.text, topic=d.category, context_note=d.context_note)
        for n, d in enumerate(pool, start=1)
    )
    invalid = {
        e.statement_id
        for e in check_context_note(ValidationInput(rows, (), (), settings=settings))
    }
    eligible = tuple(row for row in rows if row.id not in invalid)
    duplicates = {
        e.statement_id
        for e in check_statement_uniqueness(ValidationInput(eligible, (), (), settings=settings))
    }
    kept: list[PoolDraft] = []
    filtered: list[dict[str, Any]] = []
    for n, draft in enumerate(pool, start=1):
        if n in invalid:
            filtered.append({"pool": n, "status": STATUS_CONTEXT_INVALID, "text": draft.text})
        elif n in duplicates:
            filtered.append({"pool": n, "status": STATUS_DUPLICATE, "text": draft.text})
        else:
            kept.append(draft)
    return FilteredPool(tuple(kept), tuple(filtered))


__all__ = [
    "CATEGORY_ORDER",
    "DRAFT_SLICE_MAX_CHARS",
    "POOL_TARGET",
    "STATUS_CONTEXT_INVALID",
    "STATUS_DUPLICATE",
    "DraftPool",
    "FilteredPool",
    "PoolDraft",
    "PoolProposal",
    "build_pool",
    "draft_buckets",
    "draft_slices",
    "filter_pool",
    "plan_draft_calls",
    "pool_proposals",
]
