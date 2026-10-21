# Feature Implementation Spec: Bound the Statement count and Statement numbers in the LLM output schemas

## Source Feature

- `id`: pipeline-output-bounds
- `area`: pipeline
- `depends_on`: none (`e2e-real-2023-election` depends on this feature)
- `status`: `not_started` at planning time
- `source`: `feature_list.json`

## Goal

Real runs on the 2023 manifestos (`e2e-real-2023-election`) showed two problems:

- `generate_statements` returned 38 and then 44 Statements. The schema allows 1..60 (`StatementSet`), so the run only failed hours later, at the `statement_count` Validation check.
- `position_findings` returned a finding for Statement 101, which does not exist. The schema only says `ge=1`.

After this feature, the structured-output schema of each request carries the bounds that the result must meet:

- the `generate_statements` schema bounds the Statement count to the same `ValidationSettings` range that Validation enforces (`VALIDATION_MIN_STATEMENTS` / `VALIDATION_MAX_STATEMENTS`, defaults 25 and 35);
- every `statement` number in `position_findings` and `party_positions` is bounded to 1..N, where N is the number of Statements listed in that request;
- every `evidence` index in `party_positions` is bounded to 1..K, where K is the number of candidates listed in that request.

When the model gives an out-of-range answer, the provider either corrects it (the `claude_code` CLI retries against the schema) or that call fails with `LLMOutputError`. The run then ends `failed` and can be resumed with `--resume-from`.

## Non-Goals

- No retry loop in `execute_run` or the providers for `LLMOutputError`. A rejected call still fails the run.
- Pages are not bounded: a finding's `page` is not limited to the pages of its chunk (`evidence_quotes` catches page slips). Quote text and `findings` length are not bounded either (60 stays).
- Validation does not change. `statement_count` stays as it is: it still catches runs validated later with other thresholds (`pipeline validate`) and older runs.
- No change to `statement_candidates` (its prompt, its schema and its request hash stay byte-identical), to chunking, to call caps or to the checkpoint mechanism.
- No real LLM, no network, no `claude` CLI in tests. Nothing touches `data/ideology.db` or the external data directory.

## Job Story

When I run the pipeline with a real model on many manifestos,
I want an out-of-range Statement list or an unknown Statement number to be rejected at the call that produced it,
so I can correct or resume the run without waiting hours for Validation to fail, and so no stance is ever attached to a Statement that does not exist.

## Users And Permissions

- Operator (CLI `ideology pipeline run`): the only actor. Nothing changes for Voters or the API.

## Acceptance Scenarios

### Scenario 1: an out-of-range Statement count is rejected at generation
Given the default settings (25..35)
When the fake `generate_statements` response has 38 Statements (or 44, or 20)
Then the call raises `LLMOutputError` (`FakeProvider response for task 'generate_statements' does not match StatementSet: …`), the run ends `failed` with that reason and has no Dataset Version, and no position call is made.

### Scenario 2: the schema follows the configured range
Given `VALIDATION_MIN_STATEMENTS=36` and `VALIDATION_MAX_STATEMENTS=40` in the env (read by `pipeline run`)
When the fake returns 38 Statements
Then generation succeeds and Validation passes `statement_count`. The `generate_statements` request schema has `minItems: 36` and `maxItems: 40`, and the prompt says 36..40.
And with the same env a 30-Statement response fails at generation.

### Scenario 3: in-range output passes unchanged
Given the default fixtures (30 Statements, in-range findings and choices)
When a run executes
Then it passes exactly as before: same Statements, positions and Validation results.

### Scenario 4: an unknown Statement number in findings is rejected
Given a run with 30 Statements
When a `position_findings` response contains `statement: 101` (or 31, or 0)
Then that call raises `LLMOutputError` (`… does not match FindingList: …`) and the run ends `failed`.

### Scenario 5: unknown Statement or evidence numbers in Party Positions are rejected
Given a run with 30 Statements and a Party whose reduce request lists K candidates
When a `party_positions` choice has `statement: 31` or `evidence: K+1`, or the list has more than 30 entries
Then that call raises `LLMOutputError` (`… does not match PositionList: …`). A repeated Statement is still a `GenerationError` (`party_positions repeated statement <n>`).

### Scenario 6: the bounds reach both real providers
Given a bounded request
Then `ClaudeCodeProvider`'s `--json-schema` argument (`build_argv`) contains `"maximum": N` for `statement` (and `"maximum": K` for `evidence`, `minItems` and `maxItems` for `statements`).
And for `AnthropicProvider`, through `httpx2.MockTransport`, an out-of-range JSON answer raises `LLMOutputError`. The Anthropic SDK (1.15, `lib/_parse/_transform.py`) does not send `minimum`, `maximum`, `maxItems` or a `minItems` above 1 as constraints. It appends them to the field `description` as hints and validates the answer on the client.

### Scenario 7: checkpoint reuse
Given a stopped run R recorded with this feature's code
When `--resume-from R` is used with the same settings
Then every call is reused (all four tasks).
Given a stopped run recorded with a wider range (simulating the old 1..60 schema, e.g. `ValidationSettings(max_statements=60)`) with 44 Statements
When it is resumed with the defaults
Then every `statement_candidates` call is reused, `generate_statements` misses and calls the provider, and the run continues.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/prompts.py`: the static schemas (`StatementSet` 1..60, `Finding.statement ≥ 1`, `PositionChoice.statement/evidence ≥ 1`, `PositionList ≤ 60`), the `PromptSpec`s and `TARGET_STATEMENT_COUNT = 30` (in the `generate_statements` system text and in `{count}`).
- `src/ideology_app/pipeline/generation.py`: `reduce_request(candidates)` and `generate_statements(provider, chunks, usage)`. It depends only on `llm.base` and `prompts`.
- `src/ideology_app/pipeline/positions.py`: `findings_request(statements, chunk)` and `positions_request(statements, candidates)`. `_check_statement` and the evidence check raise `GenerationError` after the call. The candidates are listed as `C1..CK`, and `evidence` is the 1-based index into that list.
- `src/ideology_app/pipeline/runs.py`: `execute_run` resolves `validation_settings` (env through `config.validation_settings()` when `None`) before any LLM call and passes it to `validate_run`. The CLI (`cli.py:754`, `:799`) reads the settings and passes them explicitly.
- `src/ideology_app/pipeline/checkpoint.py`: `request_hash` covers provider, model, task, system, prompt, `schema.model_json_schema()` and `max_tokens`, but not the prompt version. `_reuse` re-validates the stored output against the request schema.
- `src/ideology_app/config.py`: `ValidationSettings` and `DEFAULT_MIN_STATEMENTS` / `DEFAULT_MAX_STATEMENTS`. `validation/statement_count.py`.
- `src/ideology_app/llm/{base,fake,anthropic_provider,claude_code_provider}.py`: Fake validates with `request.schema`. Anthropic uses `messages.parse(output_format=request.schema)`. Claude Code uses `--json-schema json.dumps(schema.model_json_schema())` and then `model_validate`.
- `tests/test_pipeline_prompts.py` (`FINGERPRINTS`, constant assertions), `tests/pipeline_fixtures.py`, `tests/test_pipeline_{generation,positions,runs,checkpoint}.py`, `tests/test_validation_runs.py`, `tests/test_publishing.py`, `tests/test_cli_pipeline*.py`, `tests/test_cli_live_mode.py`, `tests/test_public_api.py`, `tests/test_llm_{anthropic,claude_code}.py`.
- `ARCHITECTURE.md`, `CONSTRAINTS.md` (prompt bump rule; checkpoint reuse rule; methodology page rule), `docs/risks-and-open-questions.md`.
- `git show 99db057` (teammate, deleted branch). Reference only: it hard-coded the defaults into `StatementSet` (so env overrides are ignored) and did not bound `party_positions`. This spec replaces it.
- Experiment (throwaway `uv run --no-project --with pydantic`, scratchpad): `create_model(name, __base__=Base, __doc__=Base.__doc__, field=(…, Field(ge=1, le=n)))` gives a schema with `"maximum": n` and the same title and description as the base, and the same JSON for the same `n` in every process.

### Existing Patterns To Follow

- Requests are built by small `*_request` functions. Settings are resolved once in `execute_run` and passed down. `pipeline` imports only `llm.base` for LLM types. `config` is a leaf, already imported by `llm.base`.
- To bump a prompt: change its `version` and replace its `FINGERPRINTS` entry.

### Current Gaps

- Schemas are static class attributes of `PromptSpec`. Nothing builds a schema per request.

## Technical Approach

1. **Schema builders in `prompts.py`.** The builders are cached with `functools.cache`. Each argument must be an `int` ≥ 1, else `ValueError`. Each builder returns a `create_model` subclass with the **same class name and docstring** as its base, so the error messages (`does not match FindingList`) and the schema titles stay the same:
   - `statement_set_schema(min_statements, max_statements) -> type[StatementSet]`: `statements: list[StatementDraft] = Field(min_length=min_statements, max_length=max_statements)`.
   - `finding_list_schema(statement_count) -> type[FindingList]`: a `Finding` subclass with `statement: int = Field(ge=1, le=statement_count)`, and `findings: list[<that>] = Field(max_length=60)`.
   - `position_list_schema(statement_count, candidate_count) -> type[PositionList]`: a `PositionChoice` subclass with `statement: Field(ge=1, le=statement_count)` and `evidence: Field(ge=1, le=candidate_count)`, and `positions: list[<that>] = Field(max_length=statement_count)`. One choice per Statement at most; repeats stay a `GenerationError`.

   The static `StatementSet`, `FindingList` and `PositionList` stay unchanged as base types and as `PromptSpec.schema`. Their docstrings and ARCHITECTURE must say that requests always use the builders. Expected JSON for N=30, K=10: `Finding.statement` = `{"maximum": 30, "minimum": 1, "title": "Statement", "type": "integer"}`; `PositionChoice.evidence` has `"maximum": 10`; `positions` has `"maxItems": 30`; `statements` has `"minItems": 25, "maxItems": 35`.
2. **Where the bounds come from.** `generate_statements(provider, chunks, usage, settings: ValidationSettings | None = None)` and `reduce_request(candidates, settings=None)`. `None` means `ValidationSettings()`, i.e. the `config` defaults. The pure layer never reads env. `execute_run` passes **its resolved `validation_settings` object**, the same one it later gives `validate_run`. So the env (through the CLI or `execute_run(None)`) drives both, and no second copy of 25/35 exists. No provider branching: the bound goes into `LLMRequest.schema`, which every provider already uses.
3. **`generate_statements` prompt (v2).** The template becomes `"…Elabora la lista final de {count} afirmaciones del cuestionario (como mínimo {min_count} y como máximo {max_count}), en el orden en que deben presentarse."` with `count = min(max(TARGET_STATEMENT_COUNT, min), max)`. The system line `- Unas {TARGET_STATEMENT_COUNT} afirmaciones en total.` is removed, so it cannot contradict a configured range. With the defaults the prompt still asks for 30, so the methodology page ("unas 30", "entre 25 y 35") stays true.
4. **Position requests (v2 each).** `findings_request(statements, chunk, statement_count)` and `positions_request(statements, candidates, statement_count)` set `schema=` to the builders' output (`candidate_count = len(candidates)`). The prompt texts do not change: they already say "`statement` es el número de la afirmación entre corchetes" and "cita solo números de la lista". Remove the now-unreachable range checks in `positions.py` (`_check_statement` for findings and choices, and the evidence-range check). Keep the repeat check. Update the docstrings and ARCHITECTURE: those `GenerationError` messages are gone.
5. **Versions.** `PROMPT_VERSIONS` becomes `statement_candidates: v1`, `generate_statements: v2`, `position_findings: v2`, `party_positions: v2`. The fingerprint test pins each spec with a reference schema: `CandidateList` for `statement_candidates` (whose fingerprint must stay `a2073f8c…1177`), `statement_set_schema(25, 35)`, `finding_list_schema(30)` and `position_list_schema(30, 10)`. A builder change then also fails the pin.
6. **Checkpoint interaction.** The version string is not part of `request_hash`; schema or prompt changes are what change it.
   - `statement_candidates`: the request is byte-identical, so the same hash. On the same bundle, provider and model, all recorded calls (the 79 of the stopped e2e run) are reused.
   - `generate_statements`: misses, because the schema and the template changed. One new call.
   - `position_findings` / `party_positions`: miss, because the schema embeds N (and K). They also depend on the new Statements.
   - Between two runs on this code with the same settings, everything is reusable: N and K are deterministic. If `VALIDATION_MIN/MAX_STATEMENTS` changes between stop and resume, `generate_statements` misses. The position calls are then reused only if the new Statement list is identical, which is unlikely with a real model.

## Expected File Changes

- `src/ideology_app/pipeline/prompts.py` (modify): the builders, versions and template/system text described above.
- `src/ideology_app/pipeline/generation.py` (modify): the `settings` parameter; the docstring notes `config.ValidationSettings`.
- `src/ideology_app/pipeline/positions.py` (modify): request signatures, bounded schemas, range checks removed.
- `src/ideology_app/pipeline/runs.py` (modify): `generate_statements(..., settings=validation_settings)`; docstring.
- `src/ideology_app/pipeline/__init__.py` (modify): export the three builders.
- Tests (modify or add, see Verification): `test_pipeline_prompts.py`, `test_pipeline_generation.py`, `test_pipeline_positions.py`, `test_pipeline_runs.py`, `test_pipeline_checkpoint.py`, `test_llm_claude_code.py`, `test_llm_anthropic.py`. Also adapt the tests that use `statements_payload(20)` to reach Validation: `test_publishing.py` (`failing_provider`), `test_validation_runs.py` (~468, 785, 844, 857), `test_cli_pipeline.py` (~904, 932, 1017), `test_cli_pipeline_report.py` (~310, 430, 567), `test_cli_live_mode.py` (~381) and `test_public_api.py` (~522, 557). For each one:
  - if it needs *a Validation failure*, use a failure the schema still allows (`statements_payload(duplicate=(2, 5))` or `topic=("economy", 15)`) and update the expected strings;
  - if it needs *a `statement_count` failure*, generate with a wider range (validate_run patched, as the existing `validating_run` helpers do, with `ValidationSettings(min_statements=20)` or the env during generation), then validate with the defaults;
  - if it needs *a passing 20-Statement run*, it already passes `min_statements=20` and works unchanged.

  Do not delete a test without a replacement.

## Visual Design Impact

- UI involved: no. Pipeline only. **Browser validation does not apply** (AGENTS.md exempts CLI/pipeline features).

## Durable Documentation Impact

- `ARCHITECTURE.md` (update): the `prompts.py` line (builders, versions v1/v2/v2/v2, template fields `{count}`, `{min_count}`, `{max_count}`); the `generation.py` and `positions.py` lines (signatures, removed `GenerationError` messages, schema-enforced bounds); the `runs.py` line (settings passed to generation).
- `CONSTRAINTS.md` (update, LLM section): add "The `generate_statements` request schema MUST take its Statement-count bounds from the same `ValidationSettings` object that the run's Validation uses (never a second copy). Every Statement or candidate number that an LLM output schema accepts MUST be bounded to the numbers listed in that request." Reason: such output fails at the call, not hours later or silently.
- `AGENTS.md`: not needed (no workflow change).
- `apps/web/src/features/methodology/MethodologyPage.tsx`: not needed. No Validation check, `ValidationSettings` default or described prompt rule changes, and "unas 30" is still the default request.
- `docs/risks-and-open-questions.md` (update):
  - In the "Settled: the prompts and chunking…" entry, replace "All prompts `v1`" with "`statement_candidates` v1; the other three v2 (`pipeline-output-bounds`)".
  - In "Real-LLM behaviour unverified", rewrite the structured-output paragraph. With `anthropic`, the SDK sends `minimum`, `maximum`, `maxItems` and a `minItems` above 1 only as description hints and validates on the client, so an out-of-range answer fails the call (no retry) and the run (resumable). `claude_code` validates against the full schema and retries up to 5 times. Keep this open for `e2e-real-2023-election`: how often a real model breaks the bounds.
  - Update "Questionnaire shape vs real output": the count is now bounded at the `generate_statements` call (since `pipeline-output-bounds`), so out-of-range counts fail at generation, not at Validation. Duplicates and topic share are still checked only at Validation.

## Implementation Plan

1. Before changing code, compute and record `request_hash("fake", "fake-model", candidate_request("[página 1]\nTexto"))` on the base commit, to pin later.
2. Add the builders and the version, text and template changes in `prompts.py`. Update the fingerprints.
3. Wire `settings` through `reduce_request` / `generate_statements` / `execute_run`.
4. Bound the position requests and remove the unreachable checks.
5. Update and add tests, then the existing 20-Statement tests. Run the full gate.
6. Update ARCHITECTURE, CONSTRAINTS and risks. Record evidence.

## Implementation Tasks

- [ ] Builders with the same names and docstrings as their bases, cached, with argument checks.
- [ ] `generate_statements` v2 (template range, system count line removed); `position_findings` v2; `party_positions` v2; `statement_candidates` untouched.
- [ ] `settings` parameter in generation; `execute_run` passes its resolved settings.
- [ ] `findings_request` / `positions_request` take `statement_count`; the range checks are removed; the repeat check stays.
- [ ] Tests listed below; existing tests adapted; `FINGERPRINTS` and `PROMPT_VERSIONS` assertions updated.
- [ ] Docs updates as listed.

## Verification Plan

New or changed tests (FakeProvider, injected runners or MockTransport only; keep the `offline_guard` / autouse guards). Each test below fails on the current code:

- `test_pipeline_prompts.py`:
  - builders: in-range values pass; out-of-range values raise (`StatementSet` 24/36 vs 25/35; `statement` 0/N+1; `evidence` K+1; `positions` N+1 items);
  - JSON schema keys: `minItems`, `maxItems`, `maximum`;
  - the same name and title as the base; cached identity;
  - `ValueError` for 0 and for min > max;
  - `PROMPT_VERSIONS` v1/v2/v2/v2; the `statement_candidates` fingerprint is unchanged;
  - the pinned `candidate_request` hash from step 1 is unchanged.
- `test_pipeline_generation.py`:
  - 38 and 44 Statements raise `LLMOutputError` with the defaults;
  - `settings=ValidationSettings(min_statements=36, max_statements=40)` accepts 38;
  - the request schema and prompt carry the range, and `{count}` is clamped (e.g. 10..20 gives 20).
- `test_pipeline_positions.py`:
  - a finding with statement 101, N+1 or 0 raises `LLMOutputError`; a choice with statement N+1, evidence K+1, or N+1 entries raises `LLMOutputError`; repeats raise `GenerationError`;
  - the findings and positions request schemas show `maximum` N and K.
- `test_pipeline_runs.py`:
  - the invalid-reference cases now give `LLMOutputError` reasons; `llm_calls` drops by one because a failed call is not counted (e.g. 4→3, 5→4);
  - a 44-Statement run ends `failed` before any position call;
  - env `VALIDATION_MAX_STATEMENTS=40` with 38 Statements passes through `execute_run(…, None)`.
- `test_pipeline_checkpoint.py`: Scenario 7, both halves (count `reused` rows per task).
- `test_llm_claude_code.py`: `build_argv` with a `findings_request` / `positions_request` / `reduce_request` puts the bounds in `--json-schema`.
- `test_llm_anthropic.py`:
  - a bounded request: the sent `output_config.format.schema` carries the bound as a description hint;
  - an out-of-range answer (`statement: 101`) raises `LLMOutputError`.
- Gate: `CI=true ./init.sh` (pytest plus the web steps). All tests pass, and no test calls a real LLM, opens a socket or spawns `claude`.

## Evidence To Capture

- In `feature_list.json` → `pipeline-output-bounds.evidence` and `PROGRESS.md`:
  - the `CI=true ./init.sh` counts;
  - the names of the new tests;
  - the unchanged `statement_candidates` fingerprint and pinned hash;
  - the new `PROMPT_VERSIONS`;
  - the note "no browser check needed, pipeline feature".

## Validator Checklist

- [ ] The bounds come only from `ValidationSettings` (no literal 25/35 in `prompts.py` or `generation.py`; the static base `StatementSet` keeps 1..60 only as a type and is never sent), and `execute_run` passes the same object to generation and Validation.
- [ ] An env override changes the schema (Scenario 2).
- [ ] The finding and choice `statement` bounds are 1..N, `evidence` is 1..K and `positions` is at most N. Out-of-range output fails with `LLMOutputError` for Fake, Claude Code (argv carries the bounds) and Anthropic (MockTransport).
- [ ] `statement_candidates` is byte-identical (fingerprint and pinned hash unchanged); only the other three tasks are v2.
- [ ] The checkpoint scenarios pass; recorded calls are never edited.
- [ ] No Validation, UI or methodology changes; ARCHITECTURE, CONSTRAINTS and risks are updated as listed.
- [ ] No adapted test lost its intent; `feature_list.json` and `PROGRESS.md` are updated; no `docs/validations/`.
