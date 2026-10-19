"""Prompt versions are pinned to their text and schema (Scenario 8), and schemas."""

import hashlib
import json

import pytest
from pipeline_fixtures import PARTIES, offline_guard
from pydantic import ValidationError

from ideology_app.pipeline import (
    GENERATE_STATEMENTS,
    PARTY_POSITIONS,
    POSITION_FINDINGS,
    PROMPT_VERSIONS,
    PROMPTS,
    STATEMENT_CANDIDATES,
    TARGET_STATEMENT_COUNT,
    TOPICS,
    CandidateList,
    Finding,
    FindingList,
    PositionChoice,
    PositionList,
    PromptSpec,
    StatementDraft,
    StatementSet,
)

# To change a prompt: bump its version, then replace its entry here with the new
# (task, version) and the fingerprint printed by the failing test.
FINGERPRINTS = {
    ("statement_candidates", "v1"): "a2073f8c4dcc630a08056db3bef2f59f3e412532693fd2b364af902bbfbe1177",
    ("generate_statements", "v1"): "3c8431a896d5bfd1357d74b7bf3e474db4f00b8e5c14510e98406222010c2e39",
    ("position_findings", "v1"): "63888355b8d8d698510ab87764593a3be8a80fbbf242b2e7bd9489ffbc616fbe",
    ("party_positions", "v1"): "4d819d2a639b8bac9f3fff66a5a3201face47e53af45507cc9d036ec7b27b490",
}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def fingerprint(spec: PromptSpec) -> str:
    payload = json.dumps(
        {
            "system": spec.system,
            "template": spec.template,
            "schema": spec.schema.model_json_schema(),
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

    other_schema = PromptSpec(
        task=STATEMENT_CANDIDATES.task,
        version=STATEMENT_CANDIDATES.version,
        system=STATEMENT_CANDIDATES.system,
        template=STATEMENT_CANDIDATES.template,
        schema=StatementSet,
        max_tokens=STATEMENT_CANDIDATES.max_tokens,
    )
    assert fingerprint(other_schema) != FINGERPRINTS[(changed.task, changed.version)]


def test_prompt_versions_and_constants() -> None:
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v1",
        "generate_statements": "v1",
        "position_findings": "v1",
        "party_positions": "v1",
    }
    assert POSITION_FINDINGS.schema is FindingList
    assert POSITION_FINDINGS.max_tokens == 4096
    assert PARTY_POSITIONS.schema is PositionList
    assert PARTY_POSITIONS.max_tokens == 8192
    assert STATEMENT_CANDIDATES.schema is CandidateList
    assert STATEMENT_CANDIDATES.max_tokens == 4096
    assert GENERATE_STATEMENTS.schema is StatementSet
    assert GENERATE_STATEMENTS.max_tokens == 8192
    assert TARGET_STATEMENT_COUNT == 30
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
    assert str(TARGET_STATEMENT_COUNT) in GENERATE_STATEMENTS.system
    assert "{count}" in GENERATE_STATEMENTS.template
    assert "{candidates}" in GENERATE_STATEMENTS.template
    assert "{chunk}" in STATEMENT_CANDIDATES.template


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
    item = {"text": "Subir el salario mínimo.", "topic": "employment"}
    with pytest.raises(ValidationError):
        StatementSet.model_validate({"statements": []})
    assert len(StatementSet.model_validate({"statements": [item] * 60}).statements) == 60
    with pytest.raises(ValidationError):
        StatementSet.model_validate({"statements": [item] * 61})


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
    assert len(FindingList.model_validate({"findings": [_FINDING] * 60}).findings) == 60
    with pytest.raises(ValidationError):
        FindingList.model_validate({"findings": [_FINDING] * 61})


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
    assert len(PositionList.model_validate({"positions": [_CHOICE] * 60}).positions) == 60
    with pytest.raises(ValidationError):
        PositionList.model_validate({"positions": [_CHOICE] * 61})
