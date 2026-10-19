import pytest
from pdf_factory import blank_pdf, encrypt_pdf, make_text_pdf

from ideology_app import pdf_text
from ideology_app.pdf_text import NO_TEXT_LAYER, PdfTextError, extract_pages


def test_text_on_two_pages_with_accents() -> None:
    data = make_text_pdf(
        [
            "Programa electoral\nSubir el salario mínimo por encima de la inflación.",
            "Página dos: educación pública (gratuita).",
        ]
    )

    pages = extract_pages(data)

    assert len(pages) == 2
    assert "salario mínimo" in pages[0]
    assert "inflación" in pages[0]
    assert pages[1] == "Página dos: educación pública (gratuita)."


def test_page_without_text_keeps_its_slot() -> None:
    pages = extract_pages(make_text_pdf(["uno", None, "tres"]))

    assert pages == ["uno", "", "tres"]


@pytest.mark.parametrize(
    "data, page_count",
    [(make_text_pdf([None, None]), 2), (blank_pdf(), 1)],
    ids=["shapes-only", "add-blank-page"],
)
def test_no_text_layer(data: bytes, page_count: int) -> None:
    with pytest.raises(PdfTextError) as info:
        extract_pages(data)

    assert info.value.reason == NO_TEXT_LAYER
    assert info.value.page_count == page_count


def test_no_pages() -> None:
    with pytest.raises(PdfTextError) as info:
        extract_pages(make_text_pdf([]))

    assert info.value.reason == "PDF has no pages"
    assert info.value.page_count == 0


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.4\nthis is not really a pdf",
        make_text_pdf(["hola", "adiós"])[:400],
        b"",
    ],
    ids=["garbage", "truncated", "empty"],
)
def test_unreadable_pdf(data: bytes) -> None:
    with pytest.raises(PdfTextError) as info:
        extract_pages(data)

    assert info.value.reason.startswith("could not read PDF: ")
    assert len(info.value.reason) <= 500


def test_long_read_error_is_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_stream: object) -> None:
        raise ValueError("x" * 2000)

    monkeypatch.setattr(pdf_text, "PdfReader", boom)

    with pytest.raises(PdfTextError) as info:
        extract_pages(b"%PDF-")

    assert info.value.reason.startswith("could not read PDF: ValueError: xxx")
    assert len(info.value.reason) == 500


def test_password_encrypted_pdf() -> None:
    data = encrypt_pdf(make_text_pdf(["secreto"]), "secret")

    with pytest.raises(PdfTextError) as info:
        extract_pages(data)

    assert info.value.reason == "PDF is encrypted"


def test_empty_password_pdf_is_read() -> None:
    data = encrypt_pdf(make_text_pdf(["abierto"]), "")

    assert extract_pages(data) == ["abierto"]


def test_nul_characters_are_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    from pypdf import PageObject

    monkeypatch.setattr(PageObject, "extract_text", lambda self, *a, **k: "a\x00b\x00")

    assert extract_pages(make_text_pdf(["ignored"])) == ["ab"]
