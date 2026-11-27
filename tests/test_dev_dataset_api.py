"""dev-dataset S2: the public API serves the seeded dev database (TestClient, offline)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pipeline_fixtures import offline_guard

from ideology_app.dev_dataset import content
from ideology_app.main import create_app

N_TYPICAL = 43


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def client(dev_seed: Any) -> Iterator[TestClient]:
    with TestClient(create_app(f"sqlite:///{dev_seed.database}")) as client:
        yield client


def _base(client: TestClient) -> str:
    (election,) = client.get("/api/v1/elections").json()["elections"]
    return f"/api/v1/dataset-versions/{election['published_dataset_version_id']}"


def test_one_v2_election(client: TestClient) -> None:
    body = client.get("/api/v1/elections").json()
    (election,) = body["elections"]
    assert election["name"] == content.ELECTION_NAME
    assert election["published_dataset_version_generation"] == "v2"
    legacy = client.get(f"/api/v1/dataset-versions/{election['published_dataset_version_id']}")
    assert legacy.status_code == 404
    assert legacy.json()["error"]["code"] == "dataset_version_is_v2"


def test_constituency_overview(client: TestClient) -> None:
    rows = client.get(f"{_base(client)}/constituencies").json()["constituencies"]
    assert len(rows) == 52
    by_code = {row["code"]: row for row in rows}
    assert by_code["52"]["available"] is False
    assert by_code["52"]["unavailable_reason"] == "fewer_than_two_parties"
    for code, row in by_code.items():
        if code == "52":
            continue
        assert row["available"] is True
        n = row["valid_statement_count"]
        assert row["offered_lengths"] == ([n] if n < 20 else [x for x in (20, 30, 40, 50) if x <= n])
    assert 50 in by_code["08"]["offered_lengths"]
    assert by_code["51"]["offered_lengths"] == [14]


def test_madrid_questionnaire(client: TestClient) -> None:
    body = client.get(f"{_base(client)}/constituencies/28").json()
    assert len(body["statements"]) == N_TYPICAL
    assert all(s["context_note"] for s in body["statements"])
    texts = {s["text"] for s in body["statements"]}
    assert content.REWORDING.text in texts
    ai_text = content.STATEMENTS_BY_KEY[content.REWORDING.statement].text
    assert ai_text not in texts
    assert [p["short_name"] for p in body["parties"]] == ["CUARZO", "JADE", "ONIX", "ZAFIRO"]
    assert [(p["short_name"], p["reason"]) for p in body["excluded_parties"]] == [
        ("MICA", "too_few_proposals")
    ]


def test_melilla_is_unavailable_but_served(client: TestClient) -> None:
    response = client.get(f"{_base(client)}/constituencies/52")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False and body["statements"] == []
    assert {p["short_name"] for p in body["excluded_parties"]} == {"GRAFITO", "PIZARRA"}


def test_barcelona_proposals_and_logos(client: TestClient) -> None:
    body = client.get(f"{_base(client)}/constituencies/08/proposals/territorial_model").json()
    with_proposals = [p for p in body["parties"] if p["proposals"]]
    assert len(with_proposals) >= 4
    questionnaire = client.get(f"{_base(client)}/constituencies/08").json()
    logos = {p["short_name"]: p["logo_url"] for p in questionnaire["parties"]}
    assert logos["ZAFIRO"] is None
    response = client.get(logos["BASALTO"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
