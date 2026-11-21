# Feature Implementation Spec: Clearer Statements and a neutral AI-generated context note per Statement

## Source Feature

- `id`: pipeline-statement-clarity-context
- `area`: pipeline
- `depends_on`: none (developed on `feature/pipeline-statement-clarity-context`, stacked on `three-option-scale` and `questionnaire-quick-answer`; merges into `v2`, never `main`)
- `status`: `not_started` at planning time
- `source`: `feature_list.json`; user decisions in `docs/risks-and-open-questions.md`, "Voter feedback round 1" (2026-11-21, settled)

## Goal

Voters found several published Statements of Dataset Version 5 (Election 2, `Elecciones generales 2026`) hard to read. Examples from `data/ideology.db`:

- Agreeing means opposing something: #2 "Debe derogarse la Ley de Vivienda de 2023, que permite … limitar … el alquiler", #7 "Debe derogarse la reforma laboral de 2012 …", #10 "Debe derogarse la … «ley mordaza» …".
- Abstract rules: #32 "Por cada nueva regulación que afecte a las empresas deben derogarse dos normas existentes".
- Unexplained names: CIE (#23), cheque escolar (#16), conciertos educativos (#17), ayuda oficial al desarrollo (#25), República Árabe Saharaui Democrática (#27), Plan Nacional del Agua (#28).
- Good examples to keep: #1, #6, #14, #22, #29. Each states one measure in a positive form, in plain words.

After this feature, a Pipeline Run:

1. Asks `generate_statements` (v6) to state each measure by its content and in a positive form, with no double negatives, in plain language and self-contained.
2. Gives that same request the Statements of the Election's latest Published Dataset Version as **anchors** (prompt input). The model rewrites each anchor under the new rules and tags which pool Statement came from which anchor. Selection does not change for anchors: an anchor's topic stays only if its rewritten Statement passes the same selection.
3. Gets one **context note** per Statement from the same call: a short, neutral explanation of the law, plan, institution or term the Statement names. The note is stored on the Statement (new nullable column), served by `/api/v1`, typed in `packages/core`, and checked by a new Validation check `context_note`. The check covers presence, length bounds, and no word from a configured list of evaluative words.
4. Keeps the `statement_candidates` request byte-identical. `--reuse-from 5` can then replay every recorded candidate call, and only the reduce and the position calls go to the provider.

## Non-Goals

- No priority tiers, larger extraction, Party-count ranking, or three-option separation rule. Those belong to `pipeline-statement-priority-tiers`.
- No real LLM run and no new Dataset Version in `data/ideology.db`. That belongs to `e2e-2026-dataset-clarity`.
- No Voter UI for the note: the `¿Qué significa?` disclosure is `questionnaire-length-and-context`. The only web change is `/metodologia` copy, plus the `packages/core` type and parser.
- No backfill of notes on old Dataset Versions. No hand-written or edited note, ever.
- No change to `statement_candidates` (prompt, `_COMMON_RULES`, `StatementDraft`, `CandidateList`), `position_findings` v5, `party_positions` v2, the agenda, chunking or call caps.
- No automated check of Statement wording (direction, double negatives, jargon). Those rules live in the prompt only. No check of Party names in notes (see Open Questions).

## Job Story

When a Voter meets a Statement about a law or a term they do not know, or one where agreeing means opposing something,
I want the Statement to say plainly what is proposed, with a short neutral note on what the named law, plan or institution is,
so I can answer without guessing, while the topics I already knew from the previous version stay when they still qualify.

## Users And Permissions

- Operator (CLI): `pipeline run [--resume-from R | --reuse-from R]`, `pipeline statements` (shows the note), `pipeline report` (shows the anchors line and the new pool columns), `db upgrade`, `db check`.
- Voter: reads the note through the public API (no UI in this feature) and the updated `/metodologia` copy.
- Nobody edits a note or a Statement. Notes are published only through Validation.

## Acceptance Scenarios

1. **Anchors in the reduce request.** Given Election E whose Published Dataset Version D has Statements S1..Sn, when a run executes with the FakeProvider, then the `generate_statements` prompt lists D's Statements in `position` order, as `[k] [topic] text` (k = 1..n). The schema accepts `anchor` only as `null` or an integer from 1 to n. `pipeline_runs.anchor_dataset_version_id = D`. No Party id, name or short name appears in the prompt.
2. **No Published version.** Given an Election with no Published Dataset Version (only `candidate` ones, or none), then the anchors block reads `(ninguna)`, the schema allows only `anchor: null`, and `anchor_dataset_version_id` is null. A `candidate` version is never used as anchors.
3. **Pinned anchors on resume and replay.** Given run R recorded `anchor_dataset_version_id = D`, and a newer version D' has been Published since, when a run queued with `resumed_from_run_id = R` (`--resume-from` or `--reuse-from`) executes, then it uses D. The reduce `request_hash` equals R's, and the recorded reduce call is reused with 0 tokens. If R recorded null, the run uses the current Published version.
4. **Candidate calls stay reusable.** `CANDIDATE_REQUEST_HASH` and the `("statement_candidates","v1")` fingerprint pass without being edited. `test_position_requests_are_byte_identical` passes without being edited.
5. **Prompt versions.** `PROMPT_VERSIONS == {"statement_candidates":"v1","generate_statements":"v6","position_findings":"v5","party_positions":"v2"}`. Only the `generate_statements` fingerprint is re-pinned. `GENERATE_STATEMENTS.system` contains every rule line of Technical Approach §2 verbatim.
6. **Note stored exactly.** Given a fake reduce that returns `context_note` `"  La CIE … \n"` for a selected Statement, then `statements.context_note` holds exactly that string (no trim), and `GET /api/v1/dataset-versions/{id}` returns it under `context_note`.
7. **Old versions immutable.** After `ideology db upgrade` on a copy of `data/ideology.db`, every Statement of Dataset Versions 1–5 has `context_note` NULL, and every other column is unchanged. The API serves `context_note: null` for them. `packages/core` reads `null`, and also reads a missing key as `null` (bodies cached before this feature).
8. **Validation check `context_note`.** It is appended last to `CHECKS`. With the defaults (min 30, max 300 characters):
   - a NULL or whitespace-only note gives `statement S has no context note`;
   - a stripped length of 29 or 301 gives `statement S context note has N characters; expected 30 to 300`. 30 and 300 pass;
   - a note containing `Polémica` or `injustas` (any case or accents, whole word) gives `statement S context note uses evaluative wording: injustas, polemica` (implementation finding: §6 lists matched entries in word-list order, where `injustas` comes before `polémica`; the earlier example `polemica, injustas` contradicted that rule);
   - `justicia` passes even though `injusto` is in the list (whole words only, no substrings);
   - a multi-word entry such as `por desgracia` matches only as consecutive words.
   Any entry fails the whole run, like every other check.
9. **Selection leaves out bad notes before writing.** Given a pool where Statement 4's note fails `check_context_note`, then `select_statements` never picks it (status `context_invalid`). Duplicate detection runs only among the remaining Statements, so a later copy with a valid note can stay. `SELECTION_VERSION == "v2"`. The determinism test passes, and so does the Party-permutation test (permuting which Party owns which values changes the report only in Party ids).
10. **Anchor report.** After `_finish`, `statement_selection["anchors"] == {"dataset_version_id": D, "count": n, "in_pool": [...], "selected": [...], "missing": [...]}`: sorted anchor numbers, where `missing` = not in the pool. Each `pool` row carries `anchor` and `context_note`. `pipeline report --run N` prints `statement_anchors: dataset version D, n anchors, P in pool, S selected, missing k1, k2`, `statement_anchors: none` without a Published version, and `statement_anchors: not recorded` for older runs.
11. **Configuration.** `VALIDATION_CONTEXT_NOTE_MIN_CHARS`, `VALIDATION_CONTEXT_NOTE_MAX_CHARS` and `VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS` are read by `config.validation_settings()`. The following raise `ConfigError` before any write or LLM call: min < 1; max > 500; min > max; a decimal or a sign; a word entry with no letter or digit; a list that is empty after trimming. The run's `validation_settings` JSON records all three.
12. **Committed DB.** `data/ideology.db` is at the new head (`0014`), `ideology db check` prints `Safe to commit: yes`, and `tests/test_committed_database.py` passes.
13. **Methodology.** `/metodologia` shows the copy of Technical Approach §8. In a real browser at 375 px and desktop: no overflow, console clean. The Election 2 questionnaire (Dataset Version 5, null notes) still loads and answers with no console error, and no request carries Answers.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONTEXT.md`, `CONSTRAINTS.md` (LLM Providers, Pipeline, Validation, Public API, Public Copy, Shared Database), `ARCHITECTURE.md` (Pipeline, Validation), `docs/domain-model.md`, `docs/build-brief.md` (grep), `docs/technical-discovery.md:83-87` (`--reuse-from` runbook), `docs/risks-and-open-questions.md:63-81`, `PROGRESS.md` (head), `feature_list.json` (this entry and the three dependants).
- `src/ideology_app/pipeline/prompts.py`:
  - `_COMMON_RULES` is shared with `statement_candidates`. It still says "escala de 5 puntos";
  - `StatementDraft` is the item type of both `CandidateList` and `StatementSet`;
  - `GENERATE_STATEMENTS` v5 has `max_tokens` 16384.
- `pipeline/generation.py`: `reduce_request(candidates, settings)` and `generate_statements(...) -> StatementPool(statements, agenda)`.
- `pipeline/checkpoint.py`: `request_hash` covers system, prompt, schema JSON and `max_tokens`.
- `pipeline/runs.py`: `_start` writes `running` and the source documents and returns `_RunInput`; `_finish` writes the Dataset Version and `statement_selection`; `execute_run` builds the selection dict.
- `pipeline/selection.py`: `_validation_input`; the duplicates, then tiers, then greedy order; `_PROJECTED_CHECKS`.
- `pipeline/agenda.py`, `pipeline/publishing.py` (`get_published_dataset_version`), `pipeline/reports.py`.
- `src/ideology_app/validation/{__init__,base,statement_uniqueness,evidence_quotes}.py`. `normalize_for_match` drops whitespace, so word matching must tokenise first.
- `config.py` (`ValidationSettings`, `validation_settings()`), `models.py` (`Statement`, `PipelineRun`), `migrations/versions/0013_party_logo.py` (the `recreate='never'` pattern), `llm/fake.py`, `llm/anthropic_provider.py` (timeout 120 s).
- `api/schemas.py` (`StatementOut`), `api/queries.py:190`, `packages/core/src/domain/dataset-version.ts`, `packages/core/src/infrastructure/http/public-api-client.ts` (`parseStatements`, the `parseLogoUrl` missing-key precedent).
- `apps/web/src/features/methodology/MethodologyPage.tsx:68-162`.
- `tests/test_pipeline_prompts.py` (`FINGERPRINTS`, `REFERENCE_SCHEMAS`, `CANDIDATE_REQUEST_HASH`, the v5 system test), `tests/pipeline_fixtures.py` (response helpers), `tests/test_committed_database.py`.
- `data/ideology.db`, read-only: head `0013`; Dataset Version 5 is `published` for Election 2 (32 Statements, listed above); Dataset Version 3 is `published` for Election 1.
- Not inspected line by line: `positions.py`, `cli.py` beyond `pipeline statements` and `_selection_lines`, and the Vitest fixtures that build Statements (`apps/web/src/test/fetch-mocks.ts` and four `packages/core/test` files found by grep).

### Existing Patterns To Follow

- Pure, DB-free generation and selection. Only `runs.py` touches the database. No randomness, no clock, no iteration over unordered sets.
- A request schema is bounded by its builder (`statement_set_schema`). Every number the LLM may return is bounded to what the request lists (CONSTRAINTS, LLM Providers).
- A check is a pure function of `ValidationInput`, appended to `CHECKS`, with thresholds only from `ValidationSettings`. The selection reuses check functions on the pool.
- Nullable `ADD COLUMN` migrations with `batch_alter_table(..., recreate='never')` and a hand-written downgrade.
- Additive `/api/v1` fields. The client reads a missing key as `null` (`logo_url`).

### Current Gaps

- No column, schema field or check for a note. Generation has no input from earlier Dataset Versions. The run records nothing about anchors.

## Technical Approach

**1. Schemas (`prompts.py`).** Leave `StatementDraft`, `CandidateList` and `_COMMON_RULES` untouched, so the candidate request stays byte-identical. Add:

```python
CONTEXT_NOTE_SCHEMA_MAX = 500          # structural cap; equals config.CONTEXT_NOTE_MAX_CHARS_LIMIT
ContextNoteText = Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]
class PoolStatement(StatementDraft):    # generate_statements items only
    context_note: ContextNoteText       # required
    anchor: int | None                  # required, nullable; bounded by the builder
```

- `StatementSet.statements: list[PoolStatement]`.
- `statement_set_schema(min, max, anchor_count=0)` (cached) subclasses `PoolStatement` with `anchor: (int | None, Field(ge=1, le=anchor_count))`. When `anchor_count == 0` it uses `(None, ...)` instead, so only `null` validates.
- Make both fields required (nullable `anchor`, no default). Strict structured-output schemas then accept them.
- The configured length bounds are not in the schema. They are enforced by selection (§5) and Validation (§6), so a long note costs one Statement, not the reduce call.
- `REFERENCE_SCHEMAS["generate_statements"]` becomes `statement_set_schema(60, 80, 32)`.

**2. `GENERATE_STATEMENTS` v6** (`max_tokens` 32768: 80 items with notes need about twice v5's output).

The system text is v5 with these changes. Apply them exactly; tests assert each line.

- First paragraph, replace "Recibes afirmaciones candidatas extraídas, en igual número, de los programas electorales de varias candidaturas, y redactas" with "Recibes afirmaciones candidatas extraídas, en igual número, de los programas electorales de varias candidaturas, y las afirmaciones del cuestionario publicado anteriormente para estas elecciones, si lo hay; redactas".
- Replace the v5 "Cada afirmación se entiende por sí sola…" line with:
  - "- Cada afirmación se entiende por sí sola, sin conocer la legislación ni la política vigentes: di en qué consiste lo que se propone. Nunca hables de \"la política actual\", \"el modelo vigente\" o \"la ley actual\" sin decir cuál es ni qué establece."
- Then add these lines:
  - "- Expresa la medida por su contenido y en positivo, de modo que estar de acuerdo signifique querer esa medida: en lugar de pedir que se derogue o suprima una ley, una reforma o una institución, di lo que debe regir o hacerse (por ejemplo, «Debe poder limitarse el precio del alquiler en las zonas donde es más alto» y no «Debe derogarse la Ley de Vivienda de 2023, que permite limitar el precio del alquiler»). Usa derogar, suprimir o eliminar solo cuando la propuesta no tenga otro contenido que hacer desaparecer esa norma o institución, y entonces nómbrala."
  - "- Sin dobles negaciones: no combines «no», «nunca» o «sin» con verbos como prohibir, impedir, suprimir, eliminar o derogar."
  - "- Lenguaje llano: frases cortas y palabras de uso común. Si una afirmación necesita un término técnico o el nombre de una ley, un plan o un organismo, la nota de contexto lo explica."
  - "- Nunca dejes una regla abstracta sin decir qué supone en la práctica: «Por cada nueva regulación que afecte a las empresas deben derogarse dos normas existentes» no se entiende sin saber qué normas ni para qué; di el objetivo de la medida (por ejemplo, reducir el número de normas que deben cumplir las empresas)."
- In the variety line, "usa también reducir, limitar o suprimir cuando así lo planteen las candidatas" becomes "usa también reducir o limitar cuando así lo planteen las candidatas".
- In the basis line, "Basa cada afirmación solo en las candidatas: no añadas temas ni propuestas que no aparezcan en ellas." becomes "Basa cada afirmación solo en las candidatas y en las afirmaciones anteriores: no añadas temas ni propuestas que no aparezcan en ellas."
- Add to `Reglas para la lista`:
  - "- Los votantes ya conocen las afirmaciones anteriores. Para cada una, incluye en la lista una afirmación con la misma orientación, redactada de nuevo con estas reglas, y pon su número en `anchor`; si une dos políticas, divídela en dos afirmaciones con el mismo `anchor`. Las demás afirmaciones llevan `anchor` nulo."
- New block at the end:
  - "Reglas para la nota de contexto (`context_note`) de cada afirmación:"
  - "- Una o dos frases que explican de forma neutral lo que un votante podría no conocer para entender la afirmación: qué es la ley, la reforma, el plan, la institución, el organismo, la sigla o el término técnico que nombra (nombre oficial, año y qué establece o hace). Si no nombra ninguno, explica brevemente el concepto principal."
  - "- Si un nombre es un apodo del debate público, da el nombre oficial y di que se la conoce así."
  - "- Solo hechos descriptivos: sin valoraciones, sin argumentos a favor o en contra, sin efectos previstos, sin la posición de nadie y sin nombres de partidos, de políticos ni de gobiernos."
  - "- No repitas la afirmación ni añadas propuestas."

The template inserts, before the request line: "Afirmaciones del cuestionario publicado anteriormente (una por línea, con su número y su tema entre corchetes):\n\n{anchors}\n\n". It ends with: " Cada nota de contexto tiene entre {note_min} y {note_max} caracteres y no usa ninguna de estas palabras: {evaluative_words}."

**3. Generation (`generation.py`).**

- `Anchor(text, topic)` is a frozen dataclass.
- `reduce_request(candidates, settings=None, anchors=())` renders `{anchors}` as `[k] [topic] text` lines in the given order, or `(ninguna)`. It renders `{note_min}`, `{note_max}` and `{evaluative_words}` (joined by `", "` in settings order) from `settings` and uses `statement_set_schema(low, high, len(anchors))`.
- `generate_statements(provider, chunks, usage, settings=None, anchors=())` passes them through. `StatementPool.statements` becomes `tuple[PoolStatement, ...]`.
- Anchors never join the agenda, the candidates or the pool directly. They are prompt input only, so every pool Statement, notes included, is model output, and the agenda stays Party-balanced.

**4. Runs (`runs.py`).**

`_start` resolves the anchors in the same commit that marks the run `running`:

- if `resumed_from_run_id` names a run whose `anchor_dataset_version_id` is not null, use that version;
- otherwise use `publishing.get_published_dataset_version(session, election_id)`.

It records `run.anchor_dataset_version_id` (or null) and returns `anchors: tuple[Anchor, ...]` (that version's Statements in `position` order) in `_RunInput`.

`execute_run` passes `anchors` to `generate_statements`. It adds `"anchors": anchor_summary(...)` (a pure helper in `selection.py`, from the selection report's pool rows) to the `_finish` selection dict. `_finish` writes `context_note=draft.context_note` exactly as returned.

**5. Selection (`selection.py`, `SELECTION_VERSION = "v2"`).**

- `_validation_input` carries each pool Statement's `context_note`.
- New rule 0: pool numbers with a `check_context_note` entry on the pool are ineligible (`STATUS_CONTEXT_INVALID = "context_invalid"`).
- Rule 1 (duplicates) then runs on the eligible ones only. Rules 2–5 are unchanged and get no anchor preference: anchors are kept exactly when they win the same deterministic choice. The rule depends only on Statement text, so Party symmetry is unaffected.
- Pool rows gain `anchor` and `context_note`. `_PROJECTED_CHECKS` includes the new check automatically.
- Update the module docstring.

**6. Validation check `context_note`** (`validation/context_note.py`, `NAME = "context_note"`, appended last to `CHECKS`).

- `StatementRow` gains `context_note: str | None = None`, filled by `load_input`.
- Per Statement, in order:
  - NULL or `note.strip() == ""` → the "no context note" entry;
  - otherwise `len(note.strip())` outside `[min, max]` → the length entry;
  - evaluative words → one entry listing the matched list entries (folded form, list order).
- Matching: split the note with `re.findall(r"[^\W_]+", note)` and fold each token with `normalize_for_match`. Each list entry is split and folded the same way, and matches when its token sequence occurs consecutively.
- **Decision: a note is required on every Statement of a new Dataset Version.** Reasons:
  - a deterministic "names a law or institution" detector would miss most of the user's own examples, because they are lowercase common nouns (ley mordaza, cheque escolar, concierto educativo, ayuda oficial al desarrollo, reforma laboral);
  - letting the LLM flag which Statements need a note is circular, because the same output could omit both;
  - "always" includes "present when the Statement names a law or institution", needs no heuristic, and the collapsed disclosure planned in `questionnaire-length-and-context` costs nothing for simple Statements.
- **A failing note fails the whole run**, like every other check: the run is the unit of publication, and notes are never edited. Selection rule 0 leaves out failing pool Statements beforehand, so in practice one bad note costs one candidate (the same pattern as duplicates).

**7. Config, migration, API, core.**

- `config.py`:
  - `CONTEXT_NOTE_MAX_CHARS_LIMIT = 500`;
  - `DEFAULT_CONTEXT_NOTE_MIN_CHARS = 30`, `DEFAULT_CONTEXT_NOTE_MAX_CHARS = 300`;
  - `DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS`, a tuple, in this order: injusto, injusta, injustos, injustas, polémico, polémica, polémicos, polémicas, controvertido, controvertida, controvertidos, controvertidas, represivo, represiva, represivos, represivas, abusivo, abusiva, abusivos, abusivas, desastroso, desastrosa, desastrosos, desastrosas, nefasto, nefasta, nefastos, nefastas, excelente, excelentes, beneficioso, beneficiosa, beneficiosos, beneficiosas, perjudicial, perjudiciales, acertado, acertada, acertados, acertadas, erróneo, errónea, erróneos, erróneas, fracaso, fracasos, exitoso, exitosa, exitosos, exitosas, necesario, necesaria, necesarios, necesarias, imprescindible, imprescindibles, radical, radicales, extremista, extremistas, populista, populistas, sectario, sectaria, afortunadamente, lamentablemente, desgraciadamente, por desgracia, por suerte;
  - `ValidationSettings` gains `context_note_min_chars`, `context_note_max_chars` and `context_note_evaluative_words: tuple[str, ...]`, validated in `__post_init__` (ints, `1 <= min <= max <= 500`, non-empty tuple of strings that each contain a letter or digit);
  - `validation_settings()` reads the three env vars. The word list is comma-separated and replaces the default; unset or blank means the default.
- `RunReport.validation_settings` and `PipelineRun.validation_settings` type hints become `dict[str, Any]`. The CLI prints the word list as `N words`.
- Migration `0014_statement_context_note.py`, hand-written, `recreate='never'`:
  - `statements.context_note String(500) NULL`;
  - `pipeline_runs.anchor_dataset_version_id Integer NULL`, with no FK, like `resumed_from_run_id`;
  - downgrade drops both;
  - no data migration.
- `StatementOut.context_note: str | None` (description: "Neutral AI-generated context note; null for Dataset Versions created before it existed."). `queries.py` fills it.
- `packages/core`: `Statement.contextNote: string | null`. `parseStatements` reads a missing or `null` key as `null`, accepts a non-empty string, and throws `ContractError` otherwise.
- `cli pipeline statements` adds a `context_note` column (shown with `_one_line`).

**8. Methodology copy** (`MethodologyPage.tsx` and its test; required by CONSTRAINTS "Public Copy", because a Validation check is added and the prompt rules it describes change).

- "Cómo se redactan las afirmaciones", P2: replace "Debe entenderse por sí sola: si propone cambiar o derogar una ley o una política vigente, dice cuál es o en qué consiste." with "Debe entenderse por sí sola y en lenguaje llano: expresa la medida por su contenido y en positivo, de modo que estar de acuerdo signifique querer esa medida, sin dobles negaciones; solo habla de derogar o suprimir algo cuando la propuesta no tiene otro contenido."
- After P2, add two paragraphs:
  - "La inteligencia artificial recibe también las afirmaciones del cuestionario publicado anteriormente y las vuelve a redactar con estas reglas, para que los temas que ya conoces no desaparezcan por azar. Siguen en el cuestionario solo si superan el mismo procedimiento de elección que las demás."
  - "Cada afirmación lleva una breve nota de contexto, también redactada por la inteligencia artificial, que explica de forma neutral qué es la ley, el plan, la institución o el concepto que nombra. La nota no sale de los programas, y las comprobaciones automáticas no pueden confirmar que sea exacta; sus instrucciones le piden solo hechos descriptivos, sin valoraciones ni nombres de partidos."
- P3: "no añadir nada que no esté en las candidatas" becomes "no añadir nada que no esté en las candidatas ni en las afirmaciones anteriores".
- Selection P2: "Deja fuera las afirmaciones repetidas y las que no separan" becomes "Deja fuera las afirmaciones cuya nota de contexto no cumple las comprobaciones, las repetidas y las que no separan".
- Validation list, new last item: "cada afirmación tiene una nota de contexto de entre 30 y 300 caracteres que no usa ninguna palabra valorativa de una lista fija."

## Expected File Changes

- Create `src/ideology_app/validation/context_note.py`, `src/ideology_app/migrations/versions/0014_statement_context_note.py` and `tests/test_validation_context_note.py`.
- Modify `src/ideology_app/pipeline/{prompts,generation,runs,selection,reports,__init__}.py`, `validation/{__init__,base}.py`, `config.py`, `models.py`, `api/{schemas,queries}.py` and `cli.py`.
- Modify `packages/core/src/domain/dataset-version.ts` and `packages/core/src/infrastructure/http/public-api-client.ts`, plus the core tests and fixtures that build Statements (`apps/web/src/test/fetch-mocks.ts` and the core tests found by grep).
- Modify `apps/web/src/features/methodology/MethodologyPage.tsx` and `.test.tsx`.
- Modify tests as needed:
  - `tests/test_pipeline_{prompts,generation,runs,selection,checkpoint}.py`;
  - `tests/pipeline_fixtures.py` (the default reduce response gains `context_note` (≥ 30 characters, no listed word) and `anchor: null`);
  - `tests/test_validation_{questionnaire_shape,runs}.py` (registry tuple);
  - `tests/test_config.py`, `tests/test_migrations.py`, `tests/test_public_api.py`, `tests/test_cli_pipeline{,_report}.py`.
  - Do not delete a test without a replacement.
- Data: `data/ideology.db` upgraded to `0014` (`DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db upgrade`, then `db check`). Commit it only when nobody is generating.
- Not changed: `init.sh`, `agenda.py`, `positions.py`, the `statement_candidates`, `position_findings` and `party_positions` prompts.

## Visual Design Impact

- UI involved: copy only, on `/metodologia`. Source: `DESIGN.md`. Existing sections and classes; no new design artifact. The note itself gets no UI here.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - `prompts.py`: `PoolStatement`, `statement_set_schema(min, max, anchor_count)`, `generate_statements` v6 and its fields.
  - `generation.py`: anchors.
  - `runs.py`: anchor resolution in `_start`, `anchor_dataset_version_id`, `statement_selection["anchors"]`.
  - `selection.py` v2: rule 0.
  - Validation: check 7 `context_note`, the new `ValidationSettings` fields, `StatementRow.context_note`.
  - Public API and core: `context_note` / `contextNote`.
  - `REFERENCE_SCHEMAS`.
- `CONSTRAINTS.md`: update.
  - Pipeline: "Context notes MUST be stored exactly as the provider returned them and MUST NOT be written, backfilled or edited by application code or by hand; Dataset Versions created before `0014` keep NULL. Reason: AI output is never edited, and Dataset Versions are immutable."
  - Pipeline: "Anchors MUST come only from the Statements of the Election's Published Dataset Version (or, for a run with `resumed_from_run_id`, the anchor version that run recorded), resolved in `runs._start`, and MUST enter only as `generate_statements` prompt input, never as injected pool Statements or as a selection preference. Reason: every published Statement passes the same generation, selection and Validation, and replays stay reproducible."
  - Pipeline: "`StatementDraft`, `CandidateList` and `_COMMON_RULES` MUST NOT change without bumping `statement_candidates` (which voids every recorded candidate call). Reason: `--reuse-from` replays depend on it."
  - Validation: add `context_note` to the list of checks that fail the whole run.
- `CONTEXT.md`: add **Context Note** ("a short neutral explanation of the law, plan, institution or term a Statement names, generated by the AI with the Statement and checked by Validation; never hand-written; absent on Dataset Versions created before it existed"). Add **Anchor** under Statement Pool ("the Statements of the Election's Published Dataset Version, given to Statement generation to be rewritten; they stay only if their rewritten Statement passes Statement Selection").
- `docs/domain-model.md`: Statement gains the context note. Pipeline Run records its anchor Dataset Version. Add Validation check 7.
- `docs/technical-discovery.md:83`: add "the anchors of a `--reuse-from`/`--resume-from` run are those of run R".
- `README.md`: add the three env vars to the configuration table.
- `docs/risks-and-open-questions.md`, same change:
  - line 75: settled (note always required; checks: length, word list; the run fails, and selection drops bad notes first). Add an open risk: notes come from model knowledge, not the manifestos, and their factual accuracy is not verifiable (owner `e2e-2026-dataset-clarity`, team sanity read);
  - line 76: the anchor part is implemented as prompt input;
  - add the Open Questions below that the user leaves unsettled.
- `AGENTS.md`: not needed.

## Implementation Plan

1. Config fields and env parsing, then the `context_note` check and its tests (pure data).
2. Migration `0014` and the model columns. Test upgrade and downgrade with child rows. `alembic check` reports no drift.
3. Prompts: `PoolStatement`, the builder, v6 text. Re-pin the fingerprint, and check that the candidate and position pins pass unedited.
4. Generation and runs: anchors, the pinned anchor version, the stored note. Update the fixtures.
5. Selection v2: rule 0, pool row fields, `anchor_summary`. Report line and CLI columns.
6. API, core type and parser, and their tests.
7. Methodology copy and test, then the browser check.
8. Upgrade and check `data/ideology.db`. Update the docs. Run `CI=true ./init.sh`, then record evidence.

## Implementation Tasks

- [ ] `config.py`: constants, `ValidationSettings` fields and validation, env reading, docstrings.
- [ ] `validation/context_note.py`; `StatementRow.context_note`; `load_input`; append to `CHECKS`.
- [ ] `0014` migration; `Statement.context_note`; `PipelineRun.anchor_dataset_version_id`.
- [ ] `prompts.py`: `PoolStatement`, `statement_set_schema(..., anchor_count)`, v6 text exactly as in §2, `max_tokens` 32768.
- [ ] `generation.py`: `Anchor`, `reduce_request`/`generate_statements` with `anchors`.
- [ ] `runs.py`: resolve, record and pass anchors; write `context_note`; `statement_selection["anchors"]`.
- [ ] `selection.py` v2: rule 0, row fields, `anchor_summary`. `cli.py`: `statement_anchors` line, pool columns, `pipeline statements` note column, word list as a count.
- [ ] `api/schemas.py`, `api/queries.py`; core `Statement.contextNote` and its parser.
- [ ] Methodology copy and test.
- [ ] Tests for scenarios 1–12.
- [ ] Upgrade `data/ideology.db` and run `db check`. Docs listed above.

## Verification Plan

- `CI=true ./init.sh` exits 0. Report the pytest and Vitest counts against the previous ones (pytest 1897, Vitest 1016).
- `.venv/bin/python -m pytest tests/test_pipeline_prompts.py tests/test_pipeline_generation.py tests/test_pipeline_runs.py tests/test_pipeline_selection.py tests/test_validation_context_note.py tests/test_migrations.py tests/test_public_api.py tests/test_committed_database.py -q`.
- `git diff main -- tests/test_pipeline_prompts.py` shows the `CANDIDATE_REQUEST_HASH` line and the `statement_candidates`, `position_findings` and `party_positions` fingerprints untouched.
- `.venv/bin/alembic -c alembic.ini check` reports no drift. `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/ideology db check` prints `Safe to commit: yes` at head `0014`. `sqlite3 "file:data/ideology.db?mode=ro" "select count(*) from statements where context_note is not null"` returns 0.
- E2E: the repo has no Playwright suite. API-flow coverage comes from `tests/test_public_api.py` plus the core parser tests, which is enough for an additive field.
- **Browser (required, `/metodologia` copy).**
  - Use a scratch copy of `data/ideology.db` outside the repo (migrated) via a temporary launch entry on a free port. Never use the user's server or the committed file.
  - Open `/metodologia` at 375 px and desktop width: the new paragraphs and the validation item are there, nothing overflows, the console is clean.
  - Open the Election 2 questionnaire (Dataset Version 5): it loads and answers normally with null notes. No failed request, and no request carries Answers.
  - Afterwards remove the temporary entry and the scratch DB.

## Evidence To Capture

- Gate counts. Test names per scenario. The new `PROMPT_VERSIONS` and proof that the pins are unchanged. `db check` output and the head revision. The browser check (browser, widths, console and network, texts seen), recorded in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist

- [ ] Only `generate_statements` was bumped (v6). The candidate request hash and the position fingerprints are untouched. The v6 rule lines match §2.
- [ ] Anchors are prompt input only. They come from the Published version, or the one pinned on the resumed run, and are recorded on the run. Selection has no anchor preference and stays deterministic and Party-symmetric (both tests present).
- [ ] Notes are required, stored exactly as returned, NULL on old versions, never backfilled. The `context_note` check is last in `CHECKS`, pure, with its thresholds from `ValidationSettings`, and fails the whole run. Selection drops bad notes before writing.
- [ ] `/api/v1` and core changes are additive. A missing key reads as `null`.
- [ ] `data/ideology.db` is at `0014` and passes `db check`.
- [ ] The methodology copy matches §8 and the browser check is recorded.
- [ ] CONSTRAINTS, ARCHITECTURE, CONTEXT, domain-model, README, technical-discovery and risks are updated. No `docs/validations/`. No priority-tier or UI work.

## Open Questions (not settled by the docs; flagged, not decided by the user)

1. A note on every Statement (chosen here) or only on Statements that name a law, plan or institution. The user's wording was "present when …"; the conditional rule has no reliable detector (see §6).
2. The default evaluative word list (§7) and the 30–300 bounds are planner proposals for the team to review. Should the same list also apply to Statement text?
3. Party, politician or government names in notes are banned only by the prompt. A Validation check against the Election's Party names would flag common words (`Sumar`, `Podemos`), so it is not included.
4. Anchors get no selection preference (chosen here). If the user wants known topics kept more strongly, that belongs to `pipeline-statement-priority-tiers`'s ranking.
5. A `--reuse-from R` run inherits R's anchor version (chosen for replayability). There is no CLI switch to disable anchors or pick another version.
6. Accepted: `_COMMON_RULES` still says "escala de 5 puntos". Changing it would void every recorded candidate call.
7. Raising `max_tokens` to 32768 makes the `anthropic` adapter's 120 s timeout more likely to trip on the reduce. Real runs use `claude_code` (900 s), so this stays a risk to note.
