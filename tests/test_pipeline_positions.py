"""Party Position extraction without a database (pipeline-extract-positions).

Unit level for Scenarios 2 (coalition precedence and roles), 4 (no findings or
no documents), 5 (party-blind, deterministic prompts), 6 (invalid output) and
7 (call budget). The run-level versions live in ``test_pipeline_runs.py``.
"""

from typing import Any

import pytest
from pipeline_fixtures import (
    candidate_lines,
    chunk_pages,
    fake_provider,
    findings_response,
    offline_guard,
    positions_response,
)

from ideology_app.llm import FakeProvider, LLMOutputError, LLMProviderError, LLMRequest
from ideology_app.models import SourceDocumentRole
from ideology_app.pipeline import (
    MAX_POSITION_CALLS_PER_RUN,
    DocumentPages,
    GenerationError,
    PositionResult,
    Usage,
    build_chunks,
    extract_positions,
    plan_position_calls,
)

MAIN = SourceDocumentRole.MAIN
ADDITIONAL = SourceDocumentRole.ADDITIONAL

STATEMENTS = [f"Afirmación {n}." for n in range(1, 6)]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def doc(
    party_id: int,
    document_id: int,
    *pages: str,
    role: SourceDocumentRole = MAIN,
    url: str | None = None,
) -> DocumentPages:
    return DocumentPages(
        party_id=party_id,
        document_id=document_id,
        pages=list(enumerate(pages, start=1)),
        source_url=url,
        role=role,
    )


def provider(**overrides: Any) -> FakeProvider:
    return fake_provider(
        **{"position_findings": findings_response(), "party_positions": positions_response()}
        | overrides
    )


def extract(
    fake: FakeProvider,
    documents: list[DocumentPages],
    party_ids: list[int] | None = None,
    statements: list[str] | None = None,
) -> dict[int, list[PositionResult]]:
    party_ids = party_ids if party_ids is not None else sorted({d.party_id for d in documents})
    return extract_positions(fake, statements or STATEMENTS, documents, party_ids, Usage())


def tasks(fake: FakeProvider) -> list[str]:
    return [c.task for c in fake.calls]


# Results shape


def test_every_party_gets_exactly_one_result_per_statement() -> None:
    fake = provider()
    result = extract(fake, [doc(1, 1, "Uno.", "Dos."), doc(2, 2, "Tres.")], [1, 2, 3])

    assert sorted(result) == [1, 2, 3]
    for party_id, positions in result.items():
        assert [p.statement_number for p in positions] == [1, 2, 3, 4, 5], party_id
    assert result[1][:2] == [
        PositionResult(1, 1, 1, "Uno.", 1, None),
        PositionResult(2, 1, 1, "Dos.", 2, None),
    ]
    assert all(p == PositionResult(n, None) for n, p in enumerate(result[1][2:], start=3))
    assert result[2][0] == PositionResult(1, 1, 2, "Tres.", 1, None)
    assert all(p.value is None and p.quote is None for p in result[3])


def test_usage_counts_every_successful_call() -> None:
    fake = provider()
    usage = Usage()
    extract_positions(fake, STATEMENTS, [doc(1, 1, "Uno.")], [1], usage)
    assert usage.calls == 2
    assert usage.input_tokens == sum(len(f"{c.system} {c.prompt}".split()) for c in fake.calls)
    assert usage.output_tokens > 0


# Scenario 2: coalition precedence and document roles


def test_main_document_chunks_come_first_and_candidates_are_labelled() -> None:
    fake = provider()
    # The additional document has the lower id here: role, not id, decides the order.
    documents = [
        doc(1, 4, "Principal uno.", "Principal dos."),
        doc(1, 3, "Adicional uno.", role=ADDITIONAL),
    ]
    result = extract(fake, documents)

    findings = [c for c in fake.calls if c.task == "position_findings"]
    assert [chunk_pages(c) for c in findings] == [
        [(1, "Principal uno."), (2, "Principal dos.")],
        [(1, "Adicional uno.")],
    ]
    reduce = [c for c in fake.calls if c.task == "party_positions"]
    assert len(reduce) == 1
    assert [(c["number"], c["label"], c["quote"]) for c in candidate_lines(reduce[0])] == [
        (1, "programa principal", "Principal uno."),
        (2, "programa principal", "Principal dos."),
        (3, "programa adicional", "Adicional uno."),
    ]
    assert "Si se contradicen, prevalece el programa principal" in reduce[0].system
    # Statement 1 has candidates from both documents; the fake picks the first (main).
    assert result[1][0].document_id == 4


def test_evidence_from_an_additional_document_keeps_its_document_id() -> None:
    def _choose_additional(request: LLMRequest[Any]) -> dict[str, Any]:
        candidate = next(c for c in candidate_lines(request) if c["label"] == "programa adicional")
        return {"positions": [{"statement": 1, "value": -1, "evidence": candidate["number"]}]}

    fake = provider(party_positions=_choose_additional)
    documents = [doc(1, 1, "Principal."), doc(1, 4, "Adicional.", role=ADDITIONAL)]
    assert extract(fake, documents)[1][0] == PositionResult(1, -1, 4, "Adicional.", 1, None)


def test_single_document_party_has_no_additional_label() -> None:
    fake = provider()
    extract(fake, [doc(1, 1, "Uno.", "Dos.")])
    reduce = next(c for c in fake.calls if c.task == "party_positions")
    assert "programa adicional" not in reduce.prompt
    assert {c["label"] for c in candidate_lines(reduce)} == {"programa principal"}


# Scenario 3 (unit): URL documents carry their URL


def test_url_document_evidence_carries_the_url() -> None:
    fake = provider()
    url = "https://example.org/programa.pdf"
    result = extract(fake, [doc(2, 2, "Uno.", "Dos.", url=url)])
    assert result[2][1] == PositionResult(2, 1, 2, "Dos.", 2, url)


# Scenario 4: no findings or no documents -> no stance without a reduce


def test_no_findings_means_no_stance_and_no_reduce() -> None:
    fake = provider(position_findings={"findings": []})
    result = extract(fake, [doc(1, 1, "Uno."), doc(2, 2, "Dos.")])
    assert tasks(fake) == ["position_findings", "position_findings"]
    assert all(p.value is None for positions in result.values() for p in positions)


def test_party_without_documents_gets_no_calls() -> None:
    fake = provider()
    result = extract(fake, [doc(1, 1, "Uno.")], [1, 2])
    assert tasks(fake) == ["position_findings", "party_positions"]
    assert [p.value for p in result[2]] == [None] * 5


def test_whitespace_only_document_gets_no_calls() -> None:
    fake = provider()
    result = extract(fake, [doc(1, 1, "   ", "\n")], [1])
    assert fake.calls == []
    assert [p.value for p in result[1]] == [None] * 5


# Scenario 5: prompts are party-blind and deterministic


def test_findings_prompt_lists_statements_then_one_chunk() -> None:
    fake = provider()
    documents = [doc(1, 1, "Uno.", "Dos.")]
    extract(fake, documents)
    request = fake.calls[0]
    listed = "\n".join(f"[{n}] {text}" for n, text in enumerate(STATEMENTS, start=1))
    assert request.prompt == (
        "Afirmaciones del cuestionario (una por línea, con su número entre corchetes):\n\n"
        f"{listed}\n\n"
        "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
        f"{build_chunks(documents)[0]}\n\n"
        "Indica la posición del programa en las afirmaciones que este fragmento trata, "
        "con una cita literal y su página."
    )
    assert request.max_tokens == 4096
    reduce = fake.calls[1]
    assert listed in reduce.prompt
    assert reduce.max_tokens == 8192
    assert "C1 [programa principal] [afirmación 1] [valor 1] [página 1] «Uno.»" in reduce.prompt


def test_same_input_gives_identical_requests() -> None:
    documents = [doc(2, 2, "Dos."), doc(1, 1, "Uno.", "Más."), doc(1, 5, "Otro.", role=ADDITIONAL)]
    first, second = provider(), provider()
    extract(first, documents)
    extract(second, list(reversed(documents)))
    assert first.calls == second.calls
    # Parties in id order.
    assert chunk_pages(first.calls[0]) == [(1, "Uno."), (2, "Más.")]


# Scenario 6: invalid LLM output


def _findings(*items: dict[str, Any]) -> dict[str, Any]:
    return {"findings": list(items)}


def _finding(**change: Any) -> dict[str, Any]:
    return {"statement": 1, "value": 1, "quote": "Uno.", "page": 1} | change


def _positions(*choices: tuple[int, int, int]) -> dict[str, Any]:
    return {"positions": [{"statement": s, "value": v, "evidence": e} for s, v, e in choices]}


def test_repeated_statement_raises_generation_error() -> None:
    # The schema allows a repeat; extraction rejects it.
    fake = provider(party_positions=_positions((4, 1, 1), (2, 0, 1), (4, -1, 1)))
    with pytest.raises(GenerationError) as info:
        extract(fake, [doc(1, 1, "Uno.")])
    assert str(info.value) == "party_positions repeated statement 4"


@pytest.mark.parametrize("statement", [101, 6, 0], ids=["101", "n-plus-1", "zero"])
def test_finding_for_an_unknown_statement_is_an_output_error(statement: int) -> None:
    fake = provider(position_findings=_findings(_finding(statement=statement)))
    usage = Usage()
    with pytest.raises(LLMOutputError) as info:
        extract_positions(fake, STATEMENTS, [doc(1, 1, "Uno.")], [1], usage)
    assert str(info.value).startswith(
        "FakeProvider response for task 'position_findings' does not match FindingList: "
    )
    assert tasks(fake) == ["position_findings"]
    assert usage.calls == 0


@pytest.mark.parametrize(
    "positions",
    [
        _positions((6, 1, 1)),
        _positions((0, 1, 1)),
        _positions((1, 1, 2)),
        _positions((1, 1, 0)),
        _positions(*[(n, 1, 1) for n in range(1, 6)], (1, 1, 1)),
    ],
    ids=["statement-n-plus-1", "statement-0", "evidence-k-plus-1", "evidence-0",
         "n-plus-1-entries"],
)
def test_choice_out_of_range_is_an_output_error(positions: dict[str, Any]) -> None:
    fake = provider(party_positions=positions)
    usage = Usage()
    with pytest.raises(LLMOutputError) as info:
        extract_positions(fake, STATEMENTS, [doc(1, 1, "Uno.")], [1], usage)
    assert str(info.value).startswith(
        "FakeProvider response for task 'party_positions' does not match PositionList: "
    )
    assert usage.calls == 1  # the findings call succeeded


def test_request_schemas_carry_the_statement_and_candidate_bounds() -> None:
    fake = provider(
        position_findings=_findings(
            _finding(statement=1), _finding(statement=2), _finding(statement=5)
        )
    )
    extract(fake, [doc(1, 1, "Uno.")])
    findings, reduce = fake.calls
    assert findings.schema.__name__ == "FindingList"
    finding = findings.schema.model_json_schema()["$defs"]["Finding"]["properties"]
    assert finding["statement"]["maximum"] == len(STATEMENTS)
    assert reduce.schema.__name__ == "PositionList"
    positions = reduce.schema.model_json_schema()
    choice = positions["$defs"]["PositionChoice"]["properties"]
    assert choice["statement"]["maximum"] == len(STATEMENTS)
    assert choice["evidence"]["maximum"] == 3  # C1..C3
    assert positions["properties"]["positions"]["maxItems"] == len(STATEMENTS)


def test_any_candidate_may_support_any_statement() -> None:
    fake = provider(
        position_findings=_findings(_finding(statement=1), _finding(statement=2, quote="Dos.")),
        party_positions=_positions((5, 2, 1), (1, -2, 2)),
    )
    result = extract(fake, [doc(1, 1, "Uno.")])
    assert result[1][4] == PositionResult(5, 2, 1, "Uno.", 1, None)
    assert result[1][0] == PositionResult(1, -2, 1, "Dos.", 1, None)


@pytest.mark.parametrize(
    "bad",
    [
        _findings(_finding(value=3)),
        _findings(_finding(quote="")),
        _findings(_finding(quote="x" * 501)),
        _findings(_finding(page=0)),
    ],
    ids=["value-3", "empty-quote", "long-quote", "page-0"],
)
def test_schema_mismatch_raises_output_error(bad: dict[str, Any]) -> None:
    fake = provider(position_findings=bad)
    with pytest.raises(LLMOutputError, match="does not match FindingList"):
        extract(fake, [doc(1, 1, "Uno.")])


def test_provider_errors_propagate_and_usage_keeps_successful_calls() -> None:
    def _boom(request: LLMRequest[Any]) -> dict[str, Any]:
        raise LLMProviderError("APIConnectionError")

    fake = provider(party_positions=_boom)
    usage = Usage()
    with pytest.raises(LLMProviderError):
        extract_positions(fake, STATEMENTS, [doc(1, 1, "Uno.")], [1], usage)
    assert usage.calls == 1


# Scenario 7: the call budget


def test_plan_counts_chunks_plus_one_reduce_per_party_with_chunks() -> None:
    documents = [
        doc(1, 1, "Uno.", "Dos."),
        doc(1, 2, "Tres.", role=ADDITIONAL),
        doc(2, 3, "Cuatro."),
        doc(3, 4, "  "),
    ]
    assert plan_position_calls(documents) == 3 + 2
    assert plan_position_calls([]) == 0
    big = doc(1, 9, *(["x" * 30_000] * 3))
    assert plan_position_calls([big]) == 3 + 1


def test_plan_matches_the_calls_made_when_every_party_has_findings() -> None:
    documents = [doc(1, 1, "Uno.", "Dos."), doc(1, 2, "Tres.", role=ADDITIONAL), doc(2, 3, "C.")]
    fake = provider()
    extract(fake, documents)
    assert len(fake.calls) == plan_position_calls(documents)


def test_cap_constant() -> None:
    assert MAX_POSITION_CALLS_PER_RUN == 300
