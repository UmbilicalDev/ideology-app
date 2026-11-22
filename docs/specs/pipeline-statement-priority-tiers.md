# Feature Implementation Spec: Larger extraction and Statements ranked by how many Parties take a stance

## Source Feature

- `id`: pipeline-statement-priority-tiers
- `area`: pipeline
- `depends_on`: `pipeline-statement-clarity-context` (accepted). Developed on `feature/pipeline-statement-priority-tiers`, stacked on `three-option-scale`, `questionnaire-quick-answer` and `pipeline-statement-clarity-context` (PRs #110–#112 into `v2`). Merges into `v2`, never `main`.
- `status`: `not_started` at planning time
- `source`: `feature_list.json`. User decisions in `docs/risks-and-open-questions.md`, "Voter feedback round 1" (2026-11-21, settled).

## Goal

Voters want shorter questionnaires made of the issues most Parties address, and the published Dataset Version 5 (Election 2) was built the other way round:

- extraction is capped: 67 of 68 `statement_candidates` calls of run 5 returned exactly 12 candidates, the schema maximum;
- Statements are chosen for worst-Party coverage, not for how many Parties address them;
- separation counts distinct values, so a Statement where every Party is +1 or +2 passes check 4 but separates no one on the three-option scale.

After this feature, a Pipeline Run:

1. Extracts every concrete proposal: `statement_candidates` v2, up to 30 per chunk. The Party-balanced Agenda grows to 40 per Party, and the Statement Pool to 100..140 (target 120).
2. Selects deterministically (`SELECTION_VERSION` v3). It leaves out Statements that do not separate the Parties **by side** (at least one Party in favour, +1/+2, and one against, −1/−2) and those that fewer than `min_statement_parties` (default 3) Parties take a side on. It ranks the rest by the number of Parties with a side; ties go to the more even split, then to pool order.
3. Writes the Dataset Version **in priority order** (position 1 = most Parties), with up to 40 Statements. It records the offered **questionnaire lengths** on the version (e.g. `[15, 30, 40]`), so a questionnaire of length N is always the first N Statements.
4. Validates every offered length: party coverage and topic spread run on each prefix (15, 30 and the full set). Separation and coverage follow the side rule. The count check also verifies the stored lengths.
5. Shows each pool Statement's Party count and tier in `pipeline report`. Serves `questionnaire_lengths` in `/api/v1` and reads it in `packages/core`. Updates `/metodologia`.

## Non-Goals

- No real LLM run and no new Dataset Version in `data/ideology.db`. That is `e2e-2026-dataset-clarity`.
- No Voter UI for choosing a length, no context-note disclosure, and no change to how results or Share Links handle a prefix. Those are `questionnaire-length-and-context`. The only web changes are the `/metodologia` copy and the `packages/core` type and parser.
- No change to the Share Link codec (decision in Technical Approach §9).
- No change to `position_findings` v5 or `party_positions` v2: same text, schema and `max_tokens`, and request hashes byte-identical. No change to chunking, Statement batches (20), anchors, context notes or the evidence rule.
- No anchor preference in the ranking: anchors still win or lose like any other pool Statement.
- No per-Party coverage policy, no regional Statements, and no lowering of the 50 % coverage default.

## Job Story

When a Voter has time for only a few Statements,
I want the questionnaire to start with the issues that most Parties take a side on, with each shorter length as balanced as the full one,
so I can get a meaningful ranking in 15 Statements, or a finer one in 30 or 40.

## Users And Permissions

- Operator (CLI): `pipeline run [--reuse-from R]`, `pipeline report --run N` (read-only), `db upgrade`, `db check`, and the new `VALIDATION_*` variables.
- Voter: sees the `/metodologia` copy. `questionnaire_lengths` reaches the Voter only through the API (no UI here).
- Nobody edits AI output. Lengths are computed by deterministic code from settings and never edited.

## Acceptance Scenarios

1. **Candidate prompt v2.** `PROMPT_VERSIONS == {"statement_candidates":"v2","generate_statements":"v7","position_findings":"v5","party_positions":"v2"}`. `CandidateList` accepts 0..30 candidates and rejects 31. `STATEMENT_CANDIDATES.max_tokens == 8192`. `STATEMENT_CANDIDATES.system` and `GENERATE_STATEMENTS.system` contain every rule line of §1 verbatim, and neither contains "escala de 5 puntos". `CANDIDATE_REQUEST_HASH` and the two fingerprints are re-pinned, with a comment saying so. `FINDINGS_REQUEST_HASH`, `POSITIONS_REQUEST_HASH` and the `position_findings`/`party_positions` fingerprints pass unedited. In `test_position_requests_are_byte_identical` only the `PROMPT_VERSIONS` literal changes.
2. **Pool and budget.**
   - `pool_bounds(ValidationSettings()) == (100, 140, 120)`. A fake reduce answer of 99 or 141 Statements raises `LLMOutputError`, the run ends `failed`, and no position call is made.
   - `finding_list_schema(n)` still allows at most 80 findings.
   - `MAX_POSITION_CALLS_PER_RUN == 600`. `plan_position_calls` with 68 chunks over 12 Parties and the 140 maximum gives 68 × 7 + 12 = 488 calls, which passes.
3. **Agenda v2.** `AGENDA_VERSION == "v2"` and `PARTY_QUOTA_MAX == 40`. With `pool_max` 140 and 12 Parties that each have ≥ 40 unique candidates, every Party contributes 40. The existing symmetry and short-Party tests pass.
4. **Separation by side (check 4).**
   - A Statement with values {+1, +2, +2} fails with `statement 3 does not separate parties: no party is against (3 in favour)`.
   - {−1, −2} fails with `… no party is in favour (2 against)`.
   - {0, 0} fails with `… no party is in favour or against`.
   - No values at all fails with `… no party has a stance` (message unchanged).
   - {+1, −1, 0} passes, and so does {+2, −1}. An Election with fewer than 2 Parties still gives one Election-level entry.
5. **Coverage counts sides, per length (check 3).**
   - A Party position counts only when its value is not `None` and not 0.
   - For each offered length L, ascending, the check runs on the first L Statements in position order.
   - Prefix entries read `first 15 statements: party 3 is in favour or against on 7 of 15 statements (46%); minimum is 50%`. The full-set entry has no prefix: `party 3 is in favour or against on 17 of 40 statements (42%); minimum is 50%`.
   - Entries are ordered by length, then by `party_ids`.
6. **Topic spread per length (check 6).** It runs on every offered prefix the same way. A topic with 5 of the first 15 fails: `first 15 statements: topic housing has 5 of 15 statements (34%); maximum is 30%`. The full-set message is unchanged.
7. **Count and lengths (check 5).**
   - The count range is unchanged in form (now 35..40 by default).
   - The check also compares the stored lengths with `tuple(L for L in settings.questionnaire_lengths if L < n) + (n,)`. Stored NULL or `()` is read as `(n,)`.
   - A mismatch adds `questionnaire lengths are 15, 40; expected 15, 30, 40`.
8. **Eligibility (selection v3).** Each pool Statement gets exactly one status:
   - `context_invalid` (rule 0, unchanged);
   - else `duplicate` (rule 1, among the eligible, unchanged);
   - else `not_separating` (favour = 0 or against = 0; every Statement when there are < 2 Parties);
   - else `few_parties` (favour + against < `min_statement_parties`);
   - else it is ranked.
   Non-separating Statements are never used to fill up to the minimum: tier-2 fill is removed.
9. **Priority order.**
   - Ranking key: `(-parties, -min(favour, against), pool_no)`.
   - Positions are filled 1..`max_statements` from that ranking. At position k, take the first ranked Statement whose topic count is below `cap(k)`; a Statement skipped there is tried again at k+1.
   - The result is deterministic (two calls give equal JSON) and Party-symmetric: permuting which Party owns which values changes only Party ids in the report.
   - Given 20 eligible Statements with 9, 9, 8, … Parties, the Dataset Version's positions follow that order. Topic caps (defaults 4 / 9 / 10) can defer a Statement but never reorder Statements of different topics otherwise.
10. **Dataset Version written in priority order.**
    - n = the largest count in `[min_statements, min(max_statements, L)]` whose full-set coverage passes; otherwise the best ratio, or `short` (as in v2, on the priority sequence).
    - Statements are written in sequence order, with positions 1..n. Text, topic, note and Positions/Evidence are identical to the pool entry.
    - `dataset_versions.questionnaire_lengths == [15, 30, n]`.
    - `check_topic_spread` passes on every prefix of every selection.
11. **A failing length fails the run (strict; Settled Decision 1).** Take a constructed pool where Party 3 takes a side only on Statements ranked 16 and below. The run ends `failed`, `validation failed: party_coverage`, with a `first 15 statements: party 3 …` entry. The Dataset Version stays `candidate` and nothing is published. The selection report's `projected_failures` lists `party_coverage`.
12. **Configuration.** `config.validation_settings()` reads:
    - `VALIDATION_QUESTIONNAIRE_LENGTHS` (default `15,30`; `none` = no shorter length);
    - `VALIDATION_MIN_STATEMENT_PARTIES` (default 3);
    - the new defaults `VALIDATION_MIN_STATEMENTS` 35 and `VALIDATION_MAX_STATEMENTS` 40.
    The following raise `ConfigError` before any write or LLM call: lengths that are not strictly increasing positive integers, a length ≥ the min statements, `0`, signs, decimals, and empty entries other than blank. The run's `validation_settings` JSON records both new fields.
13. **Storage, API, core.**
    - Migration `0015` adds nullable JSON `dataset_versions.questionnaire_lengths`. Dataset Versions 1–5 keep NULL, and every other column and the partial index are unchanged.
    - `GET /api/v1/dataset-versions/{id}` returns `questionnaire_lengths`: the stored list, or `[statement count]` when NULL (DV5 → `[32]`).
    - `packages/core` `DatasetVersion.questionnaireLengths` reads it. A missing key reads as `[statements.length]`. A list that is not strictly increasing positive integers ending at `statements.length` throws `ContractError`.
14. **Report.**
    - `pipeline report --run N` for a v3 run prints `questionnaire_lengths: 15, 30, 40`.
    - The `statement_selection` line shows `v3, pool P, eligible E, selected n, rule …, lengths 15/30/40, topic_caps 4/9/10, min_parties 3, projected_failures …`.
    - `selection_coverage` shows per Party `15:a 30:b 40:c (pool p/P)`.
    - The pool table has columns `pool, rank, position, tier, topic, parties, favour, against, status, anchor, text, context_note`; `tier` is the shortest offered length that contains the position.
    - Runs 1–5 (selection v1/v2) still print their old table and summary. `questionnaire_lengths: not recorded` for DVs without lengths.
15. **Committed DB.** `data/ideology.db` is at head `0015`. `ideology db check` prints `Safe to commit: yes`. `tests/test_committed_database.py` passes.
16. **Methodology.** `/metodologia` shows the §10 copy. A real browser at 375 px and desktop shows no overflow and a clean console. Election 2 (DV5) still loads and answers, and no request carries Answers.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONTEXT.md`, `CONSTRAINTS.md` (LLM Providers, Pipeline, Validation, Public API, Client-side Matching, Public Copy, Shared Database), `ARCHITECTURE.md` (grep), `docs/domain-model.md` (checks 1–7), `docs/build-brief.md`, `docs/technical-discovery.md:83-87`, `docs/risks-and-open-questions.md` (Voter feedback round 1; the 2026 coverage, pool and selection risks), `PROGRESS.md` (head), `feature_list.json` (this entry, `e2e-2026-dataset-clarity`, `questionnaire-length-and-context`).
- `docs/specs/pipeline-coverage-selection.md` and `pipeline-statement-clarity-context.md`, for format and precedent.
- `src/ideology_app/pipeline/`:
  - `prompts.py`: `_COMMON_RULES` is shared with both Statement prompts; `CandidateList` max 12; `FindingList` and `_finding_list_schema` use `POOL_MAX_STATEMENTS`, so moving the pool would change the findings request;
  - `generation.py` (`pool_bounds`, `reduce_request`), `agenda.py` (`PARTY_QUOTA_MAX` 24, `quota` rule);
  - `positions.py` (`MAX_POSITION_CALLS_PER_RUN` 300, `FINDINGS_STATEMENTS_PER_CALL` 20, `plan_position_calls` uses `POOL_MAX_STATEMENTS`);
  - `selection.py` (v2), `runs.py` (`_finish`, `execute_run`, `validate_run`), `reports.py`.
- `src/ideology_app/validation/` (all checks, `base.py`), `config.py` (`ValidationSettings`, `validation_settings()`, env helpers), `models.py` (`DatasetVersion`), migrations list up to `0014`.
- `src/ideology_app/cli.py` (`_selection_lines`, `_selection_rows`, `_setting_value`, `pipeline report`), `api/schemas.py`, `api/queries.py` (`_version_out`).
- `packages/core/src/infrastructure/share-link/share-link-codec.ts`, `application/open-share-link.ts`, `domain/{questionnaire,results,dataset-version}.ts`, `infrastructure/http/public-api-client.ts` (`parseDatasetVersion`).
- `apps/web/src/features/methodology/MethodologyPage.tsx`.
- `tests/test_pipeline_prompts.py` (pins), `tests/pipeline_fixtures.py` (2 Parties valued +1/−1, default pool payload of 70).
- `data/ideology.db`, read-only, at head `0014`. Recorded calls and the `statement_selection` of runs 3 and 5 were analysed (scratch scripts outside the repo):
  - run 5 had 68 candidate calls (67 at the 12 cap) and 272 findings calls (68 chunks × 4 batches);
  - its 77-Statement pool has 40 side-separating Statements, 39 of them with ≥ 3 Parties;
  - run 3's 55-Statement pool has 28 side-separating;
  - DV5: 25 of its 32 Statements separate by side.
- Not inspected line by line: `positions.py` beyond its constants and batching, the Vitest fixtures that build a `DatasetVersion`, and the README run section.

### Feasibility Finding (drove Settled Decision 1 and Open Question 1)

The v3 rules were simulated on run 5's recorded pool (12 Parties):

- the first 15 give a worst Party (VOX, ERC) of 7/15, one short of 50 %;
- at 30, ERC and SALF have 11/30;
- only 39 Statements are eligible, so the full set is short of 40;
- ERC takes a side on only 12 of the 39 eligible Statements, so no ordering reaches 50 % at 30 or 40.

The topic caps were never binding. A coverage-aware tie-break did not help (same 7/15). Passing therefore depends on the larger extraction and pool producing more multi-Party Statements. Only `e2e-2026-dataset-clarity` can show that.

### Existing Patterns To Follow

- Selection and checks are pure (no DB, clock or randomness, no iteration over unordered sets). Settings come only from `ValidationSettings`, and the selection reuses the check functions.
- Nullable `ADD COLUMN` migrations use `batch_alter_table(..., recreate='never')` with a hand-written downgrade (`0012`, `0014`). The API gains additive fields, and the core reads a missing key as a safe default.
- Prompt pins: bump the version and re-pin only what changed. Anything that must stay byte-identical keeps its hash test unedited.

### Current Gaps

- No ranking by Party count. No stored or served lengths. Checks see only the whole set. Separation and coverage still follow five-value semantics. The report has no tier.

## Technical Approach

**1. Extraction prompts (`prompts.py`).** Replace `_COMMON_RULES` lines 4–5 with the single line "- Cada afirmación es una propuesta política en forma afirmativa con la que un votante puede estar de acuerdo o en desacuerdo." This drops "en una escala de 5 puntos" (settles risks entry (f)) and the line "- Prefiere propuestas que los distintos partidos responderían de forma diferente.": the candidates must now capture everything, and the preference moves to the reduce.

- `STATEMENT_CANDIDATES` v2, `CandidateList.candidates` max 30, `max_tokens` 8192 (30 × about 140 tokens).
  - System: "Eres un analista político que prepara un cuestionario de orientación de voto para unas elecciones generales en España. Lees fragmentos de programas electorales y extraes todas las propuestas políticas concretas que contienen, como afirmaciones candidatas del cuestionario.\n\n{_COMMON_RULES}\n- Extrae cada propuesta concreta del fragmento, también las de detalle y las que solo aparecen una vez, sin elegir entre ellas; devuelve como máximo 30 candidatas por fragmento y, si hay más, las que el fragmento desarrolla con más detalle. Si el fragmento no contiene propuestas políticas, devuelve una lista vacía."
  - Template: the last sentence becomes "Extrae todas las propuestas políticas concretas de este fragmento como afirmaciones candidatas."
- `GENERATE_STATEMENTS` v7, `max_tokens` 49152 (140 items × about 190 tokens ≈ 27k; v6's 32768 leaves too little margin). Template unchanged. The system text is v6 with:
  - "- Elige orientaciones en las que los programas discrepen; evita las que casi cualquier programa suscribiría." → "- Elige orientaciones en las que unos programas estén a favor y otros en contra; evita las que casi cualquier programa suscribiría."
  - after the "Agrupa en una misma orientación…" line, add "- Prefiere las orientaciones que tratan más programas: el cuestionario empieza por las afirmaciones en las que se sitúan más candidaturas y deja fuera las que tratan muy pocas."
- `POOL_MIN/MAX/TARGET_STATEMENTS = 100, 140, 120`.
- New `FINDINGS_MAX = 80` replaces `POOL_MAX_STATEMENTS` in `FindingList` and `_finding_list_schema`, so the findings request stays byte-identical. Batches of 20 never need more.
- `REFERENCE_SCHEMAS["generate_statements"] = statement_set_schema(100, 140, 32)`.

*Why void the candidate calls:* every recorded candidate call hit the cap, so "every concrete proposal" cannot be reached without changing that request. Candidate calls are about 13 % of a run's input tokens (run 5: 68 calls of ~20k against 272 findings calls of ~34k). The findings calls are never reusable after a reduce change anyway, so a fresh run costs about the same extra either way. Voided: 68 calls for Election 2 and 79 for Election 1.

**2. Agenda and budget.** `agenda.PARTY_QUOTA_MAX = 40` and `AGENDA_VERSION = "v2"`. With 12 Parties that is about 480 reduce lines, roughly 20k input tokens. `positions.MAX_POSITION_CALLS_PER_RUN = 600`: Election 2 plans 488 calls, Election 1 plans 79 × 7 + 9 = 562. `MAX_LLM_CALLS_PER_RUN` (200, generation only) is unchanged.

**3. Settings (`config.py`).**

- New defaults: `DEFAULT_MIN_STATEMENTS = 35`, `DEFAULT_MAX_STATEMENTS = 40`, `DEFAULT_QUESTIONNAIRE_LENGTHS = (15, 30)`, `DEFAULT_MIN_STATEMENT_PARTIES = 3`.
- `ValidationSettings` gains `questionnaire_lengths: tuple[int, ...]` and `min_statement_parties: int`, appended after the note fields. `__post_init__` requires:
  - the lengths: a tuple of non-bool ints ≥ 1, strictly increasing, last < `min_statements` (`()` allowed);
  - `min_statement_parties`: an int ≥ 1.
- `validation_settings()` checks the two new variables after the word list.
  - The lengths are comma-separated ASCII digits, and `none` (any case) means `()`.
  - Error: `Invalid VALIDATION_QUESTIONNAIRE_LENGTHS '15,15'; expected increasing positive integers below VALIDATION_MIN_STATEMENTS (35), or none`.
- Rationale for 35..40: the full set stays clearly longer than 30, and up to 5 Statements can be dropped to meet coverage, as in the old 25..35 range. The 15/30 lengths are the user's proposal, unchanged; 35..40 is Settled Decision 2. Tuning any of them is a deliberate env change, and a `--reuse-from` replay re-selects at zero LLM cost when the pool bounds are unchanged.
- Tests that build small settings pass `questionnaire_lengths=()` explicitly.

**4. Selection v3 (`selection.py`).**

- Per pool Statement:
  - `favour` = Parties with value > 0, `against` = Parties with value < 0;
  - `parties = favour + against`, `separation = min(favour, against)`.
- Statuses follow scenario 8. Ranking follows scenario 9.
- Caps: `caps = [max(1, share*L//100) for L in lengths] + [max(1, share*min_statements//100)]`. `cap(k)` uses the first `L ≥ k`, else the last cap. Caps are non-decreasing because lengths < min.
- Placement stops at `max_statements` or when no ranked Statement fits.
- Count: `_count` on the placed sequence, unchanged. Its coverage now counts sides through `check_party_coverage`, on the full-set input with `lengths=()`.
- `Selection` gains `lengths`: the shorter lengths below n, plus n (`()` when n = 0).
- `tier(position)` = the first length ≥ position. `topic_full` = not placed, and its topic is at the last cap when placement ended. `projected_failures` runs on the selected data with `lengths`.
- Report: `version` "v3", `settings`, `lengths`, `topic_caps`, `party_ids`, `pool_size`, `eligible_count`, `selected_count`, `count_rule`, `projected_failures`, `parties` (`{party_id, pool_sides, selected_sides: [per length]}`), and `pool` rows (`pool, text, topic, context_note, anchor, values, parties, favour, against, separation, status, duplicate_of, rank, position, tier`).
- `anchor_summary` is unchanged. Rewrite the module docstring.

**5. Validation.**

- `ValidationInput.lengths: tuple[int, ...] = ()`, filled by `load_input` from `version.questionnaire_lengths`.
- `base.offered_lengths(data)` returns `data.lengths` or `(len(statements),)`, as long as statements exist.
- `party_coverage` and `topic_spread` loop over `offered_lengths` on `statements[:L]` (positions are 1..n), with messages as in scenarios 5–6.
- `statement_separation` follows scenario 4. `statement_count` follows scenario 7.
- Update every check docstring and the registry comment. Evidence, uniqueness and note checks are unchanged.

**6. Runs and storage.**

- `_finish(..., lengths=selection.lengths)` sets `DatasetVersion.questionnaire_lengths = list(lengths)` in the same insert. It is never updated.
- Migration `0015_dataset_version_questionnaire_lengths.py`: `dataset_versions.questionnaire_lengths sa.JSON NULL`.
  - Upgrade and downgrade both use `batch_alter_table('dataset_versions', recreate='never')`, so the table is never recreated and `uq_dataset_versions_published_election_id` keeps its WHERE clause (test against `sqlite_master`).
  - No data migration.
- `models.DatasetVersion.questionnaire_lengths: Mapped[list[int] | None]`.

**7. Report and CLI.**

- `RunReport.questionnaire_lengths: list[int] | None`.
- `_selection_lines` and `_selection_rows` branch on `selection["version"] == "v3"`. Older reports keep the v2 header and lines.
- `_setting_value(key, value)` shows the word list as `N words` and the lengths as `15,30`.

**8. API and core.**

- `DatasetVersionOut.questionnaire_lengths: list[int]`, description "Offered questionnaire lengths, ascending; the last is the number of Statements. A questionnaire of length N is the first N Statements. Dataset Versions created before lengths existed offer only their full length."
- `queries._version_out` fills it.
- Core `DatasetVersion.questionnaireLengths: readonly number[]`, parsed in `parseDatasetVersion` per scenario 13. Update the fixtures that build a `DatasetVersion`.

**9. Share Link decision: no codec change.**

- The v2 layout is one letter per Statement in position order. A length-N questionnaire is the first N positions, so its payload is simply N letters. No new marker is needed, and `decodeShareLink` already accepts 1..500 letters.
- The contract: a v2 payload for Dataset Version D is valid exactly when its letter count is in `D.questionnaireLengths`, and it maps to the first N Statements.
- Every existing link has letters = the Statement count, which is always the last length, so old links stay valid.
- `restoreQuestionnaire` keeps its strict equality here. Relaxing it to any offered length, and making results use only the prefix, belongs to `questionnaire-length-and-context`, because it changes the shared result screen. Record this in `CONSTRAINTS.md` and the risks doc.

**10. Methodology copy** (`MethodologyPage.tsx` and its test; required by CONSTRAINTS "Public Copy").

- Statements, P1: "propone afirmaciones candidatas: propuestas políticas con las que se puede estar de acuerdo o en desacuerdo." → "recoge como afirmaciones candidatas todas las propuestas políticas concretas que encuentra, hasta 30 por fragmento: propuestas con las que se puede estar de acuerdo o en desacuerdo."
- P2: "de unas 70 afirmaciones" → "de unas 120 afirmaciones". Last paragraph: "orientaciones en las que los partidos discrepen" → "orientaciones en las que unos partidos estén a favor y otros en contra, mejor si las tratan muchos programas".
- Selection section, replace the three paragraphs with:
  1. "La inteligencia artificial propone más afirmaciones de las que tendrá el cuestionario, entre 100 y 140, y sitúa a cada partido en todas ellas. Después, un procedimiento automático, sin inteligencia artificial y sin azar, elige hasta 40 y las ordena."
  2. "Deja fuera las afirmaciones cuya nota de contexto no cumple las comprobaciones, las repetidas, las que no separan a los partidos, porque no hay al menos uno a favor y otro en contra, y aquellas en las que menos de 3 partidos están a favor o en contra. Ordena las demás por el número de partidos que están a favor o en contra; en caso de empate, primero las más repartidas entre los dos lados y, después, las que se propusieron antes. Todos los partidos cuentan igual."
  3. "Así, las primeras afirmaciones son las que tratan más partidos, y las comprobaciones se aplican también a las primeras 15 y a las primeras 30, para que un cuestionario más corto, formado por las primeras, sea igual de equilibrado. Ningún tema supera el 30&nbsp;% de las primeras 15, de las primeras 30 ni del total: una afirmación que lo superaría pasa al primer puesto en el que cabe."
  4. "El cuestionario completo tiene entre 35 y 40 afirmaciones: el mayor número con el que todos los partidos están a favor o en contra en al menos el 50&nbsp;% de ellas. Si no es posible cumplir estas condiciones, el procedimiento se acerca todo lo que puede y las comprobaciones posteriores impiden publicar el resultado. Las afirmaciones conservan el texto con que se propusieron."
- Validation list items 2, 3, 5 and 6 become:
  - "cada partido está a favor o en contra en al menos el 50&nbsp;% de las afirmaciones, y también de las primeras 15 y de las primeras 30;"
  - "en cada afirmación hay al menos un partido a favor y otro en contra;"
  - "el cuestionario completo tiene entre 35 y 40 afirmaciones;"
  - "ningún tema reúne más del 30&nbsp;% de las afirmaciones, ni de las primeras 15 ni de las primeras 30;"

## Expected File Changes

- Create `src/ideology_app/migrations/versions/0015_dataset_version_questionnaire_lengths.py`.
- Modify:
  - `src/ideology_app/pipeline/{prompts,agenda,positions,selection,runs,reports,__init__}.py`;
  - `validation/{__init__,base,party_coverage,statement_separation,statement_count,topic_spread}.py`;
  - `config.py`, `models.py`, `cli.py`, `api/{schemas,queries}.py`.
- Modify `packages/core/src/domain/dataset-version.ts`, `infrastructure/http/public-api-client.ts`, and the core and web fixtures and tests that build a Dataset Version.
- Modify `apps/web/src/features/methodology/MethodologyPage.tsx` and `.test.tsx`.
- Tests:
  - `tests/test_pipeline_{prompts,generation,agenda,positions,selection,runs,checkpoint}.py`;
  - `tests/test_validation_*.py` for checks 3–6, `tests/test_config.py`, `test_migrations.py`, `test_public_api.py`, `test_cli_pipeline{,_report}.py`;
  - `tests/pipeline_fixtures.py`: default pool payload 120; Party values must give ≥ `min_statement_parties` sides. Either seed a third Party or pass explicit settings with `min_statement_parties=2`, but never weaken the default;
  - never delete a test without a replacement.
- Data: `data/ideology.db` upgraded to `0015` (`DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db upgrade`, then `db check`), only when nobody is generating.
- Not changed: `init.sh`, `generation.py` (its bounds follow the constants), `position_findings`/`party_positions` prompts, the share-link codec, `checkpoint.py`.

## Visual Design Impact

- UI involved: copy only, on `/metodologia`, using existing sections and classes. Source: `DESIGN.md`. No new design artifact. Length choice UI belongs to `questionnaire-length-and-context`.

## Durable Documentation Impact

- `ARCHITECTURE.md`, update:
  - `prompts.py` versions, pool constants and `FINDINGS_MAX`;
  - agenda v2, position budget 600;
  - selection v3 (statuses, priority order, caps, lengths);
  - checks 3–6 per length and by side;
  - `ValidationInput.lengths`, `DatasetVersion.questionnaire_lengths` (`0015`), API and core field;
  - migration head `0015`.
- `CONSTRAINTS.md`, update:
  - Validation: separation means "at least one Party in favour (+1/+2) and one against (−1/−2)", and coverage counts only sided Positions;
  - Validation (new): "Coverage and topic spread MUST be checked on every offered questionnaire length (each prefix), and a failing length MUST fail the whole run; lengths MUST NOT be dropped to make a run pass";
  - Pipeline: the selection writes Statements in priority order and computes `questionnaire_lengths` from settings. `dataset_versions.questionnaire_lengths` is written only by `_finish` and never updated;
  - Client-side Matching (new): "A v2 Share Link with N letters is valid only when N is one of the Dataset Version's `questionnaire_lengths` and maps to its first N Statements; no new marker is needed for prefixes";
  - Public API: the new field is part of the immutable body.
- `CONTEXT.md`:
  - add **Questionnaire Length** ("a length a Dataset Version offers; a questionnaire of length N is its first N Statements in priority order; versions before `pipeline-statement-priority-tiers` offer only their full length");
  - update **Questionnaire**, **Statement Pool** (100 to 140) and **Statement Selection** (side rule, few-Party drop, ranking by Parties with a side, priority order, per-length caps);
  - update **Party Position** (coverage reads sides).
- `docs/domain-model.md`: checks 3–6 as above (defaults 35–40, lengths 15/30), Dataset Version holds its questionnaire lengths, and a new important scenario for a failing 15-prefix.
- `README.md`: new defaults and the two new variables in the configuration table. Add them to the `env -u` list in the run command.
- `docs/technical-discovery.md:83`: note that `statement_candidates` v2 voids earlier candidate calls, so a `--reuse-from` of runs 1–5 reuses no candidate call.
- `docs/risks-and-open-questions.md`, same change:
  - line 77 (f) settled; (d) anchors: still no preference;
  - line 79: the tier part is implemented; the 15-tier coverage question is settled as strict (Settled Decision 1) and its feasibility becomes the open risk owned by `e2e-2026-dataset-clarity`;
  - line 80: settled;
  - update "Pool too narrow…" (pool 100..140, budget 600) and "Selection shapes the Questionnaire…" (ranking by Party count now favours issues many Parties address; side rule);
  - record the Settled Decisions and add the Open Questions And Risks below.
- `AGENTS.md`: not needed.

## Implementation Plan

1. Config fields and env parsing, then checks 3–6 with `ValidationInput.lengths` and their tests.
2. Migration `0015`, the model and `load_input`. Upgrade/downgrade tests, the index test, `alembic check`.
3. Prompts (§1), `FINDINGS_MAX`, agenda v2, position budget. Re-pin the two changed prompts and confirm the position pins pass unedited.
4. Selection v3 and its plain-data tests (determinism, symmetry, ranking, caps, statuses, lengths).
5. `runs._finish` lengths, fixtures, and the runs/checkpoint tests (including scenario 11).
6. Report and CLI. API and core.
7. Methodology copy and test, then the browser check.
8. Upgrade and check `data/ideology.db`, update the docs, run `CI=true ./init.sh` and record evidence.

## Implementation Tasks

- [ ] `config.py`: defaults, fields, validation, env parsing, docstring.
- [ ] Checks 3–6 and `ValidationInput.lengths` / `offered_lengths`. `load_input` reads the stored lengths.
- [ ] `0015`; `DatasetVersion.questionnaire_lengths`.
- [ ] `prompts.py` (§1 texts exactly, `CandidateList` 30, max_tokens 8192/49152, pool constants, `FINDINGS_MAX`); `agenda.py`; `positions.py` budget.
- [ ] `selection.py` v3; `runs.py` lengths in `_finish`.
- [ ] `reports.py`, `cli.py` (v3 lines, table, legacy branch, `_setting_value`).
- [ ] `api/schemas.py`, `api/queries.py`; core type, parser and fixtures.
- [ ] Methodology copy and test.
- [ ] Tests for scenarios 1–16. DB upgrade and `db check`. Docs listed above.

## Verification Plan

- `CI=true ./init.sh` exits 0. Report the pytest and Vitest counts against 1989 / 1020.
- `.venv/bin/python -m pytest tests/test_pipeline_prompts.py tests/test_pipeline_selection.py tests/test_pipeline_runs.py tests/test_validation_party_coverage.py tests/test_validation_statement_separation.py tests/test_validation_questionnaire_shape.py tests/test_config.py tests/test_migrations.py tests/test_public_api.py tests/test_cli_pipeline_report.py tests/test_committed_database.py -q`.
- `git diff v2 -- tests/test_pipeline_prompts.py` shows the `FINDINGS_REQUEST_HASH`/`POSITIONS_REQUEST_HASH` lines and the `position_findings`/`party_positions` fingerprints untouched.
- `.venv/bin/alembic -c alembic.ini check` reports no drift. `ideology db check` on `data/ideology.db` prints `Safe to commit: yes` at `0015`. `sqlite3 "file:data/ideology.db?mode=ro" "select count(*) from dataset_versions where questionnaire_lengths is not null"` returns 0.
- Sample output: a fake run's `pipeline report` showing the v3 lines and the table, plus `pipeline report --run 5` on a scratch copy of the DB showing the legacy layout.
- E2E: there is no Playwright suite. API coverage comes from `test_public_api.py` and the core parser tests, which is enough for one additive field.
- **Browser (required, `/metodologia` copy).**
  - Serve a migrated scratch copy of `data/ideology.db` outside the repo through a temporary launch entry on a free port. Never use port 8000 or the committed file.
  - Check `/metodologia` at 375 px and desktop, light and dark.
  - Answer the Election 2 questionnaire (DV5) to the results. The console must be clean and no request may carry Answers.
  - `GET /api/v1/elections/2/published-dataset-version` returns `questionnaire_lengths: [32]`.
  - Remove the entry and the scratch DB afterwards.

## Evidence To Capture

- Gate counts and test names per scenario. The new `PROMPT_VERSIONS` and proof of the unchanged position pins. `db check` output and head. Sample report output. The browser check (browser, widths, themes, console and network, texts seen). Record everything in `feature_list.json` and `PROGRESS.md` only.

## Validator Checklist

- [ ] Only `statement_candidates` (v2) and `generate_statements` (v7) were bumped, and the §1 texts match. Position request hashes are unchanged.
- [ ] Selection v3 is pure, deterministic and Party-symmetric (both tests present), ranks by Parties with a side, writes in priority order, and its topic caps make every prefix pass `topic_spread`.
- [ ] Checks 3 and 6 run on every offered length. Check 4 uses the side rule. Check 5 verifies the stored lengths. A failing length fails the run, and nothing is dropped.
- [ ] `questionnaire_lengths` is written once in `_finish`, NULL on DVs 1–5, served additively, and parsed in core with the missing-key fallback. The codec is unchanged.
- [ ] `data/ideology.db` is at `0015` and passes `db check`. The partial index is intact.
- [ ] Methodology copy matches §10, and the browser check is recorded.
- [ ] CONSTRAINTS, ARCHITECTURE, CONTEXT, domain-model, README, technical-discovery and risks are updated. No `docs/validations/`. No length-choice or note UI.

## Implementation Notes (2026-11-22, implementer)

Findings during implementation, none of which changes a scenario:

- `VALIDATION_QUESTIONNAIRE_LENGTHS` unset with a `VALIDATION_MIN_STATEMENTS` at or below 30 raises `ConfigError` (`Invalid VALIDATION_QUESTIONNAIRE_LENGTHS: the default 15,30 is not below VALIDATION_MIN_STATEMENTS (N); set lower lengths or none`) instead of silently dropping a default length (the strict rule of Settled Decision 1).
- `PositionList` (the static base type of `party_positions`) also uses `FINDINGS_MAX`, so its pinned fingerprint and request hash stay unchanged.
- A selection with 0 Statements stores `questionnaire_lengths = []` (the report prints `none`); the API then serves `[0]`. Such a version always fails `statement_count` and is never served.
- Tests: `offline_guard` sets `VALIDATION_MIN_STATEMENT_PARTIES=2` for the 2-Party seeded Election (the code default stays 3, tested in `test_config.py`). Selection v3 never keeps a non-separating Statement, so tests of Position storage and of the separation/coverage failure paths use a seam, `pipeline_fixtures.keep_pool_prefix`, that keeps pool Statements 1..N as an older selection would have.

## Settled Decisions (user, 2026-11-21)

These were the spec's open questions 1, 3 and 4; the user chose the spec's defaults. Also recorded in `docs/risks-and-open-questions.md`, "Voter feedback round 1".

1. **A questionnaire length that fails Validation fails the whole run (strict).** No length is dropped and no lower threshold applies to shorter lengths. After the real run (`e2e-2026-dataset-clarity`), the settings (lengths, coverage threshold) may be tuned and the run replayed with `--reuse-from` at no LLM cost.
2. **The full set publishes between 35 and 40 Statements** (`VALIDATION_MIN_STATEMENTS` 35, `VALIDATION_MAX_STATEMENTS` 40; not exactly 40).
3. **Minimum Parties taking a side for a Statement to be eligible: 3**, absolute (not a share of the Parties) and configurable (`VALIDATION_MIN_STATEMENT_PARTIES`).
4. **Party Positions with value 0 do not count** toward coverage, the ranking or the few-Party filter: only +1/+2 (in favour) and −1/−2 (against) count.

## Open Questions And Risks (not settled)

1. **Feasibility is unproven** (open risk, owner `e2e-2026-dataset-clarity`). On run 5's pool the v3 rules fail at 15 (7/15), 30 and 40, and ERC takes a side on only 12 of the 39 eligible Statements (see Feasibility Finding). The larger extraction is the bet. If `e2e-2026-dataset-clarity` still fails, the levers are user decisions: lengths, the coverage threshold, a per-Party coverage policy, or a smaller Party set.
2. **Cost.** Pool 100..140 plus "every proposal" means about 490 position calls for Election 2 (run 5 made 284), roughly 14–16M input tokens on `claude_code`. Every candidate call is redone (candidate calls of earlier runs are voided by `statement_candidates` v2). Lower pool bounds would cut cost but also the multi-Party Statements the ranking needs.
3. Restoring a prefix Share Link (relaxing `restoreQuestionnaire`, results over the first N only) is deferred to `questionnaire-length-and-context`. Until then, only full-length links are produced or accepted.
