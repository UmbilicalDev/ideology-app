"""The ``proposal_extraction`` prompt and its output schema (proposal-extraction).

This module defines its own ``ProposalPrompt`` and never imports
``pipeline.prompts``, so the legacy ``PROMPTS`` / ``PROMPT_VERSIONS`` and their
fingerprints stay unchanged. Changing the system text, the template or the
schema MUST bump ``PROPOSAL_EXTRACTION.version`` and the fingerprint pinned in
``tests/test_proposal_prompts.py``. Only page text reaches the prompt: no Party
names and no file names.

``ProposalItem`` / ``ProposalList`` are base types only. Every request uses
``proposal_list_schema(first_page, last_page)``, which bounds ``page`` to the
pages the request shows (the context page included).
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, create_model

from ideology_app.llm.base import LLMRequest
from ideology_app.topic_catalog import TOPIC_CATALOG

if TYPE_CHECKING:
    from ideology_app.proposals.extraction import Chunk

TASK = "proposal_extraction"

# The 18 topic catalog keys, in catalog display order.
CATEGORY_KEYS: tuple[str, ...] = tuple(entry.key for entry in TOPIC_CATALOG)
Category = Literal[CATEGORY_KEYS]  # type: ignore[valid-type]

TEXT_MAX = 1500
TAG_MAX = 40
CATEGORIES_MAX = 3
TAGS_MAX = 5
PROPOSALS_MAX = 120

ProposalText = Annotated[str, StringConstraints(min_length=1, max_length=TEXT_MAX, pattern=r"\S")]
Tag = Annotated[str, StringConstraints(min_length=1, max_length=TAG_MAX, pattern=r"\S")]


class ProposalItem(BaseModel):
    """One Proposal copied verbatim from the fragment, with the page it starts on."""

    text: ProposalText
    # Base type only: requests bound it with ``proposal_list_schema``.
    page: int = Field(ge=1)
    categories: list[Category] = Field(min_length=1, max_length=CATEGORIES_MAX)  # type: ignore[valid-type]
    tags: list[Tag] = Field(max_length=TAGS_MAX)


class ProposalList(BaseModel):
    """Every Proposal of the fragment, in the order they appear."""

    proposals: list[ProposalItem] = Field(max_length=PROPOSALS_MAX)


@dataclass(frozen=True)
class ProposalPrompt:
    """A versioned prompt: system text, user template and the output token limit."""

    task: str
    version: str
    system: str
    template: str
    max_tokens: int


def _category_list() -> str:
    return ", ".join(f"`{entry.key}` ({entry.name})" for entry in TOPIC_CATALOG)


_SYSTEM = (
    "Eres un analista político que prepara la base de un cuestionario de orientación de "
    "voto para unas elecciones generales en España. Lees un fragmento de un programa "
    "electoral y extraes todas sus propuestas: cada medida concreta o compromiso que el "
    "programa dice que hará, apoyará o rechazará.\n"
    "Reglas:\n"
    "- Una propuesta es un punto de una lista o un párrafo con una medida o un compromiso. "
    "Cada punto de una lista es una propuesta distinta.\n"
    "- Extrae todas las propuestas, también las de detalle y las que solo aparecen una vez, "
    "sin elegir, resumir ni unir.\n"
    "- Incluye texto de diagnóstico o de contexto solo cuando está en el mismo párrafo que "
    "la medida o la medida no se entiende sin él; nunca extraigas un diagnóstico solo.\n"
    "- `text` se copia literalmente del fragmento: sin parafrasear, sin puntos suspensivos, "
    "sin añadir ni quitar palabras y sin el marcador [página N]. Como máximo unos 1.000 "
    "caracteres: si el párrafo es más largo, copia el tramo continuo que contiene la medida.\n"
    "- `page` es el número del marcador de la página donde empieza el texto; el texto puede "
    "seguir en la página siguiente.\n"
    "- La página marcada «solo contexto» sirve solo para completar una propuesta que empieza "
    "antes; no extraigas propuestas que empiecen en ella.\n"
    "- `categories`: de una a tres claves de esta lista, la principal primero; normalmente "
    f"una: {_category_list()}.\n"
    "- `tags`: de cero a cinco etiquetas libres en español, en minúsculas, de una a cuatro "
    "palabras, que nombran el asunto concreto (por ejemplo «alquiler», «salario mínimo», "
    "«energía nuclear»).\n"
    "- Si el fragmento no contiene propuestas (portada, índice, presentación), devuelve una "
    "lista vacía."
)

_TEMPLATE = (
    "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
    "{chunk}\n\n"
    "Extrae todas las propuestas de este fragmento."
)

PROPOSAL_EXTRACTION = ProposalPrompt(
    task=TASK,
    version="v1",
    system=_SYSTEM,
    template=_TEMPLATE,
    max_tokens=16384,
)


def _subclass(base: type[BaseModel], **fields: Any) -> Any:
    """A subclass of ``base`` with the same name and docstring (same schema title)."""
    return create_model(base.__name__, __base__=base, __doc__=base.__doc__, **fields)


def _check_page(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer of at least 1, got {value!r}")
    return value


@lru_cache(maxsize=512)
def _proposal_list_schema(first_page: int, last_page: int) -> type[ProposalList]:
    item = _subclass(ProposalItem, page=(int, Field(ge=first_page, le=last_page)))
    return _subclass(ProposalList, proposals=(list[item], Field(max_length=PROPOSALS_MAX)))


def proposal_list_schema(first_page: int, last_page: int) -> type[ProposalList]:
    """``ProposalList`` whose ``page`` is ``first_page``..``last_page``.

    Raises ``ValueError`` unless both are integers of at least 1 and first is
    not above last. Cached: the same arguments give the same class.
    """
    first = _check_page("first_page", first_page)
    last = _check_page("last_page", last_page)
    if first > last:
        raise ValueError(f"first_page {first} is above last_page {last}")
    return _proposal_list_schema(first, last)


def proposal_request(
    chunk: "Chunk", prompt: ProposalPrompt = PROPOSAL_EXTRACTION
) -> LLMRequest[ProposalList]:
    """The request for one chunk: only its page text, bounded to its pages."""
    return LLMRequest(
        task=prompt.task,
        system=prompt.system,
        prompt=prompt.template.format(chunk=chunk.text),
        schema=proposal_list_schema(chunk.first_page, chunk.last_page),
        max_tokens=prompt.max_tokens,
    )


__all__ = [
    "CATEGORY_KEYS",
    "PROPOSAL_EXTRACTION",
    "TASK",
    "Category",
    "ProposalItem",
    "ProposalList",
    "ProposalPrompt",
    "proposal_list_schema",
    "proposal_request",
]
