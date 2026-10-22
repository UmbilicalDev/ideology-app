# Feature Implementation Spec: README (run the app locally and run the pipeline by hand)

## Source Feature

- `id`: readme
- `area`: docs
- `depends_on`: e2e-real-2023-election (`accepted`)
- `status`: not_started at planning time (2026-10-23)
- `source`: `feature_list.json` (verification: every README command run as written from a clone-like scratch state, real LLM calls only up to the provider/confirmation step; the README links to and does not contradict `AGENTS.md`, `ARCHITECTURE.md`, `docs/technical-discovery.md` and the specs)

## Goal

A root `README.md` for a new developer or Operator: (1) set up, start and try the app locally with the published 2023 Election, and (2) run the generation pipeline by hand on the shared database: configuration, provider choice, runbook, stops and resumes, reading results, and adding manifestos. It is a guide that links to the detailed docs and does not repeat every rule. Every fact in it is checked against the source named below.

## Language Decision

**Spanish**, with domain terms kept in English the first time, e.g. "afirmaciones (*Statements*)", "versión del dataset (*Dataset Version*)", "ejecución del pipeline (*Pipeline Run*)", "Validación (*Validation*)", "Evidencia (*Evidence*)". Why:
- The user asked in Spanish. The audience works on a Spanish election, and the UI, the prompts and the Statements are all in Spanish.
- No repo rule sets a language for docs. Checked: `AGENTS.md`, `CONSTRAINTS.md` (only "Public Copy" rules for UI copy), `DESIGN.md`, `CONTEXT.md`.
- `AGENTS.md` asks for the `CONTEXT.md` terms. CLI output, flags, statuses (`passed`, `failed: interrupted`) and the linked docs use the English terms, so the README pairs them.
- Commands, env vars, CLI output and code stay verbatim.
- This spec stays in English, like the other specs.

## Non-Goals

- No change to code, tests, `init.sh`, `package.json`, `.claude/launch.json` or `data/` (including `data/ideology.db` and the bundle). If `init.sh` or the CLI looks wrong while writing, record it and don't fix it.
- No real LLM call by any agent, including the `claude -p` ping. No `pipeline run --yes` and no write command on the committed `data/ideology.db`.
- No new runbook rules. The README restates the existing runbooks and links to them. `docs/technical-discovery.md` stays the detailed source.
- No English translation, no badges, no CONTRIBUTING or LICENSE (no license is set in the repo).

## Job Story

When I land on the repo for the first time, or have to generate a dataset,
I want one page that gets me from clone to a working app and tells me exactly how to run, stop, resume and read a Pipeline Run safely on the shared DB,
so I can try the app or generate without reading 35 specs or breaking the committed database.

## Users And Permissions

- New developer or Voter tester: setup, start, try, tests.
- Operator: runs the pipeline in their own terminal with their own provider credentials. The README never asks to paste or print a credential.

## Acceptance Scenarios

### Scenario 1: From clone to the 2023 Election
Given a fresh clone with Python >= 3.12, Node >= 22.13 and npm
When the reader follows "Puesta en marcha" as written
Then `./init.sh` ends with `All checks passed.`, the server starts on the committed DB, and `http://127.0.0.1:8000/` lists "Elecciones generales 2023".

### Scenario 2: Default DB trap is explained
Given the reader starts uvicorn without `DATABASE_URL`
Then the README has already explained the cause: a new empty `./ideology.db` is created, and `/api/v1/elections` answers 500 "no such table" (checked in a scratch copy). It also gives the fix: `DATABASE_URL=sqlite:///data/ideology.db`.

### Scenario 3: Pipeline runbook is safe and exact
Given the "Ejecutar el pipeline a mano" section
When it is run in a scratch clone, every command up to the run is run as written. The run command itself is run without `--yes` and with stdin not a terminal.
Then the read-only commands print what the README says. The run command gets through the configuration and provider preflight and stops at `Error: refusing to generate on the shared database without confirmation; pass --yes`, writing nothing (scratch DB `shasum` unchanged).

### Scenario 4: No contradiction
Given `AGENTS.md`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/technical-discovery.md` and the specs named below
When the validator compares them with the README
Then defaults, flags, paths, statuses and rules match, and each README section links to its detailed source.

## README Outline And Facts (each fact is verified against the source in brackets)

Sources: `cfg` = `src/ideology_app/config.py`, `cli` = `src/ideology_app/cli.py` plus `ideology … --help`, `TD` = `docs/technical-discovery.md`, `e2e` = `docs/specs/e2e-real-2023-election.md`, `FL` = `feature_list.json` e2e evidence. "Run:" means checked by the planner in a scratch copy on 2026-10-23.

1. **Qué es** (short paragraph)
   - It is an AI-generated voting advice application (VAA) for the 2023 Spanish general election: Statements, Party Positions backed by a verbatim quote (Evidence), and automatic Validation before publishing (no hand edits). Voter answers never leave the browser: a Share Link carries them in the URL fragment. [`AGENTS.md`, `CONTEXT.md`, `docs/build-brief.md`]
   - The published data: Election 1 "Elecciones generales 2023", 9 Parties (PP, PSOE, VOX, SUMAR, ERC, JUNTS, EH Bildu, EAJ-PNV, BNG; CCa and UPN excluded by decision), Dataset Version 3 with 26 Statements. [Run: `election list`, `pipeline report --run 3`; `e2e`]
   - Links: `CONTEXT.md`, `docs/build-brief.md`, `ARCHITECTURE.md`, `DESIGN.md`, `AGENTS.md` (for agents).
2. **Requisitos**
   - Python >= 3.12 [`pyproject.toml` `requires-python`]; the team's `.venv` uses 3.15 [`PROGRESS.md`]. `init.sh` uses `python3`, or `$PYTHON` if set [`init.sh`].
   - Node.js >= 22.13 [`init.sh` `NODE_MIN_*`, `package.json` `engines`] and npm [`init.sh` `step_web_install`].
   - git with access to the repo, which is private (github.com/UmbilicalDev/ideology-app answers 404 without auth) [`git remote -v`, planner check].
   - Optional: `sqlite3` for read-only inspection (`sqlite3 -readonly`) [`FL`].
   - For the pipeline only: Claude Code CLI (`claude`) with a Claude subscription, or an Anthropic API key.
   - macOS/Linux: `caffeinate` is macOS-only. On Linux, drop `caffeinate -is` and keep the machine awake another way (no Linux tool was verified, so name none as tested). Windows: not covered; `init.sh` is bash.
3. **Puesta en marcha**
   - `git clone https://github.com/UmbilicalDev/ideology-app.git` then `cd ideology-app`.
   - `./init.sh`, step by step [`init.sh`]:
     - creates `.venv` if missing;
     - checks Node;
     - `pip install -e '.[dev]'`;
     - pytest;
     - `npm ci` (exact lockfile);
     - typecheck, Vitest, `vite build` into `apps/web/dist`;
     - never starts a server.
   - `CI=true ./init.sh` is the documented verification gate [`AGENTS.md`/`PROGRESS.md`]. `init.sh` itself does not read `CI`: the steps are the same. Say only "use `CI=true ./init.sh` as in CI and the docs". Don't claim it changes behaviour.
   - Start command, from the repo root: `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app` [`TD` Shared database step 10]. Open `http://127.0.0.1:8000/` (uvicorn default port; `init.sh` prints the same URL).
   - Say explicitly: without `DATABASE_URL` the default is `sqlite:///ideology.db` in the current directory [`cfg` `DEFAULT_DATABASE_URL`]. That file is empty, so there is no 2023 Election [Run: 500 on `/api/v1/elections`].
   - `init.sh`'s closing hint (`--reload`, no `DATABASE_URL`) is about the default DB; the README explains the difference.
   - `/health` returns `{"status":"ok"}`. The API is under `/api/v1/`, Swagger UI at `/api/docs`, OpenAPI at `/api/openapi.json` [`main.py`].
   - `WEB_DIST_DIR` sets the served build, default `apps/web/dist` [`cfg`]. If `index.html` is missing, a warning is logged and `/` answers 404: run `./init.sh` or `npm run build` [`web.py`; Run: 404].
   - Optional live reload: `npm run dev -w @ideology-app/web` (Vite on its default port). It proxies `/api` and `/health` to `http://127.0.0.1:8000`, so uvicorn must run on 8000 [`apps/web/vite.config.ts`].
   - Warning box (shared-database runbook step 1 [`TD`]): never keep a server or an `ideology` process open on `data/ideology.db` while pulling, switching branches or generating. The file is replaced, and the open process keeps writing to the old copy.
4. **Probarla**
   - Flow:
     - Landing → "Elecciones generales 2023";
     - questionnaire of 26 Statements, 5-point scale, "Saltar esta afirmación", "Importante para mí", "Anterior";
     - results ranking and a per-Statement breakdown with the Evidence quote and its page (a link `#page=N` when the document has a URL; PSOE and VOX show the page only);
     - "Comparte tu resultado" → "Copiar enlace" → `/resultados#…`;
     - `/metodologia` (linked from "Cómo funciona" on the Landing).
     [`apps/web/src/features/**`, `paths.ts`, `FL` browser walk]
   - Public API (read-only, GET): `/api/v1/elections`, `/api/v1/elections/{id}`, `/api/v1/elections/{id}/published-dataset-version`, `/api/v1/dataset-versions/{id}` [`api/routes.py`].
   - Read-only CLI checks with their exact outputs:
     - `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` → `Safe to commit: yes`;
     - `… data check data/elections/es-general-2023-07-23` → `Database matches bundle es-general-2023-07-23: 9 documents`;
     - `… election list`.
     [Run]
5. **Tests**
   - `CI=true ./init.sh` runs everything.
   - Single steps:
     - `.venv/bin/python -m pytest` (or `… -m pytest tests/test_cli_pipeline.py`);
     - `npm test` (Vitest);
     - `npm run typecheck`;
     - `npm run build`.
     [`init.sh`, `package.json`]
   - Tests never call a real LLM; they use the fake provider [`CONSTRAINTS.md`, `AGENTS.md`]. `tests/test_committed_database.py` checks the committed DB [`TD` step 8].
   - Don't hardcode test counts.
6. **Ejecutar el pipeline a mano** (core; link `TD` "Local Claude Code CLI" and "Shared database", and the specs `shared-database`, `pipeline-run-checkpoint`, `pipeline-coverage-selection`, `pipeline-verified-findings`, `source-text-bundle`, `pipeline-run-report`, `e2e-real-2023-election`)
   - 6.1 Concepts:
     - A Pipeline Run generates a Statement Pool and Party Positions, selects the Questionnaire and validates it.
     - Pass → the Dataset Version is published automatically and its Election becomes `active`. Fail → it stays a candidate, not published. [`CONTEXT.md`, Run: report `publication`]
     - Dataset Versions are immutable.
     - `GENERATION_MODE`: `precomputed` (default) or `live` (live mode queues runs on source changes; they are executed with `pipeline run-queued`) [`cfg`, `cli`].
     - One active run at a time on the shared DB, for any Election [`TD`, `SHARED_PROMPT` in `cli`].
     - A Pipeline Run shown in `pipeline list` / `report` records its provider and model.
   - 6.2 Configuration table (name, default, meaning) [`cfg`]:
     - `DATABASE_URL` (`sqlite:///ideology.db`; the shared DB needs `sqlite:///data/ideology.db` from the root; `--database-url` also works);
     - `LLM_PROVIDER` (`anthropic` | `claude_code` | `fake`, default `anthropic`);
     - `LLM_MODEL` (default per provider: anthropic `claude-sonnet-5-5`, claude_code `claude-sonnet-4-6`, fake `fake-model`);
     - `ANTHROPIC_API_KEY` [`llm/anthropic_provider.py`];
     - `LLM_CLAUDE_CODE_BIN` (`claude`), `LLM_CLAUDE_CODE_TIMEOUT_SECONDS` (900), `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` (48);
     - `GENERATION_MODE` (`precomputed`);
     - `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` (50), `VALIDATION_MIN_STATEMENTS` (25), `VALIDATION_MAX_STATEMENTS` (35), `VALIDATION_MAX_TOPIC_SHARE_PERCENT` (30);
     - `ELECTIONS_DATA_DIR` (`data/elections`), `SOURCE_FILES_DIR` (`source_files`), `SOURCE_REFETCH_INTERVAL_HOURS` (6), `WEB_DIST_DIR` (`apps/web/dist`).
     Note: thresholds are code defaults decided by the user. Don't change them per run; the e2e command unsets them with `env -u` [`e2e`].
   - 6.3 Provider choice:
     - `claude_code`: your Claude subscription, no API key, local only [`TD`].
       - Log in once with `claude auth login`.
       - `claude auth status` showing loggedIn does not prove the token is fresh, so ping first with `claude -p "responde solo: ok"`. On a 401, run `claude auth login` again.
       - An API-key login is rejected by the preflight [`llm-provider-claude-code` spec].
       - Usage limit: the run prints `claude_code: usage limit reached (task …); waiting until <time> …` and waits in-process, up to `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` in total [`claude_code_provider.py`].
       - Keep AC power, lid open, `caffeinate -is`, and a terminal you won't close.
       - **Always set `LLM_MODEL=claude-sonnet-5-5`**: the provider default is `claude-sonnet-4-6`, and the runs in the DB used `claude-sonnet-5-5` [`cfg`, Run: `pipeline list`].
     - `anthropic`: paid API usage with `ANTHROPIC_API_KEY`. The key is read only at the first call: a missing key still creates a `failed` run with 0 calls (`ANTHROPIC_API_KEY is not set`) [Run on a scratch DB]. So check the key before running on the shared DB, because that run row would end up in the committed file.
     - The provider and model must stay the same to resume.
   - 6.4 Step by step on the shared DB [`TD` runbook, `e2e`]:
     1. With no server or `ideology` process open: `git status --short` empty, then `git pull`.
     2. Tell the team.
     3. Preflight: `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` (`Safe to commit: yes`), the ping, and `mkdir -p "$HOME/ideology-logs"`. Logs stay outside the repo and are never committed.
     4. The exact fresh-run command of `e2e`:
        - `caffeinate -is env -u VALIDATION_… -u LLM_… DATABASE_URL=sqlite:///data/ideology.db LLM_PROVIDER=claude_code LLM_MODEL=claude-sonnet-5-5 GENERATION_MODE=precomputed .venv/bin/ideology pipeline run --election 1 --yes 2>&1 | tee -ai "$HOME/ideology-logs/run.log"`;
        - copy the full `env -u` list verbatim from `e2e`;
        - only the log dir name may change.
     5. Without `--yes` it shows the shared-DB prompt `Continue? [y/N]`; when stdin is not a terminal it refuses [`cli` `_confirm_shared`].
     6. What you see: little or nothing until the end (no per-call progress output; only usage-limit lines on stderr) [`cli`, `claude_code_provider.py`]. At the end, `Pipeline run R: passed (dataset version V, N statements, M party positions)` plus `Published dataset version V for election E`, or `Error: pipeline run R failed: …; see "ideology pipeline checks --run R"` [`cli` `_echo_passed`, `_failure_message`].
     7. Duration and size for 2023 (9 Parties) [`FL`]: about 168 calls and about 3.0M input / 0.11M output tokens. 902 s with no usage-limit wait. Run 2 took 9,390 s with one wait. It can take several usage windows.
   - 6.5 Stops and resumes [`TD` steps 4-7, `e2e`, `cli` `_guard_unfinished`, `runs.find_unfinished_run`]:
     - Stopping: press Ctrl-C once and wait; the run ends `failed: interrupted`. If the machine sleeps or dies, a killed run can stay `running`.
     - Every completed call is already recorded.
     - Then:
       - `db check` must print `Safe to commit: yes`. It lists the unfinished run and `resume with --resume-from R`.
       - Commit **only** `data/ideology.db` (`git add data/ideology.db`), with a message naming the run and `--resume-from R`, then push and tell the team.
       - DB commits go on the working branch, then into `main` by PR.
     - Resume: the same command plus `--resume-from R`.
     - The unfinished-run guard: on the shared DB a fresh run is refused while the Election's latest run with recorded calls is `running` or `failed`, has no Dataset Version, and used the same provider and model. The message means "resume". `--fresh` (start from zero) only on a deliberate decision.
     - `--reuse-from R` re-runs after a *finished* run (one with a Dataset Version), reusing the identical calls with zero tokens (e.g. after a prompt or selection change).
     - `--resume-from` and `--reuse-from` are mutually exclusive, and so are `--fresh` and `--resume-from` [`cli`].
     - A teammate resuming elsewhere first pulls, then uses the same code revision, provider and model.
   - 6.6 Reading the results, all read-only with the same `DATABASE_URL` prefix [`cli` help]:
     - `pipeline list --election E`;
     - `pipeline report --run R` (status, provider/model, prompt_versions, calls/tokens, resumed_from/reused_calls, validation_settings, statement_selection, coverage, findings_check, publication);
     - `pipeline checks --run R`;
     - `pipeline statements --dataset-version V`;
     - `pipeline positions --dataset-version V [--party P]`;
     - `source list --party P`;
     - `source text --document D [--page N]`.
   - 6.7 When Validation fails:
     - The run gets a Dataset Version that is not published, and the published one stays.
     - Read `pipeline checks`.
     - Never edit the output, the DB, or a bundle `.md` by hand, and don't lower thresholds for one run [`AGENTS.md` invariants, `e2e`].
     - Changes go through code (prompts, selection), then `--reuse-from R`.
     - `pipeline validate --run R` exists only for a run left in `validating` [`cli`].
   - 6.8 Manifestos and Elections [`TD` Data and Storage, `source-text-bundle` spec, `cli` help]:
     - Extract: `ideology source extract PDF --party SHORT --out data/elections/<slug>/<file>.md [--url URL] [--force]` (no DB). Without `--url` the Evidence shows no link. Never commit a PDF or edit a `.md`.
     - List it in `election.toml` (format shown by the 2023 file); a new Election is a new `<slug>/` with its own `election.toml`.
     - Then `db upgrade` + `data import data/elections/<slug>` and `data check`. Import is idempotent, and a changed `.md` registers a replacement document.
     - The imported Election is `draft` until its first published run [Run: `election list` after import shows `draft`].
     - After a migration: `db upgrade` on the shared DB; a PR with a migration also commits the upgraded DB.
     - Both follow the pull → write → `db check` → commit → push cycle, never during someone's generation.
     - `data import` on the shared DB does not ask for confirmation [`cli`: only run commands call `_confirm_shared`].
   - 6.9 No fake dry run:
     - `LLM_PROVIDER=fake` from the CLI fails at once with `Error: pipeline run N failed: FakeProvider has no response for task 'statement_candidates'` and leaves a `failed` run with 0 calls [Run on a scratch DB]. The fake provider is for tests only.
     - Never point it at `data/ideology.db`.
     - The README says there is no way to rehearse without spending; the closest is the preflight (the command without `--yes`, answering `N`).
7. **Problemas frecuentes**
   - 401 / "Claude Code is not logged in or its login expired; run `claude auth login`" [`claude_code_provider.py`].
   - `Claude Code CLI 'claude' not found on PATH` [`llm-provider-claude-code` spec].
   - Empty landing or 500: wrong `DATABASE_URL` (Scenario 2).
   - `CERTIFICATE_VERIFY_FAILED` only with `source add --url` on a Python build without a CA bundle → `SSL_CERT_FILE=/etc/ssl/cert.pem`. It doesn't affect bundles or runs [`docs/risks-and-open-questions.md` "Fetching manifests by URL"].
   - Merge conflict on `data/ideology.db`: never merge. Keep one side (`git checkout --ours|--theirs data/ideology.db`), re-run `db upgrade`/`data import` if that side lacks them, then resume [`TD` step 9].
   - `db check` lists a `-journal`/`-wal`/`-shm` file or says `Safe to commit: no`: stop every process, don't commit [`cli db check --help`, `shared_db.file_checks`].
   - "has an unfinished run" refusal → 6.5.
8. **Más documentación**: links to `docs/technical-discovery.md`, `docs/domain-model.md`, `docs/risks-and-open-questions.md`, `CONSTRAINTS.md`, `docs/specs/`, `PROGRESS.md`.

## Repository Research

Files inspected:
- `AGENTS.md`, `PROGRESS.md` (state, Sessions 001-006), `feature_list.json` (e2e and readme entries), `CONTEXT.md`, `DESIGN.md` (grep), `CONSTRAINTS.md` (grep), `ARCHITECTURE.md` (data layer, API), `docs/technical-discovery.md`, `docs/specs/e2e-real-2023-election.md`, `docs/specs/llm-provider-claude-code.md` (grep), `docs/risks-and-open-questions.md`.
- `init.sh`, `pyproject.toml`, `package.json`, `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/src/features/paths.ts` and the copy greps, `.gitignore`, `.gitattributes`, `.claude/launch.json`.
- `src/ideology_app/{config,cli,main,web,shared_db}.py`, `api/routes.py`, `llm/__init__.py`, `llm/fake.py`, `llm/claude_code_provider.py` (grep), `pipeline/runs.py` (`find_unfinished_run`), `data/elections/es-general-2023-07-23/election.toml`.

Planner experiments, all in the scratchpad copy (`git archive HEAD` plus its own `.venv`; the committed DB was never opened):
- every `--help`;
- `db check`, `data check`, `election list`, `pipeline list|report|checks|statements|positions` on the copy's DB;
- the `claude_code` and `anthropic` run commands without `--yes`, which refused at confirmation with the copy's `shasum` unchanged;
- fake and no-key runs on a throwaway DB;
- uvicorn on port 8101 with the default DB (500 from `/api/v1/elections`, 404 on `/` without a build).

Risks doc: no entry names `readme`.

## Expected File Changes

- `README.md`: create (Spanish, outline above). Target about 250-400 lines, with links instead of duplicated detail.
- `PROGRESS.md`, `feature_list.json`: session log and evidence.
- Nothing else. Only if verification finds an existing doc wrong (e.g. a stale default), fix that doc in the same change and record it. If `init.sh` or the CLI looks wrong, report it and don't change it.

## Visual Design Impact

UI: none. No browser walk is required (no browser-visible change), but the served app is opened once on port 8101 (see the Verification Plan).

## Durable Documentation Impact

- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `AGENTS.md`: not needed (no boundary, rule or workflow change; `AGENTS.md` is for agents and already lists its reading order).
- `docs/technical-discovery.md`: not needed. It stays the detailed runbook, and the README links to it.
- `docs/risks-and-open-questions.md`: none expected. If a new gap appears (e.g. Linux keep-awake, `CI` unused), add it under the right section.

## Implementation Plan / Tasks

- [ ] `pwd`; read this spec; `./init.sh` in the worktree.
- [ ] Write `README.md` following the outline. Use the commands exactly as in the facts (copy the e2e `env -u` list verbatim).
- [ ] Run the Verification Plan in a scratch clone. Fix the README wherever output differs.
- [ ] Check every relative link resolves (`ls` each target).
- [ ] Contradiction pass against `AGENTS.md`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/technical-discovery.md` and the specs cited.
- [ ] `CI=true ./init.sh` in the worktree. `shasum data/ideology.db` equals `b7a1dd5a738e62e9edf28a0ba6a1757cd2c81bd3` before and after. Update `PROGRESS.md` and `feature_list.json`.

## Verification Plan

Scratch setup:
- `git clone <this worktree path> <scratchpad>/clone`, checking out the branch, with the README copied in if it is uncommitted.
- Cloning from GitHub needs repo access. Use the local clone and record that.
- The clone has its own `data/ideology.db`, so it is safe to touch. The committed file is never opened.

In the clone, run every README command as written, from the clone root:
- `./init.sh` and `CI=true ./init.sh`: exit 0;
- the individual test commands;
- every read-only CLI command of sections 4, 6.5 and 6.6, comparing outputs with the README text;
- `source extract --help`, `data import` and `data check` on a throwaway `DATABASE_URL=sqlite:///scratch.db` (never on the shared path);
- `db upgrade` on the clone's DB: expect "is at head".

Server:
- The start command with `--port 8101` appended (the only allowed deviation; never 8000).
- Check `curl /health`, `/api/v1/elections` (lists "Elecciones generales 2023"), `/api/docs` (200) and `/`.
- Open `http://127.0.0.1:8101/` once in a browser and see the 2023 Election.
- Run the Vite dev command just long enough to see it start, then stop it.
- Stop the server.

Pipeline:
- Run the exact fresh-run command with `--yes` removed, in a non-interactive shell (stdin `/dev/null`).
- Expect `Error: refusing to generate on the shared database without confirmation; pass --yes`, exit 1, and the clone DB's `shasum` unchanged.
- If `claude` is not logged in, the expected outcome is instead the preflight error. Record it and don't log in.
- Same check for `--resume-from 3` and `--reuse-from 3`.
- Also check `--resume-from 1 --reuse-from 2` gives the usage error.
- Never run the ping or any `--yes` run.

Documented behaviours:
- The fake-provider failure and the missing-key failure on a throwaway DB.
- The default-DB 500.

Not executed, and why:
- `git pull`/`push`/`commit` (verified from `TD` only);
- `claude auth login`, the ping and real runs (spend);
- `caffeinate` (only `which caffeinate`);
- the unfinished-run refusal (needs recorded calls). Verify it against `cli._guard_unfinished` and `tests/test_cli_pipeline.py`.

Finally, delete the clone, scratch DBs and logs.

## Evidence To Capture

- In `feature_list.json` / `PROGRESS.md`: the scratch path; each command group with exit code and its key output line; the 8101 check (curl codes, browser name); the refusal lines; the commands not executed and why; `shasum` before and after; the final `CI=true ./init.sh` result.
- Any doc fixed.

## Validator Checklist

- [ ] README in Spanish with the outline sections. Every fact matches its source; spot-check at least 10, including the env defaults, the `claude_code` default model note, the start command and the `env -u` command.
- [ ] Commands re-run in the validator's own scratch clone. No real LLM call; committed DB `shasum` unchanged.
- [ ] Links resolve, with no contradiction with `AGENTS.md`, `ARCHITECTURE.md`, `docs/technical-discovery.md` and the specs.
- [ ] No code, test, `init.sh` or data change. `feature_list.json` and `PROGRESS.md` updated.
