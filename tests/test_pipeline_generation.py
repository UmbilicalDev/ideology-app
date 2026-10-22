"""Chunking and the map/reduce generation, without a database (Scenarios 3-5)."""

import re
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
    Chunk,
    DocumentPages,
    GenerationError,
    StatementPool,
    Usage,
    build_chunks,
    build_document_chunks,
    generate_statements,
)
from ideology_app.pipeline.generation import candidate_request, pool_bounds, reduce_request
from ideology_app.pipeline.prompts import StatementDraft, StatementSet


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def chunks_of(*texts: str, party_id: int = 1) -> list[Chunk]:
    """Chunks of one Party's document, one per text."""
    return [Chunk(party_id=party_id, document_id=party_id, text=t) for t in texts]


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


def test_chunk_pages_list_the_pages_each_chunk_holds() -> None:
    # pipeline-verified-findings: a finding may only cite a page of its chunk.
    small = "a" * 15_000
    huge = "".join(chr(ord("a") + i % 26) for i in range(95_000))
    document = doc(1, 1, small, small, small, "   ", huge, "fin")

    chunks = build_document_chunks([document])

    # Whitespace page 4 is in no chunk; huge page 5 is in every chunk with a slice.
    assert [c.pages for c in chunks] == [(1, 2), (3,), (5,), (5,), (5, 6)]
    assert [c.text for c in chunks] == build_chunks([document])
    for chunk in chunks:
        markers = [int(n) for n in re.findall(r"\[página (\d+)\]", chunk.text)]
        assert chunk.pages == tuple(dict.fromkeys(markers))


def test_chunk_pages_default_to_empty() -> None:
    assert Chunk(1, 1, "texto").pages == ()


def test_page_exactly_at_the_limit_is_not_cut() -> None:
    marker = "[página 1]\n"
    text = "x" * (CHUNK_MAX_CHARS - len(marker))
    assert build_chunks([doc(1, 1, text)]) == [marker + text]
    text_plus = text + "y"
    chunks = build_chunks([doc(1, 1, text_plus)])
    assert chunks == [marker + text, marker + "y"]


def test_one_candidates_call_per_chunk() -> None:
    documents = [doc(1, 1, "a" * 30_000, "b" * 30_000), doc(2, 2, "c")]
    chunks = build_document_chunks(documents)
    assert [c.text for c in chunks] == build_chunks(documents)
    provider = fake_provider()
    generate_statements(provider, chunks, Usage())
    tasks = [c.task for c in provider.calls]
    assert tasks == ["statement_candidates"] * 3 + ["generate_statements"]
    assert [c.prompt for c in provider.calls[:3]] == [
        candidate_request(c.text).prompt for c in chunks
    ]


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
    assert request.max_tokens == 16384
    assert "- [economy] Beta.\n- [economy] Zeta.\n- [health] Zeta.\n- [housing] Alfa." in (
        request.prompt
    )
    assert request.prompt.count("Zeta.") == 2
    assert "55 afirmaciones" in request.prompt
    assert "(como mínimo 45 y como máximo 60)" in request.prompt


def test_generation_returns_statements_as_given_and_counts_usage() -> None:
    provider = fake_provider()
    usage = Usage()
    pool = generate_statements(provider, chunks_of("[página 1]\nA", "[página 1]\nB"), usage)
    statements = pool.statements
    assert isinstance(pool, StatementPool)

    expected = statements_payload()["statements"]
    assert [(s.text, s.topic) for s in statements] == [(e["text"], e["topic"]) for e in expected]
    assert usage.calls == 3
    # The fake counts words of the request (in) and of the JSON output (out).
    assert usage.input_tokens == sum(
        len(f"{c.system} {c.prompt}".split()) for c in provider.calls
    )
    assert usage.output_tokens > 0


def test_same_input_gives_identical_requests() -> None:
    chunks = build_document_chunks([doc(1, 1, "Uno", "Dos"), doc(2, 2, "Tres")])
    first, second = fake_provider(), fake_provider()
    generate_statements(first, chunks, Usage())
    generate_statements(second, list(chunks), Usage())
    assert first.calls == second.calls


# Scenario 5 (generation part)


def test_no_candidates_raises_generation_error() -> None:
    provider = fake_provider(statement_candidates={"candidates": []})
    usage = Usage()
    with pytest.raises(GenerationError) as excinfo:
        generate_statements(provider, chunks_of("a", "b"), usage)
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
        generate_statements(provider, chunks_of(*["x"] * MAX_LLM_CALLS_PER_RUN), Usage())
    assert str(excinfo.value) == "too many chunks: 200 (limit 199)"
    assert provider.calls == []


def test_chunk_count_at_the_limit_is_allowed() -> None:
    provider = fake_provider()
    usage = Usage()
    generate_statements(provider, chunks_of(*["x"] * (MAX_LLM_CALLS_PER_RUN - 1)), usage)
    assert usage.calls == MAX_LLM_CALLS_PER_RUN


def test_llm_error_propagates_and_keeps_partial_usage() -> None:
    def _fail_second(request: LLMRequest[Any]) -> dict[str, Any]:
        if "segundo" in request.prompt:
            raise LLMProviderError("APIConnectionError")
        return candidates_response()(request)

    provider = FakeProvider({"statement_candidates": _fail_second})
    usage = Usage()
    with pytest.raises(LLMProviderError):
        generate_statements(provider, chunks_of("primero", "segundo", "tercero"), usage)
    assert usage.calls == 1
    assert usage.input_tokens > 0


def test_schema_mismatch_is_an_output_error() -> None:
    provider = fake_provider(generate_statements={"statements": [{"text": "x", "topic": "?"}]})
    usage = Usage()
    with pytest.raises(LLMOutputError):
        generate_statements(provider, chunks_of("a"), usage)
    assert usage.calls == 1


# pipeline-output-bounds / pipeline-coverage-selection: the reduce schema
# bounds the Statement Pool size (pool_bounds of the run's ValidationSettings).


@pytest.mark.parametrize("count", [20, 35, 44, 61])
def test_out_of_range_pool_fails_the_call(count: int) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    usage = Usage()
    with pytest.raises(LLMOutputError) as excinfo:
        generate_statements(provider, chunks_of("a"), usage)
    assert str(excinfo.value).startswith(
        "FakeProvider response for task 'generate_statements' does not match StatementSet: "
    )
    assert usage.calls == 1  # only the candidates call succeeded


@pytest.mark.parametrize("count", [45, 55, 60])
def test_pool_size_at_the_default_limits_passes(count: int) -> None:
    provider = fake_provider(generate_statements=statements_payload(count))
    assert len(generate_statements(provider, chunks_of("a"), Usage()).statements) == count


@pytest.mark.parametrize(
    ("low", "high", "bounds"),
    [
        (25, 35, (45, 60, 55)),
        (10, 12, (45, 60, 55)),
        (36, 50, (50, 60, 55)),
        (40, 58, (58, 60, 58)),
        (60, 60, (60, 60, 60)),
        (1, 70, (70, 70, 70)),
    ],
)
def test_pool_schema_bounds_follow_settings(
    low: int, high: int, bounds: tuple[int, int, int]
) -> None:
    settings = ValidationSettings(min_statements=low, max_statements=high)
    assert pool_bounds(settings) == bounds
    request = reduce_request([StatementDraft(text="Alfa.", topic="housing")], settings)
    assert issubclass(request.schema, StatementSet)
    schema = request.schema.model_json_schema()["properties"]["statements"]
    assert (schema["minItems"], schema["maxItems"]) == bounds[:2]
    # The pool is never smaller than the largest allowed Questionnaire.
    assert schema["minItems"] >= high


def test_configured_range_drives_the_pool_schema() -> None:
    settings = ValidationSettings(min_statements=1, max_statements=70)
    provider = fake_provider(generate_statements=statements_payload(70))
    pool = generate_statements(provider, chunks_of("a"), Usage(), settings=settings)
    assert len(pool.statements) == 70
    request = provider.calls[-1]
    bounds = request.schema.model_json_schema()["properties"]["statements"]
    assert (bounds["minItems"], bounds["maxItems"]) == (70, 70)
    assert "70 afirmaciones (como mínimo 70 y como máximo 70)" in request.prompt

    narrow = fake_provider(generate_statements=statements_payload(60))
    with pytest.raises(LLMOutputError, match="does not match StatementSet"):
        generate_statements(narrow, chunks_of("a"), Usage(), settings=settings)


def test_default_settings_bound_the_reduce_request() -> None:
    drafts = [StatementDraft(text="Alfa.", topic="housing")]
    request = reduce_request(drafts)
    assert request.schema is reduce_request(drafts, ValidationSettings()).schema
    assert pool_bounds() == pool_bounds(ValidationSettings()) == (45, 60, 55)
    bounds = request.schema.model_json_schema()["properties"]["statements"]
    assert (bounds["minItems"], bounds["maxItems"]) == (45, 60)
    assert request.schema is not StatementSet  # the 1..60 base type is never sent


@pytest.mark.parametrize(
    ("low", "high", "line"),
    [
        (25, 35, "55 afirmaciones (como mínimo 45 y como máximo 60)"),
        (40, 58, "58 afirmaciones (como mínimo 58 y como máximo 60)"),
        (1, 70, "70 afirmaciones (como mínimo 70 y como máximo 70)"),
    ],
)
def test_pool_prompt_asks_for_target(low: int, high: int, line: str) -> None:
    settings = ValidationSettings(min_statements=low, max_statements=high)
    request = reduce_request([StatementDraft(text="Alfa.", topic="housing")], settings)
    assert f"Elabora una lista de {line}, en el orden en que deben presentarse." in (
        request.prompt
    )
