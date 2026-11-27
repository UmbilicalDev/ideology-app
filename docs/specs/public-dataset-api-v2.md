# Feature Implementation Spec: Public API for Constituencies, candidatures, Proposals and per-Constituency questionnaires

## Source Feature

- `id`: public-dataset-api-v2
- `area`: api
- `depends_on`: constituency-selection-validation (`accepted`, PR #131 into `v2`)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest API tests for every new field and for an older Dataset Version; OpenAPI updated; `CI=true ./init.sh` passes)
- Branch: `feature/public-dataset-api-v2`, cut from `feature/statement-rewording` (2e72fcf). The PR goes into `v2` after #129, #130, #131 and the `statement-rewording` PR, never into `main`.
- Owns these entries in `docs/risks-and-open-questions.md` ("Constituency redesign"): the handoff "decide what `/api/v1/dataset-versions/{id}` … does with a published v2 Dataset Version" (closed here); S5 for "the future v2 API" (Settled entry 54 and CONSTRAINTS "Readers of a v2 Party Position per Constituency"); R12 "the API serves only the final text, with no marker"; the Excluded-Party data that `results-by-constituency` will read instead of `ExcludedPartiesNotice.tsx` (Later/Not MVP entry: this feature serves the data, and the web change stays with `results-by-constituency`).

## Goal

For a published or superseded v2 Dataset Version, the read-only public API serves everything the v2 web features need, one Constituency at a time. That covers the 52 Constituencies with their availability and reason, the Parties running in each, the Excluded Parties with their reasons, each Constituency's ranked Statements and offered lengths, Party Positions with their Proposal Evidence under S5, and each running Party's Proposals in one category for the Comparador. Legacy Dataset Versions (1–5) keep byte-identical responses. A v2 version is never served in the legacy shape. `packages/core` gets the types, parsers and client methods, so later web features only consume them.

## Non-Goals

- Any web UI change: the picker, the length choice, the results note, the Comparador and the Landing filter belong to `constituency-picker`, `questionnaire-length-and-context`, `results-by-constituency` and `comparator-page`. `ExcludedPartiesNotice.tsx` stays as it is.
- Spanish copy for the Excluded or unavailable reasons. The API serves codes only.
- Statement source Proposals (`statement_proposals`), tags, the unavailable `detail` JSON, and the pipeline report. Those are for `v2-run-inspection` or never.
- `/api/v2`, response compression, CORS, pagination, query parameters.
- Changing any legacy body, legacy Validation, or S5, K1–K12 and the R rules.
- Building the dev dataset (`dev-dataset`). This feature only adds test fixtures.

## Job Story

When a v2 web feature needs a Voter's Constituency questionnaire, Party Positions or a Party's Proposals,
I want one small, immutable, cacheable request per Constituency (and per category for the Comparador),
so the client never downloads the 52-Constituency pool, never applies S5 itself, and never sends an Answer.

## Users And Permissions

- Voter (anonymous, through the web client): `GET` only, path parameters only, no cookie. Only `published` and `superseded` versions are served.
- Operator: no new surface. The pipeline writes the one new table inside `_finish_v2`.

## Decisions (A1–A12 are defaults for team review)

**A1 Shape: new path-only sub-resources under `/api/v1`, no `/api/v2`, no discriminator on the legacy body.** They are additive, so they respect "`/api/v1` changes MUST be additive". They respect "no query or body parameters", so the category goes in the path, not in `?category=`. The client needs one Constituency at a time. The whole pool in one body would be about 200+ Statements × ~20 Parties with Evidence, several MB with no compression (ARCHITECTURE: "no compression"). A per-Constituency body is bounded by n(c) × |R(c)|.

| Path | operationId | 200 body |
|---|---|---|
| `/api/v1/dataset-versions/{id}/constituencies` | `listDatasetVersionConstituencies` | `ConstituencyListOut` |
| `/api/v1/dataset-versions/{id}/constituencies/{code}` | `getConstituencyQuestionnaire` | `ConstituencyQuestionnaireOut` |
| `/api/v1/dataset-versions/{id}/constituencies/{code}/proposals/{category}` | `getConstituencyProposals` | `ConstituencyProposalsOut` |

Every route sends `IMMUTABLE_CACHE_CONTROL` with a strong ETag and answers 304 through `cached_json`. `code` is `Path(pattern="^[0-9]{2}$")` and `category` is `Path(pattern="^[a-z_]{1,40}$")`. A malformed value gets FastAPI's 422, as malformed ids do today.

**A2 Generation refusals.** `getDatasetVersion` and `getPublishedDatasetVersion` answer `404 {"error": {"code": "dataset_version_is_v2", "message": "dataset version N is a v2 version; read /api/v1/dataset-versions/N/constituencies"}}` for a v2 version. The three new routes answer `404 dataset_version_is_legacy` ("dataset version N is a legacy version; read /api/v1/dataset-versions/N") for a legacy version. Unknown and `candidate` ids keep the identical `dataset_version_not_found`. Every 404 gets `no-store`. Why 404 and not a discriminated 200: today's parser would fail on a new shape anyway. A 404 with a code is already documented (`ErrorOut`), and `openShareLink` already turns it into its not-found notice while `useQuestionnaireData` turns it into its error state, with no crash. No old Share Link can point at a v2 version, because every v1/v2 link was made from versions 1–5. `constituency-picker` will move the Landing to the new routes. The recorded risk "a published v2 version would be served nationally" is closed by this refusal.

**A3 `ElectionOut.published_dataset_version_generation`** (`"legacy" | "v2" | null`, null exactly when `published_dataset_version_id` is null) is appended last. It is additive and lets `constituency-picker` filter the Landing without one request per Election. It changes the Election bodies (pointer cache, 60 s), never a Dataset Version body.

**A4 `ConstituencyListOut`** = `{id, election_id, created_at, constituencies: [{code, name, available, unavailable_reason, valid_statement_count, offered_lengths}]}`: all 52 rows in code order, from `dataset_version_constituencies` joined with `constituencies.name`. `unavailable_reason` is null exactly when available. Values are `fewer_than_two_parties`, `too_few_statements` and `low_party_coverage`.

**A5 `ConstituencyQuestionnaireOut`** = `{dataset_version_id, code, name, available, unavailable_reason, offered_lengths, statements, parties, excluded_parties}`:
- `statements`: `[{id, rank, text, topic, context_note}]` from `constituency_statements` in rank order (all n(c); a length L is ranks 1..L). `text` is `statements.text` only. `statement_rewordings` is never joined, and no marker is added (R12, CONSTRAINTS).
- `parties`: R(c), meaning the `dataset_version_candidatures` rows of c with `excluded_reason IS NULL`, by Party id (same order rule as legacy). Each entry is `{id, name, short_name, logo_url, positions, evidence}`. `positions` has one entry per Statement in rank order, `{statement_id, value, evidence_proposal_ids}`. `evidence` is the deduplicated `ProposalOut` list `{id, text, page, url, source_document_id}` of every Proposal referenced in that Party's positions, by Proposal id. Dedup keeps the body small, because one Proposal often backs several Statements. Evidence stays per Party because a shared manifesto gives one Proposal id with a different `source_document_id` per Party. `url` is the Source Document row's `source_url`, and `page`/`text` come from `proposals`.
- `excluded_parties`: the rows of c with `excluded_reason` set, `[{id, name, short_name, reason}]` by Party id, `reason` ∈ `no_manifesto | discarded_at_review | too_few_proposals`. This is the data `results-by-constituency` needs.
- An unavailable Constituency answers 200 with `available: false`, its reason, `offered_lengths: []`, `statements: []`, its R(c) with `positions: []` and `evidence: []`, and its `excluded_parties`.

**A6 S5 in a Constituency.** For Party p, Statement s and code c: `value = effective_value(stored value, [row.constituencies for each Evidence row in rank order], c)`, rendered as an int or `"no_stance"`. The Evidence shown is only the Evidence rows that count in c, in rank order. To keep one rule, add `constituency_rules.counting_evidence(evidence_constituencies, code) -> tuple[int, ...]` (indexes of the rows listing `code`) and rewrite `effective_value` as "`value` when `value is not None` and `counting_evidence(...)` is non-empty, else `None`" (behaviour unchanged). The API uses both. So `evidence_proposal_ids` is empty exactly when `value == "no_stance"`, and 0 (neutral) carries Evidence. A missing `party_positions` row reads `no_stance` with `[]`.

**A7 Proposals for the Comparador: `ConstituencyProposalsOut`** = `{dataset_version_id, code, category, parties: [{party_id, proposals: [ProposalOut]}]}`. `parties` is every Party of R(c) by id, including those with an empty list, so all Parties are treated identically. Excluded Parties are never listed. A Proposal is listed when it counts in c for that Party (frozen, A8) and `category` is among its 1–3 `categories`, the same membership S4 positioning uses (`v2.positions.category_proposals`). Order is the frozen counted order. `category` must be a `topic_catalog.TOPIC_CATALOG` key, else `404 category_not_found`. The route works for unavailable Constituencies too (the picker disables them). There is no pagination. The 2026 bundle is ≈ 2.3M characters over 12 files, so one Constituency × one category is expected in the tens of KB. `e2e-2026-constituencies` measures it.

**A8 Freeze the counted Proposals: new insert-only table `dataset_version_proposals` (migration `0021`).** Today a version freezes only the Evidence Proposals (`party_position_proposals.constituencies`). Every other counted Proposal of a Party exists only through `counted_proposals`, which reads the ledger and bundle files live, and K9 forbids reading the ledger for a Dataset Version. Columns: `dataset_version_id` (FK, CASCADE), `party_id` (FK, CASCADE), `rank` (≥ 1, counted order per Party), `proposal_id` (FK, no cascade), `source_document_id` (FK, CASCADE), `constituencies` (JSON, sorted codes). PK `(dataset_version_id, party_id, rank)`, unique `(dataset_version_id, party_id, proposal_id)`. It is written only by `_finish_v2` from `phase4.parties` (each `PhaseProposal`), in the version's commit. It is additive `CREATE TABLE` only. `stored.dataset_version_problems` (db check) adds three problems: a legacy version with rows; a v2 version with none; an Evidence row (`party_position_proposals`) whose `(party, proposal)` is not frozen with the same `constituencies`. No v2 version exists in `data/ideology.db` (versions 1–5 are legacy), so nothing needs backfilling.

**A9 Statement order inside `parties[*].positions`** follows the body's `statements` (rank order), like the legacy alignment rule. The core parser checks it.

**A10 Party names and logos** are read live, as in the legacy body, under the accepted caching risk (`Public API caching`). Constituency names come from the migration-seeded `constituencies` table.

**A11 `packages/core`.** The types, parsers and client methods are added here, with Vitest. A new port `application/constituency-api.ts` (`ConstituencyApi`: `listConstituencies(versionId)`, `getConstituencyQuestionnaire(versionId, code)`, `getConstituencyProposals(versionId, code, category: TopicKey)`) is kept apart from `PublicApi`, so existing fakes keep compiling. `createPublicApiClient` returns `PublicApi & ConstituencyApi & FeedbackApi`. The parser resolves `evidence_proposal_ids` into nested `Proposal` objects, so consumers get `position.evidence: readonly Proposal[]`. The client checks `code` (`/^[0-9]{2}$/`) and `category` (a `TOPIC_CATALOG` key) before any request. `Election.publishedDatasetVersionGeneration` is added. A missing key reads `"legacy"` when the id is set and `null` otherwise (cached-body rule).

**A12 No new caching constant, no compression.** If the measured per-Constituency body is too big (`e2e-2026-constituencies`), compression or an Evidence split is a follow-up (recorded risk).

## Acceptance Scenarios

1. **Overview.** Given a published v2 version, when `GET …/constituencies`, then 200 with 52 rows in code order, each `available`, `unavailable_reason`, `valid_statement_count` and `offered_lengths` equal to the stored row, `Cache-Control: public, max-age=86400, immutable`, and an ETag. `If-None-Match` gets a 304.
2. **Questionnaire.** Given an available c, when `GET …/constituencies/{c}`, then `statements` are the `constituency_statements` ranks 1..n(c) with `statements.text`, `parties` are exactly R(c) by id, each with one position per Statement, `excluded_parties` lists c's Excluded Parties with their reason codes, and the exact body equals a hand-written expected JSON (direct-insert fixture).
3. **S5.** Given a Position whose only Evidence counts in 28, when c = 31 (available), then it reads `"no_stance"` with `[]` there. In 28 it reads its value with only the counting Evidence, in rank order. Given a Position with two Evidence rows, one counting in c, then only that one is served. Every served value equals `effective_value` for that c.
4. **Unavailable.** Given an unavailable c, then 200 with `available: false`, the stored reason, empty `statements` and `offered_lengths`, R(c) with empty positions, and `excluded_parties`.
5. **Comparador Proposals.** Given c and `housing`, then every R(c) Party is listed by id (empty lists included), each with only its frozen Proposals counting in c and carrying `housing` (also as a second category), in counted order. An Excluded Party never appears. A set-aside Proposal (conflict decision) does not appear in its overlap Constituency.
6. **Refusals.** A v2 version gets `404 dataset_version_is_v2` on `getDatasetVersion` and `getPublishedDatasetVersion`. A legacy version gets `404 dataset_version_is_legacy` on the three new routes. Unknown or `candidate` ids get `dataset_version_not_found`. Code `00` gets `constituency_not_found`, `abc` or `1` gets 422, an unknown category gets `category_not_found`, `Housing` gets 422. All 404s carry `no-store`.
7. **Legacy byte-identical.** `test_exact_dataset_version_body` and every legacy Dataset Version test pass unchanged (same bytes, same ETag) on a database that also holds a v2 version.
8. **Elections.** `published_dataset_version_generation` is `"legacy"`, `"v2"` or `null`, consistent with the published id, and it is appended last.
9. **Final text only.** A reworded Statement is served with the Operator's text on the questionnaire route. The raw body of every new route contains neither the AI text, the reason nor the explanation, and no `ai_text`, `reason`, `explanation` or `rewording` key. (Implementation note, 2026-11-25: A4/A5 require the keys `unavailable_reason` and `excluded_parties[*].reason`, so "no `reason` key" is read as no rewording reason: the bodies never contain the rewording's reason, AI text or explanation, and the only `"reason":` keys are the Excluded Parties' codes.)
10. **No Answers.** All routes are GET-only with no query, body, header or cookie params. Query strings change neither body nor ETag. Only `SELECT`/`PRAGMA` run.
11. **Freeze.** A v2 run writes one `dataset_version_proposals` row per counted Proposal per non-Excluded Party, equal to `phase4.parties`. `db check` reports each of the three A8 problems when tampered. Migration `0021` upgrades and downgrades cleanly, and the committed DB is upgraded with pre-existing tables identical.
12. **Core client.** Vitest: each new method requests the exact path, maps to camelCase, resolves Evidence ids, and rejects with `invalid_response` on these contract violations: misaligned positions, an unknown evidence id, evidence on `no_stance` or none on a value, a bad code or reason, a duplicate Statement id, and non-increasing ranks. A bad code or category throws before any `fetch`. The `Election` generation is parsed, including the missing-key fallback.

## Repository Research

### Files Inspected

- `src/ideology_app/api/{routes,schemas,queries,http_cache}.py`: path-only routes, `cached_json`, `ApiNotFoundError`, `_version_out` (legacy body), `PUBLIC_STATUSES`.
- `tests/test_public_api.py`: exact-body, 404, 422, 304, route-set (`test_api_routes_are_get_only_without_query_or_body`), SELECT-only, OpenAPI tests. `test_reworded_statement_is_served_as_the_final_text_only` (l.1137) calls the legacy route on a v2 version and expects 200, so it moves to the new route (A2).
- `src/ideology_app/models.py`: `DatasetVersion.model_generation`, `Statement`, `StatementRewording`, `PartyPosition`, `PartyPositionProposal.constituencies`, `DatasetVersionConstituency`, `DatasetVersionCandidature.excluded_reason`, `ConstituencyStatement`, `Proposal.categories`, `Constituency`.
- `src/ideology_app/constituency_rules.py` (`effective_value`), `pipeline/v2/run.py` (`_finish_v2`, `execute_v2_run`), `pipeline/v2/gate.py` (`PhaseProposal`, `Phase4Party`), `pipeline/v2/positions.py` (`category_proposals`), `pipeline/v2/stored.py` (`dataset_version_problems`), `proposals/conflicts.py` (`counted_proposals`).
- `tests/v2_fixtures.py`: `setup` plus `v2_fake` build a v2 version with the fake provider (P in 28/31 with partial scope `b.md`, R in 28, X Excluded `no_manifesto`).
- `packages/core/src/{domain/dataset-version.ts,domain/election.ts,application/public-api.ts,infrastructure/http/public-api-client.ts,index.ts}`, `test/infrastructure/public-api-client.test.ts`, `test/application/open-share-link.test.ts` (typed `PublicApi` fake).
- `apps/web/src/features/questionnaire/useQuestionnaireData.ts`, `share/…`, `results/ExcludedPartiesNotice.tsx`: today's consumers. They stay unchanged except Election test fixtures.
- `CONSTRAINTS.md` (Public API, Phase 4), `ARCHITECTURE.md` (Public API), `docs/risks-and-open-questions.md`, `CONTEXT.md`, `docs/domain-model.md`. Read-only check of `data/ideology.db`: versions 1–5 are all `legacy`, head `0020`, 0 Proposals.

### Existing Patterns To Follow

- Response models are frozen with `extra="forbid"`, and field order is key order. Queries are SELECT-only and raise `ApiNotFoundError`. `cached_json` and `_RESPONSES` (304 plus 404 `ErrorOut`) are reused.
- Insert-only v2 tables are written only in `_finish_v2` and checked by `dataset_version_problems`. Migrations use additive `CREATE TABLE` with tests in `tests/test_migrations.py` (HEAD, upgrade, downgrade, offline render), as `0020` did.
- `packages/core` parsers throw `ContractError` with a path, and `getParsed` wraps it.

### Current Gaps

- There is no frozen record of a version's counted Proposals (A8), and no route or core type for Constituencies.

## Technical Approach

Put the v2 read model in a new `src/ideology_app/api/queries_v2.py` (SELECT only; imports `models`, `constituency_rules` and `topic_catalog`, never `pipeline.runs` or `llm`). A shared helper `_public_version(session, id)` returns the version or raises `dataset_version_not_found`. The legacy `get_public_version` and `get_published_version` raise `dataset_version_is_v2` when `model_generation is V2`, and the v2 functions raise `dataset_version_is_legacy` otherwise. The questionnaire query loads, in a fixed number of SELECTs: the Constituency row, the ranked Statements, R(c) and the Excluded rows, the Parties, the `party_positions` of (R(c) × those Statements), and their `party_position_proposals` joined with `proposals` and `source_documents`. It then assembles the result in Python with `counting_evidence` and `effective_value`, never with an SQL filter on the JSON codes. The proposals query loads `dataset_version_proposals` for R(c), keeps rows whose `constituencies` contain c, joins `proposals` (filtering `categories` in Python), and joins `source_documents.source_url`. The pipeline change passes `phase4.parties` into `_finish_v2` and inserts one row per `PhaseProposal` in counted order. The `ElectionOut` field comes from the already joined published `DatasetVersion` row (select `model_generation` next to `id`).

## Expected File Changes

- `src/ideology_app/api/schemas.py`: modify. `ElectionOut` field (A3) and the new models: `ConstituencyListOut`, `ConstituencySummaryOut`, `ConstituencyQuestionnaireOut`, `ConstituencyStatementOut`, `ConstituencyPartyOut`, `ConstituencyPositionOut`, `ProposalOut`, `ExcludedPartyOut`, `ConstituencyProposalsOut`, `PartyProposalsOut`, with OpenAPI descriptions that state S5, the dedup and the reason codes.
- `src/ideology_app/api/queries.py`: modify (A2 refusal, A3 field). `src/ideology_app/api/queries_v2.py`: create. `src/ideology_app/api/routes.py`: modify (three routes, `ConstituencyCode` and `Category` path types, docstring "Nine JSON routes").
- `src/ideology_app/constituency_rules.py`: modify (`counting_evidence`, `effective_value` through it).
- `src/ideology_app/models.py`: modify (`DatasetVersionProposal`). `src/ideology_app/migrations/versions/0021_dataset_version_proposals.py`: create.
- `src/ideology_app/pipeline/v2/run.py`: modify (`_finish_v2` writes A8). `src/ideology_app/pipeline/v2/stored.py`: modify (A8 problems).
- `data/ideology.db`: upgraded to `0021` (CONSTRAINTS migration rule).
- Tests: create `tests/test_public_api_v2.py` (scenarios 1–6, 8–10) and `tests/api_v2_fixtures.py`. The fixture inserts directly a v2 version with two available Constituencies (28, 31) and one unavailable (`01`), three Parties, one Excluded, a Proposal shared by two Parties, an Evidence row counting only in 28, a neutral (0) Position, a reworded Statement and categories with a second category. Modify `tests/test_public_api.py` (route set, OpenAPI lists, Election JSON, move the rewording test to the new route and assert the legacy 404), `tests/test_constituency_rules.py` (`counting_evidence`), `tests/test_v2_runs.py` (rows written equal `phase4`), `tests/test_v2_selection.py` (db-check problems) and `tests/test_migrations.py` (HEAD `0021`, upgrade, downgrade, offline render).
- `packages/core`: create `src/domain/constituency.ts` and `src/application/constituency-api.ts`. Modify `src/domain/election.ts`, `src/infrastructure/http/public-api-client.ts`, `src/index.ts`, `test/infrastructure/public-api-client.test.ts`, and the Election literals in `test/application/open-share-link.test.ts` and `test/domain/results.test.ts`.
- `apps/web`: only Election test literals that need the new field (e.g. `features/landing/current-election.test.ts`). No source change.

## Visual Design Impact

- UI involved: no. There is no browser-visible change. Legacy versions are served byte-identically, and the current client ignores the new Election field. A v2 version is refused with 404, and none exists in any shared or production database. **Browser check: not required** (exempt per AGENTS.md). The validator confirms the exemption by checking that `apps/web/src` has no non-test diff.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update the Public API section with the route table (three rows), the contract, the new error codes, the `queries_v2` module and `ElectionOut`. Also update the `dataset_version_proposals` storage notes.
- `CONSTRAINTS.md`: update. Add to Public API: a v2 version is never served in the legacy shape (A2), and per-Constituency values and Evidence come only through `effective_value`/`counting_evidence`. Add to Phase 4: `dataset_version_proposals` is written only by `_finish_v2`, insert-only, and the API reads Proposals only from it, never from `counted_proposals` or the ledger. Change "future v2 API" to name `api/queries_v2.py`.
- `AGENTS.md`: not needed (no workflow change).
- `docs/risks-and-open-questions.md`: close the handoff entry 61 (decided: A1–A2). Add "Open, for team review (`public-dataset-api-v2` defaults)" A1–A12. Add the open risk "per-Constituency body size without compression; measure in `e2e-2026-constituencies`". Update the Later entry on Excluded-Party notes to say the data is served (`excluded_parties`) and the web change remains `results-by-constituency`'s.
- `docs/domain-model.md` and `CONTEXT.md` (Dataset Version, v2): it also freezes each non-Excluded Party's counted Proposals with their Constituencies. `README.md`: list the three routes. `docs/technical-discovery.md`: not needed unless it lists the API routes (check).

## Implementation Plan

1. `counting_evidence` and its tests, with `effective_value` behaviour unchanged.
2. Model, migration `0021`, `_finish_v2` write and db-check problems, with their tests. Upgrade the committed DB last.
3. Schemas, `queries_v2`, the refusals and the routes. Then the direct-insert fixture and `tests/test_public_api_v2.py`, then the end-to-end check through `v2_fixtures`.
4. Update `test_public_api.py` and OpenAPI assertions.
5. `packages/core` types, port, parsers and client, with Vitest. Then update the Election literals.
6. Docs, then `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `constituency_rules.counting_evidence`, `effective_value` rewritten through it; unit tests.
- [ ] `DatasetVersionProposal` model plus migration `0021`; migration tests; `alembic check` clean.
- [ ] `_finish_v2` writes the frozen counted Proposals; test against `phase4.parties`.
- [ ] `dataset_version_problems`: the three A8 problems, with tamper tests.
- [ ] Schemas, `queries_v2.py`, routes, A2 refusals, A3 field.
- [ ] `tests/api_v2_fixtures.py` plus `tests/test_public_api_v2.py` (exact bodies, S5, unavailable, proposals, errors, caching, no-Answers, final text).
- [ ] End-to-end test with `v2_fixtures.setup` + `execute_v2_run` (`ConstituencySettings(1, 1)`): every served value equals `effective_value` recomputed from the DB rows for each available c.
- [ ] Update `tests/test_public_api.py` (route set, OpenAPI, Election JSON, rewording test moved).
- [ ] `packages/core`: `constituency.ts`, `constituency-api.ts`, parsers, client methods, `Election` field, exports, Vitest.
- [ ] Upgrade `data/ideology.db` to `0021` with nothing holding it; record before/after hashes; `db check` safe to commit.
- [ ] Docs (Durable Documentation Impact); `feature_list.json` and `PROGRESS.md` evidence.

## Verification Plan

- `.venv/bin/pytest tests/test_public_api.py tests/test_public_api_v2.py tests/test_constituency_rules.py tests/test_v2_runs.py tests/test_v2_selection.py tests/test_migrations.py tests/test_committed_database.py`, all passing. `test_exact_dataset_version_body` is unmodified (`git diff` shows no change to it or to `seed_exact_version`).
- `npx vitest run packages/core` passes, including the new client tests.
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` reports safe to commit at `0021`.
- `CI=true ./init.sh` passes (pytest, web typecheck, Vitest, build).
- Manual smoke: start uvicorn on the committed DB. `curl /api/openapi.json` lists the three operationIds. `curl /api/v1/dataset-versions/5` gives a body byte-identical to `main` (compare SHA-256). `curl /api/v1/dataset-versions/5/constituencies` gives `404 dataset_version_is_legacy`.
- No E2E harness exists for the API beyond pytest, and there is no UI change, so pytest and Vitest coverage is enough.

## Evidence To Capture

- Test counts (pytest, Vitest) and the names of the new tests. SHA-256 of `/api/v1/dataset-versions/5` before and after.
- Migration `0021` offline render summary (1 `CREATE TABLE`, no ALTER or DROP). DB SHA-256 before and after, per-table identity, and `db check` output.
- Body size of the fixture's questionnaire and proposals responses (noted as a baseline, not a target).

## Validator Checklist

- [ ] Legacy bodies and ETags are unchanged, and a v2 version is never served in the legacy shape.
- [ ] Every per-Constituency value and Evidence list goes through `effective_value`/`counting_evidence`, with no second S5 implementation (grep `constituencies` in `api/`).
- [ ] Only `statements.text` is served, and `statement_rewordings` is not referenced in `api/`.
- [ ] Routes are GET-only and path-only, query strings are ignored, only SELECTs run, and Answers have no route.
- [ ] Excluded Parties appear only in `excluded_parties`, never in `parties` or the Proposals route, and all Parties are ordered and shaped identically.
- [ ] `dataset_version_proposals` is insert-only, written only by `_finish_v2`, and the API never reads the ledger or `counted_proposals`.
- [ ] OpenAPI documents the three operations, models and error codes. `packages/core` types and parsers exist with Vitest coverage, and `apps/web/src` has no non-test change, so no browser check is needed.
- [ ] Docs and `docs/risks-and-open-questions.md` are updated as listed. Evidence is recorded in `feature_list.json` and `PROGRESS.md`.
