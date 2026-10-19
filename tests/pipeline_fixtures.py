"""Helpers for pipeline tests: seed parsed documents via the ORM, fake responses."""

import datetime as dt
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

PARTIES = (("Partido Alfa", "PA"), ("Bloque Beta", "BB"))

# Page text never mentions a Party name or short name.
PAGES = {
    1: ["Propuestas sobre vivienda y alquiler.", "Propuestas sobre sanidad pública."],
    2: ["Medidas fiscales y de empleo.", "Medidas sobre educación y universidades."],
}


def offline_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset LLM settings and block every socket connection."""
    for name in LLM_ENV_VARS:
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
    session: Any, *, party_id: int, document_id: int, pages: Sequence[str]
) -> None:
    session.add(
        SourceDocument(
            id=document_id,
            party_id=party_id,
            origin=SourceDocumentOrigin.UPLOAD,
            status=SourceDocumentStatus.PARSED,
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


def fake_provider(**overrides: Any) -> FakeProvider:
    responses: dict[str, Any] = {
        "statement_candidates": candidates_response(),
        "generate_statements": statements_payload(),
    }
    responses.update(overrides)
    return FakeProvider(responses)
