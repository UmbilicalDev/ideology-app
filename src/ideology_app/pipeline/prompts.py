"""Versioned prompts and output schemas for the Pipeline Run's LLM tasks.

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

# Party Position extraction: findings per chunk, then one reduce per Party.

PositionValue = Literal[-2, -1, 0, 1, 2]

EvidenceQuote = Annotated[
    str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")
]


class Finding(BaseModel):
    """A stance on one Statement found in one chunk, with its verbatim quote."""

    statement: int = Field(ge=1)
    value: PositionValue
    quote: EvidenceQuote
    page: int = Field(ge=1)


class FindingList(BaseModel):
    """The findings of one chunk; empty when it addresses no Statement."""

    findings: list[Finding] = Field(max_length=60)


class PositionChoice(BaseModel):
    """A Party's stance on one Statement, citing one numbered candidate."""

    statement: int = Field(ge=1)
    value: PositionValue
    evidence: int = Field(ge=1)


class PositionList(BaseModel):
    """A Party's stances; an omitted Statement means ``no stance``."""

    positions: list[PositionChoice] = Field(max_length=60)


_SCALE = (
    "Escala de posición, desde el punto de vista del programa: -2 totalmente en "
    "desacuerdo, -1 en desacuerdo, 0 neutral, 1 de acuerdo, 2 totalmente de acuerdo."
)

POSITION_FINDINGS = PromptSpec(
    task="position_findings",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Lees un fragmento de un programa "
        "electoral y, para cada afirmación del cuestionario que el fragmento trata, "
        "indicas la posición del programa y la cita que la respalda.\n\n"
        f"{_SCALE}\n\n"
        "Reglas:\n"
        "- Informa solo de las afirmaciones que el fragmento trata de forma explícita. "
        "Nunca deduzcas una posición de la ideología general.\n"
        "- La cita se copia literalmente de una sola página: sin parafrasear, sin "
        "puntos suspensivos y sin añadir texto.\n"
        "- `page` es el número del marcador [página N] de la página de la cita.\n"
        "- `statement` es el número de la afirmación entre corchetes.\n"
        "- Si el fragmento no trata ninguna afirmación, devuelve una lista vacía."
    ),
    template=(
        "Afirmaciones del cuestionario (una por línea, con su número entre corchetes):\n\n"
        "{statements}\n\n"
        "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
        "{chunk}\n\n"
        "Indica la posición del programa en las afirmaciones que este fragmento trata, "
        "con una cita literal y su página."
    ),
    schema=FindingList,
    max_tokens=4096,
)

MAIN_LABEL = "programa principal"
ADDITIONAL_LABEL = "programa adicional"

PARTY_POSITIONS = PromptSpec(
    task="party_positions",
    version="v1",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Recibes las citas candidatas que se "
        "encontraron en los programas electorales de una misma candidatura y decides "
        "su posición final en cada afirmación del cuestionario.\n\n"
        f"{_SCALE}\n\n"
        "Reglas:\n"
        "- Para cada afirmación, elige una sola posición que las candidatas respalden y "
        "cita (`evidence`) el número de la candidata que mejor la respalda.\n"
        "- Si ninguna candidata respalda una posición, omite la afirmación: una "
        "afirmación omitida significa que la candidatura no tiene posición.\n"
        f"- Cada candidata indica si viene del {MAIN_LABEL} (el programa conjunto de "
        f"la coalición) o de un {ADDITIONAL_LABEL}. Si se contradicen, prevalece el "
        f"{MAIN_LABEL}.\n"
        "- Nunca inventes una candidata: cita solo números de la lista."
    ),
    template=(
        "Afirmaciones del cuestionario (una por línea, con su número entre corchetes):\n\n"
        "{statements}\n\n"
        "Citas candidatas (una por línea: número, programa, afirmación, valor, página "
        "y cita):\n\n"
        "{candidates}\n\n"
        "Decide la posición final en cada afirmación que las candidatas respaldan."
    ),
    schema=PositionList,
    max_tokens=8192,
)

PROMPTS: tuple[PromptSpec, ...] = (
    STATEMENT_CANDIDATES,
    GENERATE_STATEMENTS,
    POSITION_FINDINGS,
    PARTY_POSITIONS,
)

PROMPT_VERSIONS: dict[str, str] = {spec.task: spec.version for spec in PROMPTS}
