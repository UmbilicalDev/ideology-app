# Feature Implementation Spec: One committed SQLite database for all Elections

## Source Feature

- `id`: shared-database
- `area`: platform
- `depends_on`: pipeline-run-checkpoint (`accepted`), source-text-bundle (`not_started` at planning time; this feature starts only once it is `accepted`)
- `source`: `feature_list.json`. Replaces the dropped plan `pipeline-checkpoint-shared` (JSONL checkpoint files and `--resume-from-file`), and the short-lived plan `shared-election-database` (one DB per Election).

## Goal

Several developers on several machines generate data. Each local `ideology.db` holds different ids, runs and recorded calls, so a run stopped on one machine cannot be resumed on another, and sessions disagree. This feature makes one SQLite database, committed at `data/ideology.db` and holding every Election, the single source of truth. A shared checkpoint is simply that database: when a session stops, the Operator commits and pushes it by hand, and another developer pulls it and runs `pipeline run --resume-from R`. Run ids, Dataset Version ids (Share Links) and `request_hash` values are the same everywhere because everyone opens the same file. The web server serves every Election from it unchanged.

User decisions (2026-10-21, binding):
- One DB for all Elections in git, chosen over one per Election (which would show one Election per server and clash ids in Share Links).
- It is built from scratch with `db upgrade` + `data import` of each bundle. The local DB in `ideology-app-data/e2e-2023/` is not migrated.
- No auto-commit. The app never invokes git.
- One active run at a time on the shared database (team rule), confirmed by a CLI prompt.
- History growth is accepted. Past Elections' rows will be deleted later, keeping two.
- DB commits during generation go on the branch doing the work, merged to `main` by PR.
- On the shared DB an unfinished run makes `pipeline run` refuse (not just warn); `--fresh` is the explicit override.

## Non-Goals

- JSONL checkpoint files, `--resume-from-file`, automatic reuse across runs, and git automation (hooks, auto-commit, `git` subprocesses).
- Deleting past Elections' rows (a later feature; see risks), deployment and PostgreSQL, and exporting the DB to production.
- Marking stale `running` runs `failed`, locks across machines, and detecting "someone else is generating" (it is a team rule plus a prompt).
- `VACUUM` / `db compact`. The app has no delete path: the local e2e DB has `freelist_count = 0` after two runs, so `VACUUM` would reclaim nothing. Revisit with the deletion feature.
- Running a real Pipeline Run on the 2023 data (`e2e-real-2023-election`).

## Job Story

When my generation session stops (for example, out of tokens),
I want to push the shared database and let a teammate pull it and resume,
so the team pays for each LLM call once and nobody's data diverges.

## Users And Permissions

- Operator / developer: CLI only. Commits and pushes the DB by hand.
- Voter: not affected. The web server reads the configured DB, as today.

## Behaviour

1. **Selecting the DB: no new setting.**
   - `DATABASE_URL` / `--database-url` stay the only selector. The documented value for the shared file is `sqlite:///data/ideology.db`, run from the repo root.
   - The CLI, migrations and the web server (`create_app` → `make_engine(None)` → `config.database_url()`) already honour it, so there are no code changes to selection.
   - The default stays `sqlite:///ideology.db` (opt-in). A default write target inside git would let any stray command (`election create`, `source add`, `data import`, a run from an old shell) silently modify the shared file. Only run commands get the prompt below. The runbook tells developers to `export DATABASE_URL=sqlite:///data/ideology.db`.
2. **Shared database.**
   - Constant `config.SHARED_DATABASE_PATH = Path("data/ideology.db")`, relative to the current directory like the other defaults.
   - `shared_db.is_shared(url) -> bool`: the URL is SQLite with a file path whose resolved path equals `SHARED_DATABASE_PATH.resolve()`.
   - Tests already chdir into `tmp_path`. A test opts in by using `<tmp_path>/data/ideology.db`, while the usual `db_url` (`<tmp_path>/test.db`) is never shared, so existing tests stay non-interactive.
3. **Missing shared file.** With a shared URL whose file does not exist, every `requires_db` command fails before connecting: `no database at data/ideology.db; pull it, or build it with "ideology db upgrade" and "ideology data import <bundle dir>"`. Only `db upgrade` may create it. This avoids the accepted Low finding that an empty file is created, which here would be committable.
4. **Confirmation before generating on the shared DB.** It applies to `pipeline run` and to `pipeline run-queued` (only when at least one run is queued). After the provider is built and before any write, the CLI prints:
   ```
   Database data/ideology.db is shared through git.
   One active run at a time: generate only if you pulled the latest commit of this
   database and nobody else is generating on it (any Election).
   Continue? [y/N]:
   ```
   - `--yes` skips the prompt.
   - Without `--yes`, a non-interactive stdin (the seam `cli._stdin_is_interactive()` returns `sys.stdin.isatty()`) refuses with exit 1: `refusing to generate on the shared database without confirmation; pass --yes`.
   - Answering no exits 1 (`Aborted!`).
   - In every refusal no run is created.
5. **Unfinished run guard** (per Election; `pipeline run` without `--resume-from`). `runs.find_unfinished_run(session, election_id, provider, model)` takes that Election's highest-id run that has at least one recorded call. It is *unfinished* when:
   - it has no Dataset Version;
   - its status is `running` or `failed`;
   - its provider/model equal the current ones (other runs cannot be resumed anyway).

   What happens then:
   - On the shared DB the command refuses (exit 1, no run created): `election <id> has an unfinished run R (<status>, N recorded calls); resume it with --resume-from R, or pass --fresh to start from zero`. For `running` it adds: `if another developer is generating, stop; a killed run also stays running`.
   - On any other DB the same text is a warning on stderr, and the run continues (current behaviour is kept).
   - `--fresh` with `--resume-from` is a usage error.
6. **Resuming on another machine** needs no new code. `_check_resumable` ignores status, so a run left `running` by a process killed on machine A, or ended `failed: interrupted` by Ctrl-C, is resumable on machine B once B has pulled the file (pipeline-run-checkpoint Scenario 6). The stale `running` row stays as it is (see "Runs stuck in `running`" in the risks doc). Hashes match only when both machines run the same code revision (prompts, chunking, schemas) and the same `LLM_PROVIDER`/`LLM_MODEL`. A prompt change makes misses, not wrong reuse. A different model is refused.
7. **`ideology db check`** (new, read-only, SQLite only, any SQLite DB) is the safe-to-commit gate. In order:
   1. No `-journal`, `-wal` or `-shm` file next to the DB. A sidecar means a writer is active or crashed mid-write. Stop every `ideology` process, then run any read command once so SQLite rolls back.
   2. Journal mode `delete` (header bytes 18–19 equal `1`).
   3. `PRAGMA integrity_check` = `ok`.
   4. Migration at head.
   5. For every Election in the DB whose bundle exists (`source_bundle.bundle_slug(election)`), `check_against_bundle(session, read_bundle(dir))` is empty. An Election without a bundle prints `election N: no committed bundle; text not checked` (info).

   It then lists unfinished runs per Election as info: `election E, run R: running|failed, N recorded calls; resume with --resume-from R`. For `running` it adds `commit only if no ideology process is still running it`. It ends with `Safe to commit: yes` (exit 0) or one line per failed check plus `Safe to commit: no` (exit 1). It opens the file with `mode=ro` only after the sidecar check.
8. **Git**:
   - `.gitignore`: keep `*.db`, add `*.db-journal`, `*.db-wal`, `*.db-shm`, then `!data/ideology.db`. The planner verified the same negation pattern in a scratch repo: only the named file gets tracked, and sidecars and other `.db` files stay ignored.
   - `.gitattributes`: append `data/ideology.db binary`.
   - The app never sets WAL, and SQLite's default is `delete`, so a file with no sidecar is complete.
9. **Committed DB.** This feature commits `data/ideology.db`, built from scratch, containing the 2023 Election with no runs:
   - `GENERATION_MODE=precomputed DATABASE_URL=sqlite:///data/ideology.db ideology db upgrade`;
   - then `ideology data import data/elections/es-general-2023-07-23`;
   - then `db check`.

   Pipeline runs on it belong to `e2e-real-2023-election`. Expected size is about 4 MB (the local e2e DB was 4.0 MB before any run). A full run adds about 0.4–0.7 MB (281 recorded calls = 372 KB of output). A future Election is added with `data import` of its bundle into the same file.

## Acceptance Scenarios

1. **Selection and web.** In `tmp_path`:
   - `--database-url sqlite:///data/ideology.db`, after `db upgrade` + `data import` of a tiny bundle (built with `source_bundle` helpers), is detected as shared;
   - `sqlite:///<tmp>/test.db` and `sqlite:///<tmp>/other/data/ideology.db` (run from `<tmp>`) are not;
   - the default URL is unchanged;
   - `create_app("sqlite:///data/ideology.db")` lists every imported Election (two bundles) from `/api/v1/elections`.
2. **Missing shared file.** `pipeline list --election 1` with the shared URL and no file → exit 1 with the hint, and no file is created. `db upgrade` creates it.
3. **Confirmation.** On the shared tmp DB:
   - `pipeline run --election 1` without `--yes` refuses: exit 1, the message, `pipeline_runs` empty.
   - With `_stdin_is_interactive` patched to `True`, input `n` → exit 1 and no run; input `y` → the run executes.
   - `--yes` → it executes with no prompt.
   - `run-queued` behaves the same, and does not prompt when nothing is queued.
   - A non-shared DB never prompts (all existing CLI tests unchanged).
4. **Unfinished run.** A FakeProvider run on Election 1 that stops at call 4 (`failed`) on the shared DB:
   - a new `pipeline run --election 1 --yes` refuses and names `--resume-from 1`, and no run is created;
   - `--fresh` starts a new run from zero;
   - Election 2 in the same DB is not blocked by Election 1's run;
   - the same state on a non-shared DB prints the warning and runs.
   - A killed run left `running` gives the `running` wording.
   - A latest run with a Dataset Version, or with another model, gives no guard.
5. **Another machine.**
   - `<tmp>/a/data/ideology.db` is built from a bundle. Run 1 stops at call 4.
   - `<tmp>/a/data/` (DB and bundles) is copied to `<tmp>/b/data/`. The test chdirs to `<tmp>/b`.
   - There, `pipeline run --election 1 --resume-from 1 --yes` calls the provider only for the missing calls, records 3 reused calls, and ends with the same Statements as an uninterrupted run.
   - Run ids are the same in both files.
6. **`db check`.**
   - A freshly imported shared DB → `Safe to commit: yes`.
   - Each of these → exit 1 naming the problem, and the file is unchanged:
     - a `-journal` (or `-wal`) sidecar present;
     - WAL mode, set in a scratch copy;
     - a DB one migration behind head;
     - a page row edited directly (bundle mismatch naming the Election).
   - An Election without a bundle prints the info line and still exits 0.
   - A stopped run is listed with its resume hint and still exits 0.
   - A non-SQLite URL exits 1 with `db check supports SQLite databases only`.
7. **Committed DB** (`tests/test_committed_database.py`, read-only). `<repo root>/data/ideology.db` (an absolute path, since conftest chdirs to `tmp_path`):
   - opened with `mode=ro`;
   - at migration head;
   - header journal bytes `1`;
   - `integrity_check` `ok`;
   - every Election with a committed bundle (bundle root `<repo root>/data/elections`) passes `check_against_bundle`;
   - the 2023 Election has 9 Parties and page text equal to its `.md` files.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json` (this entry, sibling, `e2e-real-2023-election`), `CONSTRAINTS.md`, `ARCHITECTURE.md`, `docs/technical-discovery.md` (runbook, Configuration Points), `docs/risks-and-open-questions.md`, `.gitignore`, `init.sh`.
- `docs/specs/pipeline-run-checkpoint.md`, `docs/specs/source-text-bundle.md` (contract: `elections_data_dir`, `bundle_slug`, `read_bundle`, `check_against_bundle`, `data check`).
- `src/ideology_app/config.py` (`database_url`), `db.py` (`make_engine`, `is_initialised`, no journal pragma), `cli.py` (`main` options, `requires_db`, `pipeline run|run-queued`), `main.py` (`create_app` lifespan engine), `migrations/env.py` (falls back to `config.database_url()`), `pipeline/checkpoint.py`, `pipeline/runs.py` (`queue_run`, `_check_resumable` has no status check, `execute_run` Ctrl-C → `failed: interrupted`), `tests/conftest.py` (unsets `DATABASE_URL`, chdir to `tmp_path`), `tests/test_pipeline_checkpoint.py` (`Stopping` provider, CLI helper).
- Read-only look at `ideology-app-data/e2e-2023/ideology.db`: journal `delete`, 1154 pages of 4 KiB, freelist 0, 281 recorded calls.

### Current Gaps

- No shared-DB notion, no confirmation, no `db check`. `.gitignore` does not ignore `-journal`/`-wal`/`-shm`. There is no `data/` yet (it comes from the sibling).

## Technical Approach

- `config.py`: adds `SHARED_DATABASE_PATH` only. `database_url()` is unchanged.
- `shared_db.py` (new; stdlib + SQLAlchemy `make_url` only):
  - `sqlite_path(url) -> Path | None`, `is_shared(url)`, `SIDECARS`;
  - `file_checks(path) -> list[str]` for sidecars and header journal mode;
  - `read_only_url(path)` returns `sqlite:///file:<path>?mode=ro&uri=true`.
- `runs.py`: `find_unfinished_run(...) -> UnfinishedRun | None` (frozen: run_id, status, recorded_calls), read-only.
- `cli.py`:
  - `AppContext.shared: bool`. `requires_db` applies Behaviour 3.
  - `_confirm_shared(app, yes)` and `_stdin_is_interactive()` are the seams. `pipeline run` gets `--yes` and `--fresh`, `run-queued` gets `--yes`.
  - `db check` is new. It uses `source_bundle` / `bundle_import` from the sibling.
- `tests/conftest.py`: also unset `ELECTIONS_DATA_DIR` if the sibling did not.
- **Migrations on the committed DB**: a PR that adds a migration also runs `ideology db upgrade` and `db check` on `data/ideology.db` (shared URL), and commits it. Scenario 7 makes `init.sh` fail until it does. It does this only when no run is active. The committed DB is never downgraded (`0003`'s downgrade deletes page rows).

## Expected File Changes

- `src/ideology_app/config.py`, `cli.py`, `pipeline/runs.py`, `pipeline/__init__.py` (re-export): modify. `src/ideology_app/shared_db.py`: create.
- `.gitignore`, `.gitattributes`: modify (`.gitattributes` is created by the sibling). `data/ideology.db`: create (binary).
- `tests/test_shared_db.py` (Scenarios 1–6) and `tests/test_committed_database.py` (Scenario 7): create. `tests/conftest.py`: modify if needed.

## Visual Design Impact

- UI involved: no. CLI, configuration and data only. Browser validation does not apply (`AGENTS.md` exemption). `/api/v1` is covered by a `TestClient` assertion.

## Durable Documentation Impact

- `docs/technical-discovery.md`: update.
  - Configuration Points: `DATABASE_URL=sqlite:///data/ideology.db` is the shared DB.
  - Data and Storage: one committed SQLite DB for all Elections.
  - Add the runbook below to Integrations, after step 4, as "Shared database".
- `ARCHITECTURE.md`: update. `shared_db.py`, `db check`, the committed-DB layout (`data/ideology.db` beside `data/elections/<slug>/`).
- `CONSTRAINTS.md`: update with these rules:
  - the committed DB MUST stay in `delete` journal mode;
  - never downgrade it;
  - a migration PR upgrades and commits it;
  - tests MUST NOT write to `data/ideology.db` (read-only `mode=ro` only).
- `docs/risks-and-open-questions.md`: already updated by the planner (settled decisions, open questions, risks). The implementer adjusts it only if something changes.
- `PROGRESS.md` (Operator CLI line: shared `DATABASE_URL` value, `db check`, `--yes`, `--fresh`), `feature_list.json` (this entry): update. `AGENTS.md`, `CONTEXT.md`: not needed.

**Runbook text** (for `docs/technical-discovery.md`; commands run from the repo root with `export DATABASE_URL=sqlite:///data/ideology.db`):
1. Pull code and DB together (`git pull`) with no `ideology` process or web server open on the DB. Pulling or switching branch replaces the file: an open process would keep writing to the old copy, and those writes are lost.
2. Tell the team you are generating. One active run at a time on the shared DB, for any Election.
3. `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election N`. Confirm the prompt, or pass `--yes`. Use `--resume-from R` when the CLI or `db check` names an unfinished run.
4. To stop (usage limit, end of day), press Ctrl-C once and wait for the process to exit. The run ends `failed: interrupted`.
5. Run `.venv/bin/ideology db check`. It must print `Safe to commit: yes`.
6. Commit only the DB (`git add data/ideology.db`), with a message naming the run and `--resume-from R`, then push. Tell the team.
7. The next developer starts at step 1 and resumes with `--resume-from R`, using the same `LLM_PROVIDER`/`LLM_MODEL` and code revision.
8. Other writes (`data import` of a new or changed bundle, `db upgrade` after a migration) follow the same pull → write → `db check` → commit → push cycle, never while someone is generating.
9. A merge conflict on the DB means the rule was broken. Keep the side with the run that matters (`git checkout --ours|--theirs`), re-run `db upgrade` or `data import` if that side lacks them, and resume. Never try to merge two DB files.
10. To serve locally: `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app` (every Election).

## Implementation Plan

1. `SHARED_DATABASE_PATH` and the `shared_db` helpers, with unit tests (Scenario 1).
2. The `requires_db` missing-file guard, confirmation and `--yes` (Scenarios 2–3).
3. `find_unfinished_run`, the guard and `--fresh` (Scenario 4). Then the cross-directory resume test (Scenario 5).
4. `db check` (Scenario 6).
5. Git files. Build and check `data/ideology.db`, then add `test_committed_database.py` (Scenario 7).
6. Docs, runbook, evidence.

## Implementation Tasks

- [ ] `SHARED_DATABASE_PATH`, `sqlite_path`, `is_shared`, `file_checks`, `read_only_url`.
- [ ] The missing-file guard and `AppContext.shared`.
- [ ] `_confirm_shared` and `_stdin_is_interactive` seams. `--yes` on `pipeline run` / `run-queued`.
- [ ] `find_unfinished_run`, the shared refusal, the non-shared warning, and `--fresh`.
- [ ] `db check`, including the per-Election bundle check.
- [ ] `.gitignore`, `.gitattributes`, `data/ideology.db` (2023, no runs), and the committed-DB test.
- [ ] Docs, `CONSTRAINTS.md` rules, runbook, `PROGRESS.md`, and evidence.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → 0. `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` → clean. Tests never call a real LLM (FakeProvider and the offline guard).
- Git:
  - `git check-attr binary -- data/ideology.db` → `set`.
  - `git check-ignore -v` on `data/ideology.db-journal`, `-wal`, `-shm` and `data/other.db` → each ignored.
  - `git ls-files '*.db'` → exactly `data/ideology.db`.
- Manual:
  - `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` → `Safe to commit: yes`. Also `data check data/elections/es-general-2023-07-23`.
  - `pipeline run --election 1` with stdin from `/dev/null` → refused, and the DB bytes are unchanged (compare `shasum` before and after).
  - Run any write smoke test on a scratch copy outside the repo. Never on the committed file.

## Evidence To Capture

- `init.sh` summary and pass count, and the `-X dev -W error` result.
- The DB build transcript (commands, import summary, `db check` output), the DB size, and the 2023 Party count.
- The git attribute and ignore outputs. The refusal smoke test with unchanged `shasum`.

## Validator Checklist

- [ ] Scenarios 1–7 pass. No test writes the committed DB: its `shasum` is the same before and after `init.sh`.
- [ ] The default URL is unchanged. No new selection setting. Existing CLI tests pass untouched.
- [ ] Every refusal creates no run. Non-interactive runs without `--yes` never block or prompt.
- [ ] The committed DB holds the 2023 Election with no runs, is at head, is in `delete` mode, matches its bundle, and is tracked as binary. Sidecars are ignored.
- [ ] No git invocation in `src/`. No `VACUUM`, no JSONL, no new dependency.
- [ ] Docs and runbook updated. `feature_list.json` (this entry) and `PROGRESS.md` hold real evidence. No `docs/validations/`.
