"""public-dataset-api Scenarios 1-9: the read-only, cacheable JSON API under /api/v1.

Temporary SQLite databases, ``FakeProvider`` only, sockets blocked, no API key.
"""

import datetime as dt
import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pipeline_fixtures import (
    add_parsed_document,
    candidate_lines,
    fake_provider,
    offline_guard,
    positions_response,
    seed_election,
    statements_payload,
)
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from ideology_app.api.http_cache import etag_for, if_none_match_matches
from ideology_app.api.queries import _utc_timestamp
from ideology_app.api.routes import router
from ideology_app.config import GenerationMode
from ideology_app.db import session_scope
from ideology_app.llm import FakeProvider, LLMRequest
from ideology_app.main import app as module_app
from ideology_app.main import create_app
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    ElectionType,
    Party,
    PartyPosition,
    PipelineRun,
    PipelineRunStatus,
    SourceDocument,
    Statement,
)
from ideology_app.pipeline import execute_run, queue_run

POINTER = "public, max-age=60"
IMMUTABLE = "public, max-age=86400, immutable"

ELECTION_1 = {
    "id": 1,
    "country": "ES",
    "type": "general",
    "date": "2023-07-23",
    "name": "Generales 2023",
    "status": "active",
}

# Party 3 has one URL document (id 4); its page text names no Party.
GAMMA_URL = "https://gamma.example/programa.pdf"
GAMMA_PAGE = "Propuestas sobre transporte público y ferrocarril."
# Statement position Party 3 leaves as ``no stance`` (Parties 1 and 2 still differ there).
GAMMA_NO_STANCE = 2


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def client_for(db_url: str) -> Iterator[Callable[[], TestClient]]:
    """Open ``TestClient(create_app(db_url))`` (lifespan included); closed at teardown."""
    opened: list[TestClient] = []

    def _open() -> TestClient:
        client = TestClient(create_app(db_url))
        client.__enter__()
        opened.append(client)
        return client

    yield _open
    for client in opened:
        client.__exit__(None, None, None)


def run_pipeline(engine: Engine, provider: FakeProvider, **kwargs: Any) -> int:
    """Queue and execute a run; returns its Dataset Version id (or raises)."""
    with session_scope(engine) as session:
        run_id = queue_run(
            session,
            1,
            llm_provider=provider.name,
            llm_model=provider.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        ).id
    outcome = execute_run(engine, run_id, provider, **kwargs)
    assert outcome.dataset_version_id is not None
    return outcome.dataset_version_id


def gamma_positions() -> Callable[[LLMRequest[Any]], dict[str, Any]]:
    """``positions_response(fill=True)``, but Party 3 leaves one Statement ``no stance``."""
    base = positions_response(fill=True)

    def _respond(request: LLMRequest[Any]) -> dict[str, Any]:
        result = base(request)
        if any(c["quote"] == GAMMA_PAGE for c in candidate_lines(request)):
            result["positions"] = [
                p for p in result["positions"] if p["statement"] != GAMMA_NO_STANCE
            ]
        return result

    return _respond


def provider_with_gamma() -> FakeProvider:
    return fake_provider(party_positions=gamma_positions())


def seed_three_parties(engine: Engine) -> None:
    """``seed_election`` plus Party 3 with URL document 4, and draft Election 2."""
    seed_election(engine)
    with session_scope(engine) as session:
        session.add(Party(id=3, election_id=1, name="Coalición Gamma", short_name="CG"))
        session.flush()
        add_parsed_document(
            session, party_id=3, document_id=4, pages=[GAMMA_PAGE], source_url=GAMMA_URL
        )
        session.add(
            Election(
                id=2,
                country="ES",
                type=ElectionType.GENERAL,
                date=dt.date(2027, 5, 30),
                name="Generales 2027",
                status=ElectionStatus.DRAFT,
            )
        )


@pytest.fixture
def published(migrated_engine: Engine) -> int:
    """Election 1 active with Published V1 (3 Parties); Election 2 draft."""
    seed_three_parties(migrated_engine)
    return run_pipeline(migrated_engine, provider_with_gamma())


def election_1(version_id: int | None) -> dict[str, Any]:
    return {**ELECTION_1, "published_dataset_version_id": version_id}


# --- Scenario 1 ------------------------------------------------------------


def test_lists_only_active_elections(
    published: int, client_for: Callable[[], TestClient]
) -> None:
    response = client_for().get("/api/v1/elections")

    assert response.status_code == 200
    assert response.json() == {"elections": [election_1(published)]}
    assert response.headers["cache-control"] == POINTER
    assert response.headers["etag"] == etag_for(response.content)
    assert response.headers["content-type"] == "application/json"


def test_active_elections_ordered_by_date_desc_then_id_desc(
    published: int, migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    with session_scope(migrated_engine) as session:
        for election_id, date in ((5, dt.date(2019, 11, 10)), (6, dt.date(2019, 4, 28))):
            session.add(
                Election(
                    id=election_id,
                    country="ES",
                    type=ElectionType.GENERAL,
                    date=date,
                    name=f"Generales {election_id}",
                    status=ElectionStatus.ACTIVE,
                )
            )
        session.add(
            Election(
                id=7,
                country="PT",
                type=ElectionType.GENERAL,
                date=dt.date(2023, 7, 23),
                name="Same date",
                status=ElectionStatus.ACTIVE,
            )
        )
        session.add(
            Election(
                id=8,
                country="FR",
                type=ElectionType.GENERAL,
                date=dt.date(2030, 1, 1),
                name="Archived",
                status=ElectionStatus.ARCHIVED,
            )
        )

    body = client_for().get("/api/v1/elections").json()

    assert [e["id"] for e in body["elections"]] == [7, 1, 5, 6]
    assert body["elections"][0]["published_dataset_version_id"] is None


# --- Scenario 2 ------------------------------------------------------------


def test_get_one_election_including_draft_and_unknown(
    published: int, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()

    first = client.get("/api/v1/elections/1")
    draft = client.get("/api/v1/elections/2")
    unknown = client.get("/api/v1/elections/999")

    assert first.status_code == 200
    assert first.json() == election_1(published)
    assert first.headers["cache-control"] == POINTER
    assert draft.status_code == 200
    assert draft.json() == {
        "id": 2,
        "country": "ES",
        "type": "general",
        "date": "2027-05-30",
        "name": "Generales 2027",
        "status": "draft",
        "published_dataset_version_id": None,
    }
    assert unknown.status_code == 404
    assert unknown.json() == {
        "error": {"code": "election_not_found", "message": "election 999 not found"}
    }
    assert unknown.headers["cache-control"] == "no-store"
    assert "etag" not in unknown.headers


# --- Scenario 3 ------------------------------------------------------------


def test_published_version_follows_contract(
    published: int, migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()

    response = client.get("/api/v1/elections/1/published-dataset-version")

    assert response.status_code == 200
    assert response.headers["cache-control"] == POINTER
    body = response.json()
    assert list(body) == ["id", "election_id", "created_at", "statements", "parties"]
    assert body["id"] == published
    assert body["election_id"] == 1
    assert len(body["created_at"]) == 20 and body["created_at"].endswith("Z")
    dt.datetime.strptime(body["created_at"], "%Y-%m-%dT%H:%M:%SZ")

    statements = body["statements"]
    assert [s["position"] for s in statements] == list(range(1, 31))
    assert all(list(s) == ["id", "position", "text", "topic"] for s in statements)
    statement_ids = [s["id"] for s in statements]

    with Session(migrated_engine) as session:
        stored = {
            (p.statement_id, p.party_id): p
            for p in session.scalars(
                select(PartyPosition)
                .join(Statement)
                .where(Statement.dataset_version_id == published)
            )
        }
        doc_urls = {d.id: d.source_url for d in session.scalars(select(SourceDocument))}

    assert [p["id"] for p in body["parties"]] == [1, 2, 3]
    assert [(p["name"], p["short_name"]) for p in body["parties"]] == [
        ("Partido Alfa", "PA"),
        ("Bloque Beta", "BB"),
        ("Coalición Gamma", "CG"),
    ]
    seen_upload = seen_url = seen_no_stance = False
    for party in body["parties"]:
        assert list(party) == ["id", "name", "short_name", "positions"]
        assert [p["statement_id"] for p in party["positions"]] == statement_ids
        for position in party["positions"]:
            assert list(position) == ["statement_id", "value", "evidence"]
            row = stored[(position["statement_id"], party["id"])]
            value = position["value"]
            if value == "no_stance":
                assert row.value is None
                assert position["evidence"] is None
                seen_no_stance = True
                continue
            assert type(value) is int and -2 <= value <= 2
            assert value == row.value
            evidence = position["evidence"]
            assert list(evidence) == ["quote", "page", "url", "source_document_id"]
            assert evidence["quote"] == row.evidence_quote
            assert evidence["page"] == row.evidence_page
            assert evidence["source_document_id"] == row.evidence_source_document_id
            assert evidence["url"] == doc_urls[evidence["source_document_id"]]
            if evidence["url"] is None:
                seen_upload = True
            else:
                assert evidence["url"] == GAMMA_URL
                seen_url = True
    assert seen_upload and seen_url and seen_no_stance
    gamma = body["parties"][2]["positions"][GAMMA_NO_STANCE - 1]
    assert gamma == {
        "statement_id": statement_ids[GAMMA_NO_STANCE - 1],
        "value": "no_stance",
        "evidence": None,
    }

    by_id = client.get(f"/api/v1/dataset-versions/{published}")
    assert by_id.status_code == 200
    assert by_id.content == response.content
    assert by_id.headers["etag"] == response.headers["etag"]
    assert by_id.headers["cache-control"] == IMMUTABLE


def seed_exact_version(engine: Engine) -> None:
    """A tiny hand-seeded Published version 1 (naive created_at, as SQLite returns it)."""
    seed_election(engine, with_failed_document=False)
    with session_scope(engine) as session:
        add_parsed_document(
            session, party_id=2, document_id=7, pages=["Texto web."], source_url=GAMMA_URL
        )
        session.add(
            PipelineRun(
                id=1,
                election_id=1,
                status=PipelineRunStatus.PASSED,
                llm_provider="fake",
                llm_model="fake-model",
                generation_mode=GenerationMode.PRECOMPUTED,
                prompt_versions={},
            )
        )
        session.flush()
        session.add(
            DatasetVersion(
                id=1,
                election_id=1,
                pipeline_run_id=1,
                status=DatasetVersionStatus.PUBLISHED,
                created_at=dt.datetime(2026, 10, 19, 8, 30, 15, 987654),
            )
        )
        session.flush()
        session.add_all(
            [
                Statement(
                    id=11, dataset_version_id=1, position=2, text="Segunda.", topic="health"
                ),
                Statement(
                    id=10, dataset_version_id=1, position=1, text="Primera.", topic="economy"
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                PartyPosition(
                    statement_id=10,
                    party_id=2,
                    value=-2,
                    evidence_source_document_id=7,
                    evidence_quote="Texto web.",
                    evidence_page=1,
                    evidence_url=GAMMA_URL,
                ),
                PartyPosition(
                    statement_id=10,
                    party_id=1,
                    value=0,
                    evidence_source_document_id=1,
                    evidence_quote="Propuestas sobre vivienda y alquiler.",
                    evidence_page=1,
                ),
                PartyPosition(statement_id=11, party_id=1, value=None),
                PartyPosition(
                    statement_id=11,
                    party_id=2,
                    value=2,
                    evidence_source_document_id=2,
                    evidence_quote="Medidas sobre educación y universidades.",
                    evidence_page=2,
                ),
            ]
        )
        # A Party added after the run has no Positions and does not appear.
        session.add(Party(id=9, election_id=1, name="Nuevo", short_name="NV"))


def test_exact_dataset_version_body(
    migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    seed_exact_version(migrated_engine)

    response = client_for().get("/api/v1/dataset-versions/1")

    expected = {
        "id": 1,
        "election_id": 1,
        "created_at": "2026-10-19T08:30:15Z",
        "statements": [
            {"id": 10, "position": 1, "text": "Primera.", "topic": "economy"},
            {"id": 11, "position": 2, "text": "Segunda.", "topic": "health"},
        ],
        "parties": [
            {
                "id": 1,
                "name": "Partido Alfa",
                "short_name": "PA",
                "positions": [
                    {
                        "statement_id": 10,
                        "value": 0,
                        "evidence": {
                            "quote": "Propuestas sobre vivienda y alquiler.",
                            "page": 1,
                            "url": None,
                            "source_document_id": 1,
                        },
                    },
                    {"statement_id": 11, "value": "no_stance", "evidence": None},
                ],
            },
            {
                "id": 2,
                "name": "Bloque Beta",
                "short_name": "BB",
                "positions": [
                    {
                        "statement_id": 10,
                        "value": -2,
                        "evidence": {
                            "quote": "Texto web.",
                            "page": 1,
                            "url": GAMMA_URL,
                            "source_document_id": 7,
                        },
                    },
                    {
                        "statement_id": 11,
                        "value": 2,
                        "evidence": {
                            "quote": "Medidas sobre educación y universidades.",
                            "page": 2,
                            "url": None,
                            "source_document_id": 2,
                        },
                    },
                ],
            },
        ],
    }
    assert response.status_code == 200
    assert response.json() == expected
    # Compact JSON, keys in contract order, non-ASCII kept as UTF-8.
    assert response.content == json.dumps(
        expected, separators=(",", ":"), ensure_ascii=False
    ).encode()


def test_created_at_is_rendered_in_utc() -> None:
    tz = dt.timezone(dt.timedelta(hours=2))
    assert _utc_timestamp(dt.datetime(2026, 10, 19, 10, 0, 1, 5, tzinfo=tz)) == (
        "2026-10-19T08:00:01Z"
    )
    assert _utc_timestamp(dt.datetime(2026, 10, 19, 10, 0, 1)) == "2026-10-19T10:00:01Z"


# --- Scenario 4 ------------------------------------------------------------


def test_superseded_version_is_still_returned_by_id(
    published: int, migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    v1_before = client.get(f"/api/v1/dataset-versions/{published}")
    list_before = client.get("/api/v1/elections")
    pointer_before = client.get("/api/v1/elections/1/published-dataset-version")

    v2 = run_pipeline(migrated_engine, provider_with_gamma())

    with Session(migrated_engine) as session:
        v1_row = session.get(DatasetVersion, published)
        assert v1_row is not None and v1_row.status is DatasetVersionStatus.SUPERSEDED
    pointer = client.get("/api/v1/elections/1/published-dataset-version")
    v1_after = client.get(f"/api/v1/dataset-versions/{published}")
    election = client.get("/api/v1/elections/1")
    list_after = client.get("/api/v1/elections")

    assert v2 != published
    assert pointer.status_code == 200
    assert pointer.json()["id"] == v2
    assert v1_after.status_code == 200
    assert v1_after.content == v1_before.content
    assert v1_after.headers["etag"] == v1_before.headers["etag"]
    assert v1_after.headers["cache-control"] == IMMUTABLE
    assert election.json()["published_dataset_version_id"] == v2
    assert list_after.headers["etag"] != list_before.headers["etag"]
    assert pointer.headers["etag"] != pointer_before.headers["etag"]


# --- Scenario 5 ------------------------------------------------------------


def test_unknown_candidate_and_malformed_version_ids(
    migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    seed_election(migrated_engine)
    v1 = run_pipeline(migrated_engine, fake_provider())
    v3 = run_pipeline(
        migrated_engine, fake_provider(generate_statements=statements_payload(20))
    )
    with Session(migrated_engine) as session:
        candidate = session.get(DatasetVersion, v3)
        assert candidate is not None and candidate.status is DatasetVersionStatus.CANDIDATE
    client = client_for()

    assert client.get(f"/api/v1/dataset-versions/{v1}").status_code == 200
    for version_id in (999999, v3):
        response = client.get(f"/api/v1/dataset-versions/{version_id}")
        assert response.status_code == 404
        assert response.json() == {
            "error": {
                "code": "dataset_version_not_found",
                "message": f"dataset version {version_id} not found",
            }
        }
        assert response.headers["cache-control"] == "no-store"
    for bad in ("abc", "0", "-1", "2147483648", "9223372036854775808"):
        assert client.get(f"/api/v1/dataset-versions/{bad}").status_code == 422
        assert client.get(f"/api/v1/elections/{bad}").status_code == 422
        assert (
            client.get(f"/api/v1/elections/{bad}/published-dataset-version").status_code == 422
        )
    assert client.get("/api/v1/dataset-versions/2147483647").status_code == 404


# --- Scenario 6 ------------------------------------------------------------


def test_election_without_published_version(
    migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    seed_election(migrated_engine)
    # Only a candidate version (failed Validation): still no Published version.
    run_pipeline(migrated_engine, fake_provider(generate_statements=statements_payload(20)))
    client = client_for()

    none_yet = client.get("/api/v1/elections/1/published-dataset-version")
    unknown = client.get("/api/v1/elections/999/published-dataset-version")

    assert none_yet.status_code == 404
    assert none_yet.json() == {
        "error": {
            "code": "no_published_dataset_version",
            "message": "election 1 has no published dataset version",
        }
    }
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "election_not_found"
    assert none_yet.headers["cache-control"] == "no-store"
    assert unknown.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/elections/1").json()["published_dataset_version_id"] is None


def test_draft_election_without_any_version(
    published: int, client_for: Callable[[], TestClient]
) -> None:
    response = client_for().get("/api/v1/elections/2/published-dataset-version")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "no_published_dataset_version",
            "message": "election 2 has no published dataset version",
        }
    }
    assert response.headers["cache-control"] == "no-store"


# --- Scenario 7 ------------------------------------------------------------


def paths_for(version_id: int) -> list[str]:
    return [
        "/api/v1/elections",
        "/api/v1/elections/1",
        "/api/v1/elections/2",
        "/api/v1/elections/1/published-dataset-version",
        f"/api/v1/dataset-versions/{version_id}",
    ]


def test_conditional_requests_return_304(
    published: int, client_for: Callable[[], TestClient]
) -> None:
    client = client_for()
    for path in paths_for(published):
        first = client.get(path)
        etag = first.headers["etag"]
        assert etag.startswith('"') and etag.endswith('"') and len(etag) == 34
        for header in (etag, f"W/{etag}", f'"x", {etag}', "*", f'"x",W/{etag}'):
            response = client.get(path, headers={"If-None-Match": header})
            assert response.status_code == 304, (path, header)
            assert response.content == b""
            assert response.headers["etag"] == etag
            assert response.headers["cache-control"] == first.headers["cache-control"]
        for header in ('"nope"', etag[:-2] + '"', ""):
            response = client.get(path, headers={"If-None-Match": header})
            assert response.status_code == 200
            assert response.content == first.content


def test_if_none_match_parsing() -> None:
    assert if_none_match_matches('"a"', '"a"')
    assert if_none_match_matches(' W/"a" ', '"a"')
    assert if_none_match_matches('"b",  "a"', '"a"')
    assert if_none_match_matches("*", '"a"')
    assert not if_none_match_matches(None, '"a"')
    assert not if_none_match_matches("", '"a"')
    assert not if_none_match_matches("a", '"a"')
    assert not if_none_match_matches('"A"', '"a"')


def test_404_ignores_if_none_match(
    published: int, client_for: Callable[[], TestClient]
) -> None:
    response = client_for().get("/api/v1/elections/999", headers={"If-None-Match": "*"})

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


# --- Scenario 8 ------------------------------------------------------------


def test_api_routes_are_get_only_without_query_or_body() -> None:
    # The router's own routes carry the full prefixed path.
    api_routes = [r for r in router.routes if isinstance(r, APIRoute)]
    app_paths = {p for p in create_app("sqlite://").openapi()["paths"] if p.startswith("/api/")}
    assert app_paths == {r.path for r in api_routes}

    assert {r.path for r in api_routes} == {
        "/api/v1/elections",
        "/api/v1/elections/{election_id}",
        "/api/v1/elections/{election_id}/published-dataset-version",
        "/api/v1/dataset-versions/{dataset_version_id}",
    }
    for route in api_routes:
        assert route.methods == {"GET"}, route.path
        assert route.dependant.query_params == []
        assert route.dependant.body_params == []
        assert route.dependant.header_params == []
        assert route.dependant.cookie_params == []
        for dependency in route.dependant.dependencies:
            assert dependency.query_params == [] and dependency.body_params == []
    client = TestClient(create_app("sqlite://"))
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/elections").status_code == 405


def test_api_executes_only_selects_and_ignores_query_strings(
    published: int, migrated_engine: Engine, client_for: Callable[[], TestClient]
) -> None:
    statements: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    client = client_for()
    event.listen(Engine, "before_cursor_execute", record)
    try:
        for path in [
            *paths_for(published),
            "/api/v1/elections/999",
            "/api/v1/dataset-versions/999999",
            "/api/v1/elections/2/published-dataset-version",
        ]:
            plain = client.get(path)
            with_answers = client.get(path, params={"answers": "1:2,2:-1", "important": "1"})
            assert with_answers.status_code == plain.status_code
            assert with_answers.content == plain.content
            assert with_answers.headers.get("etag") == plain.headers.get("etag")
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert statements
    for statement in statements:
        verb = statement.lstrip().split(None, 1)[0].upper()
        assert verb in {"SELECT", "PRAGMA"}, statement


# --- Scenario 9 ------------------------------------------------------------


def test_openapi_is_exposed_under_api(client_for: Callable[[], TestClient]) -> None:
    client = client_for()

    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    expected = {
        "/api/v1/elections": ("listElections", "ElectionListOut"),
        "/api/v1/elections/{election_id}": ("getElection", "ElectionOut"),
        "/api/v1/elections/{election_id}/published-dataset-version": (
            "getPublishedDatasetVersion",
            "DatasetVersionOut",
        ),
        "/api/v1/dataset-versions/{dataset_version_id}": (
            "getDatasetVersion",
            "DatasetVersionOut",
        ),
    }
    for path, (operation_id, model) in expected.items():
        operation = schema["paths"][path]["get"]
        assert set(schema["paths"][path]) == {"get"}
        assert operation["operationId"] == operation_id
        responses = operation["responses"]
        assert responses["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{model}"
        }
        assert responses["404"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorOut"
        }
        assert "304" in responses
    value = schema["components"]["schemas"]["PositionOut"]["properties"]["value"]
    assert value["anyOf"] == [
        {"type": "integer", "minimum": -2, "maximum": 2},
        {"type": "string", "const": "no_stance"},
    ]
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/docs/oauth2-redirect").status_code == 200
    assert client.get("/docs/oauth2-redirect").status_code == 404
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_module_app_health_needs_no_database() -> None:
    assert TestClient(module_app).get("/health").json() == {"status": "ok"}


def test_unknown_api_path_keeps_default_404(client_for: Callable[[], TestClient]) -> None:
    response = client_for().get("/api/v1/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_lifespan_disposes_engine(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from ideology_app import main

    disposed: list[Engine] = []
    real_make = main.make_engine

    def tracking(url: str | None = None) -> Engine:
        engine = real_make(url)
        real_dispose = engine.dispose
        monkeypatch.setattr(
            engine, "dispose", lambda: (disposed.append(engine), real_dispose())
        )
        return engine

    monkeypatch.setattr(main, "make_engine", tracking)
    with TestClient(create_app(db_url)) as client:
        engine = client.app.state.engine  # type: ignore[attr-defined]
        assert disposed == []
    assert disposed == [engine]


def test_database_url_comes_from_environment(
    migrated_engine: Engine, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_exact_version(migrated_engine)
    monkeypatch.setenv("DATABASE_URL", db_url)

    with TestClient(create_app()) as client:
        assert client.get("/api/v1/dataset-versions/1").status_code == 200
