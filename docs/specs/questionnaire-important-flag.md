# Feature Implementation Spec: Voter marks a Statement as Important

## Source Feature

- `id`: questionnaire-important-flag (GitHub issue #41)
- `area`: web
- `depends_on`: questionnaire-answer-flow (`accepted`). Also builds on `match-score-engine` and `methodology-page` (both `accepted`).
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "Browser test: toggle the star, navigate, and the state is kept"; notes: "Amber accent is reserved for this (DESIGN.md).")

## Goal

Each Statement step of the Questionnaire (`/elecciones/:electionId/cuestionario`) gets a star toggle that marks the Statement Important. The flag lives in the same pure core reducer as the Answers, so it survives `Anterior`, `Siguiente`, `Saltar` and the end screen, and it stays in memory only, like the Answers. The feature also adds a pure selector that turns the questionnaire state into the match-score engine's `Answer[]` (with `important`), so `results-ranking` can call `computeMatchScores` without touching the reducer. No results are built here.

## Decisions

- **Where the flag lives (core).** `QuestionnaireState` (`packages/core/src/domain/questionnaire.ts`) gains `readonly important: ReadonlySet<number>`, a set of Statement ids, kept beside `answers`. The value Map stays `ReadonlyMap<number, AnswerValue>`.
  - Why a separate Set and not `{ value, important }` in the Map: an unanswered Statement has no Map entry (an invariant that `next` and `summarize` rely on), and the Voter can mark a Statement before rating it. A Set keeps both rules unchanged.
  - `startQuestionnaire(ids)` starts with an empty Set.
  - New action `{ type: "toggleImportant" }` adds or removes the current Statement's id. It does not advance and does not change `answers`. It is a no-op on the end screen, like `select`/`skip`/`next`. A toggle returns a new state with a new Set. Other actions carry the Set over unchanged (same reference is fine; it was not changed).
- **Skip and not-yet-answered Statements.** The toggle works whatever the Answer is: before any rating, on a rated Statement and on a skipped one. `select`, `skip`, `next` and `back` never clear the flag.
  - Justification: CONTEXT.md says "An Answer may be marked Important", and an Answer is a rating **or** `skip`. The engine already gives a skipped Statement no weight (skip is excluded before the weight is applied, `match-score.ts`), so a flag on a skip changes no score. Clearing it on skip would silently lose the Voter's choice if they go back and rate the Statement. A flag on a Statement with no Answer has no Answer to attach to, so the selector drops it (below), and `next` still needs an Answer: the toggle never enables `Siguiente`.
- **Selector for `results-ranking`.** Export `toMatchScoreAnswers(state): Answer[]` (type `Answer` from `match-score.ts`; `questionnaire.ts` already imports from it).
  - One entry per Statement id that has an Answer, in `statementIds` order: `{ statementId, value, important: state.important.has(statementId) }`. `important` is always a boolean. Statements without an Answer are omitted (the engine treats a missing Answer like skip). A skip keeps its flag (`{ value: "skip", important: true }`): the engine ignores it, and `share-link-create` can round-trip it losslessly.
  - It is the only shape `results-ranking` needs: `computeMatchScores(toMatchScoreAnswers(state), parties)`. Weight 2 comes from the engine's `IMPORTANT_WEIGHT`; nothing in this feature duplicates the weight.
- **Summary / end screen.** `summarize(state)` returns `{ answered, skipped, important, total }`, where `important` counts Statements that are both rated (not skip) and flagged, i.e. exactly the Statements that count double. The end screen adds one sentence after the answered/skipped one:
  - 0 → `No has marcado ninguna afirmación como importante.`
  - 1 → `Has marcado 1 afirmación como importante.`
  - k > 1 → `Has marcado {k} afirmaciones como importantes.`
  - A flag on a skipped Statement is not counted. That is consistent with the methodology copy ("Las afirmaciones que te saltes … no cuentan. Las que marques como importantes cuentan el doble.").
- **Toggle UI and accessibility** (in `StatementStep`, `QuestionnaireFlow.tsx`).
  - Placed directly after the Statement `h2` and before the radiogroup, so the keyboard order radios → `Siguiente` from `questionnaire-answer-flow` stays adjacent. DOM: `<button type="button" className="important-toggle" aria-pressed={flagged} aria-describedby="important-hint" onClick=…><svg aria-hidden="true" focusable="false" …/><span>Importante para mí</span></button>` then `<p id="important-hint" className="questionnaire__hint">Las afirmaciones importantes cuentan el doble al calcular la afinidad.</p>`.
  - The accessible name is constant (`Importante para mí`). State is announced only by `aria-pressed` (the ARIA toggle-button pattern: the name must not change with the state).
  - Native `<button>`, so Tab, Enter and Space work. Focus stays on the toggle after activation (no focus move, no advance).
  - Meaning not by colour alone. Not pressed: an outline star (stroke `--color-secondary`, no fill), 1px `--color-border` border, normal weight text. Pressed: a filled star (fill `--color-accent`, stroke `--color-text`), 2px `--color-accent` border and 600 weight text. The shape (outline vs filled) and weight carry the state; amber only adds to it.
  - Amber is used only for the pressed state and for focus (the existing `button:focus-visible` 3px `--color-accent` outline already applies). No amber on hover, on the unpressed button or anywhere else.
  - Target: `min-height: 48px; min-width: 48px`, `inline-flex`, 8px gap, star 24px. Text in `--color-text` on `--color-surface` (AA). The star's dark stroke is ≥ 3:1 against white in both states (WCAG 1.4.11).
- **Copy consistency.** The hint says "cuentan el doble", the same rule as `MethodologyPage.tsx` ("Las que marques como importantes cuentan el doble"). The matching rule, `IMPORTANT_WEIGHT` and the methodology page do not change, so CONSTRAINTS.md "Public Copy" is not triggered.
- **Memory-only.** The flag lives in the same `useReducer` as the Answers. It is never sent in a request, never put in the URL (path, query, fragment, history) and never written to `localStorage`, `sessionStorage`, cookies or IndexedDB. A reload, browser Back or leaving the page loses it, exactly like the Answers. The step's privacy note already covers it ("Tus respuestas …"); the copy does not change. Share Links (`share-link-create`) will carry it later, in the fragment.
- **Risks doc.** The flag inherits the existing entry "Answers are memory-only (`questionnaire-answer-flow`) … Revisit in `results-ranking` / `share-link-create`". That entry is extended to say "Answers and Important flags", not duplicated.

## Non-Goals

- Results, ranking, any call to `computeMatchScores` from the UI (`results-ranking`). Share Link encoding (`share-link-*`). Breakdown (`results-breakdown-evidence`).
- Changing the engine, `IMPORTANT_WEIGHT`, the methodology page or the privacy note. Redesigning the flow, controls, focus rules or scale.
- A limit on how many Statements can be Important. Persisting or warning before leaving.
- Any Python, API, migration, `init.sh`, npm dependency or new design token (`--color-accent` exists).

## Job Story

When a Statement is about something I care about a lot,
I want to mark it Important with one tap and see that mark when I come back to it,
so I can trust that it will weigh double in my result.

## Users And Permissions

- Voter: anonymous. No new request; the only API calls stay the two GETs from `questionnaire-answer-flow`, made before any Answer or flag.

## Acceptance Scenarios

Fixture: Election 1 `Generales 2023` with Published Dataset Version 1 (30 Statements in the browser, 3 in Vitest).

### Scenario 1: toggle on and off
Given Statement 1 is shown
When the Voter activates `Importante para mí`
Then the button has `aria-pressed="true"`, shows a filled amber star and bold text, focus stays on it, the Statement and `Afirmación 1 de 30` do not change, and `Siguiente` stays disabled (no Answer yet). Activating it again sets `aria-pressed="false"` with an outline star.

### Scenario 2: the flag survives navigation
Given Statement 1 is marked Important and rated `De acuerdo`
When the Voter activates `Siguiente`, then `Anterior`
Then Statement 1 shows `De acuerdo` checked and the toggle pressed. Statement 2 showed the toggle not pressed.

### Scenario 3: skip keeps the flag
Given Statement 2 is marked Important
When the Voter activates `Saltar esta afirmación`, then `Anterior`
Then Statement 2 shows `Has saltado esta afirmación.` and the toggle still pressed. Rating it `Muy de acuerdo` keeps the flag.

### Scenario 4: flag before rating, then Back
Given Statement 3 is shown with no Answer
When the Voter marks it Important and activates `Anterior`, then `Siguiente`
Then Statement 3 shows no radio checked and the toggle pressed.

### Scenario 5: end screen counts and back
Given the Voter reaches the end with 2 rated Important Statements and 1 skipped Important Statement
When the end screen shows
Then it reads `Has marcado 2 afirmaciones como importantes.` after the answered/skipped sentence. `Volver a la última afirmación` shows the last Statement with its flag as left. Unmarking one rated Statement and returning gives `Has marcado 1 afirmación como importante.`; none gives `No has marcado ninguna afirmación como importante.`

### Scenario 6: keyboard and screen reader
Given a Statement is shown
When the Voter uses only the keyboard (Tab to the toggle, Space, Enter, Tab into the radiogroup, arrow keys, Tab to `Siguiente`, Enter)
Then the toggle flips on Space and on Enter without advancing, shows the 3px amber focus outline, and the accessibility tree shows a toggle button named `Importante para mí` with its pressed state and the hint as its description. The radios → `Siguiente` order is unchanged.

### Scenario 7: flags never leave the browser
Given Scenarios 1–6 were walked through
Then no request was made after the Dataset Version load; no request carries an Answer or flag in its path, query, headers or body; the URL stayed `/elecciones/1/cuestionario` without `?` or `#`; `localStorage.length === 0`, `sessionStorage.length === 0`, `document.cookie === ""`. A reload shows Statement 1 with nothing checked and the toggle not pressed.

## Repository Research

### Files Inspected
- `packages/core/src/domain/{questionnaire,match-score}.ts`, `packages/core/src/index.ts`, `packages/core/test/domain/questionnaire.test.ts`.
- `apps/web/src/features/questionnaire/{QuestionnaireFlow.tsx,QuestionnairePage.test.tsx}`, `apps/web/src/features/methodology/MethodologyPage.tsx` (matching section), `apps/web/src/ui/{tokens,components}.css`, `apps/web/vite.config.ts`.
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md` (Core, match-score inputs), `docs/domain-model.md`, `docs/build-brief.md` (matching rule), `docs/risks-and-open-questions.md`, `docs/specs/questionnaire-answer-flow.md`, `feature_list.json` (this feature, `results-ranking`, `share-link-create`), `.agents/skills/github-flow/references/practical-notes.md`.

### Existing Patterns To Follow
- Pure reducer in core, tested under Node/Vitest; React only renders and dispatches. Web tests render `App` in `MemoryRouter` with a mocked `FetchLike` (`happyFetch`, `datasetVersionJson` in `src/test/fetch-mocks.ts`), use `fireEvent` and query by role.
- `button:focus-visible` already draws the amber outline (`components.css`). Buttons are 48px high with a 12px radius.

### Current Gaps
- No `important` field, toggle action, selector or count. `summarize` tests compare exact objects and must gain `important`.

## Expected File Changes
- `packages/core/src/domain/questionnaire.ts`: modify (Set, action, `toMatchScoreAnswers`, `summarize.important`, header comment).
- `packages/core/src/index.ts`: modify (export `toMatchScoreAnswers`).
- `packages/core/test/domain/questionnaire.test.ts`: modify.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: modify (toggle, hint, end-screen sentence).
- `apps/web/src/features/questionnaire/QuestionnairePage.test.tsx`: modify.
- `apps/web/src/ui/components.css`: modify (`.important-toggle`, its pressed state, `.questionnaire__hint`).
- Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.

## Visual Design Impact
- UI involved: yes. Source: `DESIGN.md` (amber reserved for Important and focus; Statement card includes "an Important toggle (a star)"; 48px targets). No new token or design artifact.
- States: toggle unpressed, pressed, focused (both states), hover (`border-color: var(--color-primary)` like `.button-secondary`, never amber). Inline SVG star (no icon dependency), `aria-hidden`.
- `.questionnaire__hint`: 14–16px, `--color-secondary` (not `muted`, which fails AA on `background`).
- 375px: no horizontal scroll; toggle and hint wrap. Desktop: the 720px column. No party content, no red/green.

## Durable Documentation Impact
- `ARCHITECTURE.md`: update the Core questionnaire line (replace "No `important` field yet" with the Set, `toggleImportant`, `toMatchScoreAnswers`, `summarize.important`) and the Web Client Questionnaire description (the toggle; flags are memory-only).
- `CONSTRAINTS.md`: update the two Client-side Matching rules on Answers to read "Answers (including Important flags)". No new rule.
- `docs/risks-and-open-questions.md`: extend the memory-only entry to "Answers and Important flags". Touch nothing else.
- `AGENTS.md`, `DESIGN.md`, `CONTEXT.md`, `MethodologyPage.tsx`: not needed (no workflow, token, term or matching-rule change).

## Implementation Plan
1. Core: state, action, selector, `summarize`, exports, tests.
2. Web: toggle, hint and end-screen sentence in `QuestionnaireFlow.tsx`; CSS; page tests.
3. `CI=true ./init.sh`, the greps, the browser walk-through, then the docs, `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks
- [ ] `questionnaire.test.ts`: start has an empty Set; toggle adds then removes the current id, does not advance or touch `answers`, returns a new Set (old one unchanged); toggle is a no-op on the end screen; toggle on an unanswered Statement leaves `next` a no-op; `select`/`skip`/`next`/`back` keep the Set; skip keeps the flag; `summarize` counts only rated+flagged (update existing `toEqual`s); `toMatchScoreAnswers` order, booleans, omits unanswered (flagged or not), keeps a flagged skip; one test feeding its output to `computeMatchScores` showing a flagged rated Statement weighs 2 and a flagged skip has no effect.
- [ ] `QuestionnairePage.test.tsx` (3 Statements): Scenarios 1–5 by role (`button` name `Importante para mí`, `aria-pressed`, focus stays on it, description is the hint); end-screen sentences for 0, 1 and 2; Scenario 7 in jsdom (still exactly two fetch calls, empty storage).
- [ ] CSS and docs as above.

## Verification Plan
- `CI=true ./init.sh` exits 0 (pytest unchanged; Vitest = current count + new tests; typecheck and build ok).
- `grep -rnE "localStorage|sessionStorage|indexedDB|document\.cookie" apps/web/src packages/core/src` → only tests. `grep -rn "fetch(" apps/web/src --include=*.ts --include=*.tsx` → only `main.tsx` and tests. `grep -rn "accent" apps/web/src/ui/components.css` → only focus rules and the pressed toggle.
- No E2E harness; Vitest plus the browser check cover the flow.
- **Scratch data**: build the 30-Statement scratch DB outside the repo exactly as recorded in `questionnaire-answer-flow`'s evidence in `feature_list.json` (`mktemp -d`, worktree CLI, `tests.pipeline_fixtures.fake_provider`, no key, no network). Serve it from a **temporary** `.claude/launch.json` entry as in `.agents/skills/github-flow/references/practical-notes.md` (`/usr/bin/env WEB_DIST_DIR=<worktree>/apps/web/dist DATABASE_URL=sqlite:///<scratch>/… <worktree>/.venv/bin/uvicorn … --port 8011`), start with `preview_start`, and afterwards stop it, remove the entry and delete the scratch dir; `git status` shows only feature changes.
- **Mandatory real-browser check** (AGENTS.md Browser Validation) at 375x812 and 1280x800 on the FastAPI-served build, from the Landing:
  - Scenarios 1–5: toggle on/off; flagged Statements keep the flag across `Siguiente`, `Anterior` and `Saltar`; flag before rating then Back; all 30 Statements to the end with a known number of flags; the end-screen sentence matches; `Volver a la última afirmación` and back again.
  - Scenario 6: one keyboard-only pass over at least 3 Statements (Space and Enter on the toggle) and an accessibility snapshot showing the pressed state.
  - Scenario 7: network list (only the document, assets, `GET /api/v1/elections`, `/api/v1/elections/1`, `/api/v1/dataset-versions/1`, nothing after), storage/cookie/`location.href` values, reload clears the flag.
  - Per width: toggle ≥ 48x48px, `scrollWidth <= innerWidth`, amber only on the pressed toggle and focus, the console clean.

## Evidence To Capture
- `init.sh` step results and Vitest counts; new test names; grep results.
- Browser: Chrome version, both widths, per-scenario results with the end-screen counts, toggle size, the request list, storage/cookie/URL values, keyboard and accessibility-tree summary, the scratch/launch.json cleanup. Only in `feature_list.json` and `PROGRESS.md`, never `docs/validations/`.

## Validator Checklist
- [ ] Only the files above changed; no new dependency, Python, API, `init.sh` or migration change; the engine and methodology page are untouched.
- [ ] The flag is in the core reducer as a Set by Statement id; toggling never advances or enables `Siguiente`; skip/select/back keep it.
- [ ] `toMatchScoreAnswers` output is accepted by `computeMatchScores` and gives weight 2 to rated Important Statements.
- [ ] Toggle: native button, `aria-pressed`, constant Spanish name, keyboard operable, ≥ 48px, filled vs outline star plus weight, amber only for pressed and focus.
- [ ] Scenarios 1–7 pass in a real browser at 375px and desktop; console clean; no request, URL or storage carries Answers or flags.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and the risks entry updated as specified; evidence recorded; no `docs/validations/`.
