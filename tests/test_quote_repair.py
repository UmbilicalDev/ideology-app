"""Quote repair (e2e-real-2026-election): slipped copies get the source's own words.

The cases come from run 4 of the 2026 Election, where these slips cleared
stances: a one-letter typo across a PDF line-break hyphen, a dropped phrase,
and a verbatim quote cited one page off.
"""

import pytest

from ideology_app.pipeline.quote_repair import (
    PAGE_CORRECTED,
    QUOTE_SNAPPED,
    Repair,
    repair_finding,
)
from ideology_app.validation.evidence_quotes import (
    NOT_FOUND,
    OTHER_PAGE,
    NO_LETTERS,
    find_quote_miss,
    normalize_for_match,
    normalize_pages,
    normalize_with_offsets,
)

PAGE_TYPO = (
    "Energía.\n"
    "Se garantizará la supervivencia de las centrales nu -\n"
    "cleares actuales, derogando el calendario de cierre. \n"
    "Se promoverán estudios urgentes para instalar cen -\n"
    "trales nucleares en los emplazamientos disponibles."
)
PAGE_DROPPED = (
    "125 MAYOR CAPACIDAD Y MEJORES ACCESOS PARA LOS AE -\n"
    "ROPUERTOS. Resolveremos los puntos de saturación y ejecutaremos \n"
    "las\tampliaciones\tque\tjustifiquen\tla\tdemanda\tprevista\ty\tlas\tnecesidades\t\n"
    "de conectividad territorial."
)
OTHER = "Otra página sin relación: sanidad pública, educación y cultura para todos."


def _verified(repair: Repair, pages: dict[int, str]) -> bool:
    return find_quote_miss(repair.quote, normalize_pages(pages.items()), repair.page) is None


def test_offsets_give_the_same_string_as_the_matcher() -> None:
    text = "FInanciación «pública» — Ǆ ½ ñandú x­-y İstanbul ß"
    norm, offsets = normalize_with_offsets(text)
    assert norm == normalize_for_match(text)
    assert len(offsets) == len(norm)
    assert offsets == sorted(offsets)


def test_one_letter_typo_is_snapped_to_the_source_text() -> None:
    pages = {11: OTHER, 12: PAGE_TYPO}
    quote = "Se garantizará la supervivencia de las centrales nu - clearas actuales, derogando el calendario de cierre."
    assert find_quote_miss(quote, normalize_pages(pages.items()), 12).reason == NOT_FOUND
    repair = repair_finding(quote, 12, NOT_FOUND, None, (11, 12), pages)
    assert repair is not None
    assert repair.kind == QUOTE_SNAPPED and repair.page == 12
    assert repair.quote.startswith("Se garantizará la supervivencia de las centrales nu - cleares")
    assert "\n" not in repair.quote and "  " not in repair.quote
    assert _verified(repair, pages)


def test_dropped_phrase_is_snapped_to_the_full_source_sentence() -> None:
    pages = {46: PAGE_DROPPED}
    quote = "Resolveremos los puntos de saturación y ejecutaremos las ajustifiquen la demanda prevista"
    repair = repair_finding(quote, 46, NOT_FOUND, None, (46,), pages)
    assert repair == Repair(
        QUOTE_SNAPPED,
        46,
        "Resolveremos los puntos de saturación y ejecutaremos las ampliaciones que "
        "justifiquen la demanda prevista",
    )
    assert _verified(repair, pages)


def test_snap_looks_at_the_other_pages_of_the_chunk() -> None:
    pages = {11: PAGE_TYPO, 12: OTHER}
    quote = "Se garantizará la supervivencia de las centrales nu - clearas actuales"
    repair = repair_finding(quote, 12, NOT_FOUND, None, (11, 12), pages)
    assert repair is not None and repair.page == 11 and _verified(repair, pages)


def test_snap_never_leaves_the_chunk() -> None:
    pages = {11: PAGE_TYPO, 12: OTHER}
    quote = "Se garantizará la supervivencia de las centrales nu - clearas actuales"
    assert repair_finding(quote, 12, NOT_FOUND, None, (12,), pages) is None


@pytest.mark.parametrize(
    "quote",
    [
        # Invented: the opposite stance in other words.
        "Se cerrarán todas las centrales nucleares actuales según el calendario previsto.",
        # A paraphrase of the right stance is not a copy either.
        "Garantizaremos que las centrales nucleares sigan funcionando y anularemos el plan de cierre.",
        # Too short to snap safely (under SNAP_MIN_CHARS letters).
        "centrales nu - clearas actuales",
    ],
)
def test_invented_paraphrased_or_short_quotes_are_not_snapped(quote: str) -> None:
    pages = {12: PAGE_TYPO}
    assert repair_finding(quote, 12, NOT_FOUND, None, (12,), pages) is None


def test_verbatim_quote_on_another_chunk_page_gets_that_page() -> None:
    pages = {100: "desalojo de viviendas ocupadas en 48 horas", 101: OTHER}
    quote = "desalojo de viviendas ocupadas en 48 horas"
    miss = find_quote_miss(quote, normalize_pages(pages.items()), 101)
    assert (miss.reason, miss.found_on) == (OTHER_PAGE, 100)
    repair = repair_finding(quote, 101, OTHER_PAGE, 100, (100, 101), pages)
    assert repair == Repair(PAGE_CORRECTED, 100, quote)
    assert _verified(repair, pages)


def test_other_page_outside_the_chunk_is_not_corrected() -> None:
    pages = {100: "desalojo de viviendas ocupadas en 48 horas", 101: OTHER}
    assert repair_finding("desalojo de viviendas ocupadas", 101, OTHER_PAGE, 100, (101,), pages) is None


def test_no_letters_is_never_repaired() -> None:
    assert repair_finding("…", 1, NO_LETTERS, None, (1,), {1: OTHER}) is None
