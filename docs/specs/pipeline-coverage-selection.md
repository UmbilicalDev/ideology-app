# Feature Implementation Spec: Choose the final Statements by Party coverage and separation

## Source Feature

- `id`: pipeline-coverage-selection
- `area`: pipeline
- `depends_on`: none
- `status`: `not_started` at planning time
- `source`: `feature_list.json`

## Goal

The second real run on the shared DB (`e2e-real-2023-election`, run 2) had 35 Statements and every evidence quote was valid. It still failed `party_coverage` for all 9 Parties (PP 13/35, PSOE 16, VOX 13, SUMAR 23, ERC 22, JUNTS 17, EH Bildu 3, EAJ-PNV 6, BNG 20; the minimum is 70 %) and `statement_separation` for 8 Statements. The `party_positions` reduce loses almost nothing (138 pairs found, 133 kept). The bottleneck is `position_findings`: about 2.3 findings per 40k-character chunk. The cause is that `generate_statements` produces specific measures taken from one Party's text, and the findings prompt (correctly) accepts only explicit stances backed by a verbatim quote.

After this feature, a run works in four steps:

1. It generates a **Statement pool** of 45..60 Statements.
2. It extracts every Party's Positions for the whole pool, with the same calls as today: one `position_findings` call per chunk and one `party_positions` reduce per Party.
3. Deterministic code (no LLM, no randomness) selects the final 25..35 Statements. It maximises the coverage of the worst-covered Party first, keeps only Statements that separate the Parties, and respects the questionnaire-shape rules.
4. The Dataset Version holds only the selected Statements, renumbered 1..n in pool order, and their Positions. Validation runs unchanged.

The selection, with the whole pool and its per-Statement scores, is stored on the run and shown by `pipeline report`. A new `pipeline run --reuse-from R` reuses identical recorded calls even from a run that already has a Dataset Version, so run 2's 79 `statement_candidates` calls are not paid again. The methodology page explains the selection.

## Non-Goals

- No change to the findings evidence rule, the `position_findings` / `party_positions` prompts, the Validation checks or thresholds, chunking, or the call caps (`MAX_LLM_CALLS_PER_RUN`, `MAX_POSITION_CALLS_PER_RUN`).
- `statement_candidates` stays byte-identical: same prompt, schema and `request_hash` (`CANDIDATE_REQUEST_HASH` test).
- No LLM in the selection, no per-Party weights, no Party exclusion. Statement text and topic are never edited.
- No real LLM run, no network, no `claude` CLI in tests. The real re-run belongs to `e2e-real-2023-election`.
- No `/api/v1` change. The API serves the Dataset Version, which contains only the selected Statements.

## Job Story

When a run's Statements are too specific for most manifestos to address,
I want the pipeline to generate more candidates and keep the ones that the Parties' own texts actually take a stance on and disagree about,
so that Validation can pass without weakening the evidence rule, and anyone can audit why each Statement was kept.

## Users And Permissions

- Operator (CLI): `pipeline run [--reuse-from R]` and `pipeline report --run N`. The report stays read-only.
- Voter: sees only the published Dataset Version and the updated `/metodologia` copy.

## Acceptance Scenarios

1. **Pool and positions.** Given the defaults, when a run executes with `FakeProvider`, then `generate_statements` returns 45..60 Statements. Every `position_findings` and `party_positions` request lists the whole pool (schema maximum = pool size). `llm_calls` = chunks + 1 + chunks + Parties with candidates, the same formula as before.
2. **Pool bounds enforced.** A fake `generate_statements` answer of 44 or 61 Statements raises `LLMOutputError`. The run ends `failed`, with no Dataset Version, no selection stored and no position call made.
3. **Dataset Version = selection.** Given a passing run, the Dataset Version has exactly the selected pool Statements:
   - they are in ascending pool order with positions 1..n;
   - text and topic are identical to the pool entries;
   - Party Positions exist only for the selected Statements, and their values and Evidence (document, quote, page, URL) are identical to the extraction results for that pool number.
4. **Deterministic.** The same pool, positions, Party ids and settings always give the same selected pool numbers, order and report (asserted on two calls and on the JSON).
5. **Party symmetry.** Relabelling the Parties (permuting which Party id owns which column of values) does not change the selected pool numbers.
6. **Shape rules.** The selection never contains two Statements that are equal under `normalize_for_match` (the first in pool order is kept), never puts more than `topic_cap` Statements on one topic, and never exceeds `max_statements`. `check_topic_spread` and `check_statement_uniqueness` pass on every selection.
7. **Coverage first.** In a constructed pool where Party 3 has stances on only 5 Statements, all 5 are selected (if they separate the Parties and are not duplicates) before any Statement that does not add to the worst-covered Party.
8. **Count rule.** The count is the largest n in `[min_statements, L]` at which `check_party_coverage` passes on the selection, where L is the number of eligible Statements picked, capped at `max_statements`. If no n passes, the selection uses the n with the highest worst-Party coverage ratio (ties: larger n). If fewer than `min_statements` separating Statements exist, non-separating ones are added to reach `min_statements`, and Validation then fails `statement_separation`. If even that is short, every unique Statement that fits the topic cap is kept, and Validation fails `statement_count`.
9. **Settings, not literals.** With `ValidationSettings(min_statements=10, max_statements=12, min_party_coverage_percent=50, max_topic_share_percent=40)` the selection obeys those values, the pool bounds follow (see Technical Approach) and Validation uses the same object.
10. **Audit.** `pipeline_runs.statement_selection` is written in the `_finish` commit that writes the Dataset Version, and stays null on a failed generation. `pipeline report --run N` prints the selection summary, the per-Party pool/selected stance counts and the pool table. An older run prints `statement_selection: not recorded`.
11. **Reuse from a finished run.** Given a run R that has a Dataset Version (passed or failed Validation), `pipeline run --election E --reuse-from R` queues a run with `resumed_from_run_id = R`. Identical calls (e.g. every `statement_candidates` call) are reused with zero tokens, and the rest go to the provider. `--resume-from R` still refuses R (`already has dataset version`). `--reuse-from` refuses an unknown run, another Election and another provider or model, with the same messages as resume. `--reuse-from` together with `--resume-from` is a usage error.
12. **Methodology copy.** `/metodologia` has a new section that explains the selection in Spanish. The existing sections stay true. The page is checked at 375px and desktop with a clean console.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONSTRAINTS.md` (Pipeline, Validation, LLM, Public Copy, Shared Database), `PROGRESS.md` (head), `feature_list.json`, `docs/risks-and-open-questions.md`, `docs/technical-discovery.md` (Claude Code and shared-database runbooks), `docs/domain-model.md`, `CONTEXT.md`, `ARCHITECTURE.md` (pipeline lines 46-57), `DESIGN.md` (core screen 4).
- `docs/specs/pipeline-output-bounds.md`. Read for its pattern; the other dependency specs were known through ARCHITECTURE/CONSTRAINTS and not re-read line by line.
- `src/ideology_app/pipeline/prompts.py`: `statement_set_schema`, `finding_list_schema` (max 60 findings), `position_list_schema` (`max_length = statement_count`), `GENERATE_STATEMENTS` v2 (max_tokens 8192), `TARGET_STATEMENT_COUNT`.
- `pipeline/generation.py` (`reduce_request`, `generate_statements`, call cap), `pipeline/positions.py` (`extract_positions` returns `PositionResult` per 1-based Statement number), `pipeline/runs.py` (`queue_run`, `_check_resumable` refuses a source with a Dataset Version, `_finish`, `execute_run`, `find_unfinished_run`), `pipeline/checkpoint.py` (`request_hash`, `CheckpointProvider`), `pipeline/reports.py`, `pipeline/__init__.py`.
- `validation/*.py`: the pure checks over `ValidationInput`. `check_party_coverage`, `check_statement_separation`, `check_statement_uniqueness`, `check_topic_spread` and `check_statement_count` take plain data and can be reused directly.
- `config.py` (`ValidationSettings`), `models.py` (`PipelineRun`, `Statement`), `cli.py` (`pipeline run` options and guard at 689-783, `pipeline report` at 1061, `db check` unfinished line at 211), `llm/claude_code_provider.py` (`max_tokens` becomes `CLAUDE_CODE_MAX_OUTPUT_TOKENS`).
- `migrations/versions/0008_*.py` (the pattern for a nullable JSON column on `pipeline_runs`, `recreate='never'` downgrade), the list of revisions up to head `0011`.
- `tests/pipeline_fixtures.py` (`statements_payload(30)` default, `findings_response`, `positions_response(fill=True)`), `tests/test_pipeline_prompts.py` (`FINGERPRINTS`, `REFERENCE_SCHEMAS`, `CANDIDATE_REQUEST_HASH`; `max_tokens` is not in the fingerprint), `tests/test_pipeline_checkpoint.py`, `tests/test_migrations.py`, `tests/test_committed_database.py`.
- `apps/web/src/features/methodology/MethodologyPage.tsx` and its test (7 regions, exact texts), `apps/web/src/features/landing/LandingPage.tsx` ("Cómo funciona" is still true, no change).
- `data/ideology.db` (read-only, `mode=ro`): at `0011` with no Pipeline Runs on this branch. Run 2 lives only in the user's main-checkout DB.

### Existing Patterns To Follow

- Request builders with bounded schemas built through `_subclass`. Settings are resolved once in `execute_run` and passed down.
- Pure modules (no DB) for LLM orchestration, and the DB only in `runs.py`. `pipeline` may import `validation` (runs.py already does); `validation` never imports `pipeline`.
- A nullable JSON run column written once (`validation_settings`, `0008`).

### Current Gaps

- Nothing selects Statements. `_check_resumable` blocks reuse from runs that have a Dataset Version. No column holds a selection.

## Technical Approach

**1. Pool generation (`generate_statements` v3, the only prompt bumped).**
- `prompts.py`: add `POOL_MIN_STATEMENTS = 45`, `POOL_MAX_STATEMENTS = 60` and `POOL_TARGET_STATEMENTS = 55`, and remove `TARGET_STATEMENT_COUNT`.
- `generation.py`: add `pool_bounds(settings) -> tuple[int, int, int]`:
  - `low = max(POOL_MIN_STATEMENTS, settings.max_statements)`;
  - `high = max(POOL_MAX_STATEMENTS, low)`;
  - `target = min(max(POOL_TARGET_STATEMENTS, low), high)`.

  This keeps the pool at least as large as the largest allowed questionnaire.
- `reduce_request` uses `statement_set_schema(low, high)` and the new texts. `GENERATE_STATEMENTS` keeps `task="generate_statements"`, becomes `version="v3"` and gets `max_tokens=16384`: 60 × at most 300 characters is about 6-7k output tokens, which is too close to 8192.
- New system text (Spanish, exact). Keep `_COMMON_RULES` unchanged so `statement_candidates` stays identical:
  > "Eres un analista político que prepara un cuestionario de orientación de voto para unas elecciones generales en España. Recibes afirmaciones candidatas extraídas de varios programas electorales y eliges y redactas una lista amplia de afirmaciones; después, un procedimiento automático elegirá entre ellas las del cuestionario.\n\n{_COMMON_RULES}\nReglas para la lista:\n- Prefiere propuestas sobre las que se pronuncien varios programas, no medidas de detalle que solo aparecen en uno.\n- Cubre los temas de forma amplia: ningún tema debe superar aproximadamente una cuarta parte de la lista.\n- Sin afirmaciones casi duplicadas."
- Template:
  > "Afirmaciones candidatas (una por línea, con su tema entre corchetes):\n\n{candidates}\n\nElabora una lista de {count} afirmaciones (como mínimo {min_count} y como máximo {max_count}), en el orden en que deben presentarse."
- The function names `generate_statements` / `reduce_request` stay. Their docstrings say they return the pool.

**2. Positions over the pool.** `extract_positions(provider, [s.text for s in pool], …)` is unchanged code. N = the pool size, so `finding_list_schema(N)` and `position_list_schema(N, K)` bound to the pool automatically.
- Budget: the call count does not depend on N. Findings input grows by about 9-18k characters (60 lines) on top of the 40k chunk, which is fine.
- Findings output stays at `max_tokens=4096` and `max_length=60`. At about 170 tokens per finding with a 500-character quote, 4096 fits about 24 findings per chunk; run 2 observed about 2.3 per chunk. `position_findings` and `party_positions` are not bumped (unchanged text, builder and max_tokens). Their request hashes change only because the listed Statements change.
- Reduce output: at most 60 choices of about 25 tokens each, far below 8192.

**3. Selection: new pure module `src/ideology_app/pipeline/selection.py`** (no DB, no LLM, no clock, no `random`, no iteration over unordered sets).

```python
SELECTION_VERSION = "v1"
@dataclass(frozen=True)
class Selection:
    statements: tuple[StatementDraft, ...]          # selected, pool order
    positions: dict[int, list[PositionResult]]      # renumbered 1..n
    report: dict[str, Any]                          # JSON, stored on the run
def select_statements(pool: Sequence[StatementDraft],
                      positions: Mapping[int, Sequence[PositionResult]],
                      party_ids: Sequence[int],
                      settings: ValidationSettings) -> Selection
```

Algorithm. Pool numbers are 1-based; `v[s][p]` is Party p's value on pool Statement s, or `None` for no stance.

1. **Scores per pool Statement:**
   - `stances` = the number of Parties with a value;
   - `distinct` = the number of distinct values;
   - `spread` = max - min (0 when there are fewer than 2 values).
2. **Duplicates.** Build a `ValidationInput` from the pool (`StatementRow(id=pool_no, position=pool_no, …)` and `PositionRow`s) and run `check_statement_uniqueness`. Every Statement it reports is ineligible (`status "duplicate"`, `duplicate_of` = the first such Statement in pool order).
3. **Separation.** On the same input, `check_statement_separation` marks the non-separating Statements. They form tier 2; separating unique Statements form tier 1. With fewer than 2 Parties every Statement is tier 2.
4. **Topic cap.** `topic_cap = max(1, settings.max_topic_share_percent * settings.min_statements // 100)`, which is 7 with the defaults. Any n ≥ `min_statements` with at most `topic_cap` per topic then passes `topic_spread`. A candidate whose topic already holds `topic_cap` picks is skipped.
5. **Greedy leximin sequence.** Start with S empty and `cov[p] = 0`. Repeatedly pick, among the remaining tier-1 candidates that the topic cap allows, the one with the largest key:
   `(sorted ascending list of cov[p] + (v[s][p] is not None) over all party_ids, distinct, spread, -pool_no)`
   The first part is compared lexicographically: maximise the worst-covered Party, then the next, and so on. The order of `party_ids` never matters, which gives the symmetry. Stop at `max_statements` or when no tier-1 candidate is left.
   If the sequence is shorter than `min_statements`, continue with tier-2 candidates under the same key and cap until it reaches `min_statements` or no candidate is left.
6. **Count n.** L = the sequence length.
   - If L ≤ `min_statements`: n = L (`count_rule "short"`).
   - Otherwise, for each n in `[min_statements, L]`, run `check_party_coverage` on the prefix of length n (built as a `ValidationInput`). n = the largest passing n (`"coverage_met"`).
   - If none passes: n = the value that maximises `min_p cov_p(n) / n`, compared as integers (`a*n2` vs `b*n1`), ties to the larger n (`"best_coverage"`).
7. **Output.**
   - The selected Statements are the first n of the sequence, sorted by pool number. They are renumbered 1..n, and every `PositionResult` is copied with `dataclasses.replace(statement_number=new)` (value and Evidence untouched).
   - The report also includes `projected` = the names of the checks that fail when `run_checks` runs on the selection with `CHECKS` minus `evidence_quotes` (that check needs documents). It is informational; Validation still decides.

Report JSON (stored as is):
```json
{"version":"v1","settings":{...asdict(settings)},"topic_cap":7,"party_ids":[...],
 "pool_size":55,"selected_count":30,"count_rule":"coverage_met|best_coverage|short",
 "projected_failures":["party_coverage"],
 "parties":[{"party_id":1,"pool_stances":40,"selected_stances":24}],
 "pool":[{"pool":1,"text":"…","topic":"housing","values":[2,null,-1],"stances":2,
          "distinct":2,"spread":3,"tier":1,"status":"selected|duplicate|topic_full|not_picked",
          "duplicate_of":null,"pick":4,"position":1}]}
```
- `values` follow the order of `party_ids`. `pick` is the 1-based index in the greedy sequence, or null.
- `status`:
  - `topic_full`: an eligible Statement that was not picked while its topic held `topic_cap` picks;
  - `not_picked`: any other unselected eligible Statement (including picks beyond n);
  - a tier-2 Statement that was selected has `status "selected"` with `tier 2`.

Count justification. 35 (`max_statements`) is the preference because more Statements give a finer ranking. The count drops toward 25 only as far as the worst Party's coverage requires. The range comes from `ValidationSettings`, so there is no second hard-coded copy.

**4. Wiring (`runs.py`).** `execute_run`: generate the pool, run `extract_positions` over the pool, then `select_statements(pool, positions, run_input.party_ids, validation_settings)`, then `_finish(..., selection.statements, selection.positions, None, selection=selection.report)`. `_finish` sets `run.statement_selection` in the same commit as the Dataset Version. Statement text and topic are copied from the pool unchanged.

**5. Storage (migration `0012_pipeline_run_statement_selection.py`, down_revision `0011`).**
- Add one nullable `sa.JSON` column, `pipeline_runs.statement_selection`, through `op.batch_alter_table('pipeline_runs')`. The downgrade uses `recreate='never'` + `drop_column`, as in 0008. There is no data migration; existing rows stay null.
- `models.PipelineRun.statement_selection: Mapped[dict[str, Any] | None]`.
- Lower-risk alternatives were rejected:
  - recomputing the selection from `pipeline_run_calls` at report time is fragile, because mapping reduce calls to Parties depends on the call order, and it would run today's code rather than the code that ran;
  - a new table is more schema for the same data.
- Shared DB: on this branch, after `alembic check`, run `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db upgrade`, then `ideology db check` (it must print `Safe to commit: yes`), then commit `data/ideology.db`. Do this only when nobody is generating. The branch's DB has no runs; the run-2 DB (uncommitted, in the `e2e-real-2023-election` worktree) gets `db upgrade` when it is next committed (runbook step 9: keep the side with the run, re-run `db upgrade`; never merge two DB files). Flag this to the orchestrator before merging.

**6. Report.**
- `RunReport.statement_selection: dict | None` (read-only SELECT).
- `pipeline report` adds lines after `statements`:
  - `statement_selection: v1, pool 55, selected 30, rule coverage_met, topic_cap 7, projected_failures none`;
  - `selection_coverage: party 1 24/30 (pool 40/55); party 2 …`.
- After the validation report it prints a `statement pool:` table through `_print_rows`, with columns `pool, position, topic, stances, distinct, spread, tier, status, text` (text through `_one_line`). An older run prints `not recorded` and no table.

**7. Reuse (`--reuse-from R`).**
- `queue_run(..., resumed_from_run_id=None, allow_finished_source=False)`. `_check_resumable` skips only its Dataset Version refusal when `allow_finished_source` is set. The existence, Election and provider/model checks stay.
- The CLI's `pipeline run` gets `--reuse-from R` (int). It is mutually exclusive with `--resume-from` (`UsageError: pass at most one of --resume-from or --reuse-from`). It may be combined with `--fresh`.
- `--reuse-from` runs `_guard_unfinished` exactly like a plain run. An unfinished latest run must still be resumed, or `--fresh` passed; the guard semantics and its tests are unchanged.
- It prints `Pipeline run X: reusing identical calls of run R (N recorded calls)`. `resumed_from_run_id` is set in both cases; no new column.
- Command for the 2023 re-run (from the repo root, the same `LLM_PROVIDER`/`LLM_MODEL` as run 2):
  `caffeinate -is env DATABASE_URL=sqlite:///data/ideology.db LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election <E> --reuse-from 2`
  It is expected to reuse 79 `statement_candidates` calls and make about 89 new ones (1 pool + 79 findings + 9 reduces).

## Expected File Changes

- `src/ideology_app/pipeline/prompts.py`, `generation.py`, `selection.py` (new), `runs.py`, `reports.py`, `__init__.py` (export `select_statements`, `Selection`, `pool_bounds`, the pool constants; drop `TARGET_STATEMENT_COUNT`).
- `src/ideology_app/models.py`, `src/ideology_app/migrations/versions/0012_pipeline_run_statement_selection.py` (new), `src/ideology_app/cli.py` (`--reuse-from`, report lines and table; the `db check` text may also mention `--reuse-from`, which is optional).
- `data/ideology.db` (upgraded to `0012`, nothing else changed).
- Tests: `tests/pipeline_fixtures.py` (the default `statements_payload` becomes pool-sized, 50), new `tests/test_pipeline_selection.py`, and `test_pipeline_{prompts,generation,positions,runs,checkpoint}.py`, `test_cli_pipeline.py`, `test_cli_pipeline_report.py`, `test_migrations.py`.
  - Adapt every test that expects 30 Statements; with all-tie fixtures the selection is pool Statements 1..35.
  - Adapt every test that relied on a duplicate or topic failure reaching Validation: the selection now removes those. Either use failures the selection cannot fix (a Party with no findings for `party_coverage`, a single value everywhere for `statement_separation`), or generate with laxer settings and validate with stricter ones, as `pipeline-output-bounds` did.
  - Do not delete a test without a replacement.
- `apps/web/src/features/methodology/MethodologyPage.tsx` and `MethodologyPage.test.tsx`.
- Docs: see below.

## Visual Design Impact

- UI involved: yes, static copy only on `/metodologia`. Follow `DESIGN.md`. Add one `<section aria-labelledby>` region using the existing markup. No new styles, no per-Party treatment, no request.
- New section (after "Cómo se sitúa a cada partido", before "Comprobaciones antes de publicar"), heading **"Cómo se eligen las afirmaciones del cuestionario"**. The regions become 8. Paragraphs (exact):
  1. "La inteligencia artificial propone más afirmaciones de las que tendrá el cuestionario, entre 45 y 60, y sitúa a cada partido en todas ellas. Después, un procedimiento automático, sin inteligencia artificial y sin azar, elige entre 25 y 35 para el cuestionario."
  2. "Deja fuera las afirmaciones repetidas y las que no separan a los partidos, porque todos los que tienen posición coinciden, y no deja que un tema supere el 30&nbsp;% del cuestionario. Entre las demás, elige primero las que dan posición al partido que menos tiene hasta ese momento; en caso de empate, las que muestran más posiciones distintas y, después, las que se propusieron antes. Todos los partidos cuentan igual."
  3. "El cuestionario tiene el mayor número de afirmaciones con el que todos los partidos tienen posición en al menos el 70&nbsp;% de ellas. Si no es posible cumplir estas condiciones, el procedimiento se acerca todo lo que puede y las comprobaciones posteriores impiden publicar el resultado. Las afirmaciones conservan el texto y el orden con que se propusieron."
- In "Cómo se redactan las afirmaciones", replace "Después elige y redacta la lista final, de unas 30 afirmaciones, y asigna a cada una un tema." with "Después elige y redacta una lista más amplia, de unas 55 afirmaciones candidatas, y asigna a cada una un tema.". The second paragraph adds "y propuestas que traten varios programas" after "propuestas en las que los partidos discrepen".
- Browser check: run `CI=true ./init.sh` in the worktree and serve with a temporary `.claude/launch.json` entry:
  - `/usr/bin/env WEB_DIST_DIR=<worktree>/apps/web/dist DATABASE_URL=sqlite:///<scratch outside repo>/check.db <worktree>/.venv/bin/uvicorn ideology_app.main:app --port 8061`;
  - build the scratch DB with `<worktree>/.venv/bin/ideology db upgrade`;
  - never use port 8000 or another worktree's `data/ideology.db`;
  - remove the entry and the scratch DB afterwards.

## Durable Documentation Impact

- `ARCHITECTURE.md` (update): the pipeline module list (`selection.py`, with its signature, algorithm summary and dependency on `validation`); the `prompts.py` line (pool constants, versions v1/v3/v2/v2); the `generation.py` line (`pool_bounds`); the `runs.py` line (selection step, `statement_selection` in `_finish`, `allow_finished_source`); `reports.py`; the CLI `--reuse-from`; migration `0012`.
- `CONSTRAINTS.md` (update):
  - The LLM rule: the `generate_statements` pool schema derives its bounds from the run's `ValidationSettings` via `pool_bounds` (never a second copy).
  - Pipeline (new rule): the final Statements MUST be chosen only by `pipeline.selection.select_statements` (deterministic: no LLM, randomness or clock; every Party weighted the same; thresholds only from the run's `ValidationSettings`), before the Dataset Version is written. Selected text and topic are stored exactly as the provider returned them.
  - Pipeline (new rule): `pipeline_runs.statement_selection` MUST be written only by `runs._finish`, in the Dataset Version's commit, and never updated.
  - Reword the checkpoint rule so that reuse needs an explicit `resumed_from_run_id` set by `--resume-from` or `--reuse-from`.
  - Reword the Validation rules "MUST NOT be dropped / deduplicated / reordered" so they apply to a Dataset Version once written; the pre-write selection is the only place Statements are left out.
- `AGENTS.md`: not needed.
- `docs/domain-model.md`: Pipeline Run records the Statement Selection; `--reuse-from`.
- `CONTEXT.md`: add the terms **Statement Pool** and **Statement Selection**.
- `docs/technical-discovery.md`: runbook steps 3/7 mention `--reuse-from R` for re-running after a finished or failed run.
- `docs/risks-and-open-questions.md`:
  - Update the "Settled: the prompts and chunking" line (pool; versions v1/v3/v2/v2).
  - Update "Coverage threshold vs real manifestos", "Separation vs real manifestos" and "Questionnaire shape vs real output": the selection now mitigates them, and duplicates and topic share are enforced before Validation.
  - Update "Perceived bias in Statements" with the selection mitigations.
  - Add a High risk, **"Selection shapes the Questionnaire by observed positions (`pipeline-coverage-selection`)"**:
    - Topics are chosen by where manifestos take explicit stances. Long manifestos produce more candidates, so the pool skews toward them.
    - Leximin favours whichever Party is worst covered, which is data-dependent: its topics gain weight.
    - The separation preference drops consensus topics and favours polarising ones.
    - Validation now partly measures what the selection optimised.
    - Mitigations: identical treatment of Parties (symmetry test), no LLM in the selection, the full pool and scores stored and shown by `pipeline report`, public copy, unchanged thresholds.
    - Open: real-model pool quality (owner `e2e-real-2023-election`).
  - Add a note on the shared-DB migration coordination with the run-2 DB.

## Implementation Plan

1. Prompts and pool bounds (v3, fingerprint), plus generation tests.
2. `selection.py` and its plain-data tests.
3. Wire `execute_run` / `_finish`; migration `0012`, model, `alembic check`; runs tests; adapt the fixtures and the affected tests.
4. Reuse flag (`queue_run`, CLI) and tests.
5. Report lines and table, plus CLI report tests.
6. Methodology copy and Vitest; browser check.
7. Docs; upgrade and commit `data/ideology.db`; `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `prompts.py`: pool constants, `GENERATE_STATEMENTS` v3 texts and max_tokens 16384, remove `TARGET_STATEMENT_COUNT`; the `FINGERPRINTS` entry `("generate_statements","v3")`; `REFERENCE_SCHEMAS["generate_statements"] = statement_set_schema(45, 60)`.
- [ ] `generation.py`: `pool_bounds`, `reduce_request` with the pool bounds and target.
- [ ] `selection.py`: `select_statements`, `Selection`, `SELECTION_VERSION`, using the validation check functions.
- [ ] `runs.py`: selection step, `_finish(selection=…)`, `queue_run(allow_finished_source=…)`.
- [ ] `models.py` + `0012` migration (reviewed by hand; one column; `recreate='never'` downgrade).
- [ ] `reports.py` + `cli.py` (`--reuse-from`, report lines and table).
- [ ] Tests and fixtures as listed; Methodology page and test.
- [ ] Docs; `data/ideology.db` upgraded, `db check` → `Safe to commit: yes`.

## Verification Plan

pytest (FakeProvider only, offline guards kept):
- `tests/test_pipeline_selection.py`:
  - `test_selection_is_deterministic`
  - `test_party_relabelling_does_not_change_selection`
  - `test_duplicates_keep_first_in_pool_order`
  - `test_topic_cap_is_never_exceeded_and_topic_spread_passes`
  - `test_count_within_settings_range` (defaults and custom settings)
  - `test_worst_covered_party_is_served_first`
  - `test_ties_prefer_distinct_then_spread_then_pool_order`
  - `test_largest_count_that_meets_coverage`
  - `test_best_worst_coverage_when_threshold_unreachable`
  - `test_non_separating_fill_only_to_minimum`
  - `test_fewer_unique_than_minimum_keeps_all`
  - `test_selected_in_pool_order_and_positions_renumbered_with_evidence_unchanged`
  - `test_report_is_json_and_complete`
- `tests/test_pipeline_generation.py`:
  - `test_pool_schema_bounds_follow_settings` (45..60; `max_statements=70` → 70..70)
  - `test_out_of_range_pool_fails_the_call` (44, 61)
  - `test_pool_prompt_asks_for_target`
  - the existing `statement_candidates` hash test unchanged.
- `tests/test_pipeline_prompts.py`: fingerprints (only `generate_statements` changed), `PROMPT_VERSIONS == {statement_candidates: v1, generate_statements: v3, position_findings: v2, party_positions: v2}`.
- `tests/test_pipeline_positions.py`: `test_requests_bound_to_pool_size` (schema maximum 60 with a 60-Statement pool).
- `tests/test_pipeline_runs.py`:
  - `test_dataset_version_holds_only_selected_statements`
  - `test_llm_call_count_unchanged` (= chunks + 1 + chunks + Parties)
  - `test_selection_stored_in_finish_commit`
  - `test_failed_generation_stores_no_selection`
- `tests/test_pipeline_checkpoint.py`:
  - `test_reuse_from_a_run_with_a_dataset_version` (passed and failed)
  - `test_reuse_refused_for_unknown_run_other_model_other_election`
  - the existing `test_resume_is_refused_for_a_run_with_a_dataset_version` unchanged.
- `tests/test_cli_pipeline.py`:
  - `test_cli_reuse_from_prints_and_reuses`
  - `test_reuse_from_and_resume_from_are_exclusive`
  - `test_reuse_from_still_runs_the_unfinished_guard`
- `tests/test_cli_pipeline_report.py`:
  - `test_report_shows_statement_selection_and_pool_table`
  - `test_report_old_run_selection_not_recorded`
  - the existing read-only test.
- `tests/test_migrations.py`:
  - `test_upgrade_0012_adds_nullable_statement_selection_and_keeps_rows`
  - `test_downgrade_to_0011_drops_only_the_column_and_keeps_versions` (with Dataset Version child rows)
  - `test_offline_postgresql_render_of_0012`
  - `test_migrations_match_models` passes.
- `tests/test_committed_database.py` passes (DB at head).

Vitest: `MethodologyPage.test.tsx`:
- 8 regions in order;
- the exact text of the new section (with NBSP before `%`);
- the updated "unas 55 afirmaciones candidatas" sentence;
- no request.

Browser: `/metodologia` at 375px and desktop, every section readable, console clean, no failed request (port 8061, scratch DB).

Gate: `CI=true ./init.sh` passes (pytest, web typecheck, Vitest, build). E2E: there is no persistent browser E2E harness; the copy is covered by Vitest and the browser check.

## Evidence To Capture

- pytest/Vitest counts from `CI=true ./init.sh`; the names of the new tests; `alembic check` with no drift; `ideology db check` printing `Safe to commit: yes` on the upgraded `data/ideology.db`.
- A sample `pipeline report` output (fake run) showing the selection lines and table.
- Browser check: browser name, widths 375px and desktop, console clean.
- Record these in `feature_list.json` and `PROGRESS.md` only (never in `docs/validations/`).

## Validator Checklist

- [ ] `statement_candidates` request hash unchanged; only `generate_statements` bumped (v3).
- [ ] The selection is pure, deterministic and Party-symmetric, and reads only `ValidationSettings`; no threshold literal is duplicated; it reuses the validation check functions.
- [ ] The Dataset Version holds only the selected Statements (pool order, 1..n), with Positions and Evidence identical to the extraction.
- [ ] LLM call count unchanged; Validation checks and thresholds unchanged.
- [ ] `statement_selection` is written once in `_finish`; the report is read-only and shows it.
- [ ] `--reuse-from` works from a finished run; `--resume-from` refusal and unfinished guard unchanged.
- [ ] Migration `0012` adds one column, its downgrade keeps rows, and the committed DB is upgraded and passes `db check`.
- [ ] Methodology copy updated with its test; browser check recorded.
- [ ] CONSTRAINTS/ARCHITECTURE/risks/runbook/domain docs updated; `feature_list.json` and `PROGRESS.md` updated.
