# Feature Implementation Spec: Persist Elections and Parties

## Source Feature

- `id`: db-schema-elections-parties
- `area`: data
- `depends_on`: bootstrap-app-skeleton (`accepted`)
- `status`: not_started
- `source`: `feature_list.json`

## Goal

Give the app its persistence layer and its first Operator surface. Elections and their Parties (ballot tickets) are stored through SQLAlchemy, the schema is created only by Alembic migrations, and an `ideology` CLI lets the Operator apply migrations, create an Election, add Parties to it, and list both. SQLite is the local default; the schema must stay portable to PostgreSQL. Later features (Source Documents, Pipeline Runs, Dataset Versions) add tables on top of this layer.

## Non-Goals

- Election status transitions (`draft` → `active` → `archived`). Elections are always created as `draft`; nothing in this feature changes the status.
- Editing or deleting Elections or Parties, Party logos, a Country table, Source Documents, or any other entity.
- HTTP endpoints, an admin page, or authentication. The FastAPI app does not touch the database yet.
- A PostgreSQL driver dependency or a live PostgreSQL test. Portability is checked by rendering the migration's PostgreSQL DDL offline.
- Packaging the migrations for a non-editable wheel install. `init.sh` installs editable, and that is the only supported mode.
- Changes to `init.sh` (see Verification Plan).

## Job Story

When I set up a new Election for the VAA,
I want to register it and its ballot tickets from the command line,
so that later Source Documents and Pipeline Runs have something to belong to.

## Users And Permissions

- Operator: has CLI-only access with no authentication (`docs/technical-discovery.md`). Anyone with shell access to the database URL is the Operator.
- Voter: not affected.

## Acceptance Scenarios

### Scenario 1: Migrations on an empty database

Given an empty SQLite file
When `ideology db upgrade` runs (or `run_migrations(url)` in tests)
Then the tables `elections`, `parties` and `alembic_version` exist at head, a second run is a no-op, and `downgrade base` removes both domain tables.

### Scenario 2: Create and list an Election with its Parties

Given a migrated database
When the Operator runs `ideology election create --country es --type general --date 2023-07-23 --name "Elecciones generales 2023"`, then `ideology party add --election 1 --name "Sumar" --short-name SUMAR` and `ideology party add --election 1 --name "Partido Popular" --short-name PP`
Then each command exits 0 and prints the new id. `ideology election list` shows the Election with country `ES`, type `general`, date `2023-07-23` and status `draft`, and `ideology party list --election 1` shows both Parties in creation order.

### Scenario 3: Invalid input is rejected

Given a migrated database
When the Operator passes a bad country (`ESP`, `1A`), an unknown type (`regional`), a malformed date (`23/07/2023`), or an empty or whitespace-only name or short name
Then the command exits non-zero with a message naming the bad field, and nothing is written.

### Scenario 4: Duplicates and unknown references

Given an Election ES/general/2023-07-23 with a Party named "Sumar" (short name SUMAR)
When the Operator creates the same Election again, adds a Party with the same name or the same short name to that Election, or adds a Party to election id 999
Then the command exits 1 with a clear message (`already exists` / `election 999 not found`), and the rows are unchanged. The same Party name in a different Election is allowed.

### Scenario 5: Database not migrated

Given a database file with no tables
When the Operator runs any `election` or `party` command
Then it exits 1 with `Database is not initialised; run "ideology db upgrade".` and no traceback.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json`: workflow, and this feature's entry. The previous validation left a Low finding about `init.sh`'s `run_step`.
- `CONTEXT.md`, `docs/domain-model.md`: Election (country, type, date, name; `draft`/`active`/`archived`), Party (a ballot ticket with name and short name, per Election).
- `docs/technical-discovery.md`: PostgreSQL, with SQLite acceptable for dev; Operator access is CLI-only or a single admin credential.
- `docs/build-brief.md`, `docs/risks-and-open-questions.md`: nothing blocking this feature.
- `ARCHITECTURE.md`, `pyproject.toml`, `init.sh`, `.gitignore` (`*.db` is already ignored), `src/ideology_app/{__init__,main}.py`, `tests/test_health.py`, `docs/specs/bootstrap-app-skeleton.md`.
- `.venv` (read only): Python 3.15.0, click 8.5.0 (pulled in by uvicorn); no SQLAlchemy or Alembic.

### Existing Patterns To Follow

- The package uses the src layout, with tests in `tests/` and type hints on functions.
- `init.sh` runs `pip install -e '.[dev]'` and then pytest. New dependencies go in `pyproject.toml`, so the gate picks them up automatically.

### Throwaway-Venv Findings (Python 3.15.0, outside the repo)

- SQLAlchemy 2.1.4, Alembic 1.20.0, click 8.5.0 and Mako 1.4.3 install from wheels.
- `script_location="<pkg>:migrations"` and programmatic `alembic.config.Config` work, as do upgrade, downgrade and offline `--sql` for `postgresql://`. The offline render needs no psycopg.
- **Autogenerate emits the non-native Enum CHECK three times** (once from `sa.Enum(create_constraint=True)` and twice as explicit `sa.CheckConstraint`). On PostgreSQL that means duplicate constraint names. After deleting the explicit `sa.CheckConstraint` lines, each CHECK appears exactly once, and `compare_metadata` reports no drift.
- A multi-column `uq_%(table_name)s_%(column_0_name)s` convention gives misleading names such as `uq_elections_country`. Use `column_0_N_name`.
- An engine that is never disposed prints `ResourceWarning: unclosed database` on 3.15. Inside pytest, this surfaces as an unraisable-exception warning.

### Current Gaps

- There is no database layer, configuration, CLI or migration tooling. All of it is created here.

## Technical Approach

- **Dependencies** (`pyproject.toml`): `sqlalchemy>=2.0`, `alembic>=1.13`, `click>=8.1` (listed explicitly because the code imports it). Add `[project.scripts] ideology = "ideology_app.cli:main"`. In `[tool.pytest.ini_options]`, add `filterwarnings = ["error"]` so leaked connections and deprecations fail the gate.
- **Config** (`src/ideology_app/config.py`): `database_url() -> str` returns `os.environ["DATABASE_URL"]` when it is set, otherwise `sqlite:///ideology.db`, which is relative to the current directory (the same file `*.db` already ignores). No settings library.
- **Engine and sessions** (`src/ideology_app/db.py`):
  - `make_engine(url: str | None = None) -> Engine`: for SQLite URLs it adds a `connect` event listener that runs `PRAGMA foreign_keys=ON`.
  - `session_scope(engine)`: a context manager that commits on success and rolls back on error.
  - `run_migrations(url, revision="head")` and `downgrade(url, revision)`: build an `alembic.config.Config` in code, with `script_location` set to the package's `migrations` directory and `sqlalchemy.url` set to the URL.
  - `is_initialised(engine) -> bool`: `inspect(engine).has_table("alembic_version")` and `has_table("elections")`.
  - Callers own the engine and must call `engine.dispose()`. Every code path that creates an engine disposes it in a `finally` block or a `call_on_close`: `env.py`, the CLI, and the test fixtures.
- **Models** (`src/ideology_app/models.py`):
  - `Base(DeclarativeBase)` with a `MetaData(naming_convention=…)`:
    - `pk_%(table_name)s`
    - `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`
    - `uq_%(table_name)s_%(column_0_N_name)s`
    - `ck_%(table_name)s_%(constraint_name)s`
    - `ix_%(column_0_label)s`
  - `ElectionType(StrEnum)`: `general`. `ElectionStatus(StrEnum)`: `draft`, `active`, `archived`. Both use `sa.Enum(..., native_enum=False, create_constraint=True, length=20, values_callable=lambda e: [m.value for m in e], name="election_type" | "election_status")`. The values are stored in lowercase. `length=20` leaves room for later types without changing the column length.
  - `Election` (`elections`): `id` int PK, `country` String(2) not null, `type` (ElectionType, not null), `date` Date not null, `name` String(200) not null, `status` (ElectionStatus, not null, default `draft`). Unique `(country, type, date)`. Relationship `parties`, ordered by `Party.id`.
  - `Party` (`parties`): `id` int PK, `election_id` FK `elections.id` `ON DELETE CASCADE` not null, `name` String(200) not null, `short_name` String(50) not null. Unique `(election_id, name)` and `(election_id, short_name)`.
- **Migrations** (`src/ideology_app/migrations/`: `env.py`, `script.py.mako`, `versions/0001_elections_parties.py`, `rev_id="0001"`):
  - `env.py` takes the URL from the config, falling back to `database_url()`. It supports offline mode and online mode with `render_as_batch=True`, so later SQLite `ALTER`s work, and it disposes its engine.
  - Generate the revision with autogenerate, then **delete the duplicated `sa.CheckConstraint` lines**, so each enum CHECK appears exactly once.
  - Add a root `alembic.ini` with `script_location = %(here)s/src/ideology_app/migrations` and no URL, so `.venv/bin/alembic revision --autogenerate` works for later features.
- **Domain service** (`src/ideology_app/elections.py`): plain functions that take a `Session`.
  - `create_election(session, *, country, type, date, name) -> Election`: strips the input, uppercases the country, and checks it against `^[A-Z]{2}$`. `type` must be an `ElectionType` value, and `name` must be non-empty. Status is always `draft`.
  - `add_party(session, *, election_id, name, short_name) -> Party`: the Election must exist, and the name and short name are stripped and must be non-empty.
  - `list_elections(session)`, ordered by `date`, then `id`, and `list_parties(session, election_id)`, ordered by `id`. Both raise `NotFoundError` for an unknown Election.
  - Errors: `ElectionsError` with the subclasses `InvalidInputError`, `NotFoundError` and `DuplicateError`. A duplicate is detected by catching `IntegrityError` on `flush()`, then rolling back and raising `DuplicateError`. Don't pre-query instead.
- **CLI** (`src/ideology_app/cli.py`, click):
  - `main` is a group. Its callback creates the engine from `--database-url` (default: `database_url()`, envvar `DATABASE_URL`), stores it in `ctx.obj`, and registers `ctx.call_on_close(engine.dispose)`.
  - Commands:
    - `db upgrade`: runs the migrations to head and prints `Database at <url, password hidden> is at head`.
    - `election create --country --type --date --name`: `--date` uses `click.DateTime(["%Y-%m-%d"])` and is converted to `date`. Prints `Created election <id>`.
    - `election list`: a tab-separated table with the header `id country type date status name`.
    - `party add --election ID --name --short-name`: prints `Created party <id>`.
    - `party list --election ID`: a tab-separated table with the header `id short_name name`.
  - Every `election` and `party` command first checks `is_initialised` (Scenario 5). Service errors are mapped to `click.ClickException`, which exits 1 and writes `Error: …` to stderr. Click's own type errors exit 2. An empty list prints only the header.

## Expected File Changes

- `pyproject.toml`: modify (dependencies, script entry point, `filterwarnings`).
- `alembic.ini`: create.
- `src/ideology_app/config.py`, `db.py`, `models.py`, `elections.py`, `cli.py`: create.
- `src/ideology_app/migrations/env.py`, `script.py.mako`, `versions/0001_elections_parties.py`: create.
- `tests/conftest.py`, `tests/test_migrations.py`, `tests/test_elections.py`, `tests/test_cli.py`: create.
- `ARCHITECTURE.md`: update. `CONSTRAINTS.md`: create.
- `PROGRESS.md`, `feature_list.json`: update this feature's entry only.

## Visual Design Impact

- UI involved: no. Design source: not applicable. No new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add a Data layer section (config → `db` → `models`; `elections` service; Alembic in `ideology_app/migrations`), the CLI runtime surface (`ideology …` commands, `DATABASE_URL`), and how to add a migration.
- `CONSTRAINTS.md`: create, with durable rules:
  - The schema changes only through Alembic revisions under `src/ideology_app/migrations/versions/`, and autogenerated revisions are reviewed by hand (the duplicate-CHECK finding).
  - DDL and queries stay portable to PostgreSQL: no SQLite-only types or SQL; enums are non-native with a single CHECK.
  - Every Engine that is created is disposed.
  - Tests use a temporary SQLite database, never `ideology.db`.
- `AGENTS.md`: not needed. The startup path is unchanged.
- Other docs: none. The domain docs already describe Election and Party.

## Implementation Plan

1. Add the dependencies, the entry point and `filterwarnings` to `pyproject.toml`, then reinstall with `./init.sh`.
2. Write `config.py`, `db.py` and `models.py`.
3. Add the Alembic scaffolding and `alembic.ini`. Autogenerate revision `0001` against a scratch database, remove the duplicate CHECKs, and confirm that a drift check reports no differences.
4. Write the `elections.py` service and then `cli.py`.
5. Write the tests, then run the verification plan.
6. Update `ARCHITECTURE.md` and create `CONSTRAINTS.md`. Record the evidence in `feature_list.json` (status `passing`) and in `PROGRESS.md`.

## Implementation Tasks

- [ ] `pyproject.toml` changes.
- [ ] `config.py`, plus `db.py` with the SQLite FK pragma, `session_scope`, `run_migrations`, `downgrade` and `is_initialised`.
- [ ] `models.py` with the naming convention, both enums and both tables.
- [ ] Migrations: `env.py` (disposes its engine, handles offline mode) and revision `0001` with each CHECK appearing once.
- [ ] `alembic.ini` at the root.
- [ ] `elections.py` service and its error types.
- [ ] `cli.py` with the `db`, `election` and `party` groups, and the initialisation check.
- [ ] `tests/conftest.py`: a `db_url` fixture (`sqlite:///{tmp_path}/test.db`) and a `migrated_engine` fixture that runs the migrations, yields `make_engine(db_url)` and disposes it. Also a `session` fixture.
- [ ] `test_migrations.py`:
  - Upgrade on an empty file creates the tables and stamps `0001`.
  - Upgrading twice is a no-op.
  - Downgrade to `base` removes the domain tables.
  - `compare_metadata` against `Base.metadata` reports no drift.
  - Raw inserts with a bogus `status` or `type`, or a Party whose `election_id` does not exist, raise `IntegrityError`.
  - The offline PostgreSQL render (`Config(output_buffer=io.StringIO())`, `command.upgrade(cfg, "head", sql=True)`) contains `CREATE TABLE elections` and `CREATE TABLE parties`, and each of `ck_elections_election_status` and `ck_elections_election_type` exactly once.
- [ ] `test_elections.py`:
  - Create and list, with status `draft` and the country uppercased.
  - Each invalid field from Scenario 3 is rejected.
  - Each duplicate from Scenario 4 is rejected, and the same Party name in another Election is allowed.
  - Unknown Election ids raise `NotFoundError`.
  - After a `DuplicateError`, the session is still usable.
- [ ] `test_cli.py`: uses `click.testing.CliRunner` and `--database-url`, never the default file. It covers Scenarios 1, 2, 4 and 5 end to end through the commands, including exit codes and output lines, plus one Click type-error case (bad date, exit 2).
- [ ] Docs and evidence updates.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → the `install` and `pytest` steps pass, `All checks passed.`, exit 0.
- `.venv/bin/python -m pytest -W error -p no:cacheprovider` passes; the `filterwarnings` setting already makes warnings errors. `.venv/bin/python -X dev -W error -m pytest` is also clean, with no `ResourceWarning`.
- Manual CLI smoke in a scratch directory outside the repo:
  1. `export DATABASE_URL=sqlite:////<scratch>/smoke.db`
  2. `.venv/bin/ideology election list` → the Scenario 5 error, exit 1.
  3. `db upgrade`, then the Scenario 2 commands, then both list commands → the expected rows.
  4. Re-run the create command → `already exists`, exit 1.
  5. Delete the scratch database.
- `.venv/bin/alembic -c alembic.ini history` lists revision `0001`, which shows the root `alembic.ini` resolves the script location. The offline PostgreSQL render is covered by a test.
- Confirm `git status` shows no `ideology.db` or other database file in the repo after the tests.
- `init.sh` is unchanged. This feature adds no verify step: the migration checks run inside pytest. The `run_step`/`set -e` Low finding stays deferred to the feature that next adds a multi-command step.
- E2E: no E2E harness exists and there is no HTTP or UI flow. The CliRunner tests are the end-to-end coverage for this Operator flow.

## Evidence To Capture

- The `init.sh` summary and exit code, and the pytest pass count.
- The `pytest -W error` and `-X dev` results.
- The CLI smoke transcript (commands, the key output lines, and exit codes).
- The installed versions of sqlalchemy, alembic and click.
- Confirmation that the offline PostgreSQL DDL renders each CHECK once.

## Validator Checklist

- [ ] Only the files listed above changed. There are no status transitions, edit or delete commands, HTTP endpoints or extra entities.
- [ ] Scenarios 1 to 5 pass when the validator re-runs them, through both pytest and the CLI smoke.
- [ ] The migration has each CHECK once, there is no drift against the models, and the PostgreSQL render is valid.
- [ ] Every engine is disposed: `-X dev -W error` is clean, and the CLI uses `call_on_close`.
- [ ] Tests never touch `ideology.db`, and no database file is left in the repo.
- [ ] `ARCHITECTURE.md` and `CONSTRAINTS.md` match the code.
- [ ] `feature_list.json` (this entry only) and `PROGRESS.md` are updated with real evidence.
