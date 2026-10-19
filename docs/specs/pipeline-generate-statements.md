# Feature Implementation Spec: Pipeline Run generates candidate Statements

## Source Feature

- `id`: pipeline-generate-statements (GitHub issue #10)
- `area`: pipeline
- `depends_on`: source-document-url (`accepted`), llm-provider-abstraction (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`

## Goal

The Operator runs `ideology pipeline run --election N`. A Pipeline Run is recorded and goes `queued` → `running` → `validating`. It reads the parsed Source Documents of every Party in the Election and makes LLM calls through the `LLMProvider` protocol. Its output is a `candidate` Dataset Version with a numbered list of topic-tagged Statements. The run records the provider, model, Generation Mode, prompt versions, token totals, LLM call count and timestamps. Prompts are versioned in code, and a test pins each version to the prompt text. If generation fails, the run ends `failed` with a reason and no Dataset Version is created. The run stays in `validating`; later features run the Validation checks, add Party Positions and publish.

## Non-Goals

- No Party Positions or Evidence (`pipeline-extract-positions`). The run never sees Party names.
- No Validation checks, no `validating` → `passed`/`failed` transition, no Validation report column, no publishing, no superseding (`validation-*`, `auto-publish-dataset-version`). The code must not reject duplicate, compound, mis-counted or topic-skewed Statements; that is Validation's job. Store the AI output as returned.
- No `live`-mode trigger and no background worker. The CLI runs synchronously in both Generation Modes and only records the mode.
- No run report command with durations or costs (`pipeline-run-report`), no HTTP endpoint and no UI.
- No retry or resume of a run, no deleting runs, no table linking a run to the Source Documents it used (see Risks).
- No new dependency, no change to `llm/` or `init.sh`, no fixture-file loader for the fake provider.

## Job Story

When an Election has parsed manifestos for its Parties,
I want to start one command that turns them into a candidate Questionnaire,
so the later Validation and position steps have a fixed, auditable set of Statements, with the provider, model and prompt versions recorded.

## Users And Permissions

- Operator: CLI only, no authentication (as before). Sets `LLM_PROVIDER`, `LLM_MODEL`, `GENERATION_MODE` and `ANTHROPIC_API_KEY` in the environment. Cannot edit Statements: there is no update or delete function or command.
- Voter: not affected.

## Acceptance Scenarios

All scenarios use a temporary SQLite database and a `FakeProvider`. Each pipeline test module has the autouse env and socket guard from `tests/test_llm.py`. No test reads an API key or opens a socket.

### Scenario 1: Happy path creates a candidate Dataset Version

Given a migrated database with Election 1 and Parties 1 and 2, each with one `parsed` Source Document of 2 pages, plus one `failed` document on Party 2
And a `FakeProvider` that answers `statement_candidates` with 3 candidates per call and `generate_statements` with 30 Statements over several topics
When `queue_run` and then `execute_run(engine, run_id, provider)` are called
Then the run's status is `validating`. It records `llm_provider="fake"`, `llm_model="fake-model"`, `generation_mode="precomputed"`, `prompt_versions == {"statement_candidates": "v1", "generate_statements": "v1"}`, `llm_calls == 3` (2 chunks plus 1), the summed `input_tokens`/`output_tokens` of the three results, and `created_at <= started_at <= generation_finished_at`.
And exactly one Dataset Version exists for the run: `election_id=1`, status `candidate`, 30 Statements with `position` 1..30 in the order returned and `text`/`topic` exactly as returned.
And the `failed` document was not sent to the provider.

### Scenario 2: The lifecycle is observable

Given the setup of Scenario 1
When `queue_run` returns, a separate Session reads the run's status as `queued`, with `started_at` null.
When the fake's `generate_statements` callable reads the run through a separate Session during the call, the status is `running` and no Dataset Version exists yet.
When `execute_run` returns, the status is `validating`.

### Scenario 3: Prompts are party-blind and deterministic

Given the Parties are named `Partido Alfa` / `PA` and `Bloque Beta` / `BB`, and the page text never mentions these names
When the run executes
Then no recorded `FakeProvider.calls` request has a Party name or short name in `system` or `prompt`.
Each `statement_candidates` prompt holds one chunk: the page texts as stored, each under a `[página N]` marker. The `generate_statements` prompt lists the candidates with exact duplicates removed, sorted by (topic, text), and asks for `TARGET_STATEMENT_COUNT` (30) Statements.
Running the same input twice gives identical request lists.

### Scenario 4: Long documents are chunked

Given a parsed document whose pages total more than `CHUNK_MAX_CHARS` (40,000 characters), with one single page longer than the limit and a whitespace-only page
When the chunks are built
Then each chunk has whole consecutive pages and stays at or under the limit. A page over the limit is cut into consecutive slices of at most the limit. Whitespace-only pages are left out. Chunks are ordered by Party id, then document id, then page number, and there is one `statement_candidates` call per chunk.

### Scenario 5: Generation failure ends the run `failed`

Given the fake raises `LLMOutputError` (schema mismatch) or `LLMProviderError` on any call, or every `statement_candidates` call returns an empty list
When `execute_run` is called
Then the run is `failed`, `failure_reason` is the error message (≤ 500 chars) or `no statement candidates were found in the source documents`, `generation_finished_at` is set, the tokens and call count of the calls that did succeed are kept, and no Dataset Version or Statement row exists.
And when chunks + 1 > `MAX_LLM_CALLS_PER_RUN` (200), the run fails with `too many chunks: <n> (limit 199)` before any LLM call (`provider.calls == []`).

### Scenario 6: Preconditions are checked before anything is recorded

Given an unknown Election id, or an Election whose Parties have no `parsed` Source Document
When `queue_run` is called
Then it raises `NotFoundError` (`election N not found`) or `InvalidInputError` (`election N has no parsed source documents`), and no run row is created.
Given a run that is not `queued`, or a provider whose `name`/`model` differ from the ones recorded on the run
When `execute_run` is called
Then it raises `InvalidInputError` and changes nothing.

### Scenario 7: CLI

Given a migrated database set up as in Scenario 1, and `ideology_app.cli._provider` monkeypatched to return the fake
When `ideology --database-url … pipeline run --election 1` runs
Then it exits 0 and prints `Pipeline run 1: validating (dataset version 1, 30 statements)`.
`pipeline list --election 1` prints the header `id status provider model mode dataset_version statements llm_calls input_tokens output_tokens failure_reason` and one tab-separated row.
`pipeline statements --dataset-version 1` prints the header `position topic text` and 30 rows.
When the fake fails, `pipeline run` commits the `failed` run, prints `Error: pipeline run <id> failed: <reason>` to stderr and exits 1.
With `LLM_PROVIDER=bogus` (the real `_provider`), it exits 1 with `Error: Invalid LLM_PROVIDER 'bogus'; supported values: anthropic, fake` and creates no run row. `GENERATION_MODE=bogus` behaves the same way.
On a database at `0003` or not migrated, every `pipeline` command exits 1 with the `NOT_INITIALISED` message. A missing election or dataset version exits 1 with `Error: … not found`.

### Scenario 8: Prompt versions are pinned

Given `tests/test_pipeline_prompts.py` holds a SHA-256 fingerprint for each `(task, version)`, computed over the system text, the prompt template and `schema.model_json_schema()` (sorted JSON)
When a prompt or its schema changes without a version bump and a new fingerprint
Then the test fails.

### Scenario 9: Migration 0004

`upgrade head` gives revision `0004` with tables `pipeline_runs`, `dataset_versions` and `statements`. A second upgrade does nothing. `downgrade 0003` drops exactly those three tables. `alembic check` finds no drift. The offline PostgreSQL render has each new CHECK exactly once. The database rejects a bad status, a duplicate `pipeline_run_id` in `dataset_versions`, a duplicate `(dataset_version_id, position)` and `position = 0`. Deleting an Election cascades to its runs, Dataset Versions and Statements.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`: Pipeline Run fields (provider, model, prompt versions, Generation Mode, timestamps, status); the Dataset Version lifecycle (`candidate` → `published` → `superseded`); Statement = text, topic tag, order; the neutral-wording rule; token and cost visibility; chunking listed as an implementation-time question.
- `PROGRESS.md`, `feature_list.json`: this feature is next; `validation-questionnaire-shape` owns checks 1, 5 and 6; `pipeline-run-report` owns the report.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`: migration workflow (autogenerate, then remove the duplicate Enum CHECKs by hand), non-native Enums, engine disposal, offline tests, the provider only through `build_provider` or injection.
- `src/ideology_app/models.py`, `db.py`, `config.py`, `cli.py`, `elections.py`, `source_documents.py`, `llm/{__init__,base,fake,anthropic_provider}.py`, `migrations/versions/0002_*.py`.
- `tests/conftest.py`, `tests/test_llm.py` (offline guard), `tests/test_migrations.py` (head, downgrade, PG render that counts `CHECK` == 6), `tests/test_cli_source.py` (not-initialised parametrisation).
- `docs/specs/llm-provider-abstraction.md`, `docs/specs/source-document-url.md`: format and detail level.
- Not inspected: no `.venv` exists in this worktree yet (`./init.sh` creates it). No new packages are needed; `sa.JSON` and pydantic are already available.

### Existing Patterns To Follow

- Service functions take a `Session` and raise `elections.NotFoundError` / `InvalidInputError`; `requires_db` turns them into exit 1.
- The CLI commits a `failed` row, then raises `ClickException` (as `source add` does).
- `_enum(...)` for non-native Enums, `_utcnow` for timestamps, and the `NAMING_CONVENTION` names.
- `FakeProvider` callables keyed by `task`. Note that `build_provider` with `LLM_PROVIDER=fake` returns a fake with no responses, which fails on every call. The CLI therefore needs a seam that tests can patch.

### Current Gaps

- No Pipeline Run, Dataset Version or Statement model, migration, service or CLI. Nothing imports `llm` yet.

## Technical Approach

**Models** (`models.py`). The Enums are non-native with one CHECK each.

- `PipelineRunStatus`: `queued, running, validating, passed, failed`. The enum holds the full domain lifecycle now, so later features need no CHECK migration; this feature only sets the first three and `failed`.
- `DatasetVersionStatus`: `candidate, published, superseded`.
- The column type for `GenerationMode` is `config.GenerationMode` (enum name `generation_mode`).
- `PipelineRun` (`pipeline_runs`):
  - `id`; `election_id` (FK `elections.id` with cascade, indexed); `status`;
  - `llm_provider` String(50), `llm_model` String(200), `generation_mode`;
  - `prompt_versions` `sa.JSON` (dict task → version);
  - `llm_calls`, `input_tokens`, `output_tokens` Integer, default 0;
  - `failure_reason` String(500), nullable;
  - `created_at`, `started_at` (nullable), `generation_finished_at` (nullable), all timezone-aware;
  - relationship `dataset_version` (uselist=False).
- `DatasetVersion` (`dataset_versions`): `id`; `election_id` (FK cascade, indexed); `pipeline_run_id` (FK `pipeline_runs.id` cascade, unique); `status` (default `candidate`); `created_at`; relationship `statements` ordered by `position`.
- `Statement` (`statements`): `id`; `dataset_version_id` (FK cascade); `position` Integer with CHECK `position_positive` (`position >= 1`); `text` String(300); `topic` String(50). Unique `(dataset_version_id, position)`. `topic` is not an Enum, because the topic list is versioned with the prompts.

**Migration** `0004_pipeline_runs_statements.py`: autogenerate with `--rev-id 0004`, remove the duplicate `sa.CheckConstraint` lines, and run `alembic check`.

**Package `src/ideology_app/pipeline/`.** It depends on `models`, `elections` (errors) and `llm.base` (protocol, request and errors) only, never on a concrete provider.

- `prompts.py`:
  - `TOPICS`, a tuple of slugs: `economy, taxation, employment, pensions, housing, health, education, environment_energy, immigration, justice_security, territorial_model, democracy_institutions, foreign_policy_defense, social_rights_equality, culture_language, agriculture_rural, science_digital, infrastructure_transport`. `Topic` is a `Literal` built from it.
  - Schemas: `StatementDraft(text: str, 1..300 chars, must contain a non-space character; topic: Topic)`, `CandidateList(candidates: list[StatementDraft], max 12)`, `StatementSet(statements: list[StatementDraft], 1..60)`.
  - `PromptSpec(task, version, system, template, schema, max_tokens)`: `STATEMENT_CANDIDATES` (`v1`, 4096 tokens) and `GENERATE_STATEMENTS` (`v1`, 8192 tokens). Templates use `str.format` fields.
  - `PROMPT_VERSIONS = {task: version}`, and `TARGET_STATEMENT_COUNT = 30`.
  - System rules for both prompts. Write in Spanish (Spain). One proposition per Statement: never join two policies with "y", "o" or "y/o". Neutral wording: no loaded adjectives, no party or politician names, no attribution ("el programa propone…"). Each Statement is an affirmative policy proposal that a Voter can agree or disagree with on a 5-point scale. Prefer propositions that the source parties would answer differently. Use only the given topic slugs.
  - The reduce prompt adds these rules: cover topics broadly, with no topic over about a quarter of the list; no near-duplicates; about `TARGET_STATEMENT_COUNT` Statements.
- `generation.py`:
  - `CHUNK_MAX_CHARS = 40_000` and `MAX_LLM_CALLS_PER_RUN = 200`.
  - `build_chunks(documents) -> list[str]` is a pure function that follows Scenario 4.
    Implementation note: a chunk never spans two documents (Scenario 1's `llm_calls == 3` for two small documents requires this). Pages are joined by a blank line, the limit counts the markers and separators, and each slice of an over-long page keeps its `[página N]` marker.
  - `generate_statements(provider, chunks, usage) -> list[StatementDraft]` does one `statement_candidates` call per chunk, then dedupes and sorts (Scenario 3), then makes one `generate_statements` call. `usage` is a small mutable dataclass (`calls`, `input_tokens`, `output_tokens`), updated after each successful call, so a failed run keeps partial counts.
  - Raises `GenerationError` for "no candidates" and "too many chunks". `LLMError` propagates.
- `runs.py`:
  - `queue_run(session, election_id, *, llm_provider, llm_model, generation_mode) -> PipelineRun`: checks Scenario 6 and flushes. The caller commits.
  - `execute_run(engine, run_id, provider) -> RunOutcome`, a frozen dataclass with `run_id, status, dataset_version_id, statement_count, failure_reason`. It works in three steps:
    1. In one `session_scope`: check the run, set `running` and `started_at`, and load the parsed pages of the Election's Parties into plain data (no ORM objects leave the session). This commits.
    2. Call `generate_statements` outside any transaction.
    3. In a second `session_scope`, either insert the `DatasetVersion` and its Statements, set `validating`, and record usage and `generation_finished_at`; or, on `LLMError`/`GenerationError`, set `failed` with `str(exc)[:500]` and the usage. Any other exception sets `failed` with `unexpected error: <ClassName>` and is re-raised.
  - Also `list_runs(session, election_id)` and `get_dataset_version(session, id)` (`NotFoundError`).
- `__init__.py` re-exports these.

**CLI** (`cli.py`):

- `_provider() -> LLMProvider` returns `build_provider(llm_settings())`. It is the test seam.
- Group `pipeline`:
  - `run --election`: read the settings and mode, turning `ConfigError` into `ClickException` before any write; `queue_run` in a `session_scope`; `execute_run`; finally, close the provider if it has `close`. Print as in Scenario 7.
  - `list --election`.
  - `statements --dataset-version`.
- All three use `requires_db`.

## Expected File Changes

- `src/ideology_app/models.py`: modify (3 models, 2 enums, relationships on `Election`).
- `src/ideology_app/migrations/versions/0004_pipeline_runs_statements.py`: create.
- `src/ideology_app/pipeline/{__init__,prompts,generation,runs}.py`: create.
- `src/ideology_app/cli.py`: modify (`_provider`, `pipeline` group).
- `tests/pipeline_fixtures.py` (helpers that insert parsed documents straight through the ORM, plus fake responses), `tests/test_pipeline_generation.py`, `tests/test_pipeline_runs.py`, `tests/test_pipeline_prompts.py`, `tests/test_cli_pipeline.py`: create.
- `tests/test_migrations.py`: modify (head `0004`, `ALL_TABLES`, downgrade to `0003`, `is_initialised` at `0003`, new constraint cases, PG render counts: `CHECK` 6 → 10).
- `tests/test_cli.py` / `tests/test_cli_source.py`: modify only if a head-dependent assertion breaks (add `0003` to the not-initialised parametrisation).
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `feature_list.json`, `PROGRESS.md`: see below.

## Visual Design Impact

- UI involved: no. Design source: not applicable. Browser validation is exempt (CLI and pipeline only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Data Layer: the new models and migration `0004`.
  - New "Pipeline" section: package layout, dependency direction (`models`/`elections`/`llm.base` → `pipeline` → `cli`), the two-stage map/reduce, the constants, the run lifecycle and its commit points, and how to bump a prompt version.
  - Runtime Surface: the `pipeline` commands. Update "Nothing else imports `llm` yet".
- `CONSTRAINTS.md`: update with a "Pipeline" section:
  - Any change to a prompt's system text, template or schema MUST bump its version and fingerprint. Reason: runs must record the prompt actually used.
  - The pipeline MUST NOT send Party names to the LLM when generating Statements. Reason: perceived bias.
  - Dataset Versions and Statements MUST NOT be updated or deleted by application code (only cascades). Reason: immutability.
  - `pipeline` MUST depend on `LLMProvider`, not a concrete provider.
- `AGENTS.md`: not needed. The invariants already cover this.
- `docs/risks-and-open-questions.md`: update. The chunking question for Statements is settled (map/reduce, 40k chars). Add the open risk of runs left `running` after a crash.

## Implementation Plan

1. Models, then migration `0004`, then the migration tests (Scenario 9).
2. `pipeline/prompts.py` and the fingerprint test (Scenario 8).
3. `pipeline/generation.py` with chunking and generation unit tests (Scenarios 3, 4, part of 5).
4. `pipeline/runs.py` with service tests (Scenarios 1, 2, 5, 6).
5. CLI group and tests (Scenario 7).
6. Docs, then `CI=true ./init.sh`, then evidence.

## Implementation Tasks

- [ ] Enums and models; autogenerate `0004`, remove the duplicate CHECKs, run `alembic check`.
- [ ] Update `tests/test_migrations.py`.
- [ ] `prompts.py` (topics, schemas, two `PromptSpec`s, versions); `test_pipeline_prompts.py` (fingerprints, schema rejects a bad topic, empty or whitespace text, over 300 chars, over 12 candidates).
- [ ] `generation.py` (`build_chunks`, `Usage`, `GenerationError`, `generate_statements`) and its tests.
- [ ] `runs.py` (`queue_run`, `execute_run`, `RunOutcome`, `list_runs`, `get_dataset_version`) and its tests, with the offline guard.
- [ ] CLI `_provider` and the `pipeline run|list|statements` commands; `test_cli_pipeline.py`.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`.

## Verification Plan

- `CI=true ./init.sh`: exit 0, with pytest count = 246 + new tests and node 41 passed.
- `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider`: clean, with no `ResourceWarning`.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -q tests/test_pipeline_*.py tests/test_cli_pipeline.py`: passes.
- `DATABASE_URL=sqlite:///<scratch>/x.db .venv/bin/alembic -c alembic.ini history`: shows `0003 -> 0004 (head)`. `alembic check`: no drift.
- `grep -rn "anthropic\|FakeProvider\|build_provider" src/ideology_app/pipeline`: no matches.
- Manual CLI smoke in a scratch directory outside the repo:
  - `db upgrade`, an Election, two Parties, `source add --file` with PDFs built by `tests/pdf_factory.py`.
  - `LLM_PROVIDER=fake ideology pipeline run --election 1` should exit 1 with a `failed` run ("FakeProvider has no response…"), and `pipeline list` should show it. This also proves the config path without a key or network.
  - `LLM_PROVIDER=anthropic` with no key should exit 1 with `pipeline run N failed: ANTHROPIC_API_KEY is not set`.
  - Delete the scratch directory afterwards.
- No E2E harness or browser surface. Service and CliRunner tests with the fake cover the flow.
- `init.sh` stays unchanged and starts no process.

## Evidence To Capture

- `init.sh` exit code and test counts; the `-X dev` run; alembic history/check; the grep result; the manual smoke results; and which test covers each of Scenarios 1–9. Record them in `feature_list.json` → `pipeline-generate-statements.evidence` and in a `PROGRESS.md` session. Never in `docs/validations/`.

## Risks

- A crash between the commits leaves a run in `running`. There is no recovery command yet, so the Operator queues a new run.
- The Source Documents used are not recorded per run. A document added during a run could be used by a later positions step. Revisit in `pipeline-extract-positions` or `live-mode-source-change-trigger`.
- Real-LLM quality (neutral wording, single propositions, the topic list, 40k-char chunks) is only tested in `e2e-real-2023-election`. The prompts are `v1`.

## Validator Checklist

- [ ] Each of Scenarios 1–9 has a named passing test. The CLI smoke was done offline.
- [ ] Runs stop at `validating`, and no Validation, position, publish or report work was added.
- [ ] Statements are stored exactly as the provider returned them. No update or delete path exists.
- [ ] No Party name reaches a prompt. The prompt versions are recorded on the run and pinned by fingerprints.
- [ ] The provider is resolved only through `build_provider` in `cli._provider`, and `pipeline/` imports only `llm.base`.
- [ ] Migration `0004` was reviewed, with each CHECK once and no drift.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, the risks doc, `feature_list.json` and `PROGRESS.md` are updated.
