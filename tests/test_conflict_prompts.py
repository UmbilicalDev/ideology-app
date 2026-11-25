"""The ``proposal_conflict_check`` prompt is pinned to its text and schema (proposal-conflicts).

To change the prompt: bump ``PROPOSAL_CONFLICT_CHECK.version``, then replace
the entry below with the new (task, version) and the fingerprint printed by
the failing test. ``proposal_extraction`` and the legacy prompts are untouched.
Also covers the pure request building: buckets per category in catalog order
and the 40k / 20k slicing (C10).
"""

import hashlib
import json

import pytest
from pipeline_fixtures import offline_guard
from pydantic import ValidationError

from ideology_app.pipeline import PROMPT_VERSIONS, PROMPTS, request_hash
from ideology_app.proposals.conflict_prompts import (
    CONFLICT_REQUEST_MAX_CHARS,
    CONFLICT_SLICE_MAX_CHARS,
    PROPOSAL_CONFLICT_CHECK,
    ConflictProposal,
    ContradictionList,
    conflict_list_schema,
    conflict_request,
    conflict_requests,
)
from ideology_app.proposals.prompts import PROPOSAL_EXTRACTION
from ideology_app.topic_catalog import TOPIC_CATALOG

FINGERPRINTS = {
    ("proposal_conflict_check", "v1"): "4ca714fdfca7c91d17aeebc48bbb36ca856338e17c77c0f5e83568e508f31294",
}
# request_hash("fake", "fake-model", conflict_request("housing", ["Bajar el IVA."],
# ["Subir el IVA.", "Otra."])).
REQUEST_HASH = "3cd4d9fca3249632a5be6bdea51265b85ca489a9767965a255484b76bc1a2074"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def fingerprint(schema: type[ContradictionList] | None = None) -> str:
    """Hash of the system text, template, max_tokens and the reference schema (3 x 7)."""
    payload = json.dumps(
        {
            "system": PROPOSAL_CONFLICT_CHECK.system,
            "template": PROPOSAL_CONFLICT_CHECK.template,
            "max_tokens": PROPOSAL_CONFLICT_CHECK.max_tokens,
            "schema": (schema or conflict_list_schema(3, 7)).model_json_schema(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_prompt_version_is_pinned_to_its_text_and_schema() -> None:
    key = (PROPOSAL_CONFLICT_CHECK.task, PROPOSAL_CONFLICT_CHECK.version)
    assert key == ("proposal_conflict_check", "v1")
    assert PROPOSAL_CONFLICT_CHECK.max_tokens == 4096
    assert fingerprint() == FINGERPRINTS[key], f"pin {fingerprint()}"


def test_request_is_byte_identical() -> None:
    request = conflict_request("housing", ["Bajar el IVA."], ["Subir el IVA.", "Otra."])
    assert request_hash("fake", "fake-model", request) == REQUEST_HASH
    assert request.prompt == (
        "Tema: Vivienda\n\n"
        "Propuestas del documento A:\nA1. Bajar el IVA.\n\n"
        "Propuestas del documento B:\nB1. Subir el IVA.\nB2. Otra.\n\n"
        "Indica los pares de propuestas de A y B que se contradicen."
    )


def test_fingerprint_detects_a_schema_change() -> None:
    assert fingerprint(conflict_list_schema(3, 8)) != FINGERPRINTS[
        ("proposal_conflict_check", "v1")
    ]


def test_other_prompts_are_unchanged() -> None:
    assert PROMPT_VERSIONS == {
        "statement_candidates": "v2",
        "generate_statements": "v7",
        "position_findings": "v5",
        "party_positions": "v2",
    }
    assert "proposal_conflict_check" not in PROMPTS
    assert (PROPOSAL_EXTRACTION.task, PROPOSAL_EXTRACTION.version) == ("proposal_extraction", "v1")


def test_schema_bounds_and_single_line_explanation() -> None:
    schema = conflict_list_schema(2, 3)
    assert conflict_list_schema(2, 3) is schema
    ok = {"contradictions": [{"a": 2, "b": 3, "explanation": "Una baja el IVA y otra lo sube."}]}
    assert schema.model_validate(ok).contradictions[0].a == 2
    assert schema.model_validate({"contradictions": []}).contradictions == []
    for bad in (
        {"a": 3, "b": 1, "explanation": "x"},
        {"a": 0, "b": 1, "explanation": "x"},
        {"a": 1, "b": 4, "explanation": "x"},
        {"a": 1, "b": 1, "explanation": ""},
        {"a": 1, "b": 1, "explanation": "dos\nlíneas"},
        {"a": 1, "b": 1, "explanation": " espacio"},
        {"a": 1, "b": 1, "explanation": "x" * 301},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate({"contradictions": [bad]})
    too_many = [{"a": 1, "b": 1, "explanation": "x"}] * 41
    with pytest.raises(ValidationError):
        schema.model_validate({"contradictions": too_many})
    for bad_length in (0, True, 1.5):
        with pytest.raises(ValueError):
            conflict_list_schema(bad_length, 1)  # type: ignore[arg-type]


def test_prompt_shows_only_category_and_texts() -> None:
    request = conflict_request("economy", ["Texto\ncon  saltos."], ["Otro."])
    assert "Tema: Economía" in request.prompt
    assert "A1. Texto con saltos." in request.prompt
    for word in ("Partido", ".md", "página", "PSOE", "PP"):
        assert word not in request.prompt
        assert word not in request.system
    with pytest.raises(ValueError, match="unknown category"):
        conflict_request("weather", ["a"], ["b"])


def _p(ordinal: int, text: str, *categories: str) -> ConflictProposal:
    return ConflictProposal(ordinal, text, categories)


def test_buckets_per_category_in_catalog_order() -> None:
    side_a = [_p(1, "Vivienda A.", "housing", "economy"), _p(2, "Sanidad A.", "health")]
    side_b = [_p(1, "Economía B.", "economy"), _p(2, "Vivienda B.", "housing"), _p(3, "Clima.", "environment")]

    requests = conflict_requests(side_a, side_b)

    order = [entry.key for entry in TOPIC_CATALOG]
    assert [r.category for r in requests] == sorted(["housing", "economy"], key=order.index)
    assert [(r.ordinals_a, r.ordinals_b) for r in requests] == [((1,), (2,)), ((1,), (1,))]
    assert conflict_requests(side_a, []) == []


def test_large_buckets_are_sliced_into_every_pair() -> None:
    assert (CONFLICT_REQUEST_MAX_CHARS, CONFLICT_SLICE_MAX_CHARS) == (40_000, 20_000)
    text = "x" * 9_000
    side_a = [_p(n, text, "housing") for n in range(1, 6)]  # 45,000: slices [1,2], [3,4], [5]
    side_b = [_p(1, "y" * 25_000, "housing"), _p(2, "z", "housing")]  # [1] over the limit, [2]

    requests = conflict_requests(side_a, side_b)

    assert [(r.ordinals_a, r.ordinals_b) for r in requests] == [
        ((1, 2), (1,)), ((1, 2), (2,)),
        ((3, 4), (1,)), ((3, 4), (2,)),
        ((5,), (1,)), ((5,), (2,)),
    ]
    small = conflict_requests(side_a[:2], [_p(1, "y" * 22_000, "housing")])
    assert [(r.ordinals_a, r.ordinals_b) for r in small] == [((1, 2), (1,))]
