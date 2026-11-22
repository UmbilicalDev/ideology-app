"""Versioned prompts and output schemas for the Pipeline Run's LLM tasks.

Changing a prompt's system text, template or schema MUST bump its ``version``
and the fingerprint pinned in ``tests/test_pipeline_prompts.py``. A Pipeline Run
records ``PROMPT_VERSIONS`` so it is known which prompt produced its output.

The static ``StatementSet`` (items ``PoolStatement``), ``FindingList`` and ``PositionList`` are base
types only. Every request uses the bounded schema of its builder
(``statement_set_schema``, ``finding_list_schema``, ``position_list_schema``),
which limits the Statement count and every Statement or candidate number to
the ones that request allows or lists.
"""

from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, Field, StringConstraints, create_model

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

# The Statement Pool that ``generate_statements`` asks for. The final
# Questionnaire (``ValidationSettings.min_statements``..``max_statements``) is
# chosen from it by ``pipeline.selection``; ``generation.pool_bounds`` widens
# these bounds when the configured maximum is larger.
# e2e-real-2026-election: 60..80 (was 45..60). With 11 Parties a 53-Statement
# pool held stances for some Parties on only 16 Statements, too few for any
# selection to reach the coverage minimum.
# pipeline-statement-priority-tiers: 100..140 (target 120), so the ranking by
# Parties with a side has enough multi-Party Statements for up to 40.
POOL_MIN_STATEMENTS = 100
POOL_MAX_STATEMENTS = 140
POOL_TARGET_STATEMENTS = 120

# The most findings one ``position_findings`` call may return. Fixed at 80 (the
# old pool maximum) so that request stays byte-identical when the pool moves;
# Statement batches of ``FINDINGS_STATEMENTS_PER_CALL`` (20) never need more.
FINDINGS_MAX = 80

StatementText = Annotated[
    str, StringConstraints(min_length=1, max_length=300, pattern=r"\S")
]


class StatementDraft(BaseModel):
    """One proposed Statement: an affirmative policy proposal with a topic tag."""

    text: StatementText
    topic: Topic


class CandidateList(BaseModel):
    """Statement candidates found in one chunk of manifesto text."""

    candidates: list[StatementDraft] = Field(max_length=30)


# The structural cap of a context note; equals ``config.CONTEXT_NOTE_MAX_CHARS_LIMIT``
# and the ``statements.context_note`` column width. The configured bounds
# (``ValidationSettings.context_note_min_chars``..``max_chars``) are not in the
# schema: Statement Selection and Validation enforce them, so a long note costs
# one Statement, not the reduce call.
CONTEXT_NOTE_SCHEMA_MAX = 500

ContextNoteText = Annotated[
    str, StringConstraints(min_length=1, max_length=CONTEXT_NOTE_SCHEMA_MAX, pattern=r"\S")
]


class PoolStatement(StatementDraft):
    """A Statement Pool item: a proposed Statement, its context note and its anchor."""

    context_note: ContextNoteText
    # Base type only: requests bound it with ``statement_set_schema`` (1..anchors).
    anchor: int | None


class StatementSet(BaseModel):
    """The final ordered list of Statements for a Questionnaire."""

    # Base type only: requests use ``statement_set_schema`` (the pool bounds).
    statements: list[PoolStatement] = Field(min_length=1, max_length=POOL_MAX_STATEMENTS)


def _check_bound(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer of at least 1, got {value!r}")
    return value


def _subclass(base: type[BaseModel], **fields: Any) -> Any:
    """A subclass of ``base`` with the same name and docstring, so its schema
    title, description and error messages stay those of the base."""
    return create_model(base.__name__, __base__=base, __doc__=base.__doc__, **fields)


@cache
def _statement_set_schema(
    min_statements: int, max_statements: int, anchor_count: int
) -> type[StatementSet]:
    if anchor_count == 0:
        item = _subclass(PoolStatement, anchor=(None, ...))
    else:
        item = _subclass(
            PoolStatement, anchor=(int | None, Field(..., ge=1, le=anchor_count))
        )
    return _subclass(
        StatementSet,
        statements=(
            list[item],
            Field(min_length=min_statements, max_length=max_statements),
        ),
    )


def statement_set_schema(
    min_statements: int, max_statements: int, anchor_count: int = 0
) -> type[StatementSet]:
    """``StatementSet`` with ``min_statements``..``max_statements`` Statements.

    Each item's ``anchor`` is ``null`` or an integer from 1 to ``anchor_count``
    (only ``null`` when ``anchor_count`` is 0); ``context_note`` and ``anchor``
    are both required. Raises ``ValueError`` unless both bounds are integers of
    at least 1, min is not above max, and ``anchor_count`` is a non-negative
    integer. Cached: the same arguments give the same class.
    """
    low = _check_bound("min_statements", min_statements)
    high = _check_bound("max_statements", max_statements)
    if low > high:
        raise ValueError(
            f"min_statements ({low}) must not be above max_statements ({high})"
        )
    if isinstance(anchor_count, bool) or not isinstance(anchor_count, int) or anchor_count < 0:
        raise ValueError(f"anchor_count must be a non-negative integer, got {anchor_count!r}")
    return _statement_set_schema(low, high, anchor_count)


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
- Cada afirmación es una propuesta política en forma afirmativa con la que un votante puede estar de acuerdo o en desacuerdo.
- Usa solo estas etiquetas de tema: {_TOPIC_LIST}."""

STATEMENT_CANDIDATES = PromptSpec(
    task="statement_candidates",
    version="v2",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Lees fragmentos de programas "
        "electorales y extraes todas las propuestas políticas concretas que contienen, "
        "como afirmaciones candidatas del cuestionario.\n\n"
        f"{_COMMON_RULES}\n"
        "- Extrae cada propuesta concreta del fragmento, también las de detalle y las "
        "que solo aparecen una vez, sin elegir entre ellas; devuelve como máximo 30 "
        "candidatas por fragmento y, si hay más, las que el fragmento desarrolla con "
        "más detalle. Si el fragmento no contiene propuestas políticas, devuelve una "
        "lista vacía."
    ),
    template=(
        "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
        "{chunk}\n\n"
        "Extrae todas las propuestas políticas concretas de este fragmento como "
        "afirmaciones candidatas."
    ),
    schema=CandidateList,
    # pipeline-statement-priority-tiers: up to 30 candidates of about 140 tokens.
    max_tokens=8192,
)

GENERATE_STATEMENTS = PromptSpec(
    task="generate_statements",
    version="v7",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Recibes afirmaciones candidatas "
        "extraídas, en igual número, de los programas electorales de varias "
        "candidaturas, y las afirmaciones del cuestionario publicado anteriormente "
        "para estas elecciones, si lo hay; redactas a partir de ellas una lista amplia "
        "de afirmaciones; después, un procedimiento automático elegirá entre ellas las "
        "del cuestionario.\n\n"
        f"{_COMMON_RULES}\n"
        "Reglas para la lista:\n"
        "- Cada afirmación expresa una orientación política con una dirección clara "
        "(por ejemplo, subir o bajar un impuesto, ampliar o reducir un servicio "
        "público, más o menos peso de una fuente de energía), no una medida de "
        "detalle: sin cifras, porcentajes ni plazos salvo que sean el núcleo de la "
        "propuesta.\n"
        "- Cada afirmación se entiende por sí sola, sin conocer la legislación ni "
        "la política vigentes: di en qué consiste lo que se propone. Nunca hables "
        "de \"la política actual\", \"el modelo vigente\" o \"la ley actual\" sin "
        "decir cuál es ni qué establece.\n"
        "- Expresa la medida por su contenido y en positivo, de modo que estar de "
        "acuerdo signifique querer esa medida: en lugar de pedir que se derogue o "
        "suprima una ley, una reforma o una institución, di lo que debe regir o "
        "hacerse (por ejemplo, «Debe poder limitarse el precio del alquiler en las "
        "zonas donde es más alto» y no «Debe derogarse la Ley de Vivienda de 2023, "
        "que permite limitar el precio del alquiler»). Usa derogar, suprimir o "
        "eliminar solo cuando la propuesta no tenga otro contenido que hacer "
        "desaparecer esa norma o institución, y entonces nómbrala.\n"
        "- Sin dobles negaciones: no combines «no», «nunca» o «sin» con verbos como "
        "prohibir, impedir, suprimir, eliminar o derogar.\n"
        "- Lenguaje llano: frases cortas y palabras de uso común. Si una afirmación "
        "necesita un término técnico o el nombre de una ley, un plan o un organismo, "
        "la nota de contexto lo explica.\n"
        "- Nunca dejes una regla abstracta sin decir qué supone en la práctica: «Por "
        "cada nueva regulación que afecte a las empresas deben derogarse dos normas "
        "existentes» no se entiende sin saber qué normas ni para qué; di el objetivo "
        "de la medida (por ejemplo, reducir el número de normas que deben cumplir las "
        "empresas).\n"
        "- Agrupa en una misma orientación las candidatas de programas distintos que "
        "van en esa dirección o en la contraria, para que el mayor número posible de "
        "programas se pueda situar en ella.\n"
        "- Prefiere las orientaciones que tratan más programas: el cuestionario empieza "
        "por las afirmaciones en las que se sitúan más candidaturas y deja fuera las que "
        "tratan muy pocas.\n"
        "- Elige orientaciones en las que unos programas estén a favor y otros en "
        "contra; evita las que casi cualquier programa suscribiría.\n"
        "- Varía el sentido de las afirmaciones: no todas deben proponer aumentar o "
        "ampliar algo; usa también reducir o limitar cuando así lo planteen las "
        "candidatas.\n"
        "- Basa cada afirmación solo en las candidatas y en las afirmaciones "
        "anteriores: no añadas temas ni propuestas que no aparezcan en ellas.\n"
        "- Cubre los temas de forma amplia: ningún tema debe superar aproximadamente "
        "una cuarta parte de la lista.\n"
        "- Sin afirmaciones casi duplicadas.\n"
        "- Los votantes ya conocen las afirmaciones anteriores. Para cada una, incluye "
        "en la lista una afirmación con la misma orientación, redactada de nuevo con "
        "estas reglas, y pon su número en `anchor`; si une dos políticas, divídela en "
        "dos afirmaciones con el mismo `anchor`. Las demás afirmaciones llevan "
        "`anchor` nulo.\n"
        "Reglas para la nota de contexto (`context_note`) de cada afirmación:\n"
        "- Una o dos frases que explican de forma neutral lo que un votante podría no "
        "conocer para entender la afirmación: qué es la ley, la reforma, el plan, la "
        "institución, el organismo, la sigla o el término técnico que nombra (nombre "
        "oficial, año y qué establece o hace). Si no nombra ninguno, explica "
        "brevemente el concepto principal.\n"
        "- Si un nombre es un apodo del debate público, da el nombre oficial y di que "
        "se la conoce así.\n"
        "- Solo hechos descriptivos: sin valoraciones, sin argumentos a favor o en "
        "contra, sin efectos previstos, sin la posición de nadie y sin nombres de "
        "partidos, de políticos ni de gobiernos.\n"
        "- No repitas la afirmación ni añadas propuestas."
    ),
    template=(
        "Afirmaciones candidatas (una por línea, con su tema entre corchetes):\n\n"
        "{candidates}\n\n"
        "Afirmaciones del cuestionario publicado anteriormente (una por línea, con su "
        "número y su tema entre corchetes):\n\n"
        "{anchors}\n\n"
        "Elabora una lista de {count} afirmaciones (como mínimo {min_count} y como "
        "máximo {max_count}), en el orden en que deben presentarse."
        " Cada nota de contexto tiene entre {note_min} y {note_max} caracteres y no "
        "usa ninguna de estas palabras: {evaluative_words}."
    ),
    schema=StatementSet,
    # v7 (pipeline-statement-priority-tiers): up to 140 Statements with a context
    # note each, about 190 tokens per item (~27k); v6's 32768 left too little margin.
    max_tokens=49152,
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

    findings: list[Finding] = Field(max_length=FINDINGS_MAX)


class PositionChoice(BaseModel):
    """A Party's stance on one Statement, citing one numbered candidate."""

    statement: int = Field(ge=1)
    value: PositionValue
    evidence: int = Field(ge=1)


class PositionList(BaseModel):
    """A Party's stances; an omitted Statement means ``no stance``."""

    # Base type only (requests bound it with ``position_list_schema``); kept at
    # ``FINDINGS_MAX`` so the pinned ``party_positions`` schema does not move.
    positions: list[PositionChoice] = Field(max_length=FINDINGS_MAX)


# The static FindingList and PositionList above are base types only: requests
# use these builders, which bound each number to the ones the request lists.


@cache
def _finding_list_schema(statement_count: int) -> type[FindingList]:
    finding = _subclass(Finding, statement=(int, Field(ge=1, le=statement_count)))
    return _subclass(FindingList, findings=(list[finding], Field(max_length=FINDINGS_MAX)))


def finding_list_schema(statement_count: int) -> type[FindingList]:
    """``FindingList`` whose ``statement`` numbers are 1..``statement_count``.

    Raises ``ValueError`` unless the count is an integer of at least 1. Cached.
    """
    return _finding_list_schema(_check_bound("statement_count", statement_count))


@cache
def _position_list_schema(statement_count: int, candidate_count: int) -> type[PositionList]:
    choice = _subclass(
        PositionChoice,
        statement=(int, Field(ge=1, le=statement_count)),
        evidence=(int, Field(ge=1, le=candidate_count)),
    )
    return _subclass(
        PositionList, positions=(list[choice], Field(max_length=statement_count))
    )


def position_list_schema(statement_count: int, candidate_count: int) -> type[PositionList]:
    """``PositionList`` with ``statement`` 1..N, ``evidence`` 1..K and at most N entries.

    N is ``statement_count``, K is ``candidate_count``. Raises ``ValueError``
    unless both are integers of at least 1. Cached. A repeated Statement is
    still allowed here; extraction rejects it.
    """
    return _position_list_schema(
        _check_bound("statement_count", statement_count),
        _check_bound("candidate_count", candidate_count),
    )


_SCALE = (
    "Escala de posición, desde el punto de vista del programa: -2 totalmente en "
    "desacuerdo, -1 en desacuerdo, 0 neutral, 1 de acuerdo, 2 totalmente de acuerdo."
)

POSITION_FINDINGS = PromptSpec(
    task="position_findings",
    version="v5",
    system=(
        "Eres un analista político que prepara un cuestionario de orientación de voto "
        "para unas elecciones generales en España. Lees un fragmento de un programa "
        "electoral y, para cada afirmación del cuestionario que el fragmento trata, "
        "indicas la posición del programa y la cita que la respalda.\n\n"
        f"{_SCALE}\n\n"
        "Reglas:\n"
        "- Informa solo de las afirmaciones que el fragmento trata de forma explícita. "
        "Nunca deduzcas una posición de la ideología general.\n"
        "- Una propuesta concreta del fragmento que va claramente en la dirección de "
        "una afirmación, o en la contraria, cuenta como tratarla de forma explícita: "
        "la posición es de acuerdo si va en esa dirección y en desacuerdo si va en la "
        "contraria, y la cita debe contener esa propuesta.\n"
        "- Que el fragmento no mencione un asunto no es una posición: no informes de "
        "esa afirmación.\n"
        "- La cita se copia literalmente de una sola página: sin parafrasear, sin "
        "puntos suspensivos y sin añadir texto.\n"
        "- `page` es el número del marcador [página N] de la página de la cita.\n"
        "- `statement` es el número de la afirmación entre corchetes.\n"
        "- Si el fragmento no trata ninguna afirmación, devuelve una lista vacía."
    ),
    template=(
        "Afirmaciones del cuestionario que revisar en este fragmento (una parte del "
        "cuestionario; una por línea, con su número entre corchetes):\n\n"
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
    version="v2",
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
