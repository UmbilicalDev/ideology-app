# Feature Implementation Spec: Client-side Match Score calculation

## Source Feature

- `id`: match-score-engine (GitHub issue #6)
- `area`: matching
- `depends_on`: bootstrap-app-skeleton (accepted)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`

## Goal

Ship the Match Score rule from `docs/build-brief.md` as a pure, dependency-free JavaScript ES module. It runs in the Voter's browser, so Answers never reach the server. Given a Voter's Answers and each Party's Party Positions, it returns one Match Score per Party, a count of shared valid Statements, and a "low coverage" flag. The module lives where a later UI feature can serve it as a static asset without moving it.

The feature also adds a JS unit-test runner (`node --test`, built into Node, zero npm dependencies) as a new `init.sh` step. It fixes the deferred Low finding in `init.sh`: `run_step` currently runs steps inside `if !`, which disables `set -e`, so a step with several commands can pass even when one of them fails. `init.sh` must also fail clearly when Node.js is missing or too old.

## Non-Goals

- No UI, no HTML/CSS, no results page, no ranking/sorting or tie-breaking (that is `results-ranking`), no display rounding to whole percentages.
- No `StaticFiles` mount or edit to `src/ideology_app/main.py`; `results-ranking` / `questionnaire-answer-flow` mount `/static`.
- No Share Link encoding (`share-link-create`), no dataset fetch (`public-dataset-api`), no mapping from answer labels (strongly agree ...) to numbers in the UI.
- No npm dependencies, no `package-lock.json`, no bundler, no TypeScript, no lint tooling.
- No Python source, migration, CLI or `pyproject.toml` change (a parallel session is doing `source-document-url`).
- No change to the matching rule or the threshold in `docs/build-brief.md`.

## Job Story

When I have answered the Questionnaire in my browser,
I want each Party scored against my Answers by a transparent, fixed rule,
so I can trust the ranking, and nothing I answered leaves my device.

## Users And Permissions

- Voter: indirectly. A later UI feature runs the module in the browser on data the Voter already holds.
- Operator: none. Developers/agents run the tests through `./init.sh`.

## Public API (contract for `results-ranking` and `share-link-create`)

File: `src/ideology_app/static/js/match-score.js` (ES module, `export` only, no default export, no imports, no globals such as `window`, `document`, `fetch`, `localStorage`).

```js
export const SKIP = "skip";                 // Answer value
export const NO_STANCE = "no_stance";       // Party Position value
export const IMPORTANT_WEIGHT = 2;          // weight of an Important Answer (else 1)
export const LOW_COVERAGE_THRESHOLD = 5;    // N in docs/build-brief.md

export function statementAgreement(answerValue, positionValue) // -> number in [0, 1]
export function computeMatchScore(answers, positions, options = {})   // -> MatchScoreResult (no partyId)
export function computeMatchScores(answers, parties, options = {})    // -> MatchScoreResult[]
```

- `answers`: array of `{ statementId, value, important }`. `value` is an integer in −2..+2 or `SKIP`. `important` is optional (`undefined` = `false`); if present it must be a boolean.
- `positions`: array of `{ statementId, value }`. `value` is an integer in −2..+2 or `NO_STANCE`.
- `parties`: array of `{ partyId, positions }`. The output keeps the input order (no sorting).
- `statementId` may be a number or a string. It is matched by `String(statementId)`, so `7` and `"7"` are the same Statement.
- `options.lowCoverageThreshold`: positive integer, default `LOW_COVERAGE_THRESHOLD`.
- `MatchScoreResult`: `{ partyId, matchScore, sharedStatementCount, lowCoverage }` (`computeMatchScore` omits `partyId`).
  - `matchScore`: number in [0, 1] = Σ(w·agreement) / Σw over the included Statements, or `null` when `sharedStatementCount === 0`. It is never `NaN`, and there is no division by zero.
  - `sharedStatementCount`: the number of Statements that have both an Answer other than `SKIP` and a Position other than `NO_STANCE`.
  - `lowCoverage`: `sharedStatementCount < lowCoverageThreshold`. This is `true` for 0..4 and `false` for 5 or more with the default.
- Rules: agreement = `1 − |a − p| / 4`. The weight is `IMPORTANT_WEIGHT` if `important === true`, otherwise 1. A Statement with an Answer and no Position entry for that Party, or with a Position and no Answer, is excluded, the same as skip / no stance. `important` on a skipped Answer has no effect.
- Invalid input throws, and the message names the offending field and `statementId`: `TypeError` for a non-array `answers`/`positions`/`parties` or a non-boolean `important`, `RangeError` for a value outside the sets above (`3`, `1.5`, `NaN`, `"agree"`, `null`), and `RangeError` for a duplicate `statementId` within one array or for a bad threshold.
- Purity: inputs are never mutated, and the same input always gives the same output.

## Acceptance Scenarios

All scenarios are `node:test` cases in `tests/js/match-score.test.js`. Scores are compared with `assert.strictEqual` against exact fractions such as `11 / 12`. Agreements are multiples of 0.25 and weights are integers, so the sums are exact and only the final division rounds (correctly, in both cases).

### Scenario 1: Identical answers give 100%
Given 6 Statements and a Party whose Positions equal the Voter's values (mixing −2, −1, 0, +1, +2)
When `computeMatchScore` runs
Then `matchScore === 1`, `sharedStatementCount === 6`, `lowCoverage === false`.

### Scenario 2: Opposite answers give 0%
Given 5 Statements answered +2 / −2 and Positions −2 / +2 respectively
Then `matchScore === 0` and `lowCoverage === false`.

### Scenario 3: Per-Statement agreement
`statementAgreement` returns 1, 0.75, 0.5, 0.25, 0 for distances 0..4, for example (0,0), (1,0), (0,2), (−1,2), (−2,2). It is symmetric: `statementAgreement(a,p) === statementAgreement(p,a)`.

### Scenario 4: Important weighs ×2
Given Statement A (agreement 1, Important) and Statement B (agreement 0, not Important), plus 3 filler Statements with agreement 0.5
Then `matchScore === (2·1 + 1·0 + 3·0.5) / (2 + 1 + 3)`, which is `3.5 / 6`.
With B Important instead, it is `(1 + 2·0 + 1.5) / 6`, which is `2.5 / 6`.
With no Important flags, it is `2.5 / 5` (that is, `0.5`).
Reordering the arrays does not change any of these values.

### Scenario 5: Skip and no stance are excluded
Given 7 Statements, one answered `SKIP` (with `important: true`) and one where the Party has `NO_STANCE`
Then both are left out of numerator and denominator: `sharedStatementCount === 5`, and the score equals the score computed on the 5 remaining Statements alone. A Statement whose Position entry is missing, or whose Answer is missing, is excluded the same way.

### Scenario 6: Neutral is an answer, not a skip
Given an Answer `0` and a Position `+2`
Then that Statement is included with agreement 0.5.

### Scenario 7: Low-coverage threshold
Given 4 shared valid Statements, then `lowCoverage === true`. With 5 it is `false`. With `options.lowCoverageThreshold: 3` and 3 shared Statements it is `false`, and with 2 it is `true`.

### Scenario 8: Zero shared Statements
Given every Answer is `SKIP`, or the Party has `NO_STANCE` on every answered Statement, or `answers` is `[]`
Then `matchScore === null`, `sharedStatementCount === 0`, `lowCoverage === true`, and nothing throws.

### Scenario 9: Several Parties
Given three Parties
When `computeMatchScores` runs
Then it returns three results in input order, each carrying its `partyId` and equal to `computeMatchScore` for that Party. `statementId` `7` in the Answers matches `"7"` in the Positions.

### Scenario 10: Invalid input fails loudly
Answer value `3`, `1.5`, `"agree"`, `null` → `RangeError`. Position value `"no stance"` (with a space) → `RangeError`. `important: "yes"` → `TypeError`. Duplicate `statementId` in Answers → `RangeError`. `answers` not an array → `TypeError`. `lowCoverageThreshold: 0` → `RangeError`.

### Scenario 11: Purity
Given deeply frozen inputs (`Object.freeze` on the arrays and on each item)
Then no call throws and two calls return deep-equal results.

### Scenario 12: init.sh gate
Given the repo with Node ≥ 22 on `PATH`
When `CI=true ./init.sh` runs
Then it prints `==> node`, `==> install`, `==> pytest`, `==> js-test` in that order, the JS tests report 0 failures, and it exits 0.
Given no `node` on `PATH`, or `node` older than 22, it prints a clear reason and `FAILED: node`, exits 1, and does not run later steps.
Given a step function whose first command fails and whose last command succeeds, `run_step` prints `FAILED: <name>` and exits 1.
Given `tests/js/` contains no `*.test.js` files, `js-test` fails rather than passing with 0 tests.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md` (Session 003/005 deferred `run_step`/`set -e` finding), `feature_list.json` (this entry, plus `results-ranking`, `share-link-create`, `questionnaire-*`, `public-dataset-api` for downstream needs).
- `docs/build-brief.md` (Matching Rule), `CONTEXT.md` (Answer, Important, Party Position, No Stance, Match Score), `docs/domain-model.md` (Position ∈ {−2..+2, no stance}; "skips every Statement → no ranking"), `docs/technical-discovery.md` (Jinja + HTMX or small SPA; matching client-side), `DESIGN.md` (UI only, not relevant here).
- `init.sh`, `ARCHITECTURE.md` (Verification Gate), `CONSTRAINTS.md`, `pyproject.toml` (pytest `testpaths = ["tests"]`, collects `test_*.py` only), `.gitignore`.

### Experiments (scratchpad outside the repo, Node v24.22.0, macOS `/bin/bash` 3.2.57)

- `node --test <files>` imports a sibling ES module by relative path, exits 1 on a failed assertion, and **exits 0 when no files match** (so the step must check that test files exist).
- With no `package.json`, Node detects ESM syntax silently. If an **ancestor** directory has a `package.json` without `"type"`, Node prints a `MODULE_TYPELESS_PACKAGE_JSON` warning. A root `package.json` with `"type": "module"` removes this.
- `if ! ( set -e; "$@" )` still swallows the failure: bash ignores `set -e` in a subshell that is evaluated as a condition. Only running the subshell outside any condition works: `set +e; ( set -e; "$@" ); rc=$?; set -e`.
- With `set -u` on bash 3.2, `${#arr[@]}` is safe on an empty array, but `"${arr[@]}"` is not. Check the count before expanding.
- Python `mimetypes` maps `.js` to `text/javascript`, so a future `StaticFiles` mount serves the module with a valid module MIME type.

### Existing Patterns To Follow

- `init.sh` steps are `step_<name>` functions called through `run_step <name> <fn>`, and `init.sh` never starts a server.
- Tests are offline and deterministic. pytest runs with `filterwarnings = ["error"]`.

### Current Gaps

- No JS anywhere in the repo yet, no `static/` directory, no `package.json`. There is no StaticFiles mount (that is out of scope here).

## Technical Approach

- **Module location**: `src/ideology_app/static/js/match-score.js`. It sits inside the Python package, so a UI feature can `app.mount("/static", StaticFiles(directory=<package>/static))` and import `/static/js/match-score.js` from a `<script type="module">`. Packaging for a non-editable install (setuptools package-data) is left to the feature that mounts it.
- **Module system**: add a root `package.json` containing exactly `{"private": true, "type": "module"}` (no `dependencies`, no `scripts`). There are no deps, so no lockfile is needed. It must never be used for `npm install`.
- **Implementation**: first validate and index each input array into a `Map<string, entry>`, then iterate the Answers. Skip an Answer when it is `SKIP`, has no Position, or the Position is `NO_STANCE`. Otherwise accumulate `w·agreement` and `w`. `matchScore = totalWeight === 0 ? null : weighted / totalWeight`. Use `Number.isInteger(v) && v >= -2 && v <= 2` for numeric values. Keep it to about 120 lines and add a header comment that cites `docs/build-brief.md`.
- **Tests**: `tests/js/match-score.test.js` uses `node:test` and `node:assert/strict`, and imports `../../src/ideology_app/static/js/match-score.js`. One `describe` per scenario group.
- **init.sh** (keep `set -euo pipefail` and the existing steps, and stay compatible with bash 3.2):
  - `run_step` becomes: print `==> $name`; `set +e`; `( set -e; "$@" )`; `rc=$?`; `set -e`; if `rc != 0`, print `FAILED: $name (exit $rc)` and `exit 1`.
  - `step_node`: if `command -v node` fails, print `Node.js >= 22 is required for the JS unit tests (node not found on PATH)` and return 1. Otherwise read `node -p 'process.versions.node'`, take the major with `${v%%.*}`, and if it is below 22 print `Node.js >= 22 is required (found v$v)` and return 1. Otherwise print `Node: v$v`. Constant `NODE_MIN_MAJOR=22`. 22 is the oldest LTS where `node --test` and ESM detection behave as in the experiments.
  - `step_js_test`: `shopt -s nullglob`; `files=(tests/js/*.test.js)`; if the count is 0, print `no JS test files in tests/js` and return 1; otherwise `node --test "${files[@]}"`.
  - Order: `run_step node step_node` runs **first** (fail fast, before pip), then `install`, `pytest`, `js-test`. Remove the "Add new verify steps here" example mention of match-score-engine but keep the generic how-to comment.
- **Regression test for init.sh**: `tests/test_init_script.py` (pytest, a new file, no app imports). It extracts the `run_step` and `step_node` function bodies from `init.sh` (from the line matching `^<name>\(\) \{` to the next `^\}`) and runs them under `/bin/bash -c 'set -euo pipefail; <defs>; ...'` via `subprocess.run`:
  - a multi-command step `f() { false; echo after; }`: exit 1, stdout contains `FAILED: demo`, not `after`;
  - a passing step: exit 0 and the script continues;
  - `step_node` with `PATH` set to an empty `tmp_path` dir: exit non-zero, message mentions `Node.js >= 22`;
  - `step_node` with a fake `node` (`#!/bin/sh` script printing `20.11.1`): fails with `found v20.11.1`; printing `24.1.0`: passes.
  These use only bash builtins plus the fake script, so they need no real node. The test is skipped if `/bin/bash` is absent.

## Expected File Changes

- `src/ideology_app/static/js/match-score.js`: create; the engine.
- `tests/js/match-score.test.js`: create; scenarios 1-11.
- `tests/test_init_script.py`: create; scenario 12 `run_step` / `step_node` checks.
- `package.json`: create; `{"private": true, "type": "module"}` only.
- `init.sh`: modify; `run_step` fix, `step_node`, `step_js_test`, step order.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `PROGRESS.md`, `feature_list.json`: modify (see below).
- Must NOT change: anything under `src/ideology_app/*.py`, `src/ideology_app/migrations/`, `src/ideology_app/llm/`, `pyproject.toml`, `tests/conftest.py`, `docs/validations/` (never create).

## Visual Design Impact

- UI involved: no. Design source: not applicable. No new design artifact.
- Browser Validation (AGENTS.md) is **exempt**: the feature adds no page, form, route, asset mount or client behaviour that a user can see. The module is not loaded by any page yet. It is verified by Node unit tests. The first UI feature that imports it (`results-ranking`) does the browser checks, including the "no request carries voter answers" check.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add a short "Client-side Matching" section (module path, exports, no imports or globals, intended `/static/js/match-score.js` URL, root `package.json` is only for `"type": "module"`), and update "Verification Gate" (steps `node`, `install`, `pytest`, `js-test`; `run_step` runs each step in a `set -e` subshell outside a condition; Node ≥ 22 required).
- `CONSTRAINTS.md`: update. Add a "Client-side Matching" section with these rules:
  - The Match Score MUST be computed only in `match-score.js` in the browser. The server MUST NOT get an endpoint that receives Answers. Reason: the no-voter-data invariant.
  - The module MUST stay dependency-free with no imports. Reason: it is served as-is as a static asset.
  - JS tooling MUST NOT add npm dependencies without committing a lockfile. Reason: reproducible gate.
- `AGENTS.md`: not needed. The startup path is still `./init.sh`.
- `PROGRESS.md`: update the "Standard verification path" line (Node ≥ 22 now required; `node --test` step), add a session entry, and mark the `run_step` Low finding resolved.
- `docs/build-brief.md`, `CONTEXT.md`: not needed. The rule is unchanged. The zero-shared behaviour (`null` + low coverage) is recorded in `ARCHITECTURE.md`.

## Implementation Plan

1. Fix `run_step` and add `step_node` in `init.sh`. Write `tests/test_init_script.py` and confirm it fails against the old `run_step` (temporarily, in a scratch copy) and passes against the new one.
2. Add `package.json`, then write `tests/js/match-score.test.js` (scenarios 1-11) and `match-score.js` until the tests pass.
3. Add `step_js_test` and the step order, and run `CI=true ./init.sh`.
4. Update the docs, `feature_list.json` (status `passing` + evidence) and `PROGRESS.md`.

## Implementation Tasks

- [ ] `init.sh`: new `run_step`, `step_node` (`NODE_MIN_MAJOR=22`), `step_js_test`, order node → install → pytest → js-test.
- [ ] `tests/test_init_script.py`: the five cases above.
- [ ] `package.json` with `"type": "module"` only.
- [ ] `src/ideology_app/static/js/match-score.js` per the Public API section.
- [ ] `tests/js/match-score.test.js` covering scenarios 1-11.
- [ ] Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `PROGRESS.md`. State: `feature_list.json`.

## Verification Plan

- `CI=true ./init.sh` → exit 0, steps in order, `node --test` summary shows `fail 0` and at least 11 tests, pytest all pass (count = previous + new init-script tests).
- `node --test tests/js/match-score.test.js` → exit 0, no `Warning` lines on stderr.
- Scratch copy of the repo (outside the worktree):
  - change `step_pytest` to `false; "$PY" -m pytest` → `FAILED: pytest`, exit 1;
  - `PATH=/usr/bin:/bin ./init.sh` (node lives in `/usr/local/bin` here) → `FAILED: node`, exit 1, no `==> install`;
  - break one JS assertion → `FAILED: js-test`, exit 1;
  - move `tests/js/*.test.js` away → `FAILED: js-test`.
- `grep -nE "\\b(window|document|fetch|localStorage|XMLHttpRequest|import )" src/ideology_app/static/js/match-score.js` → no matches.
- `git status` shows only the files listed in Expected File Changes, and no `node_modules/`, `package-lock.json` or `docs/validations/`.
- `init.sh` executes checks only and never starts uvicorn. It still prints the manual start command at the end.
- E2E: none exists, and this feature has no user/API flow, so unit tests are sufficient.

## Evidence To Capture

- `init.sh` exit code and the passed counts for pytest and node, plus the Node version line.
- The results of the four scratch-copy negative checks.
- The grep result for browser/network globals.
- A note that Browser Validation is exempt (no browser-visible change).

## Validator Checklist

- [ ] Scope: no Python app source, migration, CLI or `pyproject.toml` change, and no UI or static mount.
- [ ] API matches the Public API section (names, `null` for zero shared, `lowCoverage` boundary at 5, throw types).
- [ ] Scenarios 1-12 pass, and scores are asserted exactly rather than approximately.
- [ ] `run_step` fails a multi-command step whose first command fails (automated test plus scratch check).
- [ ] Missing or old Node fails `init.sh` with `FAILED: node` before `install`.
- [ ] `js-test` fails when no test files exist.
- [ ] No npm deps, no lockfile needed, `package.json` contains only `private` + `type`.
- [ ] Docs updated as listed, evidence in `feature_list.json` and `PROGRESS.md`, and no `docs/validations/`.

## Risks And Open Questions

- The `NO_STANCE = "no_stance"` and integer value encoding are chosen here, before `public-dataset-api` exists. That feature should emit these values or map them once at load. Flag this in its spec.
- The minimum number of answered Statements before a ranking is shown is still open (`docs/risks-and-open-questions.md`). The engine exposes `sharedStatementCount` / `null` so the UI can decide.
- Extracting functions from `init.sh` by line pattern in `test_init_script.py` breaks if their formatting changes. The test should fail loudly ("function not found") rather than pass vacuously.
