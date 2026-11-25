"""The ``proposal_conflict_check`` prompt, its schema and the requests (proposal-conflicts).

This module defines its own frozen prompt and never imports
``pipeline.prompts`` or touches ``proposals.prompts``, so the legacy prompts
and ``proposal_extraction`` keep their fingerprints. Changing the system text,
the template or the schema MUST bump ``PROPOSAL_CONFLICT_CHECK.version`` and
the fingerprint pinned in ``tests/test_conflict_prompts.py``. Only Proposal
text and the category name reach the prompt: no Party names, no file names
and no pages.

Requests are built per topic-catalog category, in catalog order (C1, C10). A
Proposal goes in the bucket of each of its categories; a bucket is compared
only when both sides have Proposals. When both sides together exceed
``CONFLICT_REQUEST_MAX_CHARS`` characters of Proposal text, each side is
sliced in ordinal order into slices of at most ``CONFLICT_SLICE_MAX_CHARS``
and every A-slice x B-slice pair is one request (a single Proposal over the
limit is a slice alone).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints, create_model, field_validator

from ideology_app.ingestion_ledger import note_problem
from ideology_app.llm.base import LLMRequest
from ideology_app.topic_catalog import TOPIC_CATALOG

TASK = "proposal_conflict_check"
CONFLICT_REQUEST_MAX_CHARS = 40_000
CONFLICT_SLICE_MAX_CHARS = 20_000
CONTRADICTIONS_MAX = 40
EXPLANATION_MAX = 300

Explanation = Annotated[str, StringConstraints(min_length=1, max_length=EXPLANATION_MAX)]


class ContradictionItem(BaseModel):
    """A Proposal of list A and one of list B that cannot both be held."""

    # Base types only: requests bound them with ``conflict_list_schema``.
    a: int = Field(ge=1)
    b: int = Field(ge=1)
    explanation: Explanation

    @field_validator("explanation")
    @classmethod
    def _single_line(cls, value: str) -> str:
        problem = note_problem(value)
        if problem is not None:
            raise ValueError(f"explanation {problem}")
        return value


class ContradictionList(BaseModel):
    """Every contradiction between the two lists (empty when there is none)."""

    contradictions: list[ContradictionItem] = Field(max_length=CONTRADICTIONS_MAX)


@dataclass(frozen=True)
class ConflictPrompt:
    """A versioned prompt: system text, user template and the output token limit."""

    task: str
    version: str
    system: str
    template: str
    max_tokens: int


_SYSTEM = (
    "Eres un analista político que revisa la coherencia de los programas electorales de "
    "una misma fuerza política para unas elecciones generales en España. Recibes dos "
    "listas de propuestas de la misma fuerza política sobre un mismo tema, sacadas de dos "
    "documentos, A y B, que se aplican a la vez en algunas circunscripciones.\n"
    "Indica solo los pares de propuestas que se contradicen: las dos no pueden "
    "mantenerse a la vez.\n"
    "Reglas:\n"
    "- Hay contradicción cuando las medidas son opuestas (una propone lo que la otra "
    "rechaza) o cuando fijan cifras, plazos o condiciones incompatibles para lo mismo.\n"
    "- No es contradicción: que una propuesta dé más detalle que la otra, que un asunto "
    "aparezca solo en una lista, que las medidas sean complementarias o que una añada una "
    "medida regional o local a una general.\n"
    "- `a` es el número de la propuesta de la lista A (A1 es 1) y `b` el de la lista B "
    "(B1 es 1).\n"
    "- `explanation`: una frase en español, en una sola línea y de como máximo 300 "
    "caracteres, que dice por qué no pueden mantenerse a la vez.\n"
    "- Si no hay ninguna contradicción, devuelve una lista vacía."
)

_TEMPLATE = (
    "Tema: {category}\n\n"
    "Propuestas del documento A:\n{list_a}\n\n"
    "Propuestas del documento B:\n{list_b}\n\n"
    "Indica los pares de propuestas de A y B que se contradicen."
)

PROPOSAL_CONFLICT_CHECK = ConflictPrompt(
    task=TASK,
    version="v1",
    system=_SYSTEM,
    template=_TEMPLATE,
    max_tokens=4096,
)

_CATEGORY_NAMES = {entry.key: entry.name for entry in TOPIC_CATALOG}


def _subclass(base: type[BaseModel], **fields: Any) -> Any:
    """A subclass of ``base`` with the same name and docstring (same schema title)."""
    return create_model(base.__name__, __base__=base, __doc__=base.__doc__, **fields)


def _check_length(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer of at least 1, got {value!r}")
    return value


@lru_cache(maxsize=512)
def _conflict_list_schema(len_a: int, len_b: int) -> type[ContradictionList]:
    item = _subclass(
        ContradictionItem,
        a=(int, Field(ge=1, le=len_a)),
        b=(int, Field(ge=1, le=len_b)),
    )
    return _subclass(
        ContradictionList, contradictions=(list[item], Field(max_length=CONTRADICTIONS_MAX))
    )


def conflict_list_schema(len_a: int, len_b: int) -> type[ContradictionList]:
    """``ContradictionList`` whose ``a`` is 1..``len_a`` and ``b`` is 1..``len_b``.

    Raises ``ValueError`` unless both are integers of at least 1. Cached: the
    same arguments give the same class.
    """
    return _conflict_list_schema(_check_length("len_a", len_a), _check_length("len_b", len_b))


def one_line(text: str) -> str:
    """A Proposal's text on one line (whitespace runs become one space)."""
    return " ".join(text.split())


def _numbered(prefix: str, texts: Sequence[str]) -> str:
    return "\n".join(f"{prefix}{index}. {one_line(text)}" for index, text in enumerate(texts, 1))


def conflict_request(
    category: str,
    texts_a: Sequence[str],
    texts_b: Sequence[str],
    prompt: ConflictPrompt = PROPOSAL_CONFLICT_CHECK,
) -> LLMRequest[ContradictionList]:
    """The request comparing ``texts_a`` with ``texts_b`` on one topic-catalog category."""
    if category not in _CATEGORY_NAMES:
        raise ValueError(f"unknown category {category!r}")
    return LLMRequest(
        task=prompt.task,
        system=prompt.system,
        prompt=prompt.template.format(
            category=_CATEGORY_NAMES[category],
            list_a=_numbered("A", texts_a),
            list_b=_numbered("B", texts_b),
        ),
        schema=conflict_list_schema(len(texts_a), len(texts_b)),
        max_tokens=prompt.max_tokens,
    )


@dataclass(frozen=True)
class ConflictProposal:
    """What a request needs from a Proposal: its ordinal, text and categories."""

    ordinal: int
    text: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class ConflictRequest:
    """One request and the ordinals its ``A1..An`` / ``B1..Bm`` stand for."""

    category: str
    ordinals_a: tuple[int, ...]
    ordinals_b: tuple[int, ...]
    request: LLMRequest[ContradictionList]


def _slices(side: Sequence[ConflictProposal], limit: int) -> list[list[ConflictProposal]]:
    slices: list[list[ConflictProposal]] = []
    current: list[ConflictProposal] = []
    size = 0
    for proposal in side:
        length = len(one_line(proposal.text))
        if current and size + length > limit:
            slices.append(current)
            current, size = [], 0
        current.append(proposal)
        size += length
    if current:
        slices.append(current)
    return slices


def conflict_requests(
    side_a: Sequence[ConflictProposal],
    side_b: Sequence[ConflictProposal],
    *,
    max_chars: int = CONFLICT_REQUEST_MAX_CHARS,
    slice_chars: int = CONFLICT_SLICE_MAX_CHARS,
) -> list[ConflictRequest]:
    """Every request of one overlap, in catalog order then slice order (pure)."""
    requests: list[ConflictRequest] = []
    for entry in TOPIC_CATALOG:
        bucket_a = sorted(
            (p for p in side_a if entry.key in p.categories), key=lambda p: p.ordinal
        )
        bucket_b = sorted(
            (p for p in side_b if entry.key in p.categories), key=lambda p: p.ordinal
        )
        if not bucket_a or not bucket_b:
            continue
        total = sum(len(one_line(p.text)) for p in (*bucket_a, *bucket_b))
        if total > max_chars:
            pairs = [
                (slice_a, slice_b)
                for slice_a in _slices(bucket_a, slice_chars)
                for slice_b in _slices(bucket_b, slice_chars)
            ]
        else:
            pairs = [(bucket_a, bucket_b)]
        for slice_a, slice_b in pairs:
            requests.append(
                ConflictRequest(
                    entry.key,
                    tuple(p.ordinal for p in slice_a),
                    tuple(p.ordinal for p in slice_b),
                    conflict_request(
                        entry.key, [p.text for p in slice_a], [p.text for p in slice_b]
                    ),
                )
            )
    return requests


__all__ = [
    "CONFLICT_REQUEST_MAX_CHARS",
    "CONFLICT_SLICE_MAX_CHARS",
    "CONTRADICTIONS_MAX",
    "EXPLANATION_MAX",
    "PROPOSAL_CONFLICT_CHECK",
    "TASK",
    "ConflictPrompt",
    "ConflictProposal",
    "ConflictRequest",
    "ContradictionItem",
    "ContradictionList",
    "conflict_list_schema",
    "conflict_request",
    "conflict_requests",
    "one_line",
]
