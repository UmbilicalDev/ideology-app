"""Helpers for pipeline tests: seed parsed documents via the ORM, fake responses."""

import datetime as dt
import re
import socket
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from sqlalchemy import Engine

from ideology_app.db import session_scope
from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.models import (
    Election,
    ElectionStatus,
    ElectionType,
    Party,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentPage,
    SourceDocumentStatus,
)
from ideology_app.pipeline import TOPICS

LLM_ENV_VARS = ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GENERATION_MODE")
CONFIG_ENV_VARS = (*LLM_ENV_VARS, "VALIDATION_MIN_PARTY_COVERAGE_PERCENT")

PARTIES = (("Partido Alfa", "PA"), ("Bloque Beta", "BB"))

# Page text never mentions a Party name or short name.
PAGES = {
    1: ["Propuestas sobre vivienda y alquiler.", "Propuestas sobre sanidad pública."],
    2: ["Medidas fiscales y de empleo.", "Medidas sobre educación y universidades."],
}

# Default finding value per Party, so the default run separates the Parties
# (statement_separation passes): Party 1 agrees, Party 2 disagrees.
PARTY_VALUES = {1: 1, 2: -1}


def offline_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset LLM and Validation settings and block every socket connection."""
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is blocked in pipeline tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def seed_election(engine: Engine, *, with_failed_document: bool = True) -> None:
    """Election 1, Parties 1 and 2, each with one parsed 2-page document.

    Party 2 also has a ``failed`` document (id 3) whose text must never be used.
    """
    with session_scope(engine) as session:
        election = Election(
            id=1,
            country="ES",
            type=ElectionType.GENERAL,
            date=dt.date(2023, 7, 23),
            name="Generales 2023",
            status=ElectionStatus.DRAFT,
        )
        session.add(election)
        for party_id, (name, short) in enumerate(PARTIES, start=1):
            session.add(Party(id=party_id, election_id=1, name=name, short_name=short))
        session.flush()
        for party_id, pages in PAGES.items():
            add_parsed_document(session, party_id=party_id, document_id=party_id, pages=pages)
        if with_failed_document:
            session.add(
                SourceDocument(
                    id=3,
                    party_id=2,
                    origin=SourceDocumentOrigin.UPLOAD,
                    status=SourceDocumentStatus.FAILED,
                    content_hash="f" * 64,
                    failure_reason="no text layer",
                )
            )


def add_parsed_document(
    session: Any,
    *,
    party_id: int,
    document_id: int,
    pages: Sequence[str],
    source_url: str | None = None,
) -> None:
    """A parsed document; with ``source_url`` it is a URL document, else an upload."""
    session.add(
        SourceDocument(
            id=document_id,
            party_id=party_id,
            origin=SourceDocumentOrigin.URL if source_url else SourceDocumentOrigin.UPLOAD,
            status=SourceDocumentStatus.PARSED,
            source_url=source_url,
            content_hash=f"{document_id:064x}",
            page_count=len(pages),
        )
    )
    session.flush()
    for number, text in enumerate(pages, start=1):
        session.add(
            SourceDocumentPage(source_document_id=document_id, page_number=number, text=text)
        )


def candidates_response(count: int = 3) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """``count`` candidates per chunk, the same for every chunk (so some repeat)."""

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        return {
            "candidates": [
                {"text": f"Propuesta candidata número {i}.", "topic": TOPICS[i % len(TOPICS)]}
                for i in range(count)
            ]
        }

    return _respond


def statements_payload(count: int = 30) -> dict[str, Any]:
    return {
        "statements": [
            {"text": f"Afirmación {i + 1}: el Estado debe actuar en el ámbito {i + 1}.",
             "topic": TOPICS[i % len(TOPICS)]}
            for i in range(count)
        ]
    }


_CHUNK_START = "(cada página va precedida de su marcador):\n\n"
_CHUNK_END = "\n\nIndica la posición"
_PAGE = re.compile(r"\[página (\d+)\]\n(.*?)(?=\n\n\[página \d+\]\n|\Z)", re.DOTALL)
_STATEMENTS_START = "(una por línea, con su número entre corchetes):\n\n"
_STATEMENTS_END = "\n\nCitas candidatas"
_STATEMENT = re.compile(r"^\[(\d+)\] ", re.MULTILINE)
_CANDIDATE = re.compile(
    r"^C(\d+) \[(programa principal|programa adicional)\] \[afirmación (\d+)\] "
    r"\[valor (-?\d+)\] \[página (\d+)\] «(.*)»$",
    re.MULTILINE,
)


def chunk_pages(request: LLMRequest[Any]) -> list[tuple[int, str]]:
    """The ``(page, text)`` pages of a ``position_findings`` request's chunk."""
    chunk = request.prompt.split(_CHUNK_START, 1)[1].rsplit(_CHUNK_END, 1)[0]
    return [(int(m.group(1)), m.group(2)) for m in _PAGE.finditer(chunk)]


def candidate_lines(request: LLMRequest[Any]) -> list[dict[str, Any]]:
    """The numbered candidates of a ``party_positions`` request."""
    return [
        {
            "number": int(m.group(1)),
            "label": m.group(2),
            "statement": int(m.group(3)),
            "value": int(m.group(4)),
            "page": int(m.group(5)),
            "quote": m.group(6),
        }
        for m in _CANDIDATE.finditer(request.prompt)
    ]


def statement_numbers(request: LLMRequest[Any]) -> list[int]:
    """The Statement numbers listed in a ``party_positions`` request."""
    listed = request.prompt.split(_STATEMENTS_START, 1)[1].split(_STATEMENTS_END, 1)[0]
    return [int(n) for n in _STATEMENT.findall(listed)]


def _page_value(text: str) -> int:
    """``PARTY_VALUES`` of the Party whose seeded page this is, else 1."""
    for party_id, pages in PAGES.items():
        if text in pages:
            return PARTY_VALUES[party_id]
    return 1


def findings_response(value: int | None = None) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """One finding per page of the chunk: Statement n = page n, quote = page text.

    With ``value`` None each finding takes its Party's ``PARTY_VALUES`` value
    (looked up by page text, so prompts never need a Party name); an explicit
    ``value`` is used for every page.
    """

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "statement": page,
                    "value": _page_value(text) if value is None else value,
                    "quote": text[:500],
                    "page": page,
                }
                for page, text in chunk_pages(request)
            ]
        }

    return _respond


def positions_response(fill: bool = False) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """For each Statement, the value of its first candidate, citing that candidate.

    With ``fill`` every listed Statement gets a stance: one without a candidate
    of its own uses the Party's first candidate (so its quote is still real
    page text on the cited page).
    """

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        candidates = candidate_lines(request)
        chosen: dict[int, dict[str, int]] = {}
        for c in candidates:
            chosen.setdefault(
                c["statement"],
                {"statement": c["statement"], "value": c["value"], "evidence": c["number"]},
            )
        if not fill:
            return {"positions": list(chosen.values())}
        first = candidates[0]
        return {
            "positions": [
                chosen.get(n)
                or {"statement": n, "value": first["value"], "evidence": first["number"]}
                for n in statement_numbers(request)
            ]
        }

    return _respond


def default_responses() -> dict[str, Any]:
    return {
        "statement_candidates": candidates_response(),
        "generate_statements": statements_payload(),
        "position_findings": findings_response(),
        "party_positions": positions_response(fill=True),
    }


def fake_provider(**overrides: Any) -> FakeProvider:
    responses = default_responses()
    responses.update(overrides)
    return FakeProvider(responses)
