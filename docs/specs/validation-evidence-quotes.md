# Feature Implementation Spec: Validation verifies Evidence quotes exist in the source

## Source Feature

- `id`: validation-evidence-quotes (GitHub issue #15)
- `area`: validation
- `depends_on`: pipeline-extract-positions (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (notes: check 2 in `docs/domain-model.md`; the match tolerance is decided here)

## Goal

After a Pipeline Run reaches `validating`, the same run runs Validation. This feature adds the Validation framework and its first check, `evidence_quotes` (domain check 2). The framework is a small registry of pure check functions. Their results and report entries are stored per run, and the run moves `validating` → `passed` when every registered check passes, or → `failed` otherwise. The check passes only when every non-`no stance` Party Position's quote is found, after normalisation, on the cited page of a Source Document that this run read for that Party. Each offending Party Position becomes a report entry. The Operator sees the result in `pipeline run` and lists the report with a new `pipeline checks` command.

`validation-party-coverage`, `validation-statement-separation` and `validation-questionnaire-shape` then plug in by adding one module and one registry entry each.

## Non-Goals

- No publishing. `passed` does not change the Dataset Version: it stays `candidate`. Publishing and superseding belong to `auto-publish-dataset-version`.
- No other checks: coverage, separation, count, uniqueness and topic spread are not part of this feature.
- No edit-distance or similarity fuzzy matching, and no new dependency (stdlib `unicodedata` only).
- No change to prompts, prompt versions, chunking, stored quotes, pages or page text. Normalisation happens only at match time.
- No full run report: provider, durations and costs belong to `pipeline-run-report`. No HTTP endpoint, no UI, and no change to `init.sh`.

## Job Story

When a Pipeline Run has produced a candidate Dataset Version,
I want every quoted Evidence checked automatically against the manifesto text,
so that invented or misplaced quotes never reach Voters, and I can see which positions failed.

## Users And Permissions

- Operator: CLI only. Can run Validation on a run left in `validating` and can read the report. Cannot edit results, positions or Evidence. Nothing has an update or delete path.
- Voter: not affected (nothing is published yet).

## Acceptance Scenarios

All tests use a temporary SQLite database, `FakeProvider` (or plain data for unit tests) and the autouse env/socket guard (`pipeline_fixtures.offline_guard`). No API key and no network.

### Scenario 1: Real quotes pass

Given `seed_election` and the default fake (every quote is a page's text, cited on that page)
When `execute_run` runs
Then the run is `passed` with `failure_reason` null, and its Dataset Version exists and stays `candidate`. One `validation_results` row exists (`check_name = "evidence_quotes"`, `passed = true`) with no report entries. `RunOutcome.status` is `passed` and `RunOutcome.failed_checks == ()`.

### Scenario 2: An invented quote fails the run with a report entry

Given `position_findings` returns, for Party 2, a quote that appears nowhere in its documents (e.g. `"Bajaremos el IVA de los libros al cero por ciento."`), and `party_positions` picks it for Statement 1
When `execute_run` runs
Then the run is `failed` with `failure_reason == "validation failed: evidence_quotes"`. The Dataset Version, its Statements and its Party Positions still exist unchanged (`candidate`). `validation_results` has `evidence_quotes` with `passed = false`, and exactly one entry with `statement_id` = Statement 1's id, `party_id = 2` and message `quote not found in source document 2`. Party 1's positions produce no entries.

### Scenario 3: Whitespace, accent, case and line-break differences pass

Given a page text `"Garantizaremos la educación\npública  y gratuita, también en la universi-\ndad."` and quotes such as `"garantizaremos la educacion publica y gratuita"`, `"Garantizaremos  la educación pública\ty gratuita"`, `"también en la universidad"`, a quote in NFD (decomposed accents), a quote with a NBSP, and a page with the ligature `ﬁ` against a quote with `fi`
When the check runs
Then each of these Party Positions passes. Only `normalize_for_match` makes them equal; the stored quote and page text are unchanged.

### Scenario 4: Quote on another page or across a page break

Given a document whose page 2 holds the quote's text
When the position cites page 2, the check passes. When it cites page 1, it fails with `quote not found on page 1 of source document D (found on page 2)`.
When a quote starts at the end of page 3 and continues at the start of page 4, citing page 3 passes and citing page 4 fails.

### Scenario 5: Locator integrity

Given a stance whose `evidence_page` exceeds the document's page count, or whose document is not a source document of that Party in this run (e.g. another Party's document), or whose `evidence_url` differs from the document's `source_url`, or whose quote has no letters or digits (e.g. `"…"`)
When the check runs
Then each gets one entry, with these messages: `page P does not exist in source document D (N pages)`, `source document D is not a source document of party P in this run`, `evidence URL does not match source document D`, `quote has no letters or digits`. A `no stance` position is never checked.

### Scenario 6: Registry behaviour

Given `validate_run(engine, run_id, checks=(passing_stub, failing_stub))` on a `validating` run
When it runs
Then both checks run in order (no short-circuit) and both result rows are stored, with the stub's entries in order. The run is `failed` with `validation failed: <failing_stub name>`. When the default `CHECKS` all pass, the run is `passed`.
When a check raises, the run is `failed` with `unexpected error: <ClassName>`, no result rows are stored, and the exception is re-raised. On `KeyboardInterrupt` the run is `failed` with `interrupted` and the interrupt is re-raised.
`validate_run` on a run that is not `validating` raises `InvalidInputError` (`pipeline run N is <status>, expected validating`) and changes nothing. On an unknown run it raises `NotFoundError`.

### Scenario 7: CLI

- `pipeline run` on Scenario 1 prints `Pipeline run 1: passed (dataset version 1, 30 statements, 60 party positions)` and exits 0.
- `pipeline run` on Scenario 2 commits, then prints `Error: pipeline run 1 failed: validation failed: evidence_quotes; see "ideology pipeline checks --run 1"` and exits 1.
- `pipeline checks --run 1` prints a tab-separated table with the header `check result statement party message`:
  - a passed check is one row `evidence_quotes passed` with empty cells;
  - a failed check is one row per entry, with `statement` = the Statement position and `party` = the Party id;
  - a run that has not been validated prints the header only;
  - an unknown run exits 1 with `Error: pipeline run N not found`.
- `pipeline validate --run N` validates a run left in `validating` (e.g. one created before this feature, or after a crash between commits). It prints `Pipeline run N: passed` or exits 1 with the same error as `pipeline run`. On a run in any other state it exits 1. It needs no LLM provider or API key.
- `pipeline list` shows `passed` / `failed` in its `status` column (no new columns).

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/runs.py`: `execute_run` commits `running`, then `_finish` writes the Dataset Version and sets `validating` in one commit. `RunOutcome`, `list_runs`, `list_positions`, error handling (`interrupted`, `unexpected error: <Class>`).
- `src/ideology_app/models.py`: `PipelineRunStatus` already has `passed`. `PipelineRunSourceDocument` (run → documents, with role). `PartyPosition` Evidence columns and CHECKs. `SourceDocumentPage`. `_enum`, `_utcnow`, the naming convention.
- `src/ideology_app/cli.py`: the `pipeline` group, `_print_rows`, `requires_db`, `_one_line`, and how a failed run is reported after its commit.
- `tests/pipeline_fixtures.py`: `seed_election`, `PAGES`, `add_parsed_document`, `findings_response` (quote = page text, page = page number), `chunk_pages`, `candidate_lines`, `offline_guard`.
- `tests/test_pipeline_runs.py`, `tests/test_cli_pipeline.py`, `tests/test_migrations.py`: assertions on `VALIDATING` and the `validating` CLI text, which this feature changes.
- `ARCHITECTURE.md`, `CONSTRAINTS.md` (page text stored as extracted; normalise at match time; Evidence immutable), `docs/domain-model.md` (lifecycle and checks), `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`, `docs/specs/pipeline-extract-positions.md`.

### Existing Patterns To Follow

- Services take an `Engine`, commit through `session_scope`, and return frozen dataclasses of plain data. Errors are `NotFoundError` / `InvalidInputError` from `elections`.
- Unexpected exceptions set the run `failed` with `unexpected error: <ClassName>` and re-raise. Ctrl-C sets `interrupted` and re-raises.
- The CLI commits a failed run first, then raises `click.ClickException`. Lists are tab-separated via `_print_rows`.
- Migrations are autogenerated, then reviewed by hand. Enums are non-native. `tests/test_migrations.py` covers upgrade, downgrade, drift and the PostgreSQL offline render.

### Current Gaps

- Nothing runs Validation, and nothing stores a Validation report. `passed` is never set.
- A run left in `validating` has no way forward.

## Technical Approach

**Package `src/ideology_app/validation/`.** Dependency direction: `models` → `validation` → `pipeline.runs` → `cli`. `validation` never imports `pipeline`, `llm` or `pdf_text`.

- `base.py` defines frozen dataclasses:
  - `ValidationInput(statements, positions, party_ids, documents)`, where:
    - `statements`: `StatementRow(id, position, text, topic)` in position order;
    - `positions`: `PositionRow(statement_id, statement_position, party_id, value, document_id, quote, page, url)` ordered by Statement position, then Party id;
    - `documents`: `dict[int, RunDocument(party_id, role, source_url, pages: dict[int, str])]` for every row of `pipeline_run_source_documents`.
  - `ReportEntry(message, statement_id=None, party_id=None)`; `message` is at most 500 characters.
  - `Check(name, run: Callable[[ValidationInput], list[ReportEntry]])`; `name` is a stable slug of at most 50 characters.
  - `CheckResult(name, entries)` with `passed = not entries`.
  - `load_input(session, run) -> ValidationInput`, which reads the run's Dataset Version and documents.
- Checks are pure functions of `ValidationInput`: no database, no LLM, no network, no clock. A later check that needs configuration (e.g. the coverage threshold) adds a field to `ValidationInput`, filled in `load_input`. Adding a field is not a redesign.
- `__init__.py` holds `CHECKS: tuple[Check, ...] = (EVIDENCE_QUOTES,)` and `run_checks(data, checks=CHECKS) -> list[CheckResult]`. `run_checks` runs every check in registry order, with no short-circuit. To add a check, write `validation/<name>.py` exporting a `Check` and append it to `CHECKS`.

**Check `evidence_quotes`** (`validation/evidence_quotes.py`):

- `normalize_for_match(text: str) -> str`: apply NFKD, then `casefold()`, then NFKD again. Then keep only characters where `ch.isalnum()` and that are not `unicodedata.combining`.
  - Accents (`ó`→`o`, `ñ`→`n`), case, ligatures (`ﬁ`→`fi`), NBSP and soft hyphens all fold or drop.
  - All whitespace and punctuation, including hyphens, are dropped. So pypdf spacing quirks and words hyphenated across line breaks still match.
  - Word order and every letter and digit must still match exactly.
- `quote_starts_on(norm_quote, norm_pages, page) -> bool`: true when `norm_quote` occurs in `norm_pages[page] + norm_pages.get(page + 1, "")` at an index below `len(norm_pages[page])`. That is, the quote starts on the cited page and may run onto the next one.
- For each position with a non-null `value`, in input order, record the first failing rule as one entry with the position's `statement_id` and `party_id`, then move on:
  1. The document is in `documents` with the same `party_id`. Otherwise: `source document D is not a source document of party P in this run`.
  2. `url` equals the document's `source_url`. Both are null for uploads. Otherwise: `evidence URL does not match source document D`.
  3. `page` is a key of `pages`. Otherwise: `page P does not exist in source document D (N pages)`.
  4. The normalised quote is non-empty. Otherwise: `quote has no letters or digits`.
  5. `quote_starts_on` the cited page. Otherwise, search the other pages in order. If the quote is found: `quote not found on page P of source document D (found on page Q)`. If not: `quote not found in source document D`.
- Normalise each document's pages at most once per check, lazily.

**Tolerance, settled:** normalisation only. A match is an exact substring of the normalised text. There is no edit distance and no minimum quote length. The domain wording "found in the Source Document's text" is narrowed to "starts on the cited page". The page is shown to Voters as the locator, and AI output can't be corrected by hand, so a wrong page must fail the run, not be published. The report says where the quote was found.

**Storage (migration `0006_validation_results.py`):**

- `ValidationResult` (`validation_results`): `id`, `pipeline_run_id` (FK cascade + index), `check_name` String(50) (`check` is an SQL reserved word), `passed` Boolean, `created_at`. Unique on `pipeline_run_id` + `check_name`. Relationship `entries` ordered by id.
- `ValidationReportEntry` (`validation_report_entries`): `id`, `validation_result_id` (FK cascade + index), `statement_id` (nullable FK `statements` cascade), `party_id` (nullable FK `parties` cascade), `message` String(500).
- `PipelineRun.validation_results` is ordered by id, with `passive_deletes`.
- These rows are insert-only and are written in the same commit as the status change.

**Service: `runs.validate_run(engine, run_id, checks=CHECKS) -> RunOutcome`.**

- In one `session_scope`:
  1. Load the run. Unknown → `NotFoundError`. Not `validating` → `InvalidInputError`.
  2. `load_input`, then `run_checks`, then insert one `ValidationResult` per check with its entries.
  3. Set `passed`, or set `failed` with `failure_reason = ("validation failed: " + ", ".join(failed names))[:500]`.
- If a check raises, or Ctrl-C arrives, roll back. Then, in a new session, set `failed` with `unexpected error: <ClassName>` / `interrupted` and re-raise.
- `RunOutcome` gains `failed_checks: tuple[str, ...] = ()`. `statement_count` and `position_count` are read from the Dataset Version.
- `execute_run` calls `validate_run(engine, run_id)` after `_finish` returns `validating`. The call sits outside its existing `try`, so validation errors are not handled twice. `execute_run` returns the validation outcome.
- Export `validate_run` from `pipeline/__init__.py`. Add `list_validation_results(session, run_id)` (`NotFoundError` for an unknown run) for the CLI.
- Docstrings: the lifecycle becomes `queued → running → validating → passed | failed`.

**CLI:** add `pipeline validate --run` and `pipeline checks --run` as in Scenario 7. When `outcome.failed_checks` is non-empty, `pipeline run` and `pipeline validate` append `; see "ideology pipeline checks --run N"`. Entry messages are printed through `_one_line`.

## Expected File Changes

- `src/ideology_app/validation/__init__.py`, `base.py`, `evidence_quotes.py`: create.
- `src/ideology_app/models.py`: modify. Add `ValidationResult`, `ValidationReportEntry` and the `PipelineRun.validation_results` relationship.
- `src/ideology_app/migrations/versions/0006_validation_results.py`: create. Autogenerate it and review it by hand. Renumber it if another branch lands `0006` first.
- `src/ideology_app/pipeline/runs.py`, `pipeline/__init__.py`: modify. Add `validate_run`, `list_validation_results` and `RunOutcome.failed_checks`, and wire `execute_run`.
- `src/ideology_app/cli.py`: modify. Add `pipeline validate` and `pipeline checks`, and the new run message and hint.
- `tests/test_validation_evidence_quotes.py`: create. Unit tests on plain `ValidationInput`: Scenarios 3–5 and `normalize_for_match`.
- `tests/test_validation_runs.py`: create. Scenarios 1, 2 and 6 through `execute_run` / `validate_run`.
- `tests/test_cli_pipeline.py`: modify. Scenario 7.
- `tests/test_pipeline_runs.py`: modify. Expect `PASSED` where the default fakes now pass, and `FAILED` + `validation failed: evidence_quotes` where a test uses a quote that isn't on the page (e.g. `test_quotes_are_stored_exactly_as_returned`). Keep each test's original intent.
- `tests/test_migrations.py`: modify. Cover `0006` upgrade, downgrade and drift.
- `tests/pipeline_fixtures.py`: modify only if a helper is needed (e.g. seeding a `validating` run).
- Docs: see below.

## Visual Design Impact

- UI involved: no. CLI and pipeline only, so browser validation is exempt (AGENTS.md).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Add a **Validation** section. It must cover:
    - the package and its dependency direction;
    - `ValidationInput` / `Check` / `ReportEntry` / `CheckResult`, `CHECKS` and `run_checks` (all checks run, in order);
    - checks are pure;
    - how to add a check: a module, one `CHECKS` entry, and a new `ValidationInput` field if needed;
    - storage, and the `validate_run` transition `validating → passed | failed`;
    - the `evidence_quotes` rules and messages;
    - a note that `auto-publish-dataset-version` hooks into `validate_run`'s `passed` path.
  - Data Layer: add the two models and `0006`. A `failed` run can now have a `candidate` Dataset Version.
  - Pipeline: replace "The run stops at `validating`…" and fix "this feature sets all but `passed`".
  - Runtime Surface: add `pipeline validate`, `pipeline checks` and the new messages.
- `CONSTRAINTS.md`: add a **Validation** section.
  - Checks MUST be pure functions of `ValidationInput` (no DB, LLM, network or clock).
  - Validation results and entries MUST be written only by `validate_run`, together with the run's status change, and never updated or deleted.
  - Quote matching MUST go through `validation.evidence_quotes.normalize_for_match`.
  - Only `auto-publish-dataset-version` may change a Dataset Version's status.
- `docs/domain-model.md`: update check 2 to "…quote, normalised, starts on the cited page (or runs onto the next) of a Source Document the run read for that Party". Add to the Pipeline Run lifecycle: a failed-Validation run keeps its `candidate` Dataset Version, which is never published.
- `docs/risks-and-open-questions.md`: update in the same change.
  - Implementation-Time Questions: delete the "fuzzy-match tolerance…" entry, because it is settled by the rules above. If a settled note is kept, it must be short and must name normalisation only and the cited-page rule.
  - Risks: add **Quote matching unverified on real manifestos (`e2e-real-2023-election`)**. It covers:
    - The cited-page rule fails the whole run on any page slip.
    - Extraction errors (wrong characters, column interleaving) fail real quotes.
    - Quotes with `…` or `[...]` elisions fail.
    - Very short quotes (e.g. "no") can match by chance.
    - If the failure rate is high, relax to document-level matching or tune the prompts. Don't edit output.
  - Risks: in "Runs stuck in `running`", add that a run left in `validating` is now recoverable with `ideology pipeline validate --run N`.
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`: not needed.

## Implementation Plan

1. Write the `validation` package and `normalize_for_match`, and unit-test them on plain data (Scenarios 3–5).
2. Add the models and migration `0006`, and extend the migration tests.
3. Add `validate_run` / `list_validation_results` and wire `execute_run` (Scenarios 1, 2, 6). Update the existing run tests.
4. Add the CLI commands and messages (Scenario 7). Update the CLI tests.
5. Update the docs, run `CI=true ./init.sh`, and record evidence.

## Implementation Tasks

- [ ] `validation/base.py`: dataclasses and `load_input`. `validation/__init__.py`: `CHECKS` and `run_checks`.
- [ ] `validation/evidence_quotes.py`: `normalize_for_match`, `quote_starts_on`, and the `EVIDENCE_QUOTES` check with the exact messages above.
- [ ] Models, `0006` (reviewed by hand; `alembic check` reports no drift), and migration tests.
- [ ] `runs.validate_run`, `list_validation_results`, `RunOutcome.failed_checks`, the `execute_run` call, and exports.
- [ ] CLI `pipeline validate`, `pipeline checks`, the run message and the hint.
- [ ] Tests for Scenarios 1–7. Fix the existing `VALIDATING` / `validating` expectations.
- [ ] Update `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/domain-model.md` and `docs/risks-and-open-questions.md`.

## Verification Plan

- `CI=true ./init.sh` exits 0: pytest and `node --test` pass, with no warnings (`filterwarnings = ["error"]`).
- Run `.venv/bin/python -m pytest tests/test_validation_evidence_quotes.py tests/test_validation_runs.py tests/test_cli_pipeline.py tests/test_pipeline_runs.py -q` with `ANTHROPIC_API_KEY` unset; it passes.
- `alembic history` shows `0005 -> 0006 (head)`. `alembic check` reports no drift. `downgrade 0005` drops only the two new tables.
- `grep -rn "import" src/ideology_app/validation/` shows no `pipeline`, `llm`, `anthropic` or `pdf_text` imports.
- Offline CLI smoke in a scratch directory outside the repo, with `cli._provider` patched to the fixture fake: a run that passes, a run with an invented quote that fails, `pipeline checks` output, and `pipeline validate` on a run seeded as `validating`.
- No E2E harness exists. Browser validation is exempt (no browser-visible change).

## Evidence To Capture

- In `feature_list.json` → `validation-evidence-quotes.evidence` and a `PROGRESS.md` session: the test counts, the tests mapped to Scenarios 1–7, the alembic output, the smoke results, and any deviations from this spec.

## Open Questions (non-blocking)

- `validation-questionnaire-shape` is also dependency-ready. If it is built in parallel, whichever branch merges second rebases onto this framework: it reuses `CHECKS`, `validation_results` and `validate_run`, and renumbers its migration if it has one.

## Validator Checklist

- [ ] Scope: no publishing; Dataset Version status unchanged; no other checks; no prompt, stored-quote or page-text changes; no new dependency.
- [ ] Scenarios 1–7 pass with `FakeProvider` only, with no key and no network.
- [ ] The registry shape and the "add a check" recipe are documented in `ARCHITECTURE.md`. The rules are in `CONSTRAINTS.md`.
- [ ] `docs/risks-and-open-questions.md` and `docs/domain-model.md` were edited as listed.
- [ ] Migration reviewed by hand; no drift; downgrade is clean.
- [ ] `feature_list.json` and `PROGRESS.md` are updated with evidence. No `docs/validations/` directory exists.
