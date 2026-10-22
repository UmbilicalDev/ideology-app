# Feature Implementation Spec: Orientation-level Statements from a Party-balanced agenda; coverage threshold 60%

## Source Feature

- `id`: pipeline-balanced-statements
- `area`: pipeline
- `depends_on`: none
- `status`: `not_started` at planning time
- `source`: `feature_list.json`

## Goal

The real run on `feature/e2e-real-2023-election-main` (run 1 in that branch's DB) produced a 58-Statement pool and selected 26, but only ERC reached 70 % coverage (PP 46 %, PSOE 58 %, VOX 46 %, SUMAR 65 %, ERC 77 %, JUNTS 54 %, EH Bildu 46 %, EAJ-PNV 46 %, BNG 58 %). Only 220 of 522 Statement × Party pairs had a stance, and no Statement had all 9 Parties. There were two causes:

- the Statements were concrete measures ("jornada de 32 horas", "45 días de indemnización") that only one or two manifestos state;
- the agenda followed manifesto length. Every chunk returned the maximum 12 candidates, so PSOE (19 chunks) and SUMAR (19) gave 47 % of the 935 candidates, while EH Bildu (1 chunk of 16 pages) gave 12 (1 %).

After this feature, a run:

1. Keeps the `statement_candidates` map byte-identical.
2. Picks, in deterministic code, **the same number of candidates from every Party** (the Party-balanced agenda), spread over the topics that Party's own manifesto treats most.
3. Asks `generate_statements` (v4) for **orientation-level** Statements: one policy direction a voter can agree or disagree with (raise or lower a tax, more or less nuclear energy), with no figures or detailed measures, grouping candidates from several manifestos on the same axis, contested rather than consensus, and based only on the candidates.
4. Uses `position_findings` (v3), which says explicitly that a concrete proposal clearly going in a Statement's direction, or in the opposite one, counts as treating it. The proposal must be in the quote. Inference from ideology or from silence stays forbidden.
5. Selects and validates as today, with `DEFAULT_MIN_PARTY_COVERAGE_PERCENT` lowered from 70 to 60 (user decision, 2026-10-22). The methodology page says so.

## Non-Goals

- No inferred stances (direction B, deferred). No knowledge source other than the committed manifestos. No new documents, and no external knowledge in prompts.
- No change to `statement_candidates` (prompt, schema, `CANDIDATE_REQUEST_HASH`), `party_positions` (v2), chunking, call caps, pool bounds (45..60, target 55), the selection algorithm (`SELECTION_VERSION` v1), or the Validation checks. The only exception is the coverage default.
- No new LLM call, no migration, no change to `data/ideology.db` rows, no `/api/v1` change.
- No real LLM run (that belongs to `e2e-real-2023-election`). Tests never call a real LLM or the `claude` CLI.

## Job Story

When a run's Statements follow the longest manifestos and their detailed measures,
I want every Party to weigh the same in the agenda and the Statements to be policy directions most Parties can be placed on,
so that coverage and separation can pass on real manifestos without inventing stances.

## Users And Permissions

- Operator (CLI): `pipeline run [--reuse-from R]`, `pipeline report --run N` (one new read-only line).
- Voter: sees only the published Dataset Version and the updated `/metodologia` copy.

## Acceptance Scenarios

1. **Equal quota.**
   - Given 9 Parties with the run-1 shape (unique candidates 72, 216, 60, 228, 144, 108, 12, 48, 47; a fake that answers per chunk), when generation runs, then `quota = max(ceil(60/9)=7, min(24, 12)) = 12` and every Party contributes exactly 12. The `generate_statements` request lists 108 lines.
   - Given 2 Parties with 100 candidates each, `quota = max(30, 24) = 30`.
   - Given 3 Parties with 36, 24 and 12, `quota = max(20, 12) = 20`, so they contribute 20, 20 and 12 (shortfall, see 2).
   - The agenda report records the quota and the picks per Party.
2. **Shortfall, nothing invented.** A Party with fewer unique candidates than the quota contributes all of them and no others. A Party with 0 candidates contributes none and is listed with `picked 0`. If every Party has 0, the existing `GenerationError(NO_CANDIDATES_REASON)` is raised before the reduce call.
3. **Even spread.** Within a Party, picks go round-robin over its topics. Topic order: the Party's candidate count on the topic (most first), then the topic's first appearance (chunk, rank), then `TOPICS` order. Within a topic the order is (rank in chunk, chunk index). This is asserted on a constructed case.
4. **Deterministic and Party-symmetric.** The same per-chunk outputs give a byte-identical `generate_statements` request (same `request_hash`). Permuting which Party id owns which chunks' outputs leaves the request identical, and leaves the agenda report identical up to the Party ids. The prompt never contains a Party id or name.
5. **`statement_candidates` unchanged.** `CANDIDATE_REQUEST_HASH` and the `("statement_candidates","v1")` fingerprint pass unedited.
6. **Prompt versions.** `PROMPT_VERSIONS == {"statement_candidates":"v1","generate_statements":"v4","position_findings":"v3","party_positions":"v2"}`. The fingerprints are re-pinned only for the two bumped prompts.
7. **Orientation rules present.** `GENERATE_STATEMENTS.system` contains the rule lines of Technical Approach §3 verbatim. `POSITION_FINDINGS.system` still contains "Nunca deduzcas una posición de la ideología general." and the verbatim-quote rule, plus the two new lines of §4.
8. **Call count.** A FakeProvider run makes `chunks + 1 + chunks + Parties with findings` calls, the same formula as before.
9. **Agenda recorded.** After `_finish`, `pipeline_runs.statement_selection["agenda"]` holds the agenda report. `pipeline report --run N` prints `statement_agenda: …`; a run without it prints `statement_agenda: not recorded`.
10. **Threshold 60.** `DEFAULT_MIN_PARTY_COVERAGE_PERCENT == 60` and `ValidationSettings().min_party_coverage_percent == 60`. With no env value set, a run's selection (`count_rule`, `coverage_met` at 60 %) and Validation both use 60. A Party at 18/30 (60 %) passes and one at 17/30 fails.
11. **Methodology copy.** `/metodologia` shows the new texts of §6 (60 %, balanced agenda, orientations, concrete-proposal rule). It is checked in a real browser at 375 px and desktop with a clean console.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONSTRAINTS.md` (Pipeline, LLM Providers, Public Copy, Shared Database), `ARCHITECTURE.md` (Pipeline and Validation sections), `CONTEXT.md` (Statement Pool, Statement Selection), `PROGRESS.md` (head), `feature_list.json` (this entry, uncommitted), `docs/risks-and-open-questions.md` (lines 10, 20-27, 62, 79, 97-105), `docs/domain-model.md:43`.
- `docs/specs/pipeline-coverage-selection.md` (read in full). The other listed specs were known through ARCHITECTURE/CONSTRAINTS; I did not re-read them line by line.
- `src/ideology_app/pipeline/prompts.py`: `_COMMON_RULES` is shared by `statement_candidates` and `generate_statements`, so it must not change. Also read `GENERATE_STATEMENTS` v3 and `POSITION_FINDINGS` v2.
- `pipeline/generation.py` (`generate_statements(provider, chunks: Sequence[str], …)` loses the Party of each chunk; `reduce_request` dedupes and sorts `(topic, text)`; `build_document_chunks` keeps `party_id`), `pipeline/runs.py:385-415` (`build_chunks` call, `_finish(selection=…)`), `pipeline/checkpoint.py` (`request_hash` covers system, prompt, schema, max_tokens).
- `src/ideology_app/config.py:41,92,202`, `cli.py:1085-1193` (`_selection_lines`), `apps/web/src/features/methodology/MethodologyPage.tsx` (lines 49-62 statements, 66-84 positions, 103, 118) and its test (lines 74, 154).
- `tests/test_pipeline_prompts.py` (`FINGERPRINTS`, `REFERENCE_SCHEMAS`, `CANDIDATE_REQUEST_HASH`), `tests/test_pipeline_generation.py` (passes plain strings as chunks), `tests/pipeline_fixtures.py` (`candidates_response`).
- I read the evidence DB read-only, from a scratch copy outside the repo. Its 79 recorded `statement_candidates` outputs: every chunk returned 12 candidates (BNG's last chunk 11), 934 unique. Chunks per Party: PP 6, PSOE 19, VOX 5, SUMAR 19, ERC 12, JUNTS 9, EH Bildu 1, EAJ-PNV 4, BNG 4. I simulated the rule below on them: quota 12 gives 108 lines; 8 Parties cover 12 distinct topics each, EH Bildu 6; all 18 topics appear (employment 11 … infrastructure 3).

### Existing Patterns To Follow

- Pure, DB-free modules for LLM orchestration (`generation.py`, `selection.py`). The DB is touched only in `runs.py`. Deterministic code has no `random`, no clock and no iteration over unordered sets.
- Bump a prompt by changing its `version` and replacing its `FINGERPRINTS` entry. The audit JSON is written once in `_finish`.

### Current Gaps

- Nothing balances candidates by Party, and `generate_statements` does not know which Party each chunk belongs to.

## Technical Approach

**1. New pure module `src/ideology_app/pipeline/agenda.py`.** It imports only `prompts` (no DB or LLM).

```python
AGENDA_VERSION = "v1"
PARTY_QUOTA_MAX = 24
@dataclass(frozen=True)
class Agenda:
    candidates: tuple[StatementDraft, ...]   # union of picks, deduped, sorted by (topic, text)
    quota: int
    report: dict[str, Any]                   # JSON, see below
def balance_candidates(per_chunk: Sequence[tuple[int, Sequence[StatementDraft]]],
                       pool_max: int) -> Agenda
```

`per_chunk` is `(party_id, candidates of that chunk)` in chunk order.

Rule:

1. **Unique candidates per Party.** For each Party, keep its unique `(topic, text)` in first-seen order. Record for each its `chunk` (0-based index among that Party's chunks) and `rank` (index in that chunk's output). `n_p` is the count.
2. **Quota.** `P` = the number of Parties with `n_p ≥ 1`. `quota = max(ceil(pool_max / P), min(PARTY_QUOTA_MAX, min n_p over those Parties))`. Each Party contributes `min(n_p, quota)`.
   - In the normal case every Party gives exactly the smallest Party's count (capped at 24). Equal weight is achieved by cutting the long manifestos down, never by inventing content for short ones.
   - The floor `ceil(pool_max / P)` (60/9 → 7) applies only when the smallest Party has fewer candidates than that. It keeps at least `pool_max` lines when the others have enough; the short Party then gives everything it has, recorded as a shortfall.
   - The cap keeps the reduce input focused (at most 216 lines for 9 Parties). Run 1's reduce had 934 lines.
3. **Spread within a Party.**
   - Group the Party's candidates by topic.
   - Order its topics by: count desc, then first appearance `(chunk, rank)`, then `TOPICS` index. This is the Party's own emphasis, with no global topic order beyond the last tie-break.
   - Within a topic, order by `(rank, chunk)`, so each chunk's first proposals come first.
   - Pick round-robin: round 1 takes the first candidate of every topic in that order, round 2 the second, and so on, until the Party's share is reached.
4. **Union.** Take all picks and drop exact cross-Party duplicates. The result, sorted by `(topic, text)`, is `Agenda.candidates`.
   - The reduce lines therefore do not depend on Party ids or their order, which gives the symmetry.
   - No Party label enters the prompt.
5. **Report:**
   ```json
   {"version":"v1","pool_max":60,"floor":7,"quota_max":24,"quota":12,"lines":108,
    "parties":[{"party_id":1,"chunks":6,"candidates":72,"unique":72,"picked":12}]}
   ```
   `parties` are in Party-id order and include every Party seen in `per_chunk`.

Why not a topic-first agenda? Equal weight is the user's requirement, and per-topic slots would give a Party more weight on topics where others are silent. The round-robin over each Party's own topics already gives breadth.

Why balance in code and not in `statement_candidates`? Its request stays byte-identical, so `--reuse-from` reuses all recorded map calls (79 for the 2023 bundle). The balance becomes an auditable deterministic rule, and the call count does not change.

**2. `generation.py`.**
- `generate_statements(provider, chunks: Sequence[Chunk], usage, settings=None) -> StatementPool`, where `StatementPool(statements: tuple[StatementDraft, ...], agenda: Agenda)` is frozen.
- It calls `candidate_request(chunk.text)` per chunk (unchanged), then `balance_candidates([(chunk.party_id, output.candidates) …], pool_max=pool_bounds(settings)[1])`, then `reduce_request(agenda.candidates, settings)`.
- The `too many chunks` and `no candidates` errors stay, at the same points. `reduce_request` itself is unchanged (it still dedupes and sorts).
- `runs.execute_run` passes `build_document_chunks(run_input.documents)` (same texts, same order as `build_chunks`) and uses `pool.statements`. It calls `_finish(..., selection={**selection.report, "agenda": pool.agenda.report})`.
- `build_chunks` stays and is still exported. Export `Agenda`, `balance_candidates`, `AGENDA_VERSION`, `PARTY_QUOTA_MAX`, `StatementPool` from `pipeline/__init__.py`.

**3. `GENERATE_STATEMENTS` v4** (template and `max_tokens=16384` unchanged; `_COMMON_RULES` unchanged). Exact system text:

> "Eres un analista político que prepara un cuestionario de orientación de voto para unas elecciones generales en España. Recibes afirmaciones candidatas extraídas, en igual número, de los programas electorales de varias candidaturas, y redactas a partir de ellas una lista amplia de afirmaciones; después, un procedimiento automático elegirá entre ellas las del cuestionario.\n\n{_COMMON_RULES}\nReglas para la lista:\n- Cada afirmación expresa una orientación política con una dirección clara (por ejemplo, subir o bajar un impuesto, ampliar o reducir un servicio público, más o menos peso de una fuente de energía), no una medida de detalle: sin cifras, porcentajes, plazos ni nombres de leyes o planes concretos.\n- Agrupa en una misma orientación las candidatas de programas distintos que van en esa dirección o en la contraria, para que el mayor número posible de programas se pueda situar en ella.\n- Elige orientaciones en las que los programas discrepen; evita las que casi cualquier programa suscribiría.\n- Varía el sentido de las afirmaciones: no todas deben proponer aumentar o ampliar algo; usa también reducir, limitar o suprimir cuando así lo planteen las candidatas.\n- Basa cada afirmación solo en las candidatas: no añadas temas ni propuestas que no aparezcan en ellas.\n- Cubre los temas de forma amplia: ningún tema debe superar aproximadamente una cuarta parte de la lista.\n- Sin afirmaciones casi duplicadas."

The `_COMMON_RULES` lines on a single proposition, neutral wording and a 5-point affirmative form still apply.

**4. `POSITION_FINDINGS` v3** (template, schema and `max_tokens` unchanged). In the `Reglas:` list, keep the first line unchanged and insert two lines right after it:

> "- Una propuesta concreta del fragmento que va claramente en la dirección de una afirmación, o en la contraria, cuenta como tratarla de forma explícita: la posición es de acuerdo si va en esa dirección y en desacuerdo si va en la contraria, y la cita debe contener esa propuesta.\n- Que el fragmento no mencione un asunto no es una posición: no informes de esa afirmación."

Justification:

- Orientation-level Statements are rarely restated literally. A manifesto expresses a direction through concrete measures (run 1 had 2.3–7 findings per chunk). A strict reading of "de forma explícita" would discard exactly those measures.
- The evidence rule does not change in substance:
  - the quote must still be verbatim and must contain the proposal, so a Voter can check it;
  - ideology-based inference stays forbidden (the existing line stays);
  - silence is now named explicitly as not a stance.
- Naming the contrary direction lets explicit counter-proposals become −1/−2. This is a partial answer to the observed positive-stance bias.
- The findings requests change in every run anyway, because the Statements change, so the bump costs no reuse.

**5. Threshold.** `config.DEFAULT_MIN_PARTY_COVERAGE_PERCENT = 60` and its docstring ("default 60"). Validation and the selection already read `ValidationSettings`, so no other code changes. Tests that rely on the default change from 70 to 60 (expected messages such as `minimum is 70%`, the `(70, 25, 35, 30)` defaults tuple, the party-coverage default tests). Tests that pass an explicit 70 keep it.

**6. Methodology copy** (`MethodologyPage.tsx`; NBSP before `%`, as today; no new section, still 7 regions).
- "Cómo se redactan las afirmaciones", replacing both paragraphs:
  - P1: "Una inteligencia artificial lee los programas por fragmentos y propone afirmaciones candidatas: propuestas políticas con las que se puede estar de acuerdo o en desacuerdo. Después, un procedimiento automático, sin inteligencia artificial y sin azar, toma el mismo número de candidatas de cada partido, sea cual sea la extensión de su programa, repartidas entre los temas que más trata cada programa. Un partido con menos candidatas aporta todas las que tiene."
  - P2: "Con esas candidatas, la inteligencia artificial redacta una lista más amplia, de unas 55 afirmaciones, y asigna a cada una un tema. Cada afirmación expresa una orientación política con una dirección clara, como subir o bajar un impuesto, y no una medida de detalle, para que el mayor número posible de partidos se pueda situar en ella."
  - P3: "Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres de partidos o de políticos, una sola propuesta por afirmación, temas variados, orientaciones en las que los partidos discrepen y no añadir nada que no esté en las candidatas. Nadie modifica a mano el resultado."
- "Cómo se sitúa a cada partido", replacing paragraph 2: "Si el programa no trata una afirmación, el partido queda sin posición en ella: sus instrucciones le prohíben deducir la posición de la ideología general del partido o de que el programa no mencione el asunto. Sí cuenta como tratarla una propuesta concreta del programa que va claramente en la dirección de la afirmación o en la contraria, y la cita debe contener esa propuesta."
- Lines 103 and 118: `70&nbsp;%` becomes `60&nbsp;%`. Update `MethodologyPage.test.tsx` with the exact texts.

**7. Report line.** In `cli._selection_lines`, before `statement_selection`, add:

`statement_agenda: v1, quota 12, lines 108; party 1 12/72 (6 chunks); party 2 …`

It reads `statement_selection.get("agenda")`; when that is missing, it prints `statement_agenda: not recorded`.

## Expected File Changes

- Create `src/ideology_app/pipeline/agenda.py` and `tests/test_pipeline_agenda.py`.
- Modify `src/ideology_app/pipeline/{prompts,generation,runs,__init__}.py`, `src/ideology_app/config.py` and `src/ideology_app/cli.py`.
- Modify tests:
  - `tests/test_pipeline_{prompts,generation,runs,positions,checkpoint,selection}.py`, `tests/test_cli_pipeline{,_report}.py`, `tests/test_validation_{party_coverage,runs,questionnaire_shape}.py`, `tests/test_cli_live_mode.py`, `tests/test_llm_anthropic.py` and `tests/test_llm_claude_code.py`, as needed;
  - `tests/pipeline_fixtures.py`, which may gain a per-Party candidates helper.
  - Do not delete any test without a replacement.
- Modify `apps/web/src/features/methodology/MethodologyPage.tsx` and `.test.tsx`.
- Docs: see below. Not changed: `data/ideology.db`, migrations, `init.sh`.

## Visual Design Impact

- UI involved: yes, copy only, on `/metodologia`. Source: `DESIGN.md`. Existing layout and classes; no new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Add `agenda.py` to the package list, with the rule, the dependency `prompts → agenda → generation` and the `StatementPool` return type.
  - Prompt versions (`generate_statements` v4, `position_findings` v3) and a summary of the v4/v3 rules.
  - `ValidationSettings` default 60.
  - The `agenda` key in `statement_selection` and the report line.
- `CONSTRAINTS.md`: update the Pipeline section with two rules.
  - (a) "The candidates sent to `generate_statements` MUST be chosen only by `pipeline.agenda.balance_candidates`: deterministic, the same quota for every Party, no Party label in the prompt. Reason: agenda balance must be reproducible and party-neutral."
  - (b) "`position_findings` MUST NOT allow stances inferred from general ideology or from silence; every stance cites a verbatim quote that contains the proposal. Reason: explicit-evidence rule (direction B deferred by user decision 2026-10-22)."
  - The Public Copy rule already covers the page.
- `CONTEXT.md`: add the term **Party-balanced Agenda**: "the candidates given to Statement generation, the same number from every Party whatever its manifesto length". Update Statement Pool so it says the pool is generated from that agenda.
- `docs/domain-model.md:43`: change "default 70%" to "default 60%".
- `docs/risks-and-open-questions.md`, in the same change:
  - line 10: the versions become v1/v4/v3/v2, and add "candidates balanced per Party by `agenda.balance_candidates` since `pipeline-balanced-statements`";
  - line 27: coverage 60 %;
  - the "Perceived bias" entry: add the Party-balanced agenda as a mitigation (the agenda-length bias is fixed). Keep it open: wording is unverified, and the positive-stance bias remains, because stances still come from what manifestos propose (v3 only lets explicit counter-proposals count);
  - the UPN entry: its 36 % would still fail at 60 %;
  - the coverage entry: record the user decision (70 → 60 on 2026-10-22, a deliberate threshold change, not a per-run one), the run-1 numbers, and a new sub-point: **EH Bildu has a structural ceiling**. Its single 16-page document is one chunk, so it has at most 12 candidates and one findings call. The quota makes it weigh equally in the agenda, but its coverage still depends on that one call;
  - the separation entry: orientation-level Statements plus the "contested axes" rule are the new mitigation. Open until a real run;
  - the selection entry: delete "long manifestos produce more candidates, so the pool skews toward them" (fixed), and add that the quota is set by the shortest manifesto;
  - add to Implementation-Time Questions: "Deferred (user decision 2026-10-22): direction B, stances inferred from a manifesto's general orientation without an explicit quote. Not built; it would need a new Evidence model and Validation";
  - add a risk: "Agenda size with a short manifesto: with quota 12 the reduce sees about 108 lines for a 45..60 pool; if the model pads the pool or invents beyond the candidates, revisit `PARTY_QUOTA_MAX`/floor (`e2e-real-2023-election`)."
- `AGENTS.md`: not needed (no workflow change).

## Implementation Plan

1. Write `agenda.py` and its tests (quota, shortfall, spread, symmetry, report).
2. Wire it into `generation.py`/`runs.py` (`Chunk` input, `StatementPool`, agenda in `statement_selection`), and adapt the generation, runs and checkpoint tests.
3. Bump the prompts (v4, v3), re-pin their fingerprints and assert the rule lines. `CANDIDATE_REQUEST_HASH` must pass untouched.
4. Change the threshold to 60 and adapt the dependent tests.
5. Add the CLI report line and its tests.
6. Update the methodology copy and tests, then check it in the browser.
7. Update the docs above. Run `CI=true ./init.sh`, then record evidence in `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks

- [ ] `agenda.py`: `balance_candidates`, `Agenda`, constants and docstrings stating the rule.
- [ ] `generation.generate_statements` takes `Sequence[Chunk]` and returns `StatementPool`; `runs.execute_run` uses `build_document_chunks` and stores the agenda.
- [ ] `prompts.py`: `GENERATE_STATEMENTS` v4 and `POSITION_FINDINGS` v3 texts exactly as in §3/§4; re-pin `FINGERPRINTS`.
- [ ] `config.py`: default 60, docstring.
- [ ] `cli.py`: `statement_agenda` line.
- [ ] Methodology page and test copy.
- [ ] Tests for scenarios 1-10; adapt existing tests.
- [ ] Docs: ARCHITECTURE, CONSTRAINTS, CONTEXT, domain-model, risks.

## Verification Plan

- `CI=true ./init.sh` exits 0 (pytest, Vitest, typecheck, build). Report the counts against main (pytest 1388, Vitest 349).
- `.venv/bin/python -m pytest tests/test_pipeline_agenda.py tests/test_pipeline_prompts.py tests/test_pipeline_generation.py tests/test_pipeline_runs.py tests/test_validation_party_coverage.py tests/test_cli_pipeline_report.py -q`. The prompts test must pass with `CANDIDATE_REQUEST_HASH` and the `statement_candidates` fingerprint unedited (`git diff` shows that line untouched).
- `grep -n "70" src/ideology_app/config.py apps/web/src/features/methodology/MethodologyPage.tsx docs/domain-model.md` shows no coverage-threshold 70 left.
- Optional offline sanity check: run `balance_candidates` on run 1's recorded candidate outputs from a scratch copy of the evidence DB outside the repo. Expect quota 12 and 108 lines.
- **Browser (required)**, following `.agents/skills/github-flow/references/practical-notes.md` "Checking A Worktree's Build In A Browser":
  - after the gate, add a temporary `.claude/launch.json` entry `tmp-pipeline-balanced-statements` with absolute worktree paths (`WEB_DIST_DIR=<worktree>/apps/web/dist`, `DATABASE_URL=sqlite:///<scratch-dir>/check.db` outside the repo, migrated with `<worktree>/.venv/bin/ideology db upgrade`) and `uvicorn … --port 8071`. Never use the user's server on port 8000 or `data/ideology.db`;
  - open `/metodologia` at 375 px and at desktop width. Check the new statements and positions paragraphs and both "60 %" mentions, and that nothing overflows at 375 px. Read the console (no errors) and the network (no failed requests);
  - stop the server, remove the temporary entry, delete the scratch DB. `git status` shows only the feature's files.

## Evidence To Capture

- The gate counts. The test names for scenarios 1-10. Proof that the `CANDIDATE_REQUEST_HASH` line is unchanged. The new `PROMPT_VERSIONS`.
- The browser check: browser name, widths 375 and desktop, console and network clean, the texts seen. The optional run-1 agenda simulation output.

## Validator Checklist

- [ ] The `statement_candidates` request is byte-identical: the hash and fingerprint pins are unedited.
- [ ] Only `generate_statements` (v4) and `position_findings` (v3) were bumped. The findings prompt still forbids ideology-based inference and requires verbatim quotes, and names silence as no stance.
- [ ] The agenda is deterministic, has the same quota for every Party, and puts no Party id or name in any prompt. The symmetry test exists.
- [ ] The call count formula is unchanged. There is no new LLM call, migration or DB row change.
- [ ] The default coverage is 60 everywhere (config, docs, methodology page and test). Explicit-70 tests keep their meaning.
- [ ] The risks doc entries are updated as listed: agenda bias fixed, positive-stance bias open, 60 % decision, EH Bildu ceiling, direction B deferred. CONSTRAINTS, ARCHITECTURE and CONTEXT are updated.
- [ ] The browser check of `/metodologia` at 375 px and desktop is recorded. The temporary launch entry is removed.
- [ ] `feature_list.json` and `PROGRESS.md` were updated, and there is no `docs/validations/`.
