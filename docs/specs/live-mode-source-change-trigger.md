# Feature Implementation Spec: Live mode queues a Pipeline Run when a Source Document changes

## Source Feature

- `id`: live-mode-source-change-trigger (GitHub issue #32)
- `area`: pipeline
- `depends_on`: auto-publish-dataset-version (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "pytest: live + new document → run queued; live + same hash → no run; precomputed → no run"; notes: "Never generates per user.")

## Goal

With `GENERATION_MODE=live`, a new `parsed` Source Document queues a Pipeline Run for its Election, in the same commit as the document. With `precomputed` (the default) nothing is queued and `ideology source add` behaves exactly as today. Adding the same bytes to the same Party again is still a `DuplicateError`, so nothing is written and no run is queued. Queued runs are executed by a new, synchronous Operator command, `ideology pipeline run-queued`. Generation is never per user: the public API and web client are not touched.

## Decisions

- **"Queued" means a `queued` `PipelineRun` row only.** The trigger never calls the LLM. A `source add` must stay fast and must not need an API key, and a run takes minutes and costs money. Execution is a separate step, `ideology pipeline run-queued [--election N]`. It runs every `queued` run in id order, one at a time, in the foreground, through the existing `execute_run` (Validation and publishing are unchanged). The command can be scheduled later (cron or container) by the first deployment feature. No worker, scheduler or background thread is added: an always-on process belongs to deployment, and periodic re-fetch is `live-mode-url-refetch`.
- **What counts as a "change".** Stored files are content-addressed, and a `SourceDocument` row's `content_hash` never changes (`CONSTRAINTS.md`). So in this repo a changed manifesto arrives as a *new* Source Document with a new hash, via `--file` or `--url`. The trigger fires when a document is added and ends `parsed`. Cases:
  - Same hash for the same Party: `DuplicateError` before the trigger, so no run.
  - Same bytes for a *different* Party: a new document whose input changes that Party's positions, so a run is queued.
  - A `failed` document (fetch error, not a PDF, no text layer): it adds no input, so no run.
  - `live-mode-url-refetch` will call the same trigger function when a re-fetch yields a new hash. How a re-fetched hash is stored stays its open question.
- **One function, one mode table.** New module `src/ideology_app/pipeline/triggers.py`:
  - `QUEUE_ON_SOURCE_CHANGE: dict[GenerationMode, bool] = {PRECOMPUTED: False, LIVE: True}`, plus `queues_on_source_change(mode) -> bool` (a dict lookup). This table is the only place in the code that gives Generation Mode a behaviour. A test asserts that every `GenerationMode` member has an entry.
  - `queue_run_for_source_change(session, document, *, generation_mode, llm: LLMSettings | None) -> SourceChangeOutcome`. It never commits. If the mode does not queue, or `document.status` is not `parsed`, it returns `SourceChangeOutcome(election_id, run_id=None, newly_queued=False)` and writes nothing. If the mode queues and `llm` is `None`, it raises `ValueError` (a programming error). The live path is described in the next bullet.
  - `SourceChangeOutcome` is frozen plain data: `election_id: int`, `run_id: int | None`, `newly_queued: bool`.
- **Coalescing: at most one `queued` run per Election.** On the live path, `queue_run_for_source_change`:
  1. Locks the Election row with `publishing.election_lock_statement(election_id)` (`FOR UPDATE` on PostgreSQL; on SQLite the document insert already holds the write lock).
  2. Looks for the lowest-id `queued` run of the Election. If one exists, it returns `run_id=<that id>, newly_queued=False`. That run has not started yet, and `_start` loads every `parsed` document when it starts, so it will read the new document.
  3. Otherwise it calls `runs.queue_run(session, election_id, llm_provider=llm.provider, llm_model=llm.model, generation_mode=generation_mode)` and returns `newly_queued=True`.

  Runs in `running` or `validating` do **not** suppress queuing: they loaded their input before this document existed, so skipping would lose the change. The worst case per Election is one in-flight run plus one queued run, however many documents change at once. Publish order (run id) already makes the newer run's version win.
- **Provider and model recorded at queue time.** They come from `config.llm_settings()` (the registry key equals the provider's `name` for both `anthropic` and `fake`). No provider is built and no key is read. `run-queued` builds the provider with `cli._provider()`. A run queued for a different provider or model fails `execute_run`'s existing check (`InvalidInputError`, run left `queued`), and the command reports it and moves on.
- **CLI wiring (`source add`).** Before any write, read `config.generation_mode()`. If `triggers.queues_on_source_change(mode)` is true, also read `config.llm_settings()`. A `ConfigError` exits 1 with nothing written. This is new for `source add`: an invalid `GENERATION_MODE` now fails it in either mode, while the LLM settings are read only in `live`. Call the trigger inside the same `session_scope` as the add, so the document and its run commit together. Output after the existing line:
  - newly queued: `Queued pipeline run R for election E (generation mode live)`;
  - coalesced: `Pipeline run R is already queued for election E`;
  - precomputed: nothing extra.

  A `failed` document keeps today's error and exit 1.
- **`pipeline run --election`** is unchanged in both modes: it queues and executes its own run synchronously.
- **No migration.** The `queued` status, `generation_mode` and `ix_pipeline_runs_election_id` already exist (head stays `0008`).

## Non-Goals

- No periodic URL re-fetch, no re-hash of existing rows, no host allow-list (all `live-mode-url-refetch`).
- No worker, scheduler, background task or HTTP endpoint. No change to `main.py`, `api/`, `web.py`, `apps/web/` or `packages/`.
- No price table, money cap or stuck-`running` recovery (deferred below). No atomic claim of a queued run.
- No change to `execute_run`, `validate_run`, publishing, checks, prompts, `init.sh` or migrations. No new dependency.

## Job Story

When I add or replace a party's manifesto for an Election in `live` mode,
I want a regeneration to be queued for that Election automatically, once, however many documents I add,
so that I don't have to remember to re-run the pipeline, and nothing is spent until the queue is executed.

## Users And Permissions

- Operator (CLI only): adds Source Documents, executes queued runs with `pipeline run-queued`.
- Voter: unaffected. Nothing is generated per user, and the API stays read-only.

## Acceptance Scenarios

All tests use temporary SQLite (`migrated_engine` / `db_url`), PDFs from `tests/pdf_factory.py`, files in `tmp_path`, `FakeProvider` and the autouse env/socket guard (`offline_guard`, which unsets `GENERATION_MODE`, `LLM_*` and the API key). There is no API key and no network.

1. **Live + new document → run queued.** Given an Election with one Party and `generation_mode=live`, when an uploaded text PDF is added and the trigger is called, then exactly one `PipelineRun` exists with status `queued`, `generation_mode=live`, provider/model from the settings, `prompt_versions == PROMPT_VERSIONS`, no Dataset Version, and `FakeProvider.calls == []`. The same holds for a URL document added with a fake `fetch=`.
2. **Live + same hash → no run.** Given a Party whose document was added in `precomputed` mode (0 runs), when the same file is added again in `live` mode, then `DuplicateError` is raised, no new document exists and the run count is still 0. CLI: `source add` exits 1 with the existing duplicate message, and `pipeline list` is empty.
3. **Precomputed → no run.** Given `precomputed`, when a new parsed document is added, then the outcome has `run_id=None`, and there are no runs. CLI: the output is byte-identical to today's single line.
4. **Failed document → no run.** In `live` mode, a blank (no text layer) PDF or a failed fetch gives `run_id=None` and no run.
5. **Coalescing.** In `live` mode, adding documents for two Parties of the same Election gives one `queued` run: the second outcome has the same `run_id` and `newly_queued=False`. A `queued` run of *another* Election does not coalesce. With a `running` run and no `queued` run, a new document queues one. With a `running` run and a `queued` run, it does not.
6. **Atomic with the document.** If the trigger raises inside the add's `session_scope` (e.g. a monkeypatched `queue_run`), neither the document nor a run is committed.
7. **Mode table is complete.** `set(QUEUE_ON_SOURCE_CHANGE) == set(GenerationMode)`.
8. **CLI config errors.** `GENERATION_MODE=bogus` makes `source add` exit 1 with the `Invalid GENERATION_MODE …` message and no document. `GENERATION_MODE=live` with `LLM_PROVIDER=bogus` exits 1 with no document. `precomputed` with `LLM_PROVIDER=bogus` still succeeds.
9. **`pipeline run-queued` happy path.** Given `live`, `LLM_PROVIDER=fake` and a seeded Election, when `source add` queues run R and then `pipeline run-queued` runs with `cli._provider` patched to `fake_provider()`, then R ends `passed`. The output has the same `Pipeline run R: passed (…)` and `Published dataset version …` lines as `pipeline run`, and the exit code is 0.
10. **`run-queued` edge cases.**
    - No queued runs: prints `No queued pipeline runs`, exit 0.
    - `--election N` executes only that Election's runs.
    - A run that fails generation or Validation prints `Error: pipeline run N failed: …` on stderr; later runs still execute; exit 1.
    - A run queued for another provider or model stays `queued`, the error is reported, exit 1.
    - Invalid `VALIDATION_*` or `LLM_PROVIDER`: exit 1 before any run changes.
    - The provider is closed once.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/runs.py`: `queue_run` (needs a parsed document, flushes only) and `execute_run` / `_start` (status and provider check, loads documents at start).
- `src/ideology_app/pipeline/publishing.py`: `election_lock_statement`.
- `src/ideology_app/source_documents.py`: add functions, duplicates, `failed` paths.
- `src/ideology_app/cli.py`: `source add`, `pipeline run`, `_provider`, `_raise_if_failed`, `_echo_publish`.
- `src/ideology_app/config.py` (`generation_mode`, `llm_settings`), `src/ideology_app/llm/__init__.py`, `llm/fake.py` (`name = "fake"`).
- `tests/conftest.py`, `tests/pipeline_fixtures.py`, `tests/test_cli_source.py`, `tests/test_cli_pipeline.py`.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `docs/specs/auto-publish-dataset-version.md`.

### Existing Patterns To Follow

- Services take a `Session` and never commit; the CLI owns `session_scope`.
- Config errors are resolved before any write (as in `pipeline run`).
- `cli._provider` is the test seam, and the provider is closed in `finally`.
- Pipeline code depends on `llm.base` / `config` only.

### Current Gaps

- `GENERATION_MODE` is parsed but has no behaviour.
- No executor for runs left `queued`.
- `test_cli_source.py` has no env guard, so `GENERATION_MODE` / `LLM_*` from the shell could leak into it.

## Expected File Changes

- `src/ideology_app/pipeline/triggers.py`: create (mode table, `queues_on_source_change`, `queue_run_for_source_change`, `SourceChangeOutcome`).
- `src/ideology_app/pipeline/runs.py`: modify. Add `list_queued_run_ids(session, election_id=None) -> list[int]` (id order; `NotFoundError` for an unknown Election). Nothing else changes.
- `src/ideology_app/pipeline/__init__.py`: re-export the new names.
- `src/ideology_app/cli.py`: modify `source add` (config read and trigger call) and add `pipeline run-queued`.
- `tests/test_pipeline_triggers.py`: create (scenarios 1–7).
- `tests/test_cli_live_mode.py`: create (scenarios 2, 3 and 8–10 via the CLI).
- `tests/test_cli_source.py`: add the autouse `offline_guard` (or an env unset).

## Visual Design Impact

- UI involved: no. Backend and CLI only, so browser validation does not apply (`AGENTS.md` exempts CLI/pipeline features). No web files are touched (`landing-election-picker` is running in parallel).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Pipeline: add `triggers.py`, the mode table, coalescing and `list_queued_run_ids`.
  - LLM Providers config line: replace `GENERATION_MODE` "parsed only, no behaviour yet".
  - Replace "The CLI runs synchronously in both Generation Modes and only records the mode".
  - Runtime Surface: `source add` live output, `pipeline run-queued`.
- `CONSTRAINTS.md`: update (Pipeline). Add these rules:
  - Generation Mode MUST get its behaviour only from `pipeline.triggers.QUEUE_ON_SOURCE_CHANGE` (no `if mode == …` elsewhere).
  - The live trigger MUST run in the same transaction as the document it reacts to, and MUST NOT call an LLM.
  - Request handlers MUST NOT queue or execute runs (never per user).
- `AGENTS.md`: not needed (no workflow change).
- `CONTEXT.md`: update the Generation Mode entry: "`live` (a Pipeline Run is queued automatically when a Source Document is added or its content changes, and executed by the Operator's queue command)".
- `docs/domain-model.md`: update "Run triggers" the same way.
- `docs/technical-discovery.md`: not needed. `GENERATION_MODE` row is still accurate; line 71 "background task or a CLI command" is satisfied by the CLI command.
- `docs/risks-and-open-questions.md`: update, in the same change:
  - **LLM cost estimate / price table** (Implementation-Time, names this feature): **deferred**, re-target to "the first deployment feature, before `pipeline run-queued` is scheduled". Reason: this feature spends nothing by itself. Spending happens only when the Operator runs `run-queued`, and it is bounded by the existing per-run caps (≤ 200 Statement and ≤ 300 position calls) and by coalescing (≤ 1 queued run per Election).
  - **Provider cost/availability, especially in `live` mode**: keep. Add these mitigations and the open item: no money cap until the first deployment feature schedules execution.
  - **Runs stuck in `running`**: rewrite. The live trigger ignores `running` runs, so a stuck run never blocks queuing. `run-queued` touches only `queued` runs. Recovery (marking stale `running` runs `failed`) is **deferred** to the first deployment feature, the first truly unattended runner.
  - **New risk: concurrent executors.** Two `pipeline run-queued` processes can both start the same run (`_start` reads, then updates, without an atomic claim), on SQLite and PostgreSQL. Run one executor at a time. An atomic `UPDATE … WHERE status = 'queued'` claim is owed by the first deployment feature.
  - **Fetching manifests by URL** ("add an allow-list before … `live` mode triggers fetches"): leave as is and name `live-mode-url-refetch`. This feature triggers no fetches.

## Implementation Plan

1. Write `pipeline/triggers.py` and `runs.list_queued_run_ids`, plus `tests/test_pipeline_triggers.py`.
2. Wire `source add`, and add the env guard to `test_cli_source.py`.
3. Add `pipeline run-queued`:
   - Resolve `config.validation_settings()` and `_provider()` first.
   - Read the ids in one session. For each, call `execute_run`. On an `ElectionsError`, echo `Error: <msg>` to stderr and continue. For a `failed` outcome, echo the same message as `_raise_if_failed` to stderr. For a `passed` one, print the `pipeline run` lines.
   - Close the provider in `finally`.
   - At the end, if anything failed, raise `ClickException("K of M queued pipeline runs failed")`.
4. Write the CLI tests, update the docs and the risks doc, and run `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `triggers.py` with the mode table, outcome and function (lock, coalesce, `queue_run`).
- [ ] `list_queued_run_ids` in `runs.py`; re-exports.
- [ ] `source add` config read and trigger call; new output lines.
- [ ] `pipeline run-queued [--election N]`.
- [ ] Tests for scenarios 1–10; env guard in `test_cli_source.py`.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `CONTEXT.md`, `docs/domain-model.md`, risks doc.
- [ ] `PROGRESS.md` and `feature_list.json` evidence.

## Verification Plan

- `.venv/bin/pytest tests/test_pipeline_triggers.py tests/test_cli_live_mode.py tests/test_cli_source.py tests/test_cli_pipeline.py -q`: all pass.
- `CI=true ./init.sh`: exit 0. Pytest runs with `filterwarnings=error` and no new warnings. The web steps are unchanged.
- `grep -rn "GenerationMode\.\(LIVE\|PRECOMPUTED\)" src/`: only `config.py` (default) and `pipeline/triggers.py`.
- `alembic heads`: still `0008`. `git status` shows no changes under `apps/`, `packages/` or `src/ideology_app/{api,web.py,main.py}`.
- Manual CLI smoke in a scratch directory (`DATABASE_URL` and `SOURCE_FILES_DIR` in the scratch dir, `LLM_PROVIDER=fake`):
  1. `db upgrade`, `election create`, `party add`.
  2. `GENERATION_MODE=live source add --file <pdf>` prints the queued line.
  3. `pipeline list` shows one `queued` run with mode `live`.
  4. `pipeline run-queued` with `LLM_PROVIDER=fake` ends `failed` (no canned responses). Expected: it shows the executor runs it and reports exit 1.
  5. With `precomputed`, `source add` prints no queue line.
- E2E: not applicable (no browser-visible change). The CLI tests cover the flow.

## Evidence To Capture

- The pytest counts, `CI=true ./init.sh` result, the grep output and the smoke transcript summary, recorded in `feature_list.json` → `live-mode-source-change-trigger.evidence` and in `PROGRESS.md`. Note: no browser validation (backend only).

## Validator Checklist

- [ ] Three required tests exist and pass (live + new → queued; live + same hash → none; precomputed → none).
- [ ] The trigger never calls the LLM. The document and its run share one commit. There is at most one `queued` run per Election.
- [ ] Mode behaviour comes only from the `triggers.py` table. `precomputed` `source add` output is unchanged.
- [ ] `execute_run`, `validate_run`, publishing, checks and migrations are unchanged. No web or API files changed.
- [ ] Risks doc entries were updated as listed. `CONSTRAINTS.md`, `ARCHITECTURE.md`, `CONTEXT.md` and the domain model were updated.
- [ ] No `docs/validations/`. Evidence is in `feature_list.json` and `PROGRESS.md`.
