"""Prompt versions are pinned to their text and schema (Scenario 8), and schemas."""

import hashlib
import json
from typing import Any

import pytest
from pipeline_fixtures import PARTIES, offline_guard
from pydantic import BaseModel, ValidationError

from ideology_app.pipeline import (
    CONTEXT_NOTE_SCHEMA_MAX,
    GENERATE_STATEMENTS,
    PARTY_POSITIONS,
    POOL_MAX_STATEMENTS,
    POOL_MIN_STATEMENTS,
    POOL_TARGET_STATEMENTS,
    POSITION_FINDINGS,
    PROMPT_VERSIONS,
    PROMPTS,
    STATEMENT_CANDIDATES,
    TOPICS,
    CandidateList,
    Finding,
    FindingList,
    PositionChoice,
    PositionList,
    PromptSpec,
    StatementDraft,
    StatementSet,
    finding_list_schema,
    position_list_schema,
    request_hash,
    statement_set_schema,
)
from ideology_app.llm import LLMRequest
from ideology_app.models import SourceDocumentRole
from ideology_app.pipeline.generation import DocumentPages, candidate_request
from ideology_app.pipeline.positions import (
    _Candidate,
    findings_request,
    positions_request,
    statement_lines,
)
from ideology_app.pipeline.prompts import _COMMON_RULES

# To change a prompt: bump its version, then replace its entry here with the new
# (task, version) and the fingerprint printed by the failing test.
FINGERPRINTS = {
    ("statement_candidates", "v1"): "a2073f8c4dcc630a08056db3bef2f59f3e412532693fd2b364af902bbfbe1177",
    ("generate_statements", "v6"): "5ef86697e9a0b579a80ab8fa9e6e91c89d814f59c0d897491011e776c1e03ac1",
    ("position_findings", "v5"): "988fb77e0034909faa79574b65c49889d496a4790c54e65a43e580d921f03690",
    ("party_positions", "v2"): "cd473fcb60cd0ad4c7cbbd0e30c4d5c1d2bfeb37340bcd4aa7801277f1eee9e3",
}

# Requests use the bounded builders, so each prompt is pinned with a reference
# schema: a builder change then fails the pin too.
REFERENCE_SCHEMAS = {
    "statement_candidates": lambda: CandidateList,
    "generate_statements": lambda: statement_set_schema(60, 80, 32),
    "position_findings": lambda: finding_list_schema(30),
    "party_positions": lambda: position_list_schema(30, 10),
}

# request_hash("fake", "fake-model", candidate_request("[página 1]\nTexto")) computed
# on base commit b992e57, before pipeline-output-bounds: the statement_candidates
# request must stay byte-identical so recorded calls stay reusable.
CANDIDATE_REQUEST_HASH = "2936c24068bdc5d815241addb8324d71f4032fc878e880cd953fb36feccf9dab"

# request_hash("fake", "fake-model", ...) of the position requests below. The
# party_positions hash was computed on main cf062e4, before pipeline-verified-findings
# changed extraction; the position_findings hash was re-pinned when its template
# changed to v4 (e2e-real-2026-election, Statement batches; and its schema to at most
# 80 findings). Both requests must stay
# byte-identical so recorded calls stay reusable (--resume-from / --reuse-from).
FINDINGS_REQUEST_HASH = "5f2a99d75e0893205935fc45806f95239a76e95e8a84266a5d5289dd76f9ab08"
POSITIONS_REQUEST_HASH = "7bebf386e9b4167ad9d1c972a2be8055b9c6c944d57c572a0f689f30b66bdea0"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def fingerprint(spec: PromptSpec, schema: type[BaseModel] | None = None) -> str:
    """Hash of the system text, template and schema (default: the task's reference)."""
    if schema is None:
        schema = REFERENCE_SCHEMAS[spec.task]()
    payload = json.dumps(
        {
            "system": spec.system,
            "template": spec.template,
            "schema": schema.model_json_schema(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("spec", PROMPTS, ids=lambda s: s.task)
def test_prompt_version_is_pinned_to_its_text_and_schema(spec: PromptSpec) -> None:
    key = (spec.task, spec.version)
    assert key in FINGERPRINTS, f"new prompt version {key}: pin {fingerprint(spec)}"
    assert fingerprint(spec) == FINGERPRINTS[key], (
        f"{spec.task} changed without a version bump; bump the version and pin "
        f"{fingerprint(spec)}"
    )


def test_fingerprint_detects_a_change() -> None:
    changed = PromptSpec(
        task=STATEMENT_CANDIDATES.task,
        version=STATEMENT_CANDIDATES.version,
        system=STATEMENT_CANDIDATES.system + " ",
        template=STATEMENT_CANDIDATES.template,
        schema=STATEMENT_CANDIDATES.schema,
        max_tokens=STATEMENT_CANDIDATES.max_tokens,
    )
    assert fingerprint(changed) != FINGERPRINTS[(changed.task, changed.version)]

    key = (STATEMENT_CANDIDATES.task, STATEMENT_CANDIDATES.version)
    assert fingerprint(STATEMENT_CANDIDATES, StatementSet) != FINGERPRINTS[key]
    # A builder change fails the pin too.
    findings = (POSITION_FINDINGS.task, POSITION_FINDINGS.version)
    assert fingerprint(POSITION_FINDINGS, finding_list_schema(31)) != FINGERPRINTS[findings]
    positions = (PARTY_POSITIONS.task, PARTY_POSITIONS.version)
    assert fingerprint(PARTY_POSITIONS, position_list_schema(30, 11)) != FINGERPRINTS[positions]
    generate = (GENERATE_STATEMENTS.task, GENERATE_STATEMENTS.version)
    assert fingerprint(GENERATE_STATEMENTS, statement_set_schema(60, 81)) != FINGERPRINTS[generate]
    # The anchor bound is part of the pinned schema too.
    assert fingerprint(GENERATE_STATEMENTS, statement_set_schema(60, 80, 31)) != FINGERPRINTS[
        generate
    ]


def test_statement_candidates_request_is_byte_identical() -> None:
    # Its recorded calls must stay reusable by --resume-from (pipeline-output-bounds).
    assert STATEMENT_CANDIDATES.version == "v1"
    assert fingerprint(STATEMENT_CANDIDATES, STATEMENT_CANDIDATES.schema) == FINGERPRINTS[
        ("statement_candidates", "v1")
    ]
    request = candidate_request("[página 1]\nTexto")
    assert request.schema is CandidateList
    assert request_hash("fake", "fake-model", request) == CANDIDATE_REQUEST_HASH


def _pin_documents() -> tuple[DocumentPages, DocumentPages]:
    url = "https://example.org/a.pdf"
    return (
        DocumentPages(1, 10, [(1, "Texto")], url, SourceDocumentRole.MAIN),
        DocumentPages(1, 11, [(2, "Otro")], None, SourceDocumentRole.ADDITIONAL),
    )


def _pinned_position_requests() -> tuple[LLMRequest[Any], LLMRequest[Any]]:
    listed = statement_lines(["Afirmación uno", "Afirmación dos"])
    main, extra = _pin_documents()
    candidates = [_Candidate(1, 1, "Texto", 1, main), _Candidate(2, -1, "Otro", 2, extra)]
    return (
        findings_request(listed, "[página 1]\nTexto", 2),
        positions_request(listed, candidates, 2),
    )


def test_position_requests_are_byte_identical() -> None:
    # pipeline-verified-findings changes no request: same versions, same hashes.
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v1",
        "generate_statements": "v6",
        "position_findings": "v5",
        "party_positions": "v2",
    }
    findings, positions = _pinned_position_requests()
    assert request_hash("fake", "fake-model", findings) == FINDINGS_REQUEST_HASH
    assert request_hash("fake", "fake-model", positions) == POSITIONS_REQUEST_HASH


def test_a_verification_verdict_does_not_change_the_positions_request() -> None:
    # The party_positions request lists unverifiable candidates exactly like
    # verified ones, so its hash does not depend on the verdicts.
    listed = statement_lines(["Afirmación uno", "Afirmación dos"])
    main, extra = _pin_documents()
    missed = [
        _Candidate(1, 1, "Texto", 1, main, "not_found"),
        _Candidate(2, -1, "Otro", 2, extra, "other_page", 3),
    ]
    request = positions_request(listed, missed, 2)
    assert request_hash("fake", "fake-model", request) == POSITIONS_REQUEST_HASH


def test_prompt_versions_and_constants() -> None:
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v1",
        "generate_statements": "v6",
        "position_findings": "v5",
        "party_positions": "v2",
    }
    assert POSITION_FINDINGS.schema is FindingList
    assert POSITION_FINDINGS.max_tokens == 4096
    assert PARTY_POSITIONS.schema is PositionList
    assert PARTY_POSITIONS.max_tokens == 8192
    assert STATEMENT_CANDIDATES.schema is CandidateList
    assert STATEMENT_CANDIDATES.max_tokens == 4096
    assert GENERATE_STATEMENTS.schema is StatementSet
    assert GENERATE_STATEMENTS.max_tokens == 32768
    assert (POOL_MIN_STATEMENTS, POOL_MAX_STATEMENTS, POOL_TARGET_STATEMENTS) == (60, 80, 70)
    assert len(TOPICS) == 18 and len(set(TOPICS)) == 18
    assert TOPICS[0] == "economy" and TOPICS[-1] == "infrastructure_transport"


@pytest.mark.parametrize(
    "spec", [STATEMENT_CANDIDATES, GENERATE_STATEMENTS], ids=lambda s: s.task
)
def test_system_prompt_states_the_rules(spec: PromptSpec) -> None:
    for topic in TOPICS:
        assert topic in spec.system
    for rule in ("español de España", "Una sola proposición", "neutral", "5 puntos"):
        assert rule in spec.system


def test_reduce_prompt_adds_list_rules() -> None:
    assert "cuarta parte" in GENERATE_STATEMENTS.system
    assert "casi duplicadas" in GENERATE_STATEMENTS.system
    # The pool (v4): orientation-level Statements from the Party-balanced agenda.
    assert "lista amplia" in GENERATE_STATEMENTS.system
    assert "procedimiento automático" in GENERATE_STATEMENTS.system
    assert "se pronuncien varios programas" not in GENERATE_STATEMENTS.system
    # The count lives only in the template, so it cannot contradict the range.
    assert str(POOL_TARGET_STATEMENTS) not in GENERATE_STATEMENTS.system
    assert "afirmaciones en total" not in GENERATE_STATEMENTS.system
    for field in (
        "{count}", "{min_count}", "{max_count}", "{anchors}", "{note_min}", "{note_max}",
        "{evaluative_words}",
    ):
        assert field in GENERATE_STATEMENTS.template
    assert "{candidates}" in GENERATE_STATEMENTS.template
    assert "{chunk}" in STATEMENT_CANDIDATES.template


# The exact v6 system text (pipeline-statement-clarity-context, Technical Approach
# section 2): v5 with the clarity rules, the anchors and the context note block.
# ``_COMMON_RULES`` is shared with statement_candidates and stays unchanged.
GENERATE_STATEMENTS_V6_RULE_LINES = (
    "- Cada afirmación se entiende por sí sola, sin conocer la legislación ni la política "
    "vigentes: di en qué consiste lo que se propone. Nunca hables de \"la política "
    "actual\", \"el modelo vigente\" o \"la ley actual\" sin decir cuál es ni qué "
    "establece.",
    "- Expresa la medida por su contenido y en positivo, de modo que estar de acuerdo "
    "signifique querer esa medida: en lugar de pedir que se derogue o suprima una ley, una "
    "reforma o una institución, di lo que debe regir o hacerse (por ejemplo, «Debe poder "
    "limitarse el precio del alquiler en las zonas donde es más alto» y no «Debe derogarse "
    "la Ley de Vivienda de 2023, que permite limitar el precio del alquiler»). Usa derogar, "
    "suprimir o eliminar solo cuando la propuesta no tenga otro contenido que hacer "
    "desaparecer esa norma o institución, y entonces nómbrala.",
    "- Sin dobles negaciones: no combines «no», «nunca» o «sin» con verbos como prohibir, "
    "impedir, suprimir, eliminar o derogar.",
    "- Lenguaje llano: frases cortas y palabras de uso común. Si una afirmación necesita un "
    "término técnico o el nombre de una ley, un plan o un organismo, la nota de contexto lo "
    "explica.",
    "- Nunca dejes una regla abstracta sin decir qué supone en la práctica: «Por cada nueva "
    "regulación que afecte a las empresas deben derogarse dos normas existentes» no se "
    "entiende sin saber qué normas ni para qué; di el objetivo de la medida (por ejemplo, "
    "reducir el número de normas que deben cumplir las empresas).",
    "- Varía el sentido de las afirmaciones: no todas deben proponer aumentar o ampliar "
    "algo; usa también reducir o limitar cuando así lo planteen las candidatas.",
    "- Basa cada afirmación solo en las candidatas y en las afirmaciones anteriores: no "
    "añadas temas ni propuestas que no aparezcan en ellas.",
    "- Los votantes ya conocen las afirmaciones anteriores. Para cada una, incluye en la "
    "lista una afirmación con la misma orientación, redactada de nuevo con estas reglas, y "
    "pon su número en `anchor`; si une dos políticas, divídela en dos afirmaciones con el "
    "mismo `anchor`. Las demás afirmaciones llevan `anchor` nulo.",
    "Reglas para la nota de contexto (`context_note`) de cada afirmación:",
    "- Una o dos frases que explican de forma neutral lo que un votante podría no conocer "
    "para entender la afirmación: qué es la ley, la reforma, el plan, la institución, el "
    "organismo, la sigla o el término técnico que nombra (nombre oficial, año y qué "
    "establece o hace). Si no nombra ninguno, explica brevemente el concepto principal.",
    "- Si un nombre es un apodo del debate público, da el nombre oficial y di que se la "
    "conoce así.",
    "- Solo hechos descriptivos: sin valoraciones, sin argumentos a favor o en contra, sin "
    "efectos previstos, sin la posición de nadie y sin nombres de partidos, de políticos ni "
    "de gobiernos.",
    "- No repitas la afirmación ni añadas propuestas.",
)

GENERATE_STATEMENTS_V6_SYSTEM = (
    "Eres un analista político que prepara un cuestionario de orientación de voto para "
    "unas elecciones generales en España. Recibes afirmaciones candidatas extraídas, en "
    "igual número, de los programas electorales de varias candidaturas, y las afirmaciones "
    "del cuestionario publicado anteriormente para estas elecciones, si lo hay; redactas a "
    "partir de ellas una lista amplia de afirmaciones; después, un procedimiento "
    "automático elegirá entre ellas las del cuestionario.\n\n"
    f"{_COMMON_RULES}\n"
    "Reglas para la lista:\n"
    "- Cada afirmación expresa una orientación política con una dirección clara (por "
    "ejemplo, subir o bajar un impuesto, ampliar o reducir un servicio público, más o menos "
    "peso de una fuente de energía), no una medida de detalle: sin cifras, porcentajes ni "
    "plazos salvo que sean el núcleo de la propuesta.\n"
    + "\n".join(GENERATE_STATEMENTS_V6_RULE_LINES[0:5])
    + "\n"
    "- Agrupa en una misma orientación las candidatas de programas distintos que van en esa "
    "dirección o en la contraria, para que el mayor número posible de programas se pueda "
    "situar en ella.\n"
    "- Elige orientaciones en las que los programas discrepen; evita las que casi cualquier "
    "programa suscribiría.\n"
    + "\n".join(GENERATE_STATEMENTS_V6_RULE_LINES[5:7])
    + "\n"
    "- Cubre los temas de forma amplia: ningún tema debe superar aproximadamente una cuarta "
    "parte de la lista.\n"
    "- Sin afirmaciones casi duplicadas.\n"
    + "\n".join(GENERATE_STATEMENTS_V6_RULE_LINES[7:])
)

FINDINGS_V3_NEW_RULES = (
    "- Una propuesta concreta del fragmento que va claramente en la dirección de una "
    "afirmación, o en la contraria, cuenta como tratarla de forma explícita: la posición es "
    "de acuerdo si va en esa dirección y en desacuerdo si va en la contraria, y la cita debe "
    "contener esa propuesta.\n"
    "- Que el fragmento no mencione un asunto no es una posición: no informes de esa "
    "afirmación."
)


def test_reduce_prompt_v6_states_the_clarity_anchor_and_note_rules() -> None:
    # pipeline-statement-clarity-context, scenario 5: every rule line verbatim.
    for line in GENERATE_STATEMENTS_V6_RULE_LINES:
        assert line + "\n" in GENERATE_STATEMENTS.system + "\n", line
    assert GENERATE_STATEMENTS.system == GENERATE_STATEMENTS_V6_SYSTEM
    assert GENERATE_STATEMENTS.max_tokens == 32768
    # v5 lines that v6 replaces are gone.
    assert "nómbrala (por ejemplo, \"la reforma laboral de 2012\")" not in (
        GENERATE_STATEMENTS.system
    )
    assert "reducir, limitar o suprimir" not in GENERATE_STATEMENTS.system
    # The common rules are unchanged and still shared with statement_candidates.
    assert _COMMON_RULES in STATEMENT_CANDIDATES.system
    assert _COMMON_RULES in GENERATE_STATEMENTS.system


def test_reduce_template_v6_lists_anchors_and_note_limits() -> None:
    template = GENERATE_STATEMENTS.template
    assert (
        "{candidates}\n\n"
        "Afirmaciones del cuestionario publicado anteriormente (una por línea, con su "
        "número y su tema entre corchetes):\n\n{anchors}\n\nElabora una lista de"
    ) in template
    assert template.endswith(
        " Cada nota de contexto tiene entre {note_min} y {note_max} caracteres y no usa "
        "ninguna de estas palabras: {evaluative_words}."
    )


def test_findings_prompt_v3_counts_concrete_proposals_and_not_silence() -> None:
    system = POSITION_FINDINGS.system
    first = (
        "Reglas:\n- Informa solo de las afirmaciones que el fragmento trata de forma "
        "explícita. Nunca deduzcas una posición de la ideología general.\n"
    )
    # The two new lines come right after the unchanged first rule.
    assert first + FINDINGS_V3_NEW_RULES + "\n- La cita se copia literalmente" in system
    assert "Nunca deduzcas una posición de la ideología general." in system
    assert (
        "- La cita se copia literalmente de una sola página: sin parafrasear, sin "
        "puntos suspensivos y sin añadir texto." in system
    )


@pytest.mark.parametrize(
    "data",
    [
        {"text": "Subir el salario mínimo.", "topic": "wages"},
        {"text": "", "topic": "economy"},
        {"text": "   \n\t", "topic": "economy"},
        {"text": "x" * 301, "topic": "economy"},
        {"topic": "economy"},
        {"text": "Subir el salario mínimo."},
    ],
    ids=["bad-topic", "empty", "whitespace", "too-long", "no-text", "no-topic"],
)
def test_statement_draft_rejects(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StatementDraft.model_validate(data)


def test_statement_draft_accepts_limits_and_keeps_text_as_given() -> None:
    draft = StatementDraft.model_validate({"text": " " + "x" * 299, "topic": "housing"})
    assert draft.text == " " + "x" * 299


def test_candidate_list_limits() -> None:
    item = {"text": "Subir el salario mínimo.", "topic": "employment"}
    assert CandidateList.model_validate({"candidates": []}).candidates == []
    assert len(CandidateList.model_validate({"candidates": [item] * 12}).candidates) == 12
    with pytest.raises(ValidationError):
        CandidateList.model_validate({"candidates": [item] * 13})


def test_statement_set_limits() -> None:
    item = {
        "text": "Subir el salario mínimo.",
        "topic": "employment",
        "context_note": "El salario mínimo es la retribución más baja fijada por ley.",
        "anchor": None,
    }
    with pytest.raises(ValidationError):
        StatementSet.model_validate({"statements": []})
    assert len(StatementSet.model_validate({"statements": [item] * 80}).statements) == 80
    with pytest.raises(ValidationError):
        StatementSet.model_validate({"statements": [item] * 81})


# Party Position prompts and schemas.


def test_position_prompts_state_their_rules() -> None:
    for spec in (POSITION_FINDINGS, PARTY_POSITIONS):
        assert "-2 totalmente en desacuerdo" in spec.system
        assert "2 totalmente de acuerdo" in spec.system
        assert "{statements}" in spec.template
    findings = POSITION_FINDINGS.system
    assert "de forma explícita" in findings
    assert "Nunca deduzcas una posición de la ideología general" in findings
    assert "literalmente de una sola página" in findings
    assert "sin parafrasear, sin puntos suspensivos y sin añadir texto" in findings
    assert "[página N]" in findings
    assert "lista vacía" in findings
    assert "{chunk}" in POSITION_FINDINGS.template
    reduce = PARTY_POSITIONS.system
    assert "omite la afirmación" in reduce
    assert "no tiene posición" in reduce
    assert "programa principal (el programa conjunto de la coalición)" in reduce
    assert "Si se contradicen, prevalece el programa principal" in reduce
    assert "Nunca inventes una candidata" in reduce
    assert "{candidates}" in PARTY_POSITIONS.template


def test_position_prompts_name_no_party() -> None:
    for spec in (POSITION_FINDINGS, PARTY_POSITIONS):
        for name, short in PARTIES:
            assert name not in spec.system + spec.template
            assert short not in spec.system + spec.template


_FINDING = {"statement": 1, "value": 2, "quote": "Bajaremos el IVA.", "page": 1}


@pytest.mark.parametrize(
    "change",
    [
        {"value": 3},
        {"value": -3},
        {"quote": ""},
        {"quote": "  \n\t"},
        {"quote": "x" * 501},
        {"page": 0},
        {"statement": 0},
        {"value": None},
    ],
    ids=["value-3", "value-minus-3", "empty-quote", "blank-quote", "long-quote", "page-0",
         "statement-0", "no-value"],
)
def test_finding_rejects(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate(_FINDING | change)


def test_finding_keeps_the_quote_as_given_and_accepts_limits() -> None:
    finding = Finding.model_validate(_FINDING | {"quote": " " + "x" * 499, "value": -2})
    assert finding.quote == " " + "x" * 499
    assert finding.value == -2


def test_finding_list_limits() -> None:
    assert FindingList.model_validate({"findings": []}).findings == []
    assert len(FindingList.model_validate({"findings": [_FINDING] * 80}).findings) == 80
    with pytest.raises(ValidationError):
        FindingList.model_validate({"findings": [_FINDING] * 81})


_CHOICE = {"statement": 1, "value": 0, "evidence": 1}


@pytest.mark.parametrize(
    "change",
    [{"value": 3}, {"evidence": 0}, {"statement": 0}, {"value": 1.5}],
    ids=["value-3", "evidence-0", "statement-0", "fractional-value"],
)
def test_position_choice_rejects(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PositionChoice.model_validate(_CHOICE | change)


def test_position_list_limits() -> None:
    assert PositionList.model_validate({"positions": []}).positions == []
    assert len(PositionList.model_validate({"positions": [_CHOICE] * 80}).positions) == 80
    with pytest.raises(ValidationError):
        PositionList.model_validate({"positions": [_CHOICE] * 81})


# Bounded schema builders (pipeline-output-bounds).

_DRAFT = {
    "text": "Subir el salario mínimo.",
    "topic": "employment",
    "context_note": "El salario mínimo es la retribución más baja fijada por ley.",
    "anchor": None,
}


def test_statement_set_schema_bounds_the_count() -> None:
    schema = statement_set_schema(25, 35)
    for n in (25, 30, 35):
        assert len(schema.model_validate({"statements": [_DRAFT] * n}).statements) == n
    for n in (24, 36, 38, 44):
        with pytest.raises(ValidationError):
            schema.model_validate({"statements": [_DRAFT] * n})
    statements = schema.model_json_schema()["properties"]["statements"]
    assert statements["minItems"] == 25 and statements["maxItems"] == 35


def test_statement_set_schema_bounds_the_anchor() -> None:
    # pipeline-statement-clarity-context, scenarios 1 and 2.
    schema = statement_set_schema(1, 3, 32)
    for anchor in (None, 1, 32):
        schema.model_validate({"statements": [_DRAFT | {"anchor": anchor}]})
    for anchor in (0, 33, -1):
        with pytest.raises(ValidationError):
            schema.model_validate({"statements": [_DRAFT | {"anchor": anchor}]})
    item = schema.model_json_schema()["$defs"]["PoolStatement"]
    assert item["required"] == ["text", "topic", "context_note", "anchor"]
    assert item["properties"]["anchor"] == {
        "anyOf": [{"maximum": 32, "minimum": 1, "type": "integer"}, {"type": "null"}],
        "title": "Anchor",
    }
    assert item["properties"]["context_note"]["maxLength"] == CONTEXT_NOTE_SCHEMA_MAX == 500

    without = statement_set_schema(1, 3)
    assert without is statement_set_schema(1, 3, 0)
    without.model_validate({"statements": [_DRAFT]})
    with pytest.raises(ValidationError):
        without.model_validate({"statements": [_DRAFT | {"anchor": 1}]})
    assert without.model_json_schema()["$defs"]["PoolStatement"]["properties"]["anchor"] == {
        "title": "Anchor", "type": "null"
    }


@pytest.mark.parametrize(
    "change",
    [
        {"context_note": ""},
        {"context_note": " \n\t"},
        {"context_note": "x" * 501},
        {"anchor": 1.5},
    ],
    ids=["empty-note", "blank-note", "long-note", "fractional-anchor"],
)
def test_pool_statement_rejects(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        statement_set_schema(1, 3, 5).model_validate({"statements": [_DRAFT | change]})


@pytest.mark.parametrize("missing", ["context_note", "anchor"])
def test_pool_statement_requires_note_and_anchor(missing: str) -> None:
    item = {k: v for k, v in _DRAFT.items() if k != missing}
    with pytest.raises(ValidationError):
        statement_set_schema(1, 3, 5).model_validate({"statements": [item]})


def test_pool_statement_keeps_the_note_as_given() -> None:
    note = "  La CIE … \n"
    parsed = statement_set_schema(1, 3).model_validate(
        {"statements": [_DRAFT | {"context_note": note}]}
    )
    assert parsed.statements[0].context_note == note


def test_finding_list_schema_bounds_the_statement() -> None:
    schema = finding_list_schema(30)
    for n in (1, 30):
        schema.model_validate({"findings": [_FINDING | {"statement": n}]})
    for n in (0, 31, 101):
        with pytest.raises(ValidationError):
            schema.model_validate({"findings": [_FINDING | {"statement": n}]})
    with pytest.raises(ValidationError):
        schema.model_validate({"findings": [_FINDING] * 81})
    json_schema = schema.model_json_schema()
    assert json_schema["$defs"]["Finding"]["properties"]["statement"] == {
        "maximum": 30, "minimum": 1, "title": "Statement", "type": "integer"
    }
    assert json_schema["properties"]["findings"]["maxItems"] == 80


def test_position_list_schema_bounds_statement_evidence_and_length() -> None:
    schema = position_list_schema(30, 10)
    choices = [_CHOICE | {"statement": n, "evidence": 10} for n in range(1, 31)]
    assert len(schema.model_validate({"positions": choices}).positions) == 30
    for change in ({"statement": 0}, {"statement": 31}, {"evidence": 0}, {"evidence": 11}):
        with pytest.raises(ValidationError):
            schema.model_validate({"positions": [_CHOICE | change]})
    with pytest.raises(ValidationError):
        schema.model_validate({"positions": [_CHOICE] * 31})
    # Repeats pass the schema; extraction rejects them.
    assert len(schema.model_validate({"positions": [_CHOICE] * 2}).positions) == 2
    json_schema = schema.model_json_schema()
    choice = json_schema["$defs"]["PositionChoice"]["properties"]
    assert choice["statement"]["maximum"] == 30
    assert choice["evidence"] == {
        "maximum": 10, "minimum": 1, "title": "Evidence", "type": "integer"
    }
    assert json_schema["properties"]["positions"]["maxItems"] == 30


@pytest.mark.parametrize(
    ("bounded", "base"),
    [
        (lambda: statement_set_schema(25, 35), StatementSet),
        (lambda: finding_list_schema(30), FindingList),
        (lambda: position_list_schema(30, 10), PositionList),
    ],
    ids=["statement_set", "finding_list", "position_list"],
)
def test_bounded_schema_keeps_the_base_name_and_is_cached(bounded, base) -> None:
    schema = bounded()
    assert issubclass(schema, base)
    assert schema.__name__ == base.__name__
    assert schema.__doc__ == base.__doc__
    json_schema = schema.model_json_schema()
    assert json_schema["title"] == base.model_json_schema()["title"]
    assert json_schema["description"] == base.model_json_schema()["description"]
    assert bounded() is schema


def test_bounded_item_types_keep_their_base_names() -> None:
    finding = finding_list_schema(30).model_json_schema()["$defs"]["Finding"]
    assert finding["title"] == "Finding"
    assert finding["description"] == Finding.__doc__
    choice = position_list_schema(30, 10).model_json_schema()["$defs"]["PositionChoice"]
    assert choice["title"] == "PositionChoice"
    assert choice["description"] == PositionChoice.__doc__


@pytest.mark.parametrize(
    "build",
    [
        lambda: statement_set_schema(0, 35),
        lambda: statement_set_schema(25, 0),
        lambda: statement_set_schema(36, 35),
        lambda: statement_set_schema(True, 35),
        lambda: statement_set_schema(25.0, 35),
        lambda: statement_set_schema(25, 35, -1),
        lambda: statement_set_schema(25, 35, True),
        lambda: finding_list_schema(0),
        lambda: finding_list_schema(-1),
        lambda: position_list_schema(0, 10),
        lambda: position_list_schema(30, 0),
    ],
    ids=["set-min-0", "set-max-0", "set-min-above-max", "set-bool", "set-float",
         "set-anchors-negative", "set-anchors-bool",
         "findings-0", "findings-negative", "positions-n-0", "positions-k-0"],
)
def test_builders_reject_invalid_bounds(build) -> None:
    with pytest.raises(ValueError):
        build()
