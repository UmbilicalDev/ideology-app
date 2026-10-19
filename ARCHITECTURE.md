# Architecture

Current state after `db-schema-elections-parties` and `llm-provider-abstraction`. Keep this short; update it when layers, runtime surfaces or boundaries change.

## Layout

- Python package in src layout: `src/ideology_app/`, installed editable via `pip install -e '.[dev]'` (`pyproject.toml`, setuptools backend, `requires-python >=3.12`).
- Domain, pipeline and adapter modules will live under `src/ideology_app/` as features add them.
- Tests live in `tests/` and run with pytest (`[tool.pytest.ini_options]` in `pyproject.toml`).

## Data Layer

- Dependency direction: `config` → `db` → `models` → `elections` (service) → `cli`. The FastAPI app does not touch the database yet.
- `ideology_app.config.database_url()`: `$DATABASE_URL`, else `sqlite:///ideology.db` (relative to the current directory; `*.db` is git-ignored). SQLite is the dev default; PostgreSQL is the target.
- `ideology_app.db`: `make_engine(url)` (SQLite gets `PRAGMA foreign_keys=ON`), `session_scope(engine)` (commit/rollback), `alembic_config(url)`, `run_migrations(url, revision="head")`, `downgrade(url, revision)`, `is_initialised(engine)`. Callers own and dispose every Engine.
- `ideology_app.models`: `Base` with a constraint naming convention (`pk_`, `fk_`, `uq_<table>_<col>_<col>`, `ck_<table>_<name>`, `ix_`); `Election` (`elections`: country, type, date, name, status; unique country+type+date) and `Party` (`parties`: election_id FK cascade, name, short_name; unique per Election). Enums (`ElectionType`, `ElectionStatus`) are non-native strings with one CHECK each.
- `ideology_app.elections`: plain functions taking a `Session` (`create_election`, `add_party`, `list_elections`, `list_parties`) that validate input and raise `InvalidInputError` / `NotFoundError` / `DuplicateError` (all `ElectionsError`). Duplicates are detected from `IntegrityError` on flush.
- Migrations: Alembic in `src/ideology_app/migrations/` (`script_location = ideology_app:migrations` in code; root `alembic.ini` for developer commands). `env.py` reads the URL from the config or `database_url()`, supports offline `--sql`, uses `render_as_batch=True`, and disposes its engine.
- Add a migration: change `models.py`, then `DATABASE_URL=sqlite:///<scratch>/gen.db .venv/bin/alembic -c alembic.ini upgrade head` and `... revision --autogenerate --rev-id 000N -m "..."`, review the file by hand (see `CONSTRAINTS.md`), and check `... alembic -c alembic.ini check` reports no drift. `tests/test_migrations.py` checks upgrade/downgrade, drift and the offline PostgreSQL render.

## LLM Providers

- Package `src/ideology_app/llm/`: `base.py` (`LLMRequest[T]` with `task`, `system`, `prompt`, `schema` (a pydantic model), `max_tokens=4096`; `LLMResult[T]` with `output`, `provider`, `model`, `input_tokens`, `output_tokens`; the `LLMProvider` protocol with `name`, `model`, `generate(request) -> LLMResult`; errors `LLMError` > `LLMConfigError` (also a `config.ConfigError`), `LLMOutputError`, `LLMProviderError`), `fake.py` (`FakeProvider`), `anthropic_provider.py` (`AnthropicProvider`), `__init__.py` (re-exports, `PROVIDERS` registry, `build_provider`).
- Selection: `build_provider(llm_settings())`. `PROVIDERS` / `build_provider` is the only place that branches on the provider name. Callers depend on the `LLMProvider` protocol, never on a concrete class.
- Configuration (`ideology_app.config`): `LLM_PROVIDER` (`anthropic` default, or `fake`), `LLM_MODEL` (default per provider from `DEFAULT_MODELS`: `anthropic` -> `claude-sonnet-5-5`, `fake` -> `fake-model`), `GENERATION_MODE` (`GenerationMode.PRECOMPUTED` default, or `LIVE`; parsed only, no behaviour yet). Values are trimmed, case-insensitive, and blank means unset. Invalid values raise `ConfigError` (a `ValueError`) listing the supported values. `ANTHROPIC_API_KEY` is read only by `AnthropicProvider`, lazily on the first `generate`.
- `FakeProvider(responses, model="fake-model")`: canned responses keyed by `task` (dict, schema instance, or callable `(request) -> dict | model`), validated against the schema; records `calls`; deterministic word-count token numbers. Unknown task -> `LLMError`; schema mismatch -> `LLMOutputError`.
- `AnthropicProvider(model, *, client=None, api_key=None, max_retries=2, timeout=120.0)`: `client.messages.parse(..., output_format=request.schema)` (SDK structured output, `output_config.format.type == "json_schema"`). Maps `pydantic.ValidationError`, refusals and missing parsed output to `LLMOutputError`, and `anthropic.APIError` to `LLMProviderError` (class name and HTTP status only). Closes only a client it created (`close()` / `with`). Retries are the SDK's `max_retries`.
- Dependency direction: `config` -> `llm`. `config` never imports `llm`. Nothing else imports `llm` yet; pipeline features will.
- Add a provider: write `src/ideology_app/llm/<name>_provider.py` implementing the protocol, add one entry to `PROVIDERS` and one to `config.DEFAULT_MODELS`.
- Tests: `tests/test_llm.py` (config, registry, fake) and `tests/test_llm_anthropic.py` (adapter through an injected `anthropic.Anthropic` with an `httpx2.MockTransport` `http_client`). Each has an autouse guard that unsets the LLM env vars and blocks `socket.socket.connect` / `socket.create_connection`.

## Runtime Surface

- ASGI app: `ideology_app.main:app` (FastAPI).
- Endpoints: `GET /health` → `200 {"status": "ok"}`.
- Start locally: `.venv/bin/uvicorn ideology_app.main:app --reload`.
- Operator CLI: `.venv/bin/ideology` (`ideology_app.cli:main`, click; global `--database-url`, envvar `DATABASE_URL`): `db upgrade`, `election create --country --type --date --name`, `election list`, `party add --election --name --short-name`, `party list --election`. Lists are tab-separated with a header. Service errors exit 1 (`Error: …` on stderr), click usage errors exit 2, and `election`/`party` commands on an unmigrated database exit 1 with `Database is not initialised; run "ideology db upgrade".`
- Test client: `fastapi.testclient.TestClient`, backed by `httpx2` (Starlette deprecates `httpx` for the test client).

## Verification Gate

- `./init.sh` runs from its own directory, creates `.venv` if missing (`${PYTHON:-python3} -m venv`), then runs ordered steps through `run_step <name> <function>`, which prints `==> <name>` and exits 1 with `FAILED: <name>` on failure.
- Current steps: `install` (`pip install -e '.[dev]'`), `pytest`. Pytest runs with `filterwarnings = ["error"]`, so warnings (including leaked-connection `ResourceWarning`s) fail the gate. Migration checks run inside pytest.
- To add a step, define a `step_<name>` function and add a `run_step` line after the existing ones. Steps are functions so their arguments are never word-split.
- `init.sh` never starts a server; it only prints the start command after all checks pass.
