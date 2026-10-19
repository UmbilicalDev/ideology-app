# Feature Implementation Spec: Validation rejects Statements that don't separate parties

## Source Feature

- `id`: validation-statement-separation
- `area`: validation
- `depends_on`: pipeline-extract-positions (`accepted`). Builds on the framework from `validation-evidence-quotes` and `validation-party-coverage` (both `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (notes: check 4 in `docs/domain-model.md`; "`no stance` positions are ignored for this check")

## Goal

Add Validation check 4, `statement_separation`, through the documented plug-in path: a new module `validation/statement_separation.py` that exports a `Check`, appended to `CHECKS`. A Statement separates the Parties when its Party Positions, ignoring `no stance`, contain at least two different values. A Statement that does not separate them gets one report entry naming it, and the whole run fails (`validation failed: ...statement_separation`). The Dataset Version stays `candidate`, and no Statement is dropped.

The check has no threshold. It needs no `ValidationSettings` field, no `ValidationInput` field, no migration and no CLI change.

## Non-Goals

- No dropping or rewriting of Statements, no publishing, no Dataset Version status change.
- No minimum number of distinct values or of Parties with a stance (no threshold). Adding one later is a `ValidationSettings` field.
- No prompt changes. The generation prompt does not ask for divisive Statements; that risk is recorded, not fixed here.
- No other checks (count, uniqueness, topic spread). No HTTP or UI. No change to `init.sh`. No new dependency.
- No coupling between checks: `statement_separation` does not read `party_coverage` results or its threshold.

## Job Story

When a Pipeline Run has produced a candidate Dataset Version,
I want the run to fail if any Statement gives every Party the same position,
so that Voters never answer a Statement that cannot change the ranking, and I can see which Statements are at fault.

## Users And Permissions

- Operator: CLI only. Reads the report with `ideology pipeline checks --run N`. Cannot override a result.
- Voter: not affected (nothing is published yet).

## Settled Decisions: edge cases

The rule is domain check 4 taken literally: "at least two different Position values", counting only stances (`value is not None`) of Parties in `party_ids`.

1. **Every Party has `no stance` on a Statement → fail.** There are zero values, so fewer than two. Such a Statement adds nothing to any Match Score (the engine skips `no_stance`), so a Voter's answer to it is wasted. Message: `statement S does not separate parties: no party has a stance`.
2. **Only one Party has a stance → fail.** There is one value. The answer moves only that Party's score, so the Statement does not compare Parties. Message: `statement S does not separate parties: only party P has a stance (value V)`.
3. **Two or more stances, all equal → fail** (the core case). Message: `statement S does not separate parties: all K parties with a stance have value V`.
4. **Election with fewer than two Parties (one or zero) → fail with one Election-level entry** instead of one entry per Statement. No Statement can separate a single Party, so the root cause is the Election, not each Statement. `create_run` only requires a parsed document, so a single-Party Election can reach Validation. Message: `statements cannot separate parties: the election has N party` (N = 1) / `... has N parties` (N = 0), followed by `; at least 2 are needed`. The entry has `statement_id=None` and `party_id=None`.
5. **Zero Statements → no entries**, checked before rule 4. There is nothing to separate, and the count belongs to `validation-questionnaire-shape` (same as `party_coverage`).
6. **Interaction with `party_coverage`: both checks report, each about its own subject.** When a Party has no stances at all (no manifesto, no findings), coverage reports that Party once, and separation reports every Statement left with fewer than two stances. In a two-Party Election, that means all of them, each with `only party P has a stance`. We accept this double reporting on purpose:
   - checks stay pure and independent (CONSTRAINTS.md);
   - each entry is true about the data that would be published;
   - the separation message names the cause ("only party 1 has a stance"), so it points at the coverage problem;
   - `failure_reason` lists both checks in registry order (`validation failed: party_coverage, statement_separation`).
   Suppressing the separation entries for low-coverage Parties would make one check depend on another check's threshold.

Other details:
- `S` is the Statement's `position` (the number `pipeline statements` and `pipeline checks` show), not its database id. Each entry carries `statement_id` (the id) and `party_id=None`: the offender is the Statement, not a Party.
- Entries come in `statements` order.
- Positions whose `party_id` is not in `party_ids`, or whose `statement_id` is not in `statements`, are ignored.
- Values are compared as integers, so `0` (neutral) is a stance like any other: a Statement where every Party has `0` fails.

## Acceptance Scenarios

Every test uses plain `ValidationInput` data, or a temporary SQLite database with `FakeProvider`, plus the autouse env/socket guard. No API key, no network.

### Scenario 1: One Statement with every position equal is named (plain data)
Given 3 Statements (positions 1..3, ids 101..103) and Parties 1 and 2, where Statement 2 has values (1, 1) and the others differ
When `STATEMENT_SEPARATION.run(data)` runs
Then it returns exactly `[ReportEntry("statement 2 does not separate parties: all 2 parties with a stance have value 1", statement_id=102)]`.
And with three Parties (1, 1, -1) on Statement 2, the check passes. With (0, 0, 0) it fails with `all 3 parties with a stance have value 0`.

### Scenario 2: `no stance` is ignored
- Values (1, no stance, -1) separate: no entry.
- Values (1, no stance, 1) fail: `all 2 parties with a stance have value 1`.
- Every Party with `no stance`, or with no rows at all for the Statement: `statement S does not separate parties: no party has a stance`.
- Only Party 2 with a stance (value -2): `statement S does not separate parties: only party 2 has a stance (value -2)`.

### Scenario 3: Election-level and empty edge cases
- `party_ids=(1,)` with 3 Statements: exactly one entry, `statements cannot separate parties: the election has 1 party; at least 2 are needed`, with no `statement_id` or `party_id`. `party_ids=()`: the same, with `0 parties`.
- Zero Statements (with any number of Parties): no entries.
- Positions of a Party id not in `party_ids` are ignored (a foreign Party with value -1 does not make (1, 1) separate). Positions of an unknown Statement id are ignored.
- Several offending Statements: one entry each, in Statement position order.
- `CHECKS == (EVIDENCE_QUOTES, PARTY_COVERAGE, STATEMENT_SEPARATION)`, and `run_checks` returns the three results in that order.

### Scenario 4: Run level (`execute_run` / `validate_run`)
- With `seed_election` and the default fake (which now gives Party 1 value 1 and Party 2 value -1 on every Statement; see Test Fake), `execute_run` ends `passed`. `validation_results` holds `evidence_quotes`, `party_coverage` and `statement_separation`, all `passed=true`, in that order.
- A fake where Party 2's page-2 finding has value 1 (equal to Party 1's) gives Statement 2 the values (1, 1). The run ends `failed` with `failure_reason == "validation failed: statement_separation"`. There is exactly one entry: Statement 2's id, `party_id` None, `statement 2 does not separate parties: all 2 parties with a stance have value 1`. This relies on Party 2's first candidate being its page-1 finding, because fill mode copies the first candidate's value to the other Statements; the test asserts exactly one entry. The Dataset Version (`candidate`), its 30 Statements and its 60 Party Positions are unchanged.
- Party 2 without documents, or without findings: `failure_reason == "validation failed: party_coverage, statement_separation"`. There is one coverage entry for Party 2, and 30 separation entries, each `only party 1 has a stance (value 1)`.
- `validate_run` on a `validating` run behaves the same way. Re-running it on a finished run is rejected exactly as before.

### Scenario 5: CLI
- `ideology pipeline checks --run N` on a passing run prints three `passed` rows.
- On the Scenario 4 failing run it prints `statement_separation\tfailed\t2\t\tstatement 2 does not separate parties: all 2 parties with a stance have value 1`.
- `ideology pipeline run` prints `Error: pipeline run N failed: validation failed: statement_separation; see "ideology pipeline checks --run N"` and exits 1.
- `pipeline validate` needs no provider, as before.

## Repository Research

### Files Inspected
- `src/ideology_app/validation/__init__.py`, `base.py`, `party_coverage.py`, `evidence_quotes.py`: `Check`, `ReportEntry(message, statement_id, party_id)`, `ValidationInput` (`statements: StatementRow(id, position, text, topic)`, `positions: PositionRow(... value None = no stance)`, `party_ids`, `settings`), and `CHECKS = (EVIDENCE_QUOTES, PARTY_COVERAGE)`. `party_coverage.py` is the model to follow (pure, ignores foreign Party ids, zero Statements → `[]`).
- `src/ideology_app/pipeline/runs.py`: `create_run` requires only a parsed document, so single-Party Elections can run. `validate_run` stores every check generically.
- `src/ideology_app/cli.py`: `pipeline checks` prints `entry.statement.position` and the party id, or empty cells. No change is needed.
- `src/ideology_app/static/js/match-score.js`: `no_stance` positions are skipped (supports edge cases 1 and 2).
- `tests/pipeline_fixtures.py`: **`findings_response(value=1)` gives every Party value 1, and `positions_response(fill=True)` copies the Party's first candidate value. So in the default run both Parties have value 1 on all 30 Statements, and every default run would fail this check.**
- Tests that depend on this: `tests/test_validation_runs.py` (`_invented_for_party2` adds value 1 for Party 2's Statement 1; expected result lists of two checks), `tests/test_cli_pipeline.py` (positions rows `1\t2\t1...` for Party 2; `test_checks_list_one_row_per_entry`; `test_positions_lists_every_statement_party_pair`, which expects exit 0 on a sparse run), `tests/test_pipeline_runs.py` (`test_party_without_*`, the `failure_reason` asserts), `tests/test_validation_party_coverage.py` (registry test).
- `ARCHITECTURE.md` (Validation), `CONSTRAINTS.md` (Validation), `docs/domain-model.md` (check 4, edge cases), `docs/risks-and-open-questions.md`, `docs/specs/validation-party-coverage.md`, `docs/specs/validation-evidence-quotes.md`, `feature_list.json`, `PROGRESS.md`.

## Technical Approach

**Check (`validation/statement_separation.py`)**, imports only `validation.base`:
```
NAME = "statement_separation"
def check_statement_separation(data) -> list[ReportEntry]
STATEMENT_SEPARATION = Check(NAME, check_statement_separation)
```
1. If `not data.statements`, return `[]`.
2. If `len(data.party_ids) < 2`, return the one Election-level entry (edge case 4).
3. Group stances: for each position with `value is not None`, `party_id in party_ids` and `statement_id` among the Statement ids, record `(party_id, value)` under its `statement_id`.
4. For each Statement in order, compute `distinct = {v for _, v in stances}`. If `len(distinct) >= 2`, it passes. Otherwise build the message for zero, one or K stances (sole Party = its `party_id`; K stances all share `V`).

**Registry:** `CHECKS = (EVIDENCE_QUOTES, PARTY_COVERAGE, STATEMENT_SEPARATION)`, domain check order. Export `STATEMENT_SEPARATION` from `validation/__init__.py`, and update its docstring list if it names checks. If `validation-questionnaire-shape` merges first, append after its check in domain order (check 4 before 5 and 6).

**Test fake (`tests/pipeline_fixtures.py`):** make the default run separate.
- Add `PARTY_VALUES = {1: 1, 2: -1}`.
- `findings_response(value: int | None = None)`: with `None`, each finding's value is `PARTY_VALUES[p]` when the page text is in `PAGES[p]`, else 1. An explicit `value` keeps today's behaviour for every page (`findings_response(1)` gives equal values for both Parties, for separation-failure tests).
- The prompts still never contain Party names. Quotes, pages and call counts are unchanged.
- `positions_response(fill=True)` then gives Party 1 value 1 and Party 2 value -1 on every Statement.

**Existing tests:** keep their intent. A test aimed at another check must keep `statement_separation` passing. Adjust its fake values (e.g. `_invented_for_party2` uses value -1 for its invented finding) rather than widening its expected failures, unless separation failing is inherent to the scenario:
- Party without stances → both coverage and separation fail.
- A sparse (no-fill) run → Statements 3..30 have no stance and fail.

Sparse-run tests that expected `exit 0` with `VALIDATION_MIN_PARTY_COVERAGE_PERCENT=0` now expect the run to fail on `statement_separation`. They still assert their positions output, because a failed run keeps its Dataset Version. Long expected entry lists may be asserted by prefix plus count. Update Party 2 value expectations from `1` to `-1` where the default fake is used.

## Expected File Changes
- `src/ideology_app/validation/statement_separation.py`: create.
- `src/ideology_app/validation/__init__.py`: modify (import, `CHECKS`, `__all__`, docstring).
- `tests/test_validation_statement_separation.py`: create (Scenarios 1–3 on plain data, registry order).
- `tests/pipeline_fixtures.py`: modify (`PARTY_VALUES`, `findings_response` default).
- `tests/test_validation_runs.py`, `tests/test_pipeline_runs.py`, `tests/test_cli_pipeline.py`, `tests/test_validation_party_coverage.py`: modify (Scenarios 4–5, three-check result lists, updated expectations).
- Not changed: `base.py`, `config.py`, `pipeline/runs.py`, `cli.py`, models, migrations, prompts, `init.sh`.
- Docs: see below.

## Visual Design Impact
- UI involved: no. This is a CLI and pipeline change only, so browser validation is exempt (AGENTS.md).

## Durable Documentation Impact
- `ARCHITECTURE.md`: update the Validation section.
  - Package list: add `statement_separation.py` (check 4).
  - `CHECKS` gains `STATEMENT_SEPARATION`.
  - Add a `statement_separation` bullet: the rule, `no stance` ignored, the three per-Statement messages, the Election-level entry, zero Statements, the ignored foreign ids, and that double reporting with `party_coverage` is intended.
  - Tests line: add `tests/test_validation_statement_separation.py`.
- `CONSTRAINTS.md`: update the Validation section. A Statement that does not separate the Parties MUST fail the whole run and MUST NOT be dropped from the Dataset Version. Reason: Dataset Versions are immutable, AI output is never edited, and the run is the unit of publication.
- `docs/domain-model.md`: update.
  - Check 4 becomes "Each Statement separates the parties: at least two different Position values among them, ignoring `no stance` (so a Statement with fewer than two stances fails; an Election with fewer than two Parties fails); otherwise the whole run fails."
  - The edge case "A party with no manifesto…" also notes that, in a two-Party Election, no Statement then separates.
- `docs/risks-and-open-questions.md`: update in the same change.
  - Add a Risk under the real-run entries (`e2e-real-2023-election`): consensus Statements, or Statements where most Parties have `no stance`, fail the whole run. The generation prompt does not see Party Positions, so on real manifestos runs may fail often. Mitigation: re-run, or a later prompt or threshold change. Never drop Statements.
  - Add an Accepted Low: when a Party has no stances, `pipeline checks` lists one separation entry per Statement as well as the coverage entry (intended; the message names the cause).
  - The "Perceived bias" risk already names the separation check: no change.
- `docs/technical-discovery.md`, `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`: not needed.

## Implementation Plan
1. Write `statement_separation.py` and its plain-data tests (Scenarios 1–3).
2. Register the check and update the exports.
3. Change the fixture default to separating values. Run the full suite and fix the expectations as described, without weakening intent.
4. Add the run-level and CLI tests (Scenarios 4–5).
5. Update the docs, run `CI=true ./init.sh`, and record evidence.

## Implementation Tasks
- [ ] `validation/statement_separation.py` with the exact messages.
- [ ] `CHECKS`, `__all__` and the docstring in `validation/__init__.py`.
- [ ] `tests/test_validation_statement_separation.py`. One test per edge case: all no stance, one stance, single-Party Election, zero-Party Election, zero Statements, all `0`, a foreign Party id, an unknown Statement id, ordering, registry.
- [ ] Fixture `PARTY_VALUES` and the `findings_response(None)` default.
- [ ] Updated tests in `test_validation_runs.py`, `test_pipeline_runs.py`, `test_cli_pipeline.py` and `test_validation_party_coverage.py`. New Scenario 4/5 tests (including the coverage + separation double failure).
- [ ] Docs as listed.

## Verification Plan
- `CI=true ./init.sh` exits 0 (pytest and node pass; `filterwarnings=error`).
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest tests/test_validation_statement_separation.py tests/test_validation_runs.py tests/test_pipeline_runs.py tests/test_cli_pipeline.py tests/test_validation_party_coverage.py -q` passes.
- `grep -n "import" src/ideology_app/validation/statement_separation.py` shows only `ideology_app.validation.base` (and stdlib collections at most). No `pipeline`, `llm`, `config`, `os` or `sqlalchemy`.
- `git diff --stat main -- src/ideology_app/migrations src/ideology_app/config.py src/ideology_app/cli.py src/ideology_app/pipeline` is empty. Alembic head is still `0006`, with no drift.
- Offline CLI smoke in a scratch directory outside the repo, with `cli._provider` patched to the fixture fake and sockets blocked:
  - default run → `passed`, three `passed` rows;
  - Party 2 page-2 value 1 → failed `statement_separation`, the Statement 2 row;
  - a Party 2 document set `failed` → `validation failed: party_coverage, statement_separation`.
- No E2E harness exists. Browser validation is exempt.

## Evidence To Capture
In `feature_list.json` → `validation-statement-separation.evidence` and a `PROGRESS.md` session (never `docs/validations/`):
- test counts before and after;
- the tests mapped to Scenarios 1–5 and to each edge case;
- the grep and diff output;
- the smoke results;
- the fixture change and the test expectations it changed;
- the "browser validation exempt" note;
- any deviations.

## Open Questions (non-blocking)
- If `validation-questionnaire-shape` is built in parallel, the branch that merges second rebases. Registry order stays domain order: 2, 3, 4, then 5 and 6.

## Validator Checklist
- [ ] Scope: one new check module, registry and exports. No change to `ValidationSettings`, `ValidationInput`, storage, CLI, runs, prompts or migrations. No new dependency.
- [ ] A Statement with equal positions fails the run and is named by position in the report. `no stance` is ignored.
- [ ] Every edge case (all no stance, one stance, single- and zero-Party Election, zero Statements) behaves as settled and has its own test.
- [ ] The default fake run passes all three checks. Changed test expectations keep their intent, and double reporting with coverage is tested.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/domain-model.md` and `docs/risks-and-open-questions.md` were edited as listed.
- [ ] Evidence is only in `feature_list.json` and `PROGRESS.md`. No `docs/validations/`. `FakeProvider` only, with no key and no network.
