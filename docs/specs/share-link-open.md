# Feature Implementation Spec: Opening a Share Link reproduces the result

## Source Feature

- `id`: share-link-open (GitHub issue #49)
- `area`: sharing
- `depends_on`: share-link-create, results-breakdown-evidence (both `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Browser test: the shared URL renders identical scores"; "A superseded version shows the notice; a malformed link shows a friendly error")

## Goal

Opening `/resultados#v1-<id>-<answers>` shows, read-only, the same ranking and per-Statement breakdown the Voter saw on the end screen, computed in the browser from the fragment and the pinned Dataset Version, through the same `toMatchScoreAnswers` → `rankParties` → `buildBreakdown` path. If the Election has since published a newer version, a notice says so and offers the current Questionnaire. Empty, malformed, unsupported, truncated or unknown links and API failures show friendly Spanish messages. The answers never leave the fragment.

## Decisions

- **Core, application layer: `packages/core/src/application/open-share-link.ts`** (port `PublicApi` only; no React/DOM). `openShareLink(api: PublicApi, fragment: string): Promise<OpenShareLinkResult>`:
  1. `fragment === ""` → `{ kind: "missing" }`, no request.
  2. `decodeShareLink(fragment)`; a `ShareLinkError` → `{ kind: "invalid", reason: error.kind }`, no request.
  3. `api.getDatasetVersion(link.datasetVersionId)`: `PublicApiError` http 404 → `{ kind: "not_found" }`; any other error, or `datasetVersion.id !== link.datasetVersionId` → `{ kind: "error" }`.
  4. `restoreQuestionnaire(link, datasetVersion.statements.map(s => s.id))`; `statement_count_mismatch` → `{ kind: "invalid", reason }` (one request made, no second one).
  5. `api.getElection(datasetVersion.electionId)`: 404 → `not_found`; any other error, or `election.id !== datasetVersion.electionId` → `error`.
  6. `{ kind: "ready", election, datasetVersion, state, results: buildResults(datasetVersion, state), versionStatus, questionnaireAvailable }`.
  Any other thrown error (e.g. an engine `RangeError`) → `error`. Nothing is logged. It never returns partial data. Requests carry only the Dataset Version id and Election id (path parameters), never Answers.
- **Core, domain: `packages/core/src/domain/results.ts`.** `buildResults(version: Pick<DatasetVersion, "statements" | "parties">, state: QuestionnaireState) → { ranking, breakdown, hasScores }`: `answers = toMatchScoreAnswers(state)`, `ranking = rankParties(answers, parties)`, `breakdown = buildBreakdown(statements, parties, answers, ranking.map(p => p.partyId))`, `hasScores = ranking.some(p => p.matchScore !== null)`. `QuestionnaireFlow` switches its two `useMemo`s to one `useMemo(() => buildResults(datasetVersion, state), …)` and `EndScreen`'s `hasScores` comes from it, so both screens share one code path (identical scores by construction). No other scoring or ordering code.
- **Superseded detection (same file or `domain/shared-result.ts`):** `sharedVersionStatus(election, datasetVersionId)`: `publishedDatasetVersionId === datasetVersionId` → `current`; `null` → `no_current`; otherwise `superseded`. `questionnaireAvailable = election.status === "active" && publishedDatasetVersionId !== null`. Hence:
  - archived (or draft) Election: the result opens normally (the API serves Elections and published/superseded versions by id at any status); if superseded the notice shows **without** a Questionnaire link; no "Haz tú el cuestionario" link.
  - no published version (`no_current`): result shown, no notice, no Questionnaire link.
- **Web hook `apps/web/src/features/share/useSharedResult.ts`:** `useSharedResult(api, fragment) → { state: loading | OpenShareLinkResult, retry }`, the `useQuestionnaireData` pattern (`active` flag, `attempt` counter, rejection → `error`). `retry` repeats `openShareLink` (decode and both requests).
- **Reading the fragment:** `SharedResultsPage({ api })` reads `useLocation().hash` (React Router; works in `MemoryRouter` tests) and renders `<SharedResultLoader key={hash} api={api} fragment={hash.startsWith("#") ? hash.slice(1) : hash} />`, so the fragment is read once per mount; pasting a different link into the address bar remounts. No `window.location`, `history.*`, storage, `decodeURIComponent` or logging.
- **Address bar: the fragment stays.** The page never rewrites the URL (no `replaceState`): the Voter opened it on purpose, it is already in their history, and keeping it makes reload, bookmarks and Back work and lets the address bar be the copy source. Hence **no share button** on this page; the note says to save the link.
- **Read-only.** No `Revisar mis respuestas`, `Volver a la última afirmación` or editing. Answers cannot be changed (that would be a new Questionnaire).
- **Page frame:** `<main>`, `<h1 tabIndex={-1}>Resultado compartido</h1>` in every state, focused on mount; `document.title = "Resultado compartido · Comparador de programas electorales"` set on mount and restored on unmount (MethodologyPage pattern, export `SHARED_RESULTS_TITLE`). Focus does not move when loading finishes.
- **Ready state, in order** (impersonal Spanish; the opener may not be the person who answered):
  1. `<p className="questionnaire__election">{election.name}</p>`.
  2. Superseded only: `<section className="card shared-notice" aria-labelledby="superseded-title">` with `<h2 id="superseded-title">Hay un cuestionario más reciente</h2>`, `<p>Este resultado se calculó con una versión anterior del cuestionario de estas elecciones y se muestra tal como era. El cuestionario actual puede tener otras afirmaciones y otras posiciones.</p>` and, when `questionnaireAvailable`, `<Link className="button-primary" to={questionnairePath(election.id)}>Hacer el cuestionario actual</Link>`. Neutral card, not amber, not an alert.
  3. `<h2 id="results-title">Afinidad con cada partido</h2>` (ResultsRanking's list name).
  4. `Se respondieron {answered} de {total} afirmaciones y se saltaron {skipped}.` and `Se marcaron k afirmaciones como importantes.` / `Se marcó 1 afirmación como importante.` / `No se marcó ninguna afirmación como importante.` (from `summarize`).
  5. `hasScores`: `<p>Afinidad entre las respuestas de este enlace y el programa de cada partido, de mayor a menor.</p>` + `<ResultsRanking ranking={results.ranking} />`; otherwise `<p>Las respuestas de este enlace no permiten calcular la afinidad: ninguna afirmación respondida tiene la posición de algún partido.</p>` (only a hand-made link can reach it).
  6. `<p>Esto no es una recomendación de voto: solo compara estas respuestas con lo que dicen los programas, según una inteligencia artificial que puede equivocarse.</p>`, then `<Link className="text-link" to={METHODOLOGY_PATH}>Cómo se calcula la afinidad</Link>` (same tab: Back restores the fragment, nothing is lost).
  7. Not superseded and `questionnaireAvailable`: `<p><Link className="button-primary" to={questionnairePath(election.id)}>Haz tú el cuestionario</Link></p>`.
  8. `<ResultsBreakdown rows={results.breakdown} answerOwner="link" />`.
  9. `<p className="questionnaire__note">Este resultado se calcula en tu navegador a partir del propio enlace: las respuestas van tras el símbolo «#» y no se envían a ningún servidor. Para volver a verlo, guarda el enlace.</p>`, then `Volver al inicio` (`back-link`).
- **`ResultsBreakdown` gets an optional `answerOwner?: "voter" | "link"` (default `voter`, current copy unchanged).** `link`: intro starts `La respuesta del enlace y la posición de cada partido…` (rest identical) and the answer line reads `Respuesta del enlace: <strong>…</strong>`. Markup, order and labels otherwise identical.
- **Non-ready states** (h1 stays; each ends with `Volver al inicio`; no partial data):
  - `loading`: `<p role="status">Cargando resultado…</p>`.
  - `missing`: `Este enlace no contiene ningún resultado. Comprueba que lo has copiado entero.`
  - `invalid` `malformed` and `statement_count_mismatch`: `Este enlace no es válido o está incompleto. Comprueba que lo has copiado entero o pide que te lo envíen de nuevo.`
  - `invalid` `unsupported_version`: `Este enlace se creó con una versión más reciente de esta web. Recarga la página para abrirlo.`
  - `not_found`: `No encontramos el cuestionario de este enlace. Puede que ya no esté disponible.`
  - `error`: `<div role="alert"><p>No se ha podido cargar el resultado. Comprueba tu conexión e inténtalo de nuevo.</p><button className="button-primary">Reintentar</button></div>`.
- **End-screen loss note (revisited):** when `hasScores`, `RESULTS_NOTE` gains `Para volver a verlo más tarde, copia antes el enlace de «Comparte tu resultado».`; without scores the current sentence stays (no share section there). No leave warning is added.
- **Methodology (CONSTRAINTS.md "Public Copy"):** append to the share paragraph: `Al abrir el enlace se ve el mismo resultado, calculado de nuevo en el navegador con la misma versión del cuestionario; si después se ha publicado una más reciente, se avisa.` Update `SHARE_TEXT` in its test.
- No API, Python, migration (head stays 0009) or dependency change.

## Non-Goals

- Serving stored PDFs or a "document replaced" notice for Evidence (risk entry deferred, below). Mobile deep links / universal links.
- A share button, editing answers, comparing two links, or merging a link into a new Questionnaire.
- Any change to the codec format, ranking rules or the API.

## Job Story

When someone sends me a result link (or I saved my own),
I want it to open the same ranking and evidence it showed originally,
so I can trust and discuss it, and take the current questionnaire if it has changed.

## Users And Permissions

- Anyone holding the link (anonymous): reads the result. Two GET requests, no Answers in them.

## Acceptance Scenarios

Vitest fixtures: `datasetVersionJson({ statements: 6 })` (id 1, Statements 101–106), `electionJson()` (pointer 1, `active`).

1. **Same result.** Given `/resultados#v1-1-dddddA`, when the page loads, then the requests are exactly `/api/v1/dataset-versions/1`, `/api/v1/elections/1`; the ranking rows and breakdown equal what the end screen shows after answering the same way (test: drive `QuestionnaireFlow` to the end with the same answers, collect row texts, compare with the shared page's); no notice; `Haz tú el cuestionario` links to `/elecciones/1/cuestionario`.
2. **Superseded.** Given the Election's pointer is 2 and the link pins 1, then the notice `Hay un cuestionario más reciente` with `Hacer el cuestionario actual` shows above the unchanged result, and no second CTA.
3. **Archived / no published.** Given `status: "archived"` and pointer 2: notice without a link, result shown, no CTA. Given pointer `null`: no notice, no CTA, result shown.
4. **Missing / malformed / unsupported / truncated.** `/resultados`, `/resultados#` → missing copy, 0 requests. `#v1-1-dddddf`, `#garbage`, `#V1-1-a`, a 1025-character fragment → invalid copy, 0 requests. `#v2-1-a` → unsupported copy, 0 requests. `#v1-1-ddddd` (5 letters) and `#v1-1-ddddddd` (7) → invalid copy after exactly 1 request.
5. **Unknown version.** Dataset Version 404 → not-found copy, 1 request. Election 404 → not-found copy.
6. **Errors and retry.** A rejected fetch, a 500 or an invalid body on either request → alert + `Reintentar`; clicking it repeats both requests and then shows the result. No `console.error`/`console.warn` calls (spy).
7. **Privacy.** No requested URL contains the payload letters or `#`; storage is empty; the URL is not rewritten (`MemoryRouter` location still has the hash).
8. **Frame.** h1 focused on mount, `document.title` set and restored; no `Copiar enlace`, `Revisar mis respuestas`.
9. **End screen + methodology copy.** The loss note includes the new sentence when scores exist and not otherwise; the methodology paragraph has the appended sentence.
10. **Core.** `openShareLink` unit tests cover each branch with a fake `PublicApi`; `buildResults` equals the hand-composed pipeline; `sharedVersionStatus` three cases.

## Repository Research

### Files Inspected

- `AGENTS.md`, `ARCHITECTURE.md` (Client-side Matching, Public API, Public API Client, Web Client), `CONSTRAINTS.md` (Client-side Matching, Public Copy), `CONTEXT.md`, `DESIGN.md`, `docs/domain-model.md` (superseded scenario), `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`, `docs/specs/{share-link-create,results-breakdown-evidence,results-ranking}.md`, `.agents/skills/github-flow/references/practical-notes.md`.
- `packages/core/src/index.ts`, `infrastructure/share-link/share-link-codec.ts`, `domain/{questionnaire,ranking,breakdown}.ts` (by ARCHITECTURE), `application/public-api.ts`.
- `apps/web/src/{app/App.tsx,app/App.test.tsx,features/paths.ts,features/share/SharedResultsPage.tsx,features/questionnaire/{QuestionnairePage,QuestionnaireFlow,useQuestionnaireData}.tsx,features/results/{ResultsRanking,ResultsBreakdown}.tsx,features/methodology/MethodologyPage.tsx,features/not-found/NotFoundPage.tsx,features/landing/format-date.ts,test/{fetch-mocks,setup}.ts}`, `tests/pipeline_fixtures.py`, `src/ideology_app/cli.py` (`_provider`).

### Existing Patterns To Follow

- Pure core + thin React; pages get `api` as a prop; loader hook with `active` flag and `retry`; Spanish copy; tests render `App` in `MemoryRouter` with a mocked `FetchLike` and query by role.

### Current Gaps

- `/resultados` is a static placeholder that takes no `api`. `App.test.tsx` and `ShareResults.test.tsx` Scenario 6 assert the placeholder; both must be replaced by the new behaviour.

## Expected File Changes

- `packages/core/src/domain/results.ts`, `packages/core/src/application/open-share-link.ts` (+ `sharedVersionStatus` in one of them): create; `packages/core/src/index.ts`: exports.
- `packages/core/test/domain/results.test.ts`, `packages/core/test/application/open-share-link.test.ts`: create.
- `apps/web/src/features/share/SharedResultsPage.tsx`: rewrite; `useSharedResult.ts`, `SharedResultsPage.test.tsx`: create.
- `apps/web/src/app/App.tsx`: pass `api` to `SharedResultsPage`; `App.test.tsx`, `features/share/ShareResults.test.tsx`: replace the placeholder tests.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: `buildResults` + loss note; `QuestionnairePage.test.tsx`: note assertion.
- `apps/web/src/features/results/ResultsBreakdown.tsx` (+ test): `answerOwner` prop.
- `apps/web/src/features/methodology/MethodologyPage.tsx` and test: one sentence.
- `apps/web/src/ui/components.css`: `.shared-notice` (card spacing only, if `.card` is not enough).
- Docs below, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact

- UI: yes, `DESIGN.md`. Screens: `/resultados` (loading, ready, superseded, each error), end-screen note. Reuses `.card`, `.button-primary`, `.text-link`, `.back-link`, `.questionnaire__note`, the ranking and breakdown styles unchanged. Notice is a neutral card (amber stays reserved for Important/focus); every Party identical. 48px targets; no horizontal scroll at 375px. No new design artifact.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Core: `buildResults`, `openShareLink`, `sharedVersionStatus`, tests. Web Client: the `/resultados` route description (replaces "placeholder until share-link-open"), `useSharedResult`, the `answerOwner` prop, the loss-note change, test list. Remove "A later Share Link route can render…".
- `CONSTRAINTS.md` "Client-side Matching": add: a Share Link MUST be opened only through `openShareLink` and rendered only from its `ready` result (no partial result); the shared page MUST NOT rewrite, strip or copy the fragment (no `history.*`, storage). Extend the `rankParties` rule: shared and end-screen results MUST both come from `buildResults`.
- `DESIGN.md`: Core Screens: add `5. Shared result: read-only ranking + breakdown, superseded notice, link errors`.
- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`: not needed (terms and the superseded scenario already match).
- `docs/risks-and-open-questions.md` (implementer edits):
  1. Memory-only entry: reword: since `share-link-open` a copied Share Link reopens the result at `/resultados` (fragment kept in the address bar, so reload works there); the end screen itself is still memory-only and its loss note now points to `Comparte tu resultado`; no leave warning.
  2. Archived entry (line "Settled (`landing-election-picker`)"): append that `share-link-open` opens archived Elections' links (result shown; no Questionnaire offered for non-`active` Elections, notice without a link). Keep "Open: nothing sets `archived` yet…".
  3. "Evidence links point at a URL's current content": keep, add `share-link-open` makes old versions reachable but deliberately adds no replaced-document notice; still no owner (stored-PDF serving out of scope).
  4. iOS/Android Share Links: unchanged (left open).
  5. "Share Links expose answers…": add that the opened link also stays in the opener's browser history (the page keeps the fragment by design).

## Implementation Plan

1. Core: `buildResults`, `sharedVersionStatus`, `openShareLink`, exports, tests.
2. `QuestionnaireFlow` refactor to `buildResults` (existing tests must pass unchanged), loss note.
3. `ResultsBreakdown` `answerOwner`; `useSharedResult`; `SharedResultsPage`; `App.tsx`; CSS.
4. Web tests (Scenarios 1–9), replace placeholder tests; methodology copy.
5. `CI=true ./init.sh`, greps, browser walk-through, docs, evidence.

## Implementation Tasks

- [ ] `open-share-link.test.ts`: every branch of the Decisions list, request counts per branch, mismatched ids → `error`, engine throw → `error`.
- [ ] `results.test.ts`: deep-equal to the hand-composed pipeline for a seeded set of states; `hasScores` false when all skipped.
- [ ] `SharedResultsPage.test.tsx`: Scenarios 1–8 (Scenario 1 compares against the end screen rendered through `App`).
- [ ] Update `App.test.tsx`, `ShareResults.test.tsx` Scenario 6, `QuestionnairePage.test.tsx` note, `MethodologyPage.test.tsx`, `ResultsBreakdown.test.tsx`.
- [ ] Docs and risks edits as listed.

## Verification Plan

- `CI=true ./init.sh` exits 0: pytest unchanged (966), Vitest 283 + new tests, typecheck and build ok.
- Greps (no matches outside tests unless stated): `grep -rnE "location\.hash|window\.location|history\.(push|replace)State|localStorage|sessionStorage|document\.cookie|console\." apps/web/src packages/core/src` (only `ShareResults.tsx`'s existing `window.location.origin`); `grep -rn "fetch(" apps/web/src --include=*.tsx --include=*.ts` → only `main.tsx` and tests; `grep -rn "decodeShareLink" apps/web/src packages/core/src` → only the codec, `open-share-link.ts`, index and tests.
- No E2E harness exists; Vitest + the browser walk cover the flow.
- **Scratch server** (practical-notes "Checking A Worktree's Build In A Browser"): scratch dir under the session scratchpad, outside the repo; `<worktree>/.venv/bin/ideology db upgrade`, then a Python script run with the worktree venv that builds the PDFs with `tests/pdf_factory.py`, registers Election (set `active`), `Partido Alfa`/`Bloque Beta` and sources via the CLI, and runs `pipeline run` with `ideology_app.cli._provider` patched to `tests.pipeline_fixtures.fake_provider()` (no key, no network). Temporary `.claude/launch.json` entry `tmp-share-link-open` with `/usr/bin/env WEB_DIST_DIR=<worktree>/apps/web/dist DATABASE_URL=sqlite:///<scratch>/check.db <worktree>/.venv/bin/uvicorn ideology_app.main:app --port 8041`. Never port 8000. Remove the entry and scratch dir afterwards; `git status` shows only feature changes.
- **Real browser, mandatory**, at 375x812 and 1280x800:
  - A (identical): answer the Questionnaire with ratings, skips and Important flags; `Copiar enlace` (the built-in browser denies the clipboard, so take the URL from the fallback field); note the ranking rows (names, `%`, shared counts, badges) and a few breakdown rows; open the URL in a new page; the same rows, percentages and breakdown answers appear; open a Position and its Evidence link works; `Haz tú el cuestionario` opens the Questionnaire. Reload the shared page: same result.
  - B (superseded): run the pipeline a second time (FakeProvider) so a new version is published; reopen the A link → notice + `Hacer el cuestionario actual` (opens the new version); scores unchanged. Optionally set the Election `archived` in the scratch DB → notice without a link.
  - C (errors): `/resultados`, `#v1-<D>-zzz`, `#v9-1-a`, the A link with its last letter removed, `#v1-999999-<letters>` (404). Each shows its copy; network shows 0, 0, 0, 1 and 1 requests respectively. Network error: open `/resultados` (missing copy), stop uvicorn, paste a valid fragment into the address bar (a fragment-only navigation: no page load, the loader remounts) → alert; restart uvicorn, `Reintentar` → the result.
  - Throughout: the network list shows only `GET /resultados`, assets, `/api/v1/dataset-versions/<D>`, `/api/v1/elections/<E>`; none contains the answers; the uvicorn access log shows `GET /resultados` with no fragment; storage and cookies empty; console clean; no horizontal scroll at 375px; focus lands on the h1; tab title correct.

## Evidence To Capture

- `init.sh` counts, new test names, grep results; browser name/version, widths, Runs A–C with the URL used, request lists, the access-log line, console state and cleanup. Only in `feature_list.json` and `PROGRESS.md`; never `docs/validations/`.

## Validator Checklist

- [ ] Scope matches Expected File Changes; no API/Python/migration/dependency change.
- [ ] Shared and end-screen results both come from `buildResults`; scores identical in Vitest and in the browser.
- [ ] Superseded/archived/no-current behaviour as specified; every error state has its copy, no partial data, nothing logged, `Reintentar` works.
- [ ] Fragment read only through `useLocation`, decoded only by `decodeShareLink`, never rewritten or sent; requests carry only ids.
- [ ] Loss note, methodology sentence and `answerOwner` copy updated with tests.
- [ ] Browser Runs A–C pass at 375px and desktop; console clean.
- [ ] ARCHITECTURE, CONSTRAINTS, DESIGN and the five risks-doc edits made; evidence recorded.
