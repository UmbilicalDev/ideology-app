# Feature Implementation Spec: Runnable FastAPI skeleton with test gate

## Source Feature

- `id`: bootstrap-app-skeleton
- `area`: platform
- `depends_on`: none
- `status`: not_started
- `source`: `feature_list.json`

## Goal

Turn the pre-bootstrap repository into a runnable Python project. `./init.sh` becomes the real gate: it ensures a virtualenv exists, installs the package with its dev extras, and runs pytest. The app is a FastAPI ASGI app with one endpoint, `GET /health`, so every later feature has an install path, a test runner and a running server to build on.

## Non-Goals

- Database, migrations, configuration loading or a CLI (`db-schema-elections-parties`).
- LLM providers, the pipeline, or any domain model.
- UI, templates, static files, or JS tooling. The JS test runner arrives with `match-score-engine`; this feature only leaves room for extra verify steps.
- Linters, formatters, type checkers, CI workflows, Docker, or a dependency lockfile.

## Job Story

When I start a new session on this repository,
I want one command that installs everything and tells me whether the baseline is green,
so I can begin feature work without rediscovering how the project runs.

## Users And Permissions

- Developer or agent: runs `./init.sh` and the dev server locally.
- Voter and Operator: not affected. `/health` is public and returns a fixed value.

## Acceptance Scenarios

### Scenario 1: Fresh checkout

Given a clone of the repo with no `.venv`
When the developer runs `CI=true ./init.sh`
Then it creates `.venv`, installs the package with `[dev]`, runs pytest with at least one passing test, prints the start command, and exits 0.

### Scenario 2: Existing virtualenv

Given `.venv` already exists (this repo's `.venv` runs Python 3.15.0)
When the developer runs `./init.sh` again
Then it reuses `.venv`, reinstalls idempotently, and exits 0. It never starts a server.

### Scenario 3: Health endpoint

Given the app is running with `.venv/bin/uvicorn ideology_app.main:app`
When a client requests `GET /health`
Then the response is `200` with JSON body `{"status": "ok"}`, and unknown paths return 404.

### Scenario 4: Failing test breaks the gate

Given a test that fails
When the developer runs `./init.sh`
Then it prints `FAILED: pytest` and exits non-zero.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json` — workflow; this is the first ready feature.
- `docs/technical-discovery.md` — Python + FastAPI backend; pytest-based tests.
- `init.sh` — the pre-bootstrap script that only prints messages; it gets replaced.
- `.gitignore` — ignores `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.egg-info/`, `.env`, `*.db`, `.DS_Store`.
- `.venv` — Python 3.15.0. It already contains fastapi 0.143.2, starlette 1.8.0, uvicorn 0.54.0, pydantic 2.14.1, pytest 9.1.1 and httpx2 2.13.1 left over from an earlier attempt. System `python3` is 3.13.9.

### Existing Patterns To Follow

- None in code yet. The harness requires `./init.sh` to be the non-blocking standard gate: run checks, never start long-running processes, and print manual follow-up commands.

### Current Gaps

- There is no `pyproject.toml`, no package and no tests.
- Python 3.15 is very new. An earlier check found that every dependency here installs from wheels on it. Starlette's test client imports `httpx2` and emits a deprecation warning when only `httpx` is installed, so the dev dependency is `httpx2`, not `httpx`.
- Because `.venv` is pre-populated, Scenario 1 can't be proven in place. Run it on a copy of the repo without `.venv`.

## Technical Approach

- **Packaging:** `pyproject.toml` with the setuptools backend and the src layout (`src/ideology_app/`).
  - `requires-python = ">=3.12"` keeps 3.12–3.13 as fallbacks if a later dependency lacks 3.15 wheels.
  - Runtime deps: `fastapi>=0.115`, `uvicorn>=0.30`.
  - The `dev` extra: `pytest>=8`, `httpx2>=2`.
  - Pytest config: `testpaths = ["tests"]`, `addopts = "-q"`.
- **App:** `src/ideology_app/main.py` defines `app = FastAPI(title="ideology-app")` and `GET /health` returning `{"status": "ok"}`. `__init__.py` holds `__version__ = "0.1.0"`.
- **Test:** `tests/test_health.py` uses `fastapi.testclient.TestClient`.
- **init.sh** (replaced completely, bash, `set -euo pipefail`):
  1. `cd "$(dirname "$0")"`, so it works from any directory.
  2. If `.venv/bin/python` is missing, create the venv with `"${PYTHON:-python3}" -m venv .venv`.
  3. Print the repository path and the Python version.
  4. Install: `.venv/bin/python -m pip install --disable-pip-version-check -q -e '.[dev]'`.
  5. Verify: run an ordered list of steps through a `run_step <name> <cmd...>` helper. It prints `==> <name>`; on failure it prints `FAILED: <name>` and exits 1. Store each step so that arguments are never word-split; for example, define each step as its own bash function or array rather than a single string. The only step today is `pytest` (`.venv/bin/python -m pytest`). A comment shows where future steps go.
  6. Print `All checks passed.` and the start command `.venv/bin/uvicorn ideology_app.main:app --reload`. Never run it.
  - `CI=true` needs no special handling: the script is already non-interactive.

## Expected File Changes

- `pyproject.toml` — create.
- `src/ideology_app/__init__.py` — create.
- `src/ideology_app/main.py` — create.
- `tests/test_health.py` — create.
- `init.sh` — replace with the bootstrapped gate described above; keep it executable.
- `ARCHITECTURE.md` — create (see below).
- `PROGRESS.md`, `feature_list.json` — update this feature's state and evidence only.

## Visual Design Impact

- UI involved: no
- Design source: not applicable
- Screens or states affected: none
- New design artifact required: no

## Durable Documentation Impact

- `ARCHITECTURE.md`: create — this feature establishes the package layout, the runtime surface (ASGI app module, `/health`) and the verification gate. Keep it short: layout, runtime surface, gate, and how to add a verify step.
- `CONSTRAINTS.md`: not needed — there's no durable MUST/MUST NOT rule beyond what `AGENTS.md` already states.
- `AGENTS.md`: not needed — the startup path is still `./init.sh`.
- Other docs: none.

## Implementation Plan

1. Create `pyproject.toml` and the package with the health endpoint.
2. Add the health test.
3. Replace `init.sh` with the gate.
4. Run the verification plan, including Scenario 1 on a copy without `.venv` and Scenario 4 on a copy with a broken test.
5. Write `ARCHITECTURE.md`; update `feature_list.json` (`passing` plus evidence) and `PROGRESS.md`.

## Implementation Tasks

- [ ] `pyproject.toml` with the metadata, deps, dev extra and pytest config above.
- [ ] `src/ideology_app/__init__.py` and `src/ideology_app/main.py`.
- [ ] `tests/test_health.py`: asserts 200 and the exact JSON body.
- [ ] New `init.sh` with venv creation, install, the `run_step` helper and a step list free of word-splitting.
- [ ] `chmod +x init.sh`.
- [ ] `ARCHITECTURE.md`.
- [ ] Update this feature in `feature_list.json` and add a session entry to `PROGRESS.md`.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → `==> pytest`, `1 passed`, `All checks passed.`, exit 0, with no server process left behind.
- `.venv/bin/python -m pytest -W error` → passes with no warnings.
- Scenario 1: copy the repo to a scratch directory outside the repo, without `.venv`, and run `CI=true ./init.sh` → exit 0.
- Scenario 4: in a scratch copy, break the assertion and run `./init.sh` → `FAILED: pytest`, exit 1. Never edit the real test for this.
- Scenario 3: `.venv/bin/uvicorn ideology_app.main:app --port 8000`, then `curl -s -w ' %{http_code}\n' http://127.0.0.1:8000/health` → `{"status":"ok"} 200`, and `/nope` → 404. Stop the server afterwards.
- Run `init.sh` once from another directory (`cd /tmp && /path/to/init.sh`) → still exits 0.
- E2E: no E2E harness exists and there is no user flow; the TestClient test plus the curl smoke cover it.

## Evidence To Capture

- `init.sh` output summary and exit codes for scenarios 1, 2 and 4.
- The `pytest -W error` result.
- The curl output for `/health` and the 404.
- The installed versions of fastapi, starlette, uvicorn, pytest and httpx2.

Record evidence only in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist

- [ ] Only the files listed above changed; no DB, LLM, UI or JS tooling.
- [ ] Scenarios 1–4 pass when re-run by the validator.
- [ ] `init.sh` never starts a server, works from any directory, and doesn't word-split step arguments.
- [ ] `pytest -W error` is clean.
- [ ] `ARCHITECTURE.md` matches the code.
- [ ] `feature_list.json` (only this entry) and `PROGRESS.md` are updated with real evidence.
- [ ] No unrelated product behavior or extra feature work was added.
