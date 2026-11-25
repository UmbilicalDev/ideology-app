"""Pure chunking and the Proposal check (proposal-extraction, P1, P2, P5; scenarios 2-3)."""

import pytest
from proposal_fixtures import FILLER, big_page, big_pages, item, measure

from ideology_app.proposals.extraction import (
    CHECK_VERSION,
    DROP_REASONS,
    PROPOSAL_CHUNK_MAX_CHARS,
    Chunk,
    build_chunks,
    check_items,
)
from ideology_app.proposals.prompts import proposal_list_schema


def _outputs(chunks: list[Chunk], items_per_chunk: list[list[dict[str, object]]]):
    return [
        proposal_list_schema(chunk.first_page, chunk.last_page).model_validate(
            {"proposals": items}
        )
        for chunk, items in zip(chunks, items_per_chunk, strict=True)
    ]


# --- build_chunks -------------------------------------------------------------------


def test_constants() -> None:
    assert PROPOSAL_CHUNK_MAX_CHARS == 12_000
    assert CHECK_VERSION == "v1"
    assert DROP_REASONS == ("not_found", "other_page", "context_page", "duplicate", "no_letters")


def test_small_document_is_one_chunk_without_context() -> None:
    chunks = build_chunks(["Uno.", "", "  \n", "Cuatro."])

    assert chunks == [Chunk(0, (1, 4), None, "[página 1]\nUno.\n\n[página 4]\nCuatro.")]
    assert (chunks[0].first_page, chunks[0].last_page) == (1, 4)


def test_every_chunk_but_the_last_gets_the_next_page_as_context() -> None:
    pages = big_pages(3)
    chunks = build_chunks(pages)

    assert [(c.index, c.pages, c.context_page) for c in chunks] == [
        (0, (1,), 2),
        (1, (2,), 3),
        (2, (3,), None),
    ]
    assert chunks[0].text == (
        f"[página 1]\n{pages[0]}\n\n[página 2 — solo contexto]\n{pages[1]}"
    )
    assert chunks[0].last_page == 2 and chunks[2].last_page == 3


def test_the_limit_counts_markers_and_separators_and_never_slices_a_page() -> None:
    marker = len("[página 1]\n")
    page = "x" * (100 - marker)  # 100 characters with its marker
    # 3 pages and 2 separators: 304 characters.
    assert [c.pages for c in build_chunks([page] * 3, max_chars=304)] == [(1, 2, 3)]
    assert [c.pages for c in build_chunks([page] * 3, max_chars=303)] == [(1, 2), (3,)]
    huge = "y" * 500
    chunks = build_chunks([page, huge, page], max_chars=150)
    assert [(c.pages, c.context_page) for c in chunks] == [((1,), 2), ((2,), 3), ((3,), None)]
    assert huge in chunks[1].text  # a page over the limit is a chunk alone, whole


def test_blank_pages_are_skipped_and_never_context() -> None:
    marker = len("[página 1]\n")
    page = "z" * (100 - marker)
    chunks = build_chunks([page, "   ", page, "", page], max_chars=100)

    assert [(c.pages, c.context_page) for c in chunks] == [((1,), 3), ((3,), 5), ((5,), None)]


def test_no_text_gives_no_chunks() -> None:
    assert build_chunks([]) == []
    assert build_chunks(["", " \n "]) == []


def test_real_size_pages_make_one_chunk_each() -> None:
    assert 6_000 < len(big_page(1)) < 12_000 - 20
    assert len(build_chunks(big_pages(5))) == 5


# --- check_items ------------------------------------------------------------------


def test_scenario_2_every_drop_reason_is_counted_and_excluded() -> None:
    pages = big_pages(3)
    chunks = build_chunks(pages)
    kept_text = measure(1, 1)
    outputs = _outputs(
        chunks,
        [
            [
                item(kept_text, 1),
                item("Una medida inventada que no aparece en el programa.", 1),
                item(measure(3, 2), 1),  # starts on page 3
                item(measure(2, 1), 2),  # the context page
                item(kept_text.upper(), 1, ("economy",)),  # same normalised text
                item("— · —", 1),
            ],
            [item(measure(2, 1), 2)],
            [item(measure(3, 1), 3, ("housing", "economy"), ())],
        ],
    )

    result = check_items(chunks, outputs, pages)

    assert [(p.ordinal, p.chunk_index, p.page, p.text) for p in result.kept] == [
        (1, 0, 1, kept_text),
        (2, 1, 2, measure(2, 1)),
        (3, 2, 3, measure(3, 1)),
    ]
    assert result.kept[2].categories == ("housing", "economy") and result.kept[2].tags == ()
    assert result.counts() == {
        "not_found": 1,
        "other_page": 1,
        "context_page": 1,
        "duplicate": 1,
        "no_letters": 1,
    }
    assert result.returned == 8
    report = result.report()
    assert report["kept"] == 3 and report["check_version"] == "v1"
    assert report["dropped"][1] == {
        "chunk": 0,
        "page": 1,
        "reason": "other_page",
        "found_on": 3,
        "text": measure(3, 2),
    }
    assert [d["reason"] for d in report["dropped"]] == [
        "not_found",
        "other_page",
        "context_page",
        "duplicate",
        "no_letters",
    ]


def test_scenario_3_a_proposal_running_onto_the_context_page_is_kept() -> None:
    end = "Proponemos ampliar el parque público"
    start = "de vivienda en alquiler social durante la legislatura."
    pages = [FILLER + " " + FILLER[:2000] + " " + end, start + " " + FILLER]
    chunks = build_chunks(pages)
    assert [(c.pages, c.context_page) for c in chunks] == [((1,), 2), ((2,), None)]
    text = f"{end}\n{start}"

    result = check_items(chunks, _outputs(chunks, [[item(text, 1)], []]), pages)

    assert [(p.page, p.text) for p in result.kept] == [(1, text)]
    assert result.dropped == ()


def test_text_and_fields_are_stored_exactly_as_returned() -> None:
    pages = ["Bajaremos  el IVA  de la luz al 5 %."]
    chunks = build_chunks(pages)
    returned = "bajaremos el iva de la luz al 5%"
    result = check_items(
        chunks, _outputs(chunks, [[item(returned, 1, ("economy", "taxation"), ("iva", "luz"))]]), pages
    )

    assert result.kept[0].text == returned
    assert result.kept[0].categories == ("economy", "taxation")
    assert result.kept[0].tags == ("iva", "luz")


def test_a_text_over_more_than_two_pages_fails() -> None:
    pages = ["Uno dos", "tres cuatro", "cinco seis"]
    chunks = build_chunks(pages)
    result = check_items(
        chunks, _outputs(chunks, [[item("dos tres cuatro cinco", 1)]]), pages
    )

    assert result.kept == () and result.dropped[0].reason == "not_found"


def test_chunks_and_outputs_must_match() -> None:
    chunks = build_chunks(["Uno."])
    with pytest.raises(ValueError, match="1 chunks but 0 outputs"):
        check_items(chunks, [], ["Uno."])
