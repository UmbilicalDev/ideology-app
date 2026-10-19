"""Prompt versions are pinned to their text and schema (Scenario 8), and schemas."""

import hashlib
import json

import pytest
from pipeline_fixtures import offline_guard
from pydantic import ValidationError

from ideology_app.pipeline import (
    GENERATE_STATEMENTS,
    PROMPT_VERSIONS,
    PROMPTS,
    STATEMENT_CANDIDATES,
    TARGET_STATEMENT_COUNT,
    TOPICS,
    CandidateList,
    PromptSpec,
    StatementDraft,
    StatementSet,
)

# To change a prompt: bump its version, then replace its entry here with the new
# (task, version) and the fingerprint printed by the failing test.
FINGERPRINTS = {
    ("statement_candidates", "v1"): "a2073f8c4dcc630a08056db3bef2f59f3e412532693fd2b364af902bbfbe1177",
    ("generate_statements", "v1"): "3c8431a896d5bfd1357d74b7bf3e474db4f00b8e5c14510e98406222010c2e39",
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
    assert PROMPT_VERSIONS == {"statement_candidates": "v1", "generate_statements": "v1"}
    assert STATEMENT_CANDIDATES.schema is CandidateList
    assert STATEMENT_CANDIDATES.max_tokens == 4096
    assert GENERATE_STATEMENTS.schema is StatementSet
    assert GENERATE_STATEMENTS.max_tokens == 8192
    assert TARGET_STATEMENT_COUNT == 30
    assert len(TOPICS) == 18 and len(set(TOPICS)) == 18
    assert TOPICS[0] == "economy" and TOPICS[-1] == "infrastructure_transport"


@pytest.mark.parametrize("spec", PROMPTS, ids=lambda s: s.task)
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
