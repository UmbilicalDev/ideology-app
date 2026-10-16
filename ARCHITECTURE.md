# Architecture

Current state after `bootstrap-app-skeleton`. Keep this short; update it when layers, runtime surfaces or boundaries change.

## Layout

- Python package in src layout: `src/ideology_app/`, installed editable via `pip install -e '.[dev]'` (`pyproject.toml`, setuptools backend, `requires-python >=3.12`).
- Domain, pipeline and adapter modules will live under `src/ideology_app/` as features add them.
- Tests live in `tests/` and run with pytest (`[tool.pytest.ini_options]` in `pyproject.toml`).

## Runtime Surface

- ASGI app: `ideology_app.main:app` (FastAPI).
- Endpoints: `GET /health` → `200 {"status": "ok"}`.
- Start locally: `.venv/bin/uvicorn ideology_app.main:app --reload`.
- Test client: `fastapi.testclient.TestClient`, backed by `httpx2` (Starlette deprecates `httpx` for the test client).

## Verification Gate

- `./init.sh` runs from its own directory, creates `.venv` if missing (`${PYTHON:-python3} -m venv`), then runs ordered steps through `run_step <name> <function>`, which prints `==> <name>` and exits 1 with `FAILED: <name>` on failure.
- Current steps: `install` (`pip install -e '.[dev]'`), `pytest`.
- To add a step, define a `step_<name>` function and add a `run_step` line after the existing ones. Steps are functions so their arguments are never word-split.
- `init.sh` never starts a server; it only prints the start command after all checks pass.
