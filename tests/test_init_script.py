"""Regression tests for the `run_step`, `step_node` and `step_web_install` helpers in init.sh.

The functions are extracted from init.sh by line pattern and run under
/bin/bash with `set -euo pipefail`, so they need no real Node.js.
"""

import re
import subprocess
from pathlib import Path

import pytest

INIT_SH = Path(__file__).resolve().parent.parent / "init.sh"
BASH = Path("/bin/bash")

pytestmark = pytest.mark.skipif(not BASH.exists(), reason="/bin/bash not available")


def _function(name: str) -> str:
    lines = INIT_SH.read_text().splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(rf"^{re.escape(name)}\(\) \{{", line)),
        None,
    )
    if start is None:
        raise AssertionError(f"function {name} not found in {INIT_SH}")
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^\}", lines[i])),
        None,
    )
    if end is None:
        raise AssertionError(f"end of function {name} not found in {INIT_SH}")
    return "\n".join(lines[start : end + 1])


def _assignment(name: str) -> str:
    for line in INIT_SH.read_text().splitlines():
        if re.match(rf"^{re.escape(name)}=", line):
            return line
    raise AssertionError(f"assignment {name}= not found in {INIT_SH}")


def _run(script: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    defs = "\n".join(
        [
            _assignment("NODE_MIN_MAJOR"),
            _assignment("NODE_MIN_MINOR"),
            _function("run_step"),
            _function("step_node"),
            _function("step_web_install"),
        ]
    )
    env = {"PATH": path} if path is not None else {"PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [str(BASH), "-c", f"set -euo pipefail\n{defs}\n{script}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_run_step_fails_multi_command_step_whose_first_command_fails() -> None:
    result = _run("f() { false; echo after; }\nrun_step demo f\necho continued")
    assert result.returncode == 1
    assert "==> demo" in result.stdout
    assert "FAILED: demo" in result.stdout
    assert "after" not in result.stdout
    assert "continued" not in result.stdout


def test_run_step_passing_step_continues() -> None:
    result = _run("f() { true; echo inside; }\nrun_step demo f\necho continued")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "inside" in result.stdout
    assert "continued" in result.stdout
    assert "FAILED" not in result.stdout


def test_step_node_fails_without_node_on_path(tmp_path: Path) -> None:
    result = _run("run_step node step_node\necho continued", path=str(tmp_path))
    assert result.returncode != 0
    assert "Node.js >= 22.13 is required for the web client" in result.stdout
    assert "not found on PATH" in result.stdout
    assert "FAILED: node" in result.stdout
    assert "continued" not in result.stdout


def _fake_node(directory: Path, version: str) -> None:
    node = directory / "node"
    node.write_text(f"#!/bin/sh\necho {version}\n")
    node.chmod(0o755)


@pytest.mark.parametrize("version", ["20.11.1", "21.7.3", "22.12.0", "22.0.0"])
def test_step_node_fails_on_old_node(tmp_path: Path, version: str) -> None:
    _fake_node(tmp_path, version)
    result = _run("run_step node step_node\necho continued", path=str(tmp_path))
    assert result.returncode != 0
    assert f"Node.js >= 22.13 is required (found v{version})" in result.stdout
    assert "FAILED: node" in result.stdout
    assert "continued" not in result.stdout


@pytest.mark.parametrize("version", ["22.13.0", "22.20.1", "23.0.0", "24.1.0"])
def test_step_node_passes_on_supported_node(tmp_path: Path, version: str) -> None:
    _fake_node(tmp_path, version)
    result = _run("run_step node step_node\necho continued", path=str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Node: v{version}" in result.stdout
    assert "continued" in result.stdout


def test_step_web_install_fails_without_npm_on_path(tmp_path: Path) -> None:
    result = _run("run_step web-install step_web_install\necho continued", path=str(tmp_path))
    assert result.returncode != 0
    assert "npm not found on PATH" in result.stdout
    assert "FAILED: web-install" in result.stdout
    assert "continued" not in result.stdout
