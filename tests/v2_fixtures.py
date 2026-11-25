"""Shared helpers for the statements-from-proposals tests (FakeProvider only, tmp_path bundles).

Election (format 2) with three Parties:

- ``P`` runs in 28 and 31 and lists ``a.md`` (all its Constituencies, 3
  Proposals) and ``b.md`` (28 only, 2 Proposals): one overlap in 28, and a
  partial scope (``b.md`` counts only in 28).
- ``R`` runs in 28 and lists ``r.md`` (3 Proposals).
- ``X`` runs in 28 and lists nothing; it is Excluded (``no_manifesto``).

Every document has one page holding its measures; extraction returns each
measure with the categories and tags of ``MEASURES``. The two categories are
``housing`` (Vivienda) and ``economy`` (Economía). The v2 fake provider
(``v2_fake``) drafts one Statement per ``STATEMENTS`` entry whose category is
the request's, citing every listed Proposal, and positions a Party with the
``STANCES`` of the Proposals it lists. Its ``statement_rewording_check``
(statement-rewording) answers equivalent unless the new wording contains
``REJECT_MARKER`` (``CAMBIO``).
"""

import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from bundle_factory import CandidatureSpec, DocumentSpec
from conflict_fixtures import conflict_fake
from proposal_fixtures import import_dir, keep_all, write_v2
from sqlalchemy import Engine

from ideology_app import ingestion_ledger as ledgers
from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.pipeline.v2.gate import Phase4Party, PhaseProposal
from ideology_app.proposals import conflicts, store

P = CandidatureSpec("P", "Partido P", ["28", "31"])
R = CandidatureSpec("R", "Partido R", ["28"])
X = CandidatureSpec("X", "Partido X", ["28"])

HOUSING = ("housing",)
ECONOMY = ("economy",)

# file -> [(text, categories, tags)]
MEASURES: dict[str, list[tuple[str, tuple[str, ...], tuple[str, ...]]]] = {
    "a.md": [
        ("Bajar el precio del alquiler en todo el país.", HOUSING, ("alquiler",)),
        ("Subir el salario mínimo cada año.", ECONOMY, ("salarios",)),
        ("Construir más vivienda pública en alquiler.", HOUSING, ("vivienda pública",)),
    ],
    "b.md": [
        ("Congelar el alquiler en la provincia.", HOUSING, ("alquiler",)),
        ("Crear un banco público regional.", ECONOMY, ()),
    ],
    "r.md": [
        ("Liberalizar el suelo para construir más viviendas.", HOUSING, ("suelo",)),
        ("Rebajar el impuesto de sociedades.", ECONOMY, ("impuestos",)),
        ("Eliminar el impuesto de patrimonio.", ECONOMY, ("impuestos",)),
    ],
}

# Proposal text -> value it gives on the Statement of its main category.
STANCES: dict[str, int] = {
    "Bajar el precio del alquiler en todo el país.": 2,
    "Construir más vivienda pública en alquiler.": 1,
    "Congelar el alquiler en la provincia.": 2,
    "Liberalizar el suelo para construir más viviendas.": -1,
    "Subir el salario mínimo cada año.": -1,
    "Crear un banco público regional.": -2,
    "Rebajar el impuesto de sociedades.": 2,
    "Eliminar el impuesto de patrimonio.": 1,
}

NOTE = "Una nota de contexto que describe la medida y su alcance general en España."

# category name (prompt) -> Statement texts drafted for it, in order.
STATEMENTS: dict[str, list[str]] = {
    "Vivienda": ["Debe limitarse el precio del alquiler de vivienda."],
    "Economía": ["Deben bajarse los impuestos a las empresas."],
}

PARTY_NAMES = ("Partido P", "Partido R", "Partido X", "a.md", "b.md", "r.md", "P:", "R:")


def page(file: str) -> str:
    return " ".join(text for text, _, _ in MEASURES[file])


def documents() -> list[DocumentSpec]:
    return [
        DocumentSpec("a.md", "P", [page("a.md")], ["P"]),
        DocumentSpec("b.md", "P", [page("b.md")], ["P"], ["28"]),
        DocumentSpec("r.md", "R", [page("r.md")], ["R"]),
    ]


def extraction_fake() -> FakeProvider:
    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        items = []
        for measures in MEASURES.values():
            for text, categories, tags in measures:
                if text in request.prompt:
                    items.append(
                        {"text": text, "page": 1, "categories": list(categories), "tags": list(tags)}
                    )
        return {"proposals": items}

    return FakeProvider({"proposal_extraction": respond})


def setup(
    root: Path,
    engine: Engine,
    *,
    contradictions: Sequence[dict[str, Any]] = (),
    decide: tuple[str, str] | None = None,
    parties: Sequence[CandidatureSpec] = (P, R, X),
    detect: bool = True,
    exclude_x: bool = True,
) -> Path:
    """Write, import, keep, extract, exclude X, detect conflicts (and decide)."""
    directory = write_v2(root, parties, documents())
    import_dir(engine, directory)
    keep_all(directory, min_proposals=1)
    provider = extraction_fake()
    plan = store.prepare_extraction(engine, directory, provider)
    summary = store.execute_plan(engine, provider, plan)
    assert summary.error is None and not summary.failed and not summary.stopped
    if exclude_x and any(p.short_name == "X" for p in parties):
        ledgers.no_manifesto_in_dir(directory, "X")
    if detect:
        conflicts.detect(engine, directory, conflict_fake(contradictions))
    if decide is not None:
        ledgers.decide_conflict_in_dir(
            directory, "P", prevails=decide[0], over=decide[1], reason="Decidido."
        )
    return directory


_PROPOSAL_RE = re.compile(r"^P(\d+)\. (?:\[[^\]]*\] )?(.*)$", re.MULTILINE)
_STATEMENT_RE = re.compile(r"^\[(\d+)\] (.*)$", re.MULTILINE)
_PREVIOUS_RE = re.compile(r"^S(\d+)\. (.*)$", re.MULTILINE)


def category_of(request: LLMRequest[Any]) -> str:
    return request.prompt.splitlines()[0].removeprefix("Tema: ")


def listed_proposals(request: LLMRequest[Any]) -> list[str]:
    return [text for _, text in _PROPOSAL_RE.findall(request.prompt)]


def listed_statements(request: LLMRequest[Any]) -> list[str]:
    return [text for _, text in _STATEMENT_RE.findall(request.prompt)]


def listed_previous(request: LLMRequest[Any]) -> list[str]:
    return [text for _, text in _PREVIOUS_RE.findall(request.prompt)]


def drafts_responder(
    statements: Mapping[str, Sequence[str]] = STATEMENTS, note: str = NOTE
) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """New Statements for the category not yet listed, citing every listed Proposal;
    a Statement already listed (``S<k>``) gets every listed Proposal as an addition."""

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        numbers = list(range(1, len(listed_proposals(request)) + 1))
        previous = listed_previous(request)
        texts = [t for t in statements.get(category_of(request), []) if t not in previous]
        return {
            "statements": [{"text": t, "context_note": note, "sources": numbers} for t in texts],
            "additions": [{"statement": k, "sources": numbers} for k in range(1, len(previous) + 1)],
        }

    return respond


def positions_responder(
    stances: Mapping[str, int] = STANCES,
) -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """Every listed Statement gets the value of the first listed Proposal with a stance,
    citing every listed Proposal with a stance; no stance when none has one."""

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        proposals = listed_proposals(request)
        cited = [k for k, text in enumerate(proposals, start=1) if text in stances]
        if not cited:
            return {"positions": []}
        value = stances[proposals[cited[0] - 1]]
        return {
            "positions": [
                {"statement": k, "value": value, "evidence": cited[:5]}
                for k in range(1, len(listed_statements(request)) + 1)
            ]
        }

    return respond


REJECT_MARKER = "CAMBIO"
_NEW_TEXT_RE = re.compile(r"Nueva redacción:\n\n(.*)\n\n", re.DOTALL)


def rewording_new_text(request: LLMRequest[Any]) -> str:
    match = _NEW_TEXT_RE.search(request.prompt)
    assert match is not None, request.prompt
    return match.group(1)


def rewording_responder() -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """Equivalent unless the new wording contains ``REJECT_MARKER``."""

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        if REJECT_MARKER in rewording_new_text(request):
            return {"equivalent": False, "explanation": "La nueva redacción cambia la medida."}
        return {"equivalent": True, "explanation": "Misma medida con palabras más sencillas."}

    return respond


def v2_fake(
    *,
    drafts: Callable[[LLMRequest[Any]], dict[str, Any]] | None = None,
    positions: Callable[[LLMRequest[Any]], dict[str, Any]] | None = None,
    rewordings: Callable[[LLMRequest[Any]], dict[str, Any]] | None = None,
    fail_on_call: int | None = None,
    model: str = "fake-model",
) -> FakeProvider:
    """The v2 fake provider; with ``fail_on_call`` the n-th call (1-based) raises."""
    provider: FakeProvider
    draft_fn = drafts or drafts_responder()
    position_fn = positions or positions_responder()
    rewording_fn = rewordings or rewording_responder()

    def wrap(fn: Callable[[LLMRequest[Any]], dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        def respond(request: LLMRequest[Any]) -> dict[str, Any]:
            if fail_on_call is not None and len(provider.calls) == fail_on_call:
                raise LLMProviderError("provider overloaded (529)")
            return fn(request)

        return respond

    provider = FakeProvider(
        {
            "statement_drafts": wrap(draft_fn),
            "proposal_positions": wrap(position_fn),
            "statement_rewording_check": wrap(rewording_fn),
        },
        model=model,
    )
    return provider


# --- Plain data for pure tests ------------------------------------------------------


def phase_proposal(
    proposal_id: int,
    text: str,
    categories: Sequence[str] = HOUSING,
    tags: Sequence[str] = (),
    *,
    document: int = 1,
    content_hash: str = "h1",
    ordinal: int | None = None,
    constituencies: Sequence[str] = ("28",),
    page: int = 1,
) -> PhaseProposal:
    return PhaseProposal(
        proposal_id=proposal_id,
        content_hash=content_hash,
        ordinal=proposal_id if ordinal is None else ordinal,
        page=page,
        text=text,
        categories=tuple(categories),
        tags=tuple(tags),
        file=f"doc{document}.md",
        source_document_id=document,
        source_url=None,
        constituencies=tuple(constituencies),
    )


def phase_party(party_id: int, *proposals: PhaseProposal) -> Phase4Party:
    return Phase4Party(party_id=party_id, short_name=f"S{party_id}", proposals=tuple(proposals))


# --- v2-run-inspection: a run with a filtered draft, a slice disagreement and no stances ---

# Economía also drafts the Vivienda Statement again: the copy is filtered as a duplicate.
INSPECTION_STATEMENTS: dict[str, list[str]] = {
    "Vivienda": ["Debe limitarse el precio del alquiler de vivienda."],
    "Economía": [
        "Deben bajarse los impuestos a las empresas.",
        "Debe limitarse el precio del alquiler de vivienda.",
    ],
}
# P's "vivienda pública" Proposal takes the other side (a slice disagreement once each
# Proposal is its own slice); R's housing Proposal takes none (R has no stance).
INSPECTION_STANCES: dict[str, int] = {
    **{k: v for k, v in STANCES.items() if not k.startswith("Liberalizar")},
    "Construir más vivienda pública en alquiler.": -1,
}


def one_proposal_slices(
    proposals: Sequence[PhaseProposal], max_chars: int = 0
) -> list[list[PhaseProposal]]:
    """``positions.position_slices`` with one Proposal per slice (monkeypatched in)."""
    return [[p] for p in proposals]


def inspection_fake() -> FakeProvider:
    """``v2_fake`` drafting ``INSPECTION_STATEMENTS`` and positioning with
    ``INSPECTION_STANCES``; use with ``one_proposal_slices`` patched in."""
    return v2_fake(
        drafts=drafts_responder(INSPECTION_STATEMENTS),
        positions=positions_responder(INSPECTION_STANCES),
    )
