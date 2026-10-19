#!/usr/bin/env bash
# Standard startup and verification gate. Installs the app into .venv and runs
# every verify step in order. Never starts a long-running server.
set -euo pipefail

cd "$(dirname "$0")"

NODE_MIN_MAJOR=22
NODE_MIN_MINOR=13

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
  local need="$NODE_MIN_MAJOR.$NODE_MIN_MINOR"
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js >= $need is required for the web client (node not found on PATH)"
    return 1
  fi
  local v major rest minor
  v="$(node -p 'process.versions.node')"
  major="${v%%.*}"
  rest="${v#*.}"
  minor="${rest%%.*}"
  if [[ "$major" -lt "$NODE_MIN_MAJOR" ]] ||
    [[ "$major" -eq "$NODE_MIN_MAJOR" && "$minor" -lt "$NODE_MIN_MINOR" ]]; then
    echo "Node.js >= $need is required (found v$v)"
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

step_web_install() {
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm is required for the web client (npm not found on PATH)"
    return 1
  fi
  echo "npm: $(npm --version)"
  # Installs exactly the committed package-lock.json; fails if package.json and
  # the lockfile disagree.
  npm ci --no-audit --no-fund
}

step_web_typecheck() {
  npm run typecheck
}

step_web_test() {
  npm test
}

step_web_build() {
  npm run build
}

run_step node step_node
run_step install step_install
run_step pytest step_pytest
run_step web-install step_web_install
run_step web-typecheck step_web_typecheck
run_step web-test step_web_test
run_step web-build step_web_build
# Add new verify steps as `step_<name>` functions plus a `run_step` line.

echo "All checks passed."
echo "Start the app manually (from the repository root) with:"
echo "  .venv/bin/uvicorn ideology_app.main:app --reload"
echo "then open http://127.0.0.1:8000/ (API under /api/v1/, docs at /api/docs)."
echo "Optional live-reload client (proxies /api and /health to port 8000):"
echo "  npm run dev -w @ideology-app/web"
