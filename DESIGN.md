---
name: ideology-app (Civic Horizon)
description: Neutral, civic, mobile-first voting advice tool on Material Design 3 with the Civic Horizon palette. Calm and trustworthy; no party colours in the base UI.
designAssets:
  sourceOfTruth:
    - docs/design/civic-horizon.md
  generatedConcepts:
    - docs/design/questionnaire-prototype.png
themes:
  light: "colors (the unprefixed Civic Horizon roles)"
  dark: "colorsDark (the dark-* Civic Horizon roles), via prefers-color-scheme: dark"
  unused: "the light-* Civic Horizon roles"
colors:
  primary: "#004d64"
  on-primary: "#ffffff"
  primary-container: "#006684"
  on-primary-container: "#a2e1ff"
  secondary: "#715d02"
  on-secondary: "#ffffff"
  secondary-container: "#fade7d"
  on-secondary-container: "#756107"
  tertiary-container: "#006874"
  on-tertiary-container: "#97e4f2"
  tertiary-fixed: "#a2effd"
  on-tertiary-fixed-variant: "#004f58"
  surface: "#f5faff"
  surface-container-lowest: "#ffffff"
  surface-container-low: "#eef4fa"
  surface-container: "#e8eff4"
  surface-container-high: "#e2e9ef"
  surface-container-highest: "#dde3e9"
  on-surface: "#161c21"
  on-surface-variant: "#3f484d"
  outline: "#70787e"
  outline-variant: "#bfc8cd"
colorsDark:
  primary: "#65d3ff"
  on-primary: "#003546"
  primary-container: "#004d64"
  on-primary-container: "#bfe9ff"
  secondary: "#e9c336"
  on-secondary: "#3a2f00"
  secondary-container: "#534400"
  on-secondary-container: "#ffe082"
  tertiary-container: "#004f58"
  on-tertiary-container: "#9eeffd"
  tertiary-fixed: "#a2effd"
  on-tertiary-fixed-variant: "#004f58"
  surface: "#0f1416"
  surface-container-lowest: "#0a0f11"
  surface-container-low: "#171d1e"
  surface-container: "#1b2122"
  surface-container-high: "#262b2d"
  surface-container-highest: "#303638"
  on-surface: "#dee4e5"
  on-surface-variant: "#bfc8cc"
  outline: "#899296"
  outline-variant: "#40484c"
semantic:
  card: { light: "{colors.surface-container-lowest}", dark: "{colorsDark.surface-container-low}" }
  card-nested: { light: "{colors.surface-container-low}", dark: "{colorsDark.surface-container}" }
  info-container: { light: "{colors.tertiary-fixed}", dark: "{colorsDark.tertiary-container}" }
  on-info-container: { light: "{colors.on-tertiary-fixed-variant}", dark: "{colorsDark.on-tertiary-container}" }
  focus-ring: "secondary"
  elevation-2: { light: "0 2px 8px -2px rgba(0, 31, 42, 0.08)", dark: "0 2px 8px -2px rgba(0, 0, 0, 0.4)" }
typography:
  fontFamily: "Public Sans (self-hosted variable font), system-ui, sans-serif"
  headline-lg: { fontSize: 32px, lineHeight: 40px, fontWeight: 600, letterSpacing: 0px }
  headline-lg-mobile: { fontSize: 26px, lineHeight: 34px, fontWeight: 600, letterSpacing: 0px }
  headline-sm: { fontSize: 24px, lineHeight: 32px, fontWeight: 500, letterSpacing: 0px }
  title-lg: { fontSize: 22px, lineHeight: 28px, fontWeight: 500, letterSpacing: 0px }
  title-md: { fontSize: 16px, lineHeight: 24px, fontWeight: 600, letterSpacing: 0.15px }
  body-lg: { fontSize: 16px, lineHeight: 24px, fontWeight: 400, letterSpacing: 0.5px }
  body-md: { fontSize: 14px, lineHeight: 20px, fontWeight: 400, letterSpacing: 0.25px }
  label-lg: { fontSize: 14px, lineHeight: 20px, fontWeight: 600, letterSpacing: 0.1px }
  label-md: { fontSize: 12px, lineHeight: 16px, fontWeight: 500, letterSpacing: 0.5px }
rounded:
  small: 0.25rem
  default: 0.5rem
  medium: 0.75rem
  large: 1rem
  extra-large: 1.5rem
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
layout:
  maxWidth: 1200px
  compact: { range: "0-599px", columns: 4, margin: 16px, gutter: 16px, content: "1 / -1" }
  medium: { range: "600-839px", columns: 8, margin: 32px, gutter: 24px, content: "1 / -1" }
  expanded: { range: "840px+", columns: 12, margin: 48px, gutter: 32px, content: "2 / span 10" }
  statementMeasure: "30em (about 65 characters of Public Sans at headline-sm; 65ch would fit about 80)"
  textMeasure: 75ch
components:
  button-primary: { style: filled, backgroundColor: primary, textColor: on-primary, rounded: full, minHeight: 48px, typography: title-md }
  button-secondary: { style: outlined, border: "1px outline", textColor: primary, rounded: full, minHeight: 48px, typography: title-md }
  button-tonal: { style: tonal, backgroundColor: secondary-container, textColor: on-secondary-container, rounded: full, minHeight: 48px, typography: title-md }
  card: { level: 1, backgroundColor: card, border: "1px outline-variant", rounded: large, shadow: none }
  statement-card: { level: 2, backgroundColor: card, border: "1px outline-variant", rounded: extra-large, shadow: elevation-2 }
  disclosure-card: { backgroundColor: surface-container-low, border: "1px outline-variant", rounded: large, icon: "shield on info-container, rounded medium" }
  scale-option:
    base: { backgroundColor: card, border: "1px outline-variant", textColor: on-surface, rounded: default, minHeight: 48px }
    agree-checked: { backgroundColor: primary-container, border: "2px primary", textColor: on-primary-container, fontWeight: 600 }
    neutral-checked: { backgroundColor: surface-container-high, border: "2px outline", textColor: on-surface-variant, fontWeight: 600 }
    disagree-checked: { backgroundColor: outline-variant, border: "2px outline", textColor: on-surface, fontWeight: 600 }
  important-toggle:
    off: { backgroundColor: transparent, border: "1px outline", textColor: on-surface, star: "outline, stroke secondary", rounded: full }
    on: { backgroundColor: secondary-container, border: "1px secondary", textColor: on-secondary-container, star: "filled secondary", fontWeight: 600 }
  coverage-badge: { backgroundColor: info-container, textColor: on-info-container, rounded: full, typography: label-md }
  important-mark: { backgroundColor: secondary-container, textColor: on-secondary-container, rounded: full, typography: label-md }
  evidence-quote: { backgroundColor: surface-container-high, textColor: on-surface, borderLeft: "4px outline", typography: body-lg, fontStyle: normal }
  progress: { track: surface-container-highest, value: primary, height: 8px, rounded: full }
  ranking-bar: { track: surface-container-highest, fill: primary, height: 8px, rounded: full }
---

# Design Direction

## Overview

A calm, civic tool built on Material Design 3 with the Civic Horizon palette (`docs/design/civic-horizon.md`). The UI must never suggest a preference: identical treatment for every party, and no party colours anywhere.

## Existing Design Assets

- `docs/design/civic-horizon.md`: the source palette, type scale, shapes, elevation and grid. This file picks the parts the app uses; `apps/web/src/ui/tokens.css` mirrors this file.

## Generated Concept Images

- `docs/design/questionnaire-prototype.png`: a visual reference for the Questionnaire. Only its look and its disclosure card (shield and title) are adopted; its topic pill, `Inicio / N% completado / Finalización` labels and right-aligned arrow button are not.

## Product Feel

Trustworthy, quiet, readable, like a good public-service website. Evidence (quotes) is a first-class element, not hidden detail.

## Neutrality Rules (unchanged)

- Every party row and every party position looks the same, in every state. No winner styling: the first row is not emphasised (no number, medal, colour or size change).
- No party colours for bars, backgrounds or text. Party logos are an open question.
- No red/green on the agreement scale. Disagree states use a neutral slate (`outline-variant`), never red.
- The meaning of the scale never relies on colour alone: the label text and the filled radio dot carry it.

## Themes

Exactly two themes, chosen by the operating system through `prefers-color-scheme`; there is no in-app toggle.

- **Light** uses the unprefixed Civic Horizon roles (`colors` above).
- **Dark** uses the `dark-*` roles (`colorsDark` above).
- The `light-*` roles of the source are not used.
- `color-scheme: light dark` is declared so native controls and scrollbars follow the theme.

## Colors

- **Primary** (dark teal / bright cyan in dark): filled buttons, links, progress, ranking bars, agree states.
- **Secondary** (gold): focus ring, the Important flag (toggle and mark) and the tonal `Copiar enlace` button. Gold means "focus" or "marked by you", never a party.
- **Tertiary / info pair**: `Baja cobertura` and the shield tile on the disclosure card. Light uses `tertiary-fixed` with `on-tertiary-fixed-variant`; dark uses `tertiary-container` with `on-tertiary-container`. An "AI-generated" tag, if one is ever added, uses the same pair.
- **Surfaces**: the page is `surface`; cards are `surface-container-lowest` in light and `surface-container-low` in dark; a disclosure nested inside a card is one tier up.
- Never put text on `outline` or `outline-variant` except the disagree state, whose pair is checked below.

## Typography

**Public Sans** is the only typeface, self-hosted from the app's own `/assets/` (no third-party font request). Evidence quotes also use it; they are told apart by layout (a tinted block with a 4px left border), not by a serif or italics. No italic face is loaded.

- `h1` (page title): headline-lg (headline-lg-mobile below 600px).
- Statement text (`h2` on the Questionnaire): headline-sm, at most about 65 characters per line (`max-inline-size: 30em`; `65ch` measures the wide "0" glyph and would fit about 80 Public Sans characters).
- Other `h2`: title-lg. `h3`, `h4`: title-md.
- Body: body-lg. Notes, hints, legends, dates and the breakdown number: body-md in `on-surface-variant` (14px rather than the source's 12px body-sm, which is too small for long privacy notes).
- Buttons: title-md. Badges: label-md. Progress and Election labels: label-lg.
- Running text is capped at 75 characters per line.

## Layout

The M3 responsive grid replaces the old 720px column. `main` is a CSS grid, at most 1200px wide and centred.

- **Compact (0–599px):** 4 columns, 16px margins, 16px gutters; content spans all columns. Landing elections in 1 column.
- **Medium (600–839px):** 8 columns, 32px margins, 24px gutters; content spans all columns. Landing elections in 2 columns.
- **Expanded (840px+):** 12 columns, 48px margins, 32px gutters; content spans columns 2–11.

One Statement per screen in the Questionnaire. The Results breakdown stays stacked at every width. No horizontal scroll at any width.

## Elevation & Depth

Tonal elevation, as in the source. Only levels 0–2 are used (there are no sticky bars or dialogs).

- **Level 0:** the `surface` page.
- **Level 1:** cards (`card` surface, 1px `outline-variant`, no shadow): the Landing AI card, election links, ranking rows, breakdown rows, the share card, the superseded notice.
- **Level 2:** the Questionnaire's Statement card, with the soft ambient `elevation-2` shadow.

## Shapes

- Cards: large (16px). The Statement card: extra-large (24px).
- Scale options: default (8px) inside the extra-large Statement card.
- Buttons, the Important toggle, badges and progress/ranking bars: full pill.
- Nested positions: medium (12px). Text field: small (4px).
- Minimum tap target 48px for every control and text link.

## Components

- **Buttons.** Filled (`button-primary`): Siguiente, Revisar mis respuestas, Reintentar, shared-result CTAs. Outlined (`button-secondary`): Saltar esta afirmación, Anterior, Volver a la última afirmación. Tonal (`button-tonal`): only `Copiar enlace`. Hover adds an 8% state layer. Disabled filled buttons use the M3 12% `on-surface` container with a 38% label. DOM order stays the reading and focus order (Siguiente first).
- **Statement card** (Level 2): the progress label and bar, the Statement, the Important row (toggle and hint), the 5-option scale, the skipped note and the controls.
- **Scale option**: a full-width radio row with its label. A custom circle radio (filled dot when checked; the native radio returns under forced colours). Checked states: agree → `primary-container` with a 2px `primary` border and `on-primary-container` text; neutral → `surface-container-high` with `on-surface-variant`; disagree → slate `outline-variant` with `on-surface` text and a 2px `outline` border. All checked states use weight 600.
- **Important toggle**: an outlined pill with an outline star in `secondary`; pressed, it becomes a `secondary-container` pill with a filled star and weight 600. The star shape and `aria-pressed` carry the state.
- **Disclosure card** (Questionnaire only, below the Statement card): a decorative shield (`aria-hidden`) in a 40px info tile, the title `Transparencia algorítmica y privacidad garantizada` and the unchanged AI/privacy note.
- **Ranking row**: party name + short name, percentage, a `primary` bar on a `surface-container-highest` track, and a `Baja cobertura` badge (info pair) when it applies. Every row looks the same.
- **Breakdown row**: the Statement, the Voter's answer (Saltada / `Importante (cuenta el doble)` mark on `secondary-container`), and each party's position in ranking order as a native disclosure revealing the Evidence quote and its locator: a link to `url#page=N`, or the page alone for uploaded documents; `Sin posición en el programa` for no stance.
- **Evidence quote**: Public Sans body-lg on `surface-container-high` with a 4px `outline` left border; never serif, never italic.
- **Share card**: `Copiar enlace` (tonal) copies the Share Link to the clipboard; if copying fails, the link is shown in a read-only field, focused and selected, to copy by hand. A short note says that nothing is stored on any server and that anyone with the link can see the answers.
- **Focus**: a 3px solid `secondary` ring with a 2px offset on every link, button, summary and scale option.

## Core Screens

1. Landing: choose an Election, a short methodology summary, and an "AI-generated" disclosure card.
2. Questionnaire: Statement card plus disclosure card.
3. Results: ranking + per-Statement breakdown + share.
4. Methodology: how Statements and Positions are generated and validated.
5. Shared result (`/resultados#…`): read-only ranking + breakdown from a Share Link, a neutral superseded notice (a card, not an alert), and friendly link errors.
6. Not found.

## Accessibility Baseline

WCAG 2.1 AA contrast for every text pair in both themes, and at least 3:1 for borders that identify a control and for the focus ring. Checked pairs (light / dark):

| Pair | Light | Dark |
|---|---|---|
| on-surface on surface / card | 16.4 / 17.2 | 14.4 / 13.3 |
| on-surface-variant on surface / card | 8.9 / 9.4 | 10.9 / 10.0 |
| primary (links) on surface / card | 8.9 / 9.4 | 10.9 / 10.0 |
| on-primary on primary | 9.4 | 7.7 |
| on-primary-container on primary-container (agree) | 4.56 | 7.3 |
| on-surface-variant on surface-container-high (neutral) | 7.6 | 8.4 |
| on-surface on outline-variant (disagree) | 10.1 | 7.3 |
| on-secondary-container on secondary-container | 4.56 | 7.4 |
| on-info on info-container (Baja cobertura) | 7.2 | 7.2 |
| on-surface on surface-container-high (quote) | 14.0 | 11.1 |
| outline border on card / surface (≥ 3) | 4.5 / 4.3 | 5.4 / 5.8 |
| focus ring secondary on surface / card (≥ 3) | 6.1 / 6.4 | 10.9 / 10.0 |

The scale is a native radio group usable by keyboard and screen reader.

## Do's and Don'ts

- Do show party order by score only; ties are ordered alphabetically.
- Do label AI-generated content clearly.
- Do take every colour, font and shadow from `tokens.css`.
- Don't use party colours for bars or backgrounds.
- Don't use red/green on the agreement scale.
- Don't load fonts, styles, scripts or images from another origin.

## Open Design Questions

- Logo and product name.
- Whether to show party logos at all (licensing and neutrality).
