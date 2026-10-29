"""web-client-skeleton Scenarios 3-5: FastAPI serves the built web client.

Each test builds a fake dist in ``tmp_path``; no Node.js, no network.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pipeline_fixtures import offline_guard

from ideology_app import config
from ideology_app.api.feedback_routes import feedback_router
from ideology_app.api.routes import router
from ideology_app.main import create_app

INDEX_HTML = "<!doctype html><title>Comparador</title><div id=root></div>"
ASSET_JS = b"console.log('app');\n"
SECRET = "do not serve me"
IMMUTABLE = "public, max-age=31536000, immutable"
NOT_FOUND = {"detail": "Not Found"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """``tmp_path/web/dist`` with an index and a hashed asset; a secret file sits next to dist."""
    root = tmp_path / "web"
    dist_dir = root / "dist"
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "index.html").write_text(INDEX_HTML)
    (dist_dir / "assets" / "app-abc123.js").write_bytes(ASSET_JS)
    (dist_dir / "robots.txt").write_text("User-agent: *\n")
    (root / "secret.txt").write_text(SECRET)
    return dist_dir


@pytest.fixture
def client_for(db_url: str) -> Iterator[Callable[[Path], TestClient]]:
    """Open ``TestClient(create_app(db_url, dist))`` (lifespan included)."""
    opened: list[TestClient] = []

    def _open(dist_dir: Path) -> TestClient:
        client = TestClient(create_app(db_url, web_dist_dir=dist_dir))
        client.__enter__()
        opened.append(client)
        return client

    yield _open
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def migrated_client(
    migrated_engine: object, client_for: Callable[[Path], TestClient], dist: Path
) -> TestClient:
    return client_for(dist)


# --- Scenario 3: FastAPI serves the build ----------------------------------


@pytest.mark.parametrize("path", ["/", "/some/deep/path?x=1", "/anything", "/docs", "/redoc"])
def test_root_and_client_routes_return_index(migrated_client: TestClient, path: str) -> None:
    response = migrated_client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == INDEX_HTML


def test_hashed_asset_is_served_immutable(migrated_client: TestClient) -> None:
    response = migrated_client.get("/assets/app-abc123.js")

    assert response.status_code == 200
    assert response.content == ASSET_JS
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == IMMUTABLE


def test_other_dist_files_are_no_cache(migrated_client: TestClient) -> None:
    for path in ("/robots.txt", "/index.html"):
        response = migrated_client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path", ["/assets/missing.js", "/favicon.ico", "/some/dir/image.png", "/openapi.json"]
)
def test_missing_file_with_extension_is_404_json(migrated_client: TestClient, path: str) -> None:
    response = migrated_client.get(path)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_non_get_on_client_path_is_405(migrated_client: TestClient) -> None:
    assert migrated_client.post("/anything").status_code == 405


# --- Scenario 4: API and health keep precedence ----------------------------


def test_api_and_health_keep_precedence(migrated_client: TestClient) -> None:
    client = migrated_client

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    openapi = client.get("/api/openapi.json")
    assert openapi.status_code == 200
    assert openapi.headers["content-type"].startswith("application/json")
    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()
    elections = client.get("/api/v1/elections")
    assert elections.status_code == 200
    assert elections.headers["content-type"].startswith("application/json")
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/elections").status_code == 405

    for path in ("/api/v1/nope", "/api", "/api/", "/health/x", "/api/v1/x.js", "/api/v1/elections/"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json() == NOT_FOUND, path


def test_admin_is_a_reserved_prefix(migrated_client: TestClient, dist: Path) -> None:
    # feedback-admin: the catch-all never serves admin/..., even a real file there.
    (dist / "admin").mkdir()
    (dist / "admin" / "index.html").write_text("admin")
    for path in ("/admin/index.html", "/admin/x", "/admin/api", "/admin/api/v1/nope", "/admin/x.js"):
        response = migrated_client.get(path)
        assert response.status_code == 404, path
        assert response.json() == NOT_FOUND, path
    assert migrated_client.get("/administracion").status_code == 200  # only the exact prefix


def test_openapi_paths_have_no_catch_all(dist: Path) -> None:
    paths = set(create_app("sqlite://", web_dist_dir=dist).openapi()["paths"])
    expected = {
        r.path
        for r in [*router.routes, *feedback_router.routes]
        if getattr(r, "path", "").startswith("/api/")
    }

    assert paths == expected | {"/health"}


# --- Scenario 5: missing build and traversal --------------------------------


def _assert_not_built(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert client.get("/some/deep/path").status_code == 404
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_missing_dist_dir_is_404_and_warns(
    tmp_path: Path, client_for: Callable[[Path], TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "nowhere" / "dist"
    with caplog.at_level(logging.WARNING, logger="ideology_app.web"):
        client = client_for(missing)

    _assert_not_built(client)
    messages = [r.getMessage() for r in caplog.records if r.name == "ideology_app.web"]
    assert messages == [f"web client not built: {missing / 'index.html'} not found; run ./init.sh"]


def test_dist_without_index_is_404_and_warns(
    tmp_path: Path, client_for: Callable[[Path], TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    empty = tmp_path / "dist"
    (empty / "assets").mkdir(parents=True)
    (empty / "assets" / "app.js").write_text("x")
    with caplog.at_level(logging.WARNING, logger="ideology_app.web"):
        client = client_for(empty)

    _assert_not_built(client)
    assert client.get("/assets/app.js").status_code == 404
    assert any("web client not built" in r.getMessage() for r in caplog.records)


def test_build_present_logs_no_warning(
    dist: Path, client_for: Callable[[Path], TestClient], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="ideology_app.web"):
        client_for(dist)

    assert [r for r in caplog.records if r.name == "ideology_app.web"] == []


def test_build_made_after_startup_is_served_without_restart(
    tmp_path: Path, client_for: Callable[[Path], TestClient]
) -> None:
    later = tmp_path / "dist"
    client = client_for(later)
    assert client.get("/").status_code == 404

    later.mkdir()
    (later / "index.html").write_text(INDEX_HTML)

    assert client.get("/").text == INDEX_HTML


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/%2e%2e%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/../secret.txt",
    ],
)
def test_traversal_never_serves_files_outside_dist(migrated_client: TestClient, path: str) -> None:
    response = migrated_client.get(path)

    assert SECRET not in response.text
    assert response.status_code == 404


def test_symlink_out_of_dist_is_not_served(dist: Path, client_for: Callable[[Path], TestClient]) -> None:
    (dist / "link.txt").symlink_to(dist.parent / "secret.txt")
    response = client_for(dist).get("/link.txt")

    assert response.status_code == 404
    assert SECRET not in response.text


# --- Setting ----------------------------------------------------------------


def test_web_dist_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_DIST_DIR", raising=False)
    assert config.web_dist_dir() == Path("apps/web/dist")


@pytest.mark.parametrize("raw", ["", "   "])
def test_web_dist_dir_blank_means_default(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("WEB_DIST_DIR", raw)
    assert config.web_dist_dir() == Path("apps/web/dist")


def test_web_dist_dir_from_env_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_DIST_DIR", "  /srv/web/dist  ")
    assert config.web_dist_dir() == Path("/srv/web/dist")


def test_create_app_reads_web_dist_dir_from_env(
    monkeypatch: pytest.MonkeyPatch, dist: Path, db_url: str
) -> None:
    monkeypatch.setenv("WEB_DIST_DIR", str(dist))
    with TestClient(create_app(db_url)) as client:
        assert client.get("/").text == INDEX_HTML


def test_create_app_default_dist_is_relative_to_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_url: str
) -> None:
    built = tmp_path / "apps" / "web" / "dist"
    built.mkdir(parents=True)
    (built / "index.html").write_text(INDEX_HTML)
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(db_url)) as client:
        assert client.get("/").text == INDEX_HTML
