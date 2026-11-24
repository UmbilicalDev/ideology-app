# Feature Implementation Spec: Spanish topic catalog in citizen-priority order

## Source Feature

- `id`: topic-catalog
- `area`: core
- `depends_on`: none
- `status`: not_started at planning time (2026-11-24)
- `source`: `feature_list.json` (verification: every category key has a name and order, and a test fails on a missing one; the pipeline's topic tags map onto it; CIS source, question and date recorded in docs; `CI=true ./init.sh` passes)
- Branch: `feature/topic-catalog`, cut from `v2`, merged into `v2` by PR (never `main`).
- Settles the risks-doc entry "Open (`topic-catalog`): which CIS barometer question and date define the topic order, and where topics the CIS does not name go."

## Goal

Define one topic catalog that the pipeline (Python) and the web client (TypeScript) both use. Each of the 18 existing topic keys gets a Spanish display name and a 1-based display order. The order follows how often citizens name each issue as one of Spain's main problems in the latest CIS barometer. The catalog is the fixed list of main categories for Proposals and Statements and the topic order of the Comparador. This feature only defines the list. Its consumers (`proposal-extraction`, `statements-from-proposals`, `comparator-page`) are separate features.

## Non-Goals

- No new, renamed or removed topic key. Statements in Dataset Versions 1–5 stay valid (see "Keys").
- No change to `prompts.py` (`Topic`, `TOPICS`, `_TOPIC_LIST`, schemas), `agenda.py`, `selection.py`, Validation, the matching rule or the public API. No recorded LLM request fingerprint or prompt version changes.
- No UI. The Comparador and any topic heading belong to `comparator-page`. `/metodologia` copy about the CIS source belongs to `methodology-v2`.
- How Proposals carry one or more categories, and the extraction prompt that lists them: `proposal-extraction`.
- No secondary tags (they are free and are not topics, see `CONTEXT.md`).
- No automatic refresh from newer CIS barometers.

## Job Story

When I build Proposal extraction, Statement generation or the Comparador,
I want one fixed list of topic keys with Spanish names and a documented citizen-priority order,
so that all features use the same categories and Voters see the topics citizens care about most first.

## Users And Permissions

- Implementers of later features: they read the catalog from Python or from `@ideology-app/core`.
- Operator, Voter: no visible change in this feature.

## CIS Source (settled)

- CIS estudio nº 3587, "Barómetro de noviembre 2026". Published 23 Nov 2026. Fieldwork 10–17 Nov 2026. N = 8.034.
- Pregunta 6R: "¿Cuál es, a su juicio, el principal problema que existe actualmente en España? ¿Y el segundo? ¿Y el tercero?" (respuesta espontánea, multirrespuesta, recodificada). Use its **TOTAL** column, which is the sum of the three mentions, in % of respondents as printed (one decimal). Pregunta 7R (problems that affect the respondent personally) is not used. It is about the respondent's own situation, while the Comparador ranks national policy topics.
- Results PDF: https://www.cis.es/documents/d/guest/es3587mar_a-pdf. Advance page: https://www.cis.es/en/w/avance-de-resultados-del-estudio-3587-bar%C3%B3metro-de-noviembre-2026-
- "Otras respuestas", "Ninguno", "N.S." and "N.C." are not categories and are not recorded.

## Mapping (Pregunta 6R category → catalog key, TOTAL %)

Each of the 55 published categories goes to exactly one key, or is explicitly unmapped. The labels must be copied exactly as printed. A label that wraps over two lines in the PDF is joined with one space.

| Order | Key | Name (es) | CIS categories (TOTAL) | Rank value |
|---|---|---|---|---|
| 1 | housing | Vivienda | La vivienda 59,5 | 59,5 |
| 2 | economy | Economía | La crisis económica, los problemas de índole económica 24,7; Los problemas derivados del turismo. Masificación 0,3 | 24,7 |
| 3 | employment | Empleo | Los problemas relacionados con la calidad del empleo 23,9; El paro 9,1; Los problemas relacionados con los/as autónomos/as 0,5 | 23,9 |
| 4 | immigration | Inmigración | La inmigración 23,1 | 23,1 |
| 5 | democracy_institutions | Democracia e instituciones | Los problemas políticos en general 13,2; El Gobierno y partidos o políticos/as concretos/as 12,4; El mal comportamiento de los/as políticos/as 8,8; Los extremismos 8,0; La corrupción y el fraude 7,6; Lo que hacen los partidos políticos 3,7; Papel de los medios de comunicación y redes: desinformación, manipulación informativa, difusión de bulos 1,9; El funcionamiento de la democracia 1,3; La falta de confianza en los/las políticos/as y las instituciones 0,9; La falta de acuerdos, unidad y capacidad de colaboración. Situación e inestabilidad política 0,8; La Monarquía 0,2 | 13,2 |
| 6 | health | Sanidad | La sanidad 12,7; Preocupación sobre la salud propia, de familiares y/o allegados/as 0,3; Problemas psicológicos (preocupaciones, soledad, tristeza, desamparo, etc.) 0,2; Las drogas 0,2 | 12,7 |
| 7 | social_rights_equality | Derechos sociales e igualdad | Los problemas relacionados con la juventud. Falta de apoyo y oportunidades para los/as jóvenes 7,5; Las desigualdades, incluida la de género, diferencias de clases, la pobreza 4,6; Los problemas de índole social 2,7; El racismo 1,0; La violencia de género 0,7; Los problemas relacionados con la mujer 0,3 | 7,5 |
| 8 | education | Educación | La educación 6,5 | 6,5 |
| 9 | justice_security | Justicia y seguridad | La inseguridad ciudadana 5,5; La Administración de Justicia 1,1; La ocupación de viviendas 0,4 | 5,5 |
| 10 | environment_energy | Medio ambiente y energía | El cambio climático 3,6; Los problemas relacionados con el agua, la sequía 1,1; La subida de tarifas energéticas, crisis energética 0,9; El medio ambiente 0,7; Los incendios 0,1 | 3,6 |
| 11 | taxation | Impuestos | La subida de los impuestos 2,3 | 2,3 |
| 12 | pensions | Pensiones | Las pensiones 1,8 | 1,8 |
| 13 | foreign_policy_defense | Política exterior y defensa | Política exterior y relaciones internacionales. Papel de España en el marco internacional 1,1; Las guerras en general 0,9; Crisis con Marruecos. Fronteras de Ceuta y Melilla 0,5 | 1,1 |
| 14 | infrastructure_transport | Infraestructuras y transporte | Las infraestructuras 1,1 | 1,1 |
| 15 | science_digital | Ciencia y digitalización | El modelo productivo español. La falta de inversión en industrias e I+D 0,7 | 0,7 |
| 16 | territorial_model | Modelo territorial | Los nacionalismos 0,4; Los estatutos de autonomía 0,3; La independencia de Cataluña 0,2 | 0,4 |
| 17 | agriculture_rural | Agricultura y mundo rural | Los problemas de la agricultura, ganadería y pesca 0,4; La España vaciada, la despoblación 0,2 | 0,4 |
| 18 | culture_language | Cultura y lenguas | (none) | — |

Unmapped, because each is a general mood or cuts across many areas rather than being one policy area: La crisis de valores 4,9; Aumento de la crispación social, revueltas sociales 4,3; El funcionamiento de los servicios públicos 3,5; Las incertidumbres ante el futuro, la inseguridad y el miedo al futuro 0,7; Poca conciencia ciudadana (falta de civismo, de sentido espíritu cívico) 0,4; La falta de servicios públicos. Los recortes 0,3. (Mapped 49 + unmapped 6 = 55.)

**Order rule.** A topic's rank value is the **highest** TOTAL among its mapped categories, not their sum, so that a topic with many small categories does not climb. Topics are sorted by rank value, highest first. Ties (13/14 at 1,1; 16/17 at 0,4) are broken by the current `TOPICS` order. Topics with no mapped category come after all ranked topics, also in `TOPICS` order. Values are compared in integer tenths of a percent (59,5 → 595), so no floats are involved.

**Keys.** All 18 keys stay unchanged. Every category in the top 12 by TOTAL has a home: the youth category (rank 12, 7,5) goes to `social_rights_equality`, and the political-class categories go to `democracy_institutions`. The highest unmapped category (crisis de valores, 4,9) ranks 15th. So no key is added, and the Statements of Dataset Versions 1–5 need nothing (the shared DB uses only these 18 keys; checked 2026-11-24).

## Acceptance Scenarios

### Scenario 1: catalog is complete and ordered
Given `ideology_app.topic_catalog.TOPIC_CATALOG`
When the tests run
Then it has exactly the 18 keys of `prompts.TOPICS`, each with a non-empty unique Spanish name and an `order` that is exactly 1..18. The sequence matches the table above.

### Scenario 2: a missing name or order fails
Given a copy of the catalog with one empty name, a missing or duplicate order, or a key added to or missing from `TOPICS`
When `catalog_problems(entries, TOPICS)` runs
Then it returns a problem naming that key, and the test that asserts `catalog_problems(TOPIC_CATALOG, TOPICS) == []` would fail.

### Scenario 3: order follows the rule
Given the recorded `CIS_6R_TOTALS` and each entry's `cis_categories`
When the order is computed with the rule above
Then it equals the declared order. Every recorded category is either mapped exactly once or listed in `CIS_6R_UNMAPPED`, never both, and no entry names a category that is not recorded.

### Scenario 4: web client gets the same catalog
Given the committed `packages/core/src/domain/topic-catalog.generated.ts`
When pytest renders the TypeScript from the Python catalog
Then the output is byte-identical to the committed file. `@ideology-app/core` exports `TOPIC_CATALOG`, `TopicKey` and `findTopic(key)` (`undefined` for an unknown key), and `findTopic("housing")?.name === "Vivienda"`.

### Scenario 5: legacy pipeline untouched
Given this change
When the existing prompt-fingerprint, agenda and selection tests run
Then they pass unchanged. Every Statement topic in the committed `data/ideology.db` is a catalog key.

## Repository Research

### Files Inspected

- `src/ideology_app/pipeline/prompts.py:20-42,172`: `Topic` Literal (18 keys), `TOPICS = get_args(Topic)`, and `_TOPIC_LIST` embedded in the generation prompt. The enum order is in the JSON schema and in the prompt text, so reordering it would change prompt fingerprints and request hashes.
- `src/ideology_app/pipeline/agenda.py:25,59-62`: `_TOPIC_INDEX` from `TOPICS` is the last tie-break of a Party's topic order. Reordering `TOPICS` would change the Agenda and therefore the reduce request.
- `src/ideology_app/models.py:385-386`: `Statement.topic` is a free `String(50)` ("the topic list is versioned with the prompts"). `api/queries.py:200` serves it as is.
- `packages/core/src/domain/dataset-version.ts:11` (`topic: string`), `infrastructure/http/public-api-client.ts:167`: the web client parses the topic but never shows it. `apps/web/src` has no topic display (only `/metodologia` prose uses "tema"). `apps/web/src/test/fetch-mocks.ts:57` uses a non-key `"economía"`, which shows that unknown keys must be tolerated.
- `tests/test_pipeline_prompts.py:216-225` pins `TOPICS` length and order. `tests/test_committed_database.py` shows the read-only pattern for opening `data/ideology.db`.
- `Dockerfile`: the server image installs only `src/` (no package data), and the web stage copies `packages/core`. Runtime JSON in `src/` or reading `packages/` from Python would need packaging changes.
- `init.sh` (pytest, web typecheck, `vitest run` over `packages/core` and `apps/web`, web build). `package.json`, `vitest.config.ts`, `packages/core/src/index.ts`.
- `CONTEXT.md` ("Topic / tema / categoría", Proposal, Statement), `docs/domain-model.md`, `docs/risks-and-open-questions.md` "Constituency redesign", `docs/technical-discovery.md` "Data and Storage", `ARCHITECTURE.md:49-52`.
- Shared DB query (read-only): Dataset Versions 1–5 use only the 18 keys.

### Existing Patterns To Follow

- Pure Python modules with frozen dataclasses and tuples (no unordered iteration), as in `agenda.py`.
- Core exports go through `packages/core/src/index.ts`. Core tests go in `packages/core/test/domain/`.

## Technical Approach

**Source of truth: Python module, with a generated TypeScript file checked by a drift test.** `src/ideology_app/topic_catalog.py` holds the catalog. A deterministic renderer writes `packages/core/src/domain/topic-catalog.generated.ts`, and a pytest test fails when the committed file differs from the renderer's output. Rejected alternatives:
- Public API endpoint: it adds a runtime request and a cache for static data, and the web tests and `dev-dataset` would need the server or mocks. It also mixes a code constant into the immutable Dataset Version contract.
- Shared JSON file: Python would have to read a file under `packages/` (absent from the server image) or ship package data (a Dockerfile and pyproject change), and TypeScript would lose the literal `TopicKey` type.

`topic_catalog.py` must not import from `pipeline` (future Proposal code will import it). Contents:
- `CisSource` frozen dataclass and `CIS_SOURCE` (study `"3587"`, title, `published="2026-11-23"`, fieldwork `"2026-11-10".."2026-11-17"`, `sample=8034`, `question="6R"`, the question text, both URLs).
- `CIS_6R_TOTALS: tuple[tuple[str, int], ...]`: all 55 categories with TOTAL in tenths, in the published order. `CIS_6R_UNMAPPED: tuple[str, ...]`.
- `TopicEntry(key: str, name: str, order: int, cis_categories: tuple[str, ...])` and `TOPIC_CATALOG: tuple[TopicEntry, ...]` in display order, exactly as in the table.
- `rank_order(entries, totals, legacy_order) -> tuple[str, ...]`: applies the order rule. `legacy_order` is passed in, and the tests pass `prompts.TOPICS`.
- `catalog_problems(entries, legacy_keys) -> list[str]`: reports an empty or whitespace name, a duplicate name, an order set other than 1..N, a duplicate key, and keys missing from or extra to `legacy_keys`.
- `render_typescript() -> str` and `if __name__ == "__main__": sys.stdout.write(render_typescript())`. Regenerate with `.venv/bin/python -m ideology_app.topic_catalog > packages/core/src/domain/topic-catalog.generated.ts`.

Generated TS (header comment names the generator and says "do not edit"; only key, name, order):
```ts
export const TOPIC_CATALOG = [
  { key: "housing", name: "Vivienda", order: 1 },
  /* … 18 entries in order … */
] as const;
export type TopicKey = (typeof TOPIC_CATALOG)[number]["key"];
```
The hand-written `packages/core/src/domain/topics.ts` re-exports these and adds `findTopic(key: string)`, which returns the entry or `undefined`. `Statement.topic` stays `string`, because old or dev data may hold anything. The Comparador decides how to show an unknown key.

The pipeline's `Topic`/`TOPICS` keep their legacy order (the prompt order). Display order exists only in the catalog. `agenda.py` behaviour, prompt versions, schemas and request fingerprints do not change.

## Expected File Changes

- `src/ideology_app/topic_catalog.py`: create.
- `tests/test_topic_catalog.py`: create. Tests: completeness against `TOPICS`; `catalog_problems` on the real catalog (empty) and on broken copies (missing name, duplicate or missing order, extra or missing key); mapping coverage (55 = mapped + unmapped, disjoint, no unknown label); `rank_order` equals the declared order and the table's sequence; the TS drift test (reads the repo file by absolute path from `__file__`); every topic in the committed DB is a catalog key (read-only, pattern of `test_committed_database.py`).
- `packages/core/src/domain/topic-catalog.generated.ts`: create (generated).
- `packages/core/src/domain/topics.ts`, `packages/core/src/index.ts`: create and modify (exports).
- `packages/core/test/domain/topics.test.ts`: create (18 entries, orders 1..18 ascending, non-empty names, `findTopic` hit and miss).
- Docs listed below. No change to `prompts.py`, `agenda.py`, `models.py`, the API or `apps/web`.

## Visual Design Impact

- UI involved: no. Nothing is rendered yet, so browser validation does not apply. `comparator-page` does the browser check when it shows names and order.

## Durable Documentation Impact

- `docs/technical-discovery.md`: update. Add a "Topic catalog" bullet under "Data and Storage" with the CIS study, question 6R, TOTAL column, dates, N, URLs, the order rule, where the catalog lives and the regenerate command.
- `CONTEXT.md`: update "Topic / tema / categoría". Say there are 18 keys with Spanish names, in citizen-priority order (CIS 3587, Pregunta 6R, Nov 2026; details in technical-discovery), that the keys are stable, and that legacy Statements use the same keys.
- `docs/risks-and-open-questions.md`: replace the "Open (`topic-catalog`)" line with a "Settled (`topic-catalog`)" line (question, date, rule, unmapped categories, no key added). Add "Open, for team review" items from the section below. Add a handoff: "`methodology-v2` explains the topic order and its CIS source".
- `ARCHITECTURE.md`: update. Add `ideology_app.topic_catalog` (pure, imports nothing from `pipeline`), the generated core file and `findTopic`. Add a note that the `prompts.Topic` order is the legacy prompt order, not the display order.
- `CONSTRAINTS.md`: update (Pipeline). Add: the topic catalog MUST be edited only in `topic_catalog.py` and the TS file regenerated, never hand-edited; topic keys MUST NOT be renamed or removed while any Dataset Version uses them; `prompts.Topic` MUST NOT be reordered for display.
- `AGENTS.md`, `DESIGN.md`, `docs/domain-model.md`, `docs/build-brief.md`: not needed (no workflow, UI or domain-rule change; the domain model already points to `topic-catalog`).

## Implementation Plan

1. Write `topic_catalog.py` (data copied from the tables above, then the functions).
2. Write `tests/test_topic_catalog.py`, then generate the TS file with the module command.
3. Add `topics.ts`, the index exports and the core test.
4. Update the docs, then run `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `CIS_SOURCE`, `CIS_6R_TOTALS` (55 rows, tenths), `CIS_6R_UNMAPPED` (6), `TOPIC_CATALOG` (18) exactly as specified.
- [ ] `rank_order`, `catalog_problems`, `render_typescript`, `__main__`.
- [ ] Python tests, including negative `catalog_problems` cases and the TS drift test.
- [ ] Generated TS file, `topics.ts` with `findTopic`, `index.ts` exports, core test.
- [ ] Docs: technical-discovery, CONTEXT, risks, ARCHITECTURE, CONSTRAINTS.
- [ ] `git diff --stat` shows no change under `src/ideology_app/pipeline/`, `apps/web/` or `data/`.

## Verification Plan

- `.venv/bin/python -m pytest tests/test_topic_catalog.py tests/test_pipeline_prompts.py tests/test_pipeline_agenda.py tests/test_pipeline_selection.py`: all pass, fingerprint pins untouched.
- `npx vitest run packages/core/test/domain/topics.test.ts` and `npm run typecheck`.
- Drift check by hand: change one name in the Python catalog and confirm the drift test fails. Blank one name and confirm the `catalog_problems` test fails. Revert both.
- `CI=true ./init.sh` passes. No E2E: there is no browser- or API-visible change.

## Evidence To Capture

- Test names and counts from pytest and vitest, the `CI=true ./init.sh` result, the two manual failure checks, and confirmation that `pipeline/` is unchanged. Record them in `feature_list.json` and `PROGRESS.md`.

## For Team Review (defaults chosen, not blocking)

1. Political-class complaints ("El Gobierno y partidos…", "mal comportamiento…", "Lo que hacen los partidos") are mapped to `democracy_institutions`. They do not move its rank, which comes from "Los problemas políticos en general" (13,2). Leaving all political categories unmapped would leave it with no category, so it would drop from 5th to 17th, just before `culture_language`.
2. The youth category goes to `social_rights_equality` (which puts it 7th, ahead of education). Mapping it to `employment` would give `social_rights_equality` 4,6, so it would drop to 9th, behind education and `justice_security`.
3. "La ocupación de viviendas" goes to `justice_security`, not `housing` (no effect on the order).
4. The catalog is pinned to estudio 3587. A newer barometer is adopted only by a deliberate change (a new spec or user decision). Keys stay stable; only names and order may change.
5. Display names are short headings for the Comparador; `comparator-page` may ask for different wording.

## Validator Checklist

- [ ] The table, the unmapped list and the CIS figures match the code exactly, and the order equals the rule's output.
- [ ] `catalog_problems` negative cases exist, and the drift test compares against the committed TS file.
- [ ] No change to `prompts.py`, `agenda.py`, fingerprints, the API or `apps/web`. The matching rule is untouched.
- [ ] CIS source, question and date are in `docs/technical-discovery.md` and `CONTEXT.md`. The risks entry is settled.
- [ ] `CI=true ./init.sh` passes, and evidence is in `feature_list.json` and `PROGRESS.md`.
