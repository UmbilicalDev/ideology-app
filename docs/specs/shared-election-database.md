# Feature Implementation Spec: One committed SQLite database per Election

## Source Feature

- `id`: shared-election-database
- `area`: platform
- `depends_on`: pipeline-run-checkpoint (`accepted`), source-text-bundle (`not_started` at planning time; this feature starts only once it is `accepted`)
- `source`: `feature_list.json`. Replaces the dropped plan `pipeline-checkpoint-shared` (JSONL checkpoint files and `--resume-from-file`).

## Goal

Several developers on several machines generate data for the same Election. Each local `ideology.db` holds different ids, runs and recorded calls, so a run stopped on one machine cannot be resumed on another, and sessions disagree. This feature makes one SQLite database per Election, committed at `data/elections/<slug>/ideology.db` next to its Source Text Bundle, the single source of truth. A shared checkpoint is simply that database: when a session stops, the Operator commits and pushes it by hand, and another developer pulls it and runs `pipeline run --resume-from R`. Run ids and `request_hash` values are the same everywhere because everyone opens the same file.

User decisions (2026-10-21, binding):
- One DB per Election in git. It is built from scratch with `db upgrade` + `data import` of the bundle. The local DB in `ideology-app-data/e2e-2023/` is not migrated.
- No auto-commit. The app never invokes git.
- One active run per Election at a time (team rule), confirmed by a CLI prompt.
- History growth is accepted. Past Elections' data will be deleted later, keeping only two.

## Non-Goals

- JSONL checkpoint files, `--resume-from-file`, automatic reuse across runs, and git automation (hooks, auto-commit, `git` subprocesses).
- Serving several Elections from one web server, deployment, PostgreSQL, exporting a DB to production.
- Marking stale `running` runs `failed`, locks across machines, and detecting "someone else is generating" (it is a team rule plus a prompt).
- `VACUUM` / `db compact`. The app has no delete path: the local e2e DB has `freelist_count = 0` after two runs, so `VACUUM` would reclaim nothing.
- Running a real Pipeline Run on the 2023 data (`e2e-real-2023-election`).

## Job Story

When my generation session stops (for example, out of tokens),
I want to push the Election's database and let a teammate pull it and resume,
so the team pays for each LLM call once and nobody's data diverges.

## Users And Permissions

- Operator / developer: CLI only. Commits and pushes the DB by hand.
- Voter: not affected. The web server reads whichever DB is configured.

## Behaviour

1. **Selecting the DB.**
   - New setting `ELECTION_DB=<slug>`, also available as the global CLI option `--election-db <slug>` (click `envvar="ELECTION_DB"`).
   - `config.database_url()` resolves the URL in this order:
     - `DATABASE_URL` is the explicit override and is used when set;
     - else `ELECTION_DB` gives `sqlite:///<abs elections_data_dir()>/<slug>/ideology.db`;
     - else the existing default `sqlite:///ideology.db`.
   - Setting both `DATABASE_URL` and `ELECTION_DB`, from flags or env, is an error: `ConfigError` / exit 1, `set either DATABASE_URL (--database-url) or ELECTION_DB (--election-db), not both`. There is no silent precedence.
   - The slug must match `^[a-z]{2}-[a-z]+-\d{4}-\d{2}-\d{2}$`, which also blocks path traversal. `<root>/<slug>/election.toml` must exist (the `bundle_slug` contract of `source-text-bundle`). Otherwise: `ConfigError` `no Election data directory <path> (expected election.toml)`.
   - The web server uses the same resolution with no code change (`create_app` → `make_engine(None)` → `config.database_url()`), so `ELECTION_DB=es-general-2023-07-23 uvicorn ideology_app.main:app` serves that Election. The default is unchanged. An explicit choice keeps an accidental run off the shared file, and there is no "current" Election once there are two.
2. **Shared database.** A database is *shared* when its URL is SQLite with a file path whose resolved path is `<elections_data_dir().resolve()>/<slug>/ideology.db`. The rule is the same whether it was selected by `ELECTION_DB` or by a `DATABASE_URL` that points at that file. Helper `shared_db.shared_slug(url, root=None) -> str | None`. Tests use `tmp_path` DBs, which are never shared, so they stay non-interactive unless a test opts in through `ELECTIONS_DATA_DIR`.
3. **Missing shared file.** With a shared URL whose file does not exist, every `requires_db` command fails before connecting: `no database at <path>; build it with "ideology --election-db <slug> db upgrade" and "data import"`. Only `db upgrade` may create it. This avoids the accepted Low finding that an empty file is created, which here would be un-ignored and committable.
4. **Confirmation before generating on a shared DB.** It applies to `pipeline run` and to `pipeline run-queued` (only when at least one run is queued). After the provider is built and before any write, the CLI prints:
   ```
   Database data/elections/<slug>/ideology.db is shared through git.
   One active run per Election: generate only if you pulled the latest commit of this
   database and nobody else is generating election <slug>.
   Continue? [y/N]:
   ```
   - `--yes` skips the prompt.
   - Without `--yes`, a non-interactive stdin (the seam `cli._stdin_is_interactive()` returns `sys.stdin.isatty()`) refuses with exit 1: `refusing to generate on a shared database without confirmation; pass --yes`.
   - Answering no exits 1 (`Aborted!`).
   - In every refusal no run is created.
5. **Unfinished run guard** (`pipeline run` without `--resume-from`). `runs.find_unfinished_run(session, election_id, provider, model)` takes the Election's highest-id run that has at least one recorded call. It is *unfinished* when:
   - it has no Dataset Version;
   - its status is `running` or `failed`;
   - its provider/model equal the current ones (other runs cannot be resumed anyway).

   What happens then:
   - On a shared DB the command refuses (exit 1, no run created): `election <id> has an unfinished run R (<status>, N recorded calls); resume it with --resume-from R, or pass --fresh to start from zero`. For `running` it adds: `if another developer is generating this Election, stop; a killed run also stays running`.
   - On any other DB the same text is a warning on stderr, and the run continues (current behaviour is kept).
   - `--fresh` with `--resume-from` is a usage error.
6. **Resuming on another machine** needs no new code. `_check_resumable` ignores status, so a run left `running` by a process killed on machine A, or ended `failed: interrupted` by Ctrl-C, is resumable on machine B once B has pulled the file (pipeline-run-checkpoint Scenario 6). The stale `running` row stays as it is (see "Runs stuck in `running`" in the risks doc). Hashes match only when both machines run the same code revision (prompts, chunking, schemas) and the same `LLM_PROVIDER`/`LLM_MODEL`. A prompt change makes misses, not wrong reuse. A different model is refused.
7. **`ideology db check`** (new, read-only, SQLite only) is the safe-to-commit gate. In order:
   1. No `-journal`, `-wal` or `-shm` file next to the DB. A sidecar means a writer is active or crashed mid-write. Stop every `ideology` process, then run any read command once so SQLite rolls back.
   2. Journal mode `delete` (header bytes 18–19 equal `1`).
   3. `PRAGMA integrity_check` = `ok`.
   4. Migration at head.
   5. On a shared DB, the `source-text-bundle` check `check_against_bundle` passes against its own directory.

   It then lists unfinished runs as info: `run R: running|failed, N recorded calls; resume with --resume-from R`. For `running` it adds `commit only if no ideology process is still running it`. It ends with `Safe to commit: yes` (exit 0) or one line per failed check plus `Safe to commit: no` (exit 1). It opens the file with `mode=ro` only after the sidecar check.
8. **Git**:
   - `.gitignore`: keep `*.db`, add `*.db-journal`, `*.db-wal`, `*.db-shm`, then `!data/elections/*/ideology.db`. The planner verified in a scratch repo that only `data/elections/<slug>/ideology.db` gets tracked. Sidecars, other `.db` names and deeper paths stay ignored.
   - `.gitattributes`: append `data/elections/*/ideology.db binary`.
   - The app never sets WAL, and SQLite's default is `delete`, so a file with no sidecar is complete.
9. **Committed 2023 DB.** This feature commits `data/elections/es-general-2023-07-23/ideology.db`, built from scratch with no runs:
   - `GENERATION_MODE=precomputed ideology --election-db es-general-2023-07-23 db upgrade`;
   - then `data import data/elections/es-general-2023-07-23`;
   - then `db check`.

   Pipeline runs on it belong to `e2e-real-2023-election`. Expected size is about 4 MB (the local e2e DB was 4.0 MB before any run). A full run adds about 0.4–0.7 MB (281 recorded calls = 372 KB of output).

## Acceptance Scenarios

1. **Resolution.**
   - With `ELECTIONS_DATA_DIR=<tmp>/data/elections` and a bundle `<slug>/election.toml`, `--election-db <slug>` and `ELECTION_DB=<slug>` open `<tmp>/data/elections/<slug>/ideology.db`.
   - `db upgrade` creates it, and `election list` shows the imported Election.
   - Both settings set → exit 1 with the "not both" message.
   - A bad slug or a missing directory → exit 1, and no file is created.
   - `create_app()` with `ELECTION_DB` serves that Election from `/api/v1/elections`.
2. **Missing shared file.** `pipeline list --election 1` with `--election-db <slug>` and no `ideology.db` → exit 1 with the build hint, and no file is created.
3. **Confirmation.** On a shared tmp DB:
   - `pipeline run --election 1` without `--yes` refuses: exit 1, the message, `pipeline_runs` empty.
   - With `_stdin_is_interactive` patched to `True`, input `n` → exit 1 and no run; input `y` → the run executes.
   - `--yes` → it executes with no prompt.
   - `run-queued` behaves the same, and does not prompt when nothing is queued.
   - A non-shared DB never prompts (all existing CLI tests unchanged).
4. **Unfinished run.** A FakeProvider run that stops at call 4 (`failed`) on a shared DB:
   - a new `pipeline run --yes` refuses and names `--resume-from 1`, and no run is created;
   - `--fresh` starts run 2 from zero;
   - the same state on a non-shared DB prints the warning and runs.
   - A killed run left `running` gives the `running` wording.
   - A latest run with a Dataset Version, or with another model, gives no guard.
5. **Another machine.**
   - Machine A: `<tmp>/a/data/elections/<slug>/` holds a bundle, built with `db upgrade` + `data import`. Run 1 stops at call 4.
   - The bundle directory, including `ideology.db`, is copied to `<tmp>/b/...`. The test chdirs to `<tmp>/b`.
   - There, `pipeline run --election 1 --resume-from 1 --yes` calls the provider only for the missing calls, records 3 reused calls, and ends with the same Statements as an uninterrupted run.
   - Run ids are the same in both files.
6. **`db check`.**
   - A freshly imported shared DB → `Safe to commit: yes`.
   - Each of these → exit 1 naming the problem, and the file is unchanged:
     - a `-journal` (or `-wal`) sidecar present;
     - WAL mode, set in a scratch copy;
     - a DB one migration behind head;
     - a page row edited directly (bundle mismatch).
   - A stopped run is listed with its resume hint and still exits 0.
   - A non-SQLite URL exits 1 with `db check supports SQLite databases only`.
7. **Committed DB** (`tests/test_committed_databases.py`, read-only). For every `data/elections/*/ideology.db` under the repo root (an absolute path, since conftest chdirs to `tmp_path`):
   - opened with `mode=ro`;
   - at migration head;
   - header journal bytes `1`;
   - `integrity_check` `ok`;
   - `check_against_bundle` empty.

   For 2023 the DB also has 9 Parties, and its page text equals the `.md` files.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json` (this entry, sibling, `e2e-real-2023-election`), `CONSTRAINTS.md`, `ARCHITECTURE.md`, `docs/technical-discovery.md` (runbook, Configuration Points), `docs/risks-and-open-questions.md` (the `pipeline-checkpoint-shared` settled line, "Runs stuck in `running`", "Usage limits", "SQLite downgrades that recreate a table", the Low finding on missing SQLite files), `.gitignore`, `init.sh`.
- `docs/specs/pipeline-run-checkpoint.md`, `docs/specs/source-text-bundle.md` (shared contract: `elections_data_dir`, `bundle_slug`, `check_against_bundle`, `data check`, `ideology.db` reserved and ignored by the manifest reader).
- `src/ideology_app/config.py` (`database_url`), `db.py` (`make_engine`, `is_initialised`, no journal pragma), `cli.py` (`main` options, `requires_db`, `pipeline run|run-queued`), `main.py` (`create_app` lifespan engine), `migrations/env.py` (falls back to `config.database_url()`), `pipeline/checkpoint.py`, `pipeline/runs.py` (`queue_run`, `_check_resumable` has no status check, `execute_run` Ctrl-C → `failed: interrupted`), `tests/conftest.py` (unsets `DATABASE_URL`, chdir to `tmp_path`), `tests/test_pipeline_checkpoint.py` (`Stopping` provider, CLI helper).
- Read-only look at `ideology-app-data/e2e-2023/ideology.db`: journal `delete`, 1154 pages of 4 KiB, freelist 0, 281 recorded calls.

### Current Gaps

- No Election-scoped DB selection, no shared-DB notion, no confirmation, no `db check`. `.gitignore` does not ignore `-journal`/`-wal`/`-shm`. There is no `data/` yet (it comes from the sibling).

## Technical Approach

- `config.py`: `election_db()` returns the slug or `None` (trimmed, blank = unset, validated). `database_url()` follows Behaviour 1. `ConfigError` is raised for both-set, a bad slug or a missing directory. Imports stay stdlib-only (no `source_bundle` import; the existence check is a path test).
- `shared_db.py` (new; stdlib + SQLAlchemy `make_url` only):
  - `shared_slug(url, root=None)`, `sqlite_path(url) -> Path | None`, `SIDECARS`;
  - `file_checks(path) -> list[str]` for sidecars and header journal mode;
  - `read_only_url(path)` returns `sqlite:///file:<path>?mode=ro&uri=true`.
- `runs.py`: `find_unfinished_run(...) -> UnfinishedRun | None` (frozen: run_id, status, recorded_calls), read-only.
- `cli.py`:
  - `main` gets `--election-db`. When both options are set, raise `UsageError`; otherwise build the URL via config, catching `ConfigError`.
  - `AppContext` gets `shared_slug`. `requires_db` applies Behaviour 3.
  - `_confirm_shared(app, yes)` and `_stdin_is_interactive()` are the seams. `pipeline run` gets `--yes` and `--fresh`, `run-queued` gets `--yes`.
  - `db check` is new.
- `tests/conftest.py`: also unset `ELECTION_DB` and `ELECTIONS_DATA_DIR`.
- **Migrations on committed DBs**: a PR that adds a migration also runs `ideology --election-db <slug> db upgrade` and `db check` on every committed DB, and commits them. Scenario 7 makes `init.sh` fail until it does. It does this only when no run is active for that Election. A committed DB is never downgraded (`0003`'s downgrade deletes page rows).

## Expected File Changes

- `src/ideology_app/config.py`, `cli.py`, `pipeline/runs.py`, `pipeline/__init__.py` (re-export): modify. `src/ideology_app/shared_db.py`: create.
- `.gitignore`, `.gitattributes`: modify (`.gitattributes` is created by the sibling). `data/elections/es-general-2023-07-23/ideology.db`: create (binary).
- `tests/test_shared_db.py` (Scenarios 1–6) and `tests/test_committed_databases.py` (Scenario 7): create. `tests/conftest.py`, `tests/test_config.py`: modify.

## Visual Design Impact

- UI involved: no. CLI, configuration and data only. Browser validation does not apply (`AGENTS.md` exemption). `/api/v1` is covered by a `TestClient` assertion.

## Durable Documentation Impact

- `docs/technical-discovery.md`: update.
  - Configuration Points: add `ELECTION_DB` and `ELECTIONS_DATA_DIR`, and state that `DATABASE_URL` is the explicit override.
  - Data and Storage: one committed SQLite DB per Election.
  - Add the runbook below to Integrations, after step 4, as "Shared Election database".
- `ARCHITECTURE.md`: update. `shared_db.py`, the URL resolution, `db check`, the committed-DB layout.
- `CONSTRAINTS.md`: update with these rules:
  - committed DBs MUST stay in `delete` journal mode;
  - never downgrade a committed DB;
  - a migration PR upgrades and commits every committed DB;
  - tests MUST NOT write to `data/elections/*/ideology.db` (read-only `mode=ro` only).
- `CONTEXT.md`: no new term. Optionally add "Election database" under Dataset Version / Pipeline Run, if useful.
- `docs/risks-and-open-questions.md`: already updated by the planner (settled decisions, open questions, risks). The implementer adjusts it only if something changes.
- `PROGRESS.md` (Operator CLI line: `--election-db`, `ELECTION_DB`, `db check`, `--yes`, `--fresh`), `feature_list.json` (this entry): update. `AGENTS.md`: not needed.

**Runbook text** (for `docs/technical-discovery.md`; commands run from the repo root):
1. Pull code and DB together (`git pull`) with no `ideology` process or web server open on that DB. Pulling or switching branch replaces the file: an open process would keep writing to the old copy, and those writes are lost.
2. Tell the team you are generating `<slug>`. One active run per Election.
3. `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology --election-db <slug> pipeline run --election N`. Confirm the prompt, or pass `--yes`. Use `--resume-from R` when the CLI or `db check` names an unfinished run.
4. To stop (usage limit, end of day), press Ctrl-C once and wait for the process to exit. The run ends `failed: interrupted`.
5. Run `.venv/bin/ideology --election-db <slug> db check`. It must print `Safe to commit: yes`.
6. Commit only the DB (`git add data/elections/<slug>/ideology.db`), with a message naming the run and `--resume-from R`, then push. Tell the team.
7. The next developer starts at step 1 and resumes with `--resume-from R`, using the same `LLM_PROVIDER`/`LLM_MODEL` and code revision.
8. A merge conflict on the DB means the team rule was broken. Keep the side with the run that matters (`git checkout --ours|--theirs`), re-run `db upgrade` if a migration landed, and resume. Never try to merge two DB files.
9. To serve an Election locally: `ELECTION_DB=<slug> .venv/bin/uvicorn ideology_app.main:app`. That is one Election per server process.

## Implementation Plan

1. `config` resolution and `shared_db` helpers, with unit tests (Scenario 1). Update conftest.
2. CLI option, `requires_db` missing-file guard, confirmation and `--yes` (Scenarios 2–3).
3. `find_unfinished_run`, the guard and `--fresh` (Scenario 4). Then the cross-directory resume test (Scenario 5).
4. `db check` (Scenario 6).
5. Git files. Build and check the 2023 DB, then add `test_committed_databases.py` (Scenario 7).
6. Docs, runbook, evidence.

## Implementation Tasks

- [ ] `election_db()` / `database_url()` resolution and errors. `shared_slug`, `sqlite_path`, `file_checks`, `read_only_url`.
- [ ] `--election-db`, the both-set error, the missing-file guard, and `AppContext.shared_slug`.
- [ ] `_confirm_shared` and `_stdin_is_interactive` seams. `--yes` on `pipeline run` / `run-queued`.
- [ ] `find_unfinished_run`, the shared refusal, the non-shared warning, and `--fresh`.
- [ ] `db check`.
- [ ] `.gitignore`, `.gitattributes`, the 2023 DB (no runs), and the committed-DB test.
- [ ] Docs, `CONSTRAINTS.md` rules, runbook, `PROGRESS.md`, and evidence.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → 0. `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` → clean. Tests never call a real LLM (FakeProvider and the offline guard).
- Git:
  - `git check-attr binary -- data/elections/es-general-2023-07-23/ideology.db` → `set`.
  - `git check-ignore -v` on `<that>.db-journal`, `-wal`, `-shm` and `data/elections/x/other.db` → each ignored.
  - `git ls-files 'data/elections/*/ideology.db'` → exactly the 2023 file.
- Manual:
  - `ideology --election-db es-general-2023-07-23 db check` → `Safe to commit: yes`. Also `data check`.
  - `pipeline run --election 1` with stdin from `/dev/null` → refused, and the DB bytes are unchanged (compare `shasum` before and after).
  - Use a scratch copy (`ELECTIONS_DATA_DIR` set to a temp dir) for any write smoke test. Never run on the committed file.

## Evidence To Capture

- `init.sh` summary and pass count, and the `-X dev -W error` result.
- The DB build transcript (commands, import summary, `db check` output), the DB size, and the 2023 Party count.
- The git attribute and ignore outputs. The refusal smoke test with unchanged `shasum`.

## Validator Checklist

- [ ] Scenarios 1–7 pass. No test writes the committed DB: its `shasum` is the same before and after `init.sh`.
- [ ] `DATABASE_URL` still works alone. Both set is an error. The default is unchanged. Existing CLI tests pass untouched.
- [ ] Every refusal creates no run. Non-interactive runs without `--yes` never block or prompt.
- [ ] The committed DB has no runs, is at head, is in `delete` mode, matches the bundle, and is tracked as binary. Sidecars are ignored.
- [ ] No git invocation in `src/`. No `VACUUM`, no JSONL, no new dependency.
- [ ] Docs and runbook updated. `feature_list.json` (this entry) and `PROGRESS.md` hold real evidence. No `docs/validations/`.
