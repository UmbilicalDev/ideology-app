"""Chunking and the map/reduce generation, without a database (Scenarios 3-5)."""

from typing import Any

import pytest
from pipeline_fixtures import candidates_response, fake_provider, offline_guard, statements_payload

from ideology_app.config import ValidationSettings
from ideology_app.llm import FakeProvider, LLMOutputError, LLMProviderError, LLMRequest
from ideology_app.pipeline import (
    CHUNK_MAX_CHARS,
    GENERATE_STATEMENTS,
    MAX_LLM_CALLS_PER_RUN,
    NO_CANDIDATES_REASON,
    STATEMENT_CANDIDATES,
    DocumentPages,
    GenerationError,
    Usage,
    build_chunks,
    generate_statements,
)
from ideology_app.pipeline.generation import candidate_request, reduce_request
from ideology_app.pipeline.prompts import StatementDraft, StatementSet


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def doc(party_id: int, document_id: int, *texts: str) -> DocumentPages:
    return DocumentPages(
        party_id=party_id,
        document_id=document_id,
        pages=[(n, t) for n, t in enumerate(texts, start=1)],
    )


# Scenario 4: chunking


def test_small_document_is_one_chunk_with_page_markers() -> None:
    chunks = build_chunks([doc(1, 1, "Uno.\nlínea", "Dos.")])
    assert chunks == ["[página 1]\nUno.\nlínea\n\n[página 2]\nDos."]


def test_each_document_gets_its_own_chunks_ordered_by_party_then_document() -> None:
    documents = [doc(2, 5, "B5"), doc(1, 9, "A9"), doc(1, 4, "A4"), doc(2, 1, "B1")]
    assert build_chunks(documents) == [
        "[página 1]\nA4",
        "[página 1]\nA9",
        "[página 1]\nB1",
        "[página 1]\nB5",
    ]


def test_pages_are_ordered_by_page_number_and_whitespace_pages_skipped() -> None:
    document = DocumentPages(
        party_id=1, document_id=1, pages=[(3, "Tres"), (1, "Uno"), (2, " \n\t ")]
    )
    assert build_chunks([document]) == ["[página 1]\nUno\n\n[página 3]\nTres"]


def test_document_with_only_whitespace_pages_has_no_chunk() -> None:
    assert build_chunks([doc(1, 1, "  ", "\n")]) == []


def test_long_document_is_split_into_whole_pages_under_the_limit() -> None:
    small = "a" * 15_000
    huge = "".join(chr(ord("a") + i % 26) for i in range(95_000))
    document = doc(1, 1, small, small, small, "   ", huge, "fin")

    chunks = build_chunks([document])

    assert len(chunks) > 3
    assert all(len(c) <= CHUNK_MAX_CHARS for c in chunks)
    # Pages 1+2 fit together (30k + markers); page 3 starts a new chunk.
    assert chunks[0] == f"[página 1]\n{small}\n\n[página 2]\n{small}"
    assert chunks[1].startswith(f"[página 3]\n{small}")
    assert "[página 4]" not in "".join(chunks)
    # The huge page is cut into consecutive slices, each under its marker.
    slices = [c for c in chunks if "[página 5]" in c]
    rebuilt = "".join(
        piece.split("[página 5]\n", 1)[1].split("\n\n[página 6]")[0]
        for c in slices
        for piece in c.split("\n\n")
        if piece.startswith("[página 5]")
    )
    assert rebuilt == huge
    assert len(slices) == 3
    assert chunks[-1].endswith("[página 6]\nfin")


def test_page_exactly_at_the_limit_is_not_cut() -> None:
    marker = "[página 1]\n"
    text = "x" * (CHUNK_MAX_CHARS - len(marker))
    assert build_chunks([doc(1, 1, text)]) == [marker + text]
    text_plus = text + "y"
    chunks = build_chunks([doc(1, 1, text_plus)])
    assert chunks == [marker + text, marker + "y"]


def test_one_candidates_call_per_chunk() -> None:
    chunks = build_chunks([doc(1, 1, "a" * 30_000, "b" * 30_000), doc(2, 2, "c")])
    provider = fake_provider()
    generate_statements(provider, chunks, Usage())
    tasks = [c.task for c in provider.calls]
    assert tasks == ["statement_candidates"] * 3 + ["generate_statements"]
    assert [c.prompt for c in provider.calls[:3]] == [candidate_request(c).prompt for c in chunks]


# Scenario 3: deterministic, party-blind requests


def test_candidate_request_holds_the_chunk_and_versioned_prompt() -> None:
    request = candidate_request("[página 1]\nTexto {con llaves}")
    assert request.task == "statement_candidates"
    assert request.system == STATEMENT_CANDIDATES.system
    assert "[página 1]\nTexto {con llaves}" in request.prompt
    assert request.schema is STATEMENT_CANDIDATES.schema
    assert request.max_tokens == 4096


def test_reduce_request_dedupes_and_sorts_candidates() -> None:
    drafts = [
        StatementDraft(text="Zeta.", topic="economy"),
        StatementDraft(text="Alfa.", topic="housing"),
        StatementDraft(text="Beta.", topic="economy"),
        StatementDraft(text="Zeta.", topic="economy"),
        StatementDraft(text="Zeta.", topic="health"),
    ]
    request = reduce_request(drafts)
    assert request.task == "generate_statements"
    assert request.system == GENERATE_STATEMENTS.system
    assert request.max_tokens == 8192
    assert "- [economy] Beta.\n- [economy] Zeta.\n- [health] Zeta.\n- [housing] Alfa." in (
        request.prompt
    )
    assert request.prompt.count("Zeta.") == 2
    assert "30 afirmaciones" in request.prompt
    assert "(como mínimo 25 y como máximo 35)" in request.prompt


def test_generation_returns_statements_as_given_and_counts_usage() -> None:
    provider = fake_provider()
    usage = Usage()
    statements = generate_statements(provider, ["[página 1]\nA", "[página 1]\nB"], usage)

    expected = statements_payload()["statements"]
    assert [(s.text, s.topic) for s in statements] == [(e["text"], e["topic"]) for e in expected]
    assert usage.calls == 3
    # The fake counts words of the request (in) and of the JSON output (out).
    assert usage.input_tokens == sum(
        len(f"{c.system} {c.prompt}".split()) for c in provider.calls
    )
    assert usage.output_tokens > 0


def test_same_input_gives_identical_requests() -> None:
    chunks = build_chunks([doc(1, 1, "Uno", "Dos"), doc(2, 2, "Tres")])
    first, second = fake_provider(), fake_provider()
    generate_statements(first, chunks, Usage())
    generate_statements(second, list(chunks), Usage())
    assert first.calls == second.calls


# Scenario 5 (generation part)


def test_no_candidates_raises_generation_error() -> None:
    provider = fake_provider(statement_candidates={"candidates": []})
    usage = Usage()
    with pytest.raises(GenerationError) as excinfo:
        generate_statements(provider, ["a", "b"], usage)
    assert str(excinfo.value) == NO_CANDIDATES_REASON
    assert usage.calls == 2
    assert [c.task for c in provider.calls] == ["statement_candidates"] * 2


def test_no_chunks_raises_generation_error_without_calls() -> None:
    provider = fake_provider()
    with pytest.raises(GenerationError, match=NO_CANDIDATES_REASON):
        generate_statements(provider, [], Usage())
    assert provider.calls == []


def test_too_many_chunks_fails_before_any_call() -> None:
    provider = fake_provider()
    with pytest.raises(GenerationError) as excinfo:
        generate_statements(provider, ["x"] * MAX_LLM_CALLS_PER_RUN, Usage())
    assert str(excinfo.value) == "too many chunks: 200 (limit 199)"
    assert provider.calls == []


def test_chunk_count_at_the_limit_is_allowed() -> None:
    provider = fake_provider()
    usage = Usage()
    generate_statements(provider, ["x"] * (MAX_LLM_CALLS_PER_RUN - 1), usage)
    assert usage.calls == MAX_LLM_CALLS_PER_RUN


def test_llm_error_propagates_and_keeps_partial_usage() -> None:
    def _fail_second(request: LLMRequest[Any]) -> dict[str, Any]:
        if "segundo" in request.prompt:
            raise LLMProviderError("APIConnectionError")
        return candidates_response()(request)

    provider = FakeProvider({"statement_candidates": _fail_second})
    usage = Usage()
    with pytest.raises(LLMProviderError):
        generate_statements(provider, ["primero", "segundo", "tercero"], usage)
    assert usage.calls == 1
    assert usage.input_tokens > 0


def test_schema_mismatch_is_an_output_error() -> None:
    provider = fake_provider(generate_statements={"statements": [{"text": "x", "topic": "?"}]})
    usage = Usage()
    with pytest.raises(LLMOutputError):
        generate_statements(provider, ["a"], usage)
    assert usage.calls == 1


# pipeline-output-bounds: the reduce schema bounds the Statement count.


@pytest.mark.parametrize("count", [20, 38, 44])
def test_out_of_range_statement_count_is_an_output_error(count: int) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    usage = Usage()
    with pytest.raises(LLMOutputError) as excinfo:
        generate_statements(provider, ["a"], usage)
    assert str(excinfo.value).startswith(
        "FakeProvider response for task 'generate_statements' does not match StatementSet: "
    )
    assert usage.calls == 1  # only the candidates call succeeded


@pytest.mark.parametrize("count", [25, 35])
def test_statement_count_at_the_default_limits_passes(count: int) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    assert len(generate_statements(provider, ["a"], Usage())) == count


def test_configured_range_drives_the_schema_and_prompt() -> None:
    settings = ValidationSettings(min_statements=36, max_statements=40)
    provider = fake_provider(generate_statements=statements_payload(38))
    statements = generate_statements(provider, ["a"], Usage(), settings=settings)
    assert len(statements) == 38
    request = provider.calls[-1]
    assert issubclass(request.schema, StatementSet)
    bounds = request.schema.model_json_schema()["properties"]["statements"]
    assert (bounds["minItems"], bounds["maxItems"]) == (36, 40)
    assert "36 afirmaciones del cuestionario (como mínimo 36 y como máximo 40)" in (
        request.prompt
    )

    narrow = fake_provider(generate_statements=statements_payload(30))
    with pytest.raises(LLMOutputError, match="does not match StatementSet"):
        generate_statements(narrow, ["a"], Usage(), settings=settings)


def test_default_settings_bound_the_reduce_request() -> None:
    drafts = [StatementDraft(text="Alfa.", topic="housing")]
    request = reduce_request(drafts)
    assert request.schema is reduce_request(drafts, ValidationSettings()).schema
    bounds = request.schema.model_json_schema()["properties"]["statements"]
    assert (bounds["minItems"], bounds["maxItems"]) == (25, 35)
    assert request.schema is not StatementSet  # the 1..60 base type is never sent


@pytest.mark.parametrize(
    ("low", "high", "count"), [(10, 20, 20), (36, 40, 36), (25, 35, 30), (30, 30, 30)]
)
def test_requested_count_is_the_target_clamped_to_the_range(
    low: int, high: int, count: int
) -> None:
    settings = ValidationSettings(min_statements=low, max_statements=high)
    request = reduce_request([StatementDraft(text="Alfa.", topic="housing")], settings)
    assert (
        f"lista final de {count} afirmaciones del cuestionario "
        f"(como mínimo {low} y como máximo {high})"
    ) in request.prompt
