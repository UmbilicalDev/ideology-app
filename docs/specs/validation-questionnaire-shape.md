# Feature Implementation Spec: Validation checks Statement count, uniqueness and topic spread

## Source Feature

- `id`: validation-questionnaire-shape (GitHub issue #21)
- `area`: validation
- `depends_on`: pipeline-generate-statements (`accepted`). Builds on the framework from `validation-evidence-quotes`, `validation-party-coverage` and `validation-statement-separation` (all `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (notes: "Checks 1, 5 and 6. Detecting compound propositions can be heuristic.")

## Goal

Add domain Validation checks 1 (uniqueness part), 5 and 6 through the existing plug-in path. There are three new `Check`s, each in its own module, and each is appended to `CHECKS`:

- `statement_uniqueness`: no two Statements have the same normalised text.
- `statement_count`: the number of Statements is within a configured range (default 25–35).
- `topic_spread`: no single topic has more than a configured share of the Statements (default 30%).

If any of them fails, the whole run fails (`validation failed: ...`). The Dataset Version stays `candidate`, and no Statement is dropped, merged or rewritten. Thresholds are new `config.ValidationSettings` fields, read from the environment by `config.validation_settings()`, following the `party_coverage` pattern. There is no migration, no new table, no `ValidationInput` field, no CLI command change and no new dependency.

## Decisions

- **Three registry entries, not one.** Each rule is a separate domain check with its own threshold. Separate entries mean `failure_reason` names exactly what failed (`validation failed: statement_count`), and `pipeline checks` shows one row per rule. It also follows the documented "one module exports one `Check`" pattern, with no sub-results and no framework change.
- **Registry order.** The new checks are appended after the existing three, in domain order: `CHECKS = (EVIDENCE_QUOTES, PARTY_COVERAGE, STATEMENT_SEPARATION, STATEMENT_UNIQUENESS, STATEMENT_COUNT, TOPIC_SPREAD)`. Appending keeps the existing rows and `failure_reason` strings stable. Change the registry comment to say that registry order is run order, and that checks are appended as they are added (it currently says "domain check order").
- **Duplicate = same text after `normalize_for_match`.** This is the existing Validation normaliser in `validation/evidence_quotes.py`: NFKD, `casefold()`, NFKD, then keep only `isalnum()` characters that are not combining marks. So case, accents, ligatures, whitespace and punctuation are ignored, and word order and every letter and digit still count. Exact duplicates are a subset of this. Topic is ignored, so the same text under two topics is still a duplicate. The normaliser is reused (imported from `validation.evidence_quotes`), so the repo has one normalisation rule. Accepted corner case: dropping separators can merge different tokens (`"2,1 %"` and `"21 %"`), and a Statement with no letters or digits normalises to `""`. Both can only cause a false *failure*, never a false pass, so they are acceptable. Near-duplicates (paraphrases) are **not** detected.
- **Default topic share 30%, and a topic fails only when it is strictly above it** (`count * 100 > percent * total`). The reduce prompt asks for "no topic above approximately a quarter". 30% leaves room for "approximately" (8 of 30 = 26.7% passes) and still catches clear skew (10 of 30 = 33% fails; 50% fails).
- **The "single proposition" (no compound "y/o") half of check 1 is deferred.** A lexical heuristic on "y"/"o" would flag many legitimate Spanish Statements ("investigación y desarrollo") and fail whole runs, while missing real compounds. For now only the prompt asks for single propositions (both prompts already say so). Revisit with real-LLM output in `e2e-real-2023-election`. The deferral is recorded in the risks doc and in `docs/domain-model.md` (see Durable Documentation Impact).

## Non-Goals

- No compound-proposition detection, no semantic or fuzzy near-duplicate detection, no topic-coverage minimum (for example "at least K topics").
- No dropping, deduplicating or reordering of Statements, and no Dataset Version status change.
- No prompt change. `TARGET_STATEMENT_COUNT`, the `StatementSet` schema (1..60) and prompt versions stay as they are.
- No per-Election thresholds, no storing of thresholds on the run, no migration, no HTTP or UI, no `init.sh` change, no new dependency.
- No coupling between checks: none of the three reads another check's result. `party_coverage` and `statement_separation` keep returning `[]` for zero Statements.

## Job Story

When a Pipeline Run has produced a candidate Dataset Version,
I want the run to fail if the Questionnaire is too short or too long, repeats a Statement, or piles too many Statements onto one topic,
so that Voters only ever get a balanced Questionnaire of the intended length, and I can see from the report which rule failed.

## Users And Permissions

- Operator: CLI only. Sets thresholds through the environment and reads the report with `ideology pipeline checks --run N`. Cannot override a result.
- Voter: not affected (nothing is published yet).

## Acceptance Scenarios

All tests use plain `ValidationInput` data or a temporary SQLite database with `FakeProvider` (`tests/pipeline_fixtures.py`), plus the autouse env/socket guard. They need no API key and no network.

### Scenario 1: Statement count (`statement_count`)

Given default settings
- 20 Statements gives exactly one entry, with no `statement_id` and no `party_id`: `questionnaire has 20 statements; expected 25 to 35`.
- 24 and 36 fail. 25, 30 and 35 pass. 0 Statements fails (`questionnaire has 0 statements; expected 25 to 35`). This check owns the zero case.
- With `ValidationSettings(min_statements=10, max_statements=20)`, 20 passes and 21 fails. With `min_statements == max_statements == 30`, only 30 passes.

### Scenario 2: Duplicates (`statement_uniqueness`)

- Statements 2 and 5 have the same text. One entry is returned, with `statement_id` = Statement 5's id: `statement 5 duplicates statement 2`.
- Texts that differ only in case, accents, whitespace or punctuation are duplicates: `"El Estado debe subir el IVA."` and `"el estado debe subir el iva"` and `"El  Estado debe subir el IVA"`.
- Same text with different topics is a duplicate. Texts that differ by one word or one digit are not.
- Three copies (positions 1, 4 and 9) give two entries, for 4 and 9, each naming statement 1. Entries come in Statement order.
- 0 or 1 Statements give no entries.

### Scenario 3: Topic spread (`topic_spread`)

Given default settings (30%)
- 30 Statements with 15 on `economy` (50%) give exactly one entry, with no ids: `topic economy has 15 of 30 statements (50%); maximum is 30%`.
- 9 of 30 (exactly 30%) passes. 10 of 30 fails with `(34%)`. The percent is the ceiling, `-(-count * 100 // total)`, so for a failing topic it is always above the maximum.
- Two offending topics give two entries, in the order each topic first appears in the Statements.
- 0 Statements gives no entries.
- With `max_topic_share_percent=100`, everything on one topic passes. With `0`, every topic present fails.

### Scenario 4: Settings and configuration

- `ValidationSettings()` has `min_statements=25`, `max_statements=35`, `max_topic_share_percent=30` and `min_party_coverage_percent=70`.
- `__post_init__` raises `ValueError` in these cases:
  - `min_statements` or `max_statements` is not an `int`, is a `bool`, or is below 1;
  - `min_statements > max_statements`;
  - `max_topic_share_percent` is outside 0..100 or is not an `int`.
- `config.validation_settings()` reads `VALIDATION_MIN_STATEMENTS`, `VALIDATION_MAX_STATEMENTS` and `VALIDATION_MAX_TOPIC_SHARE_PERCENT` through `_env`:
  - Unset or blank gives the default. `" 28 "` gives 28.
  - Statement counts accept ASCII-digit integers of at least 1. Anything else (`"0"`, `"-1"`, `"2.5"`, `"abc"`) raises `ConfigError("Invalid VALIDATION_MIN_STATEMENTS '<raw>'; expected a positive integer")` (same for MAX).
  - The share accepts 0..100, with the same message shape as the coverage variable: `...; expected an integer from 0 to 100`.
  - A min above the max (including against a default, for example `VALIDATION_MIN_STATEMENTS=40` alone) raises `ConfigError("Invalid statement count range: VALIDATION_MIN_STATEMENTS (40) is greater than VALIDATION_MAX_STATEMENTS (35)")`.
  - Variables are checked in this order: coverage, min, max, range, share. The first error wins.

### Scenario 5: Run level and CLI

- With the default fake (30 Statements, distinct texts, topics `TOPICS[i % 18]`, so at most 2 per topic), `execute_run` ends `passed`. `validation_results` holds six `passed` rows in registry order, and `pipeline checks` prints six `passed` rows.
- The run-level verification uses `fake_provider(generate_statements=...)` with these payloads:
  - 20 Statements ends `failed` with `failure_reason == "validation failed: statement_count"`;
  - 30 Statements with one duplicated text ends `failed` with `"validation failed: statement_uniqueness"`;
  - 30 Statements with 15 on one topic (texts distinct) ends `failed` with `"validation failed: topic_spread"`;
  - a valid set ends `passed`.

  In each failing case the Dataset Version and all its Statements still exist, unchanged and `candidate`.
- The existing `test_statements_are_stored_as_returned_even_if_odd` (3 Statements, two identical) keeps its intent: the Statements are stored as returned. It now expects `FAILED`. The implementer asserts the actual `failure_reason`. Expected: `validation failed: statement_uniqueness, statement_count, topic_spread`, since `economy` has 2 of 3.
- CLI: a failing count prints `Error: pipeline run N failed: validation failed: statement_count; see "ideology pipeline checks --run N"` and exits 1. `pipeline checks` shows the row `statement_count\tfailed\t\t\tquestionnaire has 20 statements; expected 25 to 35`.
- `VALIDATION_MAX_TOPIC_SHARE_PERCENT=abc ideology pipeline run` exits 1 with `Error: Invalid VALIDATION_MAX_TOPIC_SHARE_PERCENT 'abc'; ...` before any write (no run row). `pipeline validate` behaves the same way and leaves the run `validating`. This needs no CLI code change, because both commands already call `config.validation_settings()`.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json`, `CONTEXT.md`, `docs/domain-model.md` (checks 1, 5, 6), `docs/risks-and-open-questions.md`, `ARCHITECTURE.md` (Validation), `CONSTRAINTS.md` (Pipeline, Validation).
- `docs/specs/pipeline-generate-statements.md`, `validation-party-coverage.md`, `validation-statement-separation.md`.
- `src/ideology_app/validation/{__init__,base,evidence_quotes,party_coverage,statement_separation}.py`, `src/ideology_app/config.py` (`ValidationSettings`, `_env`, `validation_settings()`).
- `src/ideology_app/pipeline/{prompts,generation}.py`: `TARGET_STATEMENT_COUNT = 30`; `StatementSet.statements` 1..60; 18 `TOPICS`; the reduce prompt asks for "Unas 30" Statements, "no topic above approximately a quarter" and "no near-duplicates"; `reduce_request` dedupes only exact `(topic, text)` candidates. Final Statements are stored as returned.
- `tests/pipeline_fixtures.py` (`statements_payload`, `default_responses`, `CONFIG_ENV_VARS`, `offline_guard`); `tests/test_pipeline_runs.py:181` (odd-Statements test asserting `PASSED`); `tests/test_cli_pipeline.py:417` (`PASSED_CHECKS`, three rows); `tests/test_validation_runs.py` (result lists ending at `statement_separation`); `tests/test_validation_statement_separation.py:76` (asserts the exact `CHECKS` tuple).

### Interaction With Generation (analysis)

- The **count** is targeted at 30 by the prompt and allowed up to 1..60 by the schema. A 25–35 range is ±5 around the target, so compliant output passes, and a model that ignores the target (for example 12 or 50) fails. The default fake returns exactly 30, so the default run passes and the check does not fail every run. Tests that pass 20 or 36 make it fire.
- The **topic spread** prompt target is about 25%. 30% with a strict `>` comparison accepts small overshoots (8/30), so prompt-compliant runs pass. The default fake spreads 30 Statements over 18 topics (at most 2 each, 6.7%), so it passes. A 15/30 payload makes it fire.
- **Uniqueness**: the fake's texts are numbered and distinct, so the default run passes. The odd-Statements test and the new duplicate payload make it fire. The reduce prompt forbids near-duplicates, but only exact candidate pairs are deduped in code, so exact or case/punctuation duplicates in the final list are possible and are caught.
- Real-LLM behaviour against these defaults is unverified. Record it as a risk for `e2e-real-2023-election` (see Durable Documentation Impact).

### Existing Patterns To Follow

- A check module exports `NAME` and a `Check`, imports only `validation.base` (plus, here, `normalize_for_match`), and returns entries in a deterministic order.
- Thresholds come from `data.settings`, never from literals. Config readers raise `ConfigError` with the supported values. CLI commands resolve config before any write (already in place).

### Current Gaps

- `ValidationSettings` has only `min_party_coverage_percent`. There is no count, uniqueness or topic check.

## Technical Approach

**Config (`config.py`):**
- Add `DEFAULT_MIN_STATEMENTS = 25`, `DEFAULT_MAX_STATEMENTS = 35` and `DEFAULT_MAX_TOPIC_SHARE_PERCENT = 30`.
- Add three fields to `ValidationSettings`, after the existing one: `min_statements`, `max_statements`, `max_topic_share_percent`. Extend `__post_init__` (Scenario 4) and the docstring.
- In `validation_settings()`, factor out two small private readers: `_percent_env(name, default)`, which reuses the existing coverage message, and `_positive_int_env(name, default)`. Then check the range and build the settings. Keep the existing coverage behaviour and messages byte-for-byte.

**Checks (each a new module importing `Check, ReportEntry, ValidationInput` from `validation.base`):**
- `validation/statement_uniqueness.py`: `STATEMENT_UNIQUENESS = Check("statement_uniqueness", ...)`. It walks `data.statements` in order with a `dict[normalised text → first StatementRow]`. A later hit gives `ReportEntry(f"statement {s.position} duplicates statement {first.position}", statement_id=s.id)`. It imports `normalize_for_match` from `ideology_app.validation.evidence_quotes`.
- `validation/statement_count.py`: `STATEMENT_COUNT = Check("statement_count", ...)`. With `n = len(data.statements)`, it returns one entry when `not min <= n <= max`, otherwise `[]`.
- `validation/topic_spread.py`: `TOPIC_SPREAD = Check("topic_spread", ...)`. If there are no Statements it returns `[]`. Otherwise it builds a `Counter` of `s.topic` and walks topics in first-appearance order. A topic fails when `count * 100 > percent * total`, and the message uses the ceiling percent (Scenario 3).
- `validation/__init__.py`: import the three, extend `CHECKS` (see Decisions) and `__all__`, and update the module docstring and comment.

**Fixtures (`tests/pipeline_fixtures.py`):**
- Add the three env names to `CONFIG_ENV_VARS`.
- Optionally add `statements_payload(count=30, topic=None, duplicate=None)` helpers for the run-level payloads. Keep the default output unchanged.

**Existing tests:** update expectations without weakening intent.
- Append the three `passed` rows to `PASSED_CHECKS` and to the result lists in `test_validation_runs.py`.
- Change the exact `CHECKS` assertion in `test_validation_statement_separation.py` to a prefix (`CHECKS[:3]`). The new test module asserts the full tuple.
- Update the odd-Statements test (Scenario 5).
- Any other test whose run now fails one of the new checks keeps its intent and asserts the new `failure_reason`.

## Expected File Changes

- `src/ideology_app/config.py`: modify (defaults, fields, validation, env reading).
- `src/ideology_app/validation/statement_uniqueness.py`, `statement_count.py`, `topic_spread.py`: create.
- `src/ideology_app/validation/__init__.py`: modify (registry, exports, docstring).
- `tests/test_validation_questionnaire_shape.py`: create (Scenarios 1–4 on plain data and config, full `CHECKS` tuple, purity).
- `tests/pipeline_fixtures.py`: modify (env guard, optional payload helper).
- `tests/test_validation_runs.py`, `tests/test_pipeline_runs.py`, `tests/test_cli_pipeline.py`, `tests/test_validation_statement_separation.py`: modify (Scenario 5, updated expectations).
- No change to `base.py`, `pipeline/`, `cli.py`, migrations, `init.sh`, `pyproject.toml`.

## Visual Design Impact

- UI involved: no. This is a CLI and pipeline change only, with no browser-visible change, so browser validation is exempt (AGENTS.md).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Validation section: list the three modules, the new `CHECKS` tuple and the order rule, the new `ValidationSettings` fields and defaults, and one bullet per check (rule, comparison, message, zero-Statements behaviour, the duplicate normalisation reused from `normalize_for_match`).
  - Configuration bullet: add the three env vars.
- `CONSTRAINTS.md`: update the Validation section. Generalise the separation bullet, or add one: a Statement set that is out of range, contains duplicates or over-weights a topic MUST fail the whole run, and Statements MUST NOT be dropped, deduplicated or reordered to make it pass.
- `docs/domain-model.md`:
  - Check 1 becomes: "Every Statement is unique (same text after normalisation: case, accents, whitespace and punctuation ignored). Single-proposition detection is not automated yet; only the prompts require it."
  - Check 5 becomes: "configured range, default 25–35".
  - Check 6 becomes: "configured share, default 30%; a topic fails when strictly above it".
- `docs/risks-and-open-questions.md`: update in the same change. No existing entry names this feature.
  - Add an Implementation-Time Question: compound-proposition detection (the second half of check 1) is deferred by `validation-questionnaire-shape`. A "y/o" heuristic would cause false failures, so it is to be revisited with real output in `e2e-real-2023-election`.
  - Add a Risk under the real-run entries (`e2e-real-2023-election`): a real model may return fewer than 25 or more than 35 Statements, a paraphrased near-duplicate (not caught), or more than 30% on one topic. Any of these fails the whole run. Mitigation: re-run, a deliberate env threshold change, or a prompt change. Never edit the output.
  - Under "Perceived bias", note that topic spread is now enforced at 30%.
  - Add an Accepted Low: the duplicate normaliser drops separators, so different numbers can collide (`2,1` vs `21`). This is a false failure only.
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`, `docs/technical-discovery.md`: not needed.

## Implementation Plan

1. Config: defaults, fields, validation and env readers, plus config tests (Scenario 4).
2. The three check modules and the registry, plus plain-data tests (Scenarios 1–3).
3. Fixture env guard, then fix existing tests and add the run-level and CLI tests (Scenario 5).
4. Docs, then `CI=true ./init.sh`, then evidence.

## Implementation Tasks

- [ ] `config.py`: constants, `ValidationSettings` fields and `__post_init__`, `validation_settings()` readers and range check.
- [ ] `statement_uniqueness.py`, `statement_count.py`, `topic_spread.py` with the exact messages.
- [ ] `CHECKS`, `__all__` and docstring in `validation/__init__.py`.
- [ ] `tests/test_validation_questionnaire_shape.py`: boundaries 20/24/25/30/35/36/0; custom ranges; duplicate variants (exact, case, accents, whitespace, punctuation, different topic, one-word and one-digit difference, triple); topic 9/30 pass, 10/30 and 15/30 fail; two offending topics in order; share 0 and 100; config parsing; full registry tuple.
- [ ] `CONFIG_ENV_VARS` in `tests/pipeline_fixtures.py`. Update the expectations of existing run and CLI tests. Add the four run-level verification tests (20, duplicates, 50% topic, valid).
- [ ] Docs as listed.

## Verification Plan

- `CI=true ./init.sh` exits 0, with pytest and node passing.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` is clean.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest tests/test_validation_questionnaire_shape.py tests/test_validation_runs.py tests/test_pipeline_runs.py tests/test_cli_pipeline.py -q` passes. It must include the four `feature_list.json` cases: 20 Statements → failed; duplicates → failed; 50% on one topic → failed; valid set → passed.
- `grep -n "import" src/ideology_app/validation/{statement_uniqueness,statement_count,topic_spread}.py` shows only `collections`, `validation.base` and `validation.evidence_quotes`, with no literal `25`, `35` or `30` in the checks.
- `git diff --stat main -- src/ideology_app/migrations src/ideology_app/cli.py src/ideology_app/pipeline src/ideology_app/validation/base.py init.sh pyproject.toml` is empty. `alembic heads` is still `0006`.
- Offline CLI smoke in a scratch directory outside the repo (CliRunner, `cli._provider` patched to the fixture fake, sockets blocked, no key):
  - the default run passes with six `passed` rows;
  - a 20-Statement payload fails with `statement_count`;
  - `VALIDATION_MIN_STATEMENTS=20` makes that same payload pass;
  - `VALIDATION_MAX_TOPIC_SHARE_PERCENT=abc` exits 1 with no run row.
- No E2E harness exists. Browser validation is exempt (no UI).

## Evidence To Capture

- In `feature_list.json` → `validation-questionnaire-shape.evidence` and a `PROGRESS.md` session (never `docs/validations/`):
  - test counts;
  - which tests cover Scenarios 1–5 and the four verification cases;
  - the grep and diff outputs;
  - the smoke results;
  - the "browser validation exempt" note;
  - the docs updated;
  - any deviations.

## Validator Checklist

- [ ] Scope: three checks only, no compound detection, no Statement dropping, no prompt, migration, CLI or dependency change.
- [ ] `CHECKS` is the six-tuple in the stated order. The new checks are pure and read thresholds only from `data.settings`.
- [ ] The duplicate rule uses `normalize_for_match` and ignores topic. Count bounds are inclusive. Topic fails only when strictly above the share. Messages match exactly.
- [ ] Defaults are 25/35/30. Env parsing and the range check reject bad values before any write.
- [ ] The default fake run passes all six checks. The four verification cases are tested with `FakeProvider` only, with no key and no network. Existing tests keep their intent.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/domain-model.md` and `docs/risks-and-open-questions.md` are updated as listed, including the recorded deferral.
- [ ] `feature_list.json` and `PROGRESS.md` hold the evidence. No `docs/validations/` directory exists.
