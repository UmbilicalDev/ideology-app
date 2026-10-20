# Feature Implementation Spec: Methodology page explains AI generation

## Source Feature

- `id`: methodology-page (GitHub issue #37)
- `area`: web
- `depends_on`: landing-election-picker (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Vitest + Testing Library: the page renders and is linked from the landing and results pages"; notes: mitigation for the bias and legal risks, legal wording reviewed before a public launch)

## Goal

Add a public, static Methodology screen (`DESIGN.md` Core Screens 4) at `/metodologia`. It explains in Spanish, using only what is actually built, where the data comes from, how Statements and Party Positions are generated, the Evidence quotes, the Validation checks, the matching rule, the privacy model, and a disclaimer. The Landing's methodology summary links to it instead of saying "se publicará próximamente". The page makes no API request and names no party.

## Decisions

- **Route `/metodologia`** (ASCII, no accent, no `.`, one segment). It is `export const METHODOLOGY_PATH = "/metodologia";` in `features/paths.ts`, rendered by `features/methodology/MethodologyPage.tsx`. Keep the change self-contained because `questionnaire-answer-flow` edits `paths.ts`/`App.tsx` in parallel. Add one export line after `HOME_PATH`, one `import { MethodologyPage } ...` line (alphabetical, between the landing and not-found imports), and one `<Route path={METHODOLOGY_PATH} element={<MethodologyPage />} />` right after the `HOME_PATH` route. Do not touch the questionnaire lines. Whoever merges second keeps both sides.
- **Static copy, no API.** The page takes no `api` prop and calls nothing. Reasons:
  - `/api/v1` exposes no thresholds. They live in `config.ValidationSettings` and per run in `pipeline_runs.validation_settings`, which the public API does not serve.
  - Adding them would be an API change outside this web slice.
  - The text is meant to go through legal review, and generated text can't be reviewed in advance.
  
  The copy therefore states the **defaults** (`config.py`: coverage 70 %, 25–35 Statements, topic share 30 %) and `LOW_COVERAGE_THRESHOLD = 5` / `IMPORTANT_WEIGHT = 2` from `packages/core/src/domain/match-score.ts`. The staleness risk is handled with a new `CONSTRAINTS.md` rule and a risks-doc entry (see Durable Documentation Impact).
- **Accuracy rules for the copy.** These parts are not built yet: the Questionnaire, Important, results, Evidence display and Share Links. The copy describes them as the rule the engine applies ("cuentan el doble"), in future tense ("Podrás consultar", "se usará un enlace"), or with nothing that claims a UI exists. Single-proposition Statements, neutral wording, topic variety and coalition precedence are only **prompt instructions** (`pipeline/prompts.py`), so the copy says "Sus instrucciones le piden…" or "debe" and never presents them as verified. The six Validation checks are the ones in `validation/__init__.py` `CHECKS`. The copy also says openly that a check verifies a quote exists but not that it supports the stance (risks doc, "Quote verified but stance misread").
- **Provisional copy.** A code comment at the top of `MethodologyPage.tsx` says: `// Provisional copy: pending legal review before a public launch (docs/risks-and-open-questions.md, "Electoral and legal exposure").` Nothing in the visible text says "provisional". The site is not publicly launched, and the risks doc tracks the legal check.
- **Neutrality.** No party, coalition or politician names, no logos, no images, no party colours. The only links are the back link and, on the Landing, the new methodology link.
- **Title, focus and scroll.** The new Landing link sits near the bottom, and declarative React Router keeps the scroll position, so without this the page would open mid-scroll. On mount a single `useEffect` does two things:
  - It sets `document.title = "Metodología · Comparador de programas electorales"` and restores the previous title in its cleanup, so this is safe under StrictMode and the Landing title comes back.
  - It calls `headingRef.current?.focus()` on the `<h1 tabIndex={-1}>`. Focus scrolls the heading into view and screen readers announce the new page.
  
  CSS: `main h1[tabindex="-1"]:focus { outline: none; }`, because the heading is not interactive. This is the only focus or scroll management added, and it applies to this page only.
- **Results link deferred** to `results-ranking`, because the results page does not exist. This spec records the deferral in `feature_list.json` and in the risks doc (see Durable Documentation Impact). It also narrows this feature's verification entry, explicitly and not silently.

## Non-Goals

- No results, Questionnaire, Share Link or Important UI, and no link from the results page (owed by `results-ranking`). No change to the Questionnaire placeholder or the not-found page.
- No API, Python, migration (Alembic head stays `0008`), `init.sh` or dependency change. No new design tokens.
- No per-route titles on other pages and no global scroll/focus manager.
- No visible "provisional" banner. No legal review: that is a human task before a public launch.

## Job Story

When I am unsure whether an AI-made voting tool is fair or trustworthy,
I want to read how its Statements, Party Positions and scores are produced and what happens to my answers,
so I can judge the results and check the quotes myself.

## Users And Permissions

- Voter: anonymous and read-only. Opening the page makes no request beyond the static assets.

## Acceptance Scenarios

Exact Spanish copy (tests assert the headings and the sentences named in Tasks). `%` is written `70&nbsp;%` etc. in JSX (a U+00A0 before `%`). Inside `<main>`, in this order:

- `<h1 tabIndex={-1}>Metodología</h1>`, then `<p>Esta página explica de dónde salen las afirmaciones y las posiciones de los partidos, cómo se comprueban antes de publicarse, cómo se calcula la afinidad y qué pasa con tus respuestas.</p>`
- Seven `<section aria-labelledby="methodology-<key>-title">`, each with its own `<h2 id=…>`:
  1. `sources`, **Programas electorales**:
     - `<p>Se usan los programas electorales de las candidaturas con representación en el Congreso de los Diputados, ya sean partidos o coaliciones, tal como se presentaron a las elecciones. Si el programa conjunto de una coalición contradice el de uno de sus partidos, la inteligencia artificial debe dar prioridad al programa conjunto.</p>`
     - `<p>Las instrucciones que recibe la inteligencia artificial nunca incluyen el nombre del partido: solo el texto de su programa, que puede mencionarlo. Todos los programas se procesan con las mismas instrucciones.</p>`
  2. `statements`, **Cómo se redactan las afirmaciones**:
     - `<p>Una inteligencia artificial lee los programas por fragmentos y propone afirmaciones: propuestas políticas concretas con las que se puede estar de acuerdo o en desacuerdo. Después elige y redacta la lista final, de unas 30 afirmaciones, y asigna a cada una un tema.</p>`
     - `<p>Sus instrucciones le piden una redacción neutral, sin adjetivos valorativos ni nombres de partidos o de políticos, una sola propuesta por afirmación, temas variados y, preferiblemente, propuestas en las que los partidos discrepen. Nadie modifica a mano el resultado.</p>`
  3. `positions`, **Cómo se sitúa a cada partido**:
     - `<p>La inteligencia artificial vuelve a leer el programa de cada partido y, en cada afirmación que el programa trata de forma explícita, le asigna una posición en una escala de cinco puntos, de «totalmente en desacuerdo» a «totalmente de acuerdo», y copia una cita literal del programa, con su página, que la respalda.</p>`
     - `<p>Si el programa no trata una afirmación, el partido queda sin posición en ella: sus instrucciones le prohíben deducir la posición de la ideología general del partido.</p>`
     - `<p>Podrás consultar la cita de cada posición para comprobarla. Las comprobaciones automáticas verifican que la cita está en el programa, pero no pueden confirmar que respalde la posición asignada; por eso es importante que puedas leerla.</p>`
  4. `validation`, **Comprobaciones antes de publicar**:
     - `<p>Antes de publicar los datos de unas elecciones, se comprueba automáticamente que:</p>`
     - A `<ul>` with exactly 6 `<li>`:
       - `cada cita aparece literalmente en el programa del partido, empezando en la página indicada, sin tener en cuenta mayúsculas, tildes, espacios ni signos de puntuación;`
       - `cada partido tiene posición en al menos el 70 % de las afirmaciones;`
       - `en cada afirmación hay al menos dos posiciones distintas entre los partidos que tienen posición;`
       - `no hay dos afirmaciones con el mismo texto;`
       - `el cuestionario tiene entre 25 y 35 afirmaciones;`
       - `ningún tema reúne más del 30 % de las afirmaciones.`
     - `<p>Si falla cualquiera de estas comprobaciones, no se publica nada y siguen vigentes los datos publicados anteriormente, si los hay. Una vez publicados, los datos no se modifican nunca: si se generan datos nuevos, sustituyen a los anteriores.</p>`
  5. `matching`, **Cómo se calcula la afinidad**:
     - `<p>Tus respuestas y las posiciones de los partidos usan la misma escala de cinco puntos. En cada afirmación, la coincidencia con un partido es del 100 % si tu respuesta y su posición son iguales, y baja 25 puntos por cada paso de diferencia en la escala: es del 0 % entre «totalmente de acuerdo» y «totalmente en desacuerdo».</p>`
     - `<p>La afinidad con cada partido es la media de esas coincidencias en las afirmaciones que respondes y en las que el partido tiene posición. Las afirmaciones que te saltes y aquellas en las que el partido no tiene posición no cuentan. Las que marques como importantes cuentan el doble.</p>`
     - `<p>Si compartes menos de 5 afirmaciones con un partido, su afinidad se marca como de baja cobertura, porque se basa en pocos datos. Los partidos se ordenan por afinidad y, en caso de empate, alfabéticamente.</p>`
  6. `privacy`, **Tus respuestas**:
     - `<p>Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún servidor, y la afinidad se calcula en tu propio dispositivo. No hay cuentas de usuario ni estadísticas sobre las respuestas.</p>`
     - `<p>Para volver a abrir o compartir un resultado se usará un enlace que lleva tus respuestas al final de la dirección, tras el símbolo «#». Los navegadores no envían esa parte de la dirección al servidor.</p>`
  7. `disclaimer`, **Aviso**, with `className="card"`:
     - `<p>Esta herramienta no es una recomendación de voto. Las afirmaciones y las posiciones las genera automáticamente una inteligencia artificial, sin revisión humana, y pueden contener errores. La afinidad solo refleja lo que dicen los programas electorales, no lo que los partidos han hecho o votado. Contrasta las citas con los programas originales antes de sacar conclusiones.</p>`
- `<p><Link className="back-link" to={HOME_PATH}>Volver al inicio</Link></p>`
- Landing change: the third paragraph of "Cómo funciona" (`La explicación completa de la metodología se publicará próximamente.`) becomes `<p><Link className="text-link" to={METHODOLOGY_PATH}>Lee la metodología completa</Link></p>`. The rest of the Landing is unchanged.

The matching copy checks out against the engine: 1 − |d|/4 gives 100/75/50/25/0 %.

### Scenario 1: open from the Landing
Given the Landing at `/`, in any list state (loading, loaded, empty or error)
When the Voter activates `Lee la metodología completa`
Then the URL is `/metodologia`, the `Metodología` h1 is focused and in view, the tab title is `Metodología · Comparador de programas electorales`, and no API request is made.

### Scenario 2: back to the Landing
Given Scenario 1
When the Voter presses browser Back (or activates `Volver al inicio`)
Then the Landing shows again with its title `Comparador de programas electorales`, and Forward returns to the page.

### Scenario 3: deep link and reload
Given the FastAPI-served build
When `/metodologia` is opened or reloaded directly
Then the page renders with no API request. `/metodologia/x` renders `Página no encontrada`, and the existing not-found paths still do.

### Scenario 4: neutral and accessible
Given the page at 375px and at desktop width
Then there is one h1 and seven h2 in the order above, each section is a named region, no party name or image appears, there is no horizontal scroll, the column is 720px, tap targets are at least 48px, and the focus ring is visible on the links.

## Repository Research

### Files Inspected
- `apps/web/src/{app/App.tsx,app/App.test.tsx,main.tsx,features/paths.ts,features/landing/LandingPage.tsx,LandingPage.test.tsx,features/not-found/NotFoundPage.tsx,ui/components.css,ui/global.css,test/setup.ts,test/fetch-mocks.ts}`, `apps/web/{index.html,package.json}` (React 19.3.1, react-router 7.18.4).
- `src/ideology_app/validation/{__init__.py,evidence_quotes.py}` (the six `CHECKS`, normalisation, cited-page rule), `config.py` (`ValidationSettings` defaults 70/25/35/30), `pipeline/prompts.py` (neutral-wording, single-proposition, coalition and no-inference rules, `TARGET_STATEMENT_COUNT = 30`), `api/schemas.py` (no thresholds exposed).
- `packages/core/src/domain/match-score.ts` (`1 − |a − p| / 4`, weight 2, threshold 5, skip/no-stance excluded).
- `CONTEXT.md`, `DESIGN.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md` (Web Client), `docs/build-brief.md`, `docs/domain-model.md`, `docs/risks-and-open-questions.md`, `docs/specs/landing-election-picker.md`, `.agents/skills/github-flow/references/practical-notes.md`, `.claude/launch.json`, `PROGRESS.md` (Vitest 82 = 41 + 24 core + 17 web).

### Existing Patterns To Follow
- Pages render their own `<main>`; sections use `aria-labelledby` on the h2; `.card`, `.back-link` (48px); Tests render `<MemoryRouter><App api={createPublicApiClient({ fetch })} /></MemoryRouter>` and assert the mock `fetch` call count.

### Current Gaps
- No methodology route. The Landing tests assert no methodology link (`has no methodology link`, `queryAllByRole("link")` length 0 in Scenarios 4/5, all links = Elections in Scenario 6).

## Expected File Changes
- create `apps/web/src/features/methodology/MethodologyPage.tsx`, `MethodologyPage.test.tsx`.
- modify `apps/web/src/features/paths.ts`, `app/App.tsx`, `app/App.test.tsx`, `features/landing/LandingPage.tsx`, `LandingPage.test.tsx`, `ui/components.css`.
- docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `feature_list.json`, `PROGRESS.md`.

## Visual Design Impact
- UI involved: yes. Design source: `DESIGN.md`. No new artifact or token.
- Body text is `text` on `background`. The disclaimer is a `.card` (surface, border, 12px radius). Lists use the default bullets with `padding-left: var(--space-lg)` and `margin: 0 0 var(--space-md)` (add `main ul:not(.election-list)` or a `.plain-list` class, the implementer's choice, scoped so `.election-list` is unaffected).
- `.text-link` joins the `.back-link` rule (`.back-link, .text-link { display: inline-flex; align-items: center; min-height: 48px; }`). Links use `primary` with the amber `:focus-visible` outline already defined. Add `main h1[tabindex="-1"]:focus { outline: none; }`.
- `muted` is not used (AA on `background` fails). No red/green, no party colours.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update the Web Client route table (`/metodologia` → `features/methodology/MethodologyPage.tsx`: static, no `api` prop, no request, sets and restores `document.title`, focuses the h1), the Landing line (the summary now links to it), `.text-link` in the components list, the tests list, and "Current state after".
- `CONSTRAINTS.md`: add under Web Client Serving (or a new "Public Copy" heading):
  - Rule: `MethodologyPage.tsx` and its test MUST be updated in the same change whenever a Validation check, a `ValidationSettings` default, the matching rule (`match-score.ts` constants or formula), the prompt rules it describes, or the privacy model changes.
  - Reason: the page is static copy and the public description of the method; stale copy is a legal and trust risk.
- `docs/risks-and-open-questions.md`:
  - **Perceived bias in Statements**: change "and a public methodology page" to "and the public methodology page (`/metodologia`, since `methodology-page`), which states these rules and that the LLM never sees party names". The risk stays open (real-LLM wording unverified).
  - **Electoral and legal exposure**: rewrite the tail. The disclaimer and methodology page exist since `methodology-page`. Their copy, like the Landing's AI disclosure and summary, is provisional (comment in `MethodologyPage.tsx`). The legal check before a public launch is still open and owned by no feature yet; it must happen before the first public deployment. The risk stays open.
  - New Implementation-Time entry:
    - The methodology page is static and states the default thresholds (70 %, 25–35, 30 %) and low coverage at 5. A deployment that sets `VALIDATION_*` differently must update the copy (see `CONSTRAINTS.md`). Serving each Dataset Version's recorded thresholds through `/api/v1` is the alternative, and no feature owns it.
    - Owed by `results-ranking`: a link to `METHODOLOGY_PATH` from the results page, and a low-coverage badge wording consistent with "baja cobertura" (or an update to the page).
    - Owed by `share-link-create`: switch the privacy paragraph from "se usará un enlace" to present tense.
- `feature_list.json`:
  - `methodology-page.verification` becomes `["Vitest + Testing Library: the page renders, is linked from the landing page and deep-links to /metodologia (the results-page link is deferred to results-ranking)", "Browser check at 375px and desktop following DESIGN.md"]`.
  - Append to `results-ranking.verification` `"Vitest: the results page links to the methodology page (METHODOLOGY_PATH)"`, and to its notes `"Link to /metodologia (deferred by methodology-page); match the 'baja cobertura' wording or update MethodologyPage."`
  - Append to `share-link-create.notes` `"Update the MethodologyPage privacy paragraph to present tense (deferred by methodology-page)."`
- `AGENTS.md`, `DESIGN.md` (Core Screens 4 already describes the page), `docs/domain-model.md`, `docs/build-brief.md`: not needed.

## Implementation Plan
1. `paths.ts` + `App.tsx` route, then `MethodologyPage.tsx` with the exact copy and the effect.
2. Landing link + CSS.
3. Tests (new + updated), `CI=true ./init.sh`, browser walk-through, docs.

## Implementation Tasks
- [ ] `MethodologyPage.test.tsx` (render at `/metodologia` through `App` with `vi.fn<FetchLike>()`):
  - the h1 text and `document.activeElement` is the h1;
  - the h2 texts in order equal the seven headings, and seven named regions exist;
  - the validation `<ul>` has 6 items, and one item asserts `cada partido tiene posición en al menos el 70 % de las afirmaciones;`;
  - the intro, the first privacy paragraph and the disclaimer paragraph (inside the `Aviso` region) are asserted exactly;
  - the second `Programas electorales` paragraph (prompts never include the party name) is asserted exactly inside its region, and the old wording `nunca recibe el nombre del partido` is absent;
  - `document.title` is the methodology title;
  - the only link is `Volver al inicio` → `/`; there is no `img`; `fetch` is never called.
- [ ] `App.test.tsx`:
  - Landing (mock lists one Election) → click `Lee la metodología completa` → h1 `Metodología`, fetch called once in total; `Volver al inicio` → Election link shown again, and `document.title` is restored to its previous value (jsdom does not load `index.html`, so the test sets `document.title = "Comparador de programas electorales"` before rendering and asserts it again after going back);
  - deep link `/metodologia` makes no fetch;
  - add `/metodologia/x` to the not-found `test.each`.
- [ ] `LandingPage.test.tsx`:
  - replace `has no methodology link` with `links to the methodology page` (link `Lee la metodología completa` with href `/metodologia`);
  - `expectDisclosureAndMethodology` asserts that link instead of the "próximamente" text;
  - Scenarios 4/5: no `election-link` cards (query within the Elections region), and the methodology link is present;
  - Scenario 6: take links from the Elections region.
- [ ] CSS and docs per sections above. Run `grep -rn "próximamente" apps/web/src`; it should give no match outside the Questionnaire placeholder (`muy pronto`).

## Verification Plan
- `CI=true ./init.sh` exits 0: pytest unchanged (910 at last record), Vitest 82 + the new tests, typecheck and build ok. `git diff --stat` touches no Python, migration, `init.sh` or `package*.json`. `grep -rn "fetch(" apps/web/src` gives no new match.
- No E2E harness exists. Vitest with `MemoryRouter` plus the browser check cover the flow.
- **Browser** (Chrome via chrome-devtools MCP, or the desktop preview), following `practical-notes.md`:
  - Serving:
    - After the gate, create `SCRATCH=$(mktemp -d /tmp/methodology-XXXXXX)` and run `DATABASE_URL=sqlite:///$SCRATCH/check.db <worktree>/.venv/bin/ideology db upgrade` (an empty migrated DB: the Landing shows the empty message plus the link). Optionally add a published Election with the scratch steps from `docs/specs/landing-election-picker.md`.
    - Serve with a **temporary** `.claude/launch.json` entry `tmp-methodology-page` (`/usr/bin/env WEB_DIST_DIR=<worktree>/apps/web/dist DATABASE_URL=sqlite:///$SCRATCH/check.db <worktree>/.venv/bin/uvicorn ideology_app.main:app --port 8021`). Use port 8021 or another free port other than 8000/8011; check with `lsof -nP -iTCP:8021`.
    - Or run the same uvicorn command directly.
    - Remove the entry and `$SCRATCH` afterwards; `git status` must show only the feature's files.
  - At 375x812 and 1280x800:
    - Scenario 1: scroll to the Landing link, click it; the page opens at the h1 and the tab title changes.
    - Scenario 2: Back, then Forward; `Volver al inicio`.
    - Scenario 3: reload `/metodologia` and open `/metodologia/x`.
    - Keyboard: Tab to `Lee la metodología completa`, press Enter, Tab to `Volver al inicio`; the focus ring is visible.
    - Read the whole page: no party names, the order and headings are right, `scrollWidth <= innerWidth` at 375px, a 720px column on desktop, links at least 48px high.
  - Console clean. Network: same-origin only; the document, JS and CSS, and `GET /api/v1/elections` only on Landing loads; **no request** when opening or reloading `/metodologia` other than the document/assets; no query strings, no body, no voter data.

## Evidence To Capture
- `init.sh` step results and Vitest/pytest counts; the new and changed test names.
- Browser: the browser and its version, the widths, each scenario's result, the console state, and the request list for the Landing → page → Back sequence and for the deep-link reload. Record it in `feature_list.json` (`methodology-page.evidence`) and `PROGRESS.md`; never in `docs/validations/`.

## Validator Checklist
- [ ] The route is `/metodologia` from `METHODOLOGY_PATH`; the edits to `App.tsx`/`paths.ts` are minimal; no questionnaire or results work.
- [ ] The copy matches this spec exactly and is true of the code (the six `CHECKS`, the `config.py` defaults, `match-score.ts`, the prompt rules); unbuilt parts are not claimed as present; no party is named.
- [ ] The Landing links to the page; the Landing tests are updated; not-found is unaffected; the page makes no request.
- [ ] The title/focus effect works and is restored; the accessibility points of Scenario 4 hold.
- [ ] The real-browser check was done at 375px and desktop with a clean console and network; the temporary launch entry and scratch DB were removed.
- [ ] `CONSTRAINTS.md`, `ARCHITECTURE.md`, the risks doc (bias, legal, new entry) and `feature_list.json` (own verification, `results-ranking`, `share-link-create`) are updated as specified; there is no `docs/validations/`.
