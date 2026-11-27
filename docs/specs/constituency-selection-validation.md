# Feature Implementation Spec: Per-Constituency Statement validity, priority order and availability

## Source Feature

- `id`: constituency-selection-validation
- `area`: pipeline
- `depends_on`: statements-from-proposals (`accepted`, PR #130 into `v2`)
- `status`: not_started at planning time (2026-11-25)
- `source`: `feature_list.json` (verification: pytest for deterministic, Party-identical per-Constituency validity and order, an unavailable Constituency with its reason, offered lengths, existing Dataset Versions unchanged; `ideology db check` passes; `CI=true ./init.sh` passes)
- Branch: `feature/constituency-selection-validation`, cut from `feature/statements-from-proposals` (749fa44, PR #130), which stacks on #125–#128 (integration PR #129). The PR goes into `v2`, never `main`.
- Owns these "Constituency redesign" entries in `docs/risks-and-open-questions.md`: the per-Constituency minimums; topic spread per Constituency; a Statement valid in no Constituency; copying candidatures into the Dataset Version; copying Excluded Parties from the ledger; the S5 handoff (`partial_scope_parties`, the `V2Pool` seam, `PUBLISH_ON_PASS[v2]`); and the `CONSTRAINTS.md` handoffs for coverage, strict lengths, separation, count range and selection v3. Each is settled below or handed off by name. `Todas (N)` only when there are fewer than 20 is already decided and is applied as is.

## Goal

A v2 run (`ideology pipeline run-v2 DIR`) gets a deterministic, AI-free, Party-identical **Constituency Selection** step between `V2Pool` and `_finish_v2`. For each of the 52 Constituencies, the Dataset Version stores: whether it is available, or its unavailable reason; the Statements valid there (S5 applied), in that Constituency's priority order; its offered lengths; and a frozen copy of the Parties running there, each Excluded one with its reason. A Constituency below the minimums is stored unavailable and the run goes on. New per-Constituency Validation checks replace legacy checks 3–6 for v2, and a passed v2 run is **published** (`PUBLISH_ON_PASS[v2] = True`). Legacy Dataset Versions 1–5, the legacy pipeline and every `/api/v1` response stay byte-identical.

## Non-Goals

- Any API, OpenAPI, `packages/` or web change (`public-dataset-api-v2`, `constituency-picker`, …). No UI, so no browser check.
- The 52-row per-Constituency table and per-Statement detail in `pipeline report|statements|positions` (`v2-run-inspection`). This feature adds only one summary line.
- Statement Rewording, the dev dataset, the real 2026 run, and its measurements (`statement-rewording`, `dev-dataset`, `e2e-2026-constituencies`).
- Changing prompts, the pool, positioning, the phase-4 gate rules, legacy `select_statements` or legacy checks 1–7.
- Ordering that favours under-covered Parties (leximin or similar). Order is by the key in K2 only.

## Job Story

When a v2 run has drafted and positioned its Statement Pool,
I want each Constituency's Questionnaire, its lengths and its availability fixed in the Dataset Version by deterministic rules,
so a Voter only sees Statements that separate the Parties on their own ballot, and the version publishes even if a Constituency cannot be served.

## Users And Permissions

- Operator: runs `pipeline run-v2` (unchanged options), and reads `pipeline report --run R` and `db check`. Tunes the two minimums through environment variables and replays them with `--reuse-from` (0 LLM calls).
- Voter: nothing visible yet. `public-dataset-api-v2` serves the new rows.

## Decisions (K1–K12 are defaults for team review)

Terms: R(c) = the non-Excluded Parties running in c (from the snapshot, K9). E(c) = the Excluded Parties running in c. A value is *sided* at ±1/±2; 0 and `no stance` are on neither side.

**S5 rule (one pure function, single source).** `effective_value(value, evidence_constituencies, code)` returns `value` when one of the Position's Evidence rows lists `code` in `party_position_proposals.constituencies`, and `None` (`no stance`) otherwise. A `no stance` Position stays `None`. It lives in the new pure module `src/ideology_app/constituency_rules.py` (stdlib only, like `constituencies.py`). Selection, the Validation checks and, later, `public-dataset-api-v2` must all call it, so the rule never forks. The Parties in `partial_scope_parties` are the ones where it changes a result. They need no special path.

**K1 Validity.** Statement s is valid in c when, among R(c) with S5 values, at least one Party is in favour and at least one is against. There is no "at least 3 Parties" rule: the legacy `min_statement_parties` is not applied, because the user decision names only the two-sides rule. With fewer than 2 Parties in R(c), nothing is valid.

**K2 Priority order.** The valid Statements of c are ranked by `(-sided_c, -separation_c, statements.position)`. `sided_c` counts the R(c) Parties with a side. `separation_c = min(favour_c, against_c)`. `statements.position` is the pool order, a total and Party-blind tie-break. This is the legacy v3 key, applied per Constituency. Then comes **topic deferral**, the same mechanism as legacy `topic_caps`/`_cap_at`. For each offered length L **strictly below** n(c), `cap_L = max(1, max_topic_share_percent * L // 100)`, using the existing `VALIDATION_MAX_TOPIC_SHARE_PERCENT` (30). At position k ≤ the largest such L, the rule takes the first remaining ranked Statement whose topic (category) has fewer than `cap(k)` placed so far, where `cap(k)` is the cap of the first such L ≥ k. If none fits, it takes the first remaining Statement. Past that, there is no cap. Every valid Statement is placed, so the Questionnaire is always all of them and every length is a prefix. Ranks are 1..n.

**K3 Minimum valid Statements = 10** (`VALIDATION_V2_MIN_STATEMENTS`, an integer ≥ 1). The briefing suggested 20, but a minimum of 20 would make `Todas (N)` (offered only below 20, a user decision) impossible. With 10, a Constituency with 10–19 valid Statements offers `Todas (N)`. Below 10, half the questionnaire or more would sit under the low-coverage flag (M < 5), so the Constituency is unavailable. S3 estimates 80 or more valid Statements per Constituency (Ceuta/Melilla 50–70), so 10 only catches real data gaps.

**K4 Per-Party coverage = 5 sided Statements** (`VALIDATION_V2_MIN_PARTY_SIDES`, an integer ≥ 1). Every Party in R(c) must take a side (S5) on at least 5 of c's valid Statements. 5 is `LOW_COVERAGE_THRESHOLD` of the matching rule (`packages/core/src/domain/match-score.ts`): below it, a Party is flagged "low coverage" even for a Voter who answers everything. The count is absolute over the full set, not a percentage per prefix. With 50–250 valid Statements, the legacy 50 %-per-length rule would make most Constituencies unavailable because of one small Party, and the Voter can always extend to the full set. Sides within the first offered length are recorded in the report, not enforced (risk entry for `e2e-2026-constituencies`).

**K5 Unavailable reasons, first that applies:** `fewer_than_two_parties` (|R(c)| < 2; `detail {"parties": k}`), `too_few_statements` (n < K3; `detail {"statements": n, "minimum": m}`), `low_party_coverage` (`detail {"parties": [{"party_id", "sides"}…] by party id, "minimum": k}`). Codes are stored and the UI maps them to Spanish copy later. Every code reads as "lack of manifestos" in the user's sense.

**K6 Topic spread per Constituency: ordering only.** Topic deferral (K2) shapes the order. The max topic share per offered length is recorded in the report. It never makes a Constituency unavailable and never fails the run: n(c) is fixed by validity, so only the order can respond, and hiding a whole Constituency over a presentation issue would hurt the Voter more than it protects them. Legacy check 6 is not applied to v2.

**K7 A Statement valid in no available Constituency stays in the Dataset Version.** It keeps its Positions and Evidence (auditable, and `statements.position` stays the pool order across `--reuse-from` replays with other thresholds). It gets no `constituency_statements` row, so it is never in a Questionnaire. The report counts them (`valid_nowhere`). `public-dataset-api-v2` serves Questionnaires only from `constituency_statements`. Dropping such Statements was rejected: it would hide AI output from inspection and couple the stored pool to the thresholds.

**K8 The run fails when no Constituency is available** (`constituency_availability` entry `no constituency is available`). Publishing it would supersede a working version with an unusable one. One or more available Constituencies: the run passes and publishes.

**K9 Snapshot.** In `load_phase4` the run copies `candidatures_by_party` for every manifest Party in phase `proposals_extracted` or `excluded`, matched by short name as today. An Excluded Party with no candidature row raises the same `Phase4Error` as an Extracted one. Each Excluded Party's ledger reason comes from `party_states`. It is written once, per Constituency, with the Dataset Version and never read live again. The ledger's free-text `note` is not copied (Operator text, not Voter data).

**K10 Offered lengths are a code constant** `OFFERED_LENGTHS = (20, 30, 40, 50)` (user decision; not configurable). For n < 20 the result is `[n]`, presented as `Todas (N)`. Otherwise it is `[L for L in OFFERED_LENGTHS if L <= n]`. An unavailable Constituency gets `[]`.

**K11 Unavailable Constituencies store no ordered rows.** `valid_statement_count` still records n(c), and `detail` says why.

**K12 Publishing.** `PUBLISH_ON_PASS[ModelGeneration.V2] = True`, with the unchanged rule: run-id order, supersede the Election's Published version of either generation. A v2 publish on an Election whose Published version is legacy supersedes it. That is the intended path for 2026 (`e2e-2026-constituencies`). The `Not published: v2 …` CLI line (`V2_NOT_PUBLISHED`) is removed.

**Storage (migration `0019`, hand-written, three new empty tables; no table recreated; insert-only; written only by `_finish_v2`).** Named constraints use `op.f` as in `0018`. Reason columns are `String` with one named CHECK, not `sa.Enum`.
- `dataset_version_constituencies`: PK `(dataset_version_id → dataset_versions CASCADE, constituency_code → constituencies.code)`; `available BOOLEAN NOT NULL`; `unavailable_reason VARCHAR(30) NULL`; `valid_statement_count INT NOT NULL` (CHECK ≥ 0); `offered_lengths JSON NOT NULL`; `detail JSON NULL`. CHECK `ck_…_reason_matches_available`: `(available AND unavailable_reason IS NULL) OR (NOT available AND unavailable_reason IN ('fewer_than_two_parties','too_few_statements','low_party_coverage'))`. 52 rows per v2 version.
- `dataset_version_candidatures`: PK `(dataset_version_id → dataset_versions CASCADE, party_id → parties CASCADE, constituency_code → constituencies.code)`; `excluded_reason VARCHAR(30) NULL` with CHECK `IN ('no_manifesto','discarded_at_review','too_few_proposals')`. This table holds both "who runs where" and "Excluded per Constituency with reason".
- `constituency_statements`: PK `(dataset_version_id → dataset_versions CASCADE, constituency_code → constituencies.code, rank)`, CHECK `rank >= 1`; `statement_id → statements CASCADE`; UNIQUE `(dataset_version_id, constituency_code, statement_id)`.
- Models: `DatasetVersionConstituency`, `DatasetVersionCandidature`, `ConstituencyStatement`. Legacy versions have no rows. The committed `data/ideology.db` is upgraded 0018 → 0019.

**Settings and recording.** `config.ConstituencySettings(v2_min_statements=10, v2_min_party_sides=5)` and `config.constituency_settings()`. The env vars hold integers ≥ 1; anything else raises `ConfigError`, the same style as `_positive_int_env`. These fields are kept out of `ValidationSettings` so that legacy runs record exactly what they record today. A v2 run records `validation_settings = asdict(settings) | asdict(constituency_settings)` (flat keys). `statement_selection` gains the key `"constituencies"`: `{"version": "v2-constituency-1", "settings": {…, "max_topic_share_percent"}, "available": a, "unavailable": [{"code", "reason"}], "valid_nowhere": [pool positions], "rows": [{"code", "parties", "excluded", "valid", "lengths", "party_sides": [{"party_id", "sides", "first_length_sides"}], "topic_max_share": [per offered length]}]}`. `REPORT_VERSION` stays `v2-pool-1`, so `pool_summary` is unchanged.

**Validation (replaces legacy checks 3–6 for v2).** `V2_CHECKS` = the five existing checks, then, in this order (stable names ≤ 50 chars, messages prefixed `constituency CC: `):
1. `constituency_snapshot`: exactly one constituency row per seeded code. Every Party with Positions has ≥ 1 candidature row and no `excluded_reason`. A Party with an `excluded_reason` has no Positions and the same reason on every row. Every Evidence row's Constituencies ⊆ its Party's snapshot codes.
2. `constituency_validity` (check 4, per c): in an available c, the listed Statements are exactly the K1-valid ones. An unavailable c lists none.
3. `constituency_availability` (checks 3 and 5, per c): available ⇔ the K5 rules pass; the reason is the first failing rule; `valid_statement_count` = n(c); `offered_lengths` = K10. Plus the K8 run-level entry.
4. `constituency_order`: ranks are 1..n and equal the K2 order recomputed by `constituency_rules.priority_order` from the stored Positions, Evidence and snapshot.

By construction they pass. A failure means rows were corrupted or written inconsistently, and fails the run. A Constituency below a minimum is never a check failure: selection stores it unavailable (domain wording: "a failure makes that Constituency unavailable" is applied before writing, and Validation confirms it). `ValidationInput` gains `constituency_settings`, `candidatures` (party → codes), `excluded` (party → reason), `constituency_rows` and `constituency_statements` (code → Statement ids by rank), filled by `load_input` for v2 only.

**`pipeline report` (v2 only; legacy output unchanged).** After the `statement_selection` line, one line: `constituencies: 50 available, 2 unavailable (31 fewer_than_two_parties, 51 too_few_statements); 3 statements valid in no available constituency`, read from the tables (`not recorded` without a Dataset Version). `pipeline run-v2` prints the same counts after the publish line. The 52-row table goes to `v2-run-inspection`.

**`db check` / `data check`.** `db check` adds `pipeline.v2.dataset_version_problems(session)`. Every v2 Dataset Version has 52 constituency rows and ≥ 1 candidature row. Each available row's ranks are 1..`valid_statement_count`. Legacy versions have no rows in the three tables. Each problem is an `Error:` line → `Safe to commit: no`. `data check` is unchanged: it must **not** compare snapshots with live candidatures, because a later BOE import must not invalidate published versions.

## Acceptance Scenarios

1. **Two Constituencies, one unavailable.** Given the `v2_fixtures` Election (P in 28 and 31, R in 28, X Excluded in 28) and `ConstituencySettings(1, 1)`, when `run-v2` runs with the canned fake, then the version has 52 constituency rows; 28 is available with its valid Statements (expected: both, P against R on each) in K2 order and lengths `[n]`; 31 is `fewer_than_two_parties`; the other 50 are `fewer_than_two_parties` with `parties: 0`; the snapshot has P×{28,31}, R×{28}, X×{28} with `no_manifesto`; the run is `passed` and **published**.
2. **S5.** Given a Party whose only Evidence for a Statement counts in 28, when c = 31, then its value there is `no stance`. If that leaves 31 with no Party against, the Statement is not valid in 31 but is valid in 28.
3. **Order and ties.** Given Statements with equal `sided_c` and `separation_c`, they follow pool order. Given more Statements of one topic than `cap(20)` within the top 20 of a c with n ≥ 21, the excess Statements move after position 20, and nothing is dropped.
4. **Lengths.** n = 9 → `too_few_statements`; 12 → `[12]`; 20 → `[20]`; 37 → `[20, 30]`; 55 → `[20, 30, 40, 50]` (defaults).
5. **Coverage.** A Party in R(c) with 4 sided valid Statements → `low_party_coverage` with that Party in `detail`; the run still passes if another Constituency is available.
6. **None available.** With default minimums on the fixture, the run fails (`validation failed: constituency_availability`), and nothing is published.
7. **Party symmetry and determinism.** Relabelling Party ids (permuting which Party owns which values and candidatures) gives the same rows up to the relabelling, and two selections of the same input are equal (`==`, JSON-identical reports).
8. **Tampering.** For each of the four new checks, a test edits one stored row of a `validating` run (in the test only) and `validate_run` fails with that check's name.
9. **Replay.** `--reuse-from R` with other `VALIDATION_V2_*` values makes 0 LLM calls, and the new availability follows the new thresholds. Publishing follows run-id order.
10. **Legacy unchanged.** Dataset Versions 1–5 have no rows in the new tables. On a scratch copy of the committed DB, `pipeline report|checks|statements|positions` for runs/versions 1–5, `pipeline list`, `data check` of both bundles, `db check`, and `GET /api/v1/elections` and `/dataset-versions/1..5` are byte-identical to 749fa44.
11. **Migration.** `0019` creates exactly the three tables with one CHECK per rule (SQLite `sqlite_master` and the offline PostgreSQL render). `alembic check` reports no drift. Downgrade to 0018 drops them and keeps every other row. On the committed DB, every pre-existing table hashes identically before and after, and `db check` prints `Safe to commit: yes`.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/v2/{run,gate,positions,pool,__init__}.py`: the `V2Pool` seam, `_finish_v2` (one commit), `load_phase4` (snapshot source), `EvidenceRef.constituencies`, every Party has one `V2Position` per Statement.
- `pipeline/selection.py`: v3 key `(-parties, -separation, n)`, `topic_caps`/`_cap_at`, the report shape and the symmetry style. `pipeline/publishing.py`: `PUBLISH_ON_PASS`. `pipeline/runs.py`: `validate_run` (checks by generation, records `asdict(settings)`). `pipeline/reports.py` and `cli.py` (`pipeline_report`, `_echo_publish`, `V2_NOT_PUBLISHED`, `pipeline_run_v2`, `db_check`/`_bundle_and_run_checks`, `data_check`).
- `validation/{__init__,base}.py` (`V2_CHECKS`, `checks_for`, `ValidationInput`, `load_input` v2 branch), `config.py` (`ValidationSettings`, env parsing), `models.py` (DatasetVersion, Statement, PartyPosition, `PartyPositionProposal.constituencies`, Candidature, Constituency, `ModelGeneration`), and migration `0018` (style).
- `bundle_import.candidatures_by_party` / `document_scopes`, `ingestion_ledger.{Phase, ExclusionReason, PartyEntry, party_states}`, and `constituencies.CONSTITUENCIES`.
- `tests/v2_fixtures.py`, `test_v2_runs.py`, `test_validation_v2.py`, `test_cli_pipeline_v2.py`, `test_migrations.py`, `test_pipeline_selection.py`, `test_config.py`, `test_cli_pipeline_report.py`.
- `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md`, `docs/risks-and-open-questions.md` ("Constituency redesign"), `CONSTRAINTS.md` (Pipeline, Phase 4, Validation, Constituencies), `ARCHITECTURE.md` (Phase 4, Validation, Public API), `packages/core/src/domain/match-score.ts` (`LOW_COVERAGE_THRESHOLD`).

### Existing Patterns To Follow

- Pure, deterministic modules with no iteration over unordered sets, plus symmetry tests (`selection.py`, `test_pipeline_selection.py`). Plain-data inputs (`Phase4Input`) usable after the session closes.
- Hand-written additive migrations with `op.f` names, upgrading the committed DB with no process holding it and with table hashes compared (Session 125 evidence). Checks as `Check(name, run)` returning `ReportEntry` lists.

### Current Gaps

- No per-Constituency storage, selection or checks. `Phase4Input` drops Excluded Parties and candidatures. A passed v2 run stays `candidate`.

## Technical Approach

1. `constituency_rules.py` (pure): `OFFERED_LENGTHS`, `UnavailableReason` (StrEnum), `effective_value`, `offered_lengths(n)`, `valid_statements(...)`, `priority_order(...)` (K2), `availability(...)` (K5). Inputs are plain tuples: Statement position, topic, per-Party `(value, evidence codes)`, R(c) and the minimums.
2. `gate.load_phase4` also returns `candidatures: Mapping[int, tuple[str, …]]` and `excluded: tuple[ExcludedParty(party_id, short_name, reason), …]` (sorted by party id; new fields with defaults).
3. `pipeline/v2/selection.py`: `select_constituencies(pool, phase4, settings, csettings) -> ConstituencySelection(rows, statements_by_code, snapshot, report)`, over the 52 `CONSTITUENCIES` in code order. `execute_v2_run(..., constituency_settings=None)` calls it after `V2Pool`; `_finish_v2` writes the three tables (Statement ids from the inserted rows) and `statement_selection["constituencies"]` in the same commit.
4. `validation/constituencies.py`: the four checks. `load_input` and `ValidationInput` are extended; `V2_CHECKS` is extended.
5. `validate_run(..., constituency_settings=None)`: for a v2 run with `None`, it reads the generation first (read-only), then `config.constituency_settings()` before the checking session, so a `ConfigError` changes nothing. A legacy run never reads the new variables.
6. Flip `PUBLISH_ON_PASS[v2]`. Then the CLI: settings read with the others, the summary line in `run-v2` and `pipeline report`, `db check` problems, `V2_NOT_PUBLISHED` removed.
7. Migration `0019`, models, the committed DB upgrade, and the docs.

## Expected File Changes

- Create: `src/ideology_app/constituency_rules.py`, `src/ideology_app/pipeline/v2/selection.py`, `src/ideology_app/validation/constituencies.py`, `src/ideology_app/migrations/versions/0019_constituency_selection.py`, `tests/test_constituency_rules.py`, `tests/test_v2_selection.py`, `tests/test_validation_constituencies.py`.
- Modify: `models.py`, `config.py`, `pipeline/v2/{gate,run,__init__}.py`, `pipeline/publishing.py`, `pipeline/runs.py` (`validate_run`), `pipeline/reports.py`, `validation/{__init__,base}.py`, `cli.py`; tests `test_v2_runs.py`, `test_cli_pipeline_v2.py` (pass `ConstituencySettings(1, 1)` where a pass is expected; publish instead of `candidate`, by design), `test_validation_v2.py`, `test_migrations.py` (+0019, head pins), `test_config.py`, `test_shared_db.py` or the `db check` tests, plus shared-head pins in the feedback tests if they pin the head; `data/ideology.db` (0019).

## Visual Design Impact

- UI involved: no. Design source: not applicable. No browser check (no browser-visible change).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Phase 4 (`selection.py`, the tables, the publish flip), Validation (the four checks, `ConstituencySettings`), Data Layer (`constituency_rules` is pure, used by pipeline, validation and later the API).
- `CONSTRAINTS.md`: update. Mark the rules on selection v3 / `select_statements`, questionnaire lengths, coverage, separation, count range and topic share (lines 83, 92, 113–116 at 749fa44) "Legacy pipeline only". Replace line 105 (`PUBLISH_ON_PASS`) with the v2 publish rule. Add under Phase 4: (a) per-Constituency rows MUST be computed only by `constituency_rules` via `pipeline.v2.selection`, before the write, deterministic and Party-identical, with thresholds only from the run's settings; (b) the three tables MUST be written only by `_finish_v2` in the Dataset Version's commit, insert-only; (c) a Constituency below a minimum MUST be stored unavailable and MUST NOT fail the run; (d) readers MUST apply S5 only through `constituency_rules.effective_value`; (e) a written Statement MUST NOT be dropped because it is valid nowhere; (f) `data check` MUST NOT compare snapshots with live candidatures. Lines 20 and 28 (copy, not read live): mention the tables.
- `AGENTS.md`: not needed (no workflow change).
- `CONTEXT.md` / `docs/domain-model.md`: replace "open, owned by `constituency-selection-validation`" (Statement Selection, Validation v2, edge cases Ceuta/Melilla) with K1–K8. Name the four checks and the publish flip. Remove "stays `candidate` until …".
- `docs/technical-discovery.md`: a "Constituency selection" section listing K1–K12, the env vars and the report shape.
- `docs/risks-and-open-questions.md`: settle the owned entries. Add "Open, for team review (`constituency-selection-validation` defaults)" with K1–K12, highlighting K3 (10 vs the suggested 20) and K4 (one Party can make a Constituency unavailable). New: (a) `e2e-2026-constituencies` measures per-Constituency n(c), availability and `first_length_sides` (a Party with 0 sides in the first 20 gets no score at that length); (b) handoff `public-dataset-api-v2`: decide what `/api/v1/dataset-versions/{id}` does with a published v2 version (today it would serve the whole pool in the legacy shape), and serve Questionnaires only from `constituency_statements` with `effective_value`; (c) handoff `v2-run-inspection`: the 52-row table; (d) handoff `methodology-v2`: describe K1–K6.

## Implementation Plan

1. Pure rules and their tests: validity, S5, K2 with deferral, K5, K10, symmetry.
2. Gate snapshot fields, then `select_constituencies` with its report.
3. Migration `0019`, models, migration tests; `_finish_v2` writes.
4. Validation checks, `load_input`, `validate_run` settings, tamper tests; flip the publish switch.
5. CLI (settings, summary lines, `db check`), the existing tests adjusted.
6. Upgrade the committed DB on a quiet file. Run the legacy byte-identity comparison on scratch copies. Update the docs and `feature_list.json` / `PROGRESS.md`.

## Implementation Tasks

- [ ] `constituency_rules.py` + `tests/test_constituency_rules.py` (scenarios 2–5, 7).
- [ ] `ConstituencySettings`, `constituency_settings()`, `test_config.py` cases (unset, valid, 0, `1.5`, `x`).
- [ ] `load_phase4` `candidatures`/`excluded`; `pipeline/v2/selection.py` + `tests/test_v2_selection.py`.
- [ ] Migration `0019` + models + `test_migrations.py` (DDL, CHECKs, downgrade, no drift).
- [ ] `_finish_v2` writes the tables and the report key; `execute_v2_run` parameter.
- [ ] `validation/constituencies.py`, `ValidationInput`/`load_input`, `V2_CHECKS`, `validate_run`; `tests/test_validation_constituencies.py` (scenario 8).
- [ ] `PUBLISH_ON_PASS[v2] = True`; remove `V2_NOT_PUBLISHED`; run-v2 and report summary lines; `dataset_version_problems` in `db check`.
- [ ] Adjust `test_v2_runs.py`, `test_cli_pipeline_v2.py`, `test_validation_v2.py`; scenarios 1, 6, 9 end to end.
- [ ] Upgrade `data/ideology.db`; run the scenario 10 and 11 evidence; update the docs listed above.

## Verification Plan

- `.venv/bin/pytest tests/test_constituency_rules.py tests/test_v2_selection.py tests/test_validation_constituencies.py tests/test_v2_runs.py tests/test_validation_v2.py tests/test_cli_pipeline_v2.py tests/test_migrations.py tests/test_config.py tests/test_pipeline_selection.py tests/test_cli_pipeline_report.py tests/test_public_api.py` passes. FakeProvider only, with the offline guard in every new module.
- `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` → `Safe to commit: yes` after the upgrade (lsof empty, no sidecars). Pre-existing table hashes are identical before and after.
- Scenario 10 on scratch DB copies against `git archive 749fa44` (as in Session 125). Manual CLI walk on a scratch format-2 bundle and DB with the canned v2 fake: `run-v2` with defaults → failed (K8); with `VALIDATION_V2_MIN_STATEMENTS=1 VALIDATION_V2_MIN_PARTY_SIDES=1` → passed and published, plus the summary line; `pipeline report --run R` shows the line.
- `CI=true ./init.sh` exits 0. No E2E/browser coverage: no API or UI change (the API is `public-dataset-api-v2`).

## Evidence To Capture

- Test counts (new and total), the `init.sh` result, the scenario-to-test mapping, the DDL listing for `0019`, the committed-DB file SHA-256 before and after plus the table hashes, the legacy byte-identity list, the manual CLI walk output lines, and any spec deviations. Record in `feature_list.json` evidence and a `PROGRESS.md` session entry.

## Validator Checklist

- [ ] Scenarios 1–11 reproduced, with FakeProvider or no provider; no real LLM call.
- [ ] Selection is pure, with no randomness, clock, LLM or unordered iteration; the relabelling test exists and passes; Statements are never edited, and valid-nowhere Statements are kept (K7).
- [ ] S5 is applied only through `constituency_rules.effective_value` (grep).
- [ ] `0019` is additive; the committed DB is at 0019 with pre-existing tables identical; `db check` is safe.
- [ ] Legacy outputs (CLI and API, runs and versions 1–5) are byte-identical; legacy runs record the same `validation_settings` keys as before.
- [ ] Docs updated as listed, with team-review defaults K1–K12 in the risks doc; `feature_list.json` and `PROGRESS.md` updated; no API, web or prompt change.

## Implementation Notes (2026-11-25, implementer)

Deviations and choices made where the spec left room; none changes a decision K1–K12.

- **CHECK `reason_matches_available`** reads `(available AND unavailable_reason IS NULL) OR (NOT available AND unavailable_reason IS NOT NULL AND unavailable_reason IN (…))`. The spec's text without `IS NOT NULL` lets an unavailable row with a NULL reason pass (the `IN` test is NULL, and a NULL CHECK passes); `test_0019_constraints_and_cascades` covers it. The count CHECK is named `ck_dataset_version_constituencies_count_nonnegative`. Convention-generated FK / UNIQUE names longer than 63 characters are truncated with a hash suffix on PostgreSQL, identically for the model and the migration (offline render checked).
- **`ValidationInput`**: `candidatures` is a tuple of `SnapshotRow(party_id, code, excluded_reason)` rather than two maps (party → codes, party → reason), so `constituency_snapshot` can see two different reasons for one Party; `constituency_rows` is a tuple of `ConstituencyRowData` in code order; `constituency_statements` maps code → `(rank, statement_id)` pairs so `constituency_order` can check the ranks.
- **`constituency_snapshot`** also reports a non-Excluded Party of the copy that has no Positions (true by construction; it would otherwise count in R(c) with only `no stance`).
- **`select_constituencies(statements, positions, phase4, max_topic_share_percent, settings)`** takes the `V2Pool` fields rather than the `V2Pool` itself, so `selection.py` does not import `run.py` (which imports it).
- **New module `pipeline/v2/stored.py`** (read-only): `constituency_summary` and `dataset_version_problems`, kept out of the pure `selection.py`.
- **`low_party_coverage` detail** lists only the Parties below the minimum (sorted by id). **`topic_max_share`** is the largest share of one topic in each offered prefix, in percent rounded down.
- **Output**: `run-v2` prints `Constituencies: …` after the publish line; `pipeline report` prints `constituencies: …`. `pipeline validate` turns a `ConfigError` from `VALIDATION_V2_*` into a one-line error.
- **Tests**: `test_v2_runs._run` passes `ConstituencySettings(1, 1)` (the fixture has 2 Statements); `test_omitted_statement_is_no_stance_and_counted_as_source_party` now expects K8 (`validation failed: constituency_availability`), since nothing separates the two Parties anywhere. The `db check` CLI case is in `test_cli_pipeline_v2.py`; the problem lines are tested in `test_v2_selection.py`. `test_shared_db.py` needed no change.
