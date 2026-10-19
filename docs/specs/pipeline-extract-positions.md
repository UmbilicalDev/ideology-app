# Feature Implementation Spec: Pipeline Run extracts Party Positions with Evidence

## Source Feature

- `id`: pipeline-extract-positions (GitHub issue #12)
- `area`: pipeline
- `depends_on`: pipeline-generate-statements (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (notes: joint coalition manifesto takes precedence; chunk long manifestos)

## Goal

After a Pipeline Run has generated its Statements, the same run extracts a Party Position for every Statement × Party of the Election: an integer −2..+2 or `no stance`. Every position other than `no stance` stores Evidence: a verbatim quote as the LLM returned it, the Source Document it came from, its page, and the document URL when the document came from a URL. The run records which Source Documents it read and which one counted as each Party's main (joint) manifesto. The lifecycle stays `queued` → `running` → `validating`, or `failed`. A Dataset Version is written only when both stages succeed, and then it is complete.

## Non-Goals

- No Validation checks: quote verification, coverage, separation and questionnaire shape are not part of this feature. The code does not check that a quote exists in the source, that a page is right, or that a Party has enough positions. No `passed` status and no publishing.
- No change to Statement generation: `statement_candidates` / `generate_statements` prompts, versions, fingerprints and `build_chunks` output stay as they are.
- No new Source Document field or CLI option to mark the joint manifesto (see Open Questions). No change to `source add`.
- No hard-crash recovery command, no background worker, no `live`-mode trigger, no run report, no HTTP endpoint or UI.
- No new dependency. No change to `llm/` or `init.sh`.

## Job Story

When an Election has a candidate Questionnaire generated from its manifestos,
I want the same run to place every Party on every Statement and cite where it says so,
so Validation can check the Evidence and Voters can see each Party's quote.

## Users And Permissions

- Operator: CLI only, as before. Cannot edit positions or Evidence. There is no update or delete path.
- Voter: not affected yet.

## Acceptance Scenarios

All tests use a temporary SQLite database, a `FakeProvider` and the autouse env/socket guard (`pipeline_fixtures.offline_guard`). No API key, no socket.

### Scenario 1: Happy path stores a position for every Statement × Party

Given the `seed_election` setup (Parties 1 and 2, one parsed 2-page document each, one `failed` document on Party 2). The fake returns 30 Statements. `position_findings` returns, for Party 1's chunk, findings for Statements 1 and 2 (page 1 and 2). For Party 2's chunk it returns one finding for Statement 1. `party_positions` picks value +2 / −1 with candidates 1 / 2 for Party 1, and value −2 with candidate 1 for Party 2.
When `execute_run` runs
Then the run is `validating`, and `prompt_versions` holds all four tasks at `v1`. `llm_calls == 3 + 2 + 2`: 2 candidate chunks + 1 reduce, then 2 finding chunks + 2 party reduces. The tokens are summed over all 7 calls.
And the Dataset Version has 30 Statements and exactly 60 `party_positions` rows, one per (Statement, Party). Positions (1, P1) = +2, (2, P1) = −1 and (1, P2) = −2 each have `evidence_source_document_id`, `evidence_quote` and `evidence_page` equal to the chosen candidate. Their `evidence_url` is null (upload). The other 57 rows have `value` null and every evidence column null.
And `pipeline_run_source_documents` has documents 1 and 2 with role `main`, and not the `failed` document 3.
And `RunOutcome.position_count == 60`.

### Scenario 2: Coalition precedence and document roles

Given Party 1 has two parsed documents, id 1 (registered first) and id 4
When the run executes
Then document 1 is recorded with role `main` and document 4 with role `additional`. Party 1 gets one `position_findings` call per chunk of each document, main first.
The `party_positions` prompt for Party 1 labels each candidate `programa principal` or `programa adicional`, lists main-document candidates first, and its system text states the precedence rule: when they conflict, the main (joint coalition) manifesto wins.
For a Party with a single document, no candidate is labelled `programa adicional`.
Evidence chosen from document 4 is stored with `evidence_source_document_id = 4`.

### Scenario 3: URL documents carry the URL locator

Given Party 2's parsed document has origin `url` and `source_url = "https://example.org/programa.pdf"`
When a position cites a candidate from that document
Then `evidence_url` equals that `source_url` and `evidence_page` is the candidate's page.

### Scenario 4: No findings, no documents → `no stance` without an LLM reduce

Given every `position_findings` call for Party 2 returns `{"findings": []}`
Or Party 2 has no parsed document at all, while Party 1 has one
When the run executes
Then all 30 of Party 2's rows have `value` null and no evidence. No `party_positions` call is made for Party 2, and with no documents, no `position_findings` call either. The run still ends `validating`.

### Scenario 5: Prompts are party-blind and deterministic

Given the Parties are named `Partido Alfa`/`PA` and `Bloque Beta`/`BB`
When the run executes
Then no recorded request (any task) contains a Party name or short name in `system` or `prompt`.
Each `position_findings` prompt lists the Statements as `[n] <text>` (n = Statement position) and then holds one chunk, exactly as `build_chunks` renders it.
Running the same input twice gives identical request lists.

### Scenario 6: Invalid LLM output fails the run with no Dataset Version

Given one of these outputs:
- a finding or position names a Statement number outside 1..n;
- a `party_positions` output names the same Statement twice;
- an evidence index outside 1..number of candidates;
- a schema mismatch (value 3, empty quote, quote over 500 chars, page 0);
- an `LLMProviderError` in either position task
When `execute_run` runs
Then the run is `failed` with a specific reason (≤ 500 chars), e.g. `position_findings referred to unknown statement 31` or `party_positions repeated statement 4`. `generation_finished_at` is set and the usage of the successful calls is kept. No Dataset Version, Statement or Party Position row exists. The `pipeline_run_source_documents` rows written at start remain.

### Scenario 7: Call budget is checked before any LLM call

Given the chunks of all Parties' documents plus one reduce per Party with documents add up to more than `MAX_POSITION_CALLS_PER_RUN` (300) (use `monkeypatch` on the constant)
When `execute_run` runs
Then the run fails with `too many position extraction calls: <n> (limit 300)`, and `provider.calls == []`.

### Scenario 8: Lifecycle and interruption

When a fake `position_findings` callable reads the run through a separate Session, the status is `running` and no Dataset Version exists.
When a fake callable raises `KeyboardInterrupt`, `execute_run` records `failed` with `interrupted` and re-raises `KeyboardInterrupt`. The run is not left `running`.

### Scenario 9: Database guarantees (migration 0005)

`upgrade head` gives `0005` with the new tables `party_positions` and `pipeline_run_source_documents`. `downgrade 0004` drops exactly those. `alembic check` finds no drift. The PG offline render has each CHECK once, 14 in total, up from 10.
The database rejects:
- `value = 3`;
- a non-null `value` with a null quote, document or page;
- a null `value` with any evidence column set;
- `evidence_page = 0`;
- a duplicate (statement_id, party_id);
- a duplicate (pipeline_run_id, source_document_id);
- a bad role.
Deleting the Election cascades to all new rows.

### Scenario 10: CLI

`pipeline run --election 1` (patched `cli._provider`) prints `Pipeline run 1: validating (dataset version 1, 30 statements, 60 party positions)`.
`pipeline positions --dataset-version 1 [--party 1]` prints the header `statement party value document page url quote` and one tab-separated row per position, ordered by statement position and then party id. `no stance` rows print `no_stance` and empty evidence cells. In the quote cell, each whitespace run (tabs, newlines) is shown as one space. This is display only; the stored quote is not changed.
An unknown dataset version or party exits 1 (`Error: … not found`). A database at `0004` exits 1 with the not-initialised message.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md` (the Party Position and Evidence shapes; the coalition rule is a prompt rule; a coalition's joint manifesto is its main Source Document), `docs/build-brief.md`, `docs/technical-discovery.md` (run log, cost visibility), `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.
- `ARCHITECTURE.md`, `CONSTRAINTS.md` (migration review, prompt version and fingerprint rule, party-blind rule, immutability).
- `docs/specs/pipeline-generate-statements.md`; `src/ideology_app/pipeline/{__init__,prompts,generation,runs}.py`; `models.py`; `migrations/versions/0004_pipeline_runs_statements.py`; the `cli.py` pipeline group; `llm/base.py`, `llm/fake.py`.
- `tests/pipeline_fixtures.py`, plus `tests/test_pipeline_runs.py` and `tests/test_migrations.py`, which are grepped for head, CHECK-count and `prompt_versions` assertions.
- Finding: migration `0004` has no party position table. The `position_positive` CHECK there belongs to `statements.position`, the Statement order, and is unrelated. A new migration `0005` is required.

### Existing Patterns To Follow

- `PromptSpec` plus fingerprints in `tests/test_pipeline_prompts.py`, `PROMPT_VERSIONS` recorded by `queue_run`, `Usage.record`, and `GenerationError` / `LLMError` → `failed` in `execute_run`. LLM calls run outside any transaction.
- Non-native enums through `_enum`, the naming convention, hand-reviewed autogenerate, and `_print_rows` for TSV output.

### Current Gaps

- There is no position model, no position prompt or stage, and no per-run record of the Source Documents used. `build_chunks` returns bare strings with no document id.

## Technical Approach

**Models** (`models.py`):

- `SourceDocumentRole(StrEnum)`: `main`, `additional`.
- `PipelineRunSourceDocument` (`pipeline_run_source_documents`): composite PK (`pipeline_run_id` FK cascade, `source_document_id` FK cascade), `role`. Relationship `PipelineRun.source_documents`.
- `PartyPosition` (`party_positions`):
  - `id`; `statement_id` FK `statements.id` cascade; `party_id` FK `parties.id` cascade, indexed;
  - `value` Integer, nullable. Null means `no stance`.
  - `evidence_source_document_id` FK `source_documents.id` cascade, nullable; `evidence_quote` Text, nullable; `evidence_page` Integer, nullable; `evidence_url` String(2048), nullable.
  - Unique (`statement_id`, `party_id`).
  - CHECKs: `value_range` (`value IS NULL OR value BETWEEN -2 AND 2`); `evidence_page_positive` (`evidence_page IS NULL OR evidence_page >= 1`); `evidence_matches_value` (null value ⇒ all four evidence columns null; non-null value ⇒ document, quote and page not null).
  - Relationship `Statement.party_positions` ordered by `party_id`.
  - Property `engine_value -> int | Literal["no_stance"]`, plus module constant `NO_STANCE = "no_stance"`. This is the single mapping to what `match-score.js` consumes.
- Domain choice: Evidence is a value object stored as columns, so the database itself enforces "every non-`no stance` Party Position has Evidence".

**Migration** `0005_party_positions.py`: autogenerate with `--rev-id 0005`. Remove the duplicate enum `sa.CheckConstraint` lines; keep the three model CHECKs. Then run `alembic check`. If another branch lands `0005` first, renumber (see the risks doc).

**`generation.py`**:

- Add `Chunk(party_id, document_id, text)` and `build_document_chunks(documents, max_chars)`, which return the same chunks with their ids.
- `build_chunks` becomes `[c.text for c in build_document_chunks(...)]`. Its output is unchanged and its existing tests must pass untouched.
- `DocumentPages` gains `source_url: str | None = None` and `role: SourceDocumentRole = MAIN`.

**`prompts.py`**: add two `v1` prompts in Spanish, with fingerprints.

- `POSITION_FINDINGS` (task `position_findings`, 4096 tokens, fields `{statements}` and `{chunk}`).
  - Schema `FindingList(findings: list[Finding], max 60)`.
  - `Finding`: `statement: int ≥ 1`, `value: Literal[-2,-1,0,1,2]`, `quote: str` (1..500 chars, non-space), `page: int ≥ 1`.
  - Rules:
    - The scale is −2 strongly disagree … +2 strongly agree, from the manifesto's point of view.
    - Report only Statements the fragment explicitly addresses. Never infer from general ideology.
    - The quote is copied verbatim from a single page, with no paraphrase, no ellipsis and no added text.
    - `page` is the number of the `[página N]` marker.
    - Return an empty list if the fragment addresses nothing.
- `PARTY_POSITIONS` (task `party_positions`, 8192 tokens, fields `{statements}` and `{candidates}`).
  - Schema `PositionList(positions: list[PositionChoice], max 60)`.
  - `PositionChoice`: `statement: int ≥ 1`, `value: Literal[-2..2]`, `evidence: int ≥ 1` (the candidate number).
  - Candidate lines are `C<k> [programa principal|programa adicional] [afirmación n] [valor v] [página p] «quote»`.
  - Rules:
    - Choose one stance per Statement that the candidates support, and cite the candidate that best supports it.
    - Omit a Statement if nothing supports a stance. An omitted Statement is `no stance`.
    - The main (joint coalition) manifesto wins over additional ones when they conflict.
    - Never invent a candidate.
  - Any candidate index is allowed for any Statement.
- Extend `PROMPTS` and `PROMPT_VERSIONS`. The prompt text MUST NOT include Party names.

**New `pipeline/positions.py`** (no database; imports `llm.base` and `prompts`):

- `MAX_POSITION_CALLS_PER_RUN = 300`.
- `plan_position_calls(documents) -> int`: the number of chunks plus the number of Parties with at least one chunk.
- `extract_positions(provider, statements, documents, party_ids, usage) -> dict[party_id, list[PositionResult]]`.
  - It processes Parties in id order and document chunks in `(role main first, document id, page)` order. It makes one `position_findings` call per chunk and validates each Statement number against 1..n.
  - It numbers candidates in order. If a Party has no candidates, it makes no reduce call. Otherwise it makes one `party_positions` call and validates the statement range, uniqueness and evidence index.
  - It returns exactly n results per Party in `party_ids`. Omitted Statements and Parties without documents get `value None`.
  - Violations raise `GenerationError` with the messages from Scenario 6. `LLMError` propagates.
- `PositionResult(statement_number, value, document_id, quote, page, url)`. The quote is the candidate's quote unchanged.

**`runs.py`**:

- `_start` additionally loads the Election's Party ids. For each Party, it treats the lowest-id `parsed` document as `main` and the others as `additional`. It inserts the `PipelineRunSourceDocument` rows in the same commit that sets `running`, and loads `source_url` into `DocumentPages`.
- `execute_run`:
  1. It checks `plan_position_calls` against the cap before any LLM call (Scenario 7).
  2. It runs `generate_statements`, then `extract_positions` (with Statement texts numbered 1..n), both outside a transaction.
  3. In one final commit, `_finish` inserts the Dataset Version, the Statements and n × Parties positions, and sets `validating`.
  4. Failure handling: `LLMError`/`GenerationError` → `failed` with the reason. `KeyboardInterrupt` → `failed` with `interrupted`, then re-raise. Any other exception → `unexpected error: <Class>`, then re-raise.
- `RunOutcome` gains `position_count`.
- Add `list_positions(session, dataset_version_id, party_id=None)`, which raises `NotFoundError` for an unknown version, or an unknown party (or one outside the version's Election).

**CLI**: extend the `pipeline run` message, and add `pipeline positions` (Scenario 10).

## Expected File Changes

- `src/ideology_app/models.py`: modify.
- `src/ideology_app/migrations/versions/0005_party_positions.py`: create.
- `src/ideology_app/pipeline/{prompts,generation,runs,__init__}.py`: modify. `pipeline/positions.py`: create.
- `src/ideology_app/cli.py`: modify.
- `tests/pipeline_fixtures.py`: modify. Add default fake responses for the two new tasks, and helpers for a second document, a URL document and finding/position callables that parse `[afirmación n]` / `[página N]`.
- `tests/test_pipeline_positions.py` (Scenarios 2–7 at the unit level): create.
- `tests/test_pipeline_runs.py`, `tests/test_pipeline_prompts.py`, `tests/test_cli_pipeline.py`, `tests/test_migrations.py`, `tests/test_cli_source.py`: modify.
  - The changed expectations are the expected `prompt_versions` (4 tasks), `llm_calls`, head `0005`, `TABLES_AT_0004`, CHECK count 14, the not-initialised parametrisation (add `0004`), two new fingerprints, and the run message.
  - Statement-generation assertions must not change otherwise.

## Visual Design Impact

- UI involved: no. Browser validation: exempt (CLI and pipeline only).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Data Layer: the new models and `0005`.
  - Pipeline: the positions stage, its constants, the main/additional rule, the single final commit, `interrupted`, and `engine_value`.
  - Runtime Surface: `pipeline positions` and the new run message.
- `CONSTRAINTS.md`: update the Pipeline section.
  - Party names MUST NOT reach any pipeline prompt (this widens the existing Statement-only rule).
  - Party Positions and Evidence MUST NOT be updated or deleted by application code.
  - Evidence quotes MUST be stored exactly as the LLM returned them (normalise only when matching).
  - A Dataset Version MUST be written only together with all its Statements and Party Positions.
- `AGENTS.md`: not needed.
- `docs/risks-and-open-questions.md`: update in the same change.
  - Implementation-Time Questions:
    - Edit the "exact prompts for Party Position extraction and how to chunk" entry to say it is settled: per-chunk findings, then a per-Party reduce, `v1`, the same 40k chunks, cap 300.
    - Edit the "Which Source Documents a Pipeline Run used is not recorded" entry: remove its first sentence (now recorded in `pipeline_run_source_documents`). Keep the content-hash question for `live-mode-url-refetch`.
    - Add: "Which document is a coalition's joint manifesto: currently the Party's lowest-id parsed document (register it first). An explicit Operator flag is undecided."
    - Add to the `validation-evidence-quotes` entry: the cited page is stored as returned; that feature decides whether the quote must be on that page or only in the document.
  - Risks:
    - Rewrite "Runs stuck in `running`". Ctrl-C now ends the run `failed: interrupted`. A hard kill or crash still leaves it `running` with no recovery command, and the Operator queues a new run; recovery is deferred to `live-mode-source-change-trigger`, the first unattended runner. Remove the sentence about Source Documents not being recorded.
    - Under real-LLM behaviour, add the position prompts and the 300-call cap. A run now makes about 2 × chunks + Parties + 1 calls.
    - Add: the reduce can pick a quote found for a different Statement, so the "quote verified but stance misread" risk applies.

## Implementation Plan

1. Models, migration `0005` and the migration tests (Scenario 9).
2. `build_document_chunks` refactor (existing chunk tests stay green).
3. Prompts, schemas and fingerprints.
4. `positions.py` and its unit tests (Scenarios 2, 4–7).
5. `runs.py` integration and run tests (Scenarios 1, 3, 8). Update the existing run tests' fixtures and expectations.
6. CLI and its tests (Scenario 10). Then docs, `CI=true ./init.sh`, and evidence.

## Implementation Tasks

- [ ] `SourceDocumentRole`, `PipelineRunSourceDocument`, `PartyPosition`, `NO_STANCE` and `engine_value`; migration `0005`; `test_migrations.py`.
- [ ] `Chunk` / `build_document_chunks`, and the `DocumentPages.source_url`/`role` fields.
- [ ] `POSITION_FINDINGS` and `PARTY_POSITIONS` with their schemas; fingerprints; schema-rejection tests (value 3, empty or long quote, page 0, over 60 items).
- [ ] `positions.py` (`plan_position_calls`, `extract_positions`, `PositionResult`, the cap) and `test_pipeline_positions.py`.
- [ ] `runs.py` (source-document records, budget pre-flight, final commit, `interrupted`, `position_count`, `list_positions`) and its tests.
- [ ] CLI `pipeline run` message and `pipeline positions`; `test_cli_pipeline.py`.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md` (edits listed above).

## Verification Plan

- `CI=true ./init.sh` exits 0 (pytest 342 + new tests, node 41).
- `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` is clean.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -q tests/test_pipeline_*.py tests/test_cli_pipeline.py` passes.
- Alembic `history` shows `0004 -> 0005 (head)` and `check` reports no drift, both on a scratch DB.
- `grep -rn "anthropic\|FakeProvider\|build_provider" src/ideology_app/pipeline` returns nothing.
- Offline CLI smoke in a scratch dir outside the repo:
  - Run `LLM_PROVIDER=fake ideology pipeline run`. It should end `failed`, committed, exit 1.
  - The run should have `pipeline_run_source_documents` rows, which you can inspect with `sqlite3` or a short Python snippet.
  - Delete the scratch dir afterwards.
- No E2E harness or browser surface. Service and CliRunner tests cover the flow.

## Evidence To Capture

- `init.sh` exit code and test counts, the `-X dev` run, alembic history/check, the grep, the smoke results, and the test that covers each of Scenarios 1–10. Record them in `feature_list.json` → `pipeline-extract-positions.evidence` and in `PROGRESS.md`. Never in `docs/validations/`.

## Open Questions (non-blocking)

- An explicit joint-manifesto flag on Source Documents, instead of the lowest-id rule. Deferred; recorded in the risks doc.
- Whether `MAX_POSITION_CALLS_PER_RUN = 300` fits real 2023 manifestos. Checked in `e2e-real-2023-election`.

## Validator Checklist

- [ ] Scenarios 1–10 each have a named passing test, and the smoke ran offline.
- [ ] Every Statement × Party has exactly one row. The DB CHECK enforces Evidence on every non-`no stance` row. Quotes are stored unchanged.
- [ ] There are no Validation checks, no `passed` status, no publishing, and no update or delete path. Statement generation behaviour is unchanged.
- [ ] No Party name appears in any prompt. Four prompt versions are recorded and pinned.
- [ ] Source Documents used and their roles are recorded per run. Ctrl-C ends a run `failed: interrupted`.
- [ ] Migration `0005` was reviewed (each CHECK once, no drift).
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and the risks doc are edited as listed. `feature_list.json` and `PROGRESS.md` are updated.
