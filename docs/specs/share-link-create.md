# Feature Implementation Spec: Voter copies a Share Link of their result

## Source Feature

- `id`: share-link-create (GitHub issue #46)
- `area`: sharing
- `depends_on`: results-ranking (`accepted`). Also builds on `questionnaire-important-flag`, `match-score-engine` and `methodology-page` (all `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Unit test: the encode/decode round-trip is lossless, including skip and Important"; "The answers appear only after `#`". Notes: version the encoding format; update the MethodologyPage privacy paragraph to present tense.)

## Goal

On the results end screen, the Voter can copy a Share Link: an `https` URL whose fragment (`#…`) carries the Dataset Version id and every Answer, including skips and Important flags. The link is built in the browser by a pure, versioned codec in `packages/core`. Copying uses the Clipboard API. When the clipboard is unavailable or denied, the link is shown in a read-only field to copy by hand. A note says that nothing is stored on any server and that anyone with the link can see the answers. No request ever carries the Answers. The methodology page's privacy paragraph moves to the present tense. Opening the link and rendering the result is `share-link-open`. Until then the link's path shows a short placeholder page.

## Decisions

- **URL shape.** `<origin>/resultados#v1-<datasetVersionId>-<answers>`, e.g. `https://example.org/resultados#v1-7-ddddddASssss`.
  - Path: `SHARED_RESULTS_PATH = "/resultados"` in `apps/web/src/features/paths.ts`. One segment, no `.` (CONSTRAINTS.md "Web Client Serving"), served by the existing SPA fallback. The path carries no data: the Election is not in the URL, because `share-link-open` gets it from the Dataset Version's `electionId`.
  - Only the fragment carries data, and browsers never send it in a request. The origin comes from `window.location.origin` at click time.
- **Format v1 (the payload after `#`).** `v1-<id>-<answers>`:
  - `v1`: the format version marker.
  - `<id>`: the Dataset Version id, `^[1-9][0-9]{0,9}$` and ≤ 2147483647 (the API id bound, the same rule as `parseElectionId`).
  - `<answers>`: one letter per Statement, in the Dataset Version's Statement order (API `position` order, which the client contract checks is strictly increasing): `-2 → a`, `-1 → b`, `0 → c`, `1 → d`, `2 → e`, skip `→ s`. The upper-case letter means the Statement is marked Important (`A`–`E`, `S`; a flagged skip keeps its flag, as `toMatchScoreAnswers` does). The length is 1..500.
  - Why it is keyed by position and not by Statement id: one character per Statement (about 35 for a 30-Statement Questionnaire, plus the prefix). This is safe because Dataset Versions are immutable, so the version id fixes the order. Every character is RFC 3986 "unreserved", so nothing is percent-encoded. The format is case-sensitive, which is fine because browsers keep fragment case.
  - Truncation safety: a cut link has fewer letters than the version has Statements, so the binding step reports `statement_count_mismatch` and never shows a partial result. No checksum is needed.
- **Versioning policy.** `SHARE_LINK_FORMAT_VERSION = 1`. Any change to the payload layout uses a new marker (`v2`…). Decoders keep accepting every earlier version, because old links pin old Dataset Versions, which stay readable. A well-formed but unknown marker (`v` followed by 1–3 digits, not `1`, then `-`) is the error `unsupported_version`, so `share-link-open` can tell "link from a newer app" apart from garbage.
- **Codec (core): `packages/core/src/infrastructure/share-link/share-link-codec.ts`.** This is where `docs/technical-discovery.md` puts the "Share Link codec". It is pure: no React, DOM, `URL` or storage; string operations and regexes only. Exports:
  - `SHARE_LINK_FORMAT_VERSION`, `MAX_SHARE_LINK_STATEMENTS = 500`.
  - `interface ShareLinkEntry { readonly value: AnswerValue; readonly important: boolean }`.
  - `interface ShareLink { readonly formatVersion: 1; readonly datasetVersionId: number; readonly entries: readonly ShareLinkEntry[] }`.
  - `class ShareLinkError extends Error { kind: "malformed" | "unsupported_version" | "statement_count_mismatch" }`. The messages name the problem, e.g. `share link: answers contain an invalid character`.
  - `encodeShareLink(state: QuestionnaireState, datasetVersionId: number): string` returns the payload without `#`. It throws `RangeError` when the id is invalid, when `statementIds` is empty or has more than 500 ids, or when a Statement has no Answer. The share button only exists on the end screen, where every Statement has an Answer.
  - `decodeShareLink(fragment: string): ShareLink` takes the text after `#` (the caller passes `location.hash.slice(1)`) and is strict, because the fragment is untrusted input:
    - longer than 1024 characters: `malformed`, checked before any regex;
    - `^v([1-9][0-9]{0,2})-` with a marker other than `1`: `unsupported_version`;
    - otherwise it must match `^v1-([1-9][0-9]{0,9})-([a-esA-ES]{1,500})$` exactly, with the id ≤ 2147483647, else `malformed`;
    - it never calls `decodeURIComponent`, JSON or `eval`;
    - a leading `#`, `%`, whitespace, a trailing `-` and `V1` are all `malformed`.
    
    Values come from a fixed lookup table, so they are valid by construction. The match-score engine's runtime checks stay as the second line of defence in `share-link-open` (decoded Answers go through `computeMatchScores`). The codec does not duplicate them.
  - `restoreQuestionnaire(link: ShareLink, statementIds: readonly number[]): QuestionnaireState`. It throws `statement_count_mismatch` when the lengths differ. Otherwise it returns `{ statementIds: [...], currentIndex: statementIds.length /* end screen */, answers: Map, important: Set }`. It exists here so that the round-trip is tested end to end. `share-link-open` calls it after loading the version.
  - Exported from `packages/core/src/index.ts`.
- **Share UI (web): `apps/web/src/features/share/ShareResults.tsx`.** Props: `{ datasetVersionId: number; state: QuestionnaireState }`. It renders a `<section className="share" aria-labelledby="share-title">` containing:
  - `<h3 id="share-title">Comparte tu resultado</h3>` and the intro `<p>Copia un enlace que lleva tus respuestas para compartir este resultado.</p>`;
  - `<button type="button" className="button-secondary">Copiar enlace</button>`;
  - `<p role="status" className="share__status">`, always rendered (empty when idle) so the live region exists before it changes;
  - in the fallback state only: `<label for="share-url">Enlace para compartir</label>` and `<input id="share-url" className="share__field" type="text" readOnly value={url}>`;
  - the note `<p className="questionnaire__note">No se guarda nada en ningún servidor: tus respuestas van dentro del propio enlace, tras el símbolo «#», y el navegador no envía esa parte de la dirección. Cualquiera que tenga el enlace podrá ver tus respuestas.</p>`.
- **On click**, the component builds `url = sharedResultsUrl(window.location.origin, encodeShareLink(state, datasetVersionId))`, where `sharedResultsUrl(origin, payload) = origin + SHARED_RESULTS_PATH + "#" + payload` lives in `paths.ts`. Then:
  - if `navigator.clipboard?.writeText` exists, it awaits it inside `try`. On success the status is `Enlace copiado.`, the field is hidden and focus stays on the button.
  - if it is missing (an insecure context, an old browser) or it rejects or throws (permission denied): the status is `No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:`, the field shows the URL, gets focus, and its text is selected (`select()`; `onFocus` also selects all).
  - It never uses `document.execCommand`, the Web Share API, `location.hash`, `history.*` or storage. It changes nothing in the current URL and sends no request.
- **End screen wiring (additive, minimal diff, because `results-breakdown-evidence` is editing the same screen on another branch).** In `QuestionnaireFlow.tsx`:
  - pass `datasetVersionId={datasetVersion.id}` to `EndScreen` (one prop);
  - add one line right before the `questionnaire__controls` div: `{hasScores ? <ShareResults datasetVersionId={datasetVersionId} state={state} /> : null}`. The all-skipped prompt has nothing to share. The ranking, the breakdown slot after it, and the other copy (including `RESULTS_NOTE`) stay as they are.
  - No other edit to the flow.
- **`/resultados` until `share-link-open`.** Add the route `SHARED_RESULTS_PATH` → `features/share/SharedResultsPage.tsx`, a static placeholder:
  - `<main>`, `<h1 tabIndex={-1}>Resultado compartido</h1>` (focused on mount, like the methodology page);
  - `<p>Todavía no se pueden abrir resultados compartidos. Puedes responder el cuestionario tú mismo desde el inicio.</p>`;
  - a `back-link` to `Volver al inicio`.
  
  It never reads `location.hash`, takes no `api` and makes no request. `share-link-open` replaces its body (keep the file and route name). Why not leave it on `NotFoundPage`: a freshly copied link would say "Página no encontrada", which reads as a bug.
- **Methodology copy (CONSTRAINTS.md "Public Copy").** Replace the second privacy paragraph with: `Puedes compartir tu resultado con un enlace que lleva tus respuestas al final de la dirección, tras el símbolo «#». Los navegadores no envían esa parte de la dirección al servidor y el enlace no se guarda en ningún sitio: quien lo tenga puede ver tus respuestas.` It makes no claim about reopening, because that is not built (`share-link-open` adds that sentence). The first paragraph is unchanged.

## Non-Goals

- Opening or decoding a link in the UI, rendering a shared ranking or breakdown, the superseded-version notice and the friendly malformed-link error (`share-link-open`).
- The per-Statement breakdown (`results-breakdown-evidence`). Any redesign of the ranking or the end screen.
- The Web Share API, QR codes, URL shorteners, social buttons or analytics. Any server, API, Python or dependency change. Putting the link into the current page URL or history.
- Mobile deep links (Later / Not MVP).

## Job Story

When I have my results,
I want to copy a link that contains my answers without creating an account or sending them anywhere,
so I can share or keep my result and trust that nothing about me was stored.

## Users And Permissions

- Voter (anonymous): copies the link. No new request. The clipboard write is triggered by the user's click.

## Acceptance Scenarios

Vitest fixture: `datasetVersionJson({ statements: 6 })` (version id 1, Statement ids 101–106).

### Scenario 1: copy succeeds
Given Statements 1–5 are rated `De acuerdo`, Statement 6 is rated `Muy en desacuerdo` and marked Important, and the results are shown
When the Voter activates `Copiar enlace` with a working clipboard
Then `writeText` is called once with `${origin}/resultados#v1-1-dddddA`, the status reads `Enlace copiado.`, no field is shown, and no request is made (the fetch mock still has 2 calls).

### Scenario 2: skip and Important round-trip
Given Statements 1 and 3–5 are rated `De acuerdo`, Statement 2 is skipped and marked Important, and Statement 6 is skipped without a flag
Then the payload is `v1-1-dSddds`, and `restoreQuestionnaire(decodeShareLink(payload), ids)` gives the same `answers` and `important` as the live state and the same `rankParties` output.

### Scenario 3: clipboard missing or denied
Given `navigator.clipboard` is undefined, or `writeText` rejects with `NotAllowedError`
When the Voter activates `Copiar enlace`
Then the status reads the fallback sentence, and a read-only field labelled `Enlace para compartir` holds the full URL, has focus and has its whole text selected.

### Scenario 4: nothing to share
Given every Statement was skipped
Then the prompt shows and there is no `Comparte tu resultado` section.

### Scenario 5: the no-storage note
Then the share section shows the note, and the storage, cookies and current URL are unchanged after copying.

### Scenario 6: placeholder route
Given the URL `/resultados#v1-1-dddddA`
Then `Resultado compartido` shows with the placeholder text and `Volver al inicio`, and no request is made.

### Scenario 7: methodology copy
Then the `Tus respuestas` region contains the new paragraph and no text containing `se usará`.

### Scenario 8: strict decode
Given each malformed input from the Implementation Tasks
Then `decodeShareLink` throws `ShareLinkError` with the listed kind and never returns partial data.

## Repository Research

### Files Inspected
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md` (Share button, Core Screens 3), `ARCHITECTURE.md` (Client-side Matching, Web Client), `CONSTRAINTS.md` (Client-side Matching, Web Client Serving, Public Copy), `PROGRESS.md`, `feature_list.json` (this feature, `share-link-open`, `results-breakdown-evidence`), `docs/domain-model.md`, `docs/build-brief.md`, `docs/technical-discovery.md` (codec in `src/infrastructure`; fragment-only), `docs/risks-and-open-questions.md`.
- `docs/specs/{results-ranking,methodology-page,match-score-engine,questionnaire-answer-flow,questionnaire-important-flag,landing-election-picker}.md`, `.agents/skills/github-flow/references/parallel-merges.md`.
- `packages/core/src/{index.ts,domain/questionnaire.ts,domain/match-score.ts,domain/ranking.ts}`, `packages/core/test/**`.
- `apps/web/src/{app/App.tsx,app/App.test.tsx,features/paths.ts,features/questionnaire/QuestionnaireFlow.tsx,features/results/ResultsRanking.tsx,features/methodology/MethodologyPage.tsx,features/methodology/MethodologyPage.test.tsx,features/not-found/NotFoundPage.tsx,test/setup.ts,test/fetch-mocks.ts,ui/components.css}`, `apps/web/tsconfig.json` (the DOM lib types `navigator.clipboard`).
- The `results-breakdown-evidence` branch was not inspected (it has no commits beyond `main`).

### Existing Patterns To Follow
- Pure core plus a thin React layer. Route constants live in `paths.ts`. Web tests render `App` in `MemoryRouter` with a mocked `FetchLike` and query by role. Spanish copy. Focus is managed with refs.

### Current Gaps
- No codec, no share UI, no `/resultados` route. jsdom has no `navigator.clipboard`, so tests define it with `Object.defineProperty(navigator, "clipboard", { value, configurable: true })` and delete it in `afterEach` (`vi.unstubAllGlobals` does not restore it).

## Expected File Changes
- `packages/core/src/infrastructure/share-link/share-link-codec.ts`: create. `packages/core/src/index.ts`: modify (exports).
- `packages/core/test/infrastructure/share-link-codec.test.ts`: create.
- `apps/web/src/features/share/ShareResults.tsx`, `ShareResults.test.tsx`, `SharedResultsPage.tsx`: create.
- `apps/web/src/features/paths.ts`: modify (`SHARED_RESULTS_PATH`, `sharedResultsUrl`). `apps/web/src/app/App.tsx`: one import and one route. `App.test.tsx`: add a placeholder deep-link test.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: modify (one prop and one line, as above). `QuestionnairePage.test.tsx`: add Scenarios 1, 3 and 4 at page level, or put them in `ShareResults.test.tsx` with the end screen rendered through `App`.
- `apps/web/src/features/methodology/MethodologyPage.tsx` and `.test.tsx`: modify (paragraph and assertion).
- `apps/web/src/ui/components.css`: append one commented block (`.share`, `.share__status`, `.share__field`).
- Docs, as listed below. `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Source: `DESIGN.md` ("Share button": copies the link, with a short note that nothing is stored). No new token.
- `.share`: a `.card`-like block (surface, 1px border, 12px radius, 16px padding, `--space-lg` bottom margin), not amber and not party-coloured. `.share__field`: `width: 100%`, min-height 48px, 1px `--color-border`, 6px radius, 16px font (no iOS zoom), the standard amber `:focus-visible` outline (add `.share__field:focus-visible` next to `input:focus-visible` if it is not already covered). `.share__status`: body text and an empty margin when idle. At 375px the long URL scrolls inside the field and never widens the page.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update.
  - Core: the codec module, its exports, format v1, the versioning policy.
  - Web Client: `features/share/` (`ShareResults` on the end screen when scores exist; clipboard with a field fallback), the `/resultados` placeholder route in the route list, and the tests list.
- `CONSTRAINTS.md` "Client-side Matching": add these rules.
  - Share Link payloads MUST be produced only by `encodeShareLink` and read only by `decodeShareLink`.
  - Any layout change MUST use a new format marker, and decoders MUST keep accepting earlier versions. Reason: old links stay valid for old Dataset Versions.
  - Client code MUST NOT write a Share Link or Answers into the current page URL, history or storage. Only the clipboard or the on-screen fallback field may hold them. Reason: shared devices and history must not keep answers.
- `DESIGN.md`: update the "Share button" line: `Copiar enlace`; if copying fails, the link is shown in a read-only field; the note says nothing is stored and that anyone with the link sees the answers.
- `docs/risks-and-open-questions.md`: the implementer makes these edits (this spec itself changes only this file):
  - replace "The Share Link encoding format and its versioning." with `Settled (share-link-create): /resultados#v1-<datasetVersionId>-<one letter per Statement in position order: a–e = −2..2, s = skip, upper case = Important>; new layouts get a new marker and decoders keep old ones; a truncated link fails the Statement-count check.`;
  - delete the "Owed by `share-link-create`: switch the methodology page's privacy paragraph…" entry (done);
  - reword the memory-only entry: since `share-link-create` the Voter can copy a Share Link (clipboard or a fallback field; nothing stored), but until `share-link-open` it opens a placeholder page, so a reload, Back or leaving still loses the results. Reopening is owned by `share-link-open`, which should then also revisit the end screen's loss note;
  - add under Risks: **Share Links expose answers to whoever holds them** (and to clipboard managers or chat history). Mitigation: the share note says so. The server never sees the fragment;
  - "iOS and Android app … how Share Links open": unchanged. The link is a plain `https` URL on `/resultados`, so the format does not constrain it.
- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/technical-discovery.md`: not needed (the terms and the codec location already match).

## Implementation Plan
1. Core codec and tests; exports.
2. `paths.ts`, the placeholder page and route, `ShareResults`, the end-screen wiring, CSS, web tests.
3. The methodology paragraph and test.
4. `CI=true ./init.sh`, greps, the browser walk-through, then the docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks
- [ ] `share-link-codec.test.ts`:
  - all 12 symbols, each value with and without Important;
  - a flagged skip `S`;
  - 1 and 500 Statements; id 1 and 2147483647;
  - for random states (seeded loop, about 200 cases, ≤ 60 Statements), `restoreQuestionnaire(decode(encode(s)))` equals the input `answers`/`important`, and `rankParties` gives deep-equal output;
  - encode throws `RangeError` for: id 0, `1.5`, 2147483648, `NaN`; empty or 501 ids; a missing Answer;
  - decode `malformed` for: `""`, `v1`, `v1-1-`, `v1-0-a`, `v1-01-a`, `v1-2147483648-a`, `v1-1-f`, `v1-1-a b`, `V1-1-a`, `v1-1-a-`, `#v1-1-a`, `v1-1-%61`, `v0-1-a`, 501 letters, a 1025-character string;
  - decode `unsupported_version` for `v2-1-a` and `v10-1-a`;
  - `restoreQuestionnaire` `statement_count_mismatch` for one id too few and one too many;
  - `currentIndex` equals the length.
- [ ] Web tests: Scenarios 1–7 (clipboard mock defined and removed per test; assert `document.activeElement` is the field; `selectionStart === 0` and `selectionEnd === url.length`; the URL has no `?` and exactly one `#`).
- [ ] CSS, docs and evidence as above.

## Verification Plan
- `CI=true ./init.sh` exits 0: pytest unchanged (966), Vitest = 196 + the new tests, typecheck and build ok.
- Greps:
  - `grep -rnE "location\.hash|history\.(push|replace)State|localStorage|sessionStorage|document\.cookie|execCommand|navigator\.share" apps/web/src packages/core/src` → nothing outside tests;
  - `grep -rn "navigator.clipboard" apps/web/src` → only `ShareResults.tsx` and its test;
  - `grep -rn "fetch(" apps/web/src --include=*.ts --include=*.tsx` → only `main.tsx` and tests.
- No E2E harness. Vitest plus the browser check cover the flow.
- **Scratch data and server**: the same recipe as `docs/specs/results-ranking.md` "Verification Plan": a session scratchpad dir, `tests.pipeline_fixtures.fake_provider`, no key, no network, Election 1 with 30 Statements, `Partido Alfa` and `Bloque Beta`, uvicorn on port 8011 through a temporary `.claude/launch.json` entry. Clean up afterwards; `git status` shows only feature changes.
- **Mandatory real browser** (AGENTS.md), Chrome, at 375x812 and 1280x800:
  - **A (copy):** rate 1–6 `De acuerdo`, rate 7 `Muy en desacuerdo` + Important, mark 8 Important and skip it, skip 9–30. Then `Copiar enlace` → `Enlace copiado.`. The clipboard (read with `navigator.clipboard.readText()` with permission granted, or pasted into a new tab's address bar) is `http://127.0.0.1:8011/resultados#v1-<D>-ddddddAS` + 22 × `s`, where `<D>` is the published version id from `/api/v1/elections/1`. It matches `^http://[^?#]+/resultados#v1-\d+-[a-esA-ES]{30}$`.
  - **B (fallback):** reload and repeat with `Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true })` run in the console first, then with a `writeText` that rejects with `NotAllowedError`. The field shows the same URL, focused and selected. At 375px it does not widen the page (`scrollWidth <= innerWidth`).
  - **C (opening):** open the copied URL in a new tab → the placeholder page. The network list shows `GET /resultados` with no fragment, and the uvicorn access log line is `GET /resultados HTTP/1.1` with no answers.
  - **D (all skipped):** no share section.
  - **E (methodology):** `/metodologia` shows the new paragraph.
  - Also: clicking `Copiar enlace` makes no request; the results tab's URL stays `/elecciones/1/cuestionario` with no `#`; storage and cookies are empty; the console is clean; the button and field are ≥ 48px; there is no amber except focus and Important; the screen reader text of the status changes on copy (accessibility snapshot).

## Evidence To Capture
- `init.sh` steps and test counts, the new test names, the grep results.
- Browser: Chrome version, both widths, Runs A–E with the copied URL text, the fallback states, the request list and the access log line, storage and URL values, the console, the cleanup. Record only in `feature_list.json` and `PROGRESS.md`, never in `docs/validations/`.

## Validator Checklist
- [ ] Only the files above changed. No API, Python, dependency or ranking change. End-screen edits are limited to one prop and one line.
- [ ] Format v1 is exactly as specified. Decode is strict, with the listed kinds. The round-trip is lossless, including skip, flagged skip and Important, and gives identical `rankParties` output.
- [ ] Copy works with the clipboard. The fallback field is focused and selected when the clipboard is missing or denied. The status is announced. The note is present.
- [ ] Answers appear only after `#`. No request, page URL, history or storage carries them.
- [ ] `/resultados` shows the placeholder and does not read the fragment. The methodology paragraph is in the present tense, with its test updated.
- [ ] Browser runs A–E pass at 375px and desktop. The console is clean.
- [ ] ARCHITECTURE, CONSTRAINTS, DESIGN and the four risks-doc edits are made. Evidence is recorded.
