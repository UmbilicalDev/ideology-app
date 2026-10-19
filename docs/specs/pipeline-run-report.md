# Feature Implementation Spec: Operator can inspect a Pipeline Run report

## Source Feature

- `id`: pipeline-run-report
- `area`: operations
- `depends_on`: auto-publish-dataset-version (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "pytest: the report command prints the stored fields for a passed run and a failed run"; notes: "Observability per docs/technical-discovery.md. Read-only: AI output cannot be edited.")

## Goal

A new read-only command, `ideology pipeline report --run N`, prints one Pipeline Run's report. The report shows:

- status, provider, model, Generation Mode and prompt versions;
- timestamps and a duration;
- LLM calls and token counts;
- the Validation thresholds the run was validated with;
- the run's Dataset Version and its publication state, which tells a passed-but-`candidate` run apart from a failed one;
- the Validation report (the same rows as `pipeline checks`).

The command only reads existing data. The one schema addition records the `ValidationSettings` a run was validated with (migration `0008`).

## Decisions

- **Stored vs new fields.** Everything except the Validation thresholds is already stored. The report derives the rest at read time.

  | Report line | Source | New? |
  |---|---|---|
  | status, failure_reason, provider, model, generation_mode, prompt_versions, created_at, started_at, generation_finished_at, llm_calls, input_tokens, output_tokens | `pipeline_runs` columns (`0004`) | stored |
  | validated_at | earliest `validation_results.created_at` of the run (`0006`) | derived |
  | duration | `generation_finished_at - started_at` | derived |
  | dataset_version, dataset_version_status, statements | `dataset_versions` (`0004`/`0007`), `statements` | stored |
  | publication (live version of the Election) | `publishing.get_published_dataset_version` | derived |
  | Validation report | `validation_results`, `validation_report_entries` (`0006`) | stored |
  | validation_settings | **new** nullable JSON column `pipeline_runs.validation_settings` (`0008`) | **new** |

- **Token/cost: tokens only. No provider-layer change and no cost estimate.** The provider layer already reports usage: `FakeProvider` returns deterministic word-count tokens, and `AnthropicProvider` returns `message.usage`. `runs._finish` already stores `llm_calls`, `input_tokens` and `output_tokens` on every run that finishes generation, failed runs included. No price table exists, and prices are volatile, so the report prints `cost: not estimated (no price table)` and stops there. A cost estimate or cost cap belongs to a later feature (see the risks doc update). Runs that never finished generation (`queued`/`running`, `generation_finished_at` null) print `not recorded` for the three usage lines, because the stored zeros would be misleading.
- **Duration = generation time only.** It runs from `started_at` to `generation_finished_at`, formatted `f"{seconds:.1f} s"`, and is `not recorded` when either timestamp is null. Validation finishes in milliseconds, but it can happen much later through `pipeline validate`, so `validated_at` is printed as its own line instead of being added to the duration. A run-level `finished_at` column is **not** added (it would touch every failure path).
- **Risk entry 1 (thresholds not stored): settled here.** `validate_run` stores `dataclasses.asdict(settings)` in `run.validation_settings`, in the same commit as the results and the `passed`/`failed` status, on both outcomes. On the unexpected-error path the transaction rolls back, so the column stays null. Runs validated before `0008` have no backfill and show `not recorded`. All four `ValidationSettings` fields are recorded, not only the coverage threshold.
- **Risk entry 2 (passed-but-`candidate`): settled here.** The `publication` line spells out the state and always names the Election's live version (see Scenario 3). `pipeline list` is **not** changed.
- **Read-only.** The command has one option, `--run`. The service only runs `SELECT`s and has no write path for Statements, Party Positions, Evidence, statuses or results.

## Non-Goals

- No cost/price table, no cost cap, and no change to `llm/` (`base.py`, `fake.py`, `anthropic_provider.py`).
- No change to `pipeline list`, `pipeline checks` output, checks, `ValidationSettings` fields, prompts, publishing rules or `init.sh`.
- No per-call usage log, no `finished_at` column, no backfill of old runs, no JSON output format, no HTTP endpoint, no UI.
- No recovery of runs stuck in `running`.

## Job Story

When a run has finished (or seems stuck),
I want one command that shows what it used, what it cost in tokens, how long it took, why Validation passed or failed, and whether its version is live,
so I can decide whether to re-run, change a threshold deliberately, or leave it alone, without editing anything.

## Users And Permissions

- Operator: CLI only, read-only. No API key or LLM provider needed. Voters are not affected.

## Output Format (exact)

These lines go to stdout, in this order, as `key: value`:

```
pipeline run: <id>
election: <election_id>
status: <status>
failure_reason: <reason | none>
provider: <llm_provider>
model: <llm_model>
generation_mode: <precomputed|live>
prompt_versions: <task=version, ... sorted by task>
created_at: <iso>
started_at: <iso | not recorded>
generation_finished_at: <iso | not recorded>
validated_at: <iso | not recorded>
duration: <S.s s (generation) | not recorded>
llm_calls: <n | not recorded>
input_tokens: <n | not recorded>
output_tokens: <n | not recorded>
cost: not estimated (no price table)
validation_settings: <key=value, ... sorted by key | not recorded>
dataset_version: <id | none>
dataset_version_status: <candidate|published|superseded | none>
statements: <count | none>
publication: <see below>

validation report:
check	result	statement	party	message
<rows exactly as `ideology pipeline checks --run N`>
```

Timestamps are printed with `isoformat(timespec="seconds")` of the stored value. Multi-line values (`failure_reason`) go through `_one_line`. A run that was never validated prints the table header with no rows.

`publication` values, where `<live>` is `dataset version X of pipeline run R` or `none`:

- no version, run `failed`: `none: the run failed before a dataset version was created`
- no version, run `queued`/`running`: `none: the run has not produced a dataset version yet`
- `candidate`, run `validating`: `not published: awaiting Validation (run "ideology pipeline validate --run N")`
- `candidate`, run `failed`: `not published: the run failed; live for election E: <live>`
- `candidate`, run `passed`: `not published: the run passed but its dataset version was kept candidate; live for election E: <live>`
- `published`: `published: live for election E`
- `superseded`: `superseded: live for election E: <live>`

An unknown run exits 1 with `Error: pipeline run N not found`. A database not at head exits 1 with the standard `NOT_INITIALISED` message.

## Acceptance Scenarios

All scenarios use temporary SQLite with `FakeProvider` through `cli._provider` and the autouse env/socket guard. They need no API key and no network.

### Scenario 1: passed and published run
Given a seeded Election and `pipeline run --election 1` that passed
When `pipeline report --run 1` runs
Then it exits 0, prints `status: passed`, `failure_reason: none`, `provider: fake`, `model: fake-model`, the four `PROMPT_VERSIONS` entries, `llm_calls`/`input_tokens`/`output_tokens` equal to the `pipeline_runs` row (non-zero, deterministic), `validation_settings: max_statements=35, max_topic_share_percent=30, min_party_coverage_percent=70, min_statements=25`, `dataset_version_status: published`, `publication: published: live for election 1`, and six `<check>\tpassed` rows identical to `pipeline checks --run 1`.

### Scenario 2: failed run (Validation failure)
Given a run that failed `statement_count` (or `party_coverage`, using existing fixtures)
When `pipeline report` runs on it
Then `status: failed`, `failure_reason: validation failed: …`, `dataset_version_status: candidate`, `publication: not published: the run failed; live for election 1: none` (or the earlier live version), and the failed check's entry rows appear in the report.

### Scenario 3: passed but kept `candidate`
Given run 1 left `validating`, run 2 passed and published, then `pipeline validate --run 1` (as in `test_validate_an_older_run_after_a_newer_one_published`)
When `pipeline report --run 1` runs
Then `status: passed`, `dataset_version_status: candidate`, `publication: not published: the run passed but its dataset version was kept candidate; live for election 1: dataset version 2 of pipeline run 2`. This line differs from Scenario 2's.

### Scenario 4: superseded run
Given two passing runs
When run 1 is reported
Then `dataset_version_status: superseded`, `publication: superseded: live for election 1: dataset version 2 of pipeline run 2`.

### Scenario 5: run failed during generation
Given a run whose `generate_statements` call raised `LLMProviderError`
Then `status: failed`, the reason is shown, `dataset_version: none`, `publication: none: the run failed before a dataset version was created`, `validated_at`/`validation_settings: not recorded`, the usage lines are the stored numbers, and the report table has only its header.

### Scenario 6: stored thresholds and older runs
Given `VALIDATION_MIN_PARTY_COVERAGE_PERCENT=50` for `pipeline run` (and separately for `pipeline validate`)
Then the report shows `min_party_coverage_percent=50`. Given a run whose `validation_settings` is set to NULL (simulating a pre-`0008` run), the report shows `validation_settings: not recorded`. Given a check that raises in `validate_run`, the column stays NULL.

### Scenario 7: duration, validating and queued runs
Given a run with `started_at` and `generation_finished_at` set 12.34 s apart (by direct ORM update in the test)
Then `duration: 12.3 s (generation)`. A `validating` run shows the awaiting-Validation `publication` line. A `queued` run shows `not recorded` for timestamps, duration and usage, and `publication: none: the run has not produced a dataset version yet`.

### Scenario 8: read-only and errors
Given any database
When `pipeline report` runs
Then every table's rows (`pipeline_runs`, `dataset_versions`, `statements`, `party_positions`, `validation_results`, `validation_report_entries`, `elections`) are identical before and after. `pipeline report --help` lists only `--run`. An unknown run exits 1, a missing `--run` exits 2, and a database at `0007` exits 1 with `NOT_INITIALISED`.

## Repository Research

### Files Inspected

- `src/ideology_app/models.py`: `PipelineRun` (all stored fields above), `DatasetVersion`, `ValidationResult.created_at`.
- `src/ideology_app/pipeline/runs.py`: `_start` sets `started_at`; `_finish` sets usage and `generation_finished_at` on success and failure; `validate_run` (where settings get stored); `list_validation_results`.
- `src/ideology_app/pipeline/publishing.py`: `get_published_dataset_version`.
- `src/ideology_app/cli.py`: `requires_db`, `_print_rows`, `_one_line`, `pipeline_checks` (row building to extract and reuse).
- `src/ideology_app/config.py`: `ValidationSettings` (frozen dataclass, four int fields).
- `src/ideology_app/llm/fake.py`, `llm/anthropic_provider.py`: both already report usage.
- `src/ideology_app/migrations/versions/0007_*.py`: head, batch style.
- `tests/test_cli_pipeline.py`, `tests/pipeline_fixtures.py`, `tests/test_migrations.py`.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/technical-discovery.md` (Observability), `docs/risks-and-open-questions.md`.

### Existing Patterns To Follow

- Service functions take a `Session` and raise `NotFoundError`; the CLI formats the output (`pipeline checks`).
- Migrations: change `models.py`, autogenerate in a scratch DB with `--rev-id 0008`, review by hand, `alembic check`.
- CLI tests use `CliRunner` + `use_fake` + `seeded`, and `_validating_run` for the validating/older-run cases.

### Current Gaps

- There is no single-run view, no stored thresholds, and no version status shown anywhere in the CLI.

## Technical Approach

1. **Model + migration.** Add `validation_settings: Mapped[dict[str, int] | None] = mapped_column(sa.JSON)` to `PipelineRun`. In `0008_pipeline_run_validation_settings.py` (`down_revision = '0007'`), add `batch_op.add_column(sa.Column('validation_settings', sa.JSON(), nullable=True))` and drop it on downgrade. No CHECK, no data migration. The partial unique index on `dataset_versions` is untouched.
2. **Record settings.** In `validate_run`, set `run.validation_settings = dataclasses.asdict(settings)` inside the session before the status flush, on both outcomes. Nothing else in `runs.py` changes.
3. **Service.** Create a new module `pipeline/reports.py` with `get_run_report(session, run_id) -> RunReport`. `RunReport` is a frozen dataclass of plain values: the run's fields, `validated_at`, `dataset_version_id`, `dataset_version_status`, `statement_count`, `live_dataset_version_id`, `live_run_id`, and `results` (from `list_validation_results`). It only reads (`session.get`, `select`, `func.min`, `get_published_dataset_version`). Re-export it from `pipeline/__init__.py`. Dependency: `models`, `publishing`, `runs` → `reports` → `cli`.
4. **CLI.** Add `pipeline report --run` under `@requires_db`. Extract `_check_rows(results)` from `pipeline_checks` so both commands share it, with `pipeline checks` output unchanged. Format the lines exactly as specified; the duration and `publication` strings are built in small pure helpers.

## Expected File Changes

- `src/ideology_app/models.py`: modify; `PipelineRun.validation_settings`.
- `src/ideology_app/migrations/versions/0008_pipeline_run_validation_settings.py`: create.
- `src/ideology_app/pipeline/runs.py`: modify; store settings in `validate_run`.
- `src/ideology_app/pipeline/reports.py`: create. `pipeline/__init__.py`: modify (re-export).
- `src/ideology_app/cli.py`: modify; `pipeline report`, `_check_rows`.
- `tests/test_cli_pipeline_report.py`: create (Scenarios 1-8, autouse `offline_guard`).
- `tests/test_validation_runs.py`: modify; settings stored on pass/fail, NULL on a raising check.
- `tests/test_migrations.py`: modify; head `0008`, `is_initialised` ladder includes `0007`, downgrade to `0007` drops only the column (and keeps `uq_dataset_versions_published_election_id`), no drift, offline PostgreSQL render adds the column (CHECK count unchanged).

## Visual Design Impact

- UI involved: no (CLI only). Browser validation is exempt.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add the `0008` column to the Data Layer, `reports.py` to Pipeline, the `pipeline report` command to Runtime Surface, and change the `ValidationSettings` note "not stored on the run" to "recorded on the run by `validate_run`".
- `CONSTRAINTS.md`: update (Validation). `pipeline_runs.validation_settings` MUST be written only by `validate_run`, in the results commit, and never updated. `pipeline report` MUST stay read-only.
- `docs/domain-model.md`: update. Pipeline Run also records its Validation thresholds.
- `docs/risks-and-open-questions.md`: delete the two Accepted Low entries naming this feature (coverage threshold not stored; passed-but-`candidate` indistinguishable). Add an Implementation-Time Question: "LLM cost estimate per run: tokens are recorded and shown by `pipeline report`, but there is no price table; add one with the `live` mode cost cap (`live-mode-source-change-trigger`)". Add an Accepted Low: "runs validated before `0008` show `validation_settings: not recorded`; the report's duration covers generation only".
- `AGENTS.md`, `CONTEXT.md`, `docs/technical-discovery.md`: not needed (no workflow or term change; Observability already lists these fields). `PROGRESS.md` operator CLI line: add `report`.

## Implementation Tasks

- [ ] Add the model column and migration `0008`; run autogenerate in a scratch DB, review it, confirm `alembic check` reports no drift.
- [ ] Store `asdict(settings)` in `validate_run`; extend `tests/test_validation_runs.py`.
- [ ] Write `pipeline/reports.py` and its re-export.
- [ ] Extract `_check_rows`; add `pipeline report`; check that the existing `pipeline checks` tests still pass unchanged.
- [ ] Write `tests/test_cli_pipeline_report.py` (Scenarios 1-8) and update `tests/test_migrations.py`.
- [ ] Update the docs listed above, plus `feature_list.json` evidence and `PROGRESS.md`.

## Verification Plan

- `CI=true ./init.sh` exits 0.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` passes clean.
- Focused: `pytest tests/test_cli_pipeline_report.py tests/test_cli_pipeline.py tests/test_validation_runs.py tests/test_migrations.py`. This must include a passed run (Scenario 1), a failed run (Scenarios 2 and 5) and the passed-but-`candidate` case (Scenario 3).
- On a scratch SQLite DB outside the repo: `alembic heads` → `0008 (head)`; `alembic check` → no drift; `upgrade 0007:0008 --sql` with a PostgreSQL URL shows `ALTER TABLE pipeline_runs ADD COLUMN validation_settings JSON`.
- `git diff --stat main -- src/ideology_app/llm src/ideology_app/validation src/ideology_app/pipeline/prompts.py src/ideology_app/pipeline/publishing.py init.sh pyproject.toml` is empty.
- No E2E harness applies (CLI only; CliRunner tests cover the flow).

## Evidence To Capture

- Test counts from both pytest runs; the focused test names for Scenarios 1-3 and 5; the alembic heads/check/PostgreSQL render output; the scope diff. Record it in `feature_list.json` → `pipeline-run-report.evidence` and `PROGRESS.md`. Note "browser validation exempt (CLI only)". Never create `docs/validations/`.

## Validator Checklist

- [ ] The report prints every field in the Output Format, exactly, for passed, failed, passed-but-`candidate`, superseded, generation-failed, validating and queued runs.
- [ ] The passed-but-`candidate` `publication` line differs from the failed-run line and names the live version.
- [ ] `validation_settings` is written only in `validate_run`'s results commit (pass and fail), stays NULL on the rollback path, and shows `not recorded` for NULL.
- [ ] The command is read-only: table rows are unchanged and it has no options other than `--run`. No `llm/` change, no cost table.
- [ ] Migration `0008` is reviewed: one nullable column, the downgrade drops only it, the partial index is kept, no drift.
- [ ] `pipeline checks` and `pipeline list` output is unchanged.
- [ ] Docs and risk entries are updated as listed. `feature_list.json` and `PROGRESS.md` are updated. No `docs/validations/`.
