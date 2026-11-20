# Feature Implementation Spec: Landing shows only the current Election, short Skip label, logo-only matrix columns

## Source Feature

- `id`: ui-2026-focus-tweaks
- `area`: web
- `depends_on`: e2e-real-2026-election (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json`

## Goal

The user (Kike) asked for three small UI changes on 2026-11-20, now that the 2026 Election is published:

1. In the Questionnaire the skip button reads `Saltar` instead of `Saltar esta afirmación`.
2. The Landing shows only the current Election and drops the visible `Elecciones disponibles` heading. The 2023 Election stays in the database, and its Questionnaire, results and Share Links still open by URL.
3. In the results Statement matrix (1024px and up) the Party column headers show only the Party logo tile. The visible short name goes, so every Party column has exactly the same width. The full Party name stays as the header's accessible name.

## Non-Goals

- No API, database, migration or Election `status` change. The 2023 Election is not archived. Archiving would hide its Questionnaire (`share-link-open`: no Questionnaire is offered for a non-`active` Election), which breaks the "still open by URL" requirement.
- No "past elections" section or link on the Landing.
- No change to the mobile breakdown cards (below 1024px), the ranking rows or the inspector. They keep logo, name and short name. The user only mentioned the matrix, and cards have no columns to align.
- No change to the Election card layout or the grid (`--election-columns`: 1 column, 2 from 640px). One card in the left column at 640px and up is the expected result. Making it full width would be a separate request.
- No re-recording of the Landing carousel videos. They may still show the old label and headers (see the accepted Low below).
- No change to the skipped note (`Has saltado esta afirmación.`), the matrix legend (`Saltada`) or the Share Link format.

## Job Story

When I open IdeologiApp before the 29 November 2026 election,
I want to see only that Election, a short skip button and a tidy matrix,
so I can start the right Questionnaire at once and compare Parties in columns that look the same.

## Users And Permissions

- Voter (anonymous): the only actor. No permission change. Answers stay in the browser, and Share Links carry them in the URL fragment.

## Acceptance Scenarios

### Scenario 1: The Landing lists only the most recent Election

Given the API lists Elections 1 (`2023-07-23`) and 2 (`2026-11-29`), both `active`
When the Voter opens `/`
Then the Elections section shows exactly one card, `Elecciones generales 2026`, linking to `/elecciones/2/cuestionario`
And there is no visible `Elecciones disponibles` heading or text
And the section is still a region with an accessible name (`aria-label="Elecciones"`).

### Scenario 2: Choosing the Election is generic

Given the API returns Elections in any order
When the Landing renders
Then it shows the Election with the latest `date` (ISO `YYYY-MM-DD`, compared as strings). On equal dates the higher `id` wins
And the `En preparación` badge still shows if that Election has no published Dataset Version.

### Scenario 3: Loading, error and empty states are unchanged

Given the request is pending, fails, or returns no Elections
Then the Landing shows `Cargando elecciones…`, the error card with `Reintentar`, or `Ahora mismo no hay elecciones disponibles…` as today, inside the same named region.

### Scenario 4: The 2023 Election stays reachable

Given the committed `data/ideology.db`
When the Voter opens `/elecciones/1/cuestionario` directly, answers and finishes
Then the 2023 Questionnaire and its results work as before
And a 2023 Share Link (`/resultados#v1-3-…`, made from that results screen) opens the shared result with the same ranking
And the API is unchanged: `GET /api/v1/elections` still lists both Elections.

### Scenario 5: Short skip label

Given any Statement in the Questionnaire
Then the outlined skip button reads `Saltar` (leading step-over icon). Its accessible name is `Saltar`
When the Voter presses it
Then the flow skips as before: the Answer is `skip`, the next Statement shows, and `Anterior` back shows `Has saltado esta afirmación.`
And at 375px the `Anterior` / `Saltar` / `Siguiente` row fits on one line without wrapping inside a button.

### Scenario 6: Logo-only, equal-width Party columns

Given the results screen at 1024px or more (end screen or shared result)
Then each Party column header contains only the 32px logo tile (or its short-name placeholder when the logo is missing or fails, which is a logo stand-in, not a text label)
And it has no visible short-name text
And its accessible name is the full Party name (e.g. `Partido Socialista Obrero Español`)
And every Party header and cell column has the same rendered width (all `.matrix__party-head` `getBoundingClientRect().width` values within 0.5px) for both Elections (12 and 9 Parties)
And cell buttons keep their accessible names (`PSOE: De acuerdo, coincidencia 75 %. Ver la cita`).

### Scenario 7: Below 1024px nothing else changes

Given the results screen at 375px
Then the breakdown cards still show each Party's tile, name and short name.

## Repository Research

### Files Inspected

- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx` (line 213): `<span>Saltar esta afirmación</span>` inside the `button-secondary` skip button.
- `apps/web/src/features/landing/LandingPage.tsx`: `<section aria-labelledby="elections-title">` with `div.section-head > h2#elections-title`. `ElectionsList` maps `state.elections` in API order. The header comment still mentions the API order.
- `apps/web/src/features/landing/useElections.ts`: loads `api.listElections()`. Leave it unchanged and put the selection in a pure helper.
- `packages/core/src/domain/election.ts`: `Election.date` is `YYYY-MM-DD`.
- `apps/web/src/features/results/ResultsMatrix.tsx`: the party `th` renders `PartyLogo`, an `aria-hidden` `span.matrix__party-short` and a `visually-hidden` full name.
- `apps/web/src/features/results/PartyLogo.tsx`: the tile is `aria-hidden`, and the placeholder draws the short name inside the fixed tile.
- `apps/web/src/features/results/ResultsBreakdown.tsx` (lines 206-209): the mobile cards show `position__short`. Leave these as they are.
- `apps/web/src/ui/components.css`: `.matrix` is `width: 100%`, auto table layout. `.matrix__party-head .party-logo` and `.matrix__party-short { white-space: nowrap }` (lines 2265-2273). `.matrix__cell` and `.match-cell { min-width: 2.75rem }`. `.landing > section:has(.election-list)` sets the margin. Party columns have no width today, so they size to the short-name text.
- `apps/web/src/ui/tokens.css` (lines 69-71): `--matrix-statement-width`, `--matrix-answer-width`, `--matrix-header-height`.
- Tests: `LandingPage.test.tsx` (region name `Elecciones disponibles` at lines 52, 134, 192; heading order at 108; "Scenario 6: several Elections keep the API order" at 239), `QuestionnairePage.test.tsx` and other tests that click `button("Saltar esta afirmación")` (`ResultsBreakdownFlow.test.tsx`, `ShareApp.test.tsx`, `ShareResults.test.tsx`, `app/App.test.tsx`), and `ResultsMatrix.test.tsx` line 124 (headers expected as `"P1Partido Uno"`).
- `DESIGN.md` lines 159, 178, 180, 185, 196, 212. Lines 180 and 212 still describe the removed upcoming card. That text is stale and should be fixed in the same edit.
- `README.md` line 103 quotes `"Saltar esta afirmación"`.
- `docs/risks-and-open-questions.md`: line 38 (Settled `landing-election-picker`: "lists exactly what the API returns… in API order") becomes untrue. Line 57 (matrix width, "revisit when more than 9 Parties") concerns the matrix. Line 174 (Landing recordings show a real results screen) is related.
- `data/ideology.db` (read-only query): Election 1 is 2023-07-23, `active`, Published DV 3. Election 2 is 2026-11-29, `active`, Published DV 5. The `(country, type, date)` combination is unique.

### Existing Patterns To Follow

- Pure view helpers next to components with their own unit tests (e.g. `breakdown-view.ts`, `format-date.ts`).
- Width tokens in `tokens.css` (`--matrix-*-width`), applied as `width`/`min-width`/`max-width` in `components.css`.
- Tests use `@testing-library/react` with role/name queries, and API data comes from `test/fetch-mocks.ts` `electionJson()`.
- There is no browser E2E harness (no Playwright). The standard gate is `CI=true ./init.sh` (Vitest included).

### Current Gaps

- None that block this feature.

## Technical Approach

1. **Skip label.** Change the span text to `Saltar`. The accessible name follows the visible text. Do not add an `aria-label`. Replace `"Saltar esta afirmación"` with `"Saltar"` in every test that queries the button. `Saltada` in the matrix legend is a different word, so exact-name queries do not collide.
2. **Landing.** Add `apps/web/src/features/landing/current-election.ts` exporting `currentElection(elections: readonly Election[]): Election | null`. It returns the latest by `date`, the higher `id` on a tie, and `null` for an empty list. In `ElectionsList` (`loaded`), render the empty message when the result is `null`. Otherwise render the same `ul.election-list` with that one `ElectionItem`. Replace `aria-labelledby="elections-title"` and the `section-head`/`h2` with `<section aria-label="Elecciones">`, and keep the `:has(.election-list)` CSS hook working. Update the component's header comment. Elections remain "what the API returns, and then the most recent one".
3. **Matrix.** In `ResultsMatrix.tsx`, remove the `span.matrix__party-short` from the party `th`. Keep `PartyLogo` and the `visually-hidden` full name. Add the token `--matrix-party-width: 3.5rem` to `tokens.css` (32px tile plus 2 × `--space-xs` padding, and at least the 2.75rem cell button plus padding). Give `.matrix__party-head` and `.matrix__cell` `width`, `min-width` and `max-width` set to the token. Remove the `.matrix__party-short` rule and fix the `.party-logo` bottom margin (no `--space-xs` gap is needed under the tile). The extra width of the `width: 100%` table then goes to the columns in equal shares, because every Party column has the same declared width and content. If Chromium does not give equal widths, use the fallback: drop `width: 100%` from `.matrix` so the table is as wide as its columns, and record this as a deviation. `--matrix-header-height` (used for scroll-padding) can stay. A taller padding is still safe, so do not tune it unless the implementer measures a visible gap.
   Implementation note (2026-11-20, implementer): the token ships as `3.25rem` (52px = the 2.75rem cell button + 2 × `--space-xs`, the minimum this step states), not `3.5rem`. Measured in Chromium: with 3.5rem the 2023 shared result (9 Parties, app shell, 1280px) gained a 16px sideways scroll (table 944px in a 928px box) that the old short-name layout did not have (928px); with 3.25rem it fits (928px), the columns stay equal and the cell button stays 45px wide.
4. **Docs.** Edit `DESIGN.md`, `README.md` and the risks doc as listed below.

## Expected File Changes

- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`: modify (label).
- `apps/web/src/features/landing/current-election.ts`: create (pure selector).
- `apps/web/src/features/landing/current-election.test.ts`: create (latest by date, unordered input, tie on date to higher id, empty to null, single).
- `apps/web/src/features/landing/LandingPage.tsx`: modify (one Election, no h2, `aria-label`).
- `apps/web/src/features/landing/LandingPage.test.tsx`: modify (region name `Elecciones`; the heading order without the h2; replace "Scenario 6 … keep the API order" with "only the most recent Election is listed", using 2023, 2027 and 2026 in shuffled order, so only 2027 is listed and no `Elecciones disponibles` text appears anywhere; the empty, error and loading tests stay green).
- `apps/web/src/features/results/ResultsMatrix.tsx`: modify (drop the short-name span).
- `apps/web/src/features/results/ResultsMatrix.test.tsx`: modify (headers expected as `"Partido Uno"`…, no `.matrix__party-short`, every party `th` has the class and a `.party-logo` and no other visible text). jsdom has no layout, so equal widths are checked in the browser only.
- `apps/web/src/ui/tokens.css`, `apps/web/src/ui/components.css`: modify (token, column widths, remove the short-name rule).
- Tests that click the skip button: `QuestionnairePage.test.tsx`, `ResultsBreakdownFlow.test.tsx`, `ShareApp.test.tsx`, `ShareResults.test.tsx`, `app/App.test.tsx`. Modify the label only, and add one assertion in `QuestionnairePage.test.tsx` that the visible text is exactly `Saltar`.
- `DESIGN.md`, `README.md`, `docs/risks-and-open-questions.md`: modify (see below).
- `feature_list.json`, `PROGRESS.md`: status and evidence at the end.

## Visual Design Impact

- UI involved: yes. Design source: `DESIGN.md`. No new design artifact.
- Screens affected: the Landing Elections section, the Questionnaire controls row, and the results Statement matrix header (end screen and shared result, 1024px and up).
- `DESIGN.md` edits:
  - Line 178 (Buttons): `Saltar esta afirmación` becomes `Saltar`.
  - Line 185 (Statement card): `Saltar esta afirmación` becomes `Saltar`.
  - Line 180 (Election card): drop the stale upcoming-card sentence. State that the Landing shows only the most recent Election by date, with older ones reachable by URL.
  - Line 212 (Core Screens 1): replace "`Elecciones disponibles` grid (API order, then the upcoming card)" with "the most recent Election's card (no section heading; region named `Elecciones`)".
  - Line 196 (Statement matrix): replace "32px logo tile + short name, full name hidden" with "32px logo tile only, full name hidden; every Party column `--matrix-party-width` 3.5rem wide".
  - Line 159 grid note: keep it, and optionally add "(one card today)".
  - The YAML token block: add `matrixPartyWidth` only if the other matrix widths are listed there. Check first.

## Durable Documentation Impact

- `ARCHITECTURE.md`: not needed. There is no new layer or boundary.
- `CONSTRAINTS.md`: not needed. There is no new MUST rule.
- `AGENTS.md`: not needed.
- `README.md`: update line 103 (`"Saltar"`). If the README says the Landing lists every Election, adjust that too (check).
- `docs/risks-and-open-questions.md`:
  - Edit line 38. The Landing now shows only the most recent active Election by date (`ui-2026-focus-tweaks`), and older active Elections are reached by URL and Share Links.
  - Add an Open item: if the Operator creates a newer active Election before it has a Published Dataset Version, the Landing would show only that `En preparación` card and hide the current one. Revisit by preferring the latest published Election (owner: the feature that adds the next Election).
  - Edit line 57 with the measured matrix width for 32 Statements × 12 Parties at 1024px and 1280px after this change.
  - Add an Accepted Low to the line-174 entry: the Landing recordings may show the old `Saltar esta afirmación` label and short names under the matrix logos.

## Implementation Plan

1. Run `./init.sh` (baseline).
2. Skip label: update the component and every test.
3. Landing: add the selector and its tests, update `LandingPage.tsx` and its tests.
4. Matrix: update the markup, the token and the CSS, then the matrix test.
5. Run `CI=true ./init.sh`.
6. Browser walk (below).
7. Update the docs, then `feature_list.json` (status and evidence) and `PROGRESS.md`.

## Implementation Tasks

- [ ] `QuestionnaireFlow.tsx`: change the label to `Saltar`, and update the six test files.
- [ ] `current-election.ts` and its test.
- [ ] `LandingPage.tsx`: render one Election, use `aria-label="Elecciones"`, remove the h2, and update the comment.
- [ ] `LandingPage.test.tsx`: update the region name, the heading order and the latest-only test.
- [ ] `ResultsMatrix.tsx`: remove the short-name span.
- [ ] `tokens.css`/`components.css`: add `--matrix-party-width`, set the equal column widths, and remove `.matrix__party-short`.
- [ ] `ResultsMatrix.test.tsx`: update the header expectations.
- [ ] Update `DESIGN.md`, `README.md` and the risks doc.
- [ ] Run `CI=true ./init.sh`, then do the browser walk.

## Verification Plan

- `CI=true ./init.sh` exits 0 (pytest unchanged, Vitest count up by the new tests, `vite build` ok).
- `rg -n "Saltar esta afirmación|Elecciones disponibles|matrix__party-short" apps/web/src README.md DESIGN.md` has no hits (`dist/` excluded).
- Browser (real, per AGENTS.md): build, then start with `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app` and open `http://127.0.0.1:8000/`. Do the walk at 375×812 and 1280×800, in dark and light:
  1. Landing: one card `Elecciones generales 2026`, no `Elecciones disponibles`, carousel below, link to `/elecciones/2/cuestionario`. The accessibility tree shows region `Elecciones`.
  2. 2026 Questionnaire: the button reads `Saltar`, and at 375px the three buttons sit on one row without wrapping. Skip one Statement, go `Anterior` and see the skipped note, then go forward. Finish and reach results.
  3. Results at 1280 (and at 1024 if possible): Party headers show logos only. In DevTools, every `.matrix__party-head` width is equal (record the value). Hover or focus a header cell: the screen-reader name is the full name. Open a cell and the inspector works.
  4. At 375: the breakdown cards still show name and short name.
  5. Share Link from 2026 results opens with the same ranking.
  6. Open `/elecciones/1/cuestionario` directly: answer (skips are fine), check the results matrix (9 equal columns), make a 2023 Share Link and open it.
  7. Console has no errors. Network shows only same-origin requests, none failed, and no request carries answers (the fragment is never sent).
- E2E: there is no persistent E2E harness. The unit tests plus the real-browser walk cover this feature.

## Evidence To Capture

- `CI=true ./init.sh` result with pytest and Vitest counts.
- Browser, widths and themes used. The measured Party column width(s) at 1280 for 12 and 9 Parties. The result of each walk step above.

## Validator Checklist

- [ ] Only these three changes plus the listed docs. No API, DB or status change, and the mobile cards are untouched.
- [ ] Scenarios 1-7 pass in a real browser at 375px and 1280px, light and dark.
- [ ] Party columns are equal width (measured), and headers have the full name as their accessible name.
- [ ] 2023 Questionnaire, results and Share Link open by URL.
- [ ] The DESIGN.md, README and risks doc edits are present, and the stale upcoming-card text is gone.
- [ ] `feature_list.json` and `PROGRESS.md` updated with evidence. No `docs/validations/`.
