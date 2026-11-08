"""The production image (deploy-container): static checks of ``Dockerfile`` and ``.dockerignore``.

No Docker here: the build and the running container are checked by hand (see
the spec). These tests pin the settings a careless edit could undo.
"""

import json
import re
from pathlib import Path

from ideology_app import config

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")


def _joined() -> str:
    """The Dockerfile with line continuations joined."""
    return re.sub(r"\\\n\s*", "", DOCKERFILE)


def _instructions(name: str) -> list[str]:
    return [
        line.split(None, 1)[1]
        for line in _joined().splitlines()
        if line.strip().upper().startswith(name + " ")
    ]


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    for value in _instructions("ENV"):
        for key, val in re.findall(r"(\w+)=(\S+)", value):
            env[key] = val
    return env


def test_cmd_runs_one_worker_without_access_log_behind_proxy() -> None:
    (cmd,) = _instructions("CMD")
    argv = json.loads(cmd)
    assert argv[:2] == ["uvicorn", "ideology_app.main:app"]
    assert argv[argv.index("--workers") + 1] == "1"
    assert "--no-access-log" in argv
    assert "--proxy-headers" in argv
    # Trusted proxies come from FORWARDED_ALLOW_IPS at run time, never a baked-in "*".
    assert "--forwarded-allow-ips" not in argv
    assert "FORWARDED_ALLOW_IPS" not in _env()


def test_runs_as_non_root_user() -> None:
    users = _instructions("USER")
    assert users and users[-1] not in ("root", "0")


def test_base_images_are_pinned() -> None:
    images = [value.split()[0] for value in _instructions("FROM")]
    assert len(images) == 2
    for image in images:
        assert re.fullmatch(r"[\w./-]+:\d+\.\d+\.\d+[\w.-]*", image), image


def test_paths_and_volume() -> None:
    env = _env()
    assert env["DATABASE_URL"] == "sqlite:////app/data/ideology.db"
    assert env["FEEDBACK_DATABASE_URL"].startswith("sqlite:////data/")
    assert env["WEB_DIST_DIR"] == "/app/web"
    assert _instructions("VOLUME") == ["/data"]
    # The published database is copied from its committed path.
    assert f"COPY {config.SHARED_DATABASE_PATH.as_posix()} " in DOCKERFILE
    assert "ADMIN_USERS" not in env


def test_dockerignore_keeps_secrets_and_local_databases_out() -> None:
    lines = [line.strip() for line in DOCKERIGNORE.splitlines()]
    for pattern in (".env", ".git", ".venv", "**/node_modules", "**/*.db", "source_files"):
        assert pattern in lines, pattern
    # The only database allowed in, after the *.db exclusion.
    assert lines.index("!data/ideology.db") > lines.index("**/*.db")
