"""``pipeline.v2.positions``: one call per Party x category, merge rule, neutrality (S4, S12).

Pure: plain ``Phase4Party`` data and FakeProvider only (scenarios 3, 4, 6, 9).
"""

from typing import Any

import pytest
from pipeline_fixtures import offline_guard
from v2_fixtures import ECONOMY, HOUSING, NOTE, listed_proposals, listed_statements
from v2_fixtures import phase_party as party
from v2_fixtures import phase_proposal as proposal

from ideology_app.llm import FakeProvider, LLMOutputError, LLMRequest
from ideology_app.pipeline import GenerationError, Usage
from ideology_app.pipeline.v2.pool import PoolDraft
from ideology_app.pipeline.v2.positions import (
    POSITION_SLICE_MAX_CHARS,
    EvidenceRef,
    V2Position,
    assign_positions,
    plan_position_calls,
)

HOUSING_A = PoolDraft("Debe limitarse el alquiler.", NOTE, "housing", (1,))
HOUSING_B = PoolDraft("Debe construirse más vivienda pública.", NOTE, "housing", (2,))
ECONOMY_A = PoolDraft("Deben bajarse los impuestos.", NOTE, "economy", (3,))
STATEMENTS = (HOUSING_A, HOUSING_B, ECONOMY_A)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def _fake(respond: Any) -> FakeProvider:
    return FakeProvider({"proposal_positions": respond})


def _ref(p: Any) -> EvidenceRef:
    return EvidenceRef(p.proposal_id, p.source_document_id, p.constituencies, p.page, p.text, p.source_url)


def test_against_no_stance_and_no_call_without_proposals() -> None:
    against = proposal(1, "Liberalizar el alquiler.", HOUSING, constituencies=("28", "31"))
    p1 = party(1, against)
    p2 = party(2)  # no Proposals at all: no call, no stance everywhere

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        # Addresses only the first Statement; leaves the second out.
        return {"positions": [{"statement": 1, "value": -2, "evidence": [1]}]}

    provider = _fake(respond)
    outcome = assign_positions(provider, STATEMENTS, [p2, p1], Usage())

    assert len(provider.calls) == 1  # Party 1 x housing only (no economy Proposal)
    assert listed_statements(provider.calls[0]) == [HOUSING_A.text, HOUSING_B.text]
    assert listed_proposals(provider.calls[0]) == ["Liberalizar el alquiler."]
    assert outcome.positions == {
        1: [V2Position(-2, (_ref(against),)), V2Position(None), V2Position(None)],
        2: [V2Position(None)] * 3,
    }
    assert outcome.report == {
        "calls": 1,
        "sided": 1,
        "no_stance": 5,
        "slice_disagreements": [],
        # Party 1 owns no source of Statements 2-3 (sources are ids 2 and 3).
        "source_party_no_stance": 0,
    }


def test_a_proposal_with_several_categories_is_listed_in_each() -> None:
    both = proposal(1, "Bajar el IVA de la vivienda.", ("economy", "housing"))
    provider = _fake({"positions": []})
    outcome = assign_positions(provider, STATEMENTS, [party(1, both)], Usage())
    assert [r.prompt.splitlines()[0] for r in provider.calls] == ["Tema: Vivienda", "Tema: Economía"]
    # Source 1 of Statement 1 belongs to the Party, which has no stance on it.
    assert outcome.report["source_party_no_stance"] == 1
    assert plan_position_calls([party(1, both)]) == 2


def test_empty_evidence_fails_the_call_and_a_repeat_is_a_generation_error() -> None:
    p1 = party(1, proposal(1, "x", HOUSING))
    with pytest.raises(LLMOutputError):
        assign_positions(
            _fake({"positions": [{"statement": 1, "value": 1, "evidence": []}]}),
            STATEMENTS, [p1], Usage(),
        )
    with pytest.raises(LLMOutputError):  # another Party's number is out of range
        assign_positions(
            _fake({"positions": [{"statement": 1, "value": 1, "evidence": [2]}]}),
            STATEMENTS, [p1], Usage(),
        )
    repeated = {"positions": [{"statement": 1, "value": 1, "evidence": [1]}] * 2}
    with pytest.raises(GenerationError, match="repeated statement 1"):
        assign_positions(_fake(repeated), STATEMENTS, [p1], Usage())


def _sliced_party() -> Any:
    half = POSITION_SLICE_MAX_CHARS // 2 + 1
    return party(
        1,
        proposal(1, "A" * half, HOUSING),
        proposal(2, "B" * half, HOUSING),
    )


def test_slices_merge_same_side_and_disagreement_is_no_stance() -> None:
    p1 = _sliced_party()
    assert plan_position_calls([p1]) == 2
    answers = {
        # Statement 1: +1 then +2 (same side): first value, Evidence union.
        # Statement 2: +1 then -1: no stance, recorded.
        1: [{"statement": 1, "value": 1, "evidence": [1]}, {"statement": 2, "value": 1, "evidence": [1]}],
        2: [{"statement": 1, "value": 2, "evidence": [1]}, {"statement": 2, "value": -1, "evidence": [1]}],
    }
    provider: FakeProvider

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        return {"positions": answers[len(provider.calls)]}

    provider = _fake(respond)
    outcome = assign_positions(provider, STATEMENTS, [p1], Usage())
    first, second = p1.proposals
    assert outcome.positions[1][:2] == [
        V2Position(1, (_ref(first), _ref(second))),
        V2Position(None),
    ]
    assert outcome.report["slice_disagreements"] == [
        {"party_id": 1, "category": "housing", "pool": 2, "values": [1, -1]}
    ]


def test_positions_do_not_depend_on_party_ids_or_order() -> None:
    texts = {"Bajar el alquiler.": 2, "Liberalizar el suelo.": -1, "Bajar el IVA.": 1}

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        proposals = listed_proposals(request)
        value = texts[proposals[0]]
        return {
            "positions": [
                {"statement": k, "value": value, "evidence": [1]}
                for k in range(1, len(listed_statements(request)) + 1)
            ]
        }

    def parties(id_a: int, id_b: int) -> list[Any]:
        return [
            party(id_a, proposal(1, "Bajar el alquiler.", HOUSING), proposal(2, "Bajar el IVA.", ECONOMY)),
            party(id_b, proposal(3, "Liberalizar el suelo.", HOUSING, document=2)),
        ]

    one = assign_positions(_fake(respond), STATEMENTS, parties(1, 2), Usage()).positions
    two = assign_positions(_fake(respond), STATEMENTS, list(reversed(parties(9, 4))), Usage()).positions
    assert [[p.value for p in one[1]], [p.value for p in one[2]]] == [
        [p.value for p in two[9]], [p.value for p in two[4]],
    ]
    assert [p.value for p in one[1]] == [2, 2, 1]
    assert [p.value for p in one[2]] == [-1, -1, None]
