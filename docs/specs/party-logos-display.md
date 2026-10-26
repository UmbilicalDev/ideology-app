# Feature Implementation Spec: Party logos and short-name placeholder on the results

## Source Feature

- `id`: party-logos-display
- `area`: web
- `depends_on`: party-logos-data (accepted), results-summary-card (accepted)
- `status`: not_started at planning time (2026-10-26)
- `source`: `feature_list.json`

## Goal

On the end screen and the shared result, every Party in the ranking and in each breakdown row shows a **party-logo tile** before its name. The tile holds the Party's logo, loaded from the same-origin `logoUrl`. When there is no logo, or the logo fails to load, it holds a neutral placeholder with the Party's short name. Every Party gets the same tile in both themes, so neutrality holds. Showing the logos must not reveal anything about the Voter's answers through the logo requests.

## Decisions

1. **Logos are shown** (user, 2026-10-26). This settles DESIGN.md's open question. The only place a Party's colours may appear is the logo image itself.
2. **One fixed light tile in both themes** (user). Background `--color-party-logo-tile: #ffffff` (the light `surface-container-lowest`). Border 1px `--md-sys-color-outline-variant` (follows the theme). Corner `--md-sys-shape-corner-small` (4px; with the logos' 6% padding nothing gets clipped). `box-sizing: border-box; overflow: hidden; flex: none`. The colour tokens are declared once in `:root` of `tokens.css` and **not overridden** in the dark block. The image fills the tile with `object-fit: contain` and no extra padding, because the committed PNGs already carry 6% padding.
3. **Sizes** are layout tokens in `tokens.css`:
   - Ranking tile `--party-logo-size-ranking`: **40px** below 600px (375), **48px** from 600px (about 700 and 1280).
   - Breakdown tile `--party-logo-size-breakdown`: **32px** at every width. It fills the 48px summary row exactly (32 + 2×8 padding).
4. **Where tiles appear**:
   - every ranking row (`ResultsRanking`), first in `.ranking-row__head`;
   - every Party Position summary in every breakdown row (`ResultsBreakdown`), after the chevron and before the name.
   - Both screens get this automatically, because both render these components.
   - Nowhere else: not the summary card (it shows no Party), the Landing, the Questionnaire, Methodology or Not found.
5. **Accessibility.** The tile is decorative. The wrapper has `aria-hidden="true"`, the `<img>` has `alt=""`, and the placeholder SVG is `aria-hidden`. The Party name and short name stay as text, unchanged.
6. **Placeholder that fits any short name.** An inline SVG `<text>` (fill `--color-on-party-logo-tile: #3f484d`, fixed in both themes; 9.4:1 on white) inside a `viewBox` computed by a pure helper. `preserveAspectRatio="xMidYMid meet"` then scales the text to fit inside the tile, whatever the length (`short_name` is ≤ 50 chars). The helper is `placeholderLayout(shortName)`:
   - **Lines.** One line, unless the name is longer than 4 characters and contains a space or a hyphen. Then it is split once at the first such character: a space is dropped (`EH Bildu` → `EH` / `Bildu`), a hyphen stays at the end of line 1 (`EAJ-PNV` → `EAJ-` / `PNV`). At most 2 lines.
   - **Geometry.** Font size is 10 user units through the token `--party-logo-placeholder-font: 600 10px/12px var(--md-ref-typeface-plain)`, with a 0.72em advance per character. Line height is 12. Padding is 2 on each side. The viewBox is at least 28×28, so `PP` does not fill the tile. The result is centred with `text-anchor="middle"` and per-line `<tspan>`s.
   - The placeholder is decorative. At 32px a long name renders small; that is acceptable because the same text sits next to the tile.
7. **Load failure → placeholder, no layout shift.** `PartyLogo` keeps `failed` state. `onError` swaps the `<img>` for the placeholder inside the same, fixed-size wrapper. Each instance handles its own failure. If `logoUrl` changes, `failed` resets (use `key={logoUrl}`).
8. **The logo requests must not leak the ranking (privacy).** If `<img>` elements load in DOM order, the logo requests on the results reach the server in ranking order, and the ranking is derived from the Answers. To prevent this:
   - Logos are **preloaded in Dataset Version order** (`parties` order from the API, by id) as soon as the Dataset Version is available. This means `useQuestionnaireData` when it becomes `ready` (before the first Answer), and `useSharedResult` when `openShareLink` returns `ready`, before `setState`.
   - `preloadPartyLogos(parties)` (in `apps/web`) creates one `new Image()` per non-null `logoUrl`, in order, with `decoding = "async"`. It keeps the images in a module-level `Map<url, HTMLImageElement>` so they are de-duplicated and not garbage-collected mid-load.
   - The rendered `<img>` elements then come from the in-flight request or the HTTP cache (`immutable`, 1 year, with the current `v`).
   - `<img>` never uses `loading="lazy"`, which would tie requests to scrolling.
   - Logo bytes are requested only by `<img>`/`Image` with the exact `logoUrl` value, never by `fetch`.
   - Accepted limit: with DevTools "Disable cache", rendered images may request again in DOM order. This is a debugging setting, not a Voter's default.
9. **View models carry the URL.** `RankedParty` and `BreakdownPosition` (packages/core, pure) gain `readonly logoUrl: string | null`, copied from `Party.logoUrl`. Components get it from `buildResults` and do no lookup of their own.
10. **Normalisation script: deferred, not committed.** A faithful script needs an image library (Pillow), which would be a new dependency. This feature is web-only. Instead, the recipe moves from the party-logos-data spec into the durable runbook (`docs/technical-discovery.md`, Party logos line):
    - trim transparent margins (alpha > 8);
    - fit without distortion into a 256×256 transparent PNG with 6% padding, centred;
    - save as optimised PNG;
    - only at the user's request (CONSTRAINTS.md Party Logos).
    
    The risks entry is reworded: commit a script when the next Election's logos arrive. It must run in a throwaway environment (e.g. `uv run --with pillow`) and add no runtime or `.[dev]` dependency.
11. **No new npm or Python dependency.**

## Non-Goals

- Any API, schema, CLI, bundle or `data/ideology.db` change (owned by party-logos-data). No new logo files, and no edits to committed logo files.
- Logos on the Landing, Questionnaire, Methodology, summary card, share card or Not found. No favicon or tab title change.
- A logo normalisation script (Decision 10), and tightening the SVG check (accepted Low; all logos are PNG).
- Party colours anywhere outside the logo image. No winner emphasis.
- Licensing of the logos (an open user question; it stays in the risks doc).

## Job Story

When I look at my results or a shared result,
I want to recognise each Party by its logo at a glance,
so I can scan the ranking and the per-Statement positions faster, without any Party being favoured.

## Users And Permissions

- Voter / opener of a Share Link: read-only. Answers stay in memory or in the fragment. Logo requests carry only the Party id and the hash.

## Acceptance Scenarios

### Scenario 1: logos in the ranking and breakdown
Given the Published Dataset Version where all 9 Parties have a logo
When the Voter finishes the Questionnaire
Then every ranking row shows a tile with that Party's logo before its name (40px at 375, 48px at 700/1280), and every Party Position summary shows a 32px tile. Names, short names, percentages and values are unchanged as text.

### Scenario 2: placeholder
Given a Party with `logoUrl` null (e.g. `EH Bildu`, `EAJ-PNV`, `PP` cleared in a scratch DB)
When the results render
Then its tiles show the short name (`EH`/`Bildu`, `EAJ-`/`PNV`, `PP`) in `#3f484d` on the white tile, fully inside the tile with no clipping or overflow, and the same size, shape, border and background as a logo tile.

### Scenario 3: load failure
Given a Party whose logo request fails (blocked or 404)
When the results render
Then that Party's tiles show the placeholder, no row moves (same tile box before and after), and the other logos still show.

### Scenario 4: dark theme
Given `prefers-color-scheme: dark`
When the results render
Then every tile keeps the white background. Dark-on-transparent logos (EAJ-PNV text, BNG) are legible, and placeholder text keeps 9.4:1.

### Scenario 5: shared result
Given a Share Link copied from Scenario 1 or 2
When it is opened in a fresh context
Then the shared ranking and breakdown show the same tiles as the end screen.

### Scenario 6: neutrality
Given any mix of logos and placeholders
Then every ranking row and position summary has the same structure and classes, and the same computed tile size, background and border. Nothing differs by rank.

### Scenario 7: privacy
Given the Questionnaire page
When the Dataset Version loads
Then the logo GETs (`/api/v1/parties/{id}/logo?v=<16 hex>`) go out in Party id order, before the first Answer. The end screen triggers no new logo request (cache), or at most requests that again do not follow the ranking.
On a shared result the logo GETs go out in Party id order whatever the ranking. The `Referer` header never contains the fragment. No request carries Answers, and none goes to another origin.

## Repository Research

### Files Inspected

- `apps/web/src/features/results/ResultsRanking.tsx`, `ResultsBreakdown.tsx`, `ResultsSummary.tsx`: where the tiles go. The summary card shows no Party.
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx` (end screen), `features/share/SharedResultsPage.tsx`: both render `ResultsRanking` and `ResultsBreakdown` from `buildResults`.
- `apps/web/src/features/questionnaire/useQuestionnaireData.ts` ("only requests … before the first Answer"), `features/share/useSharedResult.ts`: the preload hooks.
- `apps/web/src/ui/tokens.css`, `components.css` (`.ranking-row__head` flex-wrap baseline; `.position__summary` flex-wrap, min-height 48px), `design-tokens.test.tsx` (no colour literals outside tokens).
- `apps/web/src/features/results/ResultsRanking.test.tsx` and the other results tests:
  - `ResultsRanking.test.tsx:144` asserts `li.querySelector("img, svg")` is null (the old no-logo rule);
  - `ShareResults.test.tsx:253,265` and `ResultsBreakdown.test.tsx:115` compare `textContent`, which will now include placeholder text.
- `apps/web/src/test/fetch-mocks.ts` (`logo_url: null` fixtures), `test/setup.ts`.
- `packages/core/src/domain/{ranking,breakdown,results,dataset-version}.ts` and their tests (exact `toEqual` on `RankedParty`/`BreakdownPosition`).
- `packages/core/src/infrastructure/http/public-api-client.ts`: `logoUrl` already validated against `^/api/v1/parties/[1-9][0-9]*/logo\?v=[0-9a-f]{16}$`.
- `DESIGN.md`, `docs/design/civic-horizon.md`, `CONSTRAINTS.md` (Client-side Matching, Party Logos, Web Client Styling), `ARCHITECTURE.md`, `docs/risks-and-open-questions.md` (lines on party logos and the normalisation recipe), `docs/specs/party-logos-data.md`, `src/ideology_app/api/http_cache.py` (`LOGO_CACHE_CONTROL` immutable 1 year).
- `data/ideology.db`: 9 Parties, ids 1-9 (`PP, PSOE, VOX, SUMAR, ERC, JUNTS, EH Bildu, EAJ-PNV, BNG`), all with PNG logos of 3.5-27 kB.

### Existing Patterns To Follow

- `BrandTitle` decorative `<img alt="">`. Icons are `aria-hidden` inline SVG.
- Layout sizes switch only in `tokens.css` media queries (e.g. `--brand-logo-size`).
- Web tests inject a `FetchLike`. jsdom does not load images, so stub the `Image` global to record `src` order.

### Current Gaps

- `RankedParty` and `BreakdownPosition` have no `logoUrl`.
- No party-logo component, no tile tokens, no preload.
- CONSTRAINTS.md Client-side Matching says "no per-Party colour, highlight or logo placeholder", which must be reworded. No E2E harness exists.

## Expected File Changes

- `DESIGN.md`: modify first. Changes:
  - Settle the open question and remove it from "Open Design Questions".
  - Neutrality rule exception: "only the logo image itself carries a Party's colours".
  - Add `party-logo-tile` / `on-party-logo-tile` (fixed in both themes) to `semantic`.
  - Add a `party-logo` component (YAML and prose: tile, sizes, shape, placeholder, failure) and update the Ranking row and Breakdown row prose.
  - Accessibility table row: `on-party-logo-tile on party-logo-tile` 9.4 / 9.4.
  - Do's and Don'ts: add "Don't recolour, crop or resize a logo per Party; same tile for all".
- `apps/web/src/ui/tokens.css`: modify. Add `--color-party-logo-tile`, `--color-on-party-logo-tile` and `--party-logo-placeholder-font` (root only), plus the size tokens (Decision 3).
- `apps/web/src/ui/components.css`: modify. Add `.party-logo`, `__img` and `__placeholder` / `__text`. The ranking head becomes tile + `.ranking-row__label` (name and short, `min-width: 0`) + percent, with `align-items: center`. The percent stays right-aligned; its null text may wrap within its own box. Add the tile in `.position__summary`. Update the "no … logo" comments.
- `apps/web/src/features/results/PartyLogo.tsx`: create. `PartyLogo({ logoUrl, shortName, size: "ranking" | "breakdown" })`, plus the exported pure `placeholderLayout`.
- `apps/web/src/features/results/party-logo-preload.ts`: create. `preloadPartyLogos(parties: readonly { logoUrl: string | null }[])`.
- `apps/web/src/features/results/ResultsRanking.tsx`, `ResultsBreakdown.tsx`: modify. Render the tile and update the doc comments.
- `apps/web/src/features/questionnaire/useQuestionnaireData.ts`, `features/share/useSharedResult.ts`: modify. Call the preload (Decision 8).
- `packages/core/src/domain/ranking.ts`, `breakdown.ts`: modify. Add `logoUrl` to the view models.
- Tests:
  - new `apps/web/src/features/results/PartyLogo.test.tsx`;
  - modify `ResultsRanking.test.tsx` (replace the no-img assertion with "exactly one identical `.party-logo` per row"), `ResultsBreakdown.test.tsx`, `ShareResults.test.tsx` (compare text excluding `.party-logo`, or update the expected strings), `SharedResultsPage.test.tsx`, `QuestionnairePage.test.tsx` (preload order), `design-tokens.test.tsx` (tile colour tokens absent from the dark block);
  - `test/fetch-mocks.ts`: an option for non-null `logo_url`;
  - `packages/core/test/domain/{ranking,breakdown,results}.test.ts`: `logoUrl` passes through.
- `CONSTRAINTS.md`, `ARCHITECTURE.md`, `docs/risks-and-open-questions.md`, `docs/technical-discovery.md`: see below.

## Visual Design Impact

- UI involved: yes. Design source: `DESIGN.md` (updated first by this feature) and `docs/design/civic-horizon.md`. No new design artifact.
- States: logo / placeholder (1 and 2 lines) / failed → placeholder; light and dark; compact, medium and expanded; ranking with and without `Baja cobertura`; the null-percent row; positions open and closed.
- No horizontal scroll at 375. Names are never truncated. Tap targets are unchanged (the tile is not interactive; the whole summary stays the target).

## Durable Documentation Impact

- `DESIGN.md`: update (above).
- `CONSTRAINTS.md`: update.
  - Client-side Matching: replace "(no per-Party colour, highlight or logo placeholder)" with "(no per-Party colour or highlight; every Party gets the same party-logo tile, logo or short-name placeholder)".
  - Party Logos: add "Logos MUST be requested only via `<img>`/`Image` with `logoUrl` (no `fetch`, no `loading="lazy"`) and MUST be preloaded in Dataset Version Party order as soon as the version is loaded, before results render. Reason: request order must not reveal the ranking." Also add "The tile colours MUST be the fixed `--color-party-logo-tile` pair, identical in both themes."
- `ARCHITECTURE.md`: update. Add `logoUrl` to `RankedParty` / `BreakdownPosition`, describe `PartyLogo` + `preloadPartyLogos`, list the new tests, and add the feature to the "Current state" list.
- `docs/risks-and-open-questions.md`: update.
  - Line 11: DESIGN.md's question is now settled by party-logos-display; licensing stays open (user).
  - Line 13: reword per Decision 10. Add the DevTools "Disable cache" limit of Decision 8 as an accepted Low.
- `docs/technical-discovery.md`: update the Party logos runbook line with the normalisation recipe.
- `AGENTS.md`, `README.md`, `CONTEXT.md`, Methodology copy: not needed. There is no workflow, operator or domain change, and the privacy text stays true.

## Implementation Plan

1. Update DESIGN.md, then `tokens.css` to mirror it.
2. Core: add `logoUrl` to the view models and their tests.
3. Web: `PartyLogo` + `placeholderLayout` + CSS, placed in the ranking and the breakdown.
4. Preload helper, wired into both hooks.
5. Adjust existing tests, add new ones, and update the durable docs.
6. Gate, then the browser walk, then evidence.

## Implementation Tasks

- [ ] DESIGN.md edits (Decisions 1-7). Tokens in `tokens.css`; extend `design-tokens.test.tsx` to assert that the tile colour tokens are not redefined in the dark block.
- [ ] `ranking.ts` / `breakdown.ts`: `logoUrl` passes through; update the exact `toEqual` expectations and add a non-null case.
- [ ] `PartyLogo.tsx`:
  - wrapper `<span class="party-logo party-logo--{size}" aria-hidden="true">`;
  - `<img class="party-logo__img" src={logoUrl} alt="" width="256" height="256" decoding="async">` with `onError` → placeholder;
  - placeholder `<svg class="party-logo__placeholder" viewBox=… preserveAspectRatio="xMidYMid meet" focusable="false">` with `<text class="party-logo__text">` and `<tspan>`s.
- [ ] Tests in `PartyLogo.test.tsx`:
  - `placeholderLayout` for `PP`, `SUMAR`, `EH Bildu`, `EAJ-PNV`, a 50-char name and a short name that contains a space;
  - logo renders an `img` with `alt=""` and the exact URL;
  - null → placeholder text;
  - `fireEvent.error(img)` → placeholder inside the same wrapper node (no img left);
  - the wrapper class is identical in all three cases.
- [ ] Insert the tile in `RankingRow` (head restructure) and `Position` (summary). CSS per Decision 2/3.
- [ ] `party-logo-preload.ts` + tests: stub `Image`, check order = input order, skip nulls, de-duplicate repeats.
- [ ] Wire the preload into `useQuestionnaireData` (on `ready`) and `useSharedResult` (on `ready`, before `setState`). Tests: QuestionnairePage records preload `src` order 1, 2 before any answer; SharedResultsPage records Party-id order when the ranking order differs.
- [ ] Fix the textContent-based expectations in the existing tests without weakening what they check.
- [ ] Update CONSTRAINTS.md, ARCHITECTURE.md, the risks doc and technical-discovery.md.

## Verification Plan

- `CI=true ./init.sh` exits 0: pytest unchanged (1560), Vitest above 373, typecheck, build.
- Greps:
  - `grep -rnE "#[0-9a-fA-F]{3,8}\b|rgba?\(" apps/web/src/ui/components.css apps/web/src/ui/global.css` → nothing;
  - `grep -rn 'loading="lazy"\|fetch(' apps/web/src --include='*.tsx' --include='*.ts'` → only `main.tsx` and tests;
  - `grep -rn "dangerouslySetInnerHTML" apps/web/src` → nothing.
- No E2E harness. Vitest plus the real-browser walk cover the feature.
- **Data** (in `$SCRATCH` under the session scratchpad; never serve or modify `data/ideology.db`):
  - (A) `cp data/ideology.db $SCRATCH/a.db`. All 9 logos.
  - (B) `cp data/ideology.db $SCRATCH/b.db`, then `DATABASE_URL=sqlite:///$SCRATCH/b.db .venv/bin/ideology party logo <S> --election 1 --clear` for `"EH Bildu"`, `EAJ-PNV` and `PP` (confirm `logo_url` is null for ids 1, 7, 8 via `/api/v1/elections/1/published-dataset-version`).
  - Serve each with `/usr/bin/env WEB_DIST_DIR=… DATABASE_URL=… .venv/bin/uvicorn ideology_app.main:app --port <free, never 8000>`. Use temporary `.claude/launch.json` entries if using the preview tool.
  - Use a **different port** for A and B and a fresh browser context: the Dataset Version body is cached `immutable` per origin.
- **Real browser** at 375×812, about 700×900 and 1280×800, each in light and dark (`prefers-color-scheme` emulation):
  - **A:** run the Questionnaire (rate a few, mark one Important, skip the rest) → end screen.
    - Scenario 1 tile sizes from `getBoundingClientRect` (40/48/48 ranking; 32 breakdown).
    - Logos legible in dark (EAJ-PNV, BNG).
    - Open a URL position.
    - `Copiar enlace` → open the link in a fresh context (Scenario 5).
  - **B:** same walk. Placeholders `PP`, `EH`/`Bildu`, `EAJ-`/`PNV` fully inside the tile at 32 and 40/48 (text bbox within the tile bbox), with the same tile box as logo tiles.
  - **Failure (on A):** block `**/api/v1/parties/4/logo*` (DevTools request blocking or Playwright `route.abort()`), then reload and redo the end screen.
    - SUMAR tiles show the placeholder.
    - Row `getBoundingClientRect` and tile size equal to the unblocked run; a `layout-shift` PerformanceObserver reports 0 after the swap.
    - The blocked request is the only failed one; its console error is expected and recorded.
  - At every stop:
    - `scrollWidth <= innerWidth`;
    - identical computed tile background (`rgb(255, 255, 255)` in both themes), border and size across rows;
    - no rank-dependent styling;
    - placeholder contrast 9.4:1;
    - console clean (except the deliberate block);
    - accessibility tree: tiles absent, row names unchanged.
  - **Network:**
    - only same-origin requests;
    - the logo GETs are `/api/v1/parties/{1..9}/logo?v=<16 hex>`, issued in id order right after the Dataset Version (Questionnaire), and in id order on the shared result;
    - no logo request in ranking order when the cache is enabled;
    - `Referer` without `#`;
    - no request contains Answers (no Share Link payload, no `?` other than `v=`).
- **Cleanup:** stop the servers, revert `.claude/launch.json`, delete `$SCRATCH`; `git status` shows only feature files.

## Evidence To Capture

- `init.sh` step results and Vitest count; the new test names; grep output.
- Browser name and version; the widths and themes; tile sizes measured; screenshots only if the user asks.
- For A, B and the failure run: what was seen, the logo request order on both screens, the console, and the network origin list.
- Record in `feature_list.json` evidence and `PROGRESS.md` only (never `docs/validations/`).

## Validator Checklist

- [ ] DESIGN.md was updated (question settled, `party-logo` component, exception wording) and `tokens.css` mirrors it; no colour literal in component CSS.
- [ ] Scenarios 1-7 pass in a real browser at 375/700/1280, light and dark.
- [ ] Every Party gets an identical tile; placeholder and failure fallback work without layout shift.
- [ ] Logo requests: same-origin, `<img>`/`Image` only, Dataset Version order, never ranking order, no Answers.
- [ ] Core view models carry `logoUrl`; `buildResults` still feeds both screens; no re-sorting.
- [ ] CONSTRAINTS.md, ARCHITECTURE.md, the risks doc and technical-discovery.md were updated as specified; no new dependency.
- [ ] Scope: no API, DB, logo-file or script changes; `feature_list.json` and `PROGRESS.md` were updated with evidence.

## As Implemented

- Implemented as specified on 2026-10-26 (Session 070), with the open questions answered as proposed: one white tile in both themes, normalisation script deferred (recipe in `docs/technical-discovery.md`), logo preload in Party id order plus the CONSTRAINTS.md MUSTs.
- Change approved by the user during implementation (2026-10-26): the Party Position summary is laid out like the ranking head. It is now chevron, the 32px tile, then one text box `.position__label` (`flex: 1 1 0; min-width: 0`, itself a wrapping flex row) holding the name, the short name and the stance; the summary no longer wraps, so the tile is never alone on its line and long names (PSOE, BNG, EAJ-PNV at 375px) wrap inside the box beside the tile. The 48px minimum height, the disclosure and keyboard behaviour, the summary text and the identical treatment of every Party are unchanged; the stance stays right-aligned when it fits on the name's line.
- Load-failure check: the browser had no request blocking, so a local test proxy answered 404 for Party 4's logo. Two expected 404 console errors appear (the preload and the rendered `<img>`, since failed responses are not cached); recorded as an accepted Low in the risks doc.

