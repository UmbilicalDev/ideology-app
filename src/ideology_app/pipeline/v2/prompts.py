"""The v2 prompts ``statement_drafts`` and ``proposal_positions``, their schemas and requests.

This module defines its own frozen ``V2Prompt``s and never imports
``pipeline.prompts``: neither task joins the legacy ``PROMPTS`` /
``PROMPT_VERSIONS``, whose fingerprints and recorded calls stay unchanged. A v2
run records ``V2_PROMPT_VERSIONS``. Changing a system text, template,
``max_tokens`` or schema MUST bump that prompt's ``version`` and the
fingerprint pinned in ``tests/test_v2_prompts.py``.

Only Proposal text (and its free tags), Statement texts, the category's
Spanish name and the configured Context Note bounds reach the prompts: no
Party name or short name, no file name and no page.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, create_model

from ideology_app.config import ValidationSettings
from ideology_app.llm.base import LLMRequest
from ideology_app.proposals.conflict_prompts import one_line
from ideology_app.topic_catalog import TOPIC_CATALOG

DRAFTS_MAX_NEW = 25
DRAFT_SOURCES_MAX = 40
DRAFT_TARGET_PER_PROPOSALS = 12
DRAFT_TARGET_MIN = 3
EVIDENCE_MAX = 5
NO_PREVIOUS_TEXT = "(ninguna)"

CATEGORY_NAMES: dict[str, str] = {entry.key: entry.name for entry in TOPIC_CATALOG}


@dataclass(frozen=True)
class V2Prompt:
    """A versioned v2 prompt: system text, ``str.format`` template and output token limit."""

    task: str
    version: str
    system: str
    template: str
    max_tokens: int


# --- Schemas ----------------------------------------------------------------------

DraftText = Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"\S")]
NoteText = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]


class DraftStatement(BaseModel):
    """A new Statement, its Context Note and the numbers of the Proposals it groups."""

    text: DraftText
    context_note: NoteText
    # Base type only: requests bound each number with ``draft_set_schema``.
    sources: list[int] = Field(min_length=1, max_length=DRAFT_SOURCES_MAX)


class DraftAddition(BaseModel):
    """More Proposal numbers for a Statement already listed (``S<statement>``)."""

    statement: int = Field(ge=1)
    sources: list[int] = Field(min_length=1, max_length=DRAFT_SOURCES_MAX)


class DraftSet(BaseModel):
    """The Statements drafted from one slice of a category, and additions to earlier ones."""

    statements: list[DraftStatement] = Field(max_length=DRAFTS_MAX_NEW)
    additions: list[DraftAddition] = Field(max_length=DRAFTS_MAX_NEW)


PositionValue = Literal[-2, -1, 0, 1, 2]


class ProposalPosition(BaseModel):
    """The stance of the Proposals on one Statement and the Proposals that back it."""

    statement: int = Field(ge=1)
    value: PositionValue
    evidence: list[int] = Field(min_length=1, max_length=EVIDENCE_MAX)


class ProposalPositionList(BaseModel):
    """One entry per Statement the Proposals address; an omitted one is no stance."""

    positions: list[ProposalPosition]


def _subclass(base: type[BaseModel], **fields: Any) -> Any:
    """A subclass of ``base`` with the same name and docstring (same schema title)."""
    return create_model(base.__name__, __base__=base, __doc__=base.__doc__, **fields)


def _check(name: str, value: object, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}, got {value!r}")
    return value


def _numbers(upper: int, max_items: int) -> Any:
    return (
        list[Annotated[int, Field(ge=1, le=upper)]],
        Field(min_length=1, max_length=max_items),
    )


@lru_cache(maxsize=1024)
def _draft_set_schema(n_proposals: int, n_previous: int) -> type[DraftSet]:
    statement = _subclass(DraftStatement, sources=_numbers(n_proposals, DRAFT_SOURCES_MAX))
    if n_previous == 0:
        additions: Any = (list[DraftAddition], Field(max_length=0))
    else:
        addition = _subclass(
            DraftAddition,
            statement=(int, Field(ge=1, le=n_previous)),
            sources=_numbers(n_proposals, DRAFT_SOURCES_MAX),
        )
        additions = (list[addition], Field(max_length=n_previous))
    return _subclass(
        DraftSet,
        statements=(list[statement], Field(max_length=DRAFTS_MAX_NEW)),
        additions=additions,
    )


def draft_set_schema(n_proposals: int, n_previous: int) -> type[DraftSet]:
    """``DraftSet`` whose source numbers are 1..``n_proposals`` and whose additions name
    ``S1..S<n_previous>`` (at most ``n_previous`` of them; none when it is 0).

    Raises ``ValueError`` unless ``n_proposals`` >= 1 and ``n_previous`` >= 0. Cached.
    """
    return _draft_set_schema(
        _check("n_proposals", n_proposals, 1), _check("n_previous", n_previous, 0)
    )


@lru_cache(maxsize=1024)
def _position_set_schema(n_statements: int, n_proposals: int) -> type[ProposalPositionList]:
    item = _subclass(
        ProposalPosition,
        statement=(int, Field(ge=1, le=n_statements)),
        evidence=_numbers(n_proposals, EVIDENCE_MAX),
    )
    return _subclass(
        ProposalPositionList, positions=(list[item], Field(max_length=n_statements))
    )


def position_set_schema(n_statements: int, n_proposals: int) -> type[ProposalPositionList]:
    """``ProposalPositionList`` with ``statement`` 1..N (at most N entries) and 1..5
    ``evidence`` numbers in 1..K. Raises ``ValueError`` unless both are >= 1. Cached.
    A repeated Statement is allowed here; ``positions.assign_positions`` rejects it."""
    return _position_set_schema(
        _check("n_statements", n_statements, 1), _check("n_proposals", n_proposals, 1)
    )


# --- Prompts ----------------------------------------------------------------------

_STATEMENT_RULES = (
    "Reglas para cada afirmación:\n"
    "- Escribe en español de España.\n"
    "- Una sola proposición por afirmación: nunca unas dos políticas con \"y\", \"o\" ni "
    "\"y/o\".\n"
    "- Redacción neutral: sin adjetivos valorativos, sin nombres de partidos ni de "
    "políticos y sin atribuciones (nada de \"el programa propone...\").\n"
    "- Cada afirmación es una propuesta política en forma afirmativa con la que un "
    "votante puede estar de acuerdo o en desacuerdo, y expresa una orientación con una "
    "dirección clara (por ejemplo, subir o bajar un impuesto, ampliar o reducir un "
    "servicio público).\n"
    "- Sin cifras, porcentajes ni plazos salvo que sean el núcleo de la propuesta.\n"
    "- Cada afirmación se entiende por sí sola, sin conocer la legislación ni la "
    "política vigentes: di en qué consiste lo que se propone.\n"
    "- Expresa la medida por su contenido y en positivo, de modo que estar de acuerdo "
    "signifique querer esa medida: en lugar de pedir que se derogue o suprima una ley, "
    "una reforma o una institución, di lo que debe regir o hacerse. Usa derogar, "
    "suprimir o eliminar solo cuando la propuesta no tenga otro contenido que hacer "
    "desaparecer esa norma o institución, y entonces nómbrala.\n"
    "- Sin dobles negaciones: no combines «no», «nunca» o «sin» con verbos como "
    "prohibir, impedir, suprimir, eliminar o derogar.\n"
    "- Lenguaje llano: frases cortas y palabras de uso común. Si una afirmación necesita "
    "un término técnico o el nombre de una ley, un plan o un organismo, la nota de "
    "contexto lo explica.\n"
)

_GROUP_RULES = (
    "Reglas para agrupar:\n"
    "- Agrupa las propuestas que tratan el mismo asunto, aunque estén redactadas de otra "
    "forma o vayan en la dirección contraria, y escribe una sola afirmación por grupo.\n"
    "- En `sources` cita el número de cada propuesta del grupo (P1 es 1), también las "
    "que van en la dirección contraria.\n"
    "- No repitas ninguna de las afirmaciones ya redactadas: si un grupo trata el mismo "
    "asunto que una de ellas, añade sus números en `additions` con el número de esa "
    "afirmación (S1 es 1).\n"
    "- Prefiere los asuntos que tratan varias propuestas; una propuesta de detalle "
    "puede quedarse sin afirmación.\n"
    "- Basa cada afirmación solo en las propuestas de la lista: no añadas temas ni "
    "propuestas que no aparezcan en ella.\n"
)

_NOTE_RULES = (
    "Reglas para la nota de contexto (`context_note`) de cada afirmación:\n"
    "- Una o dos frases que explican de forma neutral lo que un votante podría no "
    "conocer para entender la afirmación: qué es la ley, la reforma, el plan, la "
    "institución, el organismo, la sigla o el término técnico que nombra (nombre "
    "oficial, año y qué establece o hace). Si no nombra ninguno, explica brevemente el "
    "concepto principal.\n"
    "- Si un nombre es un apodo del debate público, da el nombre oficial y di que se la "
    "conoce así.\n"
    "- Solo hechos descriptivos: sin valoraciones, sin argumentos a favor o en contra, "
    "sin efectos previstos, sin la posición de nadie y sin nombres de partidos, de "
    "políticos ni de gobiernos.\n"
    "- No repitas la afirmación ni añadas propuestas."
)

STATEMENT_DRAFTS = V2Prompt(
    task="statement_drafts",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Recibes propuestas concretas, "
        "copiadas literalmente de los programas electorales, sobre un mismo tema, y las "
        "afirmaciones de ese tema ya redactadas. Agrupas las propuestas similares y "
        "redactas una afirmación del cuestionario por grupo; después, un procedimiento "
        "automático situará a cada candidatura en cada afirmación a partir de sus "
        "propuestas.\n\n"
        + _STATEMENT_RULES
        + _GROUP_RULES
        + _NOTE_RULES
    ),
    template=(
        "Tema: {category}\n\n"
        "Afirmaciones ya redactadas de este tema (una por línea, con su número):\n\n"
        "{previous}\n\n"
        "Propuestas (una por línea, con su número y sus etiquetas entre corchetes):\n\n"
        "{proposals}\n\n"
        "Redacta unas {target} afirmaciones nuevas (como máximo {max_new}) a partir de "
        "los grupos de propuestas similares, citando en `sources` las propuestas de cada "
        "grupo, y añade en `additions` las propuestas que tratan una afirmación ya "
        "redactada. Cada nota de contexto tiene entre {note_min} y {note_max} caracteres "
        "y no usa ninguna de estas palabras: {evaluative_words}."
    ),
    # Up to 25 Statements with a note and up to 40 sources each, plus additions.
    max_tokens=16384,
)

_SCALE = (
    "Escala de posición, desde el punto de vista de las propuestas: -2 totalmente en "
    "desacuerdo, -1 en desacuerdo, 0 neutral, 1 de acuerdo, 2 totalmente de acuerdo."
)

PROPOSAL_POSITIONS = V2Prompt(
    task="proposal_positions",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Recibes afirmaciones del cuestionario "
        "sobre un tema y las propuestas concretas, copiadas literalmente de los programas "
        "electorales de una misma candidatura, sobre ese tema. Para cada afirmación que "
        "las propuestas tratan, indicas la posición de la candidatura y las propuestas "
        "que la respaldan.\n\n"
        f"{_SCALE}\n\n"
        "Reglas:\n"
        "- Informa solo de las afirmaciones que alguna propuesta trata de forma explícita.\n"
        "- Una propuesta que va claramente en la dirección de una afirmación cuenta como "
        "acuerdo; una que va en la dirección contraria cuenta como desacuerdo, y se cita.\n"
        "- Nunca deduzcas una posición de la ideología general ni del silencio: que "
        "ninguna propuesta trate un asunto no es una posición.\n"
        "- En `evidence` cita de 1 a 5 números de las propuestas que respaldan la posición "
        "(P1 es 1), la que mejor la respalda primero.\n"
        "- `statement` es el número de la afirmación entre corchetes. Informa de cada "
        "afirmación una sola vez.\n"
        "- Omite una afirmación cuando ninguna propuesta la trate: una afirmación omitida "
        "significa que la candidatura no tiene posición.\n"
        "- Si las propuestas no tratan ninguna afirmación, devuelve una lista vacía."
    ),
    template=(
        "Tema: {category}\n\n"
        "Afirmaciones del cuestionario (una por línea, con su número entre corchetes):\n\n"
        "{statements}\n\n"
        "Propuestas de la candidatura sobre este tema (una por línea, con su número):\n\n"
        "{proposals}\n\n"
        "Indica la posición de la candidatura en cada afirmación que estas propuestas "
        "tratan, con las propuestas que la respaldan."
    ),
    max_tokens=4096,
)

V2_PROMPTS: tuple[V2Prompt, ...] = (STATEMENT_DRAFTS, PROPOSAL_POSITIONS)
V2_PROMPT_VERSIONS: dict[str, str] = {prompt.task: prompt.version for prompt in V2_PROMPTS}


# --- Requests ---------------------------------------------------------------------


@dataclass(frozen=True)
class DraftInput:
    """A Proposal as ``statement_drafts`` shows it: text and free tags only."""

    text: str
    tags: tuple[str, ...] = ()


def category_name(category: str) -> str:
    """The Spanish catalog name of ``category``. Raises ``ValueError`` for an unknown key."""
    if category not in CATEGORY_NAMES:
        raise ValueError(f"unknown category {category!r}")
    return CATEGORY_NAMES[category]


def draft_target(count: int) -> int:
    """How many new Statements to ask for: ``clamp(ceil(count / 12), 3, 25)``."""
    return min(max(math.ceil(count / DRAFT_TARGET_PER_PROPOSALS), DRAFT_TARGET_MIN), DRAFTS_MAX_NEW)


def _proposal_line(number: int, proposal: DraftInput) -> str:
    text = one_line(proposal.text)
    if not proposal.tags:
        return f"P{number}. {text}"
    tags = ", ".join(one_line(tag) for tag in proposal.tags)
    return f"P{number}. [{tags}] {text}"


def draft_request(
    category: str,
    proposals: Sequence[DraftInput],
    previous: Sequence[str],
    settings: ValidationSettings,
) -> LLMRequest[DraftSet]:
    """The ``statement_drafts`` request for one slice of ``category``.

    ``previous`` are the texts of the Statements already drafted for the
    category (``S1. text``, or ``(ninguna)``). Raises ``ValueError`` for an
    empty slice or an unknown category.
    """
    if not proposals:
        raise ValueError("a draft request needs at least one proposal")
    previous_lines = (
        "\n".join(f"S{k}. {one_line(text)}" for k, text in enumerate(previous, start=1))
        or NO_PREVIOUS_TEXT
    )
    return LLMRequest(
        task=STATEMENT_DRAFTS.task,
        system=STATEMENT_DRAFTS.system,
        prompt=STATEMENT_DRAFTS.template.format(
            category=category_name(category),
            previous=previous_lines,
            proposals="\n".join(_proposal_line(k, p) for k, p in enumerate(proposals, start=1)),
            target=draft_target(len(proposals)),
            max_new=DRAFTS_MAX_NEW,
            note_min=settings.context_note_min_chars,
            note_max=settings.context_note_max_chars,
            evaluative_words=", ".join(settings.context_note_evaluative_words),
        ),
        schema=draft_set_schema(len(proposals), len(previous)),
        max_tokens=STATEMENT_DRAFTS.max_tokens,
    )


def position_request(
    category: str, statements: Sequence[str], proposals: Sequence[str]
) -> LLMRequest[ProposalPositionList]:
    """The ``proposal_positions`` request: Statements ``[k] text``, Proposals ``Pk. text``."""
    if not statements or not proposals:
        raise ValueError("a position request needs statements and proposals")
    return LLMRequest(
        task=PROPOSAL_POSITIONS.task,
        system=PROPOSAL_POSITIONS.system,
        prompt=PROPOSAL_POSITIONS.template.format(
            category=category_name(category),
            statements="\n".join(
                f"[{k}] {one_line(text)}" for k, text in enumerate(statements, start=1)
            ),
            proposals="\n".join(
                f"P{k}. {one_line(text)}" for k, text in enumerate(proposals, start=1)
            ),
        ),
        schema=position_set_schema(len(statements), len(proposals)),
        max_tokens=PROPOSAL_POSITIONS.max_tokens,
    )


__all__ = [
    "CATEGORY_NAMES",
    "DRAFTS_MAX_NEW",
    "DRAFT_SOURCES_MAX",
    "EVIDENCE_MAX",
    "NO_PREVIOUS_TEXT",
    "PROPOSAL_POSITIONS",
    "STATEMENT_DRAFTS",
    "V2_PROMPTS",
    "V2_PROMPT_VERSIONS",
    "DraftAddition",
    "DraftInput",
    "DraftSet",
    "DraftStatement",
    "ProposalPosition",
    "ProposalPositionList",
    "V2Prompt",
    "category_name",
    "draft_request",
    "draft_set_schema",
    "draft_target",
    "position_request",
    "position_set_schema",
]
