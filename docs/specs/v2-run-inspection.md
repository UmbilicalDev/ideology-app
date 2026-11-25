# Feature Implementation Spec: Inspect a v2 Pipeline Run: pool report, Statement sources and Proposal Evidence

## Source Feature

- `id`: v2-run-inspection
- `area`: pipeline
- `depends_on`: statements-from-proposals (accepted); also reads the tables of constituency-selection-validation, statement-rewording and public-dataset-api-v2 (all accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json`
- Branch: `feature/v2-run-inspection`, cut from `feature/public-dataset-api-v2` (base commit `98640af`). Merged into `v2` by PR, after #129–#133.

## Goal

An Operator can see what a v2 run did, from the stored data alone, before committing the shared database. `ideology pipeline report --run R` shows the pool report and the 52-row per-Constituency table. `ideology pipeline statements --run R --sources` lists each Statement's source Proposals. `ideology pipeline positions --run R --evidence` lists each Position's Evidence Proposals with their Constituencies. All of this is read-only and needs no LLM provider. Legacy output stays byte-identical.

The feature also fixes two small Operator-facing Accepted Lows that name it (see "Owned risk entries"): `run-queued` breaking on a stuck queued v2 run, and `pipeline validate` using the current environment instead of the run's recorded per-Constituency thresholds.

## Non-Goals

- Any write to runs, Dataset Versions, Statements, Positions or the report JSON. No migration. No new key in `statement_selection`.
- Any change to the v2 run itself (prompts, pool, positions, selection, rewording, publishing), to the API, the web client or `packages/`. No UI, so no browser check.
- Changing the existing one-line `constituencies:` summary of `pipeline report` and `run-v2` (D7).
- Recording the context-note thresholds at generation time (see residual in D10).
- Price table, `pipeline list` columns, legacy report sections.

## Job Story

When a v2 run finishes (or fails Validation) on the shared database,
I want to see the pool, the Statement sources, the Evidence and each Constituency's availability in the terminal,
so I can decide whether to commit the database, change a minimum, or reword a Statement, without opening SQLite.

## Users And Permissions

- Operator (local CLI): reads any run. `pipeline validate` is the only command touched here that writes, and it already did.

## Acceptance Scenarios

Fixtures: the format-2 scratch bundle and `v2_fake()` of `tests/v2_fixtures.py` (fake provider only). Outputs are tab-separated (`_print_rows`); tests pin the full stdout.

### S1: v2 report shows the pool report
Given a passed v2 run R
When `ideology pipeline report --run R` runs
Then the key lines are those of today plus one `positions:` line right after `statement_selection:`, of the form `positions: 4 calls, 30 sided, 6 no stance, 1 slice disagreements, 2 source-party no stance` (from `statement_selection.positions`).
And after the `validation report:` table and the optional `rewordings:` table come, each after a blank line:
- `parties:`, columns `party, short_name, proposals, partial_scope, sided, no_stance, excluded`. One row per Party of the candidature snapshot, by Party id. Non-Excluded Parties take `proposals` and `partial_scope` (`yes`/`no`) from `statement_selection.parties`, and `sided`/`no_stance` counted from the version's `party_positions`; `excluded` is empty. Excluded Parties have only `party`, `short_name` and `excluded` (the reason) filled.
- `categories:`, columns `category, proposals, calls, drafted, additions`, from `statement_selection.categories` in stored order.
- `filtered statements:`, columns `drafted, status, text` (`drafted` is the number in the drafted pool, not a Statement position). Only when the list is non-empty.
- `slice disagreements:`, columns `statement, party, category, values` (`values` joined with `/`, e.g. `1/-1`). Only when non-empty.
- `source parties with no stance:`, columns `statement, party`. These are Statements where a Party has `no stance` although one of its frozen counted Proposals (`dataset_version_proposals`) is a source (`statement_proposals`). They are computed from the tables, ordered by Statement position then Party id. The row count equals `positions.source_party_no_stance`. Shown only when non-empty.
- `constituencies:` (S2).

### S2: the 52-row per-Constituency table
Given the same run
When the report prints
Then `constituencies:` has columns `code, name, available, reason, parties, excluded, valid, lengths, party_sides, topic_max_share` and exactly 52 rows in `CONSTITUENCIES` order.
- `available` (`yes`/`no`) and `reason` (empty when available) come from `dataset_version_constituencies`. `name` comes from `constituencies.CONSTITUENCIES`.
- The other columns come from `statement_selection.constituencies.rows`:
  - `parties` and `excluded`: Party ids joined with `,`.
  - `valid`: the number of valid Statements.
  - `lengths`: joined with `/`.
  - `party_sides`: space-separated `party:sides/first_length_sides` (just `party:sides` when `first_length_sides` is null).
  - `topic_max_share`: joined with `/`.
  - Empty lists print as an empty cell.
- When a stored row and the report row disagree on `valid`, the table shows the stored `valid_statement_count`. `db check` covers consistency; this table does not check it.

### S3: v2 report without a Dataset Version or with an older report
Given a v2 run that failed before writing its version (`statement_selection` is NULL)
Then the output is exactly today's (no `positions:` line and no new sections).
Given a stored v2 report without the `constituencies` or `rewordings` key (scratch DBs of earlier slices)
Then the sections that need the missing key are skipped, and nothing raises.

### S4: Statement sources
Given a v2 run R with Dataset Version V
When `ideology pipeline statements --run R --sources` runs
Then the columns are `statement, rank, proposal, party, file, page, excerpt`, with one row per source Proposal (`statement_proposals`, by Statement position then rank) and per Party that counts it in V (`dataset_version_proposals`, by Party id).
- `file` is that row's Source Document `original_filename`, or `source_url` when there is no filename.
- `page` is the Proposal's page.
- `excerpt` is `_one_line(text)` cut at 120 characters with a trailing `…` when cut (D3).
- A source Proposal that no Party counts in V (should not happen) gets one row with empty `party` and `file`.
And `ideology pipeline statements --run R` (no flag) prints exactly what `--dataset-version V` prints.

### S5: Position Evidence
Given the same run
When `ideology pipeline positions --run R --evidence [--party P]` runs
Then the columns are `statement, party, value, rank, proposal, file, page, constituencies, excerpt`, one row per Position × Evidence Proposal (`party_position_proposals`, by Statement position, Party id, rank).
- `file` comes from the Evidence row's `source_document_id`.
- `constituencies` is `all` when the frozen codes equal the Party's codes in `dataset_version_candidatures` for V. Otherwise it is the codes joined with `,` (D5).
- A `no stance` Position has one row with `value`, `rank` and the later columns empty (D6).
- `--party` filters as today.

### S6: flag and id errors (exit 1 or 2, nothing written)
- Neither or both of `--dataset-version` and `--run` → usage error (exit 2): `pass exactly one of --dataset-version or --run`.
- `--run R` for an unknown run → `Error: pipeline run R not found`. For a run without a Dataset Version → `Error: pipeline run R has no dataset version`.
- `--sources` or `--evidence` on a legacy version → `Error: dataset version V is a legacy dataset version; --sources needs a v2 one` (`--evidence` likewise). Exit 1, nothing on stdout.

### S7: legacy byte-identity
Given scratch copies of `data/ideology.db` (runs 1–5, Dataset Versions 1–5)
When the commands below run with the code at `98640af` and with this branch
Then stdout, stderr and the exit codes are identical:
- `pipeline report --run 1..5`, `pipeline checks --run 1..5`, `pipeline list --election 1|2`;
- `pipeline statements --dataset-version 1..5`, `pipeline positions --dataset-version 1..5` (and `--party` for one Party of each Election);
- `pipeline run-queued --yes` (no queued run), `pipeline validate --run 3` (refused, not validating).
And `pipeline statements --run 3` equals `--dataset-version 3`, and `pipeline positions --run 5` equals `--dataset-version 5`.

### S8: `run-queued` skips queued v2 runs (owned Low)
Given a `queued` v2 run N and no queued legacy run
When `ideology pipeline run-queued` runs
Then stderr has `Warning: pipeline run N is a queued v2 run and was skipped; start a new one with "ideology pipeline run-v2 DIR"`, stdout has `No queued pipeline runs`, the exit code is 0, nothing is asked or written, and run N stays `queued`.
Given a queued v2 run and a queued legacy run, only the legacy run executes, the same warning is printed, and the exit code follows the legacy run as today. `--election` filters both.

### S9: `pipeline validate` uses the run's recorded thresholds (owned Low)
Given a v2 run left in `validating` that selected with `VALIDATION_V2_MIN_STATEMENTS=3`, `…_MIN_PARTY_SIDES=1` and `max_topic_share_percent=30`, recorded in `statement_selection.constituencies.settings`
When `pipeline validate --run R` runs with a different `VALIDATION_V2_MIN_*` and `VALIDATION_MAX_TOPIC_SHARE_PERCENT` in the environment
Then the run is validated with the recorded three values and `constituency_availability` passes. The run's `validation_settings` records the recorded values.
And stdout first prints `Using the run's recorded constituency settings: max_topic_share_percent=30, v2_min_party_sides=1, v2_min_statements=3`.
A legacy run is unchanged: thresholds come from the environment and there is no extra line.

## Repository Research

### Files Inspected

- `src/ideology_app/cli.py` — `pipeline_report` (v2 branch: `pool_summary`, `constituency_summary`, `rewording_summary`, `rewordings:` table), `pipeline_statements`/`pipeline_positions` (only `--dataset-version`), `pipeline_run_queued`, `pipeline_validate`, `_print_rows`, `_one_line`, `requires_db` (maps `ElectionsError` to `Error: …`).
- `src/ideology_app/pipeline/reports.py` — `RunReport` already carries `model_generation`, `dataset_version_id`, `statement_selection`. No change is needed.
- `src/ideology_app/pipeline/v2/stored.py` — `constituency_summary`, `dataset_version_problems`. The docstring hands the 52-row table to this feature.
- `src/ideology_app/pipeline/v2/run.py` — `_finish_v2` writes the report (`{**pool.report, "constituencies": selection.report}`), the Statements, sources, Evidence and frozen Proposals in one commit. `execute_v2_run` builds the pool report keys: `version`, `bundle`, `parties`, `partial_scope_parties`, `proposals`, `categories`, `filtered`, `pool_size`, `positions`, `rewordings`.
- `src/ideology_app/pipeline/v2/pool.py` (category rows; `filtered` numbered in the drafted pool), `v2/positions.py` (`calls, sided, no_stance, slice_disagreements[{party_id, category, pool, values}], source_party_no_stance`), `v2/selection.py` (`constituencies` report: `settings`, `available`, `unavailable`, `valid_nowhere`, `rows[{code, parties, excluded, valid, lengths, party_sides[{party_id, sides, first_length_sides}], topic_max_share}]`).
- `src/ideology_app/pipeline/runs.py` — `list_queued_run_ids` has no generation filter. `_start` raises `InvalidInputError` for v2. `validate_run(..., settings, constituency_settings)` reads the env when `None`. `list_positions`, `get_dataset_version`.
- `src/ideology_app/models.py` — `StatementProposal`, `PartyPositionProposal`, `DatasetVersionConstituency`, `DatasetVersionCandidature`, `DatasetVersionProposal`, `Proposal` (`page`, `text`), `SourceDocument` (`original_filename`, `source_url`), `Party.short_name`.
- `src/ideology_app/config.py` (`ConstituencySettings`), `validation/constituencies.py` (uses both minimums and `data.settings.max_topic_share_percent`).
- `tests/test_cli_pipeline_v2.py`, `tests/v2_fixtures.py`, `tests/test_validation_constituencies.py` (pins `validate_run` reading the env for v2 when `None`; this stays true).
- `docs/risks-and-open-questions.md` lines 148, 157, 272, 275. `docs/specs/statements-from-proposals.md`, `constituency-selection-validation.md`, `statement-rewording.md`, `public-dataset-api-v2.md`. `docs/technical-discovery.md` (runbook l.142), `README.md` l.253–256, `ARCHITECTURE.md` l.74–87, `CONSTRAINTS.md` l.132.
- `data/ideology.db`: head `0021`, runs 1–5 and versions 1–5 all legacy, no v2 run and no queued run.

### Existing Patterns To Follow

- Read-only helpers in `pipeline/v2/stored.py` (only `SELECT`s, plain return values). The CLI formats them with `_print_rows`, prints `None` as empty, and puts a blank line before each section title.
- v2 report output is gated on `report.model_generation is ModelGeneration.V2`. Legacy branches are not touched.
- Tests: `CliRunner` with separate stderr, the `run`/`use` fixtures, `setup()` + `v2_fake()`, exact-string assertions.

### Current Gaps

- No reader for `statement_proposals`, `party_position_proposals`, the constituency rows or the per-Party side counts.
- `statements`/`positions` cannot take a run id.

## Technical Approach

1. **`src/ideology_app/pipeline/v2/inspection.py` (new, read-only, `SELECT` only, frozen dataclasses of plain values).**
   - `party_rows(session, version_id, selection) -> list[PartyRow]`
   - `source_no_stance(session, version_id) -> list[tuple[int, int]]` (Statement position, Party id)
   - `constituency_rows(session, version_id, selection) -> list[ConstituencyTableRow] | None` (`None` without the `constituencies` key)
   - `statement_sources(session, version_id) -> list[SourceRow]`
   - `position_evidence(session, version_id, party_id) -> list[EvidenceRow]` (reuses `list_positions` for the Party check)
   - `recorded_constituency_settings(selection) -> tuple[ConstituencySettings, int] | None` (pure; `None` when the key is missing)
   - `excerpt(text, limit=120)`

   Export them from `pipeline/v2/__init__.py`. Batch the queries (one per table, joined in Python) so that 300 Statements × 12 Parties stays fast.
2. **CLI `pipeline report`.** In the v2 branch, add the `positions:` key line, then the sections of S1/S2 after the `rewordings:` table. Formatting helpers live next to `REWORDINGS_HEADER` (`PARTIES_HEADER`, `CATEGORIES_HEADER`, `CONSTITUENCIES_HEADER`, …). Every new read happens inside the existing `session_scope`. The legacy branch is not touched.
3. **CLI `pipeline statements` / `positions`.** `--dataset-version` stops being `required`. Add `--run` (int), and `--sources` / `--evidence` (flags). A shared `_version_for(session, dataset_version_id, run_id) -> DatasetVersion` enforces "exactly one" (`click.UsageError`) and resolves the run (`NotFoundError`, `InvalidInputError` for no version). The legacy refusal is a `click.ClickException` raised before any output. The no-flag path keeps today's code unchanged.
4. **`run-queued` (S8).** `list_queued_run_ids(session, election_id=None, generation: ModelGeneration | None = None)`, where `None` keeps today's behaviour for other callers. The CLI asks for `LEGACY` runs and, separately, for `V2` runs to warn about. The warnings go to stderr before `No queued pipeline runs` or before the confirmation.
5. **`pipeline validate` (S9).** Before calling `validate_run`, the CLI reads the run (read-only session): if it is v2 and `recorded_constituency_settings(statement_selection)` is not `None`, it passes `constituency_settings=` and `settings=dataclasses.replace(env_settings, max_topic_share_percent=recorded)`, and prints the line. `validate_run` stays unchanged, so its env default for direct callers still holds.

## Expected File Changes

- `src/ideology_app/pipeline/v2/inspection.py` — create.
- `src/ideology_app/pipeline/v2/__init__.py` — modify; export the new names.
- `src/ideology_app/pipeline/v2/stored.py` — modify the docstring only (the table now lives in `inspection`).
- `src/ideology_app/pipeline/runs.py` — modify; add the `generation` filter to `list_queued_run_ids`.
- `src/ideology_app/cli.py` — modify `pipeline_report` (v2 branch), `pipeline_statements`, `pipeline_positions`, `pipeline_run_queued`, `pipeline_validate`.
- `tests/test_v2_inspection.py` — create (unit tests of the readers on a v2 version built with `v2_fake()`).
- `tests/test_cli_pipeline_v2.py` — modify; exact outputs for S1–S6, S8 and S9. Add a hand-built queued v2 run like the existing legacy-refusal test.
- `tests/test_pipeline_triggers.py` — modify; cover the generation filter.
- Docs listed below.

## Visual Design Impact

- UI involved: no. Design source: not applicable. No browser check (CLI only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add `v2/inspection.py` to the v2 module list, the `generation` filter of `list_queued_run_ids`, and the new CLI flags in the Operator CLI line.
- `CONSTRAINTS.md`: update line 132. `pipeline statements|positions` (including `--sources`/`--evidence`) MUST stay read-only like `pipeline report`.
- `AGENTS.md`: not needed (no workflow change).
- `README.md`: update l.253–256 (Spanish). Cover `--run`, `--sources`, `--evidence`, the report sections and the `run-queued` skip.
- `docs/technical-discovery.md`: update. In the runbook (l.142), replace "the 52-row table is `v2-run-inspection`" with the report sections and the two inspection commands. In the rewording runbook (l.171), mention `pipeline statements --run R`. Note that `pipeline validate` uses the recorded minimums.
- `docs/risks-and-open-questions.md`: see the next section.
- `PROGRESS.md`, `feature_list.json`: evidence by the implementer.

## Owned risk entries (decisions)

- l.157, the 52-row table handoff: **settled** by S2. Delete it.
- l.275, a queued v2 run breaks `run-queued`: **fixed** (S8). The fix is small and Operator-facing, and the current behaviour turns every later `run-queued` call into exit 1. Delete the entry.
- l.272, `pipeline validate` uses the env: **fixed for the per-Constituency thresholds** (S9). They are already recorded, the fix is a CLI-only change, and a wrong env otherwise fails a sound run. Rewrite the entry as the narrower residual: the context-note thresholds (`VALIDATION_CONTEXT_NOTE_*`) of a v2 run and all legacy thresholds are still read from the env, because they are not recorded before Validation. Owner: none, or the next feature that touches the v2 report.
- l.148, the `main` document role: **reviewed, unchanged**. Inspection shows each Evidence's own Source Document and never the role, which nothing reads. Edit the entry to say so and drop "revisit with `v2-run-inspection`".

## Team-review defaults (recorded in the risks doc under "Open, for team review (`v2-run-inspection` defaults)")

- D1 `--run R` is added beside `--dataset-version` (exactly one of them).
- D2 `--sources`/`--evidence` refuse legacy versions instead of printing an empty table.
- D3 Excerpts are 120 characters, one line, with `…` when cut.
- D4 Party ids are used in the tables (as in today's CLI). `short_name` appears only in `parties:`. There is one source row per counting Party.
- D5 Evidence Constituencies print as `all` when they equal the Party's snapshot codes.
- D6 A `no stance` Position shows as one row with empty Evidence columns.
- D7 The one-line `constituencies:` summary stays as it is. The table carries the detail.
- D8 Section order is as in S1. Optional sections are printed only when non-empty.
- D9 `run-queued` skips queued v2 runs with a warning and exits 0. It does not mark them failed.
- D10 `pipeline validate` uses the recorded constituency settings. The context-note thresholds stay env-based (residual Low).
- D11 The unavailable `detail` JSON is not printed. `party_sides` and the `validation_settings` line show the same facts.

## Implementation Plan

1. Write `inspection.py` with unit tests (readers, `excerpt`, `recorded_constituency_settings`).
2. Add the `pipeline report` v2 sections, with exact-output tests (S1–S3).
3. Add `--run`, `--sources` and `--evidence`, with tests (S4–S6).
4. Add the `list_queued_run_ids` filter and the `run-queued` warning (S8). Make `pipeline validate` use the recorded settings (S9).
5. Check legacy byte-identity on scratch copies (S7). Update the docs and the risks entries.

## Implementation Tasks

- [ ] `inspection.py` and exports. Unit tests on a `v2_fake()` version, including the source-no-stance count equal to the report's value.
- [ ] `pipeline report` v2: `positions:` line and the `parties`, `categories`, `filtered statements`, `slice disagreements`, `source parties with no stance` and `constituencies` sections. Full-stdout test with 52 rows.
- [ ] S3 tests: no version, report without `constituencies`/`rewordings` (edit the JSON in a scratch test DB).
- [ ] `statements`/`positions`: `--run`, `--sources`, `--evidence`. Error tests for S6.
- [ ] `list_queued_run_ids(generation=)`. `run-queued` warning tests (alone, mixed, `--election`).
- [ ] `pipeline validate` with the recorded settings. Test with a different env (S9) and a legacy no-change test.
- [ ] S7 diff script on scratch DB copies against `98640af`.
- [ ] Update ARCHITECTURE, CONSTRAINTS, README, technical-discovery and the risks doc.

## Verification Plan

- `.venv/bin/pytest tests/test_v2_inspection.py tests/test_cli_pipeline_v2.py tests/test_pipeline_triggers.py -W error` must pass. Full suite via `CI=true ./init.sh` exits 0.
- S7: extract the base with `git archive 98640af | tar -x -C <scratch>/base`. For each command in S7, run it on a fresh copy of `data/ideology.db` with `PYTHONPATH=<scratch>/base/src .venv/bin/python -c 'from ideology_app.cli import main; main()' …` (first check that `ideology_app.__file__` points at the base) and with the branch's `.venv/bin/ideology`. Diff stdout, stderr and exit codes; all must be identical. Confirm the committed DB is unchanged (`git status`, `sha256`), at `0021`, and that `db check` says it is safe.
- Manual CLI walk on a scratch format-2 bundle and DB with `LLM_PROVIDER=fake` and the canned v2 fake: `run-v2` → `pipeline report --run 1` (52 rows) → `statements --run 1 --sources` → `positions --run 1 --evidence --party 1`. Then a hand-queued v2 run → `run-queued`.
- No E2E or browser step: CLI only, no API or UI change.

## Evidence To Capture

The test counts before and after. The scenario → test mapping. The S7 command list with "identical" against `98640af`. The committed DB hash unchanged and its `db check` result. An excerpt of the manual walk's report (headers and one row per section). Record any deviation from S1–S9 or D1–D11 in an "Implementation Notes" section of this spec.

## Validator Checklist

- [ ] Read-only: the new code paths only `SELECT` (`validate` writes only as before). No migration. No change to the v2 run, API or web.
- [ ] S1–S9 pass with exact outputs, and the 52 rows are in `CONSTITUENCIES` order.
- [ ] Legacy outputs for runs and Dataset Versions 1–5 are byte-identical to `98640af` on scratch copies.
- [ ] The risks entries at l.148, 157, 272 and 275 are updated as decided, and the D1–D11 team-review entry is added.
- [ ] Docs updated. `feature_list.json` and `PROGRESS.md` hold the evidence. `CI=true ./init.sh` exits 0. No real LLM call.

## Implementation Notes

- D3: an excerpt keeps the first 120 characters of the one-line text and appends `…` when cut (121 characters in all); text of at most 120 characters is unchanged.
- S9: the CLI uses the recorded settings only for a v2 run whose status is `validating` (the only state `validate_run` accepts). For a v2 run in any other state, no `Using the run's recorded constituency settings` line is printed and `validate_run` refuses it as before.
- S9 test: the `validating` v2 run is built by calling `execute_v2_run` with `pipeline.v2.run.validate_run` patched out (as `_validating_run` does for legacy runs); the run selected with `ConstituencySettings(2, 1)` and topic share 30, and the environment then says 5/5/50. The spec example's `VALIDATION_V2_MIN_STATEMENTS=3` cannot pass on the fixture (Constituency 28 has 2 valid Statements), so the test records 2.
- The legacy no-change test for `pipeline validate` lives in `tests/test_cli_pipeline.py` (next to `_validating_run`), not in `tests/test_cli_pipeline_v2.py`.
- `tests/v2_fixtures.py` gains `inspection_fake()`, `one_proposal_slices` (patched over `positions.position_slices`) and their data, to produce a filtered draft, a slice disagreement and source Parties with no stance on the small fixture bundle.
- S7: 31 commands compared against `98640af` on fresh copies of `data/ideology.db`; 29 are byte-identical (stdout, stderr, exit code). The 2 differences are the intentional D1 message for `pipeline statements` / `positions` with neither option (`Error: Missing option '--dataset-version'.` → `Error: pass exactly one of --dataset-version or --run`, exit 2 in both).
