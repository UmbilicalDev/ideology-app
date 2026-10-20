# Feature Implementation Spec: Voter answers Statements on the 5-point scale

## Source Feature

- `id`: questionnaire-answer-flow (GitHub issue #36)
- `area`: web
- `depends_on`: landing-election-picker (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Browser test: answer, skip and go back across all Statements"; "Network check: no request carries the answers"; notes: "The scale is an accessible radio group; no red/green.")

## Goal

The Questionnaire placeholder at `/elecciones/:electionId/cuestionario` becomes the real Questionnaire (`DESIGN.md` Core Screens 2). It loads the Election's Published Dataset Version through the `packages/core` public API client and shows one Statement at a time with a progress bar. The Voter picks one of five options (an accessible radio group), skips, moves forward and goes back, through every Statement, and reaches a clear end screen (results come later). Answers live only in React state in the browser. They are never sent in a request, never written to browser storage and never put in the URL.

## Decisions

- **Loading (two requests, pinned version).** `PublicApi` gains two methods (the port and the client grow; nothing is redesigned):
  - `getElection(id: number): Promise<Election>` → `GET /api/v1/elections/{id}`, parsed with the existing `parseElection`.
  - `getDatasetVersion(id: number): Promise<DatasetVersion>` → `GET /api/v1/dataset-versions/{id}`.
  - The page calls `getElection(electionId)` first. `publishedDatasetVersionId === null` → the "not available yet" state, with no second request. Otherwise it calls `getDatasetVersion(publishedDatasetVersionId)`.
  - Why not `/published-dataset-version`: the client does not read error bodies (`!ok` never calls `json()`), so its 404 cannot tell `election_not_found` from `no_published_dataset_version`. Two requests give two distinct states, the Election name for the page, and a pinned version id. A live-mode publish during the session does not change the Statements the Voter is answering (`docs/domain-model.md` edge case). The by-id body is `immutable`-cached.
  - Same request shape as `listElections`: `{ method: "GET", headers: { Accept: "application/json" } }`, no query string and no body. The id is the only variable in the path, and it is a number.
- **`DatasetVersion` domain type** (`packages/core/src/domain/dataset-version.ts`, all readonly, camelCase): `{ id, electionId, createdAt, statements: Statement[], parties: Party[] }`. `Statement { id, position, text, topic }`. `Party { id, name, shortName, positions: PartyPosition[] }`. `PartyPosition { statementId, value: ScaleValue | typeof NO_STANCE, evidence: Evidence | null }`. `Evidence { quote, page, url: string | null, sourceDocumentId }`. The full body is parsed and checked now, so `results-ranking` and `results-breakdown-evidence` reuse it without touching the adapter. This feature renders only `statements`.
  - Contract checks (`invalid_response`, the message names the path like `listElections` does):
    - `id`, `election_id`, statement `id`, party `id`, `source_document_id` and `page` are positive safe integers. Statement `position` is a positive safe integer (DB check `position >= 1`).
    - `created_at` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`. `text`, `topic`, `name`, `short_name` and `quote` are strings. `url` is a string or `null`.
    - `statements` and `parties` are arrays. Statement ids are unique, and positions strictly increase (the API sends position order).
    - Each party's `positions` has exactly one entry per Statement in Statement order (`positions[i].statement_id === statements[i].id`). `value` is an integer −2..2 or `"no_stance"`. `evidence` is `null` exactly when `value` is `"no_stance"`.
    - Unknown keys are ignored. An empty `statements` array is valid for the client; the page handles it.
- **Answer state** (`packages/core/src/domain/questionnaire.ts`, pure, no React or DOM, tested under Node; reusable by the later mobile app):
  - `type AnswerValue = ScaleValue | typeof SKIP` (reuses `match-score.ts`'s `ScaleValue` and `SKIP`, so `results-ranking` maps it straight to the engine's `Answer`).
  - `interface QuestionnaireState { readonly statementIds: readonly number[]; readonly currentIndex: number; readonly answers: ReadonlyMap<number, AnswerValue> }`, keyed by Statement id. `currentIndex` runs `0..statementIds.length`, and `length` means the end screen. An unanswered Statement has no map entry.
  - `startQuestionnaire(statementIds)` returns index 0 with an empty map.
  - `reduceQuestionnaire(state, action)` with these actions:
    - `{ type: "select", value: ScaleValue }` records the value for the current Statement and does **not** advance.
    - `{ type: "skip" }` records `SKIP` and advances.
    - `{ type: "next" }` advances only when the current Statement has an entry (a value or `SKIP`); otherwise the state is unchanged.
    - `{ type: "back" }` moves to `max(0, currentIndex − 1)`, also from the end screen.
    - Every action is a no-op on the end screen except `back`. Each action returns a new state with a new `Map`, never a mutated one.
  - Invariant: every Statement before `currentIndex` has an entry. Exported helper `summarize(state) → { answered, skipped, total }`.
  - No `important` field. `questionnaire-important-flag` adds it.
- **Where state lives.** `useReducer` in `QuestionnaireFlow`, which `QuestionnairePage` renders once the data is ready, with `key={datasetVersion.id}`.
  - Not persisted: no `localStorage`, `sessionStorage`, cookies or IndexedDB.
  - The URL never changes while answering: no per-Statement route, query, fragment or history entry.
  - Reloading, browser Back, or leaving the page discards the Answers. The page says so.
  - Share Links (`share-link-create`) are the only planned way to carry Answers, in the fragment. How `results-ranking` receives the Answers (lifting the state, or rendering results inside the flow) is that feature's decision.
- **Interaction (no auto-advance).** Choosing an option only selects it, because native radios change on arrow keys, and auto-advancing would move on at the first arrow press. Controls, in DOM order:
  - `Siguiente`: `button-primary`, natively `disabled` until the current Statement has an entry.
  - `Saltar esta afirmación`: `button-secondary`.
  - `Anterior`: `button-secondary`, not rendered on the first Statement.
  - Returning to a Statement shows its stored value checked, or for a skip, no radio checked plus the text `Has saltado esta afirmación.`. Choosing a value replaces a skip. `Saltar` on an answered Statement replaces the value with a skip.
- **Accessibility.**
  - The Statement text is `<h2 id="statement-text" tabIndex={-1}>`.
  - The scale is `<div role="radiogroup" aria-labelledby="statement-text">` holding five native `<label className="scale-option"><input type="radio" name={`answer-${statement.id}`} value=... /> <span>label</span></label>`. Native radios give Tab into the group, arrow keys to move and select, and Space to select.
  - Order and labels (meaning carried by text, never by colour): −2 `Muy en desacuerdo`, −1 `En desacuerdo`, 0 `Ni de acuerdo ni en desacuerdo`, 1 `De acuerdo`, 2 `Muy de acuerdo`.
  - The step component is keyed by Statement id, so no checked state leaks between Statements.
  - After `Siguiente`, `Saltar` or `Anterior`, focus moves to the new Statement's `h2`, or to the end screen's `h2`. Initial load does not move focus.
  - Progress: `<p id="questionnaire-progress">Afirmación {n} de {total}</p>` plus `<progress max={total} value={n} aria-labelledby="questionnaire-progress">`, where `n = currentIndex + 1`.
- **Statement order:** API `position` order. Randomisation stays an open question in the risks doc. The topic is not shown.
- **No party content.** The Questionnaire shows no Party names, logos, colours or Positions, so all Parties are treated identically by construction.

## Non-Goals

- Important flag/star (`questionnaire-important-flag`). Match Scores, ranking, the "skipped everything" prompt and any call to `computeMatchScores` (`results-ranking`). Evidence display (`results-breakdown-evidence`). Share Link encode/open (`share-link-*`). Methodology page or link (`methodology-page`).
- Persisting Answers anywhere (Web Storage, cookies, IndexedDB, URL) or warning before leaving the page.
- Showing topics, randomising order, `document.title` per route, an "archived/historical" label (nothing sets `archived` yet; any Election with a Published version is answerable).
- Any Python, API, migration, `init.sh`, Node floor or npm dependency change. No new design tokens.

## Job Story

When I have chosen an Election,
I want to rate its Statements one by one, skip the ones I have no view on and correct earlier answers,
so I can finish the Questionnaire knowing my answers never left my browser.

## Users And Permissions

- Voter: anonymous, read-only. The only requests are `GET /api/v1/elections/{id}` and `GET /api/v1/dataset-versions/{id}`, both made before the first Answer, with no voter data.

## Acceptance Scenarios

Exact Spanish copy (tests assert it). Inside `<main>`: `<h1>Cuestionario</h1>`, then per state:
- Loading: `<p role="status">Cargando cuestionario…</p>`.
- Step: `<p className="questionnaire__election">{election.name}</p>`, the progress `p` + `progress`, the `h2`, the radiogroup, the optional `Has saltado esta afirmación.`, the controls, then `<p className="questionnaire__note">Las afirmaciones las ha generado una inteligencia artificial a partir de los programas electorales. Tus respuestas se quedan en este navegador: no se envían a ningún servidor y se pierden si recargas o sales de la página.</p>`.
- End: the Election name, then `<h2 tabIndex={-1}>Has llegado al final del cuestionario</h2>`, `<p>Has respondido {answered} de {total} afirmaciones y has saltado {skipped}.</p>`, `<p>Los resultados estarán disponibles muy pronto.</p>`, a `button-secondary` `Volver a la última afirmación` (dispatches `back`) and `<Link className="back-link" to="/">Volver al inicio</Link>`.
- Not available (`publishedDatasetVersionId` null, or zero Statements): `<p>El cuestionario de estas elecciones todavía no está disponible. Vuelve a consultarlo más adelante.</p>` + `Volver al inicio`.
- Election 404 (`PublicApiError` `kind: "http"`, `status: 404` from `getElection`): render the existing `NotFoundPage` (`Página no encontrada`).
- Error (any other `PublicApiError`, a 404 from `getDatasetVersion`, or `datasetVersion.electionId !== electionId`): `<div role="alert"><p>No se ha podido cargar el cuestionario. Comprueba tu conexión e inténtalo de nuevo.</p><button className="button-primary">Reintentar</button></div>` + `Volver al inicio`. `Reintentar` shows loading and repeats both requests. Nothing is logged to the console.

### Scenario 1: load and first Statement
Given Election 1 `Generales 2023` is active with Published Dataset Version 1 of 30 Statements
When the Voter opens `/elecciones/1/cuestionario` (from the Landing link or directly)
Then the loading status shows, then the first Statement (position 1), `Afirmación 1 de 30`, a progress bar at 1/30, five unchecked radios in the labelled radiogroup, `Siguiente` disabled, `Saltar esta afirmación` enabled, and no `Anterior`. Exactly `GET /api/v1/elections/1` then `GET /api/v1/dataset-versions/1` were requested.

### Scenario 2: answer and advance
Given Scenario 1
When the Voter selects `De acuerdo` and activates `Siguiente`
Then Statement 2 shows with `Afirmación 2 de 30`, no radio checked, `Anterior` visible, and focus on the Statement heading. Selecting alone did not advance.

### Scenario 3: skip
Given Statement 2 is shown
When the Voter activates `Saltar esta afirmación`
Then Statement 3 shows (`Afirmación 3 de 30`).

### Scenario 4: go back and change
Given Statement 3 is shown after Scenarios 2–3
When the Voter activates `Anterior`
Then Statement 2 shows with no radio checked, `Has saltado esta afirmación.` and `Siguiente` enabled. Activating `Anterior` again shows Statement 1 with `De acuerdo` checked. Selecting `Muy de acuerdo` replaces the stored value, and `Siguiente` returns to Statement 2, which is still skipped.

### Scenario 5: through every Statement to the end
Given the Voter is on any Statement
When they answer or skip every remaining Statement up to `Afirmación 30 de 30` and leave the last one with `Siguiente` or `Saltar`
Then the end screen shows `Has respondido {a} de 30 afirmaciones y has saltado {s}.` with the right counts (a + s = 30) and focus on its heading. `Volver a la última afirmación` shows Statement 30 with its stored Answer. The URL stayed `/elecciones/1/cuestionario` throughout, with no `?` or `#`.

### Scenario 6: keyboard and screen reader
Given a Statement is shown
When the Voter uses only the keyboard (Tab into the group, arrow keys, Space, Tab to `Siguiente`, Enter)
Then the selection follows the arrow keys without advancing, a 3px amber focus outline is visible on the focused option and on buttons, and the accessibility tree shows a radiogroup named by the Statement text, five radios with their Spanish labels and checked state, and a progressbar labelled `Afirmación n de 30`.

### Scenario 7: no published version, unknown Election, API error
Given Election 2 is `draft` (published id `null`), Election 999 does not exist, and on another server the API answers 500
When the Voter opens each Questionnaire URL
Then they see, respectively, the not-available message (only `GET /api/v1/elections/2` was requested), `Página no encontrada`, and the alert with `Reintentar` (which retries and, if the API now succeeds, shows Statement 1). Invalid ids (`/elecciones/abc/cuestionario`) still render `Página no encontrada` with no request.

### Scenario 8: Answers never leave the browser
Given Scenarios 1–5 were walked through
Then the network log shows no request after the Dataset Version load: no request carries any Answer in its path, query, headers or body. `localStorage.length === 0`, `sessionStorage.length === 0` and `document.cookie === ""`.

## Repository Research

### Files Inspected
- `apps/web/src/{main.tsx,app/App.tsx,app/App.test.tsx,features/paths.ts,features/questionnaire/QuestionnairePlaceholderPage.tsx,features/landing/{LandingPage.tsx,useElections.ts,LandingPage.test.tsx},features/not-found/NotFoundPage.tsx,test/{fetch-mocks.ts,setup.ts},ui/{tokens,global,components}.css}`, `apps/web/package.json`.
- `packages/core/src/{index.ts,application/public-api.ts,domain/election.ts,domain/match-score.ts,infrastructure/http/public-api-client.ts}`, `packages/core/test/infrastructure/public-api-client.test.ts`.
- `src/ideology_app/api/schemas.py` (the `DatasetVersionOut` contract), `src/ideology_app/models.py` (`position >= 1`), `tests/pipeline_fixtures.py` (`fake_provider` yields 30 Statements), `.mcp.json` (chrome-devtools-mcp).
- `ARCHITECTURE.md` (Public API, Public API Client, Web Client), `CONSTRAINTS.md`, `DESIGN.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/build-brief.md`, `docs/risks-and-open-questions.md`, `docs/specs/{landing-election-picker,public-dataset-api,web-client-skeleton}.md`, `feature_list.json` (downstream `questionnaire-important-flag`, `results-ranking`, `share-link-create`).

### Existing Patterns To Follow
- Layers `ui` → `features` → `core`. Contract checks and pure rules live in core (Node-tested). Pages take `api` as a prop. `useElections` shows the data-hook pattern (an `active` flag, `retry`, no logging).
- Web tests render `<MemoryRouter><App api={createPublicApiClient({ fetch: vi.fn<FetchLike>() })} /></MemoryRouter>`, use `fireEvent` (no user-event), and global `fetch` throws.

### Current Gaps
- The client has only `listElections`. There is no Dataset Version type and no answer state. The placeholder makes no API call.

## Expected File Changes
- `packages/core/src/domain/dataset-version.ts`: create (types).
- `packages/core/src/domain/questionnaire.ts`: create (state, reducer, `summarize`).
- `packages/core/src/application/public-api.ts`: modify (two methods).
- `packages/core/src/infrastructure/http/public-api-client.ts`: modify. Add `getElection` and `getDatasetVersion`, and a `parseDatasetVersion` reusing `ContractError` and the helpers. Wrap contract errors the same way for every method, e.g. one `getParsed(path, parse)` helper.
- `packages/core/src/index.ts`: modify (re-export the new types and functions).
- `packages/core/test/infrastructure/public-api-client.test.ts`: modify. `packages/core/test/domain/questionnaire.test.ts`: create.
- `apps/web/src/features/questionnaire/QuestionnairePage.tsx`: create (parses the id, `NotFoundPage` on `null`, renders states).
- `apps/web/src/features/questionnaire/useQuestionnaireData.ts`: create. State `loading | ready {election, datasetVersion} | unavailable | not_found | error`, plus `retry`.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: create (reducer, step, end screen, focus).
- `apps/web/src/features/questionnaire/QuestionnairePage.test.tsx`: create.
- `apps/web/src/features/questionnaire/QuestionnairePlaceholderPage.tsx`: delete.
- `apps/web/src/app/App.tsx`: modify (route → `QuestionnairePage api={api}`). `apps/web/src/app/App.test.tsx`: modify (the placeholder scenarios become Questionnaire ones; invalid-id cases keep "no fetch").
- `apps/web/src/test/fetch-mocks.ts`: modify. Add `datasetVersionJson({ statements: n, electionId })`: n Statements `Afirmación de prueba {i}` with positions 1..n, and two parties with one position each per Statement, including one `no_stance` with `evidence: null`.
- `apps/web/src/ui/components.css`: modify (see Visual Design Impact).
- Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Source: `DESIGN.md`. No new design artifact or token.
- `.scale-option`: a block label, full width, stacked vertically at every width. `surface` background, 1px `border`, 12px radius, min-height 48px, 16px padding, a visible native radio, and text in `text`.
  - Decorative 4px left border on a grey-to-blue ramp from `--color-scale-disagree-strong` (−2) to `--color-scale-agree-strong` (+2): `color-mix(in srgb, …)` at 100/75/50/25/0 % disagree. Meaning stays in the labels.
  - Checked (`:has(input:checked)`): 2px `primary` border and 600 weight. No red/green and no party colours anywhere.
- Focus: add `input:focus-visible` to the amber outline rule. `.scale-option:has(input:focus-visible)` gets the 3px `accent` outline. The programmatically focused `h2[tabindex="-1"]:focus` has no outline.
- `.button-secondary`: `surface` background, `primary` text, 1px `border`, 12px radius, min-height 48px, 600 weight. `.button-primary:disabled`: `opacity: 0.5; cursor: not-allowed`. Controls are in a `flex-wrap` row with an 8px gap, and wrap on narrow screens.
- `progress`: full width, 8px high, `primary` fill on a `border` track (`appearance: none` with `::-webkit-progress-*` / `::-moz-progress-bar`).
- `.questionnaire__election` and `.questionnaire__note` use `text` or `secondary` colour, never `muted`, which fails AA on `background`.
- At 375px: single column, no horizontal scroll, every tap target ≥ 48px. Desktop: the 720px column.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update.
  - Public API Client: `getElection` and `getDatasetVersion`, the `DatasetVersion` types and their checks.
  - Core: `domain/questionnaire.ts`.
  - Web Client: the route now renders `QuestionnairePage`, its states and requests, and the in-memory-only Answers. Add the feature to the "Current state after" line.
- `CONSTRAINTS.md` (Client-side Matching): add "Client code MUST NOT write Answers to `localStorage`, `sessionStorage`, cookies or IndexedDB. Reason: answers stay in memory until a deliberate feature (Share Links) decides otherwise; shared devices must not keep them."
- `docs/risks-and-open-questions.md`:
  - "Order in which Statements are shown": note that `questionnaire-answer-flow` shows API `position` order; randomisation stays open.
  - Add an Implementation-Time Question: "Answers are memory-only (`questionnaire-answer-flow`), so a reload, browser Back or leaving the page loses them, with no warning. Revisit in `results-ranking` / `share-link-create`."
  - "Minimum number of answered Statements": add `(results-ranking)`.
  - Touch only these entries; the parallel `live-mode-url-refetch` edits the URL re-fetch entries.
- `AGENTS.md`, `DESIGN.md`, `CONTEXT.md`, `docs/technical-discovery.md`: not needed (no workflow, token or term change).

## Implementation Plan
1. Core: the types, `questionnaire.ts` and its tests, then the two client methods and their tests.
2. Web: `fetch-mocks` additions, `useQuestionnaireData`, `QuestionnaireFlow`, `QuestionnairePage`, the route, CSS. Delete the placeholder.
3. Web tests, then `CI=true ./init.sh`, then the browser walk-through, then the docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks
- [ ] `questionnaire.test.ts`: start state; `select` does not advance and overwrites; `skip` records and advances; `next` is a no-op without an entry and advances with a value or a skip; `back` clamps at 0 and works from the end; actions on the end screen other than `back` are no-ops; immutability (the old Map is unchanged); `summarize` counts; a 0-Statement start is immediately at the end.
- [ ] Client tests:
  - Exact URLs `/api/v1/elections/7` and `/api/v1/dataset-versions/3` with the same `init`, and `baseUrl` prefixing.
  - Mapping to camelCase. 404 → `http` with status 404 and `json` not called. Network and invalid JSON.
  - A table of bad Dataset Version bodies: a missing `statements`, a bad `created_at`, a duplicate statement id, a non-increasing position, a positions length mismatch, a wrong `statement_id` order, value `3` / `"2"`, evidence `null` with a value, evidence present with `no_stance`, page `0`. Each has the expected message.
- [ ] `QuestionnairePage.test.tsx` (3-Statement fixture):
  - Scenarios 1–5 by roles: `radiogroup` by name, `radio` by label, `button` by name, the `progressbar` value. Focus is on the `h2` after each move (`document.activeElement`).
  - Scenario 7 (null id → one fetch call; 404 → `Página no encontrada`; 500 → alert, retry → step; `electionId` mismatch → alert; zero Statements → not available).
  - Scenario 8 in jsdom: after the whole flow, `fetch` was called exactly twice with the two URLs, and `localStorage`/`sessionStorage` are empty.
- [ ] `App.test.tsx`: Landing link → Questionnaire Statement 1; `Volver al inicio` from the end screen; the invalid-id paths render not-found without fetch.
- [ ] CSS and docs as above.

## Verification Plan
- `CI=true ./init.sh` exits 0, with Vitest counts = previous 82 + the new tests (the replaced placeholder tests are counted out) and the build ok.
- `grep -rnE "localStorage|sessionStorage|indexedDB|document\.cookie" apps/web/src packages/core/src` → no match outside tests. `grep -rn "fetch(" apps/web/src --include=*.ts --include=*.tsx` → only `main.tsx` and tests.
- No E2E harness exists. Vitest plus the browser walk-through below cover the flow.
- **Scratch data**: reuse the `landing-election-picker` spec's Verification Plan script verbatim, outside the repo with `mktemp -d`. It creates Election 1 with 30 published Statements (fake provider, no key, no network), draft Election 2, `empty.db` and an `unmigrated.db`. Serve `landing.db` on port 8000 and `unmigrated.db` on 8002.
- **Browser** (Chrome via chrome-devtools MCP) at 375x812 and 1280x800, on the FastAPI-served build:
  - Port 8000: walk Scenarios 1–6 by clicking from the Landing, over all 30 Statements. Mix answers and skips, go back at least twice including from the end screen, and change one answer. Also reload the deep link (Answers lost, Statement 1 shown). Take an accessibility snapshot for Scenario 6, and do one full keyboard-only pass of at least 3 Statements.
  - `/elecciones/2/cuestionario`, `/elecciones/999/cuestionario` and `/elecciones/abc/cuestionario` on 8000, and `/elecciones/1/cuestionario` on 8002, for Scenario 7. On 8002 the expected 500 and Chrome's "Failed to load resource" line are the only console output allowed.
  - Scenario 8: list the network requests after finishing. Only the document, assets, `GET /api/v1/elections/1` and `GET /api/v1/dataset-versions/1` appear (a revisit may be cache-served), none after the Dataset Version load, none with a query string or body. Evaluate `localStorage.length`, `sessionStorage.length`, `document.cookie` and `location.href`.
  - Per width: no horizontal scroll (`scrollWidth <= innerWidth`), targets ≥ 48px, the console is clean, and there is no red/green. Stop the servers and delete the scratch dir.

## Evidence To Capture
- The `init.sh` step results and Vitest counts; the new test names; the grep results.
- Browser: the Chrome version, both widths, each scenario's result (answered/skipped counts on the end screen), the request list and the storage/cookie/URL values for Scenario 8, a keyboard and accessibility-tree summary. Record them in `feature_list.json` and `PROGRESS.md` only, never in `docs/validations/`.

## Validator Checklist
- [ ] Only the files above changed; there is no new npm dependency and no Python, `init.sh` or migration change (no overlap with `live-mode-url-refetch`).
- [ ] The API is reached only through the core client; the Dataset Version contract is checked in core; requests are exactly the two GETs.
- [ ] Answers are memory-only: no storage, URL or request carries them (browser network and storage check done).
- [ ] The radiogroup is native, keyboard-operable and labelled; no auto-advance; focus moves to the new Statement; no red/green and no party content.
- [ ] Scenarios 1–8 pass at 375px and desktop; the end screen is a placeholder for results only; there is no Important flag.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and the risks doc are updated as specified; `feature_list.json` and `PROGRESS.md` have evidence; there is no `docs/validations/`.
