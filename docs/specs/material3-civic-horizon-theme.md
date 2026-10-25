# Feature Implementation Spec: Material 3 redesign with the Civic Horizon palette

## Source Feature

- `id`: material3-civic-horizon-theme
- `area`: web
- `depends_on`: landing-election-picker, questionnaire-important-flag, results-breakdown-evidence, share-link-open, methodology-page (all `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification + notes), `docs/design/civic-horizon.md` (palette, type scale, shapes, elevation, grid), `docs/design/questionnaire-prototype.png` (visual reference)

## Goal

Every web screen (Landing, Questionnaire, Results end screen, Methodology, Shared result, Not found) takes a Material Design 3 look built from the Civic Horizon colour roles, the Public Sans type scale, M3 shapes and tonal elevation. It has a light theme and a dark theme (`prefers-color-scheme`) and uses the M3 responsive grid. Behaviour, routes, requests, data flow and copy stay the same. The one exception is the Questionnaire's AI/privacy note, which becomes a card with a decorative shield and the title `Transparencia algorítmica y privacidad garantizada`. DESIGN.md is rewritten first, and `tokens.css` mirrors it.

## Decisions (user, 2026-10-25; not to be reopened)

1. Public Sans is the only typeface, Evidence quotes included. It is self-hosted, with no third-party request. Quotes are told apart by layout (a tinted block with a left border), not by a serif.
2. There are exactly two themes. Light uses the unprefixed roles of `civic-horizon.md`. Dark uses the `dark-*` roles via `prefers-color-scheme: dark`. The `light-*` set is not used.
3. The M3 grid replaces the 720px column: compact 0–599px, medium 600–839px, expanded 840px and up with a 1200px max. The Results breakdown stays stacked.
4. From the prototype, only the shield icon and the title on the Questionnaire's disclosure card are added. The topic pill, the `Inicio / N% completado / Finalización` labels, the political compass and the match chip are out of scope.
5. DESIGN.md is rewritten first and keeps the neutrality rules: identical party treatment, no winner styling, no party colours, no red/green on the scale, and disagree states in neutral slate.

## Planner Decisions (not dictated; validator judges against these)

- **Token naming.** `tokens.css` holds three groups.
  - M3 system tokens: `--md-sys-color-<role>`, `--md-sys-typescale-<role>` (a `font` shorthand) plus `--md-sys-typescale-<role>-tracking`, `--md-sys-shape-corner-<size>`.
  - App spacing and layout tokens.
  - A few semantic aliases that pick a different role per theme. Components use only `var(--…)` tokens.
- **Every width media query lives in `tokens.css`.** It switches layout tokens only, because CSS cannot use custom properties inside `@media`. `global.css` and `components.css` have no width media queries.
- **Card surface.** This follows the civic-horizon "Card Framing" rule. `--color-card` is `surface-container-lowest` in light and `surface-container-low` in dark. `--color-card-nested` (a disclosure inside a card) is `surface-container-low` in light and `surface-container` in dark.
- **Info / tertiary tonal pair.** It is used for `Baja cobertura` and the shield container.
  - Light: `--color-info-container` = `tertiary-fixed` #a2effd, `--color-on-info-container` = `on-tertiary-fixed-variant` #004f58. This matches the prototype's light chip.
  - Dark: `tertiary-container` #004f58 and `on-tertiary-container` #9eeffd. The dark set has no fixed roles, and a bright chip on a dark page would shout.
  - The UI has no "AI-generated" tag element today. Adding one would be a copy change, so none is added. The `.tag--info` class is the defined treatment if one is ever added.
- **Focus ring: 3px solid `secondary`, offset 2px.** This keeps the old rule that gold means focus and Important, and keeps it distinct from primary selection borders.
- **Buttons.**
  - Filled (`.button-primary`): Siguiente, Revisar mis respuestas, Reintentar, shared CTAs.
  - Outlined (`.button-secondary`, class kept so tests stay untouched): Saltar esta afirmación, Anterior, Volver a la última afirmación.
  - Tonal (new `.button-tonal`, secondary-container): only `Copiar enlace`. M3 uses secondary for "save" actions.
  - The DOM and visual order of the controls is unchanged (Siguiente first). The prototype's right-aligned Siguiente and its arrow are not copied, because CSS reordering would break focus order.
- **Scale option states** are selected with `:has(input[value="…"]:checked)`, with no markup change. The native radio is drawn with `appearance: none` (a circle in `currentColor` with a filled dot when checked) and goes back to `appearance: auto` under `forced-colors: active`. The old decorative grey-to-blue left border is dropped.
- **Statement card.** The Statement step is wrapped in `<div className="statement-card">` (Level 2). The h1, the Election name and the disclosure card stay outside it. The end screen gets no wrapper.
- **Disclosure title as `<h3>`.** An extra h2 would break `getByRole("heading", { level: 2 })` in the existing tests.
- **Type mapping.**
  - Headings: h1 is headline-lg (headline-lg-mobile at compact). Generic h2 is title-lg. The Statement h2 is headline-sm. h3 and h4 are title-md.
  - Text: body is body-lg. Notes, hints, legend, dates and the breakdown number are body-md (14px, not civic-horizon's 12px body-sm, which is too small for long privacy notes).
  - Buttons are title-md (16px/600). Badges are label-md. Progress and Election labels are label-lg.
- **Shield icon.** An original inline SVG (a stroked shield with a check), so no icon licence is involved.
- **Reading measure.** `main p, .plain-list, blockquote` get `max-inline-size: 75ch`. The Statement h2 gets `65ch`.
- **Font package.** `@fontsource-variable/public-sans@5.3.0` (OFL-1.1), imported as `wght.css` (normal style only, variable weights 100–900). Checked by the planner in a scratch install: it ships `files/public-sans-{latin,latin-ext,vietnamese}-wght-normal.woff2` (27 KB, 18 KB and 8 KB), loaded by `unicode-range`. Spanish text needs only the latin file. The italic CSS is not imported.

## Non-Goals

- Any change to API, Python, migrations, core logic, routes, request shape, state handling, copy (except the one title) or test behaviour.
- Topic pill, percentage/progress labels, political compass, match chip, arrow icons, logo or product name, party logos, an in-app theme toggle, a third theme, Level 3/4 surfaces (there are no sticky bars or dialogs), animations beyond the existing chevron.
- Editing accepted historical specs (they are superseded by this one).

## Job Story

When I open the voting advice tool on my phone or laptop, in daylight or dark mode,
I want a calm, legible, modern interface that treats every party the same,
so I can focus on the Statements and the Evidence without visual bias.

## Users And Permissions

- Voter (anonymous): same screens and permissions as before. The only new request is same-origin font files under `/assets/`. No request carries Answers.

## Acceptance Scenarios

### Scenario 1: light theme, Questionnaire at 375px
Given the OS is in light mode and the Voter opens a published Questionnaire at 375px
Then:
- the page background is `#f5faff`;
- the Statement step is a white card (24px radius, soft shadow);
- `Siguiente` is a pill with background `#004d64`, white label and height ≥ 48px;
- the five options show unselected outlines with no red or green;
- below the card a disclosure card shows a decorative shield in a `#a2effd` tile, the title `Transparencia algorítmica y privacidad garantizada`, then the unchanged NOTE text;
- every text uses Public Sans and there is no horizontal scroll.

### Scenario 2: scale states and Important
When the Voter picks each option in turn
Then:
- agree (`De acuerdo`, `Muy de acuerdo`) shows a `primary-container` fill, a 2px `primary` border and `on-primary-container` 600 text;
- neutral shows `surface-container-high` with `on-surface-variant`;
- disagree shows the `outline-variant` slate fill with `on-surface` text and a 2px `outline` border;
- every checked state also shows a filled radio dot.

When `Importante para mí` is pressed, it shows a `secondary-container` pill with a filled star and 600 text. Tab focus on any control shows a 3px `secondary` ring. Arrow keys still move within the radio group.

### Scenario 3: dark theme
Given the OS prefers dark
When any screen loads
Then:
- the page is `#0f1416` and cards are `#171d1e`;
- primary is `#65d3ff` with `#003546` labels;
- the Important pressed state is `#534400`/`#ffe082`;
- `Baja cobertura` is `#004f58`/`#9eeffd`;
- text pairs meet AA (table below), and form controls and scrollbars are dark (`color-scheme`).

### Scenario 4: grid
At 375px content spans 4 columns with 16px margins. At about 700px it spans 8 columns with 32px margins, and the Landing election list shows 2 columns. At 1280px `main` is 1200px wide and centred, with 48px margins, and content spans columns 2–11. The Statement wraps at about 65 characters or fewer. The Results breakdown stays stacked. `scrollWidth <= innerWidth` holds everywhere.

### Scenario 5: results and neutrality
On the end screen and on `/resultados#…`:
- every ranking row and breakdown position has identical classes and computed colours;
- no row is emphasised;
- bars are `primary` on a `surface-container-highest` track;
- `Baja cobertura` uses the info pair, and `Importante (cuenta el doble)` uses `secondary-container`;
- an opened position shows the quote in Public Sans in a tinted block with a 4px left border;
- the superseded notice is a neutral card;
- `Copiar enlace` is a tonal pill.

### Scenario 6: no third-party request, no Answers
Then the network shows only same-origin requests: the document, JS, CSS, `.woff2` under `/assets/`, and `GET /api/v1/...` ids. None carries Answers, and the console is clean.

## Repository Research

### Files Inspected
- `AGENTS.md`, `DESIGN.md`, `CONTEXT.md`, `CONSTRAINTS.md` (Client-side Matching; npm exact pins + "new runtime dependency MUST be justified in its feature spec"; Web Client Serving), `ARCHITECTURE.md` (Web Client lines on fonts, the 720px column, amber focus, Georgia), `PROGRESS.md`, `feature_list.json`, `docs/risks-and-open-questions.md` (no entry names this feature; DESIGN's "logo and product name" stays open), `docs/technical-discovery.md` (no CSS-in-JS, `src/ui` holds tokens), `docs/design/civic-horizon.md`, `docs/design/questionnaire-prototype.png`, `docs/specs/results-breakdown-evidence.md`, `docs/specs/share-link-open.md` (scratch recipe), `.agents/skills/github-flow/references/practical-notes.md`.
- `apps/web/{index.html,package.json,tsconfig.json,vite.config.ts}`, `src/main.tsx`, `src/ui/{tokens,global,components}.css`, every feature component (`LandingPage`, `QuestionnairePage`, `QuestionnaireFlow`, `ResultsRanking`, `ResultsBreakdown`, `ShareResults`, `SharedResultsPage`, `MethodologyPage`, `NotFoundPage`), and the class/heading/SVG assertions in all `*.test.tsx`.
- `src/ideology_app/web.py`: `/assets/*` is served with a 1-year immutable cache. `.woff2` gets the Python mimetypes type; browsers load fonts whatever the Content-Type, and the response has no `nosniff`.

### Existing Patterns To Follow
- `tokens.css` mirrors DESIGN.md front matter. CSS is plain and global (`components.css` by BEM-ish class). Spanish copy. Tests render `App` in `MemoryRouter` with a mocked `FetchLike`. Inline `aria-hidden` SVG (StarIcon). Exact-pinned npm deps with `npm ci`.

### Test Constraints Found (must keep passing unmodified)
- Class assertions: `questionnaire__election`, `questionnaire__note` (NOTE paragraph, end-screen notes, shared note), `questionnaire__hint`, `coverage-badge`, `ranking-legend`, `button-primary` / `button-secondary` (Revisar / Volver), `text-link`, `election-link`, `card` (Methodology Aviso), `card shared-notice`, `important-mark`, `evidence__quote`, `ranking-row`.
- Single-h2 queries on the Questionnaire. No `svg` or `img` in Methodology `main`, in ranking rows or in the breakdown (the chevron stays CSS). Only `.ranking-bar__fill` has inline `style`.

### Current Gaps
- No web font, no dark theme, no grid. Hard-coded `#ffffff` in `.button-primary`. The disclosure is a bare `<p>`.

## Technical Approach

### `apps/web/src/ui/tokens.css` (rewrite; header comment: "Mirrors DESIGN.md. Change DESIGN.md first.")

`:root` gets `color-scheme: light dark` and the font stack:

```css
--md-ref-typeface-plain: "Public Sans Variable", "Public Sans", system-ui, sans-serif;
```

Colour roles: one block for light, one `@media (prefers-color-scheme: dark) { :root { … } }` for dark.

| Token `--md-sys-color-*` | Light | Dark |
|---|---|---|
| primary / on-primary | #004d64 / #ffffff | #65d3ff / #003546 |
| primary-container / on-primary-container | #006684 / #a2e1ff | #004d64 / #bfe9ff |
| secondary / on-secondary | #715d02 / #ffffff | #e9c336 / #3a2f00 |
| secondary-container / on-secondary-container | #fade7d / #756107 | #534400 / #ffe082 |
| tertiary-container / on-tertiary-container | #006874 / #97e4f2 | #004f58 / #9eeffd |
| tertiary-fixed / on-tertiary-fixed-variant | #a2effd / #004f58 | same (fixed roles) |
| surface | #f5faff | #0f1416 |
| surface-container-lowest / -low / (plain) / -high / -highest | #ffffff / #eef4fa / #e8eff4 / #e2e9ef / #dde3e9 | #0a0f11 / #171d1e / #1b2122 / #262b2d / #303638 |
| on-surface / on-surface-variant | #161c21 / #3f484d | #dee4e5 / #bfc8cc |
| outline / outline-variant | #70787e / #bfc8cd | #899296 / #40484c |

Aliases (per theme):
- `--color-card`, `--color-card-nested`, `--color-info-container`, `--color-on-info-container` as in Planner Decisions.
- `--color-focus-ring: var(--md-sys-color-secondary)`.
- `--elevation-2`: `0 2px 8px -2px rgba(0,31,42,.08)` in light, `0 2px 8px -2px rgba(0,0,0,.4)` in dark.

Type scale. Each role is written as `--md-sys-typescale-<role>: <weight> <size>/<line> var(--md-ref-typeface-plain)` plus a `-tracking` token, in rem:

| Role | Weight | Size / line (px) | Tracking (px) |
|---|---|---|---|
| headline-lg | 600 | 32/40 | 0 |
| headline-lg-mobile | 600 | 26/34 | 0 |
| headline-sm | 500 | 24/32 | 0 |
| title-lg | 500 | 22/28 | 0 |
| title-md | 600 | 16/24 | .15 |
| body-lg | 400 | 16/24 | .5 |
| body-md | 400 | 14/20 | .25 |
| label-lg | 600 | 14/20 | .1 |
| label-md | 500 | 12/16 | .5 |

Shapes: `--md-sys-shape-corner-small: .25rem`, `-default: .5rem`, `-medium: .75rem`, `-large: 1rem`, `-extra-large: 1.5rem`, `-full: 9999px`.

Spacing: `--space-xs` 4px, `--space-sm` 8px, `--space-md` 16px, `--space-lg` 24px, `--space-xl` 32px.

Layout tokens:
- Compact (default): `--layout-max-width: 1200px; --layout-columns: 4; --layout-margin: 1rem; --layout-gutter: 1rem; --layout-content-column: 1 / -1; --page-title-font: var(--md-sys-typescale-headline-lg-mobile); --election-columns: 1; --card-padding: var(--space-md)`.
- `@media (min-width: 600px)`: 8 columns, margin 2rem, gutter 1.5rem, `--page-title-font: headline-lg`, `--election-columns: 2`, `--card-padding: var(--space-lg)`.
- `@media (min-width: 840px)`: 12 columns, margin 3rem, gutter 2rem, `--layout-content-column: 2 / span 10`, `--card-padding: var(--space-xl)`.

### `apps/web/src/ui/global.css`
- `body`:
  - colours: `background: var(--md-sys-color-surface)`, `color: on-surface`;
  - type: `font: var(--md-sys-typescale-body-lg)`, `letter-spacing: var(--md-sys-typescale-body-lg-tracking)`.
- `main`:
  - box: `box-sizing: border-box`, `max-width: var(--layout-max-width)`, `margin: 0 auto`, `padding: var(--space-lg) var(--layout-margin)`;
  - grid: `display: grid`, `grid-template-columns: repeat(var(--layout-columns), minmax(0, 1fr))`, `column-gap: var(--layout-gutter)`, `align-content: start`.
- `main > * { grid-column: var(--layout-content-column); min-width: 0 }`.
- Headings:
  - `h1`: `font: var(--page-title-font)`.
  - `h2`: title-lg.
  - `h3` and `h4`: title-md.
  - All take their tracking token.
- `main p, .plain-list, blockquote { max-inline-size: 75ch }`.

### `apps/web/src/ui/components.css` (restyle every existing class; shared rules)

**Cards (Level 1).**
- Covers `.card`, `.election-link`, `.ranking-row`, `.breakdown-row`, `.share`, `.shared-notice`.
- `background: var(--color-card)`, 1px `outline-variant` border, `corner-large`, `padding: var(--card-padding)` (`.election-link`, `.ranking-row` and `.breakdown-row` keep `--space-md`), no shadow.
- Hover on `.election-link`: `border-color: primary`.
- `.election-list` uses `grid-template-columns: repeat(var(--election-columns), minmax(0,1fr))`.

**`.statement-card` (Level 2).**
- `--color-card`, 1px `outline-variant` border, `corner-extra-large`, `box-shadow: var(--elevation-2)`, `padding: var(--card-padding)`, margin-bottom `--space-lg`.
- `.questionnaire__statement`: headline-sm, `max-inline-size: 65ch`.

**`.disclosure-card`.**
- `surface-container-low`, 1px `outline-variant`, `corner-large`, padding `--space-md`.
- Flex layout, gap `--space-md`, `align-items: flex-start`.
- `.disclosure-card__icon`: 40×40 `corner-medium` tile, `--color-info-container` background, shield in `--color-on-info-container`, `flex: none`.
- `.disclosure-card__title`: label-lg (14px/600, as in the prototype), `on-surface`, `margin: 0 0 var(--space-xs)`.
- The text keeps the `questionnaire__note` class (body-md, `on-surface-variant`, `margin: 0`).

**Buttons.**
- Shared: `min-height: 48px`, `padding: 0 var(--space-lg)`, `corner-full`, title-md, `cursor: pointer`.
- `.button-primary`: `primary` background, `on-primary` label. Hover is `color-mix(in srgb, var(--md-sys-color-on-primary) 8%, var(--md-sys-color-primary))`. `:disabled` (M3) is `color-mix(in srgb, var(--md-sys-color-on-surface) 12%, transparent)` with the label at 38% (WCAG-exempt inactive control), `cursor: not-allowed`.
- `.button-secondary` (outlined): transparent background, 1px `outline` border, `primary` label. Hover is an 8% primary state layer via `color-mix(... primary 8%, transparent)`.
- `.button-tonal`: `secondary-container` background, `on-secondary-container` label. Hover mixes 8% `on-secondary-container`.
- `a.button-primary` stays inline-flex.

**Focus.**
- `a, button, input, summary` `:focus-visible` and `.scale-option:has(input:focus-visible)`: `outline: 3px solid var(--color-focus-ring); outline-offset: 2px`.
- The existing `h2[tabindex="-1"]` and `main h1[tabindex="-1"]` no-outline rules stay.
- `a` is `primary`; `.text-link` and `.back-link` keep 48px.

**Progress.**
- Label: label-lg, `on-surface-variant`.
- Bar: 8px, `corner-full`, `surface-container-highest` track, `primary` value (all three pseudo-elements).
- `.questionnaire__election`: label-lg, `on-surface-variant`.

**`.scale`.**
- Gap `--space-sm`.

**`.scale-option` base.**
- Box: `min-height: 48px` (56px is fine), padding `--space-md`.
- Colours: `--color-card` background, 1px `outline-variant` border, `on-surface` body-lg text.
- Shape: `corner-default`.
- Hover: `border-color: outline`.

**`.scale-option` radio indicator.**
- `input`: `appearance: none`, 20×20, `border: 2px solid currentColor`, `border-radius: 50%`, colour `on-surface-variant`.
- `input:checked`: `background: radial-gradient(circle, currentColor 0 4px, transparent 4.5px)`.
- `@media (forced-colors: active) { .scale-option input { appearance: auto } }`.

**`.scale-option` checked states** (2px border with the padding reduced by 1px, `font-weight: 600`).
- Agree (`value="1"`, `"2"`): `primary-container` background, `on-primary-container` text, `primary` border; the input uses `currentColor`.
- Neutral (`"0"`): `surface-container-high`, `on-surface-variant`, `outline` border.
- Disagree (`"-1"`, `"-2"`): `outline-variant` background, `on-surface` text, `outline` border.

**Important.**
- `.important-row` is a flex wrapper (wrap, `align-items: center`, gap `--space-sm` `--space-md`, margin-bottom `--space-md`); the hint keeps `margin: 0`.
- `.important-toggle`: pill, 48px, transparent background, 1px `outline`, `on-surface`, title-md at weight 500. Star: stroke `secondary`, no fill.
- `[aria-pressed="true"]`: `secondary-container` background, `on-secondary-container` text, 1px `secondary` border, 600. Star filled and stroked `secondary`.
- `.important-mark`: pill, `secondary-container` / `on-secondary-container`, label-md, padding 2px 10px.

**Ranking.**
- Name: title-md. Short name: body-md `on-surface-variant`. Percent: title-md, tabular-nums.
- Bar: 8px pill, `surface-container-highest` track, `primary` fill.
- Meta: body-md `on-surface-variant`. Legend: body-md `on-surface-variant`.
- `.coverage-badge`: pill, `--color-info-container` / `--color-on-info-container`, label-md, padding 2px 10px, no border.

**Breakdown.**
- `.breakdown-row__number`: label-lg `on-surface-variant`. `__statement` (h4): title-md.
- `.position`: `--color-card-nested`, 1px `outline-variant`, `corner-medium`.
- Summary: 48px. Chevron: `on-surface-variant`. Short name: `on-surface-variant`.
- `.evidence__quote`: body-lg, `on-surface`, `surface-container-high` background, `border-left: 4px solid var(--md-sys-color-outline)`, padding `--space-sm` `--space-md`, radius `0 corner-default corner-default 0`, `overflow-wrap: anywhere`. No serif and no italic.

**Share.**
- `.share` is a card. `.share__field`: 48px, 1px `outline`, `corner-small`, `--color-card`, `on-surface`, `font: inherit`, 16px.
- The `.share .button-secondary` margin rule becomes `.share .button-tonal`.

**Notes and hints.**
- `.questionnaire__note`, `.questionnaire__hint`, `.election-link__date`: body-md `on-surface-variant`.
- `.questionnaire__skipped`: body-lg `on-surface`, no longer italic (no italic face is loaded; this avoids a synthetic oblique).

### Font
- `apps/web/package.json` `dependencies`: `"@fontsource-variable/public-sans": "5.3.0"` (exact). Update `package-lock.json` with `npm install` in the repo, then check that `npm ci` passes.
- Justification (CONSTRAINTS npm rule):
  - self-hosting with no third-party request;
  - versioned provenance;
  - OFL-1.1 permits bundling;
  - about 27 KB downloaded for Spanish.
- Alternatives rejected: the Google Fonts CDN is a third-party request; hand-vendored woff2 files have no provenance.
- `src/main.tsx`: `import "@fontsource-variable/public-sans/wght.css";` before `./ui/global.css`. Vite emits the woff2 files to `dist/assets/` with hashed names (`vite/client` types cover `*.css`). If typecheck rejects the bare import, use `@import "@fontsource-variable/public-sans/wght.css";` as the first line of `global.css` instead.
- `index.html`: add `<meta name="color-scheme" content="light dark" />` so there is no white flash in dark mode.

### Markup (only these changes)
- `QuestionnaireFlow.tsx` `StatementStep`:
  - wrap the progress label through the controls in `<div className="statement-card">`;
  - wrap the Important button and the hint in `<div className="important-row">`;
  - replace `<p className="questionnaire__note">{NOTE}</p>` with:
    ```tsx
    <section className="disclosure-card" aria-labelledby="ai-privacy-title">
      <span className="disclosure-card__icon"><ShieldIcon /></span>
      <div>
        <h3 id="ai-privacy-title" className="disclosure-card__title">Transparencia algorítmica y privacidad garantizada</h3>
        <p className="questionnaire__note">{NOTE}</p>
      </div>
    </section>
    ```
  - `ShieldIcon` is like `StarIcon`: 24×24, `aria-hidden="true"`, `focusable="false"`, `fill="none"`, `stroke="currentColor"`, `strokeWidth="1.75"`, `strokeLinejoin="round"`, `strokeLinecap="round"`, paths `M12 3l7 3v5c0 4.5-3 8.3-7 9.5-4-1.2-7-5-7-9.5V6z` and `M9 12l2 2 4-4`.
  - DOM order is unchanged.
- `ShareResults.tsx`: `Copiar enlace` className becomes `button-tonal`.
- No other TSX changes. In particular, no className is added to party rows.

## Expected File Changes
- Modify:
  - `DESIGN.md` (first);
  - `apps/web/src/ui/{tokens,global,components}.css`;
  - `apps/web/src/main.tsx`, `apps/web/index.html`, `apps/web/package.json`, `package-lock.json`;
  - `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`, `apps/web/src/features/share/ShareResults.tsx`;
  - `apps/web/src/features/questionnaire/QuestionnairePage.test.tsx` (add one test only);
  - `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`.
- Create: `apps/web/src/ui/design-tokens.test.tsx`.
- Unchanged: every other test, all Python, `packages/core`, accepted specs, `docs/design/*`.

## Visual Design Impact
- UI: yes, every screen. Source: the rewritten `DESIGN.md`, derived from `docs/design/civic-horizon.md`. The prototype is a reference only.
- States to handle: loading/error/empty on Landing, Questionnaire and Shared; disabled Siguiente; the three checked tones; Important on and off; low coverage; open and closed position; URL/upload/no-stance Evidence; the share fallback field; the superseded notice; Not found. Each in light and dark.
- New design artifact: none (DESIGN.md is the artifact).

### WCAG 2.1 AA pairs (planner-computed; the implementer re-checks with computed styles)

| Pair | Light | Dark |
|---|---|---|
| on-surface / surface, card, nested | 16.4 / 17.2 / 15.5 | 14.4 / 13.3 / 12.7 |
| on-surface-variant / surface, card, nested | 8.9 / 9.4 / 8.4 | 10.9 / 10.0 / 9.6 |
| primary (links) / surface, card | 8.9 / 9.4 | 10.9 / 10.0 |
| on-primary / primary (filled) | 9.4 | 7.7 |
| on-primary-container / primary-container (agree) | 4.56 | 7.3 |
| on-surface-variant / surface-container-high (neutral) | 7.6 | 8.4 |
| on-surface / outline-variant (disagree) | 10.1 | 7.3 |
| on-secondary-container / secondary-container (tonal, Important, mark) | 4.56 | 7.4 |
| on-info / info-container (Baja cobertura) | 7.2 | 7.2 |
| on-surface / surface-container-high (quote) | 14.0 | 11.1 |
| Non-text ≥ 3: outline border / card, surface | 4.5 / 4.3 | 5.4 / 5.8 |
| Non-text ≥ 3: focus ring secondary / surface, card | 6.1 / 6.4 | 10.9 / 10.0 |
| Non-text ≥ 3: primary border / card | 9.4 | 10.0 |

Rules: never put `outline` or `outline-variant` under text. The secondary star on secondary-container is 4.8 (light) and 5.6 (dark).

## Durable Documentation Impact
- `DESIGN.md`: rewrite (task 1).
  - Front matter:
    - `name`;
    - `designAssets.sourceOfTruth: [docs/design/civic-horizon.md]`, `generatedConcepts: [docs/design/questionnaire-prototype.png]`;
    - `colors` (light roles used) and `colorsDark` (the matching `dark-*` values);
    - `typography` (the roles used), `rounded`, `spacing`, `layout` (breakpoints, columns, margins, gutters, max 1200);
    - `components` (button-primary, button-secondary/outlined, button-tonal, scale-option states, important-toggle, card, statement-card, coverage-badge, important-mark, evidence-quote).
  - Prose keeps: Overview (neutral), Product Feel, the identical party treatment, no winner styling, no party colours, no red/green, the meaning never by colour alone, 48px targets, WCAG AA, Evidence as first-class.
  - Prose replaces: Inter/Georgia → Public Sans only (quotes by layout); 720px → the M3 grid (breakdown stacked); amber → secondary gold for focus, Important and tonal; the themes section; the elevation levels used (0–2); component specs as in this spec; the disclosure card with its shield.
  - Open Design Questions keep "logo and product name" and "party logos".
- `ARCHITECTURE.md` Web Client:
  - the `global.css` line: grid, Public Sans and the font import;
  - Landing: "No web font is loaded" becomes "Public Sans is self-hosted from `/assets/`; no request leaves the origin";
  - Questionnaire: the statement card, the disclosure card with its title, the restyled scale states (replacing the "grey-to-blue left border" and "amber" wording), Georgia → Public Sans, the `button-tonal` share.
- `CONSTRAINTS.md`: add a section `## Web Client Styling`:
  - "Component CSS MUST take colours, font families and shadows only from `apps/web/src/ui/tokens.css` (enforced by `design-tokens.test.tsx`). Reason: two themes and one auditable neutral palette."
  - "The web client MUST NOT load fonts, styles, scripts or images from another origin. Reason: privacy (no third-party sees Voters) and the invariant that only same-origin requests carry ids."
- `docs/risks-and-open-questions.md`: add under Implementation-Time Questions: "Settled (`material3-civic-horizon-theme`, user decision 2026-10-25): Civic Horizon M3 theme. Light = unprefixed roles, dark = `dark-*` via `prefers-color-scheme` (no in-app toggle); Public Sans self-hosted (`@fontsource-variable/public-sans`), quotes by layout; M3 grid, max 1200px." No existing entry names this feature.
- `AGENTS.md`, `CONTEXT.md`, `README.md`: not needed (no workflow, term or command change).

## Implementation Plan
1. Rewrite `DESIGN.md`.
2. Tokens, the font dependency and import, `global.css`.
3. `components.css` restyle.
4. The two TSX edits, the new tests.
5. `CI=true ./init.sh`.
6. Browser walkthrough.
7. Docs and evidence.

## Implementation Tasks
- [ ] DESIGN.md rewrite as above.
- [ ] `npm install -w @ideology-app/web @fontsource-variable/public-sans@5.3.0 --save-exact`. Confirm the exact pin in `package.json` and the lockfile.
- [ ] `tokens.css`, `global.css` and `components.css` per Technical Approach. Remove `--font-quote`, `--reading-width` and the old colour tokens.
- [ ] `QuestionnaireFlow.tsx` wrappers, disclosure card and ShieldIcon. `ShareResults.tsx` class.
- [ ] New QuestionnairePage test: `getByRole("region", { name: "Transparencia algorítmica y privacidad garantizada" })` contains:
  - an h3 with that text;
  - the unchanged NOTE in `p.questionnaire__note`;
  - one `svg[aria-hidden="true"]`.
  It also checks that the region follows the radiogroup in DOM order and is absent on the end screen.
- [ ] `ui/design-tokens.test.tsx`:
  - loads the CSS via `import.meta.glob("./*.css", { query: "?raw", import: "default", eager: true })`;
  - for every file but `tokens.css`, asserts there is no `#hex`, no `rgb(`/`hsl(` and no `font-family:`/`font:` value without `var(` or `inherit`;
  - asserts `tokens.css` contains `prefers-color-scheme: dark`, `Public Sans` and no `Georgia`/`Inter`;
  - asserts no CSS file has `url(http` or `@import url(` to another origin.
- [ ] Docs per Documentation Impact.

## Verification Plan
- `CI=true ./init.sh` exits 0: pytest unchanged (1454), Vitest 350 plus the new tests with no existing test edited, typecheck, build. `ls apps/web/dist/assets/*.woff2` lists the Public Sans files.
- Greps:
  - `grep -rnE "#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(" apps/web/src/ui/global.css apps/web/src/ui/components.css` → nothing;
  - `grep -rnE "Georgia|Inter,|720px|fonts\.(googleapis|gstatic)" apps/web/src apps/web/index.html` → nothing;
  - `grep -rn "dangerouslySetInnerHTML\|localStorage\|sessionStorage" apps/web/src` → tests only or nothing (as before).
- No E2E harness exists. Vitest and the real-browser walk cover the feature.
- **Data:**
  - (A) copy `data/ideology.db` to `$SCRATCH/real.db` (real 26 Statements, 9 Parties, long names; never serve or modify the committed file);
  - (B) the `share-link-open` scratch recipe (FakeProvider pipeline run twice), for the superseded notice and an upload/URL/no-stance mix.
  - Temporary `.claude/launch.json` entries `tmp-material3-a` and `tmp-material3-b` on free ports (never 8000), per practical-notes.
- **Real browser** at 375×812, about 700×900 and 1280×800, each in light and in dark (DevTools/Playwright `prefers-color-scheme` emulation):
  - Landing:
    - AI card;
    - election cards (1 column at 375, 2 at 700 and up);
    - the loading state (throttle), and the error and `Reintentar` (stop the server).
  - Questionnaire:
    - statement card and disclosure card;
    - each scale state, Important on and off, disabled Siguiente;
    - keyboard: Tab to the group, arrows, Space, the focus ring visible on every control; VoiceOver or the accessibility tree announces `radio, Muy de acuerdo, 5 of 5` style labels and the Important toggle state;
    - Anterior, Saltar, the end screen (rate a few so `Baja cobertura` shows), open a URL position and an upload position, `Copiar enlace` (copied and fallback);
    - Revisar mis respuestas, Volver a la última afirmación.
  - Methodology (`/metodologia`), Not found (`/nope`).
  - Shared result: a fresh link (A), a superseded link (B), malformed `#zzz`.
  - At every stop:
    - `document.documentElement.scrollWidth <= innerWidth`;
    - `getComputedStyle(body).fontFamily` starts with `"Public Sans Variable"` and `document.fonts.check('16px "Public Sans Variable"')` is true;
    - the quote's computed font is Public Sans;
    - `main` is 1200px wide at 1280 and its content starts at column 2;
    - the Statement line length is about 65ch or less;
    - party rows have identical computed background, border and colour.
  - Contrast: spot-check the table pairs from computed colours in both themes (DevTools contrast or a small `getComputedStyle` script); any failure blocks.
  - Network: only same-origin requests (document, `/assets/*.js|css|woff2`, `/api/v1/elections`, `/api/v1/elections/{id}`, `/api/v1/dataset-versions/{id}`); no `?` or `#` with Answers in any request, no other origin. Console: no errors or warnings.
- **Cleanup:** stop servers, `git checkout .claude/launch.json`, delete `$SCRATCH`, `git status` shows only feature files.

## Evidence To Capture
- `init.sh` step results, the Vitest count and new test names, the grep results, the woff2 asset names and sizes.
- The browser name and version, the 3 widths × 2 themes, the screens walked, the contrast spot-check values, the network origin list, the console result, the scroll-width checks. Record them only in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist
- [ ] DESIGN.md was rewritten first and keeps every neutrality rule. `tokens.css` mirrors it. No hard-coded colour or font outside `tokens.css` (the test and grep pass).
- [ ] Public Sans comes from same-origin `/assets/`, quotes included. No serif anywhere. The dependency is exact-pinned and justified.
- [ ] Light and dark match the role table. The light-* set is unused. The AA table holds in the browser.
- [ ] The grid behaves at 375, 700 and 1280. Max 1200px. The breakdown is stacked. No horizontal scroll.
- [ ] Component mapping as specified: filled, outlined and tonal buttons; scale tones (disagree slate, no red or green); Important on secondary; badge on the info tertiary pair; focus ring secondary; cards and elevation.
- [ ] The disclosure card has the shield (aria-hidden), the exact title and the unchanged text. No other copy changed. Topic pill, progress labels, compass and chip are absent.
- [ ] Party rows and positions are identical, with no winner emphasis. Existing tests are unmodified. Only the listed files changed.
- [ ] The browser walk ran in both themes at all three widths: console clean, same-origin only, no Answers in any request. Docs and evidence are updated.

## As Implemented (implementer, 2026-10-25)

Deviations found during implementation, each narrow and needed to meet the spec's own acceptance criteria:

- **Statement measure `30em`, not `65ch`.** In the browser, `65ch` (the width of a "0" at 24px, about 968px) let the 26 real Statements reach 78 characters per line at 1280px. `30em` (720px) gives at most 66, meeting Scenario 4's "about 65 characters or fewer". Running text keeps `75ch` as specified (recorded as a Low finding).
- **`apps/web/vite.config.ts`** gets `test.css.include: [/[?&]raw(?:&|$)/]`. Vitest replaces every CSS import with an empty string by default, so the `?raw` glob in `design-tokens.test.tsx` read `""` and its assertions passed vacuously. Only `?raw` CSS imports are let through; component CSS imports stay empty in tests.
- **`global.css`: `main > * > :last-child { margin-bottom: 0 }`.** `main` is now a grid, and a grid item does not collapse its last child's bottom margin with its own, so sections gained an extra 16px gap (for example on `/metodologia`).
- **`.scale-option input { font: inherit }`.** The radio inputs computed `Arial` (the UA default for form controls); now every element computes Public Sans.
