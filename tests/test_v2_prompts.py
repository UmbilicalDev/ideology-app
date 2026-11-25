"""The v2 prompts are pinned to their text and schema (statements-from-proposals).

To change a prompt: bump its ``version`` in ``pipeline/v2/prompts.py``, then
replace the entry below with the new (task, version) and the fingerprint
printed by the failing test. The legacy prompts are untouched: their
``PROMPT_VERSIONS`` do not list the v2 tasks.
"""

import hashlib
import json

import pytest
from pipeline_fixtures import offline_guard
from pydantic import BaseModel, ValidationError

from ideology_app.config import ValidationSettings
from ideology_app.pipeline import PROMPT_VERSIONS, PROMPTS, request_hash
from ideology_app.pipeline.v2.prompts import (
    PROPOSAL_POSITIONS,
    STATEMENT_DRAFTS,
    V2_PROMPT_VERSIONS,
    V2_PROMPTS,
    DraftInput,
    V2Prompt,
    draft_request,
    draft_set_schema,
    draft_target,
    position_request,
    position_set_schema,
)

FINGERPRINTS = {
    ("statement_drafts", "v1"): "65e7cbbf73c23328fb209ced3732cc259f01006bbf055122f1ada204b199c4aa",
    ("proposal_positions", "v1"): "d73457d36c872ed5493b251eb58212ed185945aa2c71dbea1cbca2d6f21b6c8f",
}
# request_hash("fake", "fake-model", <the requests of test_requests_are_byte_identical>).
DRAFT_REQUEST_HASH = "59286a5ca3e17620b507cb6ef432bef1327c24e7f3d33f94918bbba60ea440e6"
POSITION_REQUEST_HASH = "842455adaf0db4673b9c4e613d55ecc2896a1eecdd4d8e537c1921497b756312"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def fingerprint(prompt: V2Prompt, schema: type[BaseModel]) -> str:
    payload = json.dumps(
        {
            "system": prompt.system,
            "template": prompt.template,
            "max_tokens": prompt.max_tokens,
            "schema": schema.model_json_schema(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reference(prompt: V2Prompt) -> type[BaseModel]:
    if prompt is STATEMENT_DRAFTS:
        return draft_set_schema(7, 3)
    return position_set_schema(4, 6)


@pytest.mark.parametrize("prompt", V2_PROMPTS, ids=lambda p: p.task)
def test_prompts_are_pinned_to_their_text_and_schema(prompt: V2Prompt) -> None:
    key = (prompt.task, prompt.version)
    assert fingerprint(prompt, _reference(prompt)) == FINGERPRINTS[key], (
        f"pin {fingerprint(prompt, _reference(prompt))}"
    )


def test_versions_and_limits() -> None:
    assert V2_PROMPT_VERSIONS == {"statement_drafts": "v1", "proposal_positions": "v1"}
    assert (STATEMENT_DRAFTS.max_tokens, PROPOSAL_POSITIONS.max_tokens) == (16384, 4096)
    assert not set(V2_PROMPT_VERSIONS) & set(PROMPT_VERSIONS)
    assert [p.task for p in PROMPTS] == [
        "statement_candidates", "generate_statements", "position_findings", "party_positions",
    ]
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v2",
        "generate_statements": "v7",
        "position_findings": "v5",
        "party_positions": "v2",
    }


def test_fingerprint_detects_a_schema_change() -> None:
    assert fingerprint(STATEMENT_DRAFTS, draft_set_schema(7, 4)) != FINGERPRINTS[
        ("statement_drafts", "v1")
    ]


def test_requests_are_byte_identical() -> None:
    draft = draft_request(
        "housing",
        [DraftInput("Bajar el alquiler.", ("alquiler",)), DraftInput("Subir el IVA.")],
        ["Debe bajarse el alquiler."],
        ValidationSettings(),
    )
    assert request_hash("fake", "fake-model", draft) == DRAFT_REQUEST_HASH
    assert draft.prompt.startswith(
        "Tema: Vivienda\n\n"
        "Afirmaciones ya redactadas de este tema (una por línea, con su número):\n\n"
        "S1. Debe bajarse el alquiler.\n\n"
        "Propuestas (una por línea, con su número y sus etiquetas entre corchetes):\n\n"
        "P1. [alquiler] Bajar el alquiler.\nP2. Subir el IVA.\n\n"
        "Redacta unas 3 afirmaciones nuevas (como máximo 25)"
    )
    assert "entre 30 y 300 caracteres" in draft.prompt
    position = position_request(
        "economy", ["Deben bajarse los impuestos."], ["Bajar el IVA.", "Subir el IRPF."]
    )
    assert request_hash("fake", "fake-model", position) == POSITION_REQUEST_HASH
    assert position.prompt == (
        "Tema: Economía\n\n"
        "Afirmaciones del cuestionario (una por línea, con su número entre corchetes):\n\n"
        "[1] Deben bajarse los impuestos.\n\n"
        "Propuestas de la candidatura sobre este tema (una por línea, con su número):\n\n"
        "P1. Bajar el IVA.\nP2. Subir el IRPF.\n\n"
        "Indica la posición de la candidatura en cada afirmación que estas propuestas "
        "tratan, con las propuestas que la respaldan."
    )


def test_no_previous_and_one_line_text() -> None:
    request = draft_request(
        "economy", [DraftInput("Bajar\n  el   IVA.", ("a\nb",))], [], ValidationSettings()
    )
    assert "\n\n(ninguna)\n\n" in request.prompt
    assert "P1. [a b] Bajar el IVA." in request.prompt
    with pytest.raises(ValueError):
        draft_request("economy", [], [], ValidationSettings())
    with pytest.raises(ValueError):
        draft_request("nope", [DraftInput("x")], [], ValidationSettings())


@pytest.mark.parametrize(
    ("count", "target"), [(1, 3), (36, 3), (37, 4), (120, 10), (300, 25), (5000, 25)]
)
def test_draft_target(count: int, target: int) -> None:
    assert draft_target(count) == target


def test_draft_schema_bounds() -> None:
    schema = draft_set_schema(3, 2)
    ok = {
        "statements": [{"text": "T", "context_note": "N", "sources": [1, 3, 3]}],
        "additions": [{"statement": 2, "sources": [2]}],
    }
    assert schema.model_validate(ok).statements[0].sources == [1, 3, 3]
    for bad in (
        {"statements": [{"text": "T", "context_note": "N", "sources": [4]}], "additions": []},
        {"statements": [{"text": "T", "context_note": "N", "sources": []}], "additions": []},
        {"statements": [{"text": " ", "context_note": "N", "sources": [1]}], "additions": []},
        {"statements": [{"text": "T", "context_note": "N" * 501, "sources": [1]}], "additions": []},
        {"statements": [{"text": "T" * 301, "context_note": "N", "sources": [1]}], "additions": []},
        {"statements": [], "additions": [{"statement": 3, "sources": [1]}]},
        {"statements": [], "additions": [{"statement": 1, "sources": [1]}] * 3},
        {"statements": [{"text": "T", "context_note": "N", "sources": [1]}] * 26, "additions": []},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(bad)
    no_previous = draft_set_schema(3, 0)
    with pytest.raises(ValidationError):
        no_previous.model_validate(
            {"statements": [], "additions": [{"statement": 1, "sources": [1]}]}
        )
    assert draft_set_schema(3, 2) is schema
    for args in ((0, 1), (1, -1), (True, 0)):
        with pytest.raises(ValueError):
            draft_set_schema(*args)


def test_position_schema_bounds() -> None:
    schema = position_set_schema(2, 3)
    ok = {"positions": [{"statement": 2, "value": -2, "evidence": [3, 1]}]}
    assert schema.model_validate(ok).positions[0].evidence == [3, 1]
    for bad in (
        {"positions": [{"statement": 3, "value": 1, "evidence": [1]}]},
        {"positions": [{"statement": 1, "value": 3, "evidence": [1]}]},
        {"positions": [{"statement": 1, "value": 1, "evidence": []}]},
        {"positions": [{"statement": 1, "value": 1, "evidence": [4]}]},
        {"positions": [{"statement": 1, "value": 1, "evidence": [1, 1, 1, 1, 1, 1]}]},
        {"positions": [{"statement": 1, "value": 1, "evidence": [1]}] * 3},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(bad)
    with pytest.raises(ValueError):
        position_set_schema(0, 1)


def test_no_party_or_file_names_in_the_prompts() -> None:
    for prompt in V2_PROMPTS:
        for text in (prompt.system, prompt.template):
            assert "[página" not in text and ".md" not in text
