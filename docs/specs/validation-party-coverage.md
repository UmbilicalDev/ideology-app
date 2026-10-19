# Feature Implementation Spec: Validation enforces minimum Party coverage

## Source Feature

- `id`: validation-party-coverage
- `area`: validation
- `depends_on`: pipeline-extract-positions (`accepted`). It also builds on `validation-evidence-quotes` (`accepted`), which provides the framework.
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (notes: check 3 in `docs/domain-model.md`; "Initial position: fail the whole run")

## Goal

Add Validation check 3, `party_coverage`, to the existing framework (`CHECKS`, `validate_run`, `validation_results`, `pipeline checks`). A Party is covered on a Statement when its Party Position there is not `no stance`. The check fails when any Party of the Election is covered on less than the configured share of the run's Statements. The default share is 70%, and `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` changes it. Each offending Party gets one report entry that states its coverage. A failing check fails the whole run. Parties are never excluded, and the Dataset Version stays `candidate`.

The only framework extension is a small `ValidationSettings` value. `config` reads it, it travels in `ValidationInput.settings`, and it is passed explicitly through `execute_run` / `validate_run`. Later threshold checks (`validation-questionnaire-shape`) add their fields to it.

## Non-Goals

- No Party exclusion, no "publish with a notice", no change to Dataset Version status (publishing belongs to `auto-publish-dataset-version`).
- No per-Election threshold override (mentioned in `docs/technical-discovery.md`). The threshold is one value for the whole process. The override is deferred and recorded in the risks doc.
- No new table, column or migration. The threshold is not stored on the run; see the risks doc entry for `pipeline-run-report`.
- No other checks (separation, count, uniqueness, topic spread). No prompt changes. No HTTP endpoint or UI. No change to `init.sh`. No new dependency.

## Job Story

When a Pipeline Run has produced a candidate Dataset Version,
I want the run to fail if any Party took a position on too few Statements,
so that Voters never get a Questionnaire where a Party's Match Score rests on a handful of Statements, and I can see which Party fell short and by how much.

## Users And Permissions

- Operator: CLI only. Sets the threshold through the environment and reads the report with `pipeline checks`. Cannot override a result.
- Voter: not affected (nothing is published yet).

## Settled Decision: fail the run

A Party below the threshold fails the whole run: `failed`, `validation failed: party_coverage`. The run never excludes the Party, and nothing is published with a notice. Reasons:
- excluding a Party silently changes the Voter's ballot;
- the UI must treat all Parties identically;
- AI output is never edited, so a run cannot be patched;
- the run is the unit of publication.

The Operator's remedies are to add or fix the Source Document and re-run, or to change the threshold deliberately. `docs/risks-and-open-questions.md` and `docs/domain-model.md` are updated in the same change (see Durable Documentation Impact).

## Acceptance Scenarios

Every test uses a temporary SQLite database, `FakeProvider` or plain `ValidationInput` data, and the autouse env/socket guard. No API key and no network.

### Scenario 1: Boundary at the default threshold

Given plain data with 10 Statements, Parties 1 and 2 and default settings, where Party 1 has stances on 7 Statements and Party 2 on 6
When `PARTY_COVERAGE.run(data)` runs
Then it returns exactly one entry: `party_id=2`, `statement_id=None`, message `party 2 has positions on 6 of 10 statements (60%); minimum is 70%`. Party 1 (exactly 70%) has no entry.
The same holds at 30 Statements: 21 passes; 20 (66%) and 18 (60%) fail.

### Scenario 2: Threshold is configurable

Given the 30-Statement data where a Party has 18 stances
When settings are `ValidationSettings(min_party_coverage_percent=60)`, it passes. At `100`, a Party with 29 of 30 fails with `(96%); minimum is 100%`. At `0`, a Party with 0 stances passes.
And `config.validation_settings()` works as follows:
- unset or blank → 70;
- `" 55 "` → 55;
- `"0"` and `"100"` are accepted;
- `"0.7"`, `"70%"`, `"-1"`, `"101"` and `"abc"` raise `ConfigError` with the message `Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT '<raw>'; expected an integer from 0 to 100`.

### Scenario 3: Edge cases

- A Party of the Election with no Party Position rows at all, or only `no stance` rows, has 0 coverage. It fails with `party P has positions on 0 of N statements (0%); minimum is T%`.
- Several offending Parties give one entry each, in Party id order.
- Positions of a Party id not in `party_ids` are ignored.
- Zero Statements: the check returns no entries. Coverage is undefined, and the Statement count belongs to `validation-questionnaire-shape`.
- An Election with zero Parties: no entries.

### Scenario 4: Run level (through `execute_run` / `validate_run`)

- Given `seed_election` and the default fake, which now gives every Party a stance on every Statement (see Technical Approach), `execute_run` ends `passed`. `validation_results` holds `evidence_quotes` and `party_coverage`, in that order, both `passed=true`.
- Given Party 2 with no parsed document, or with no findings (the existing `test_party_without_*` tests), the run ends `failed` with `failure_reason == "validation failed: party_coverage"`. It has one entry, `party_id=2`, with a message naming `0 of 30 statements (0%)`. The Dataset Version and all 60 Party Positions still exist, unchanged and `candidate`.
- When both checks fail, `failure_reason == "validation failed: evidence_quotes, party_coverage"`.
- `validate_run(engine, run_id, settings=ValidationSettings(0))` on that run passes. With `settings=None`, `validate_run` reads `config.validation_settings()` before opening a session. An invalid env value raises `ConfigError`, and the run stays `validating` and unchanged.

### Scenario 5: CLI

- `pipeline checks --run N` of a passing run prints two rows: `evidence_quotes passed` and `party_coverage passed`. For a failing run it prints `party_coverage\tfailed\t\t2\tparty 2 has positions on 0 of 30 statements (0%); minimum is 70%`, with an empty statement cell.
- `pipeline run` reads the threshold together with `GENERATION_MODE` and the provider, before any write. An invalid `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` exits 1 with `Error: Invalid VALIDATION_MIN_PARTY_COVERAGE_PERCENT ...` and creates no run row. A coverage failure prints `Error: pipeline run N failed: validation failed: party_coverage; see "ideology pipeline checks --run N"` and exits 1.
- `pipeline validate --run N` reads the threshold first. An invalid value exits 1 and leaves the run `validating`. It still needs no LLM provider or key.

## Repository Research

### Files Inspected

- `src/ideology_app/validation/__init__.py`, `base.py`: `CHECKS = (EVIDENCE_QUOTES,)`, `run_checks`, `ValidationInput(statements, positions, party_ids, documents)`, `load_input(session, run)`. The docstring already anticipates "a configured threshold adds a field here".
- `src/ideology_app/validation/evidence_quotes.py`: the pattern for a check module that exports a `Check`.
- `src/ideology_app/pipeline/runs.py`: `validate_run(engine, run_id, checks=CHECKS)` (one commit, error handling, `RunOutcome.failed_checks`), and `execute_run` calling `validate_run(engine, run_id)` outside its `try`. `party_ids` are the Election's Parties. Every Party gets n rows, with `no stance` when it has no findings or documents.
- `src/ideology_app/config.py`: `_env` (trimmed, blank = unset), `ConfigError`, `generation_mode()` / `llm_settings()` patterns.
- `src/ideology_app/cli.py`: `pipeline run` resolves config in a `try … except config.ConfigError`. `pipeline validate` calls `validate_run` directly. `pipeline checks` prints an empty statement cell when `entry.statement` is None.
- `tests/pipeline_fixtures.py`: `LLM_ENV_VARS`, `offline_guard`, and `default_responses()`. **The default `findings_response` / `positions_response` give each Party stances on only Statements 1–2 of 30 (about 7%)**, so every default run would fail at 70%.
- `tests/test_pipeline_runs.py` (`test_party_without_findings_*`, `test_party_without_documents_*`, which assert `PASSED`), `tests/test_validation_runs.py`, `tests/test_cli_pipeline.py` (which assert a single `evidence_quotes passed` row and `no_stance` rows for Statement 3).
- `ARCHITECTURE.md` (Validation, Data Layer, Runtime Surface), `CONSTRAINTS.md` (Validation), `docs/domain-model.md` (check 3, edge cases line "A party with no manifesto…"), `docs/risks-and-open-questions.md`, `docs/technical-discovery.md` (thresholds row), `PROGRESS.md`, `feature_list.json`, `docs/specs/validation-evidence-quotes.md`.

### Existing Patterns To Follow

- Config readers live in `config.py`, use `_env`, and raise `ConfigError` with the supported values. The CLI resolves config before any write.
- Checks are pure and are unit-tested on plain `ValidationInput`. Each entry carries `party_id`, and `statement_id` when relevant.

### Current Gaps

- `ValidationInput` has no settings, and `load_input` takes none.
- The default test fake is not a realistic, coverage-passing run.

## Technical Approach

**Config (`config.py`):**
- `DEFAULT_MIN_PARTY_COVERAGE_PERCENT = 70`.
- `@dataclass(frozen=True) class ValidationSettings: min_party_coverage_percent: int = DEFAULT_MIN_PARTY_COVERAGE_PERCENT`.
- `validation_settings() -> ValidationSettings` reads `VALIDATION_MIN_PARTY_COVERAGE_PERCENT` through `_env`. It accepts only values where `raw.isascii() and raw.isdigit()`, in 0..100, else `ConfigError` (Scenario 2 message).
- `ValidationSettings.__post_init__` also rejects values outside 0..100, or values that are not `int` (but `bool` is rejected), with `ValueError`.

**Framework extension (smallest):**
- `ValidationInput` gains `settings: ValidationSettings = ValidationSettings()` as its last field, so existing plain-data tests keep working.
- `load_input(session, run, settings)` fills it.
- `validate_run(engine, run_id, checks=CHECKS, settings: ValidationSettings | None = None)` resolves `config.validation_settings()` when `settings is None`, first, outside the try and before any session. A `ConfigError` therefore changes nothing.
- `execute_run(engine, run_id, provider, validation_settings: ValidationSettings | None = None)` passes the settings to `validate_run`.
- Export `ValidationSettings` from `validation/__init__.py` (re-export from `config`).
- Dependency direction stays `config` → `validation`.

**Check `party_coverage` (`validation/party_coverage.py`):**
- `PARTY_COVERAGE = Check("party_coverage", _run)`.
- `total = len(data.statements)`. If `total == 0`, return `[]`.
- Count stances (`value is not None`) per `party_id`, counting only ids in `data.party_ids`.
- For each `party_id` in `data.party_ids` order, the Party fails when `covered * 100 < percent * total`. Use integer arithmetic, with no floats.
- The message is `party {id} has positions on {covered} of {total} statements ({covered * 100 // total}%); minimum is {percent}%`. Floor division means the shown percent is always below the minimum for a failing Party.
- Each entry is `ReportEntry(message, party_id=id)`.
- `CHECKS = (EVIDENCE_QUOTES, PARTY_COVERAGE)`. Registry order follows domain check order.

**CLI:**
- `pipeline run` adds `settings = config.validation_settings()` inside the existing `ConfigError` try and passes it to `execute_run`.
- `pipeline validate` resolves it the same way, raising `ClickException` on `ConfigError`, before calling `validate_run`.
- `pipeline checks` needs no change.

**Test fake (`tests/pipeline_fixtures.py`):**
- Make the default run realistic. `positions_response()` gets a `fill: bool` parameter, and `default_responses()` uses `fill=True`. With `fill=True`, every Statement number listed in the reduce prompt (`[n]` lines under "Afirmaciones del cuestionario") gets a stance. A Statement uses its own first candidate when it has one, otherwise the Party's first candidate.
- The quotes remain real page text on the cited page, so `evidence_quotes` still passes. Findings and call counts are unchanged.
- `offline_guard` also unsets `VALIDATION_MIN_PARTY_COVERAGE_PERCENT`, through a new `CONFIG_ENV_VARS` tuple or by extending the existing one.
- Existing tests keep their intent. A test that asserts the sparse shape uses `positions_response()` (no fill) explicitly, and either expects `failed` / `party_coverage` or passes `ValidationSettings(0)`. The `test_party_without_*` tests now expect `FAILED` with `validation failed: party_coverage`. That is the settled behaviour for a Party with no manifesto.

## Expected File Changes

- `src/ideology_app/config.py`: modify (`ValidationSettings`, default, `validation_settings()`).
- `src/ideology_app/validation/party_coverage.py`: create.
- `src/ideology_app/validation/base.py`, `__init__.py`: modify (the settings field, the `load_input` parameter, the registry, exports).
- `src/ideology_app/pipeline/runs.py`: modify (the `settings` / `validation_settings` parameters, docstrings).
- `src/ideology_app/cli.py`: modify (resolve settings in `pipeline run` / `pipeline validate`).
- `tests/test_validation_party_coverage.py`: create (Scenarios 1–3, on plain data and config).
- `tests/pipeline_fixtures.py`: modify (fill mode, env guard).
- `tests/test_validation_runs.py`, `tests/test_pipeline_runs.py`, `tests/test_cli_pipeline.py`: modify (Scenarios 4–5 and updated expectations).
- `tests/test_llm.py`: modify only if config tests live there. Otherwise keep the config tests in the new module.
- No migration. Docs: see below.

## Visual Design Impact

- UI involved: no. This is a CLI and pipeline change only, so browser validation is exempt (AGENTS.md).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Validation section: add `party_coverage` (rule, integer comparison, message, zero-Statements behaviour). Update `CHECKS`. Document `ValidationSettings` / `ValidationInput.settings` / `load_input(session, run, settings)` / the `validate_run` and `execute_run` settings parameters as the way checks get thresholds. Revise "Storage, CLI and the run transition need no change" so it says a new threshold adds a `ValidationSettings` field plus its env reader.
  - LLM Providers / configuration bullet: add `VALIDATION_MIN_PARTY_COVERAGE_PERCENT`.
  - Runtime Surface: `pipeline run` / `validate` resolve it before any write.
- `CONSTRAINTS.md`: update the Validation section. Validation thresholds MUST come from `config.ValidationSettings` (env), never from literals inside checks. A Party below coverage MUST fail the run and MUST NOT be excluded from a Dataset Version.
- `docs/domain-model.md`:
  - Check 3 becomes "Each Party has positions (not `no stance`) on at least the configured share of Statements (default 70%); otherwise the whole run fails."
  - The edge case "A party with no manifesto…" becomes "→ 0% coverage → Validation fails the run (Parties are never excluded)."
- `docs/risks-and-open-questions.md`: update in the same change.
  - Delete the open question "What happens when a Party fails coverage…", or replace it with a short "Settled (`validation-party-coverage`): fail the whole run; Parties are never excluded."
  - Add an Implementation-Time Question: per-Election threshold overrides (from `technical-discovery.md`) are not built; the threshold is process-wide.
  - Add a Risk under the real-run entries (`e2e-real-2023-election`): small Parties may fall below 70% on real manifestos and block publishing for everyone. The mitigation is a deliberate threshold change or better sources, never editing output.
  - Add an Accepted Low: the threshold used is not stored, so a passed run's report doesn't show it (`pipeline-run-report`).
- `docs/technical-discovery.md`: not needed (the row already says coverage % is configurable).
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`: not needed.

## Implementation Plan

1. Add `ValidationSettings` and `validation_settings()` with config tests.
2. Add `party_coverage.py` and the `ValidationInput.settings` field. Unit-test Scenarios 1–3 on plain data.
3. Thread settings through `load_input`, `validate_run`, `execute_run` and the CLI. Register the check.
4. Update the fixture fake (fill mode, env guard). Fix the existing run and CLI tests without weakening their intent. Add Scenarios 4–5.
5. Update the docs, run `CI=true ./init.sh`, and record evidence.

## Implementation Tasks

- [ ] `config.ValidationSettings`, `DEFAULT_MIN_PARTY_COVERAGE_PERCENT`, `validation_settings()`.
- [ ] `validation/party_coverage.py` with the exact message, plus registry and exports.
- [ ] `ValidationInput.settings`, `load_input(..., settings)`, and the `validate_run` / `execute_run` parameters.
- [ ] CLI resolution in `pipeline run` and `pipeline validate`.
- [ ] Fixture `fill` mode and env guard. Updated expectations in `test_pipeline_runs.py`, `test_validation_runs.py` and `test_cli_pipeline.py`.
- [ ] `tests/test_validation_party_coverage.py` (boundaries 7/10, 6/10, 21/30, 20/30, 18/30; thresholds 0/60/100; zero Statements; zero Parties; Party without rows; ordering; foreign party ids).
- [ ] Docs as listed.

## Verification Plan

- `CI=true ./init.sh` exits 0, with pytest and node passing and no warnings.
- Run `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest tests/test_validation_party_coverage.py tests/test_validation_runs.py tests/test_pipeline_runs.py tests/test_cli_pipeline.py -q`; it passes.
- `alembic history` still shows `0006 (head)`, and `alembic check` reports no drift (no schema change).
- `grep -n "import" src/ideology_app/validation/party_coverage.py` shows no `pipeline`, `llm` or `os` imports, and the check has no literal `70`.
- Run an offline CLI smoke in a scratch directory outside the repo, with `cli._provider` patched to the fixture fake:
  - a default run passes, and `checks` shows two `passed` rows;
  - a run whose Party 2 document is `failed` fails with `party_coverage`, and `checks` shows the 0% row;
  - `VALIDATION_MIN_PARTY_COVERAGE_PERCENT=abc ideology pipeline run` exits 1 with no new run row;
  - on a run seeded as `validating`, `VALIDATION_MIN_PARTY_COVERAGE_PERCENT=0 ideology pipeline validate` passes.
- No E2E harness exists. Browser validation is exempt.

## Evidence To Capture

- In `feature_list.json` → `validation-party-coverage.evidence` and a `PROGRESS.md` session:
  - test counts;
  - the tests mapped to Scenarios 1–5, with explicit 70%-pass / 60%-fail / configured-threshold tests;
  - the alembic no-drift output;
  - the smoke results;
  - the "browser validation exempt" note;
  - any deviations.

## Open Questions (non-blocking)

- If `validation-questionnaire-shape` or `validation-statement-separation` is built in parallel, the branch that merges second rebases onto `ValidationSettings`. It adds its fields there and appends its check to `CHECKS`, and it does not add a parallel config path.

## Validator Checklist

- [ ] Scope: no exclusion, no publishing, no migration, no other checks, no prompt changes, no new dependency.
- [ ] 70% exactly passes, 60% fails, and the threshold is configurable via env and `ValidationSettings`. Invalid values are rejected before any write.
- [ ] The report names each offending Party with `C of N statements (P%)` and the minimum.
- [ ] The default fake run passes both checks, and existing tests keep their intent.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/domain-model.md` and `docs/risks-and-open-questions.md` were edited as listed, and the coverage open question is settled.
- [ ] `feature_list.json` and `PROGRESS.md` hold the evidence. No `docs/validations/` directory exists. `FakeProvider` only, with no key and no network.
