"""Shared helpers for the proposal-extraction tests (fake provider only, bundles in tmp_path).

A big page holds ``measures`` short verbatim measures followed by filler, and
is long enough (about 7,300 characters) that every chunk holds one page: a
document of n big pages gives n chunks, each but the last with the next page
as context. ``responder`` answers like a perfect model: every measure of each
real page in the prompt (never the context page).
"""

import datetime as dt
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from bundle_factory import CandidatureSpec, DocumentSpec, manifest_v2_text, write_bundle_v2
from sqlalchemy import Engine

from ideology_app import bundle_import
from ideology_app import ingestion_ledger as ledgers
from ideology_app.db import session_scope
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.source_bundle import read_bundle

TASK = "proposal_extraction"
FILLER = " ".join(["Texto de contexto del programa electoral sin medidas concretas."] * 110)
PAGE_RE = re.compile(r"^\[página (\d+)\]$", re.MULTILINE)

PARTY_A = CandidatureSpec("A", "Partido A", "all")
PARTY_B = CandidatureSpec("B", "Partido B", ["28"])
SLUG_2027 = "es-general-2027-05-30"


def measure(page: int, k: int) -> str:
    return f"Medida {k} de la página {page}: se propone la acción {k} en la página {page}."


def big_page(page: int, measures: int = 4) -> str:
    return " ".join(measure(page, k) for k in range(1, measures + 1)) + " " + FILLER


def big_pages(count: int, measures: int = 4) -> list[str]:
    return [big_page(page, measures) for page in range(1, count + 1)]


def small_page(page: int, measures: int) -> str:
    return " ".join(measure(page, k) for k in range(1, measures + 1))


def item(text: str, page: int, categories: Sequence[str] = ("housing",), tags: Sequence[str] = ("vivienda",)) -> dict[str, Any]:
    return {"text": text, "page": page, "categories": list(categories), "tags": list(tags)}


def pages_in(request: LLMRequest[Any]) -> list[int]:
    """The real pages of a request (``[página N]`` markers, not the context page)."""
    return [int(number) for number in PAGE_RE.findall(request.prompt)]


def responder(
    measures: int = 4, fail_on_page: int | None = None
) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        pages = pages_in(request)
        if fail_on_page is not None and fail_on_page in pages:
            raise LLMProviderError("provider overloaded (529)")
        return {
            "proposals": [
                item(measure(page, k), page) for page in pages for k in range(1, measures + 1)
            ]
        }

    return respond


def fake(measures: int = 4, *, fail_on_page: int | None = None, model: str = "fake-model") -> FakeProvider:
    return FakeProvider({TASK: responder(measures, fail_on_page)}, model=model)


def called_pages(provider: FakeProvider) -> list[list[int]]:
    return [pages_in(request) for request in provider.calls]


def write_v2(
    root: Path,
    parties: Sequence[CandidatureSpec],
    documents: Sequence[DocumentSpec],
    *,
    slug: str | None = None,
    date: dt.date | None = None,
) -> Path:
    elections = root / "data" / "elections"
    if slug is None:
        return write_bundle_v2(elections, parties, documents)
    assert date is not None
    manifest = manifest_v2_text(parties, documents, date=date, name=f"Elecciones {date.year}")
    return write_bundle_v2(elections, parties, documents, slug=slug, manifest=manifest)


def import_dir(engine: Engine, directory: Path) -> None:
    with session_scope(engine) as session:
        bundle_import.import_bundle(session, read_bundle(directory))


def keep_all(directory: Path, *, min_proposals: int | None = None) -> None:
    """Create or update the ledger and review every listed document ``kept``."""
    ledgers.update_in_dir(directory, min_proposals=min_proposals)
    for document in read_bundle(directory).documents:
        ledgers.review_in_dir(directory, document.file, decision=ledgers.ReviewDecision.KEPT)


def ledger_count(directory: Path, file: str) -> int | None:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return ledger.document(file).proposals


def party_labels(directory: Path) -> dict[str, str]:
    ledger = ledgers.read_ledger(directory)
    assert ledger is not None
    return {p.short_name: ledgers.state_label(p, ledger.min_proposals) for p in ledger.parties}
