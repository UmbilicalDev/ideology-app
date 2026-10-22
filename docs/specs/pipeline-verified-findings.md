# Feature Implementation Spec: Discard unverifiable quotes before they become Evidence; coverage threshold 50%

## Source Feature

- `id`: pipeline-verified-findings
- `area`: pipeline
- `depends_on`: none
- `status`: `not_started` at planning time
- `source`: `feature_list.json`

## Goal

Real run 2 on `origin/feature/e2e-real-2023-election-main` (168 calls, pool 55, 26 selected) failed on two checks:

- `evidence_quotes`: two model copy slips, statement 8/EAJ-PNV and statement 24/BNG (e.g. "las sustituiremos" for "la sustituiremos");
- `party_coverage` at 60 %: PP 50, PSOE 73, VOX 58, SUMAR 65, ERC 73, JUNTS 58, EH Bildu 50, EAJ-PNV 50, BNG 58 %.

After this feature:

1. `extract_positions` checks every `position_findings` finding against its cited page, in code. It uses exactly the `evidence_quotes` matcher (shared code, not a copy). A finding that fails is never used as Evidence: a reduce choice that cites it becomes `no stance`. Quotes are never edited or repaired.
2. The discards are recorded on the run (`pipeline_runs.statement_selection["findings"]`, no migration). `pipeline report` shows them: a count per Party, and each discard with its Statement and page.
3. `DEFAULT_MIN_PARTY_COVERAGE_PERCENT` is 50 (was 60), a user decision of 2026-10-22. The selection and Validation follow it, and so does `/metodologia`.
4. No request changes at all. `pipeline run --election 1 --reuse-from 2` on the e2e branch replays all 168 recorded calls and makes zero LLM calls.

`evidence_quotes` stays in Validation as the final guard.

## Non-Goals

- No change to any prompt, template, schema, `max_tokens`, `PROMPT_VERSIONS`, chunk text, candidate line format or the order of calls. No change to `request_hash` or the checkpoint reuse keys.
- No quote repair, fuzzy matching, document-level matching or retry call. No new Validation check, and no change to `evidence_quotes` rules or messages.
- No migration, no change to `data/ideology.db`, no `/api/v1` change, and no selection algorithm change (`SELECTION_VERSION` stays v1).
- No real LLM run: the actual replay belongs to `e2e-real-2023-election`. Tests never call a real LLM or the `claude` CLI, and use no network.
- The methodology copy changes only 60 → 50. Mentioning the discard step is an open question (below).

## Job Story

When the model copies a manifesto quote with a small slip,
I want that finding dropped in code before it can become Evidence, with the drop recorded,
so that one slip costs one stance instead of failing a multi-hour run, and no quote is ever edited.

## Users And Permissions

- Operator (CLI): `pipeline run [--reuse-from R]`. `pipeline report --run N` gets one new line and one new table (read-only).
- Voter: sees only `/metodologia`, which changes from 60 % to 50 % in two places.

## The Reuse Conflict And Its Resolution (user decisions 2 and 3)

`positions_request` builds the `party_positions` prompt from **all** of a Party's findings, numbered `C1..CK`, and its schema bounds `evidence` to `1..K`. `request_hash` covers the prompt and the schema. The checkpoint reuses a stored output only on an identical hash.

Dropping a finding from that list ("never become candidates", taken literally) would change the prompt and K for every Party with at least one unverifiable finding. The replay would miss those reduce calls and call the provider again. That breaks decision 3, which requires zero calls.

**Resolution: verify before the reduce, but filter the reduce's output.**

- Every finding is verified right after its `position_findings` call returns. The verdict is attached to the finding.
- The `party_positions` request still lists every finding, unverifiable ones included, with the same numbers and the same K, so it is byte-identical to today.
- A reduce choice whose `evidence` points to an unverifiable finding becomes `no stance` (`PositionResult(n, None)`) and is recorded as cleared.
- A Party whose findings are all unverifiable still gets its reduce call. The call count formula is unchanged.

So an unverifiable finding never becomes Evidence, a Party Position, or input to the coverage selection.

**Trade-off, accepted for decision 3:** the model still sees the slipped candidate. If it picks the slip for Statement n while a verified candidate for n exists, n becomes `no stance` rather than the verified alternative. A deterministic fallback to another candidate is rejected because code would then choose Evidence the model did not choose (see Open Questions).

## Acceptance Scenarios

1. **Slipped quote dropped and reported (FakeProvider).**
   - Given a Party whose chunk has page 1 "…la sustituiremos…", and a `position_findings` fake that returns one finding with "las sustituiremos" (page 1) plus a verified finding for another Statement, and a reduce that cites both.
   - When `extract_positions` runs, then the slipped Statement's result is `no stance` with no Evidence, and the verified one keeps value, quote, page, document and URL exactly as returned.
   - At run level (`execute_run`), `statement_selection["findings"]` records the discard (party, document, page, statement, value, reason `not_found`, `cleared` = [n], quote verbatim), and the run's stored Party Positions contain no slipped quote.
2. **Other reasons.** The same handling applies to:
   - a quote that starts on another page of the document (reason `other_page`, `found_on` set);
   - a quote with no letters or digits (`no_letters`);
   - a cited page that is not among its chunk's pages, even when the quote is on that page elsewhere in the document (`page_not_in_chunk`).

   A quote that starts on its page and runs onto the next page is kept, as in Validation. Case, accent, ligature, whitespace and punctuation differences are kept.
3. **Same matcher code.**
   - `positions.py` imports the shared function from `ideology_app.validation.evidence_quotes`; there is no second normaliser or matcher. An identity assertion checks this.
   - A parametrised table of (pages, page, quote) cases gives the same keep/discard verdict through `extract_positions` and through `check_evidence_quotes`.
   - The existing `tests/test_validation_evidence_quotes.py` passes unedited, so its messages are byte-identical.
4. **Requests unchanged (pin).**
   - `PROMPT_VERSIONS == {"statement_candidates":"v1","generate_statements":"v4","position_findings":"v3","party_positions":"v2"}`.
   - `git diff main -- src/ideology_app/pipeline/prompts.py` is empty, and the `CANDIDATE_REQUEST_HASH` / fingerprint pins pass unedited.
   - New literals `FINDINGS_REQUEST_HASH` and `POSITIONS_REQUEST_HASH`: `request_hash("fake","fake-model", …)` of `findings_request` and of `positions_request` on a fixed input. Compute them from the unmodified code (main `cf062e4`) **before** any edit, and paste them as literals.
   - In scenario 1 the recorded `party_positions` request still lists the slipped candidate line (`candidate_lines` shows K including it).
5. **Zero-call replay.**
   - Given run A (FakeProvider, with one slipped finding) finished with a Dataset Version.
   - When run B is queued with `resumed_from_run_id=A, allow_finished_source=True` and executed with a provider that raises on any `generate`, then B records the same number of calls, all `reused`. Its sequence of request hashes equals A's, the provider is never called, and the outcome, the selection and the `findings` record equal A's.
   - The call count formula `chunks + 1 + chunks + Parties with findings` is unchanged (existing plan/usage tests pass).
6. **Selection sees verified findings only.** In scenario 1 at run level, `statement_selection["pool"][n-1]["values"]` has `None` for that Party at the cleared Statement, and `parties[].pool_stances` excludes it.
7. **Threshold 50.**
   - `DEFAULT_MIN_PARTY_COVERAGE_PERCENT == 50`, and `ValidationSettings().min_party_coverage_percent == 50`.
   - With no env value, the selection reaches `coverage_met` at 50 %, and Validation passes 15/30 and fails 14/30.
   - An explicit 60 or 70 keeps its meaning in the tests.
8. **Report.**
   - `pipeline report --run N` prints `findings_check: v1, checked F, discarded D, cleared C; party 1 0/20; …; party 9 2/30 cleared 1`. Every Party in the run appears, in id order.
   - When D > 0 it also prints a `discarded findings:` table with columns party, document, page, statement, position, value, reason, cleared, quote.
   - A run without the key (older runs, or failed before `_finish`) prints `findings_check: not recorded` and no table.
9. **Methodology copy.** `/metodologia` shows "50 %" in both places and "60 %" in neither. This is checked in a real browser at 375 px and at desktop width, with a clean console and no failed requests.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/positions.py`: `extract_positions`, `_Candidate`, `_reduce`, and `positions_request`, which builds the prompt from every candidate.
- `src/ideology_app/pipeline/checkpoint.py`: `request_hash` covers provider, model, task, system, prompt, schema JSON and `max_tokens`. Reuse is a FIFO per hash.
- `src/ideology_app/validation/evidence_quotes.py`: `normalize_for_match`, `quote_starts_on`, and the rules 3–5 in `_first_failure`.
- `src/ideology_app/pipeline/generation.py`: `Chunk(party_id, document_id, text)` has no page list. `DocumentPages.pages` is already loaded by `runs._start`.
- `src/ideology_app/pipeline/runs.py`: `execute_run` and `_finish`, where `statement_selection` = selection report + `agenda`.
- `src/ideology_app/pipeline/selection.py` (it already imports `ideology_app.validation`), `reports.py`, and `cli.py` (`_selection_lines`, `pipeline_report`).
- `src/ideology_app/config.py:41`; `apps/web/src/features/methodology/MethodologyPage.tsx:114,129` and its test (`:86,:175`).
- Tests: `tests/pipeline_fixtures.py` (`findings_response` quotes real page text), `test_pipeline_positions.py`, `test_pipeline_runs.py:573` (`test_quotes_are_stored_exactly_as_returned`), `test_validation_runs.py` (`_invented_for_party2`), `test_cli_pipeline.py` (`_invented_for_party2`, `_all_invented`, the 60 % messages), `test_pipeline_selection.py:368`, `test_cli_pipeline_report.py` (it uses 50 as its "non-default" value), and `test_pipeline_prompts.py`.
- Docs: `ARCHITECTURE.md` (lines 36, 50, 55, 64, 70, 141), `CONSTRAINTS.md:57,64`, `docs/domain-model.md:43`, `docs/risks-and-open-questions.md`, and the specs listed in the task.

### Offline Projection On Run 2 (planner, read-only)

I copied the e2e branch's `data/ideology.db` into a scratchpad outside the repo and replayed run 2 on it with the current code, with `_reduce` wrapped to emulate the output filter, and a provider that raises on any call:

- 0 provider calls (all 168 reused);
- 312 findings: 3 unverifiable (EAJ-PNV 1 of 19, BNG 2 of 30), 0 citing a page outside their chunk;
- 2 reduce choices cleared (pool 13 for EAJ-PNV, pool 50 for BNG);
- 26 selected, `coverage_met`, run **passed** at 50 %;
- worst Parties at 13/26 = 50 % (PP, EH Bildu, EAJ-PNV).

Without the filter, at 50 % only `evidence_quotes` fails. This is a projection only; the real replay belongs to `e2e-real-2023-election`. Because the margin is zero, losing one more stance for PP, EH Bildu or EAJ-PNV would fail the run.

### Existing Patterns To Follow

- The `Usage` accumulator passed into `extract_positions` is the model for the new `FindingCheck` recorder.
- `CONSTRAINTS.md:64`: all quote matching goes through `evidence_quotes.normalize_for_match`. The dependency `pipeline → validation` already exists in `selection.py`, and `validation` never imports `pipeline`.
- `statement_selection` is written only by `_finish` (`CONSTRAINTS.md:57`); the agenda is already stored there.

## Technical Approach

1. **Shared matcher** (`validation/evidence_quotes.py`):
   - Add `normalize_pages(pages: Iterable[tuple[int, str]]) -> dict[int, str]`.
   - Add a frozen `QuoteMiss(reason: str, found_on: int | None = None)` with reasons `no_letters`, `other_page`, `not_found`.
   - Add `find_quote_miss(quote: str, norm_pages: Mapping[int, str], page: int) -> QuoteMiss | None`, with precondition `page in norm_pages`. It applies rules 4–5 exactly as today: normalise the quote, then `quote_starts_on`, then the first other page in page order.
   - Refactor `_first_failure` to call it and map the miss to the **unchanged** messages.
   - Export the new names from `validation/__init__.py`.
2. **Chunk pages** (`generation.py`): add `pages: tuple[int, ...] = ()` to `Chunk`, filled by `build_document_chunks` with the page numbers of its pieces, in order and without duplicates. A long page cut into slices appears in each chunk that holds a slice. `text` is unchanged, so every request is unchanged.
3. **Extraction** (`positions.py`):
   - `_Candidate` gains `miss: str | None`, the reason, or `None` when verified.
   - In `extract_positions`, normalise each document's pages lazily, once per call, from `DocumentPages.pages`; there are no DB reads.
   - For each finding: if `finding.page not in chunk.pages`, the reason is `page_not_in_chunk`; else `find_quote_miss`. The finding is appended to `candidates` either way, in the same order.
   - `_reduce` keeps the repeated-Statement `GenerationError` check over all choices. Then a choice citing a candidate with `miss` becomes `PositionResult(statement_number, None)` and is recorded as cleared on that candidate.
   - New optional keyword `findings: FindingCheck | None = None`. `FindingCheck` is a recorder like `Usage`: checked count per Party (every Party in `party_ids`, 0 when none) and `DiscardedFinding(party_id, document_id, statement, value, page, quote, reason, found_on, cleared)`.
   - `FindingCheck.report()` returns `{"version": "v1", "checked": F, "discarded": D, "cleared": C, "parties": [{"party_id", "findings", "discarded", "cleared"}...], "items": [...]}`. Items are in call order, and the quote is verbatim.
   - Update the module docstring: quotes are verified here and never changed, and the request lists every finding so recorded calls stay reusable.
4. **Run** (`runs.execute_run`): create a `FindingCheck`, pass it in, and store `selection={**selection.report, "agenda": …, "findings": check.report()}`. Selection receives the filtered positions, so it sees verified findings only. Validation is unchanged.
5. **Report** (`cli.py`):
   - Add a `_findings_line(selection)` printed after `selection_coverage`.
   - Add a `FINDINGS_HEADER` table printed after `statement pool:` when `discarded > 0`.
   - `position` is the questionnaire position of the finding's pool Statement, from `selection["pool"]`, or empty when not selected.
   - `cleared` lists the pool numbers, comma-separated.
   - `reason` is shown as `other_page (page Q)` when `found_on` is set.
   - The quote goes through `_one_line`.
   - `reports.py` needs no change, because the data lives in `statement_selection`.
6. **Threshold:** `config.DEFAULT_MIN_PARTY_COVERAGE_PERCENT = 50` and its docstring "(default 50)". Update the methodology copy at lines 114 and 129, and its test.

## Expected File Changes

- `src/ideology_app/validation/evidence_quotes.py`, `validation/__init__.py`: modify (shared matcher; messages unchanged).
- `src/ideology_app/pipeline/generation.py`: modify (`Chunk.pages`).
- `src/ideology_app/pipeline/positions.py`, `pipeline/__init__.py`: modify (verification, output filter, `FindingCheck`, exports).
- `src/ideology_app/pipeline/runs.py`: modify (`findings` key).
- `src/ideology_app/cli.py`: modify (report line and table).
- `src/ideology_app/config.py`: modify (default 50).
- `apps/web/src/features/methodology/MethodologyPage.tsx` and its `.test.tsx`: modify (60 → 50).
- Tests to modify or add: `test_pipeline_positions.py` (scenarios 1–3), `test_pipeline_runs.py` (scenarios 1, 5, 6), `test_pipeline_prompts.py` (scenario 4 pins), `test_validation_evidence_quotes.py` (add helper tests only; existing tests untouched), `test_cli_pipeline_report.py` (scenario 8; change its "non-default" 50 to 40), `test_pipeline_selection.py` (default 50), `test_validation_party_coverage.py` / `test_config.py` (default), `test_pipeline_generation.py` (`Chunk.pages`).
- **Existing tests whose premise changes:** invented quotes no longer reach Validation, so these tests must be rewritten:
  - `_invented_for_party2` / `_all_invented` / `test_quotes_are_stored_exactly_as_returned` must assert the new behaviour: the invented finding is discarded, its Statement is `no stance`, and the discard is recorded;
  - the `evidence_quotes`-failure paths (run failed, CLI checks rows, exit codes) must keep coverage through positions that bypass extraction: monkeypatch `runs.extract_positions` to return an invented `PositionResult`, or seed rows for a `validating` run.

  Replace the 60 % messages (`minimum is 60%`) with 50 %.

## Visual Design Impact

- UI involved: yes, copy only on `/metodologia` (two "60 %" become "50 %"). Source: `DESIGN.md`. No new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Line 36 and 64: default 50, "lowered from 60 by `pipeline-verified-findings`".
  - Line 50: `positions.py` verifies findings with the shared matcher, the request lists all findings, citing choices are cleared, plus `FindingCheck`.
  - Line 70: the shared helpers.
  - Line 141: the CLI report additions.
  - The `generation.py` `Chunk.pages` field.
- `CONSTRAINTS.md`: add two Pipeline rules.
  - "Extraction MUST verify findings only through `validation.evidence_quotes` (`find_quote_miss`) and MUST NOT edit, trim or repair a quote."
  - "The `party_positions` request MUST list every finding of the Party, verified or not; filtering happens on the reduce's output. Reason: recorded calls stay reusable (`--resume-from`/`--reuse-from`)."
  - Line 57: mention the `findings` key.
- `docs/domain-model.md:43`: default 50 %. Pipeline Run (line 9): it also records the discarded findings.
- `docs/risks-and-open-questions.md`:
  - line 27: coverage 50 % on the methodology page.
  - "Quote matching unverified on real manifestos": a slip or a page slip now drops that one finding at extraction (recorded and reported) instead of failing the run, and a dropped finding lowers coverage. Run 2 had 3 of 312 findings dropped, and 2 cleared stances.
  - "Coverage threshold vs real manifestos": record the user decision of 2026-10-22 (60 → 50, a deliberate default for every run) with the run-2 numbers, and the projection that a `--reuse-from 2` replay passes with a zero margin (PP, EH Bildu, EAJ-PNV at 13/26).
  - Keep the EH Bildu ceiling and the positive-stance bias entries.
  - UPN entry: "would still fail at 50 %".
  - Selection entry: "coverage 50 % since `pipeline-verified-findings`".
  - Add an Implementation-Time Question "Settled (`pipeline-verified-findings`)" describing the output-filter design and its trade-off.
- `CONTEXT.md`, `AGENTS.md`: not needed (no new domain term, no workflow change).

## Implementation Plan

1. Compute and save the two request-hash literals on unmodified code.
2. Build the shared matcher and refactor `evidence_quotes`. The existing evidence_quotes tests must pass untouched.
3. Add `Chunk.pages`, then extraction verification, the output filter and `FindingCheck`, with unit tests.
4. Wire `findings` into the run, then the run-level, reuse and selection tests. Rewrite the invented-quote tests.
5. Add the CLI report line and table, with tests.
6. Change the threshold to 50, then the dependent tests and the methodology page and test.
7. Update the docs, run `CI=true ./init.sh`, do the browser check, and record evidence.

## Implementation Tasks

- [ ] Hash literals computed on `cf062e4` code and pinned.
- [ ] `normalize_pages`, `QuoteMiss`, `find_quote_miss`; `_first_failure` uses them.
- [ ] `Chunk.pages`.
- [ ] `_Candidate.miss`, verification in `extract_positions`, clearing in `_reduce`, `FindingCheck` + `report()`.
- [ ] `execute_run` stores `findings`.
- [ ] `pipeline report` line and table.
- [ ] Default 50; methodology copy and test.
- [ ] Tests for scenarios 1–8; rewrite the invented-quote tests; docs.

## Verification Plan

- `CI=true ./init.sh` exits 0. Report the pytest and Vitest counts against main.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest tests/test_pipeline_positions.py tests/test_pipeline_runs.py tests/test_pipeline_prompts.py tests/test_validation_evidence_quotes.py tests/test_validation_runs.py tests/test_cli_pipeline.py tests/test_cli_pipeline_report.py tests/test_pipeline_selection.py -q`.
- `git diff main -- src/ideology_app/pipeline/prompts.py src/ideology_app/pipeline/checkpoint.py tests/test_validation_evidence_quotes.py` is empty, except for added tests in the last file.
- `git diff main -- data/ideology.db src/ideology_app/migrations` is empty.
- `git grep -n "60" -- src/ideology_app/config.py apps/web/src/features/methodology docs/domain-model.md` shows no coverage 60 left.
- Optional offline replay (validator or implementer), repeating the projection above with the new code:
  - put `git show origin/feature/e2e-real-2023-election-main:data/ideology.db` into a scratch dir outside the repo;
  - `queue_run(..., resumed_from_run_id=2, allow_finished_source=True)` + `execute_run` with a `claude_code`/`claude-sonnet-5-5`-named provider that raises on `generate`;
  - expect passed, 168 reused, findings 312/3/2.
  - Never touch any worktree's `data/ideology.db`.
- **Browser (required)**, following `.agents/skills/github-flow/references/practical-notes.md` "Checking A Worktree's Build In A Browser":
  - after the gate, add a temporary `.claude/launch.json` entry `tmp-pipeline-verified-findings` with absolute worktree paths: `WEB_DIST_DIR=/Users/kike/PycharmProjects/ideology-app-worktrees/pipeline-verified-findings/apps/web/dist`, `DATABASE_URL=sqlite:///<scratch-dir>/check.db` outside the repo (migrated with the worktree's `.venv/bin/ideology db upgrade`), and the worktree's `.venv/bin/uvicorn … --port 8081`;
  - never use port 8000, this repo's `data/ideology.db`, or another worktree's DB;
  - open `/metodologia` at 375 px and at desktop width. Check both "50 %" mentions, that no "60 %" coverage text is left, and that nothing overflows at 375 px. Read the console (no errors) and the network (no failed requests);
  - stop the server, remove the entry and delete the scratch DB. `git status` shows only the feature's files.

## Evidence To Capture

- Gate counts; the test names per scenario; the pinned hash literals and how they were computed; the empty diffs of `prompts.py`, `checkpoint.py`, the DB and migrations.
- Output of the optional replay, if run.
- Browser: name, widths, the texts seen, console and network clean. Record this in `feature_list.json` and `PROGRESS.md` only (no `docs/validations/`).

## Validator Checklist

- [ ] No request changed: the prompts diff is empty, the hash pins come from pre-change code, and the zero-call reuse test passes with a provider that raises.
- [ ] One matcher: `positions.py` uses `evidence_quotes.find_quote_miss`, with no duplicate normalisation. The evidence_quotes messages and tests are unchanged.
- [ ] Unverifiable findings never become Party Positions or selection input. Quotes are stored verbatim. A cited page outside the chunk is discarded.
- [ ] Discards are recorded in `statement_selection["findings"]` and shown by `pipeline report`. Older runs show `not recorded`.
- [ ] Default 50 in config, the selection and Validation, the docs and `/metodologia`. Explicit-threshold tests keep their meaning.
- [ ] The `evidence_quotes` failure path is still covered end to end (bypassing extraction).
- [ ] Docs and risks updated as listed (the 50 % decision with run-2 numbers, the slip entry, the EH Bildu and positive-stance entries kept).
- [ ] Browser check recorded, temporary entry removed, `data/ideology.db` untouched, no `docs/validations/`.

## Open Questions

- Should `/metodologia` say that a quote not found on its page is discarded during extraction (and becomes "sin posición")? It is out of scope here (copy changes only 60 → 50). A user decision is needed.
- Fallback when the reduce cites a discarded finding: today the Statement becomes `no stance`. Picking another verified candidate with the same Statement and value would recover the stance without an LLM call, but code would be choosing Evidence. It is not built and needs a user decision.
- The replay projection passes with zero margin. A fresh (non-replay) run may land below 50 % for PP, EH Bildu or EAJ-PNV.
