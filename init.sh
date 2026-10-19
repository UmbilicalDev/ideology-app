#!/usr/bin/env bash
# Standard startup and verification gate. Installs the app into .venv and runs
# every verify step in order. Never starts a long-running server.
set -euo pipefail

cd "$(dirname "$0")"

NODE_MIN_MAJOR=22

VENV=.venv
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> Creating virtualenv in $VENV"
  "${PYTHON:-python3}" -m venv "$VENV"
fi
PY="$VENV/bin/python"

echo "Repository: $(pwd)"
echo "Python: $("$PY" --version)"

# Runs a step in a `set -e` subshell. The subshell must not be part of a
# condition (`if`, `!`, `&&`, `||`): bash ignores `set -e` there, so a step
# with several commands could pass even when one of them fails.
run_step() {
  local name="$1"
  shift
  echo "==> $name"
  local rc
  set +e
  ( set -e; "$@" )
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    echo "FAILED: $name (exit $rc)"
    exit 1
  fi
}

# Each step is a function, so its arguments are never word-split.
step_node() {
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js >= $NODE_MIN_MAJOR is required for the JS unit tests (node not found on PATH)"
    return 1
  fi
  local v
  v="$(node -p 'process.versions.node')"
  if [[ "${v%%.*}" -lt "$NODE_MIN_MAJOR" ]]; then
    echo "Node.js >= $NODE_MIN_MAJOR is required (found v$v)"
    return 1
  fi
  echo "Node: v$v"
}

step_install() {
  "$PY" -m pip install --disable-pip-version-check -q -e '.[dev]'
}

step_pytest() {
  "$PY" -m pytest
}

step_js_test() {
  shopt -s nullglob
  local files=(tests/js/*.test.js)
  if [[ ${#files[@]} -eq 0 ]]; then
    echo "no JS test files in tests/js"
    return 1
  fi
  node --test "${files[@]}"
}

run_step node step_node
run_step install step_install
run_step pytest step_pytest
run_step js-test step_js_test
# Add new verify steps as `step_<name>` functions plus a `run_step` line.

echo "All checks passed."
echo "Start the app manually with:"
echo "  .venv/bin/uvicorn ideology_app.main:app --reload"
