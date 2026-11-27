"""The ``proposal_extraction`` prompt is pinned to its text and schema (proposal-extraction).

To change the prompt: bump ``PROPOSAL_EXTRACTION.version``, then replace the
entry below with the new (task, version) and the fingerprint printed by the
failing test. Legacy prompts and ``PROMPT_VERSIONS`` are untouched.
"""

import hashlib
import json

import pytest
from pipeline_fixtures import offline_guard
from pydantic import ValidationError

from ideology_app.pipeline import PROMPT_VERSIONS, PROMPTS, request_hash
from ideology_app.proposals.extraction import build_chunks
from ideology_app.proposals.prompts import (
    CATEGORY_KEYS,
    PROPOSAL_EXTRACTION,
    ProposalList,
    proposal_list_schema,
    proposal_request,
)
from ideology_app.topic_catalog import TOPIC_CATALOG

FINGERPRINTS = {
    ("proposal_extraction", "v1"): "c041a45a4dd99ab29f86c065b2c84f3e56a0582a32d8d219baff765aed87ba01",
}
# request_hash("fake", "fake-model", proposal_request(build_chunks(["Texto", "Más"])[0])).
REQUEST_HASH = "a99eda15721a6069423eff58d954bd02f77d3bc7b6281fbe69827067b6428608"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def fingerprint(schema: type[ProposalList] | None = None) -> str:
    """Hash of the system text, template, max_tokens and the reference schema (pages 3..7)."""
    payload = json.dumps(
        {
            "system": PROPOSAL_EXTRACTION.system,
            "template": PROPOSAL_EXTRACTION.template,
            "max_tokens": PROPOSAL_EXTRACTION.max_tokens,
            "schema": (schema or proposal_list_schema(3, 7)).model_json_schema(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_prompt_version_is_pinned_to_its_text_and_schema() -> None:
    key = (PROPOSAL_EXTRACTION.task, PROPOSAL_EXTRACTION.version)
    assert key == ("proposal_extraction", "v1")
    assert PROPOSAL_EXTRACTION.max_tokens == 16384
    assert fingerprint() == FINGERPRINTS[key], f"pin {fingerprint()}"


def test_request_is_byte_identical() -> None:
    request = proposal_request(build_chunks(["Texto", "Más"])[0])
    assert request_hash("fake", "fake-model", request) == REQUEST_HASH


def test_fingerprint_detects_a_schema_change() -> None:
    assert fingerprint(proposal_list_schema(3, 8)) != FINGERPRINTS[("proposal_extraction", "v1")]


def test_legacy_prompts_are_unchanged() -> None:
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v2",
        "generate_statements": "v7",
        "position_findings": "v5",
        "party_positions": "v2",
    }
    assert "proposal_extraction" not in PROMPTS


def test_system_text_lists_every_category_in_catalog_order() -> None:
    system = PROPOSAL_EXTRACTION.system
    listing = ", ".join(f"`{e.key}` ({e.name})" for e in TOPIC_CATALOG)
    assert f"la principal primero; normalmente una: {listing}.\n" in system
    assert len(TOPIC_CATALOG) == 18 and CATEGORY_KEYS == tuple(e.key for e in TOPIC_CATALOG)
    for rule in (
        "extraes todas sus propuestas",
        "Cada punto de una lista es una propuesta distinta.",
        "sin elegir, resumir ni unir",
        "nunca extraigas un diagnóstico solo",
        "se copia literalmente del fragmento",
        "sin el marcador [página N]",
        "donde empieza el texto; el texto puede seguir en la página siguiente",
        "La página marcada «solo contexto»",
        "de cero a cinco etiquetas libres en español",
        "devuelve una lista vacía",
    ):
        assert rule in system, rule


def test_request_holds_only_page_text() -> None:
    pages = ["Primera página del programa.", "Segunda página."]
    chunk = build_chunks(pages)[0]

    request = proposal_request(chunk)

    assert request.task == "proposal_extraction"
    assert request.system == PROPOSAL_EXTRACTION.system
    assert request.max_tokens == 16384
    assert request.prompt == (
        "Fragmento de programa electoral (cada página va precedida de su marcador):\n\n"
        "[página 1]\nPrimera página del programa.\n\n[página 2]\nSegunda página.\n\n"
        "Extrae todas las propuestas de este fragmento."
    )
    assert request.schema is proposal_list_schema(1, 2)


def test_no_party_or_file_name_reaches_the_prompt() -> None:
    # The request is built from a chunk (page text only); nothing else is a parameter.
    chunk = build_chunks(["Medidas de vivienda."])[0]
    request = proposal_request(chunk)
    text = request.system + request.prompt
    for name in ("Partido", "PSOE", "PP", ".md", "party"):
        assert name not in text


def _item(**change: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": "Bajar el IVA.",
        "page": 3,
        "categories": ["economy"],
        "tags": ["iva"],
    }
    base.update(change)
    return {"proposals": [base]}


@pytest.mark.parametrize(
    "change",
    [
        {"page": 2},
        {"page": 8},
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 1501},
        {"categories": []},
        {"categories": ["economy", "housing", "health", "education"]},
        {"categories": ["vivienda"]},
        {"tags": ["a", "b", "c", "d", "e", "f"]},
        {"tags": [""]},
        {"tags": ["x" * 41]},
    ],
)
def test_schema_rejects(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        proposal_list_schema(3, 7).model_validate(_item(**change))


def test_schema_accepts_limits_and_keeps_values_as_given() -> None:
    schema = proposal_list_schema(3, 7)
    output = schema.model_validate(
        _item(text=" x" * 750, page=7, categories=["housing", "economy", "health"], tags=[])
    )
    assert output.proposals[0].text == " x" * 750
    assert schema.model_validate({"proposals": []}).proposals == []
    with pytest.raises(ValidationError):
        schema.model_validate({"proposals": [_item()["proposals"][0]] * 121})  # type: ignore[index]


def test_schema_builder_is_cached_and_checks_its_bounds() -> None:
    assert proposal_list_schema(3, 7) is proposal_list_schema(3, 7)
    assert proposal_list_schema(3, 7).__name__ == "ProposalList"
    for first, last in ((0, 1), (2, 1), (True, 2)):
        with pytest.raises(ValueError):
            proposal_list_schema(first, last)  # type: ignore[arg-type]
