# Architecture

Current state after `source-document-upload`. Keep this short; update it when layers, runtime surfaces or boundaries change.

## Layout

- Python package in src layout: `src/ideology_app/`, installed editable via `pip install -e '.[dev]'` (`pyproject.toml`, setuptools backend, `requires-python >=3.12`).
- Domain, pipeline and adapter modules will live under `src/ideology_app/` as features add them.
- Tests live in `tests/` and run with pytest (`[tool.pytest.ini_options]` in `pyproject.toml`).

## Data Layer

- Dependency direction: `config` → `db` → `models` → `elections` / `source_documents` (services; `source_documents` also uses `pdf_text`) → `cli`. The FastAPI app does not touch the database yet.
- `ideology_app.config.database_url()`: `$DATABASE_URL`, else `sqlite:///ideology.db` (relative to the current directory; `*.db` is git-ignored). SQLite is the dev default; PostgreSQL is the target.
- `ideology_app.config.source_files_dir()`: `$SOURCE_FILES_DIR`, else `source_files/` relative to the current directory (git-ignored). Uploaded Source Document files are stored there content-addressed as `<content_hash>.pdf` (lowercase hex SHA-256), written via a temp file + `os.replace`, never overwritten; Source Documents of different Parties with the same bytes share one file. Local disk only (no object storage yet).
- `ideology_app.db`: `make_engine(url)` (SQLite gets `PRAGMA foreign_keys=ON`), `session_scope(engine)` (commit/rollback), `alembic_config(url)`, `run_migrations(url, revision="head")`, `downgrade(url, revision)`, `is_initialised(engine)`. Callers own and dispose every Engine.
- `ideology_app.models`: `Base` with a constraint naming convention (`pk_`, `fk_`, `uq_<table>_<col>_<col>`, `ck_<table>_<name>`, `ix_`); `Election` (`elections`: country, type, date, name, status; unique country+type+date) and `Party` (`parties`: election_id FK cascade, name, short_name; unique per Election). `SourceDocument` (`source_documents`: party_id FK cascade + index, origin `upload`/`url`, status `registered`/`fetched`/`parsed`/`failed`, original_filename, content_hash, page_count, failure_reason, created_at; unique party_id+content_hash) and `SourceDocumentPage` (`source_document_pages`: source_document_id FK cascade, page_number ≥ 1, text; unique per document). Enums (`ElectionType`, `ElectionStatus`, `SourceDocumentOrigin`, `SourceDocumentStatus`) are non-native strings with one CHECK each.
- `ideology_app.elections`: plain functions taking a `Session` (`create_election`, `add_party`, `list_elections`, `list_parties`) that validate input and raise `InvalidInputError` / `NotFoundError` / `DuplicateError` (all `ElectionsError`). Duplicates are detected from `IntegrityError` on flush.
- `ideology_app.pdf_text`: the PDF adapter and the only module that imports `pypdf`. `extract_pages(bytes) -> list[str]` (one string per page, NUL removed, empty pages kept as `""`) or `PdfTextError(reason, page_count)` with reasons `PDF is encrypted`, `could not read PDF: <Exc>: <msg>` (≤ 500 chars), `PDF has no pages`, `no text layer found (scanned PDF?); OCR is not supported`.
- `ideology_app.source_documents`: `add_uploaded_document(session, party_id, file_path, files_dir)` validates (Party exists, regular file, 0 < size ≤ 50 MiB, starts with `%PDF-`), inserts the row (`registered`; duplicate party+hash → `DuplicateError`), stores the file (`fetched`), then extracts pages (`parsed` + page rows, or `failed` + `failure_reason`). `list_documents`, `get_document`. Reuses the `elections` error classes.
- Migrations: Alembic in `src/ideology_app/migrations/` (`script_location = ideology_app:migrations` in code; root `alembic.ini` for developer commands). `env.py` reads the URL from the config or `database_url()`, supports offline `--sql`, uses `render_as_batch=True`, and disposes its engine.
- Add a migration: change `models.py`, then `DATABASE_URL=sqlite:///<scratch>/gen.db .venv/bin/alembic -c alembic.ini upgrade head` and `... revision --autogenerate --rev-id 000N -m "..."`, review the file by hand (see `CONSTRAINTS.md`), and check `... alembic -c alembic.ini check` reports no drift. `tests/test_migrations.py` checks upgrade/downgrade, drift and the offline PostgreSQL render.

## Runtime Surface

- ASGI app: `ideology_app.main:app` (FastAPI).
- Endpoints: `GET /health` → `200 {"status": "ok"}`.
- Start locally: `.venv/bin/uvicorn ideology_app.main:app --reload`.
- Operator CLI: `.venv/bin/ideology` (`ideology_app.cli:main`, click; global `--database-url`, envvar `DATABASE_URL`): `db upgrade`, `election create --country --type --date --name`, `election list`, `party add --election --name --short-name`, `party list --election`, `source add --party --file` (prints `Created source document N: parsed (P pages)`; a `failed` document is committed, then reported as `Error: source document N failed: <reason>`, exit 1), `source list --party`, `source text --document [--page]`. Lists are tab-separated with a header (empty cells for nulls). Service errors exit 1 (`Error: …` on stderr), click usage errors exit 2, and `election`/`party`/`source` commands on a database not migrated to head (every domain table present) exit 1 with `Database is not initialised; run "ideology db upgrade".`
- Test client: `fastapi.testclient.TestClient`, backed by `httpx2` (Starlette deprecates `httpx` for the test client).

## Verification Gate

- `./init.sh` runs from its own directory, creates `.venv` if missing (`${PYTHON:-python3} -m venv`), then runs ordered steps through `run_step <name> <function>`, which prints `==> <name>` and exits 1 with `FAILED: <name>` on failure.
- Current steps: `install` (`pip install -e '.[dev]'`), `pytest`. Pytest runs with `filterwarnings = ["error"]`, so warnings (including leaked-connection `ResourceWarning`s) fail the gate. Migration checks run inside pytest.
- To add a step, define a `step_<name>` function and add a `run_step` line after the existing ones. Steps are functions so their arguments are never word-split.
- `init.sh` never starts a server; it only prints the start command after all checks pass.
