"""``pipeline.v2.pool``: buckets, slices, carry-forward and the filter (S1-S3; scenarios 6, 7).

Pure: plain ``Phase4Party`` data and FakeProvider only.
"""

from typing import Any

import pytest
from pipeline_fixtures import offline_guard
from v2_fixtures import ECONOMY, HOUSING, NOTE, category_of, listed_previous, listed_proposals
from v2_fixtures import phase_party as party
from v2_fixtures import phase_proposal as proposal

from ideology_app.config import ValidationSettings
from ideology_app.llm import FakeProvider, LLMOutputError, LLMRequest
from ideology_app.pipeline import Usage
from ideology_app.pipeline.v2.pool import (
    DRAFT_SLICE_MAX_CHARS,
    PoolDraft,
    build_pool,
    draft_buckets,
    draft_slices,
    filter_pool,
    plan_draft_calls,
    pool_proposals,
)

SETTINGS = ValidationSettings()


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def test_buckets_use_the_main_category_catalog_order_and_a_stable_sort() -> None:
    parties = [
        party(
            1,
            proposal(1, "a", ECONOMY + HOUSING, ("Zeta",), content_hash="h2"),
            proposal(2, "b", HOUSING, (), content_hash="h1"),
            proposal(3, "c", HOUSING, ("alquiler",), content_hash="h2"),
            proposal(4, "d", HOUSING, ("Alquiler",), content_hash="h1"),
        ),
        # Party 2 counts the same Proposal 3: it is drafted once.
        party(2, proposal(3, "c", HOUSING, ("alquiler",), content_hash="h2")),
    ]
    buckets = draft_buckets(pool_proposals(parties))
    # Vivienda (1) before Economía (2) in the catalog.
    assert list(buckets) == ["housing", "economy"]
    # (tags casefolded; content_hash; ordinal); no tags sort last.
    assert [p.proposal_id for p in buckets["housing"]] == [4, 3, 2]
    assert [p.proposal_id for p in buckets["economy"]] == [1]
    with pytest.raises(ValueError):
        draft_buckets(pool_proposals([party(1, proposal(9, "x", ("nope",)))]))


def test_slices_cut_at_the_limit_and_keep_a_long_proposal_alone() -> None:
    items = pool_proposals(
        [party(1, *(proposal(n, "x" * size) for n, size in enumerate((10, 15, 30, 5), 1)))]
    )
    assert [[p.proposal_id for p in s] for s in draft_slices(items, 25)] == [[1, 2], [3], [4]]
    assert [len(s) for s in draft_slices(items)] == [4]


def _drafts(answers: dict[int, dict[str, Any]]):
    provider: FakeProvider

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        return answers[len(provider.calls)]

    provider = FakeProvider({"statement_drafts": respond})
    return provider


def test_carry_forward_lists_earlier_statements_and_additions_extend_sources() -> None:
    half = DRAFT_SLICE_MAX_CHARS // 2
    # Three Proposals over 40k characters in one category: two ordered calls.
    parties = [
        party(
            1,
            proposal(1, "A" * half, HOUSING, ("a",)),
            proposal(2, "B" * half, HOUSING, ("b",)),
            proposal(3, "C" * 10, HOUSING, ("c",)),
        )
    ]
    assert plan_draft_calls(parties) == 2
    provider = _drafts(
        {
            1: {
                "statements": [
                    {"text": "Primera.", "context_note": NOTE, "sources": [2, 1, 2]},
                ],
                "additions": [],
            },
            2: {
                "statements": [{"text": "Segunda.", "context_note": NOTE, "sources": [1]}],
                "additions": [{"statement": 1, "sources": [1, 1]}],
            },
        }
    )
    usage = Usage()
    pool = build_pool(provider, parties, usage, SETTINGS)

    assert usage.calls == 2
    first, second = provider.calls
    assert listed_previous(first) == [] and "(ninguna)" in first.prompt
    assert listed_previous(second) == ["Primera."]
    assert len(listed_proposals(first)) == 2 and len(listed_proposals(second)) == 1
    assert pool.statements == (
        PoolDraft("Primera.", NOTE, "housing", (2, 1, 3)),
        PoolDraft("Segunda.", NOTE, "housing", (3,)),
    )
    assert pool.categories == (
        {"category": "housing", "proposals": 3, "calls": 2, "drafted": 2, "additions": 1},
    )
    assert pool.proposals == 3


def test_pool_order_is_category_then_call_then_draft_and_prompts_have_no_party() -> None:
    parties = [
        party(1, proposal(1, "Bajar el IVA.", ECONOMY), proposal(2, "Más vivienda.", HOUSING)),
        party(2, proposal(3, "Menos vivienda.", HOUSING)),
    ]

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        name = category_of(request)
        return {
            "statements": [
                {"text": f"{name} {k}.", "context_note": NOTE, "sources": [1]} for k in (1, 2)
            ],
            "additions": [],
        }

    provider = FakeProvider({"statement_drafts": respond})
    pool = build_pool(provider, parties, Usage(), SETTINGS)
    assert [s.text for s in pool.statements] == [
        "Vivienda 1.", "Vivienda 2.", "Economía 1.", "Economía 2.",
    ]
    for request in provider.calls:
        for name in ("S1", "S2", "doc1.md", "[página"):
            assert name not in request.prompt


def test_out_of_range_source_fails_the_call() -> None:
    provider = FakeProvider(
        {
            "statement_drafts": {
                "statements": [{"text": "T.", "context_note": NOTE, "sources": [2]}],
                "additions": [],
            }
        }
    )
    with pytest.raises(LLMOutputError):
        build_pool(provider, [party(1, proposal(1, "x"))], Usage(), SETTINGS)


def test_filter_drops_invalid_notes_then_exact_duplicates() -> None:
    drafts = [
        PoolDraft("Debe bajarse el IVA.", NOTE, "economy", (1,)),
        PoolDraft("Debe subirse el IVA.", "Una medida injusta para la mayoría de los hogares.", "economy", (2,)),
        PoolDraft("Debe bajarse el IVA", NOTE, "housing", (3,)),
        PoolDraft("Corta.", "Breve.", "economy", (4,)),
        PoolDraft("Debe subirse el IVA.", NOTE, "economy", (5,)),
    ]
    result = filter_pool(drafts, SETTINGS)
    assert [d.sources for d in result.statements] == [(1,), (5,)]
    assert result.filtered == (
        {"pool": 2, "status": "context_invalid", "text": "Debe subirse el IVA."},
        {"pool": 3, "status": "duplicate", "text": "Debe bajarse el IVA"},
        {"pool": 4, "status": "context_invalid", "text": "Corta."},
    )
