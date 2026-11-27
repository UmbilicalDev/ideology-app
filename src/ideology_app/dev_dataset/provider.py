"""The scripted dev provider (dev-dataset, D2).

A ``FakeProvider`` (name ``fake``, model ``dev-dataset-1``) with one responder
per task. Each responder reads the texts in the prompt (after ``one_line``)
and answers from ``content``; none uses prompt order or Party identity. It is
never registered in ``llm.PROVIDERS``, so ``LLM_PROVIDER`` cannot select it.
"""

import re
from typing import Any

from ideology_app.dev_dataset import content
from ideology_app.llm import FakeProvider, LLMOutputError, LLMRequest
from ideology_app.pipeline.v2.prompts import CATEGORY_NAMES
from ideology_app.proposals.conflict_prompts import one_line

MODEL = "dev-dataset-1"

_REAL_PAGE_RE = re.compile(r"^\[página (\d+)\]$")
_CONTEXT_PAGE_RE = re.compile(r"^\[página \d+ — solo contexto\]$")
_CATEGORY_RE = re.compile(r"^Tema: (.*)$", re.MULTILINE)
_PROPOSAL_RE = re.compile(r"^P(\d+)\. (?:\[[^\]]*\] )?(.*)$", re.MULTILINE)
_STATEMENT_RE = re.compile(r"^\[(\d+)\] (.*)$", re.MULTILINE)
_PREVIOUS_RE = re.compile(r"^S(\d+)\. (.*)$", re.MULTILINE)
_LIST_A_RE = re.compile(r"^A(\d+)\. (.*)$", re.MULTILINE)
_LIST_B_RE = re.compile(r"^B(\d+)\. (.*)$", re.MULTILINE)
_NEW_TEXT_RE = re.compile(r"Nueva redacción:\n\n(.*)\n\n", re.DOTALL)

_CATEGORY_KEYS = {name: key for key, name in CATEGORY_NAMES.items()}
_MEASURES = {one_line(text): measure for text, measure in content.MEASURES_BY_TEXT.items()}
_STATEMENTS = {one_line(s.text): s for s in content.STATEMENTS}


def _category(request: LLMRequest[Any]) -> str:
    match = _CATEGORY_RE.search(request.prompt)
    if match is None or match.group(1) not in _CATEGORY_KEYS:
        raise LLMOutputError("dev provider: no known category in the prompt")
    return _CATEGORY_KEYS[match.group(1)]


def _stance(text: str, statement: str) -> int | None:
    measure = _MEASURES.get(text)
    if measure is None:
        return None
    return dict(measure.stances).get(statement)


def page_sections(prompt: str) -> list[tuple[int, str]]:
    """``(page, text)`` of every real ``[página N]`` section; context pages are skipped."""
    sections: list[tuple[int, list[str]]] = []
    current: list[str] | None = None
    for line in prompt.split("\n"):
        real = _REAL_PAGE_RE.match(line)
        if real is not None:
            current = []
            sections.append((int(real.group(1)), current))
        elif _CONTEXT_PAGE_RE.match(line):
            current = None
        elif current is not None:
            current.append(line)
    return [(page, "\n".join(lines)) for page, lines in sections]


def extraction(request: LLMRequest[Any]) -> dict[str, Any]:
    """Every content measure on a real page of the chunk, in page then text order."""
    items: list[dict[str, Any]] = []
    for page, text in page_sections(request.prompt):
        found = sorted(
            (text.index(measure_text), measure_text)
            for measure_text in content.MEASURES_BY_TEXT
            if measure_text in text
        )
        for _, measure_text in found:
            measure = content.MEASURES_BY_TEXT[measure_text]
            items.append(
                {
                    "text": measure_text,
                    "page": page,
                    "categories": [measure.category],
                    "tags": list(measure.tags),
                }
            )
    return {"proposals": items}


def conflict_check(request: LLMRequest[Any]) -> dict[str, Any]:
    """The scripted contradiction pairs whose texts are in lists A and B, in either order."""
    list_a = {text: int(n) for n, text in _LIST_A_RE.findall(request.prompt)}
    list_b = {text: int(n) for n, text in _LIST_B_RE.findall(request.prompt)}
    found: list[dict[str, Any]] = []
    for conflict in content.CONFLICTS:
        first, second = (one_line(text) for text in conflict.texts)
        for a_text, b_text in ((first, second), (second, first)):
            if a_text in list_a and b_text in list_b:
                found.append(
                    {"a": list_a[a_text], "b": list_b[b_text], "explanation": conflict.explanation}
                )
    return {"contradictions": found}


def statement_drafts(request: LLMRequest[Any]) -> dict[str, Any]:
    """The category's scripted Statements not yet listed, each citing the listed Proposals
    that hold a stance on it. No additions."""
    category = _category(request)
    proposals = [(int(n), text) for n, text in _PROPOSAL_RE.findall(request.prompt)]
    previous = {text for _, text in _PREVIOUS_RE.findall(request.prompt)}
    drafted: list[dict[str, Any]] = []
    for statement in content.STATEMENTS:
        if statement.category != category or one_line(statement.text) in previous:
            continue
        sources = [n for n, text in proposals if _stance(text, statement.key) is not None]
        if sources:
            drafted.append(
                {"text": statement.text, "context_note": statement.note, "sources": sources}
            )
    return {"statements": drafted, "additions": []}


def proposal_positions(request: LLMRequest[Any]) -> dict[str, Any]:
    """For each listed Statement, the listed Proposals with a stance on it: their common
    value and the first 5 as Evidence. Mixed signs are a content bug."""
    proposals = [(int(n), text) for n, text in _PROPOSAL_RE.findall(request.prompt)]
    positions: list[dict[str, Any]] = []
    for number, text in _STATEMENT_RE.findall(request.prompt):
        statement = _STATEMENTS.get(text)
        if statement is None:
            raise LLMOutputError(f"dev provider: unscripted statement {text[:60]!r}")
        cited = [(n, v) for n, t in proposals if (v := _stance(t, statement.key)) is not None]
        if not cited:
            continue
        if len({v > 0 for _, v in cited}) > 1:
            raise LLMOutputError(
                f"dev provider: mixed stances on {statement.key}; the content is inconsistent"
            )
        positions.append(
            {"statement": int(number), "value": cited[0][1], "evidence": [n for n, _ in cited][:5]}
        )
    return {"positions": positions}


def rewording_check(request: LLMRequest[Any]) -> dict[str, Any]:
    """The scripted verdict for the new text."""
    match = _NEW_TEXT_RE.search(request.prompt)
    if match is None or match.group(1) != one_line(content.REWORDING.text):
        raise LLMOutputError("dev provider: unscripted rewording")
    return {"equivalent": True, "explanation": content.REWORDING.explanation}


def build_provider() -> FakeProvider:
    """A fresh scripted provider (tests patch this seam to make the seed fail)."""
    return FakeProvider(
        {
            "proposal_extraction": extraction,
            "proposal_conflict_check": conflict_check,
            "statement_drafts": statement_drafts,
            "proposal_positions": proposal_positions,
            "statement_rewording_check": rewording_check,
        },
        model=MODEL,
    )


__all__ = [
    "MODEL",
    "build_provider",
    "conflict_check",
    "extraction",
    "page_sections",
    "proposal_positions",
    "rewording_check",
    "statement_drafts",
]
