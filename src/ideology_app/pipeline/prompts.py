"""Versioned prompts and output schemas for Statement generation.

Changing a prompt's system text, template or schema MUST bump its ``version``
and the fingerprint pinned in ``tests/test_pipeline_prompts.py``. A Pipeline Run
records ``PROMPT_VERSIONS`` so it is known which prompt produced its output.
"""

from dataclasses import dataclass
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, Field, StringConstraints

Topic = Literal[
    "economy",
    "taxation",
    "employment",
    "pensions",
    "housing",
    "health",
    "education",
    "environment_energy",
    "immigration",
    "justice_security",
    "territorial_model",
    "democracy_institutions",
    "foreign_policy_defense",
    "social_rights_equality",
    "culture_language",
    "agriculture_rural",
    "science_digital",
    "infrastructure_transport",
]

# The topic slugs, in order. ``Topic`` is the single source of the list.
TOPICS: tuple[str, ...] = get_args(Topic)

TARGET_STATEMENT_COUNT = 30

StatementText = Annotated[
    str, StringConstraints(min_length=1, max_length=300, pattern=r"\S")
]


class StatementDraft(BaseModel):
    """One proposed Statement: an affirmative policy proposal with a topic tag."""

    text: StatementText
    topic: Topic


class CandidateList(BaseModel):
    """Statement candidates found in one chunk of manifesto text."""

    candidates: list[StatementDraft] = Field(max_length=12)


class StatementSet(BaseModel):
    """The final ordered list of Statements for a Questionnaire."""

    statements: list[StatementDraft] = Field(min_length=1, max_length=60)


@dataclass(frozen=True)
class PromptSpec:
    """A versioned prompt: system text, ``str.format`` template and output schema."""

    task: str
    version: str
    system: str
    template: str
    schema: type[BaseModel]
    max_tokens: int


_TOPIC_LIST = ", ".join(TOPICS)

_COMMON_RULES = f"""Reglas para cada afirmación:
- Escribe en español de España.
- Una sola proposición por afirmación: nunca unas dos políticas con "y", "o" ni "y/o".
- Redacción neutral: sin adjetivos valorativos, sin nombres de partidos ni de políticos y sin atribuciones (nada de "el programa propone...").
- Cada afirmación es una propuesta política en forma afirmativa con la que un votante puede estar de acuerdo o en desacuerdo en una escala de 5 puntos.
- Prefiere propuestas que los distintos partidos responderían de forma diferente.
- Usa solo estas etiquetas de tema: {_TOPIC_LIST}."""

STATEMENT_CANDIDATES = PromptSpec(
    task="statement_candidates",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Lees fragmentos de programas "
        "electorales y extraes propuestas políticas concretas que sirvan como "
        "afirmaciones del cuestionario.\n\n"
        f"{_COMMON_RULES}\n"
        "- Devuelve como máximo 12 candidatas por fragmento; si el fragmento no "
        "contiene propuestas políticas, devuelve una lista vacía."
    ),
    template=(
        "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
        "{chunk}\n\n"
        "Extrae las propuestas políticas de este fragmento como afirmaciones candidatas."
    ),
    schema=CandidateList,
    max_tokens=4096,
)

GENERATE_STATEMENTS = PromptSpec(
    task="generate_statements",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Recibes afirmaciones candidatas "
        "extraídas de varios programas electorales y eliges y redactas la lista final "
        "del cuestionario.\n\n"
        f"{_COMMON_RULES}\n"
        "Reglas para la lista:\n"
        "- Cubre los temas de forma amplia: ningún tema debe superar aproximadamente "
        "una cuarta parte de la lista.\n"
        "- Sin afirmaciones casi duplicadas.\n"
        f"- Unas {TARGET_STATEMENT_COUNT} afirmaciones en total."
    ),
    template=(
        "Afirmaciones candidatas (una por línea, con su tema entre corchetes):\n\n"
        "{candidates}\n\n"
        "Elabora la lista final de {count} afirmaciones del cuestionario, en el orden "
        "en que deben presentarse."
    ),
    schema=StatementSet,
    max_tokens=8192,
)

PROMPTS: tuple[PromptSpec, ...] = (STATEMENT_CANDIDATES, GENERATE_STATEMENTS)

PROMPT_VERSIONS: dict[str, str] = {spec.task: spec.version for spec in PROMPTS}
