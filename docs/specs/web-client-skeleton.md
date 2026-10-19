# Feature Implementation Spec: React web client skeleton with shared core package

## Source Feature

- `id`: web-client-skeleton (GitHub issue #29)
- `area`: web
- `depends_on`: bootstrap-app-skeleton (`accepted`), match-score-engine (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: npm workspaces from the committed lockfile, type-check, Vitest, build; match-score in `packages/core` with its scenarios, `src/ideology_app/static/js/match-score.js` removed; browser check at 375px and desktop with no console errors)

## Goal

FastAPI serves a React + TypeScript single-page client built with Vite. Its only page is a neutral placeholder home page that follows `DESIGN.md`. Client code is split into npm workspaces as `docs/technical-discovery.md` (Clients) describes: `packages/core` holds pure TypeScript with no React, DOM or platform APIs, and `apps/web` holds the React app. The Match Score engine moves into `packages/core` as TypeScript, with exactly the same behaviour and every existing scenario ported to Vitest. `./init.sh` installs the workspaces from the committed lockfile, type-checks, runs Vitest and builds `apps/web`.

## Decisions

- **Where FastAPI finds the build (risk 1).** New setting `config.web_dist_dir() -> Path`: `$WEB_DIST_DIR` (trimmed; blank means unset), else `Path("apps/web/dist")` relative to the current directory. This follows the `DATABASE_URL` / `SOURCE_FILES_DIR` pattern, so `uvicorn` is started from the repo root. `create_app(database_url=None, web_dist_dir=None)` resolves the path once (`Path(...).resolve()`). Tests pass a `tmp_path` dist. A later container sets `WEB_DIST_DIR`. The build lives outside the Python package, so setuptools package-data is no longer an issue. `src/ideology_app/static/` is deleted.
- **Serving rules** (new module `src/ideology_app/web.py`, `web_router(dist_dir) -> APIRouter` with one `GET /{path:path}` route, `include_in_schema=False`). It is included **last** in `create_app`, after the API router and `/health`, so all existing routes match first. For each request, in this order:
  1. `path` is `api`, starts with `api/`, is `health` or starts with `health/` → `404 {"detail": "Not Found"}` (`HTTPException(404)`), so unknown API paths keep FastAPI's default body.
  2. `dist_dir/index.html` is not a file (not built yet) → `404 {"detail": "Not Found"}`. This is checked on every request, so building while uvicorn runs needs no restart. `create_app` logs one warning (`logging.getLogger("ideology_app.web")`) when it is missing at startup: `web client not built: <dir>/index.html not found; run ./init.sh`.
  3. `(dist_dir / path).resolve()` is a file inside `dist_dir` (`is_relative_to`; this blocks `..`, encoded `%2e%2e` and symlinks out of dist) → `FileResponse`. Paths under `assets/` (Vite's content-hashed files) get `Cache-Control: public, max-age=31536000, immutable`. Every other file gets `no-cache`.
  4. The last path segment contains a `.` (a missing file such as `/assets/x.js` or `/favicon.ico`) → `404 {"detail": "Not Found"}`, never HTML in place of a script.
  5. Otherwise this is the **SPA fallback**: return `index.html` with `Cache-Control: no-cache`. `/` (empty path) also gets `index.html`. This feature has no client routes, but the fallback is settled now so later routing features don't have to touch the server. The query string is ignored.
  - GET only. A non-GET request to a path that only the catch-all matches gets `405` (Starlette partial match). The existing `405` on `/api/v1/elections` is unchanged.
  - Accepted consequence: with a build present, `/docs` and `/redoc` return the SPA's `index.html` (200), not FastAPI docs, since only `/api/docs` exists. The existing `test_public_api.py` assertions that these return 404 still hold, because those tests run without a dist. `tests/conftest.py` must unset `WEB_DIST_DIR` so a developer's environment can't change that.
- **Access logs and query strings (risk 3): deferred to the first deployment feature** (not yet in `feature_list.json`). This feature adds no query parameters and sends no request with voter data (the page makes no API call). A new CONSTRAINTS rule makes clients keep Answers out of every request. The risk entry stays, renamed to name deployment only.
- **match-score port (risk 2).** `packages/core/src/domain/match-score.ts` is a line-by-line port of `match-score.js`. It keeps the same exports, the same constants, the same runtime validation (the input comes later from an untrusted URL fragment, so the types do not replace the checks), the same error classes and messages, the same `String(statementId)` keying, the same Map iteration order, `options.lowCoverageThreshold ?? 5`, `{ partyId, ...score }` key order, `null` for zero shared Statements, and the accepted Low quirks (`null` threshold falls back to 5; `NaN`/`Infinity`/`""` ids accepted). It has no imports and uses no browser or network globals. Types: `ScaleValue = -2|-1|0|1|2`, `StatementId = number|string`, `Answer {statementId; value: ScaleValue|typeof SKIP; important?: boolean|undefined}`, `PositionInput {statementId; value: ScaleValue|typeof NO_STANCE}`, `PartyInput<P> {partyId: P; positions: readonly PositionInput[]}`, `MatchScoreOptions {lowCoverageThreshold?: number|undefined}`, `MatchScoreResult {matchScore: number|null; sharedStatementCount: number; lowCoverage: boolean}`. `computeMatchScores<P>` returns `(MatchScoreResult & {partyId: P})[]`. Constants are `as const` literals. All 41 `node:test` cases move to `packages/core/test/domain/match-score.test.ts` with the same `describe`/`test` titles and the same assertions (`strictEqual`→`toBe`, `deepStrictEqual`→`toStrictEqual`, `assert.throws(fn, {name, message})` → a local helper that catches and checks `err.name` and the regex). Invalid-input tests pass values through a local `untyped<T>(v: unknown): T` cast. The old `js-test` init step and `tests/js/` are removed, and Vitest replaces them.
- **Node floor.** Vite 8 / Vitest 5 need Node `>= 22.12` and jsdom 29 needs `^22.13 || >= 24`, so `init.sh` adds `NODE_MIN_MINOR=13`. `step_node` fails when major < 22, or when major = 22 and minor < 13, with `Node.js >= 22.13 is required (found vX)`. The "not found" message becomes `Node.js >= 22.13 is required for the web client (node not found on PATH)`. Root `package.json` gets `"engines": {"node": ">=22.13"}`.
- **Dependencies** (exact pins, no other packages; versions checked in a throwaway workspace, where `npm ci`, `tsc` on both workspaces, `vitest run` and `vite build` all passed on Node 24.22 / npm 11.19):
  - `apps/web` dependencies: `react@19.3.1`, `react-dom@19.3.1`, `@ideology-app/core@*` (workspace link).
  - Root devDependencies (all tooling, installed with `npm i --save-exact -D` at the root): `typescript@7.0.2` (the native port; it ships a `tsc` binary), `vitest@5.0.5`, `vite@8.3.4`, `@vitejs/plugin-react@6.1.2`, `@testing-library/react@16.3.3`, `@testing-library/dom@10.4.2` (its peer), `jsdom@29.1.1`, `@types/react@19.3.0`, `@types/react-dom@19.3.0`. All tooling goes at the root because, in the experiment, a workspace-level `jsdom` was installed under `apps/web/node_modules`, and the hoisted `vitest` then failed with `Cannot find package 'jsdom'`.
  - `packages/core`: none. No `@testing-library/jest-dom`, React Router, CSS framework or web-font package (React Router arrives with the first routed feature). npm 11 warns that `fsevents` has unapproved install scripts. Leave it unapproved (it is optional, and nothing needs it).

## Non-Goals

- No Election data, no API calls from the client, no Voter flow, no Questionnaire, no Share Link codec, no HTTP adapter in `core` yet.
- No React Router, no routes beyond the fallback, no Expo / `apps/mobile` (post-MVP).
- No Dockerfile or deployment, no access-log change, no CORS.
- No change to the Matching Rule, the public API contract or any Python behaviour apart from serving the build.
- No lint/format tooling (ESLint, Prettier).

## Job Story

When I open the app's address in my browser,
I want a calm, neutral page served by the same server as the API,
so later features can build the Voter flow on a working client, tested shared core and one start command.

## Users And Permissions

- Voter: sees the placeholder page. No input and nothing is sent.
- Developer/agent: runs `./init.sh`, starts uvicorn, optional `npm run dev -w @ideology-app/web` (Vite proxies `/api` and `/health` to `127.0.0.1:8000`).

## Acceptance Scenarios

### Scenario 1: gate builds and tests the client
Given a clean checkout with Node >= 22.13 and npm
When `CI=true ./init.sh` runs
Then the steps `node`, `install`, `pytest`, `web-install` (`npm ci`), `web-typecheck`, `web-test`, `web-build` all print `==>` and pass, `apps/web/dist/index.html` exists, and the script exits 0 without starting a server. A type error, a failing Vitest test or a build error makes it print `FAILED: <step>` and exit 1. A changed `package.json` without an updated lockfile fails `web-install`.

### Scenario 2: match-score semantics kept
Given `packages/core/test/domain/match-score.test.ts`
When `npm test` runs
Then the same 41 cases as the old `node --test` run pass under the same titles, `src/ideology_app/static/` and `tests/js/` no longer exist, and `packages/core/src/index.ts` re-exports the engine.

### Scenario 3: FastAPI serves the build
Given a built dist
When a client GETs `/`, `/assets/<hashed>.js` and `/some/deep/path?x=1`
Then `/` and the deep path return `index.html` (`text/html`, `no-cache`), the asset returns its bytes with the immutable Cache-Control, and `/assets/missing.js` and `/favicon.ico` return `404 {"detail": "Not Found"}`.

### Scenario 4: API and health keep precedence
Given a built dist
When a client GETs `/health`, `/api/openapi.json`, `/api/docs`, `/api/v1/elections`, `/api/v1/nope`, `/api`, `/health/x`
Then the first four behave exactly as before, the last three return `404 {"detail": "Not Found"}`, and the OpenAPI paths are unchanged (no catch-all path).

### Scenario 5: missing build and traversal
Given `WEB_DIST_DIR` pointing at a missing directory, or a directory without `index.html`
When `/` is requested
Then it returns `404 {"detail": "Not Found"}`, `/health` still returns 200, and the startup warning is logged. Given a file next to dist, `GET /%2e%2e/secret.txt` and `GET /..%2fsecret.txt` never return its content.

### Scenario 6: placeholder page in a real browser
Given `./init.sh` passed and `.venv/bin/uvicorn ideology_app.main:app --port 8000` runs from the repo root
When the page `http://127.0.0.1:8000/` is opened in Chrome (DevTools MCP) at 375x812 and at 1280x800, then `/anything` is opened and Back is pressed
Then the page shows the `<h1>` and paragraph in a single column with a 16px gutter at 375px (no horizontal scroll) and a centred column of at most 720px on desktop, with `DESIGN.md` background/text colours and the Inter/system-ui stack. `/anything` shows the same page. The console has no errors or warnings. Every request is same-origin and succeeds (document, JS, CSS; no favicon request, no font or CDN request), and no request carries a query string or body.

## Repository Research

### Files Inspected
- `init.sh`, `tests/test_init_script.py`: `run_step` subshell pattern, `step_node`, `step_js_test`. The tests extract `NODE_MIN_MAJOR` and `step_node` by line pattern.
- `src/ideology_app/main.py`: `create_app`, `/health` registered after the router, docs under `/api/`.
- `src/ideology_app/config.py` (pattern for env settings), `tests/conftest.py` (unsets `DATABASE_URL`, chdir to `tmp_path`).
- `src/ideology_app/static/js/match-score.js`, `tests/js/match-score.test.js` (41 cases), `docs/specs/match-score-engine.md`.
- `tests/test_public_api.py`: asserts `/docs`, `/redoc`, `/openapi.json` 404, unknown `/api/v1/nope` → `{"detail": "Not Found"}`, OpenAPI `/api/` paths equal to the router's.
- `package.json` (`{"private": true, "type": "module"}`), `.gitignore`, `pyproject.toml`, `.mcp.json` (chrome-devtools-mcp), `DESIGN.md`, `docs/technical-discovery.md` (Clients), `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`.
- `src/ideology_app/models.py:328,376`, `src/ideology_app/api/schemas.py:13`: comments naming `match-score.js`.

### Existing Patterns To Follow
- Env settings: trimmed, blank = unset, default relative to the current directory.
- Init steps are `step_<name>` functions plus a `run_step` line, kept compatible with bash 3.2.
- `filterwarnings = ["error"]`. Logging is fine, `warnings.warn` is not.

### Current Gaps
- No npm dependencies, lockfile, TypeScript or bundler. Nothing mounts static files.

## Technical Approach

Layout (TypeScript sources consumed directly; `packages/core` has no build step and exports `./src/index.ts`):
- Root: `package.json` (`name: ideology-app`, private, `type: module`, `workspaces: ["packages/core", "apps/web"]`, engines, scripts `typecheck` = `npm run typecheck --workspaces`, `test` = `vitest run`, `build` = `npm run build -w @ideology-app/web`), `package-lock.json`, `tsconfig.base.json` (`target`/`lib` ES2022, `module` ESNext, `moduleResolution` bundler, `strict`, `noUncheckedIndexedAccess`, `isolatedModules`, `verbatimModuleSyntax`, `skipLibCheck`, `noEmit`), `vitest.config.ts` (`test.projects: ["packages/core", "apps/web"]`). Never set `passWithNoTests`, so zero tests fails.
- `packages/core`: `package.json` (`@ideology-app/core`, `exports`, script `typecheck: tsc -p tsconfig.json`), `tsconfig.json` (extends base, `lib: ["ES2022"]`, `types: []`, so DOM globals fail type-checking), `vitest.config.ts` (`environment: "node"`, include `test/**/*.test.ts`), `src/index.ts`, `src/domain/match-score.ts`, `test/domain/match-score.test.ts`.
- `apps/web`: `package.json` (`@ideology-app/web`, scripts `dev: vite`, `build: vite build`, `typecheck: tsc -p tsconfig.json`), `tsconfig.json` (adds `DOM`, `DOM.Iterable`, `jsx: react-jsx`, `types: ["vite/client"]`; includes `src`, `vite.config.ts`), `vite.config.ts` (`defineConfig` from `vitest/config`; react plugin; `server.proxy` for `/api` and `/health` → `http://127.0.0.1:8000`; `test.environment: "jsdom"`, include `src/**/*.test.tsx`), `index.html` (`lang="es"`, viewport meta, `<title>Comparador de programas electorales</title>`, `<link rel="icon" href="data:,">` to suppress the favicon request), `src/main.tsx` (`createRoot` + `StrictMode`, imports `ui/global.css`), `src/app/App.tsx` (composition root rendering `HomePage`), `src/features/home/HomePage.tsx`, `src/features/home/HomePage.test.tsx`, `src/ui/tokens.css` (`DESIGN.md` colours, radii, spacing, type sizes as CSS custom properties), `src/ui/global.css` (body background/text, font stack, `main` max-width 720px, 16px gutter, centred).
- Page copy (exact, Spanish, no party names, no colours beyond tokens, nothing interactive): `<main>` containing `<h1>Comparador de programas electorales</h1>` and `<p>Esta aplicación está en construcción. Pronto podrás responder a una serie de afirmaciones generadas con IA y ver qué partidos se acercan más a tus respuestas.</p>`. Body text uses `text` on `background`, not `muted`.
- Python: `config.web_dist_dir()`, `web.py` as in Decisions, `main.create_app` includes `web_router` after `/health`.

## Expected File Changes
- create: the root `package-lock.json`, `tsconfig.base.json`, `vitest.config.ts`. Create everything under `packages/core/` and `apps/web/` listed above. Create `src/ideology_app/web.py`, `tests/test_web_client.py`.
- modify: `package.json`, `.gitignore` (`node_modules/`, `apps/web/dist/`, `*.tsbuildinfo`), `init.sh`, `tests/test_init_script.py` (extract `NODE_MIN_MINOR` too; cases 22.12.0 fails, 22.13.0 and 24.1.0 pass), `src/ideology_app/config.py`, `src/ideology_app/main.py`, `tests/conftest.py` (`delenv("WEB_DIST_DIR")`), `tests/test_config*.py` or `tests/test_web_client.py` for the setting, comments in `models.py` / `api/schemas.py` (`match-score.js` → `packages/core` match-score).
- delete: `src/ideology_app/static/` (whole tree), `tests/js/` (whole tree).
- docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Design source: `DESIGN.md` (tokens, Layout, Typography, Accessibility Baseline). No new design artifact.
- One screen (placeholder). States: built vs not built (404 JSON, no UI). No web font is loaded (Inter only if installed locally), so there are no external requests.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update. Rewrite "Client-side Matching" for `packages/core/src/domain/match-score.ts` (same exports/semantics, Vitest). Add a "Web Client" section: workspaces, layers and dependency direction (`ui` → `features` → `core`), `web.py` serving rules, `WEB_DIST_DIR`, the dev proxy command. Add the catch-all to Runtime Surface. Update the Verification Gate (new steps, Node 22.13, `js-test` removed). Drop the old root `package.json` sentence.
- `CONSTRAINTS.md`: update "Client-side Matching":
  - The Match Score is computed only by `packages/core/src/domain/match-score.ts` in the client, and no endpoint receives Answers.
  - `packages/core` never imports React, DOM or platform APIs, and `match-score.ts` has no imports or globals.
  - Client code MUST NOT put Answers in any request (path, query, body, headers); only the URL fragment carries them (reason: invariant plus access logs).
  - npm dependencies are exact-pinned, installed with `npm ci` from the committed lockfile, and any new runtime dependency is justified in its spec.
  - New server routes MUST be registered before `web_router`, and the fallback MUST NOT serve `/api/` or `/health` paths.
  - Update the `engine_value` reason to the new name.
- `AGENTS.md`: not needed (the startup path is still `./init.sh`).
- `docs/risks-and-open-questions.md`: replace "Shipping the web build" with a Settled entry (the rules above), plus an open item: the container image (deployment feature, not yet listed) builds with `npm ci && npm run build` and sets `WEB_DIST_DIR`. Replace the porting entry with a Settled entry. Rename the query-string risk to deployment only and mention the new client rule. Update Toolchain (Node ≥ 22.13, npm lockfile committed, no Python lockfile). Reword the JS-engine Low finding to the TS module. Add a Low entry: TypeScript 7 (native port) may not be supported by tools that need the TS compiler API (typescript-eslint, Expo); pin `typescript@6` if a later feature needs one.
- `docs/technical-discovery.md`, `DESIGN.md`: not needed (the layout matches; no new tokens).

## Implementation Plan
1. Scaffold the workspaces and configs, install the exact pins with `npm install` once to produce the lockfile, then confirm `npm ci` from a clean `node_modules`.
2. Port match-score and its tests. Before deleting the JS file, run a scratch (uncommitted) differential check: about 10,000 random inputs, valid and invalid, through both modules, comparing results and error name/message. Then delete `static/` and `tests/js/`.
3. Build the placeholder page and its Testing Library test.
4. Add `config.web_dist_dir`, `web.py`, the `main.py` wiring, `conftest.py` and the pytest tests.
5. Update `init.sh` and its tests, run `CI=true ./init.sh`, then the browser check, then the docs.

## Implementation Tasks
- [ ] Root `package.json`, `tsconfig.base.json`, `vitest.config.ts`, `.gitignore`. Workspace `package.json`/`tsconfig.json`/config files. `package-lock.json` committed.
- [ ] `packages/core/src/domain/match-score.ts`, `src/index.ts`, `test/domain/match-score.test.ts` (41 cases, same titles).
- [ ] Differential check recorded as evidence. Delete `src/ideology_app/static/`, `tests/js/`.
- [ ] `apps/web` `index.html`, `main.tsx`, `App.tsx`, `HomePage.tsx` + test, `tokens.css`, `global.css`.
- [ ] `config.web_dist_dir()`, `web.py`, `create_app(web_dist_dir=)`, conftest `delenv`.
- [ ] `tests/test_web_client.py` covering Scenarios 3-5 (tmp dist with `index.html`, `assets/app-abc123.js`, a sibling `secret.txt`; caplog for the warning; env default/blank/set).
- [ ] `init.sh`: `NODE_MIN_MINOR`, `step_web_install` (fails if `npm` is not on PATH; `npm ci --no-audit --no-fund`), `step_web_typecheck` (`npm run typecheck`), `step_web_test` (`npm test`), `step_web_build` (`npm run build`). Remove `step_js_test`. Final message prints the uvicorn command, `http://127.0.0.1:8000/`, and the optional Vite dev command.
- [ ] `tests/test_init_script.py` updates. Docs as listed.

## Verification Plan
- `CI=true ./init.sh` exits 0 (Scenario 1). Break a type, a Vitest assertion and an import in a scratch copy: each gives `FAILED: web-typecheck` / `web-test` / `web-build`, exit 1.
- `npm test` output: 41 match-score tests plus the web test pass. `npm ls --workspaces` shows `@ideology-app/core` linked.
- `.venv/bin/python -m pytest tests/test_web_client.py tests/test_public_api.py tests/test_init_script.py` passes. The full pytest run stays green.
- Browser (Scenario 6) with Chrome DevTools MCP: list console messages and network requests at each width, take a snapshot of the page structure, and check `document.documentElement.scrollWidth <= innerWidth` at 375px.
- No E2E harness exists. The browser walk-through plus pytest serving tests cover this feature's flow.

## Evidence To Capture
- The `init.sh` step list, test counts (pytest, Vitest), Node/npm versions, the dist file list.
- The result of the differential check (number of cases, 0 mismatches).
- curl or TestClient results for Scenarios 3-5.
- Browser: Chrome version, widths 375 and 1280, console 0 errors/warnings, the request list with statuses, the fallback and Back result.

## Validator Checklist
- [ ] Only the dependencies listed above, exact-pinned, and the lockfile is committed. `npm ci` works from clean.
- [ ] Test titles and count match the old `node:test` file, and the TS source still has the same checks and messages (diff against `git show HEAD:src/ideology_app/static/js/match-score.js`).
- [ ] `/api/*`, `/health`, OpenAPI and the existing API tests are unchanged. Traversal is blocked. A missing dist gives 404 and a warning.
- [ ] The browser check was done at 375px and desktop, with a clean console and no failed or external requests.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and the risks doc are updated as specified. No `docs/validations/`.
- [ ] No Election data, API call, router or Voter flow was added.
