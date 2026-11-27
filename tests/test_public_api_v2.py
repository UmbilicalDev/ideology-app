"""public-dataset-api-v2: the Constituency routes of the read-only API (scenarios 1-10).

A hand-inserted v2 Dataset Version (``api_v2_fixtures``) for exact bodies,
and one end-to-end v2 run (``v2_fixtures``, FakeProvider only) whose served
values are recomputed with ``effective_value``. Sockets are blocked.
"""

import datetime as dt
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from api_v2_fixtures import (
    AI_TEXT,
    ALFA_URL,
    CANDIDATURES,
    CREATED_AT,
    GAMMA_URL,
    LOGO_SHA,
    POSITIONS,
    PROPOSALS,
    REWORDED_TEXT,
    REWORDING_EXPLANATION,
    REWORDING_REASON,
    V2_VERSION,
    add_version,
    seed_v2_version,
)
from fastapi.testclient import TestClient
from pipeline_fixtures import offline_guard
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from ideology_app.api.http_cache import etag_for
from ideology_app.config import GenerationMode
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.constituency_rules import counting_evidence, effective_value
from ideology_app.db import session_scope
from ideology_app.main import create_app
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    ElectionType,
    ModelGeneration,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunStatus,
    Proposal,
)
from ideology_app.party_logos import logo_version
from ideology_app.pipeline.v2.stored import dataset_version_problems
from ideology_app.topic_catalog import TOPIC_CATALOG

IMMUTABLE = "public, max-age=86400, immutable"
BASE = f"/api/v1/dataset-versions/{V2_VERSION}"
LOGO_URL = f"/api/v1/parties/1/logo?v={logo_version(LOGO_SHA)}"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def client_for(db_url: str) -> Iterator[Callable[[], TestClient]]:
    opened: list[TestClient] = []

    def _open() -> TestClient:
        client = TestClient(create_app(db_url))
        client.__enter__()
        opened.append(client)
        return client

    yield _open
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    seed_v2_version(migrated_engine)
    return migrated_engine


def compact(value: Any) -> bytes:
    """The bytes ``cached_json`` sends: compact, keys in contract order, UTF-8."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def proposal(proposal_id: int, document_id: int) -> dict[str, Any]:
    _, _, page, text, _ = PROPOSALS[proposal_id]
    url = {1: ALFA_URL, 4: GAMMA_URL}.get(document_id)
    return {"id": proposal_id, "text": text, "page": page, "url": url,
            "source_document_id": document_id}


def position(statement_id: int, value: int | str, ids: list[int]) -> dict[str, Any]:
    return {"statement_id": statement_id, "value": value, "evidence_proposal_ids": ids}


def statement(statement_id: int, rank: int) -> dict[str, Any]:
    texts = {
        101: (REWORDED_TEXT, "housing", "Nota sobre el alquiler."),
        102: ("Deben bajarse los impuestos a las empresas.", "economy", None),
        103: ("Debe ampliarse la vivienda pública.", "housing", "Nota sobre vivienda pública."),
        104: ("Debe subir el salario mínimo.", "economy", "Nota sobre el salario mínimo."),
    }
    text, topic, note = texts[statement_id]
    return {"id": statement_id, "rank": rank, "text": text, "topic": topic, "context_note": note}


ALFA = {"id": 1, "name": "Partido Alfa", "short_name": "PA", "logo_url": LOGO_URL}
BETA = {"id": 2, "name": "Bloque Beta", "short_name": "BB", "logo_url": None}
GAMMA = {"id": 3, "name": "Coalición Gamma", "short_name": "CG", "logo_url": None}
XARXA = {"id": 4, "name": "Xarxa Independent", "short_name": "XI", "reason": "no_manifesto"}
DELTA = {"id": 5, "name": "Unión Delta", "short_name": "UD", "reason": "discarded_at_review"}

EXPECTED_28 = {
    "dataset_version_id": V2_VERSION,
    "code": "28",
    "name": "Madrid",
    "available": True,
    "unavailable_reason": None,
    "offered_lengths": [4],
    "statements": [statement(101, 1), statement(104, 2), statement(102, 3), statement(103, 4)],
    "parties": [
        {
            **ALFA,
            # 101: rows [1 (01, 28, 31), 6 (31)]: only 1 counts in 28. 103 is neutral (0).
            "positions": [
                position(101, 2, [1]), position(104, 2, [3]),
                position(102, -1, [3]), position(103, 0, [2]),
            ],
            "evidence": [proposal(1, 1), proposal(2, 1), proposal(3, 1)],
        },
        {
            **BETA,
            # Proposal 5 backs two Statements and is listed once.
            "positions": [
                position(101, -2, [4]), position(104, -1, [7]),
                position(102, 2, [5]), position(103, 1, [5]),
            ],
            "evidence": [proposal(4, 2), proposal(5, 3), proposal(7, 2)],
        },
        {
            **GAMMA,
            # 104: no row; 102: stored no stance. The shared Proposal 5 is Gamma's document 4.
            "positions": [
                position(101, -1, [5]), position(104, "no_stance", []),
                position(102, "no_stance", []), position(103, -1, [5]),
            ],
            "evidence": [proposal(5, 4)],
        },
    ],
    "excluded_parties": [XARXA],
}

EXPECTED_31 = {
    "dataset_version_id": V2_VERSION,
    "code": "31",
    "name": "Navarra",
    "available": True,
    "unavailable_reason": None,
    "offered_lengths": [3],
    "statements": [statement(101, 1), statement(102, 2), statement(103, 3)],
    "parties": [
        {
            **ALFA,
            # Both Evidence rows of 101 count in 31, in rank order.
            "positions": [position(101, 2, [1, 6]), position(102, -1, [3]),
                          position(103, 0, [2])],
            "evidence": [proposal(1, 1), proposal(2, 1), proposal(3, 1), proposal(6, 1)],
        },
        {
            **BETA,
            # S5: 101's only Evidence (4) counts in 28, so Beta has no stance in 31.
            "positions": [position(101, "no_stance", []), position(102, 2, [5]),
                          position(103, 1, [5])],
            "evidence": [proposal(5, 3)],
        },
        {
            **GAMMA,
            "positions": [position(101, -1, [5]), position(102, "no_stance", []),
                          position(103, -1, [5])],
            "evidence": [proposal(5, 4)],
        },
    ],
    "excluded_parties": [DELTA],
}

EXPECTED_01 = {
    "dataset_version_id": V2_VERSION,
    "code": "01",
    "name": "Araba/Álava",
    "available": False,
    "unavailable_reason": "too_few_statements",
    "offered_lengths": [],
    "statements": [],
    "parties": [
        {**ALFA, "positions": [], "evidence": []},
        {**BETA, "positions": [], "evidence": []},
    ],
    "excluded_parties": [XARXA],
}


def new_route_paths() -> list[str]:
    return [
        f"{BASE}/constituencies",
        f"{BASE}/constituencies/28",
        f"{BASE}/constituencies/31",
        f"{BASE}/constituencies/01",
        f"{BASE}/constituencies/28/proposals/housing",
        f"{BASE}/constituencies/31/proposals/economy",
        f"{BASE}/constituencies/01/proposals/housing",
    ]


def test_fixture_is_consistent_for_db_check(seeded: Engine) -> None:
    with Session(seeded) as session:
        assert dataset_version_problems(session) == []


# --- Scenario 1: overview ------------------------------------------------------------------


def test_overview_lists_the_52_stored_rows_in_code_order(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    response = client.get(f"{BASE}/constituencies")

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE
    assert response.headers["etag"] == etag_for(response.content)
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert list(body) == ["id", "election_id", "created_at", "constituencies"]
    assert (body["id"], body["election_id"]) == (V2_VERSION, 1)
    assert body["created_at"] == CREATED_AT.strftime("%Y-%m-%dT%H:%M:%SZ")
    with Session(seeded) as session:
        stored = session.scalars(
            select(DatasetVersionConstituency)
            .where(DatasetVersionConstituency.dataset_version_id == V2_VERSION)
            .order_by(DatasetVersionConstituency.constituency_code)
        ).all()
    names = dict(CONSTITUENCIES)
    assert body["constituencies"] == [
        {
            "code": row.constituency_code,
            "name": names[row.constituency_code],
            "available": row.available,
            "unavailable_reason": row.unavailable_reason,
            "valid_statement_count": row.valid_statement_count,
            "offered_lengths": row.offered_lengths,
        }
        for row in stored
    ]
    assert [c["code"] for c in body["constituencies"]] == sorted(names)
    assert len(body["constituencies"]) == 52
    assert body["constituencies"][0] == {
        "code": "01", "name": "Araba/Álava", "available": False,
        "unavailable_reason": "too_few_statements", "valid_statement_count": 1,
        "offered_lengths": [],
    }
    assert {c["code"] for c in body["constituencies"] if c["available"]} == {"28", "31"}
    # No detail JSON (Non-Goal).
    assert "detail" not in response.text


def test_every_new_route_answers_304_to_its_etag(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    for path in new_route_paths():
        first = client.get(path)
        assert first.status_code == 200, path
        assert first.headers["cache-control"] == IMMUTABLE
        etag = first.headers["etag"]
        assert etag == etag_for(first.content) and len(etag) == 34
        for header in (etag, f"W/{etag}", "*"):
            again = client.get(path, headers={"If-None-Match": header})
            assert again.status_code == 304, (path, header)
            assert again.content == b"" and again.headers["etag"] == etag
            assert again.headers["cache-control"] == IMMUTABLE
        assert client.get(path, headers={"If-None-Match": '"nope"'}).content == first.content


# --- Scenarios 2-4: questionnaires ------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"), [("28", EXPECTED_28), ("31", EXPECTED_31), ("01", EXPECTED_01)]
)
def test_exact_questionnaire_bodies(
    seeded: Engine, client_for: Callable[[], TestClient], code: str, expected: dict[str, Any]
) -> None:
    response = client_for().get(f"{BASE}/constituencies/{code}")

    assert response.status_code == 200
    assert response.json() == expected
    assert response.content == compact(expected)
    assert response.headers["etag"] == etag_for(compact(expected))


def test_parties_are_exactly_r_of_c_and_excluded_only_in_their_list(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    for code in ("01", "28", "31"):
        body = client.get(f"{BASE}/constituencies/{code}").json()
        running = sorted(p for p, rows in CANDIDATURES.items() if (code, None) in rows)
        excluded = sorted(
            p for p, rows in CANDIDATURES.items() if any(c == code and r for c, r in rows)
        )
        assert [p["id"] for p in body["parties"]] == running
        assert [p["id"] for p in body["excluded_parties"]] == excluded
        # Every Party has the same keys; positions follow the statements order.
        for party in body["parties"]:
            assert list(party) == ["id", "name", "short_name", "logo_url", "positions",
                                   "evidence"]
            assert [p["statement_id"] for p in party["positions"]] == [
                s["id"] for s in body["statements"]
            ]
            listed = {e["id"] for e in party["evidence"]}
            cited = {i for p in party["positions"] for i in p["evidence_proposal_ids"]}
            assert listed == cited
            assert [e["id"] for e in party["evidence"]] == sorted(listed)
            for item in party["positions"]:
                assert (item["value"] == "no_stance") == (not item["evidence_proposal_ids"])


def test_every_served_value_is_effective_value_with_counting_evidence(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    # Scenario 3: recompute S5 from the stored rows for every available Constituency.
    client = client_for()
    with Session(seeded) as session:
        stored = {(p.party_id, p.statement_id): p for p in session.scalars(select(PartyPosition))}
        evidence: dict[int, list[tuple[int, list[str]]]] = {}
        for row in session.scalars(
            select(PartyPositionProposal).order_by(
                PartyPositionProposal.party_position_id, PartyPositionProposal.rank
            )
        ):
            evidence.setdefault(row.party_position_id, []).append(
                (row.proposal_id, row.constituencies)
            )
    checked = 0
    for code in ("28", "31"):
        for party in client.get(f"{BASE}/constituencies/{code}").json()["parties"]:
            for item in party["positions"]:
                row = stored.get((party["id"], item["statement_id"]))
                rows = [] if row is None else evidence.get(row.id, [])
                codes = [c for _, c in rows]
                value = effective_value(None if row is None else row.value, codes, code)
                assert item["value"] == ("no_stance" if value is None else value)
                expected = [] if value is None else [
                    rows[i][0] for i in counting_evidence(codes, code)
                ]
                assert item["evidence_proposal_ids"] == expected
                checked += 1
    assert checked == 3 * 4 + 3 * 3
    assert POSITIONS[(2, 101)] == (-2, [4])  # the fixture's S5 case


# --- Scenario 5: Proposals for the Comparador ---------------------------------------------


def test_exact_proposals_body_for_housing_in_28(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    response = client_for().get(f"{BASE}/constituencies/28/proposals/housing")

    expected = {
        "dataset_version_id": V2_VERSION,
        "code": "28",
        "category": "housing",
        "parties": [
            # 6 is set aside in 28 (counts only in 31); 2 carries housing as its first category.
            {"party_id": 1, "proposals": [proposal(1, 1), proposal(2, 1)]},
            # Counted order (document 2 before 3); 5 carries housing as its second category.
            {"party_id": 2, "proposals": [proposal(4, 2), proposal(5, 3)]},
            {"party_id": 3, "proposals": [proposal(5, 4)]},
        ],
    }
    assert response.status_code == 200
    assert response.json() == expected
    assert response.content == compact(expected)


def test_proposals_follow_scope_category_and_list_every_running_party(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()

    def ids(code: str, category: str) -> dict[int, list[int]]:
        body = client.get(f"{BASE}/constituencies/{code}/proposals/{category}").json()
        assert list(body) == ["dataset_version_id", "code", "category", "parties"]
        return {p["party_id"]: [x["id"] for x in p["proposals"]] for p in body["parties"]}

    assert ids("31", "housing") == {1: [1, 2, 6], 2: [5], 3: [5]}
    assert ids("31", "economy") == {1: [2, 3], 2: [5], 3: [5]}
    assert ids("28", "economy") == {1: [2, 3], 2: [7, 5], 3: [5]}
    # Unavailable Constituency: still served; Excluded Party 4 never listed.
    assert ids("01", "housing") == {1: [1, 2], 2: [5]}
    # A valid category nobody has: every running Party with an empty list.
    assert ids("28", "education") == {1: [], 2: [], 3: []}
    # A Constituency nobody runs in.
    assert ids("05", "housing") == {}


def test_every_catalog_key_is_a_valid_category(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    for entry in TOPIC_CATALOG:
        response = client.get(f"{BASE}/constituencies/28/proposals/{entry.key}")
        assert response.status_code == 200, entry.key


# --- Scenario 6: refusals -------------------------------------------------------------------


def _error(response: Any, code: str, message: str) -> None:
    assert response.status_code == 404
    assert response.json() == {"error": {"code": code, "message": message}}
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers


def test_generation_refusals_and_not_found(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    add_version(seeded, 3, generation=ModelGeneration.LEGACY,
                status=DatasetVersionStatus.SUPERSEDED)
    add_version(seeded, 11, generation=ModelGeneration.V2, status=DatasetVersionStatus.CANDIDATE)
    client = client_for()
    v2_message = (
        f"dataset version {V2_VERSION} is a v2 version; "
        f"read /api/v1/dataset-versions/{V2_VERSION}/constituencies"
    )
    _error(client.get(BASE), "dataset_version_is_v2", v2_message)
    _error(client.get("/api/v1/elections/1/published-dataset-version"),
           "dataset_version_is_v2", v2_message)
    assert client.get("/api/v1/dataset-versions/3").status_code == 200
    for suffix in ("/constituencies", "/constituencies/28", "/constituencies/28/proposals/housing"):
        _error(
            client.get(f"/api/v1/dataset-versions/3{suffix}"),
            "dataset_version_is_legacy",
            "dataset version 3 is a legacy version; read /api/v1/dataset-versions/3",
        )
        for unknown in (11, 999):  # candidate v2 and unknown: indistinguishable
            _error(
                client.get(f"/api/v1/dataset-versions/{unknown}{suffix}"),
                "dataset_version_not_found",
                f"dataset version {unknown} not found",
            )
    _error(client.get("/api/v1/dataset-versions/11"), "dataset_version_not_found",
           "dataset version 11 not found")
    _error(client.get(f"{BASE}/constituencies/00"), "constituency_not_found",
           "constituency 00 not found")
    _error(client.get(f"{BASE}/constituencies/99/proposals/housing"), "constituency_not_found",
           "constituency 99 not found")
    _error(client.get(f"{BASE}/constituencies/28/proposals/nope"), "category_not_found",
           "category nope not found")
    for bad in ("abc", "1", "281", "2a", "%2028"):
        assert client.get(f"{BASE}/constituencies/{bad}").status_code == 422, bad
        assert client.get(f"{BASE}/constituencies/{bad}/proposals/housing").status_code == 422
    for bad in ("Housing", "housing-1", "a" * 41, "vivienda%20"):
        assert client.get(f"{BASE}/constituencies/28/proposals/{bad}").status_code == 422, bad
    for bad in ("abc", "0", "2147483648"):
        assert client.get(f"/api/v1/dataset-versions/{bad}/constituencies").status_code == 422
    assert client.get(f"{BASE}/constituencies/00", headers={"If-None-Match": "*"}).status_code == 404


# --- Scenario 7: legacy bodies unchanged next to a v2 version -------------------------------


def test_legacy_body_and_etag_are_unchanged_by_a_v2_version_in_the_database(
    migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    from test_public_api import seed_exact_version

    seed_exact_version(migrated_engine)
    client = client_for()
    before = client.get("/api/v1/dataset-versions/1")
    published_before = client.get("/api/v1/elections/1/published-dataset-version")
    with session_scope(migrated_engine) as session:
        session.add(
            Election(id=2, country="ES", type=ElectionType.GENERAL, date=dt.date(2026, 11, 29),
                     name="Generales 2026", status=ElectionStatus.ACTIVE)
        )
        session.flush()
        session.add(
            PipelineRun(id=2, election_id=2, status=PipelineRunStatus.PASSED,
                        llm_provider="fake", llm_model="fake-model",
                        generation_mode=GenerationMode.PRECOMPUTED, prompt_versions={},
                        model_generation=ModelGeneration.V2)
        )
        session.flush()
        session.add(
            DatasetVersion(id=2, election_id=2, pipeline_run_id=2,
                           status=DatasetVersionStatus.PUBLISHED, created_at=CREATED_AT,
                           model_generation=ModelGeneration.V2)
        )
    after = client.get("/api/v1/dataset-versions/1")
    published_after = client.get("/api/v1/elections/1/published-dataset-version")

    assert before.status_code == after.status_code == 200
    assert after.content == before.content
    assert after.headers["etag"] == before.headers["etag"]
    assert published_after.content == published_before.content
    assert client.get("/api/v1/dataset-versions/2").json()["error"]["code"] == (
        "dataset_version_is_v2"
    )


# --- Scenario 8: Elections --------------------------------------------------------------------


def test_election_generation_is_appended_last_and_matches_the_published_id(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    with session_scope(seeded) as session:
        session.add(
            Election(id=2, country="ES", type=ElectionType.GENERAL, date=dt.date(2023, 7, 23),
                     name="Generales 2023", status=ElectionStatus.ACTIVE)
        )
        session.add(
            Election(id=3, country="ES", type=ElectionType.GENERAL, date=dt.date(2019, 11, 10),
                     name="Generales 2019", status=ElectionStatus.ACTIVE)
        )
        session.flush()
        session.add(
            PipelineRun(id=2, election_id=2, status=PipelineRunStatus.PASSED,
                        llm_provider="fake", llm_model="fake-model",
                        generation_mode=GenerationMode.PRECOMPUTED, prompt_versions={})
        )
        session.flush()
        session.add(
            DatasetVersion(id=2, election_id=2, pipeline_run_id=2,
                           status=DatasetVersionStatus.PUBLISHED, created_at=CREATED_AT)
        )
    client = client_for()

    elections = client.get("/api/v1/elections").json()["elections"]

    assert [
        (e["id"], e["published_dataset_version_id"], e["published_dataset_version_generation"])
        for e in elections
    ] == [(1, V2_VERSION, "v2"), (2, 2, "legacy"), (3, None, None)]
    for election in elections:
        assert list(election) == [
            "id", "country", "type", "date", "name", "status",
            "published_dataset_version_id", "published_dataset_version_generation",
        ]
    one = client.get("/api/v1/elections/1")
    assert one.json()["published_dataset_version_generation"] == "v2"
    assert one.headers["cache-control"] == "public, max-age=60"
    assert client.get("/api/v1/elections/3").json()["published_dataset_version_generation"] is None


# --- Scenario 9: final text only --------------------------------------------------------------


def test_new_routes_serve_only_the_final_text(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    for path in new_route_paths():
        raw = client.get(path).text
        for hidden in (AI_TEXT, REWORDING_REASON, REWORDING_EXPLANATION,
                       "ai_text", "explanation", "rewording"):
            assert hidden not in raw, (path, hidden)
        body = json.loads(raw)
        # The only "reason" keys are Excluded Parties' codes.
        assert raw.count('"reason":') == len(body.get("excluded_parties", []))
    texts = [s["text"] for s in client.get(f"{BASE}/constituencies/28").json()["statements"]]
    assert texts[0] == REWORDED_TEXT


# --- Scenario 10: no Answers ------------------------------------------------------------------


def test_new_routes_run_only_selects_and_ignore_query_strings(
    seeded: Engine, client_for: Callable[[], TestClient]
) -> None:
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    client = client_for()
    event.listen(Engine, "before_cursor_execute", record)
    try:
        for path in [
            *new_route_paths(),
            f"{BASE}/constituencies/00",
            f"{BASE}/constituencies/28/proposals/nope",
            "/api/v1/dataset-versions/999/constituencies",
            BASE,
        ]:
            plain = client.get(path)
            with_answers = client.get(
                path, params={"answers": "101:2,102:-1", "important": "101", "category": "x"}
            )
            assert with_answers.status_code == plain.status_code, path
            assert with_answers.content == plain.content, path
            assert with_answers.headers.get("etag") == plain.headers.get("etag")
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert statements
    for sql in statements:
        assert sql.lstrip().split(None, 1)[0].upper() in {"SELECT", "PRAGMA"}, sql
    client_post = client.post(f"{BASE}/constituencies/28", json={"answers": {}})
    assert client_post.status_code == 405


# --- OpenAPI ----------------------------------------------------------------------------------


def test_openapi_documents_the_contract(client_for: Callable[[], TestClient]) -> None:
    schema = client_for().get("/api/openapi.json").json()
    components = schema["components"]["schemas"]
    assert list(components["ConstituencyListOut"]["properties"]) == [
        "id", "election_id", "created_at", "constituencies"
    ]
    assert list(components["ConstituencySummaryOut"]["properties"]) == [
        "code", "name", "available", "unavailable_reason", "valid_statement_count",
        "offered_lengths",
    ]
    assert list(components["ConstituencyQuestionnaireOut"]["properties"]) == [
        "dataset_version_id", "code", "name", "available", "unavailable_reason",
        "offered_lengths", "statements", "parties", "excluded_parties",
    ]
    assert list(components["ConstituencyStatementOut"]["properties"]) == [
        "id", "rank", "text", "topic", "context_note"
    ]
    assert list(components["ConstituencyPartyOut"]["properties"]) == [
        "id", "name", "short_name", "logo_url", "positions", "evidence"
    ]
    assert list(components["ConstituencyPositionOut"]["properties"]) == [
        "statement_id", "value", "evidence_proposal_ids"
    ]
    assert list(components["ProposalOut"]["properties"]) == [
        "id", "text", "page", "url", "source_document_id"
    ]
    assert list(components["ExcludedPartyOut"]["properties"]) == [
        "id", "name", "short_name", "reason"
    ]
    assert list(components["ConstituencyProposalsOut"]["properties"]) == [
        "dataset_version_id", "code", "category", "parties"
    ]
    assert list(components["PartyProposalsOut"]["properties"]) == ["party_id", "proposals"]
    reason = components["ExcludedPartyOut"]["properties"]["reason"]
    assert reason["enum"] == ["no_manifesto", "discarded_at_review", "too_few_proposals"]
    unavailable = components["ConstituencySummaryOut"]["properties"]["unavailable_reason"]
    assert unavailable["anyOf"][0]["enum"] == [
        "fewer_than_two_parties", "too_few_statements", "low_party_coverage"
    ]
    value = components["ConstituencyPositionOut"]["properties"]["value"]
    assert "S5" in value["description"]
    assert "once each" in components["ConstituencyPartyOut"]["properties"]["evidence"][
        "description"
    ]
    election = components["ElectionOut"]["properties"]
    assert list(election)[-1] == "published_dataset_version_generation"
    assert election["published_dataset_version_generation"]["anyOf"][0]["enum"] == [
        "legacy", "v2"
    ]
    parameters = {
        p["name"]: p
        for p in schema["paths"][
            "/api/v1/dataset-versions/{dataset_version_id}/constituencies/{code}/proposals/{category}"
        ]["get"]["parameters"]
    }
    assert set(parameters) == {"dataset_version_id", "code", "category"}
    assert all(p["in"] == "path" for p in parameters.values())
    assert parameters["code"]["schema"]["pattern"] == "^[0-9]{2}$"
    assert parameters["category"]["schema"]["pattern"] == "^[a-z_]{1,40}$"


# --- End to end: a v2 run served per Constituency ----------------------------------------------


def test_a_v2_run_is_served_with_effective_values_and_frozen_proposals(
    tmp_path: Path, migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    from v2_fixtures import setup, v2_fake

    from ideology_app.config import ConstituencySettings
    from ideology_app.pipeline.v2 import execute_v2_run, queue_v2_run

    directory = setup(tmp_path / "bundles", migrated_engine)
    with session_scope(migrated_engine) as session:
        run_id = queue_v2_run(
            session, 1, llm_provider="fake", llm_model="fake-model",
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    outcome = execute_v2_run(
        migrated_engine, run_id, v2_fake(), directory,
        constituency_settings=ConstituencySettings(1, 1),
    )
    version = outcome.dataset_version_id
    assert version is not None and outcome.publish is not None and outcome.publish.published
    client = client_for()
    overview = client.get(f"/api/v1/dataset-versions/{version}/constituencies").json()
    available = [c["code"] for c in overview["constituencies"] if c["available"]]
    assert available == ["28"]
    assert client.get("/api/v1/elections/1").json()["published_dataset_version_generation"] == "v2"

    with Session(migrated_engine) as session:
        stored = {(p.party_id, p.statement_id): p for p in session.scalars(select(PartyPosition))}
        evidence: dict[int, list[tuple[int, list[str]]]] = {}
        for row in session.scalars(
            select(PartyPositionProposal).order_by(
                PartyPositionProposal.party_position_id, PartyPositionProposal.rank
            )
        ):
            evidence.setdefault(row.party_position_id, []).append(
                (row.proposal_id, row.constituencies)
            )
        ranked = {
            code: [sid for sid, in rows]
            for code in ("28",)
            for rows in [session.execute(
                select(ConstituencyStatement.statement_id)
                .where(ConstituencyStatement.dataset_version_id == version,
                       ConstituencyStatement.constituency_code == code)
                .order_by(ConstituencyStatement.rank)
            ).all()]
        }
        running = session.scalars(
            select(DatasetVersionCandidature.party_id).where(
                DatasetVersionCandidature.dataset_version_id == version,
                DatasetVersionCandidature.constituency_code == "28",
                DatasetVersionCandidature.excluded_reason.is_(None),
            ).order_by(DatasetVersionCandidature.party_id)
        ).all()
        frozen = session.execute(
            select(DatasetVersionProposal.party_id, DatasetVersionProposal.proposal_id,
                   DatasetVersionProposal.constituencies, Proposal.categories)
            .join(Proposal, Proposal.id == DatasetVersionProposal.proposal_id)
            .where(DatasetVersionProposal.dataset_version_id == version)
            .order_by(DatasetVersionProposal.party_id, DatasetVersionProposal.rank)
        ).all()
    for code in available:
        body = client.get(f"/api/v1/dataset-versions/{version}/constituencies/{code}").json()
        assert [s["id"] for s in body["statements"]] == ranked[code]
        assert [p["id"] for p in body["parties"]] == running
        assert [p["reason"] for p in body["excluded_parties"]] == ["no_manifesto"]
        for party in body["parties"]:
            for item in party["positions"]:
                row = stored.get((party["id"], item["statement_id"]))
                rows = [] if row is None else evidence.get(row.id, [])
                codes = [c for _, c in rows]
                value = effective_value(None if row is None else row.value, codes, code)
                assert item["value"] == ("no_stance" if value is None else value)
                assert item["evidence_proposal_ids"] == (
                    [] if value is None else [rows[i][0] for i in counting_evidence(codes, code)]
                )
        for category in ("housing", "economy"):
            served = client.get(
                f"/api/v1/dataset-versions/{version}/constituencies/{code}/proposals/{category}"
            ).json()
            assert [p["party_id"] for p in served["parties"]] == running
            assert {
                p["party_id"]: [x["id"] for x in p["proposals"]] for p in served["parties"]
            } == {
                party_id: [
                    proposal_id for p, proposal_id, codes, categories in frozen
                    if p == party_id and code in codes and category in categories
                ]
                for party_id in running
            }
