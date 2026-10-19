"""Check ``evidence_quotes`` on plain ``ValidationInput`` data (no database).

validation-evidence-quotes Scenarios 3, 4 and 5, and ``normalize_for_match``.
"""

import unicodedata
from collections.abc import Sequence

import pytest
from pipeline_fixtures import offline_guard

from ideology_app.models import SourceDocumentRole
from ideology_app.validation import (
    CHECKS,
    EVIDENCE_QUOTES,
    PositionRow,
    ReportEntry,
    RunDocument,
    StatementRow,
    ValidationInput,
    normalize_for_match,
    quote_starts_on,
    run_checks,
)


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


URL = "https://example.org/programa.pdf"


def document(
    pages: Sequence[str], party_id: int = 1, source_url: str | None = None
) -> RunDocument:
    return RunDocument(
        party_id=party_id,
        role=SourceDocumentRole.MAIN,
        source_url=source_url,
        pages={n: text for n, text in enumerate(pages, start=1)},
    )


def stance(
    quote: str | None,
    page: int | None = 1,
    *,
    document_id: int | None = 1,
    party_id: int = 1,
    statement: int = 1,
    value: int | None = 1,
    url: str | None = None,
) -> PositionRow:
    return PositionRow(
        statement_id=100 + statement,
        statement_position=statement,
        party_id=party_id,
        value=value,
        document_id=document_id,
        quote=quote,
        page=page,
        url=url,
    )


def check(
    positions: Sequence[PositionRow], documents: dict[int, RunDocument]
) -> list[ReportEntry]:
    data = ValidationInput(
        statements=tuple(
            StatementRow(id=100 + n, position=n, text=f"Afirmación {n}.", topic="economy")
            for n in range(1, 4)
        ),
        positions=tuple(positions),
        party_ids=(1, 2),
        documents=documents,
    )
    return EVIDENCE_QUOTES.run(data)


def messages(positions: Sequence[PositionRow], documents: dict[int, RunDocument]) -> list[str]:
    return [e.message for e in check(positions, documents)]


def test_registry_has_evidence_quotes_first() -> None:
    assert [c.name for c in CHECKS][0] == "evidence_quotes"
    assert EVIDENCE_QUOTES.name == "evidence_quotes"


# normalize_for_match


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Educación Pública", "educacionpublica"),
        ("ESPAÑA", "espana"),
        ("universi-\ndad", "universidad"),
        ("a b", "ab"),
        ("in­ter", "inter"),
        ("ﬁnanciación", "financiacion"),
        ("Straße", "strasse"),
        ("  «Texto», con; puntuación!  ", "textoconpuntuacion"),
        ("Artículo 23.4", "articulo234"),
        ("…", ""),
        ("[...]", ""),
    ],
)
def test_normalize_for_match(text: str, expected: str) -> None:
    assert normalize_for_match(text) == expected


def test_normalize_for_match_treats_nfc_and_nfd_alike() -> None:
    nfc = unicodedata.normalize("NFC", "acción pública")
    nfd = unicodedata.normalize("NFD", "acción pública")
    assert nfc != nfd
    assert normalize_for_match(nfc) == normalize_for_match(nfd) == "accionpublica"


def test_quote_starts_on_allows_running_onto_the_next_page() -> None:
    pages = {1: "abc", 2: "defg", 3: "hi"}
    assert quote_starts_on("bcde", pages, 1)
    assert not quote_starts_on("bcde", pages, 2)
    assert quote_starts_on("gh", pages, 2)
    assert quote_starts_on("hi", pages, 3)
    assert quote_starts_on("abcdefg", pages, 1)
    assert not quote_starts_on("abcdefgh", pages, 1)  # would need three pages
    assert not quote_starts_on("xyz", pages, 1)


# Scenario 3: whitespace, accent, case and line-break differences pass

PAGE = "Garantizaremos la educación\npública  y gratuita, también en la universi-\ndad."


@pytest.mark.parametrize(
    "quote",
    [
        "garantizaremos la educacion publica y gratuita",
        "Garantizaremos  la educación pública\ty gratuita",
        "también en la universidad",
        unicodedata.normalize("NFD", "Garantizaremos la educación pública"),
        "la educación pública",
        PAGE,
    ],
    ids=["no-accents-lowercase", "extra-whitespace", "hyphenated-line-break", "nfd", "nbsp",
         "exact"],
)
def test_normalised_quotes_pass(quote: str) -> None:
    assert check([stance(quote)], {1: document([PAGE])}) == []


def test_ligature_on_the_page_matches_plain_letters_in_the_quote() -> None:
    ligature_page = {1: document(["La ﬁnanciación pública."])}
    plain_page = {1: document(["La financiación pública."])}
    assert check([stance("la financiación pública")], ligature_page) == []
    assert check([stance("la ﬁnanciación")], plain_page) == []


def test_normalisation_does_not_change_the_inputs() -> None:
    position = stance("garantizaremos la educacion publica y gratuita")
    documents = {1: document([PAGE])}
    check([position], documents)
    assert position.quote == "garantizaremos la educacion publica y gratuita"
    assert documents[1].pages[1] == PAGE


@pytest.mark.parametrize(
    "quote",
    [
        "Garantizaremos la sanidad pública",
        "pública la educación garantizaremos",
        "Garantizaremos la educación pública y gratuita en 2027",
    ],
    ids=["different-word", "word-order", "extra-digits"],
)
def test_letters_digits_and_order_must_still_match(quote: str) -> None:
    assert messages([stance(quote)], {1: document([PAGE])}) == [
        "quote not found in source document 1"
    ]


# Scenario 4: quote on another page or across a page break

PAGES = ["Primera página.", "Bajaremos el IVA de la luz.", "Al final de la página tres se dice que",
         "habrá más becas para todos.", "Fin."]


def test_quote_on_its_cited_page_passes() -> None:
    assert check([stance("Bajaremos el IVA de la luz.", 2)], {1: document(PAGES)}) == []


def test_quote_on_another_page_fails_and_says_where_it_was_found() -> None:
    assert messages([stance("Bajaremos el IVA de la luz.", 1)], {1: document(PAGES)}) == [
        "quote not found on page 1 of source document 1 (found on page 2)"
    ]


def test_quote_across_a_page_break_must_cite_the_page_where_it_starts() -> None:
    quote = "se dice que habrá más becas"
    assert check([stance(quote, 3)], {1: document(PAGES)}) == []
    assert messages([stance(quote, 4)], {1: document(PAGES)}) == [
        "quote not found on page 4 of source document 1 (found on page 3)"
    ]


def test_quote_on_the_last_page_has_no_next_page() -> None:
    assert check([stance("Fin.", 5)], {1: document(PAGES)}) == []


# Scenario 5: locator integrity


def test_page_beyond_the_document_fails() -> None:
    assert messages([stance("Fin.", 9)], {1: document(PAGES)}) == [
        "page 9 does not exist in source document 1 (5 pages)"
    ]


def test_document_of_another_party_fails() -> None:
    documents = {1: document(PAGES, party_id=1), 2: document(PAGES, party_id=2)}
    assert messages([stance("Fin.", 5, document_id=2, party_id=1)], documents) == [
        "source document 2 is not a source document of party 1 in this run"
    ]


def test_document_not_read_by_the_run_fails() -> None:
    assert messages([stance("Fin.", 5, document_id=7)], {1: document(PAGES)}) == [
        "source document 7 is not a source document of party 1 in this run"
    ]


@pytest.mark.parametrize(
    ("position_url", "document_url"),
    [(None, URL), ("https://example.org/otro.pdf", URL), (URL, None)],
    ids=["missing-url", "other-url", "url-on-upload"],
)
def test_evidence_url_must_match_the_document(
    position_url: str | None, document_url: str | None
) -> None:
    documents = {1: document(PAGES, source_url=document_url)}
    assert messages([stance("Fin.", 5, url=position_url)], documents) == [
        "evidence URL does not match source document 1"
    ]


def test_matching_url_passes() -> None:
    assert check([stance("Fin.", 5, url=URL)], {1: document(PAGES, source_url=URL)}) == []


@pytest.mark.parametrize("quote", ["…", " - ", "[...]"])
def test_quote_without_letters_or_digits_fails(quote: str) -> None:
    assert messages([stance(quote, 1)], {1: document(PAGES)}) == [
        "quote has no letters or digits"
    ]


def test_no_stance_is_never_checked() -> None:
    no_stance = stance(None, None, document_id=None, value=None)
    assert check([no_stance], {}) == []


def test_only_the_first_failing_rule_is_reported() -> None:
    # Wrong party and a page that does not exist: one entry, for the party rule.
    documents = {2: document(PAGES, party_id=2)}
    assert messages([stance("…", 9, document_id=2, party_id=1)], documents) == [
        "source document 2 is not a source document of party 1 in this run"
    ]


def test_each_offending_position_is_one_entry_in_input_order() -> None:
    documents = {1: document(PAGES, party_id=1), 2: document(["Otro texto."], party_id=2)}
    positions = [
        stance("Primera página.", 1, statement=1, party_id=1),
        stance("Inventada.", 1, statement=1, party_id=2, document_id=2),
        stance("Bajaremos el IVA", 1, statement=2, party_id=1, value=-2),
        stance(None, None, statement=2, party_id=2, document_id=None, value=None),
        stance("Otro texto.", 2, statement=3, party_id=2, document_id=2, value=0),
    ]
    assert check(positions, documents) == [
        ReportEntry("quote not found in source document 2", 101, 2),
        ReportEntry("quote not found on page 1 of source document 1 (found on page 2)", 102, 1),
        ReportEntry("page 2 does not exist in source document 2 (1 pages)", 103, 2),
    ]


def test_run_checks_reports_a_failed_evidence_quotes_result() -> None:
    data = ValidationInput(
        statements=(),
        positions=(stance("Inventada.", 1),),
        party_ids=(1,),
        documents={1: document(PAGES)},
    )
    [result] = run_checks(data, (EVIDENCE_QUOTES,))
    assert result.name == "evidence_quotes"
    assert not result.passed
    assert result.entries == (ReportEntry("quote not found in source document 1", 101, 1),)
