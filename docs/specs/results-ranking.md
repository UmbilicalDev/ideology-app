# Feature Implementation Spec: Results page shows the party ranking

## Source Feature

- `id`: results-ranking (GitHub issue #43)
- `area`: web
- `depends_on`: questionnaire-important-flag, match-score-engine (both `accepted`). Also builds on `public-dataset-api`, `questionnaire-answer-flow` and `methodology-page` (all `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: browser test with fixture data where the order and percentages match the engine; skipping every Statement shows a prompt instead of a ranking; Vitest: the results page links to `METHODOLOGY_PATH`. Notes: no party colours on the bars; link to `/metodologia`; match the "baja cobertura" wording or update `MethodologyPage`.)

## Goal

When the Voter passes the last Statement, the Questionnaire's end screen becomes the results: every Party of the Dataset Version, ordered by Match Score, each with its percentage, a neutral bar, its number of shared Statements and a `Baja cobertura` badge when it applies. Scores come only from `packages/core` (`toMatchScoreAnswers` → `computeMatchScores`) and the Party Positions already loaded. The Answers never leave the component's memory. The Voter can go back into the Questionnaire with every Answer and Important flag kept, and open the methodology page without losing them.

## Decisions

- **Where results live: inside the Questionnaire flow, no new route.** The end screen (`isAtEnd(state)`) of `QuestionnaireFlow` renders the results. The URL stays `/elecciones/:electionId/cuestionario`.
  - Why not a `/resultados` route with React Router `state`: `navigate(path, { state })` writes to `window.history.state`, which browsers keep across reloads and session restore. That is browser storage in all but name (CONSTRAINTS.md "Client-side Matching"). A route backed by a context above `<Routes>` would need a provider, a second data load and a "no Answers" path, all for the same result.
  - Consequence: there is no results URL, so no reload or deep link can reach results without Answers. A reload shows Statement 1 with nothing answered, as today. The only "no Answers" state is the all-skipped prompt (below).
  - **Seam for `share-link-create` / `share-link-open`.** The ranking UI is a separate component, `features/results/ResultsRanking.tsx`, that takes plain data (`ranking: readonly RankedParty[]`), and the ordering is a pure core function, `rankParties(answers, parties)`. A later route (e.g. `/elecciones/:id/resultados#…`) can decode Answers from the fragment and render the same component. A share button can be added to the end screen next to the ranking. Neither is built here, and nothing goes into the URL.
- **Scores and ordering (core, `packages/core/src/domain/ranking.ts`).** `rankParties(answers: readonly Answer[], parties: readonly Party[]): RankedParty[]`:
  - calls `computeMatchScores(answers, parties.map(p => ({ partyId: p.id, positions: p.positions })))` once. It does not re-implement agreement, weights, skip, `no_stance` or the threshold, and passes no options, so the threshold is `LOW_COVERAGE_THRESHOLD`.
  - `RankedParty = { partyId, name, shortName, matchScore: number | null, percent: number | null, sharedStatementCount, lowCoverage }`, with `percent = matchScore === null ? null : Math.round(matchScore * 100)` and the other fields copied from the engine.
  - Order: `percent` descending; `null` scores last; equal `percent` (a tie) by `name` with `new Intl.Collator("es")` (one module-level instance: accents, case and `ñ` sorted the Spanish way); then by `partyId` ascending, so the order is fully deterministic. Returns a new array and leaves its inputs unchanged.
  - Why ties are judged on the displayed percentage and not on the raw score: the Voter sees integers. Two Parties both shown as `81 %` would otherwise be ordered by a difference the Voter cannot see, which a reader of "en caso de empate, alfabéticamente" (MethodologyPage) would take as a broken rule. The rule is checkable from the screen. `Intl` is an ECMAScript built-in, so this is allowed in core; the "no imports" rule applies only to `match-score.ts`.
- **Minimum before a ranking (settles the open question).** The ranking is shown when at least one Party has a non-null score, i.e. the Voter rated at least one Statement (not skip) on which some Party has a stance. Otherwise the end screen shows the prompt instead of a list. No higher minimum: a low-confidence score is already flagged per Party by the badge, and hiding the ranking would hide data. Validation's separation check guarantees that every published Statement has stances from at least two Parties, so with published data "all null" happens exactly when every Statement was skipped.
- **Low coverage.** The badge text is `Baja cobertura`, the same wording as MethodologyPage ("se marca como de baja cobertura"). The threshold is the engine's `LOW_COVERAGE_THRESHOLD` (5), the same as the methodology copy. When any row has the badge, a legend under the list reads `Baja cobertura: compartes menos de {LOW_COVERAGE_THRESHOLD} afirmaciones con ese partido, así que su afinidad se basa en pocos datos.` (built from the constant, not a literal 5). MethodologyPage needs no change. If the implementer finds a mismatch anyway, fix `MethodologyPage.tsx` and its test in the same change (CONSTRAINTS.md "Public Copy").
- **Ranking row (DESIGN.md "Ranking row").** The API has no logos, and DESIGN.md leaves logos open. So: no logo, no initials avatar and no colour per Party. Every row has the same markup and style. No row is highlighted, and the first row gets no "winner" styling, number or medal.
  - Markup: `<ol className="ranking" role="list" aria-labelledby="results-title">`, then one `<li className="ranking-row">` per Party containing:
    - head line: `<span className="ranking-row__name">{name}</span> <span className="ranking-row__short">{shortName}</span>`, with the percentage `<span className="ranking-row__percent">{percent} %</span>` on the right;
    - bar: `<div className="ranking-bar" aria-hidden="true"><div className="ranking-bar__fill" style={{ width: `${percent}%` }} /></div>`, with `--color-primary` fill on a `--color-border` track for every Party;
    - meta line: `{n} afirmaciones en común` (`1 afirmación en común`), plus `<span className="coverage-badge">Baja cobertura</span>` when `lowCoverage`.
  - A `null` score shows `Sin afirmaciones en común` in place of the percentage, an empty track, and the badge (the engine marks it low coverage).
  - Accessibility: the meaning is in text (percentage, count, badge words), never in colour or bar length alone. The bar is decorative (`aria-hidden`), so a screen reader reads e.g. "Partido Alfa PA 81 % 7 afirmaciones en común".
- **End screen content, in order:**
  1. `<h2 id="results-title" tabIndex={-1}>Tus resultados</h2>`, which gets focus on arrival through the existing `headingRef` mechanism.
  2. The existing answered/skipped and Important sentences, unchanged. `Los resultados estarán disponibles muy pronto.` is removed.
  3. Either the ranking or the prompt:
     - Ranking: intro `Afinidad entre tus respuestas y el programa de cada partido, de mayor a menor.`, then the list and the legend.
     - Prompt (`role="status"` not needed; plain text): `Todavía no se puede calcular tu afinidad: no has respondido ninguna afirmación en la que los partidos tengan posición. Responde al menos una para ver los resultados.` No list and no legend.
  4. Controls: `Revisar mis respuestas` (`button-primary`; goes to Statement 1) and `Volver a la última afirmación` (`button-secondary`, as today).
  5. Disclaimer: `Esto no es una recomendación de voto: solo compara tus respuestas con lo que dicen los programas, según una inteligencia artificial que puede equivocarse.` Then the methodology link (see Navigation).
  6. Privacy note (`.questionnaire__note`): `Tus respuestas siguen solo en este navegador: si recargas la página, vuelves atrás con el navegador o sales de aquí, se pierden.`
  7. `Volver al inicio`, as today.
- **Navigation.**
  - `Revisar mis respuestas` dispatches a new core action, `{ type: "first" }`: `currentIndex = 0`, Answers and flags kept, a no-op when already at 0 (focus moves to the Statement `h2` through `move`). It is allowed from any index. The invariant "every Statement before `currentIndex` has an Answer" holds trivially. `Volver a la última afirmación` keeps using `back`.
  - After changes the Voter walks forward again with `Siguiente`/`Saltar`. The ranking is recomputed from state on every render (`useMemo` on `state`); nothing is cached.
  - The methodology link is `<Link className="text-link" to={METHODOLOGY_PATH} target="_blank" rel="noopener">Cómo se calcula la afinidad (se abre en una pestaña nueva)</Link>`. It opens in a new tab because an in-app navigation unmounts the flow and loses the Answers. The new tab gets a plain `/metodologia` URL with no query or fragment.
- **Memory-only loss (risks entry).** This feature keeps Answers memory-only and does not add a `beforeunload` or navigation-block warning. `BrowserRouter` (declarative mode) has no `useBlocker`, and `beforeunload` does not cover in-app Back. The loss is mitigated by copy (point 6) and by the new-tab methodology link. A real fix (a reopenable Share Link) belongs to `share-link-create`, and the risks entry is reworded to say so.

## Non-Goals

- Per-Statement breakdown and Evidence (`results-breakdown-evidence`). Share button, fragment encoding or a results route (`share-link-create`, `share-link-open`).
- Any change to `match-score.ts`, the matching rule, `LOW_COVERAGE_THRESHOLD`, the API, Python, migrations, `init.sh`, npm dependencies or design tokens.
- Party logos or colours, a "recommended party", charts beyond the bar, persisting Answers, leave warnings, randomised order.

## Job Story

When I have rated the Statements,
I want to see right away which Parties' manifestos are closest to my answers, and how much data each score rests on,
so I can judge the result and go back to change answers without starting over.

## Users And Permissions

- Voter (anonymous): sees results computed in the browser. No new request: only the two GETs of `questionnaire-answer-flow`, made before any Answer. The methodology tab loads `/metodologia` and its assets only.

## Acceptance Scenarios

Vitest fixture: `datasetVersionJson({ statements: 6 })` (Partido Uno +1 everywhere; Partido Dos −1 with `no_stance` on Statement 1).

### Scenario 1: ranking ordered by score
Given the Voter rates Statements 1–5 `De acuerdo` and skips 6
When the end screen shows
Then `Tus resultados` has focus, the list is `Partido Uno 100 %` (5 afirmaciones en común, no badge) then `Partido Dos 50 %` (4 afirmaciones en común, `Baja cobertura`), the legend shows, and the percentages equal `Math.round(computeMatchScores(...)*100)`.

### Scenario 2: tie → alphabetical
Given the Voter rates every Statement `Ni de acuerdo ni en desacuerdo`
Then both Parties show `75 %` and `Partido Dos` comes before `Partido Uno` (by name, not by id or API order).

### Scenario 3: Important weighs double
Given Scenario 1's Answers plus Statement 6 rated `Muy en desacuerdo` and marked Important
Then the scores reflect weight 2 (Uno: 5.5/7 → `79 %`; Dos: 3.5/6 → `58 %`).

### Scenario 4: everything skipped
Given the Voter skips every Statement
Then the prompt shows, with no list, no percentage and no legend. `Revisar mis respuestas` shows Statement 1 with `Has saltado esta afirmación.`. Rating it and moving to the end shows a ranking.

### Scenario 5: back keeps Answers
Given the results are shown
When the Voter activates `Volver a la última afirmación`, or `Revisar mis respuestas`
Then the last Statement, or Statement 1, shows its Answer checked and its Important flag pressed. Walking forward unchanged gives the same ranking.

### Scenario 6: methodology link
Then a link with href `METHODOLOGY_PATH`, `target="_blank"` and `rel` containing `noopener` is on the results and on the prompt. Opening it in the browser leaves the results tab unchanged.

### Scenario 7: Answers never leave the browser
Then there is no request after the Dataset Version load, the URL has no `?` or `#`, and localStorage, sessionStorage and cookies are empty. A reload shows Statement 1 with nothing answered.

## Repository Research

### Files Inspected
- `packages/core/src/domain/{match-score,questionnaire,dataset-version}.ts`, `packages/core/src/index.ts`, `packages/core/tsconfig.json` (`lib: ES2022`, `Intl.Collator` typed).
- `apps/web/src/app/App.tsx`, `apps/web/src/main.tsx` (declarative `BrowserRouter`), `apps/web/src/features/paths.ts`, `features/questionnaire/{QuestionnairePage,QuestionnaireFlow,useQuestionnaireData}.tsx|ts`, `QuestionnairePage.test.tsx` (helpers `routes`, `happyFetch`, `renderAt`; asserts the "muy pronto" line at l.146), `features/methodology/MethodologyPage.tsx`, `src/test/fetch-mocks.ts`, `ui/{tokens,components}.css`.
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md`, `docs/build-brief.md`, `docs/risks-and-open-questions.md`, `docs/specs/questionnaire-important-flag.md`, `docs/specs/landing-election-picker.md` (scratch script), `tests/pipeline_fixtures.py`, `feature_list.json`, `.agents/skills/github-flow/references/practical-notes.md`.
- Checked locally: Node 24 `Intl.Collator("es")` sorts `Álava, Bilbao, bloque, Nuevo, Ñandú, Otro`; `Math.round(0.125*100) === 13`.

### Existing Patterns To Follow
- Pure core plus a thin React render. Web tests render `App` in `MemoryRouter` with a mocked `FetchLike` and query by role. Focus follows moves via `headingRef` and `focusPending`. Spanish copy with ` %`.

### Current Gaps
- No ranking function, no `first` action, no results UI. `datasetVersionJson` cannot vary Party names or values (tests that need it build the body inline or get an optional `parties` override).

## Expected File Changes
- `packages/core/src/domain/ranking.ts`: create (`rankParties`, `RankedParty`).
- `packages/core/src/domain/questionnaire.ts`: modify (`first` action).
- `packages/core/src/index.ts`: modify (exports).
- `packages/core/test/domain/ranking.test.ts`: create. `packages/core/test/domain/questionnaire.test.ts`: modify.
- `apps/web/src/features/results/ResultsRanking.tsx`: create (list, rows, legend; props `ranking`).
- `apps/web/src/features/results/ResultsRanking.test.tsx`: create (component-level: null row, singular count, no colour or style per Party, badge and legend, names with accents).
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: modify (end screen per Decisions).
- `apps/web/src/features/questionnaire/QuestionnairePage.test.tsx`: modify (Scenarios 1–7; drop the "muy pronto" assertion).
- `apps/web/src/test/fetch-mocks.ts`: modify only if an optional `parties` override is added (default output unchanged).
- `apps/web/src/ui/components.css`: modify (`.ranking`, `.ranking-row*`, `.ranking-bar*`, `.coverage-badge`).
- Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `DESIGN.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Source: `DESIGN.md` (Ranking row, no party colours, 720px column, 48px targets, AA contrast). No new token or design artifact.
- `.ranking`: no list style, grid with an 8px gap. `.ranking-row`: card style (surface, 1px border, 12px radius, 16px padding). Name 600 weight; short name and meta in `--color-secondary`; percentage 600 weight with tabular numerals. Bar 8px high with 4px radius.
- `.coverage-badge`: inline, 1px `--color-secondary` border, 6px radius, `--color-text` on surface, 14px. Not amber (reserved), not red or green.
- States: ranking, ranking with badges and legend, null row, prompt. At 375px the head line wraps (name above the percentage) with no horizontal scroll.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update. Core gets `ranking.ts` (`rankParties`: engine call, percent, tie rule, es collator) and the `first` action. Web Client: the end screen is the results, `features/results/ResultsRanking.tsx`, the methodology link opens in a new tab, no results route.
- `CONSTRAINTS.md`: update "Client-side Matching" with: results order and percentages MUST come from `rankParties`, and the UI MUST NOT re-sort them or treat a Party differently (no per-Party colour, highlight or logo placeholder). Reason: one auditable ordering rule, and identical treatment of Parties.
- `DESIGN.md`: update the "Ranking row" component to read "party name + short name (logos pending the open question), percentage bar, a 'Baja cobertura' badge", and note that the first row is not emphasised.
- `docs/risks-and-open-questions.md`:
  - replace the "Owed by `results-ranking`" entry with a Settled line (methodology link in a new tab, `Baja cobertura` badge, ties on the displayed percentage by `es` name collation);
  - replace "The minimum number of answered Statements…" with Settled: one rated Statement shared with some Party, otherwise the prompt;
  - reword the memory-only entry: results stay memory-only with a loss note and the new-tab methodology link; reload/Back/leave loss stays open, owned by `share-link-create`.
- `MethodologyPage.tsx`, `AGENTS.md`, `CONTEXT.md`: not needed (wording, threshold and tie rule already match; no workflow or term change).

## Implementation Plan
1. Core: `rankParties` and tests; `first` action and tests; exports.
2. Web: `ResultsRanking` with its tests; end screen in `QuestionnaireFlow`; CSS; page tests.
3. `CI=true ./init.sh`, greps, browser walk-through, then docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks
- [ ] `ranking.test.ts`:
  - order by percent;
  - ties by name: `Álava` < `Bilbao` < `bloque` < `Nuevo` < `Ñandú`, whatever the input order or ids;
  - equal names → id;
  - different raw scores with the same rounded percent → alphabetical;
  - nulls last, alphabetical;
  - `percent` = `Math.round` of the engine score (12.5 → 13);
  - `sharedStatementCount`/`lowCoverage` equal the engine's, with the threshold boundary at 4/5;
  - inputs not mutated;
  - with `toMatchScoreAnswers`, a flagged rated Statement weighs 2.
- [ ] `questionnaire.test.ts`: `first` goes from the end and from the middle to 0, keeps the Map contents and the Set; no-op at 0; works with zero Statements.
- [ ] `QuestionnairePage.test.tsx`: Scenarios 1–7 by role (list items' text, `aria-hidden` bars, focus on `Tus resultados`, link attributes, two fetch calls only).
- [ ] CSS and docs as above.

## Verification Plan
- `CI=true ./init.sh` exits 0: pytest unchanged, Vitest = current count + new tests, typecheck and build ok.
- Greps:
  - `grep -rnE "localStorage|sessionStorage|indexedDB|document\.cookie|history\.(push|replace)State" apps/web/src packages/core/src` → only tests;
  - `grep -rn "fetch(" apps/web/src --include=*.ts --include=*.tsx` → only `main.tsx` and tests;
  - `grep -rn "statementAgreement\|IMPORTANT_WEIGHT\|/ 4" apps/web/src packages/core/src/domain/ranking.ts` → nothing (no re-implementation).
- No E2E harness. Vitest plus the browser check cover the flow.
- **Scratch data**: the recipe in `docs/specs/landing-election-picker.md` "Verification Plan" and `questionnaire-answer-flow`'s evidence. Use `mktemp -d` under the session scratchpad, the worktree CLI, `tests.pipeline_fixtures.fake_provider`, no key, no network.
  - It gives Election 1 with 30 Statements and two Parties: `Partido Alfa` (PA, id 1, +1 on every Statement) and `Bloque Beta` (BB, id 2, −1 on every Statement). Confirm with `ideology pipeline positions`.
  - Serve it with a temporary `.claude/launch.json` entry per practical-notes (`/usr/bin/env WEB_DIST_DIR=… DATABASE_URL=… uvicorn … --port 8011`, `preview_start`). Afterwards stop it, remove the entry and delete the scratch dir; `git status` shows only feature changes.
- **Mandatory real browser** (AGENTS.md) at 375x812 and 1280x800, from the Landing. Runs:
  - **A (distinct scores, non-alphabetical order):** rate 1–6 `De acuerdo`, 7 `Muy en desacuerdo` + Important, skip 8–30. Expect `Partido Alfa 81 %` (7 en común) above `Bloque Beta 56 %`, no badges. Then `Volver a la última afirmación` → 30 skipped; `Revisar mis respuestas` → 1 `De acuerdo`; unflag 7 and walk to the end → `89 %` / `54 %`.
  - **B (tie):** reload, rate 1–5 `Ni de acuerdo ni en desacuerdo`, skip the rest → both `75 %`, `Bloque Beta` first.
  - **C (low coverage):** reload, rate 1–3 `Muy de acuerdo`, skip the rest → `Partido Alfa 75 %`, `Bloque Beta 25 %`, both `Baja cobertura`, `3 afirmaciones en común`, the legend.
  - **D (all skipped):** reload, skip all 30 → the prompt and no list; `Revisar mis respuestas` → Statement 1.
  - A mixed low-coverage list and a null row are not reachable with this fixture (both Parties have a stance everywhere). They are covered by Vitest. A custom fake provider for the browser is optional, not required.
  - Each run's percentages are checked against the engine by hand (formulas above).
  - Also check:
    - the methodology link opens `/metodologia` in a new tab and the results tab keeps its ranking;
    - the network list shows only the document, assets and the three GETs, plus `/metodologia` and its assets in the new tab; no URL contains `?` or `#`;
    - storage and cookies are empty;
    - the console is clean;
    - `scrollWidth <= innerWidth`, buttons and links ≥ 48px;
    - every bar uses the same colour, and no amber appears except on focus and Important;
    - an accessibility snapshot shows the list items' text.

## Evidence To Capture
- `init.sh` step results and Vitest counts; new test names; grep results.
- Browser: Chrome version, both widths, Runs A–D with the observed percentages and order, the methodology tab, the request list, storage/URL values, console, the cleanup. Record only in `feature_list.json` and `PROGRESS.md`, never in `docs/validations/`.

## Validator Checklist
- [ ] Only the files above changed. No new route, dependency, Python, API or engine change.
- [ ] Scores come only through `rankParties` → `computeMatchScores`. Ties are on the displayed percent, sorted with `Intl.Collator("es")` by name, then id. Null scores come last.
- [ ] `Baja cobertura` with a legend built from `LOW_COVERAGE_THRESHOLD`. Identical rows with no party colour. The bar is decorative and the text carries the meaning.
- [ ] The all-skipped prompt replaces the list. Back and `Revisar mis respuestas` keep Answers and flags. The methodology link opens `METHODOLOGY_PATH` in a new tab.
- [ ] Runs A–D pass in a real browser at 375px and desktop. Console clean. No request, URL or storage carries Answers.
- [ ] ARCHITECTURE, CONSTRAINTS, DESIGN and the three risks entries updated as specified. Evidence recorded.
