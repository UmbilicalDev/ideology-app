"""Party Position extraction without a database (pipeline-extract-positions).

Unit level for Scenarios 2 (coalition precedence and roles), 4 (no findings or
no documents), 5 (party-blind, deterministic prompts), 6 (invalid output) and
7 (call budget). The run-level versions live in ``test_pipeline_runs.py``.
pipeline-verified-findings Scenarios 1-3 (unit) are at the end.
"""

import dataclasses
import inspect
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
    FindingCheck,
    GenerationError,
    PositionResult,
    Usage,
    build_chunks,
    extract_positions,
    plan_position_calls,
)
from ideology_app.pipeline import positions as positions_module
from ideology_app.validation import (
    PositionRow,
    RunDocument,
    StatementRow,
    ValidationInput,
    evidence_quotes,
)
from ideology_app.validation.evidence_quotes import check_evidence_quotes

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
        "Afirmaciones del cuestionario que revisar en este fragmento (una parte del "
        "cuestionario; una por línea, con su número entre corchetes):\n\n"
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
    # Both quotes are on page 1, so both findings are verified.
    result = extract(fake, [doc(1, 1, "Uno. Dos.")])
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
    # e2e-real-2026-election: one findings call per chunk and Statement batch;
    # the default plans for the largest pool (80 Statements = 4 batches).
    assert plan_position_calls(documents, statement_count=len(STATEMENTS)) == 3 + 2
    assert plan_position_calls(documents) == 3 * 4 + 2
    assert plan_position_calls(documents, statement_count=61) == 3 * 4 + 2
    assert plan_position_calls(documents, statement_count=60) == 3 * 3 + 2
    assert plan_position_calls(documents, statement_count=41) == 3 * 3 + 2
    assert plan_position_calls(documents, statement_count=40) == 3 * 2 + 2
    assert plan_position_calls([]) == 0
    big = doc(1, 9, *(["x" * 30_000] * 3))
    assert plan_position_calls([big], statement_count=len(STATEMENTS)) == 3 + 1


def test_plan_matches_the_calls_made_when_every_party_has_findings() -> None:
    documents = [doc(1, 1, "Uno.", "Dos."), doc(1, 2, "Tres.", role=ADDITIONAL), doc(2, 3, "C.")]
    fake = provider()
    extract(fake, documents)
    assert len(fake.calls) == plan_position_calls(documents, statement_count=len(STATEMENTS))
    pool = [f"Afirmación {n}." for n in range(1, 46)]
    fake = provider()
    extract(fake, documents, statements=pool)
    assert len(fake.calls) == plan_position_calls(documents, statement_count=len(pool))


def test_cap_constant() -> None:
    assert MAX_POSITION_CALLS_PER_RUN == 300


def test_requests_bound_to_pool_size() -> None:
    # pipeline-coverage-selection: positions are extracted for the whole pool,
    # so every bound follows the pool size (60 here), not the Questionnaire's.
    pool = [f"Afirmación {n} del conjunto amplio." for n in range(1, 61)]
    fake = provider(position_findings=_findings(_finding(statement=60), _finding(statement=1)))

    results = extract(fake, [doc(1, 1, "Uno.")], statements=pool)

    assert [len(r) for r in results.values()] == [60]
    assert results[1][0].value is not None
    assert results[1][59].value is not None
    *batches, reduce = fake.calls
    assert len(batches) == 3
    listed = "\n".join(f"[{n}] {text}" for n, text in enumerate(pool, start=1))
    assert listed in reduce.prompt
    for findings in batches:
        # Each batch call is bounded by the whole pool, not by its batch.
        finding = findings.schema.model_json_schema()["$defs"]["Finding"]["properties"]
        assert finding["statement"]["maximum"] == 60
    positions = reduce.schema.model_json_schema()
    assert positions["$defs"]["PositionChoice"]["properties"]["statement"]["maximum"] == 60
    assert positions["properties"]["positions"]["maxItems"] == 60


# pipeline-verified-findings: unverifiable findings never become Evidence


def _verified_and_slipped(request: LLMRequest[Any]) -> dict[str, Any]:
    return _findings(
        _finding(statement=1, quote="las sustituiremos", page=1),
        _finding(statement=2, value=-1, quote="Ley de Vivienda", page=1),
    )


def test_slipped_quote_is_no_stance_and_the_verified_one_is_kept() -> None:
    # Scenario 1: "las" for "la". The reduce cites both candidates.
    fake = provider(
        position_findings=_verified_and_slipped,
        party_positions=_positions((1, 1, 1), (2, -1, 2)),
    )
    check = FindingCheck()
    page = "La Ley de Vivienda: la sustituiremos por otra."
    url = "https://example.org/programa.pdf"
    result = extract_positions(
        fake, STATEMENTS, [doc(1, 7, page, url=url)], [1, 2], Usage(), check
    )

    assert result[1][0] == PositionResult(1, None)
    assert result[1][1] == PositionResult(2, -1, 7, "Ley de Vivienda", 1, url)
    # The request is unchanged: it still lists the slipped candidate.
    reduce = [c for c in fake.calls if c.task == "party_positions"][0]
    assert [c["quote"] for c in candidate_lines(reduce)] == ["las sustituiremos", "Ley de Vivienda"]
    assert check.report() == {
        "version": "v2",
        "checked": 2,
        "discarded": 1,
        "cleared": 1,
        "repaired": 0,
        "parties": [
            {"party_id": 1, "findings": 2, "discarded": 1, "cleared": 1, "repaired": 0},
            {"party_id": 2, "findings": 0, "discarded": 0, "cleared": 0, "repaired": 0},
        ],
        "items": [
            {
                "party_id": 1,
                "document_id": 7,
                "page": 1,
                "statement": 1,
                "value": 1,
                "reason": "not_found",
                "found_on": None,
                "cleared": [1],
                "quote": "las sustituiremos",
            }
        ],
        "repaired_items": [],
    }


def test_a_discarded_finding_not_cited_clears_nothing() -> None:
    fake = provider(
        position_findings=_verified_and_slipped, party_positions=_positions((2, -1, 2))
    )
    check = FindingCheck()
    extract_positions(fake, STATEMENTS, [doc(1, 1, "la Ley de Vivienda")], [1], Usage(), check)
    report = check.report()
    assert (report["checked"], report["discarded"], report["cleared"]) == (2, 1, 0)
    assert report["items"][0]["cleared"] == []


def test_one_discarded_finding_cited_twice_clears_both_statements() -> None:
    fake = provider(
        position_findings=_findings(_finding(quote="Nada de esto.")),
        party_positions=_positions((1, 1, 1), (3, 1, 1)),
    )
    check = FindingCheck()
    result = extract_positions(fake, STATEMENTS, [doc(1, 1, "Uno.")], [1], Usage(), check)
    assert all(p == PositionResult(n, None) for n, p in enumerate(result[1], start=1))
    assert check.report()["items"][0]["cleared"] == [1, 3]
    assert check.report()["cleared"] == 2


def test_party_with_only_unverifiable_findings_still_gets_its_reduce_call() -> None:
    documents = [doc(1, 1, "Uno.", "Dos.")]
    fake = provider(position_findings=_findings(_finding(quote="Inventada.")))
    result = extract(fake, documents)
    assert tasks(fake) == ["position_findings", "party_positions"]
    assert len(fake.calls) == plan_position_calls(documents, statement_count=len(STATEMENTS))
    assert all(p.value is None for p in result[1])


def test_repeated_statement_still_raises_when_a_choice_cites_a_discarded_finding() -> None:
    fake = provider(
        position_findings=_findings(_finding(quote="Inventada.")),
        party_positions=_positions((1, 1, 1), (1, 1, 1)),
    )
    with pytest.raises(GenerationError, match="repeated statement 1"):
        extract(fake, [doc(1, 1, "Uno.")])


def test_cited_page_outside_the_chunk_is_discarded_even_if_the_quote_is_there() -> None:
    # Scenario 2: two chunks (each page is near the size limit). The first
    # chunk's finding cites page 2, where the quote is, but page 2 is not in it.
    first, second = "Uno. " + "a" * 39_000, "Dos. " + "b" * 39_000

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        statement = 1 if chunk_pages(request)[0][0] == 1 else 2
        return _findings(_finding(statement=statement, quote="Dos.", page=2))

    fake = provider(position_findings=_respond, party_positions=positions_response())
    check = FindingCheck()
    result = extract_positions(fake, STATEMENTS, [doc(1, 1, first, second)], [1], Usage(), check)

    assert tasks(fake) == ["position_findings", "position_findings", "party_positions"]
    assert result[1][0] == PositionResult(1, None)
    assert result[1][1] == PositionResult(2, 1, 1, "Dos.", 2, None)
    item = check.report()["items"][0]
    assert (item["reason"], item["page"], item["cleared"]) == ("page_not_in_chunk", 2, [1])


def test_other_page_records_where_the_quote_starts() -> None:
    # e2e-real-2026-election: a page of the same chunk would be repaired, so the
    # quote is on page 2 in a second chunk (each page is near the size limit).
    first, second = "Uno. " + "a" * 39_000, "Texto de la página dos. " + "b" * 39_000

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        if chunk_pages(request)[0][0] != 1:
            return _findings()
        return _findings(_finding(quote="Texto de la página dos."))

    fake = provider(position_findings=_respond)
    check = FindingCheck()
    extract_positions(fake, STATEMENTS, [doc(1, 1, first, second)], [1], Usage(), check)
    report = check.report()
    assert report["repaired_items"] == []
    item = report["items"][0]
    assert (item["reason"], item["found_on"], item["cleared"]) == ("other_page", 2, [1])


def test_other_page_in_the_same_chunk_is_repaired_and_kept() -> None:
    # e2e-real-2026-election (findings check v2): the quote is verbatim on
    # another page of the finding's own chunk, so the page is corrected.
    fake = provider(position_findings=_findings(_finding(quote="Texto de la página dos.")))
    check = FindingCheck()
    result = extract_positions(
        fake, STATEMENTS, [doc(1, 1, "Uno.", "Texto de la página dos.")], [1], Usage(), check
    )
    assert result[1][0] == PositionResult(1, 1, 1, "Texto de la página dos.", 2, None)
    report = check.report()
    assert (report["discarded"], report["cleared"], report["repaired"]) == (0, 0, 1)
    assert report["items"] == []
    assert report["parties"][0]["repaired"] == 1
    assert report["repaired_items"] == [
        {
            "party_id": 1,
            "document_id": 1,
            "page": 1,
            "statement": 1,
            "value": 1,
            "kind": "page_corrected",
            "new_page": 2,
            "quote": "Texto de la página dos.",
            "new_quote": "Texto de la página dos.",
        }
    ]


def test_extraction_uses_the_evidence_quotes_matcher() -> None:
    # Scenario 3: one matcher, shared with Validation; no second normaliser.
    assert positions_module.find_quote_miss is evidence_quotes.find_quote_miss
    assert positions_module.normalize_pages is evidence_quotes.normalize_pages
    source = inspect.getsource(positions_module)
    assert "unicodedata" not in source and "casefold" not in source


# (pages, cited page, quote, kept?, reason)
MATCH_CASES = [
    (["La sustituiremos."], 1, "las sustituiremos", False, "not_found"),
    (["Uno.", "Texto de la dos."], 1, "Texto de la dos.", False, "other_page"),
    (["Uno."], 1, "... ¡! —", False, "no_letters"),
    (["Empieza aquí y", "sigue en la siguiente."], 1, "aquí y sigue en", True, None),
    (["Política PÚBLICA de vivienda"], 1, "politica publica", True, None),
    (["ﬁnanciación autonómica"], 1, "financiacion autonomica", True, None),
    (["vivienda, alquiler\n y  suelo"], 1, "Vivienda alquiler y suelo.", True, None),
    (["Uno.", "Dos y", "tres."], 2, "dos y tres", True, None),
    (["Uno.", "Dos y", "tres."], 1, "dos y tres", False, "other_page"),
]


@pytest.mark.parametrize(("pages", "page", "quote", "kept", "reason"), MATCH_CASES)
def test_extraction_and_validation_give_the_same_verdict(
    pages: list[str], page: int, quote: str, kept: bool, reason: str | None
) -> None:
    fake = provider(
        position_findings=_findings(_finding(quote=quote, page=page)),
        party_positions=_positions((1, 1, 1)),
    )
    check = FindingCheck()
    result = extract_positions(fake, STATEMENTS, [doc(1, 1, *pages)], [1], Usage(), check)
    report = check.report()
    if reason == "other_page":
        # e2e-real-2026-election (findings check v2): the matcher's raw verdict is
        # still other_page (it is the repair's input), but these quotes are verbatim
        # on another page of the finding's own chunk, so extraction corrects the
        # page instead of discarding. Validation below gets the raw verdict.
        assert report["items"] == []
        assert [(i["kind"], i["page"], i["new_page"], i["new_quote"])
                for i in report["repaired_items"]] == [("page_corrected", page, 2, quote)]
        assert (result[1][0].value, result[1][0].quote, result[1][0].page) == (1, quote, 2)
    else:
        assert report["repaired_items"] == []
        extraction_kept = result[1][0].value is not None
        assert extraction_kept is kept
        assert [i["reason"] for i in report["items"]] == ([] if kept else [reason])
        if kept:
            assert result[1][0].quote == quote

    data = ValidationInput(
        statements=(StatementRow(id=1, position=1, text="Afirmación 1.", topic="economy"),),
        positions=(PositionRow(1, 1, 1, 1, 1, quote, page, None),),
        party_ids=(1,),
        documents={
            1: RunDocument(1, MAIN, None, {n: t for n, t in enumerate(pages, start=1)})
        },
    )
    assert (check_evidence_quotes(data) == []) is kept
    if reason == "other_page":
        # The repaired Evidence (the page extraction stores) passes Validation.
        repaired = dataclasses.replace(
            data, positions=(PositionRow(1, 1, 1, 1, 1, quote, 2, None),)
        )
        assert check_evidence_quotes(repaired) == []


# e2e-real-2026-election: Statement batches in position_findings


def test_statement_batches_split_the_pool_in_consecutive_batches_of_20() -> None:
    assert positions_module.FINDINGS_STATEMENTS_PER_CALL == 20
    batches = positions_module.statement_batches
    assert [list(b) for b in batches(58)] == [
        list(range(1, 21)),
        list(range(21, 41)),
        list(range(41, 59)),
    ]
    assert [list(b) for b in batches(20)] == [list(range(1, 21))]
    assert [list(b) for b in batches(21)] == [list(range(1, 21)), [21]]
    assert batches(0) == []


def test_each_findings_request_lists_only_its_batch_with_global_numbers() -> None:
    pool = [f"Afirmación {n} del conjunto." for n in range(1, 46)]
    fake = provider()
    extract(fake, [doc(1, 1, "Uno.")], statements=pool)

    findings = [c for c in fake.calls if c.task == "position_findings"]
    reduce = [c for c in fake.calls if c.task == "party_positions"]
    assert len(findings) == 3 and len(reduce) == 1
    for request, numbers in zip(
        findings, (range(1, 21), range(21, 41), range(41, 46)), strict=True
    ):
        listed = "\n".join(f"[{n}] {pool[n - 1]}" for n in numbers)
        assert f"corchetes):\n\n{listed}\n\nFragmento de programa electoral" in request.prompt
        others = set(range(1, 46)) - set(numbers)
        assert all(f"[{n}] " not in request.prompt for n in others)
    # The reduce still lists the whole pool.
    assert "\n".join(f"[{n}] {t}" for n, t in enumerate(pool, start=1)) in reduce[0].prompt


def test_a_finding_for_a_statement_outside_its_batch_is_ignored() -> None:
    pool = [f"Afirmación {n}." for n in range(1, 31)]

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        # Every batch answers Statement 25 (in batch 2 only) and Statement 2
        # (in batch 1 only); each must count once, from its own batch.
        return _findings(_finding(statement=2), _finding(statement=25, value=-1))

    fake = provider(position_findings=_respond)
    check = FindingCheck()
    results = extract_positions(fake, pool, [doc(1, 1, "Uno.")], [1], Usage(), check)

    assert check.checked == {1: 2}
    reduce = next(c for c in fake.calls if c.task == "party_positions")
    assert [(c["statement"], c["value"]) for c in candidate_lines(reduce)] == [(2, 1), (25, -1)]
    assert results[1][1].value == 1 and results[1][24].value == -1


def test_plan_position_calls_multiplies_chunks_by_the_batches_of_the_pool() -> None:
    documents = [doc(1, 1, "Uno."), doc(2, 2, "Dos."), doc(2, 3, "Tres.", role=ADDITIONAL)]
    assert plan_position_calls(documents, statement_count=20) == 3 * 1 + 2
    assert plan_position_calls(documents, statement_count=21) == 3 * 2 + 2
    assert plan_position_calls(documents, statement_count=60) == 3 * 3 + 2
    assert plan_position_calls(documents, statement_count=80) == 3 * 4 + 2
    assert plan_position_calls(documents) == plan_position_calls(documents, statement_count=80)
    fake = provider()
    extract(fake, documents, statements=[f"A{n}." for n in range(1, 26)])
    assert len(fake.calls) == plan_position_calls(documents, statement_count=25)
