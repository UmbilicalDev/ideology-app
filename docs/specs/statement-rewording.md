# Feature Implementation Spec: Operator rewording of a confusing Statement without changing its meaning

## Source Feature

- `id`: statement-rewording
- `area`: pipeline
- `depends_on`: constituency-selection-validation (`accepted`, PR #131 into `v2`)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest with the fake provider: rewording applied in a new Dataset Version, original kept, equivalence rejection fails the rewording, published versions untouched; `CI=true ./init.sh` passes)
- Branch: `feature/statement-rewording`, cut from `feature/constituency-selection-validation` (d5a49d0, PR #131, stacked on #129 and #130). The PR goes into `v2`, never `main`.
- Owns these entries in `docs/risks-and-open-questions.md`, "Constituency redesign": the rewording invariant (decided), the rejected-rewording decision (decided), the domain-model "rewording equivalence check (`statement-rewording` decides where it runs)", and the `CONSTRAINTS.md` handoff "Statements/selected text stored exactly as the provider returned" plus the reasons citing "AI output is never edited". All are addressed below. Downstream features: `dev-dataset` (seeds a reworded Statement through this path), `ingestion-guide` (documents the file), `methodology-v2` (the `/metodologia` sentence), `public-dataset-api-v2` (serves the final text only).

## Goal

The Operator can fix a confusing v2 Statement by committing a rewording file next to the bundle and running `ideology pipeline run-v2 DIR --reuse-from R`. The run replays every recorded drafting and positioning call, so the pool, the Party Positions and the Evidence come out identical. An LLM equivalence check then judges each rewording. An accepted rewording replaces the Statement's text in the new Dataset Version, and the AI text, the reason and the checker's explanation are stored with it. A rejected one leaves the AI text in place, does not fail the run, and shows up in the pipeline report. The new version is validated and published by the usual rule, and earlier versions are never touched.

## Non-Goals

- Rewording Context Notes, topics or Positions; editing any row in place; any `UPDATE` of a published version.
- API, OpenAPI, `packages/` or web changes. Today's API already serves `statements.text` (the final text). The `/metodologia` sentence belongs to `methodology-v2`. No UI, so no browser check.
- Legacy runs (`pipeline run`, Dataset Versions 1–5): they never read the file.
- An Operator override of a rejection, or a manual "force" flag. The only remedy is a different wording.
- Rich per-Statement rendering in `pipeline statements|positions` (`v2-run-inspection`). This feature adds only the report section below.
- Running the real 2026 rewording (`e2e-2026-constituencies`).

## Job Story

When a published v2 Statement is hard to understand,
I want to commit a better wording with a reason and re-run from the recorded calls,
so voters get clearer text in a new Dataset Version while the Positions, the Evidence and the audit trail stay exactly what the AI produced.

## Users And Permissions

- Operator: writes `data/elections/<slug>/statement-rewordings.toml` by hand, commits it, runs `pipeline run-v2`, and reads `pipeline report --run R`. Cannot change Positions or Evidence, and cannot publish without passing Validation.
- Voter: sees only the final text, with no marker.

## Decisions (R1–R12 are defaults for team review)

**R1 File.** `<bundle>/statement-rewordings.toml` (constant `REWORDINGS_NAME`), committed beside `election.toml` and `ingestion-ledger.json`. TOML because a person writes it with long Spanish text, like `election.toml`; the JSON ledger is machine-written. A missing file means no rewordings. Format:
```toml
format = 1

[[rewordings]]
ai_text = "texto exacto de la IA"
text = "nueva redacción"
reason = "por qué la original confunde"
```
Only the keys `format` (must be `1`) and `rewordings` are allowed at top level, and exactly `ai_text`, `text` and `reason` (all strings) in each entry. Further rules: `text` must be 1..300 characters with a non-space character (the `DraftText` bounds); `ai_text` must be 1..300 characters; `reason` must be 1..500 characters and not blank; `text != ai_text` (exact); two entries must not have the same `normalize_for_match(ai_text)`; at most `MAX_REWORDINGS = 100` entries. A bad file raises `RewordingFileError(InvalidInputError)` with `path:entry N: message`. `.toml` files are not subject to the bundle's unlisted-`.md` rule (`source_bundle.py`), so `read_bundle`, `data import`, `data check` and the ledger ignore the file.

**R2 Identity across runs: the AI text.** An entry matches the kept pool Statement (after `filter_pool`) whose `normalize_for_match(text)` equals `normalize_for_match(ai_text)`. Statement ids change with every version, and a hash is opaque in a PR diff. The source-Proposal set changes whenever any slice is redrafted. A replay reproduces AI texts byte for byte, and `filter_pool` leaves kept texts unique under `normalize_for_match`, so the match is unambiguous. Matching with the normaliser tolerates copy slips in case, punctuation and whitespace. What gets stored is always the pool's text, never the file's `ai_text`.

**R3 Where it applies: after `assign_positions`, before `select_constituencies`.** `proposal_positions` requests contain the Statement texts. Positions computed on the AI text therefore replay the same `request_hash`es, which gives identical Positions and Evidence with 0 new calls. Rewording before positioning would change every position request of that category and could change Positions. Selection uses Positions and topics, never text, so applying the rewording before it does not change availability or order. `filter_pool` (Context Note, duplicates) runs on AI text, as today.

**R4 Pre-checks (no LLM call), in pool order of the matched Statement, then unmatched entries in file order:**
- `not_found`: no kept Statement matches, either because the pool changed or a Statement was filtered.
- `duplicate`: `normalize_for_match(text)` equals the AI text of another kept Statement, or the `text` of an earlier matched entry that passed this pre-check. This keeps final texts unique, so check 1 stays green.
- Otherwise the entry gets one equivalence call: `applied` if the verdict is equivalent, else `rejected`.

None of these statuses fails the run. An `LLMError` during an equivalence call fails the run, as any LLM error does. Recorded calls stay reusable.

**R5 Equivalence prompt** (`pipeline/v2/prompts.py`, a `V2Prompt` added to `V2_PROMPTS`, so `V2_PROMPT_VERSIONS` gains a third key):
- Identity: task `statement_rewording_check`, version `v1`, `max_tokens` 1024.
- Schema: `RewordingVerdict(equivalent: bool, explanation: 1..500 characters with a non-space)`.
- Template fields: `{ai_text}` (the original), `{context_note}` (marked as context that will not change), and `{text}` (the new wording). All are passed through `one_line`. Builder: `rewording_request(ai_text, context_note, text)`.
- What the system text says (Spanish): the two wordings are equivalent only if a voter who agrees with one would agree with the other, with the same measure, direction, scope, conditions, figures and deadlines. The new wording must not add or remove proposals, and must not add value judgements or the names of parties or politicians. Simpler words, a different order, or spelling out a term or acronym count as equivalent. When in doubt, answer not equivalent, and explain in one or two sentences.
- What never reaches the prompt: the `reason` (it would argue for acceptance), and any Party, file or page.
- Pinning: fingerprint pinned in `tests/test_v2_prompts.py` with a request hash. The two existing pins stay unchanged.

**R6 Replay.** Each equivalence call goes through the run's `CheckpointProvider` and is recorded. Example:
- `--reuse-from R` (R = the published run) with a new file: drafts and positions are all reused; only one call per pre-checked entry is new.
- `--reuse-from` the rewording run itself: 0 non-reused calls and identical verdicts.
- An edited entry calls again only for itself.
- `plan_calls` adds `len(entries)` before checking `MAX_V2_CALLS_PER_RUN`.

**R7 Storage: new table, migration `0020`** (additive `CREATE TABLE`, no batch rebuild of `statements`, which is referenced with `ON DELETE CASCADE`):
- `statement_rewordings`, with columns:
  - `statement_id` (PK, FK `statements.id` `ON DELETE CASCADE`)
  - `ai_text VARCHAR(300) NOT NULL`
  - `reason VARCHAR(500) NOT NULL`
  - `explanation VARCHAR(500) NOT NULL`
- One CHECK: `ck_statement_rewordings_reason_not_blank` (`trim(reason) <> ''`).
- Model `StatementRewording`; `Statement.rewording` is a one-to-one relationship, optional and `passive_deletes`.
- `statements.text` holds the final text. Only `_finish_v2` inserts rows, in the Dataset Version's commit, and never updates them. Legacy versions never have rows.
- Committed DB: `data/ideology.db` is upgraded `0019 → 0020` (`db check` requires head). Every pre-existing table must be byte-identical (per-table hash), with `journal_mode` `delete`, and `db check` must say safe to commit.

**R8 Run report.** `statement_selection["rewordings"]` is written only when the file exists, so older reports are unchanged:
```
{version: "v2-rewording-1", file, sha256 (of the file bytes), prompt_version,
 entries: [{status, statement (1-based position or null), ai_text (pool text when matched, else the file's), text, reason, explanation (null without a call)}]}
```
This stores the AI text, the new text and the reason of rejected rewordings too, as the 2026-11-24 decision requires. `REPORT_VERSION` stays `v2-pool-1`.

**R9 Validation check `statement_rewording`**, appended last to `V2_CHECKS`. It is pure and turns "published only through Validation" into a check. `load_input` adds `StatementRow.ai_text`, `rewording_reason` (both `None` without a row) and `ValidationInput.applied_rewordings` (the `applied` report entries as plain tuples). The check reports:
- `statement S rewording keeps the AI text` when `ai_text == text`;
- `statement S is reworded without an accepted equivalence check` when there is a row but no applied entry with the same position, `ai_text`, `text` and `reason`;
- `applied rewording of statement S is not stored` for the reverse case.

Uniqueness (check 1) and `context_note` keep running on `statements.text` and the unchanged note. Legacy `CHECKS` is unchanged.

**R10 Context Note is not rewordable.** Notes are factual explanations that a separate filter and check already constrain. Opening them to hand edits would need a second equivalence rule. A follow-up can add it if `e2e-2026-constituencies` shows the need.

**R11 CLI picks the file up automatically.** No flag. The file is a bundle input like the ledger, and a flag would let two runs of the same bundle differ silently.
- `run-v2` reads it before queueing. A `RewordingFileError` gives exit 1, one `Error:` line, and nothing written. `_start_v2` reads it again; an error there sets the run `failed` with `rewording file invalid: …`.
- Before the run it prints `Rewordings: statement-rewordings.toml (N entries)`.
- After the run it prints `Rewordings: A applied, J rejected, D duplicate, F not found`, plus one `Warning: rewording of "<ai_text>": <status>[: explanation]` line on stderr per non-applied entry.
- `pipeline report --run R` (v2 only): adds a `rewordings: …` summary line (`none` without the key) and, when entries exist, a `rewordings:` table with columns `status, statement, ai_text, text, reason, explanation`. Legacy report output stays byte-identical.

**R12 API: final text only.** `/api/v1/dataset-versions/{id}` keeps `text` = `statements.text`, never exposes `ai_text`, reason or explanation, and adds no marker. A new CONSTRAINTS rule binds `public-dataset-api-v2` to the same.

## Acceptance Scenarios

1. **Applied.** Given a passed v2 run R (canned fake provider, Dataset Version V published) and a file rewording one Statement, when `run-v2 DIR --reuse-from R` runs, then:
   - a new run passes, publishes V′ and supersedes V;
   - the only non-reused calls are 1 `statement_rewording_check`;
   - V′ has the new text at the same position, a `statement_rewordings` row with the AI text, reason and explanation, and the report entry is `applied`;
   - every Position value and Evidence row (by Statement position and Party) equals V's;
   - V's rows are unchanged and only its status changed.
2. **Rejected.** Given the fake says not equivalent, then the run passes, the Statement keeps its AI text, there is no row, the report entry is `rejected` with the explanation, and the CLI warns.
3. **Duplicate / not found.** A `text` equal (normalised) to another Statement's AI text becomes `duplicate`, and an `ai_text` matching nothing becomes `not_found`. Neither makes a call and the run passes.
4. **Bad file.** Each R1 violation (missing key, extra key, `format = 2`, blank reason, text over 300, `text == ai_text`, repeated `ai_text`, TOML syntax) gives `run-v2` exit 1, an `Error:` line naming the file and entry, and no run row.
5. **Replay.** Running `--reuse-from` the scenario-1 run gives 0 non-reused calls, the same text, rows and report entries.
6. **Prompt hygiene.** The equivalence request contains the AI text, the note and the new text. It contains neither the reason nor any Party name, short name or file. Its fingerprint and the two existing v2 pins pass.
7. **Tamper.** On a stored version, each of these fails `statement_rewording`: deleting the row, changing `statements.text` with no row, or editing the report entry. The DB CHECK rejects a blank reason.
8. **Legacy unaffected.** A rewording file beside a format-1 bundle is never read. The legacy `pipeline report`, `checks`, `statements` and API for Dataset Versions 1–5 are byte-identical to d5a49d0.
9. **Migration.** `0020` upgrades and downgrades cleanly, `alembic check` shows no drift, and the offline PostgreSQL render has 1 `CREATE TABLE` and 1 CHECK, with no ALTER or DROP. The committed DB is upgraded with pre-existing tables identical.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/v2/run.py`: the `execute_v2_run` flow, `V2Pool`, `_finish_v2`, `plan_calls`, `pool_summary`.
- `src/ideology_app/pipeline/v2/pool.py`: `PoolDraft`, `filter_pool` (Context Note and `normalize_for_match` duplicates).
- `src/ideology_app/pipeline/v2/prompts.py`: `V2Prompt`, pinned v2 prompts, `one_line`.
- `pipeline/v2/gate.py`, `pipeline/checkpoint.py` (`request_hash`, hash-keyed reuse), `pipeline/runs.py` (`_check_resumable`, `validate_run`).
- `src/ideology_app/validation/{__init__,base,statement_uniqueness,context_note}.py`.
- `src/ideology_app/models.py` (`Statement`, `ModelGeneration`), `migrations/versions/0019_constituency_selection.py`.
- `src/ideology_app/cli.py` (`pipeline_run_v2`, `pipeline_report`, `pipeline_statements`), `source_bundle.py` (unlisted-file rule), `ingestion_ledger.py`, `llm/fake.py`, `api/queries.py`.
- `tests/test_v2_prompts.py`, `tests/test_validation_v2.py`, `tests/v2_fixtures.py`, `tests/pipeline_fixtures.py` (names only).
- `CONSTRAINTS.md`, `ARCHITECTURE.md` (Phase 4), `CONTEXT.md`, `docs/domain-model.md`, `docs/risks-and-open-questions.md`, `feature_list.json`.

### Existing Patterns To Follow

- Insert-only rows written in `_finish_v2`'s single commit. Reports stored in `statement_selection`.
- New v2 prompts get their own `V2Prompt`, a pinned fingerprint and a request hash. Every LLM call goes through `CheckpointProvider`.
- Pure checks over `ValidationInput`, loaded only in `load_input`, with one tampered-row test per check (`test_validation_constituencies.py`).
- Additive migrations with upgrade, downgrade, constraint and offline-render tests (`test_migrations.py`, 0019).
- Every new test module that touches the DB uses `offline_guard`. Only `FakeProvider` is allowed.

### Current Gaps

- No rewording reader, no equivalence prompt, no `statement_rewordings` table, no check. `V2_PROMPT_VERSIONS` has two keys (tests assert it).
- The committed DB has no v2 run, so the real path is exercised only on scratch DBs in tests.

## Technical Approach

New module `src/ideology_app/pipeline/v2/rewording.py`. It is pure apart from the injected provider, and depends on `prompts`, `pool`, `validation.evidence_quotes.normalize_for_match`, `generation.Usage` and `elections.InvalidInputError`. It contains:
- `REWORDINGS_NAME`, `MAX_REWORDINGS`, `REPORT_KEY_VERSION = "v2-rewording-1"`;
- `RewordingEntry(ai_text, text, reason)` and `RewordingFile(path, sha256, entries)`;
- `read_rewordings(bundle_dir) -> RewordingFile | None` (`tomllib`, R1);
- `AppliedRewording(text, reason, explanation)` and `RewordingOutcome(applied: Mapping[int, AppliedRewording] keyed by 0-based pool index, report: dict)`;
- `apply_rewordings(provider, statements: Sequence[PoolDraft], file, usage) -> RewordingOutcome` (R2, R4).

Changes elsewhere:
- In `run.py`, `_Started` carries the `RewordingFile | None` read in `_start_v2`. `execute_v2_run` calls `apply_rewordings` right after `assign_positions` (R3). `V2Pool` gets `rewordings: Mapping[int, AppliedRewording]` (default empty) and the report gets the `rewordings` key when a file exists.
- `_finish_v2` writes `text = applied.text if reworded else draft.text` and inserts `StatementRewording` rows.
- `plan_calls(phase4, rewordings=0)`.
- `validation/statement_rewording.py` implements the R9 check.
- `cli.py` prints the R11 lines. A new helper `rewording_summary(report)` in `run.py` is shared by `run-v2` and `report`.

## Expected File Changes

- `src/ideology_app/pipeline/v2/rewording.py`: create (R1, R2, R4, R8).
- `src/ideology_app/pipeline/v2/prompts.py`: modify (R5 prompt, schema, builder, `V2_PROMPTS`).
- `src/ideology_app/pipeline/v2/run.py`, `pipeline/v2/__init__.py`: modify (R3, R6, R8, exports).
- `src/ideology_app/models.py`: modify (`StatementRewording`, `Statement.rewording`).
- `src/ideology_app/migrations/versions/0020_statement_rewordings.py`: create (R7).
- `src/ideology_app/validation/statement_rewording.py`: create. `validation/base.py` and `validation/__init__.py`: modify (R9).
- `src/ideology_app/pipeline/v2/stored.py`: modify (`dataset_version_problems` reports `statement_rewordings` rows on a legacy version).
- `src/ideology_app/cli.py`: modify (R11).
- `data/ideology.db`: upgraded to `0020` (R7).
- Tests:
  - create `tests/test_v2_rewording.py` (reader, matching, pre-checks, apply, run scenarios 1–5);
  - modify `tests/test_v2_prompts.py`, `tests/test_validation_v2.py` (check list plus tamper cases), `tests/test_migrations.py` (HEAD `0020`, upgrade/downgrade/constraints/offline render), `tests/test_cli_pipeline_v2.py` (scenarios 1–4 via CLI, report section), `tests/test_public_api.py` (final text, no extra fields);
  - modify `tests/v2_fixtures.py` (a `statement_rewording_check` canned response, equivalent unless the new text contains a marker such as `CAMBIO`).

## Visual Design Impact

- UI involved: no. Design source: not applicable. No screens or states change, and no new design artifact is needed. The `/metodologia` text is owned by `methodology-v2`.

## Durable Documentation Impact

- `CONSTRAINTS.md`: update. This settles the handoff.
  - Pipeline rule "Statements are stored exactly as the provider returned them" becomes: "…except a v2 Statement whose Statement Rewording passed `statement_rewording_check` in that run: `statements.text` is the Operator's text and `statement_rewordings.ai_text` holds the provider's text exactly."
  - Reasons citing "AI output is never edited" (context notes, verified findings, `pipeline report` read-only) become "AI output is never edited (a Statement's text changes only through a recorded Statement Rewording in a new run)".
  - New Phase 4 rules:
    - `statement_rewordings` is insert-only, written only by `_finish_v2`;
    - rewordings come only from `statement-rewordings.toml` through `read_rewordings`, apply only after `assign_positions`, and need an `equivalent` verdict;
    - the `reason` never reaches a prompt;
    - bumping `statement_rewording_check` follows the v2 prompt rule;
    - readers serving Voters MUST serve only `statements.text`, with no `ai_text`, reason or marker.
- `ARCHITECTURE.md`: update Phase 4 with the data flow step, `rewording.py`, the table, the report key, the check, and the tests.
- `docs/domain-model.md`: update the v2 checks (`statement_rewording`, and the equivalence gate placement and statuses in "New gates"). Keep line 63, adding "stored with the new Dataset Version".
- `CONTEXT.md`: update only if wording drifts. It already matches.
- `docs/technical-discovery.md`: update with the file format and a runbook (edit file, commit, `run-v2 DIR --reuse-from R`, read the report).
- `docs/risks-and-open-questions.md`:
  - edit the CONSTRAINTS handoff bullet to mark the `statement-rewording` part done;
  - add a "Settled by default (`statement-rewording`, R1–R12)" entry for team review;
  - add an Open risk: equivalence false accepts and rejects of the LLM judge (measured in `e2e-2026-constituencies`).
- `AGENTS.md`: not needed (the invariant already states it).

## Implementation Plan

1. Prompt, schema and builder, with the pin test (R5).
2. Model, migration `0020` and its tests (R7). Upgrade the committed DB last, after the tests pass.
3. `rewording.py`: reader and `apply_rewordings`, with unit tests (R1, R2, R4, R8).
4. Wire into `execute_v2_run`, `_start_v2`, `plan_calls` and `_finish_v2` (R3, R6). Add run tests for scenarios 1, 2, 3 and 5.
5. Validation check and `load_input`, plus tamper tests (R9). Add the `stored.py` legacy guard.
6. CLI lines and the report section, plus CLI tests (R11). Add the API test (R12).
7. Legacy byte-identity on scratch copies (scenario 8). Update the docs.

## Implementation Tasks

- [ ] `RewordingVerdict`, `STATEMENT_REWORDING_CHECK`, `rewording_request`; extend `V2_PROMPTS`; pin fingerprint and request hash.
- [ ] `StatementRewording` model and migration `0020`; migration tests; `alembic check` clean.
- [ ] `read_rewordings` with every R1 error; `apply_rewordings` with R2 matching, R4 order and statuses, and the R8 report.
- [ ] `V2Pool.rewordings`, `_finish_v2` writes, `plan_calls` bound, `_start_v2` re-read and failure reason.
- [ ] `statement_rewording` check appended to `V2_CHECKS`; `load_input` fields; tamper tests.
- [ ] CLI pre-run line, summary and warnings; `pipeline report` line and table; CLI and API tests.
- [ ] Upgrade `data/ideology.db` to `0020` with nothing holding it; record hashes; `db check` safe.
- [ ] Doc updates listed above; `feature_list.json` evidence; `PROGRESS.md` session.

## Verification Plan

- `.venv/bin/pytest tests/test_v2_rewording.py tests/test_v2_prompts.py tests/test_validation_v2.py tests/test_migrations.py tests/test_cli_pipeline_v2.py tests/test_v2_runs.py tests/test_public_api.py` passes, with FakeProvider only and `offline_guard` in every new DB test module.
- `CI=true ./init.sh` exits 0. It runs non-blocking checks only and starts no server.
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` reports "Safe to commit: yes". Per-table hashes of the pre-existing tables are identical before and after the upgrade.
- Manual CLI walk on a scratch format-2 bundle and DB with the canned v2 fake: run-v2 → publish; add a file with one applied, one rejected and one not-found entry → `run-v2 --reuse-from 1` prints the lines from R11; `pipeline report --run 2` shows the table; replay `--reuse-from 2` makes 0 non-reused calls.
- Scenario 8 diff against d5a49d0 (via `git archive`) on scratch DB copies.
- No E2E or browser check: there is no browser-visible change, and API output is unchanged except for text values.

## Evidence To Capture

- pytest and Vitest counts against the baseline (pytest 2568), and the new tests per scenario.
- The migration `0020` offline render summary. DB SHA-256 before and after, the per-table identity, and `db check` output.
- The manual CLI walk output lines, and the call counts (new vs reused) for scenarios 1 and 5.
- The legacy byte-identity list.

## Validator Checklist

- [ ] Positions and Evidence of the reworded version equal the source version's, and only `statement_rewording_check` calls are new.
- [ ] Rejected, duplicate and not-found entries never fail the run and appear in the report with AI text, new text and reason.
- [ ] The prompt never contains the reason or any Party name, and the existing v2 pins are unchanged.
- [ ] No `UPDATE` of statements or published rows. `statement_rewordings` is insert-only and written only in `_finish_v2`.
- [ ] The `statement_rewording` check catches each tamper case. The API serves only the final text.
- [ ] The legacy path is byte-identical. The committed DB is upgraded safely.
- [ ] CONSTRAINTS, ARCHITECTURE, domain-model, technical-discovery and risks are updated as listed. `feature_list.json` and `PROGRESS.md` are updated.
- [ ] Scope: no UI, no context-note rewording, no override flag.

## Implementation Notes (2026-11-25, implementer)

- `rewording_summary(selection)` lives in `pipeline/v2/rewording.py` (exported from `pipeline.v2`) next to the report it reads, instead of `run.py`; `run-v2` and `pipeline report` share it as planned.
- R1: `format` is required; `rewordings` may be absent (no entries). Errors read `<path>: message` (file-level: TOML syntax, not UTF-8, unknown or missing top-level key, `format`, too many entries) or `<path>:entry N: message` (entry-level). A repeated `ai_text` is reported on the later entry (`same ai_text as entry M`).
- R4: "an earlier matched entry that passed this pre-check" is read literally: the earlier entry's text blocks a later one once it got an equivalence call, whatever its verdict, so the pre-checks never depend on a verdict. A new text equal (normalised) to its own AI text is not a duplicate.
- R5: `rewording_request` raises `ValueError` for a blank AI text, note or new text (never reached from the run: pool texts and notes are schema-bounded and the reader refuses a blank text).
- R9 limit: the check compares rows with `applied` report entries only, so it cannot see a changed `statements.text` of a Statement that has neither a row nor an entry (its AI text is only in the recorded calls). Scenario 7's "changing `statements.text` with no row" is tested on the reworded Statement (text changed and row deleted), plus five other tamper cases; the limit is recorded under R9 in `docs/risks-and-open-questions.md`.
- R11: the `Rewordings:` summary and the warnings follow the publish and `Constituencies:` lines and are printed only for a passed run (a failed run ends with the usual `Error:` line); the pool-size warning stays last. Every v2 `pipeline report` now has a `rewordings:` line (`none` without a file); legacy reports are unchanged.
- `_start_v2` re-reads the file after the gate and the Election check, before recording the run's documents; on an error the run is `failed` with `rewording file invalid: <path>…` and nothing else is written.
- `tests/test_feedback_store.py` and `tests/test_feedback_migrations.py` pin the shared head (`0020`) and now check that no `0021*` revision exists.
