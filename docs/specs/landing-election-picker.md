# Feature Implementation Spec: Landing page lets a Voter choose an Election

## Source Feature

- `id`: landing-election-picker (GitHub issue #31)
- `area`: web
- `depends_on`: public-dataset-api (`accepted`), web-client-skeleton (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Vitest + Testing Library: the page renders the published Election and the disclosure from a mocked API response"; "Manual check at 375px and desktop widths following DESIGN.md"; notes: neutral palette, no party colours)

## Goal

The placeholder home page becomes the Landing screen (`DESIGN.md` Core Screens 1). It lists the active Elections returned by `GET /api/v1/elections`, shows an "AI-generated" disclosure and a short methodology summary, and lets the Voter choose an Election. Choosing one navigates client-side to the Questionnaire route for that Election. Here that route shows a placeholder page; `questionnaire-answer-flow` replaces it. The page handles loading, an empty list and API errors. The HTTP client and the Election type live in `packages/core`, so `apps/web` stays a thin UI.

## Decisions

- **Router: `react-router@7.18.4`** (exact pin, `apps/web` dependency; brings `cookie` and `set-cookie-parser`, 3 packages in total). Why a dependency: `docs/technical-discovery.md` (Clients) already chose React Router, and the MVP needs about five routes (landing, Questionnaire, results, methodology, Share Link). A hand-written History API router would have to re-implement link click handling (modifier keys, middle click), `popstate` and params. Why 7 and not 8: `react-router@8.5.0` (latest) declares `engines.node >= 22.22.0`, above the repo's `>= 22.13` floor (`init.sh` `NODE_MIN_MINOR=13`). `7.18.4` (dist-tag `version-7`) needs Node `>= 20` and React `>= 18`. Use **declarative mode** (`BrowserRouter` in `main.tsx`, `<Routes>`/`<Route>`/`<Link>`/`useParams`; `MemoryRouter` in tests), not data mode or framework mode (no loaders and no Vite plugin). This was checked in a throwaway copy of the workspace outside the repo (Node 24.22, npm 11.19). `npm install --save-exact -w @ideology-app/web react-router@7.18.4` added 3 packages, and `npm run typecheck` (TS 7.0.2), `vitest run` and `vite build` all passed. The JS bundle grew from 219.9 kB to 259.7 kB (68.8 kB to 82.5 kB gzip).
- **SPA fallback compatibility.** The server already returns `index.html` for any `GET` path without a `.` in its last segment (`web.py`). Client route segments therefore never contain a `.`. Deep links and reloads of every route work with no Python change.
- **Routes** (Spanish slugs, like the UI; defined once in `apps/web/src/features/paths.ts`):
  - `/` → `LandingPage`.
  - `/elecciones/:electionId/cuestionario` → `QuestionnairePlaceholderPage`. `parseElectionId(raw)` accepts only `/^[1-9][0-9]{0,9}$/` with a value `<= 2147483647` (the API id bound) and otherwise returns `null`. A `null` renders `NotFoundPage`. `questionnairePath(id: number)` builds the path.
  - `*` → `NotFoundPage` (needed because the server fallback serves `index.html` for any unknown path).
  - The placeholder makes **no API call**. Loading the Questionnaire, unknown or `draft` ids and `no_published_dataset_version` all belong to `questionnaire-answer-flow`.
- **Archived Elections (risks-doc entry naming this feature): hide.** The Landing lists exactly what `GET /api/v1/elections` returns (only `active`, `date` desc then `id` desc), in that order, with no client-side filtering or re-sorting. Archived Elections stay reachable by id for Share Links (`share-link-open`, labelled historical per `docs/domain-model.md`). A "past elections" section is deferred to the feature that first sets `archived`. This spec updates that risks-doc entry (see Durable Documentation Impact).
- **Core API client** (`packages/core`, no DOM types: its `tsconfig` has `lib: ["ES2022"]`, `types: []`, so `fetch`/`Response` are structural types defined in core):
  - `src/domain/election.ts`: `ElectionStatus = "draft" | "active" | "archived"`. `Election { readonly id: number; country: string; type: string; date: string /* YYYY-MM-DD */; name: string; status: ElectionStatus; publishedDatasetVersionId: number | null }`, all fields readonly.
  - `src/application/public-api.ts`: the port `interface PublicApi { listElections(): Promise<readonly Election[]> }`.
  - `src/infrastructure/http/public-api-client.ts`:
    - Types: `HttpResponseLike { readonly ok: boolean; readonly status: number; json(): Promise<unknown> }` and `FetchLike = (url: string, init: { readonly method: "GET"; readonly headers: Readonly<Record<string, string>> }) => Promise<HttpResponseLike>`.
    - `class PublicApiError extends Error`: `name = "PublicApiError"`, `readonly kind: "network" | "http" | "invalid_response"`, `readonly status: number | null`.
    - `createPublicApiClient(options: { fetch: FetchLike; baseUrl?: string }): PublicApi`. Keep `options.fetch` in a local variable and call it as a plain function, never as `options.fetch(...)`, because `window.fetch` called as a method of another object throws "Illegal invocation".
  - `listElections()` behaviour:
    - It calls `${baseUrl}/api/v1/elections` (default `baseUrl` is `""`, and one trailing `/` is trimmed) with `{ method: "GET", headers: { Accept: "application/json" } }`. No query string, no body, nothing else in the request.
    - A rejected fetch → `PublicApiError("network", null)`.
    - `!ok` → `"http"` with the status. `json()` is not called, because a 500 is `text/plain`, as seen on an unmigrated DB.
    - A rejected `json()` or a body that breaks the contract → `"invalid_response"`. The message names the path, e.g. `elections[0].date must be YYYY-MM-DD`.
    - Contract checks: the body is an object with an `elections` array. Each item is an object with `id` a positive safe integer; `country`, `type` and `name` strings; `date` matching `^\d{4}-\d{2}-\d{2}$`; `status` one of the three values; and `published_dataset_version_id` `null` or a positive safe integer. Unknown keys are ignored, because `/api/v1` changes are additive.
    - Mapping snake_case → camelCase happens here once (as the risks doc settled).
  - `src/index.ts` re-exports these types plus `createPublicApiClient` and `PublicApiError`.
- **Web wiring.** `main.tsx` builds `createPublicApiClient({ fetch: (url, init) => window.fetch(url, init) })` and renders `<StrictMode><BrowserRouter><App api={api} /></BrowserRouter></StrictMode>`. `App({ api }: { api: PublicApi })` renders only `<Routes>`. Pages receive `api` as a prop; there is no context or state library. Components never call `fetch`. In production StrictMode does not double effects, so a Landing load makes exactly one API request.
- **Landing data hook** (`features/landing/useElections.ts`):
  - It returns `{ state: {kind: "loading"} | {kind: "loaded"; elections} | {kind: "error"}, retry }`.
  - The effect ignores a stale result through an `active` flag in its cleanup, so StrictMode in dev and unmounts are safe.
  - `retry` sets `loading` and fetches again. Errors are not logged to the console.
  - Every `PublicApiError` kind shows the same message.
- **An active Election with `publishedDatasetVersionId: null`** should not exist (`docs/domain-model.md`: active means it has a Published version). It is still listed as a link, and `questionnaire-answer-flow` handles the API's 404.

## Non-Goals

- No Questionnaire, Statement loading, Answers, `getElection`/Dataset Version client methods, Share Links or results. No methodology page or link (`methodology-page` adds the link; the summary only says the full methodology is coming).
- No archived or "past elections" section, no auto-redirect when there is a single Election, no client-side caching of the list across navigations, no focus or scroll management on route change, no `document.title` per route.
- No Python, API, `init.sh` or Node floor change. No new design tokens, logos or party names on this page.

## Job Story

When I open the site to compare party manifestos,
I want to see which Elections I can use, know that the content is AI-generated and how it was made,
so I can pick an Election and start the Questionnaire knowing what I am looking at.

## Users And Permissions

- Voter: anonymous and read-only. The only request is `GET /api/v1/elections`, with no Answers or voter data.

## Acceptance Scenarios

Exact Spanish copy (tests assert these strings; legal wording is provisional, see the risks doc):
- `<h1>` `Comparador de programas electorales`, then the intro `<p>` `Responde a una serie de afirmaciones y descubre qué partidos se acercan más a tus respuestas, según sus programas electorales.`
- Disclosure: `<section aria-labelledby="ai-disclosure-title">`, with `<h2 id="ai-disclosure-title">Contenido generado con IA</h2>` and `<p>Las afirmaciones y las posiciones de los partidos las ha generado automáticamente una inteligencia artificial a partir de sus programas electorales, sin revisión humana, y pueden contener errores. Cada posición se apoya en una cita literal del programa que podrás consultar. Esta herramienta no es una recomendación de voto.</p>`.
- Elections: a section with `<h2>Elecciones disponibles</h2>`. Loading: `<p role="status">Cargando elecciones…</p>`. Loaded: a `<ul>` with one `<li><Link>` per Election, showing `<span>{name}</span>{" "}<span>{date}</span>` (the literal space keeps the accessible name `Generales 2023 23 de julio de 2023`), with the date formatted by `Intl.DateTimeFormat("es-ES", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })` from the `YYYY-MM-DD` parts (`23 de julio de 2023`). Empty: `<p>Ahora mismo no hay elecciones disponibles. Vuelve a consultarlo más adelante.</p>`. Error: `<div role="alert"><p>No se han podido cargar las elecciones. Comprueba tu conexión e inténtalo de nuevo.</p><button type="button">Reintentar</button></div>`.
- Methodology summary: `<h2>Cómo funciona</h2>`, then `<p>Una inteligencia artificial lee los programas electorales de los partidos con representación en el Congreso, redacta afirmaciones neutrales y sitúa a cada partido ante cada afirmación con una cita literal como prueba.</p>`, `<p>Antes de publicar los datos, unas comprobaciones automáticas verifican, entre otras cosas, que cada cita aparece en el programa. Tus respuestas se quedan en tu navegador: no se envían ni se guardan en ningún servidor.</p>` and `<p>La explicación completa de la metodología se publicará próximamente.</p>` (no link).
- Order inside `<main>`: h1, intro, disclosure, Elections, methodology. The disclosure and methodology render in every list state.
- Placeholder: `<main><h1>Cuestionario</h1><p>El cuestionario de estas elecciones estará disponible muy pronto.</p><p><Link to="/">Volver al inicio</Link></p></main>`. Not found: `<h1>Página no encontrada</h1><p>Esta dirección no corresponde a ninguna página.</p>` plus the same back link.

### Scenario 1: published Election listed
Given the API returns Election 1 `Generales 2023` (2023-07-23, active, published version 1)
When the Voter opens `/`
Then the loading status shows first, then a link `Generales 2023 23 de julio de 2023` to `/elecciones/1/cuestionario`, with the disclosure and methodology visible. Exactly one request, `GET /api/v1/elections`, was made.

### Scenario 2: choose an Election, then Back
Given Scenario 1
When the Voter activates the link, then presses browser Back
Then the placeholder (`Cuestionario`) shows with no API request, the URL is `/elecciones/1/cuestionario`, and Back returns to `/` with the list shown again. `Volver al inicio` also returns to `/`.

### Scenario 3: deep link and unknown paths
Given the FastAPI-served build
When `/elecciones/1/cuestionario` is opened or reloaded directly
Then the placeholder renders and no API request is made. `/elecciones/abc/cuestionario`, `/elecciones/0/cuestionario`, `/elecciones/2147483648/cuestionario` and `/nada` render `Página no encontrada`.

### Scenario 4: no active Elections
Given the API returns `{"elections": []}` (or only `draft` Elections exist)
When `/` loads
Then the empty message shows, there is no list or link to the Questionnaire, and the disclosure and methodology are still shown.

### Scenario 5: API error and retry
Given the API answers 500 (or the fetch rejects, or the body breaks the contract)
When `/` loads
Then the alert and `Reintentar` show. Activating `Reintentar` shows loading again and, if the API now succeeds, the list.

### Scenario 6: several Elections keep API order
Given the API returns Elections 3 (2027-07-01) then 1 (2023-07-23)
When `/` loads
Then both links appear in that order, styled identically.

## Repository Research

### Files Inspected
- `apps/web/src/{main.tsx,app/App.tsx,features/home/HomePage.tsx,HomePage.test.tsx,ui/tokens.css,ui/global.css}`, `apps/web/{index.html,package.json,tsconfig.json,vite.config.ts}`: the composition root, tokens, the web test include `src/**/*.test.tsx` (jsdom).
- `packages/core/{package.json,tsconfig.json,vitest.config.ts,src/index.ts}`: no DOM lib; core tests are included as `test/**/*.test.ts` (node environment).
- Root `package.json` (tooling exact-pinned at the root; no `@testing-library/user-event`, so tests use `fireEvent`), `vitest.config.ts`, `tsconfig.base.json`, `.gitignore`, `.mcp.json` (chrome-devtools-mcp).
- `src/ideology_app/web.py` behaviour via `ARCHITECTURE.md` (Web Client) and the `web-client-skeleton` spec; `docs/specs/public-dataset-api.md` (contract, statuses, caching).
- `src/ideology_app/cli.py` (`_provider` seam), `src/ideology_app/llm/fake.py`, `tests/pipeline_fixtures.py`, `tests/pdf_factory.py`: what the scratch data steps reuse.
- `CONSTRAINTS.md`, `DESIGN.md`, `CONTEXT.md`, `docs/technical-discovery.md` (Clients), `docs/domain-model.md` (Election lifecycle), `docs/risks-and-open-questions.md`.

### Existing Patterns To Follow
- Layers `ui` → `features` → `core`. Business rules and contract checks live in core and are tested under Node. Pages render their own `<main>`.
- Exact pins and a committed lockfile; `init.sh` already runs `npm ci`, typecheck, Vitest and the build (no change).

### Current Gaps
- No router, no API client, no Election type, and no fetch guard for web tests.
- `LLM_PROVIDER=fake` from config has no canned responses, so `ideology pipeline run` alone fails. The scratch data steps patch `cli._provider` with `tests.pipeline_fixtures.fake_provider` (checked in a throwaway venv: run 1 passed, version 1 published, Election 1 `active`).

## Expected File Changes
- create `packages/core/src/domain/election.ts`, `src/application/public-api.ts`, `src/infrastructure/http/public-api-client.ts`, `test/infrastructure/public-api-client.test.ts`. Modify `src/index.ts`.
- create `apps/web/src/features/paths.ts`, `features/landing/{LandingPage.tsx,useElections.ts,format-date.ts,LandingPage.test.tsx}`, `features/questionnaire/QuestionnairePlaceholderPage.tsx`, `features/not-found/NotFoundPage.tsx`, `app/App.test.tsx`, `test/setup.ts`, `test/fetch-mocks.ts` (helper `jsonResponse(body, status = 200)` and `textResponse(status)`), `ui/components.css`.
- modify `apps/web/src/app/App.tsx`, `main.tsx` (imports `ui/components.css` too), `vite.config.ts` (`test.setupFiles: ["src/test/setup.ts"]`), `apps/web/package.json`, `package-lock.json`. Delete `apps/web/src/features/home/`.
- docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Design source: `DESIGN.md`. No new design artifact or token.
- Election link (`.election-link`): a block card with `surface` background, a 1px `border`, a 12px radius, min-height 48px and 16px padding. Text is `text`, no underline, name in 600 weight with the date below in `muted`. Use `muted` only on `surface`: it is 4.8:1 on white but 4.4:1 on `background`, which fails AA. Hover: border `primary`. `:focus-visible`: 3px `accent` outline (the amber is reserved for focus and Important).
- The disclosure is a `surface` card with a border and 12px radius. `Reintentar` uses `button-primary` (primary background, white text, 12px radius, min-height 48px). No party colours and no red/green anywhere.
- At 375px: single column, 16px gutter, no horizontal scroll. Desktop: 720px column.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update.
  - Web Client: React Router 7 declarative mode, the route table, `features/{landing,questionnaire,not-found,paths.ts}`, the `api` prop wiring and the web test setup that blocks `fetch`.
  - New core layers: `domain/election.ts`, the `application/public-api.ts` port, and `infrastructure/http/public-api-client.ts` with its error kinds and contract checks.
  - Add the feature to the "Current state after" line.
- `CONSTRAINTS.md`: update (Client-side Matching / Web Client Serving).
  - Client code MUST reach the public API only through the `packages/core` client; components MUST NOT call `fetch`.
  - Client route segments MUST NOT contain a `.`, because the SPA fallback answers such paths with 404.
  - Web tests MUST NOT reach the network: `src/test/setup.ts` stubs global `fetch` to throw, and tests inject a mocked `FetchLike`.
- `docs/risks-and-open-questions.md`: update.
  - Rewrite "Archived Elections" as: Settled (`landing-election-picker`): the Landing hides archived Elections (it lists only what `GET /api/v1/elections` returns). Open: nothing sets `archived` yet, and whether a "past elections" section is added is decided by the feature that archives.
  - Toolchain: React Router is pinned at 7.18.4 because 8.x needs Node >= 22.22. Move to 8 only together with a deliberate Node floor bump in `init.sh`.
  - "Electoral and legal exposure": the Landing disclosure and methodology copy are provisional and part of the legal check.
- `AGENTS.md`, `DESIGN.md`, `docs/technical-discovery.md`: not needed (startup path unchanged, no new tokens, React Router already chosen).

## Implementation Plan
1. Core: the Election type, the port, the client, and its tests.
2. Add `react-router@7.18.4` with `npm install --save-exact -w @ideology-app/web react-router@7.18.4`, then check that `npm ci` works from a clean `node_modules`.
3. Web: `paths.ts`, the pages, the hook, the CSS, the App/main wiring and the test setup. Delete `home/`.
4. Web tests, then `CI=true ./init.sh`, then the browser validation, then the docs.

## Implementation Tasks
- [ ] Core tests (`public-api-client.test.ts`): the request is exactly one call with URL `/api/v1/elections` and `{method: "GET", headers: {Accept: "application/json"}}`; `baseUrl` `"http://h/"` gives `http://h/api/v1/elections`; snake→camel mapping keeps order; `null` published id; extra keys ignored; rejected fetch → `network`; 500 → `http`, status 500, `json` not called; rejected `json()` → `invalid_response`; table of bad bodies (non-object, missing or non-array `elections`, item not an object, `id` 0 / 1.5 / `"1"`, `name` 7, `date` `23/07/2023`, `status` `closed`, published id `"1"`) → `invalid_response`, with the message naming the field.
- [ ] `src/test/setup.ts`: `beforeEach` `vi.stubGlobal("fetch", ...)` throwing `network access is blocked in web tests`; `afterEach` `cleanup()` and `vi.unstubAllGlobals()`.
- [ ] `LandingPage.test.tsx` (render `<MemoryRouter initialEntries={["/"]}><App api={createPublicApiClient({ fetch: mockFetch })} /></MemoryRouter>`): Scenario 1 (loading on a pending promise, then the link, href, date text, disclosure heading and text, methodology, one fetch call); Scenario 4; Scenario 5 (500, rejected fetch and an invalid body each give the alert; retry → list); Scenario 6 order; no link whose name matches `/metodología/i`; the disclosure is present in the loading, empty and error states.
- [ ] `App.test.tsx`: clicking the Election link shows `Cuestionario`, and `Volver al inicio` returns to the list; the deep link `/elecciones/1/cuestionario` renders with the mock fetch never called; the four not-found paths of Scenario 3, with no fetch.
- [ ] CSS per Visual Design Impact. Docs per Durable Documentation Impact.

## Verification Plan
- `CI=true ./init.sh` exits 0, with the Vitest count = 41 match-score tests + the new core and web tests (the 2 old HomePage tests are removed), and the build ok. `npm ci` from a clean `node_modules` succeeds. `grep -rn "fetch(" apps/web/src --include=*.tsx --include=*.ts` matches only `main.tsx` and the tests.
- No E2E harness exists. Vitest with `MemoryRouter` plus the browser walk-through cover the flow.
- **Scratch data** (one shell, from the repo root after `./init.sh`; everything lives outside the repo; `.venv/bin/python` has pytest, so the test helpers import):
  ```sh
  REPO=$PWD; SCRATCH=$(mktemp -d /tmp/landing-XXXXXX); export SOURCE_FILES_DIR=$SCRATCH/source_files
  cat > $SCRATCH/make_pdfs.py <<'EOF'
  import sys; from pathlib import Path
  sys.path.insert(0, sys.argv[1])
  from tests.pdf_factory import make_text_pdf
  from tests.pipeline_fixtures import PAGES
  out = Path(sys.argv[2])
  (out / "alfa.pdf").write_bytes(make_text_pdf(PAGES[1]))
  (out / "beta.pdf").write_bytes(make_text_pdf(PAGES[2]))
  EOF
  cat > $SCRATCH/run_fake_pipeline.py <<'EOF'
  import sys
  sys.path.insert(0, sys.argv[1])
  from tests.pipeline_fixtures import fake_provider
  from ideology_app import cli
  cli._provider = fake_provider  # FakeProvider with canned responses; no key, no network
  cli.main(["pipeline", "run", "--election", sys.argv[2]])
  EOF
  export DATABASE_URL=sqlite:///$SCRATCH/landing.db; I=$REPO/.venv/bin/ideology
  $I db upgrade
  $I election create --country ES --type general --date 2023-07-23 --name "Generales 2023"
  $I party add --election 1 --name "Partido Alfa" --short-name PA
  $I party add --election 1 --name "Bloque Beta" --short-name BB
  $REPO/.venv/bin/python -I $SCRATCH/make_pdfs.py $REPO $SCRATCH
  $I source add --party 1 --file $SCRATCH/alfa.pdf; $I source add --party 2 --file $SCRATCH/beta.pdf
  $REPO/.venv/bin/python -I $SCRATCH/run_fake_pipeline.py $REPO 1   # "Published dataset version 1 for election 1"
  $I election create --country ES --type general --date 2027-07-01 --name "Generales 2027 (borrador)"  # stays draft
  $I election list    # 1 active, 2 draft
  DATABASE_URL=sqlite:///$SCRATCH/empty.db $I db upgrade   # empty state
  touch $SCRATCH/unmigrated.db                              # error state: API answers 500
  ```
  Then start three servers from the repo root: `DATABASE_URL=sqlite:///$SCRATCH/landing.db .venv/bin/uvicorn ideology_app.main:app --port 8000`, and the same with `empty.db` on 8001 and `unmigrated.db` on 8002.
- **Browser** (Chrome via chrome-devtools MCP), at 375x812 and 1280x800:
  - Port 8000, Scenarios 1–3 and 6 as a user:
    - Only `Generales 2023` is listed; the draft is not.
    - Click the link, then Back, then `Volver al inicio`. Reload the deep link and open the not-found paths.
    - Keyboard: Tab to the link and Enter, and check that the focus ring is visible.
  - Port 8001: Scenario 4.
  - Port 8002: Scenario 5. `GET /api/v1/elections` 500 and Chrome's own "Failed to load resource" line are expected; nothing else may appear.
  - For each page check:
    - no horizontal scroll at 375px (`scrollWidth <= innerWidth`), a 720px column on desktop, `DESIGN.md` colours, tap targets of at least 48px;
    - the console is clean (apart from the expected 500 line on port 8002);
    - every request is same-origin and succeeds: the document, JS, CSS and exactly one `GET /api/v1/elections` per Landing load (a Back may be served from the HTTP cache), with no query string, no body and no request on the placeholder.
  - Stop the servers and delete `$SCRATCH` afterwards.

## Evidence To Capture
- The `init.sh` step results and test counts; the names of the new tests; the `npm ci` result; `react-router` and its 2 deps in the lockfile.
- The scratch-data command outputs (published line, `election list`).
- Browser: the Chrome version, widths, each scenario's result, the console and the request list per step, plus the Back and deep-link results. Record them in `feature_list.json` and `PROGRESS.md`; never in `docs/validations/`.

## Validator Checklist
- [ ] Only `react-router@7.18.4` (exact) was added; `npm ci` is clean; no change to Python, `init.sh` or the Node floor.
- [ ] The API client and types are in `packages/core` with no DOM types; components never call `fetch`; web tests block global `fetch`.
- [ ] Copy, routes, the not-found handling and archived/draft hiding match this spec; there is no methodology link.
- [ ] The browser walk-through was done on the FastAPI build at 375px and desktop, covering the list, empty, error, navigation, Back and deep link; no voter data was sent.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and the risks doc are updated as specified; there is no `docs/validations/`.
