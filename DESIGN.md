---
name: ideology-app (Civic Horizon)
description: Neutral, civic, mobile-first voting advice tool on Material Design 3 with the Civic Horizon palette. Calm and trustworthy; no party colours in the base UI (only a party logo image carries its own colours).
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
  party-logo-tile: { light: "#ffffff", dark: "#ffffff", note: "fixed in both themes (the light surface-container-lowest), so dark-on-transparent logos stay legible" }
  on-party-logo-tile: { light: "#3f484d", dark: "#3f484d", note: "placeholder text, fixed in both themes (the light on-surface-variant)" }
  elevation-2: { light: "0 2px 8px -2px rgba(0, 31, 42, 0.08)", dark: "0 2px 8px -2px rgba(0, 0, 0, 0.4)" }
  elevation-4: { light: "0 8px 24px -4px rgba(0, 31, 42, 0.16)", dark: "0 8px 24px -4px rgba(0, 0, 0, 0.5)", note: "the feedback dialog only" }
  scrim: { light: "rgba(0, 0, 0, 0.32)", dark: "rgba(0, 0, 0, 0.32)", note: "the feedback dialog backdrop" }
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
  coverage-badge: { backgroundColor: info-container, textColor: on-info-container, rounded: full, typography: label-md, icon: info, focusable: true }
  coverage-tooltip: { backgroundColor: on-surface, textColor: surface, rounded: small, typography: body-md, maxWidth: "min(24rem, 100%)", shows: "hover, focus, tap; Escape closes" }
  notice-card: { level: 1, backgroundColor: card, border: "1px outline-variant", rounded: large, icon: "info on info-container, rounded medium" }
  election-card: { level: 1, backgroundColor: card, border: "1px outline-variant", rounded: large, hover: "border primary, elevation-2", cta: "button-primary pill: Realizar cuestionario" }
  summary-card: { level: 1, backgroundColor: card, border: "1px outline-variant", rounded: large, donut: "64px, arc primary, track surface-container-highest, decorative", star: "secondary, filled when Important > 0" }
  brand-title: { logo: "apps/web/src/assets/ideologiapp-logo.svg, 40px (48px from 600px), decorative", name: IdeologiApp, typography: page title }
  share-card: { level: 1, backgroundColor: card, border: "1px outline-variant", rounded: large, holds: "share (Comparte tu resultado) then share-app (Comparte IdeologiApp)", divider: "1px outline-variant between the two sections" }
  share-target: { icon: "48px circle, 1px outline, card background, icon on-surface", caption: "label-md on-surface-variant", minTarget: 48px, hover: "8% on-surface", colours: "neutral tokens only, never brand colours" }
  important-mark: { backgroundColor: secondary-container, textColor: on-secondary-container, rounded: full, typography: label-md }
  evidence-quote: { backgroundColor: surface-container-high, textColor: on-surface, borderLeft: "4px outline", typography: body-lg, fontStyle: normal }
  progress: { track: surface-container-highest, value: primary, height: 8px, rounded: full }
  ranking-bar: { track: surface-container-highest, fill: primary, height: 8px, rounded: full }
  party-logo:
    tile: { backgroundColor: party-logo-tile, border: "1px outline-variant", rounded: small, boxSizing: border-box, decorative: true }
    size: { ranking: "40px (48px from 600px)", breakdown: 32px }
    image: { source: "the API's same-origin logoUrl only", fit: "object-fit contain, no extra padding (the committed PNGs carry 6% padding)", alt: "" }
    placeholder: { content: "Party short name, at most 2 lines (split once at the first space or hyphen when longer than 4 characters)", textColor: on-party-logo-tile, typography: "600 10px/12px, scaled to fit by an SVG viewBox" }
    failure: "a logo that fails to load becomes the placeholder in the same tile (no layout shift)"
  feedback-button: { style: "button-secondary (outlined)", label: "Danos tu opinión", icon: "feedback speech bubble before the text, decorative", placement: "Landing: last in main, after Cómo funciona; end screen: after the Cómo se calcula la afinidad link, before the first Volver al inicio" }
  feedback-dialog: { level: 4, element: "native dialog, showModal", backgroundColor: surface-container-highest, textColor: on-surface, rounded: extra-large, shadow: elevation-4, backdrop: scrim, width: "min(36rem, 100% - 2 * layout margin)", padding: lg, title: "Ayúdanos a mejorar (title-lg)", subtitle: "Dinos qué te ha parecido IdeologiApp (body-md on-surface-variant)" }
  text-area: { backgroundColor: card, border: "1px outline", textColor: on-surface, rounded: small, fontSize: 16px, minHeight: 8rem, resize: vertical, label: "visible, above the field" }
  icon-button: { size: 48px, rounded: full, backgroundColor: transparent, iconColor: on-surface-variant, hover: "8% on-surface", label: "aria-label only (Cerrar)" }
---

# Design Direction

## Overview

A calm, civic tool built on Material Design 3 with the Civic Horizon palette (`docs/design/civic-horizon.md`). The UI must never suggest a preference: identical treatment for every party, and no party colours anywhere except inside a party's own logo image.

## Existing Design Assets

- `apps/web/src/assets/ideologiapp-logo.svg`: the product logo (user-provided). It is an image with its own fixed colours (sky blue, white, gold); it is the product's mark, never a party's, and it is never recoloured or used next to a party. It is also the browser tab icon (`<link rel="icon">` in `apps/web/index.html`).
- `apps/web/src/assets/ideologiapp-touch-icon.png`: the home-screen icon (`apple-touch-icon`), 180x180, the logo rendered with its sky-blue background filled to the corners (iOS shows transparent corners as black). Regenerate it from the SVG if the logo changes.
- `apps/web/public/favicon.ico`: 16/32/48px fallback of the logo for clients that ask for `/favicon.ico` directly. Regenerate it with the touch icon.
- Tab title: `IdeologiApp`; pages with their own title use `<Page> · IdeologiApp` (`Metodología · IdeologiApp`, `Resultado compartido · IdeologiApp`). The Landing subtitle `Comparador de programas electorales` stays as page text.
- `docs/design/civic-horizon.md`: the source palette, type scale, shapes, elevation and grid. This file picks the parts the app uses; `apps/web/src/ui/tokens.css` mirrors this file.

## Generated Concept Images

- `docs/design/questionnaire-prototype.png`: a visual reference for the Questionnaire. Only its look and its disclosure card (shield and title) are adopted; its topic pill, `Inicio / N% completado / Finalización` labels and right-aligned arrow button are not.

## Product Feel

Trustworthy, quiet, readable, like a good public-service website. Evidence (quotes) is a first-class element, not hidden detail.

## Neutrality Rules (unchanged)

- Every party row and every party position looks the same, in every state. No winner styling: the first row is not emphasised (no number, medal, colour or size change).
- No party colours for bars, backgrounds or text. The only exception: the logo image itself carries a Party's colours (logos shown, decided by the user on 2026-10-26).
- Every Party gets the same party-logo tile (same size, shape, border and white background, in both themes), with its logo or, when it has none or the logo fails to load, a short-name placeholder. A logo is never recoloured, cropped or resized per Party.
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
- **Secondary** (gold): focus ring, the Important flag (toggle and mark) and the tonal result `Copiar enlace` button (share targets don't use it, except for their focus ring). Gold means "focus" or "marked by you", never a party.
- **Tertiary / info pair**: `Baja cobertura` and the shield tile on the disclosure card. Light uses `tertiary-fixed` with `on-tertiary-fixed-variant`; dark uses `tertiary-container` with `on-tertiary-container`. An "AI-generated" tag, if one is ever added, uses the same pair.
- **Surfaces**: the page is `surface`; cards are `surface-container-lowest` in light and `surface-container-low` in dark; a disclosure nested inside a card is one tier up.
- **Party logo tile**: `party-logo-tile` (`#ffffff`) with `on-party-logo-tile` (`#3f484d`) for the placeholder, the same pair in both themes, so dark-on-transparent logos stay legible in dark mode and every Party looks the same. Its border is `outline-variant` and follows the theme.
- Never put text on `outline` or `outline-variant` except the disagree state, whose pair is checked below.
- **Errors** use text only (a `role="alert"` message, the feedback dialog's problem line); there is no error colour role.

## Typography

**Public Sans** is the only typeface, self-hosted from the app's own `/assets/` (no third-party font request). Evidence quotes also use it; they are told apart by layout (a tinted block with a 4px left border), not by a serif or italics. No italic face is loaded.

- `h1` (page title): headline-lg (headline-lg-mobile below 600px). On the Landing and the Questionnaire the `h1` is the brand title: the decorative logo (40px, 48px from 600px) and the name **IdeologiApp**.
- Statement text (`h2` on the Questionnaire): headline-sm, at most about 65 characters per line (`max-inline-size: 30em`; `65ch` measures the wide "0" glyph and would fit about 80 Public Sans characters).
- Other `h2`: title-lg. `h3`, `h4`: title-md, except the `Detalle por afirmación` title, which uses title-lg like an `h2`.
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

Tonal elevation, as in the source. Levels 0–2 and Level 4 are used (there are no sticky bars; the feedback dialog is the only dialog).

- **Level 0:** the `surface` page.
- **Level 1:** cards (`card` surface, 1px `outline-variant`, no shadow): the Landing AI card, election cards, ranking rows, breakdown rows, the share card (one card for both share sections), the superseded notice. An election card gets the `elevation-2` shadow and a `primary` border on hover.
- **Level 2:** the Questionnaire's Statement card, with the soft ambient `elevation-2` shadow.
- **Level 4:** the feedback dialog: `surface-container-highest` with the `elevation-4` shadow over a `scrim` backdrop (32% black, both themes). The page behind it is inert and does not scroll.

## Shapes

- Cards: large (16px). The Statement card: extra-large (24px).
- Scale options: default (8px) inside the extra-large Statement card.
- Buttons, the Important toggle, badges and progress/ranking bars: full pill.
- Nested positions: medium (12px). Text field and text area: small (4px). The feedback dialog: extra-large (24px).
- Minimum tap target 48px for every control and text link.

## Components

- **Buttons.** Filled (`button-primary`): Siguiente, Revisar mis respuestas, Reintentar, `Enviar` and `Cerrar` in the feedback dialog, shared-result CTAs, the `Realizar cuestionario` pill inside an election card. Outlined (`button-secondary`): Saltar esta afirmación, Anterior, Volver a la última afirmación, `Danos tu opinión` (with a decorative speech-bubble icon), and `Volver al inicio` (a link styled as a button) on every screen that offers it; the end screen shows it before `Detalle por afirmación` and again at the end. Tonal (`button-tonal`): only the result `Copiar enlace`; the IdeologiApp share targets are not tonal buttons. Hover adds an 8% state layer. Disabled filled buttons use the M3 12% `on-surface` container with a 38% label. DOM order stays the reading and focus order (Siguiente first).
- **Statement card** (Level 2): the progress label and bar, the Statement, the Important row (toggle and hint), the 5-option scale, the skipped note and the controls.
- **Scale option**: a full-width radio row with its label. A custom circle radio (filled dot when checked; the native radio returns under forced colours). Checked states: agree → `primary-container` with a 2px `primary` border and `on-primary-container` text; neutral → `surface-container-high` with `on-surface-variant`; disagree → slate `outline-variant` with `on-surface` text and a 2px `outline` border. All checked states use weight 600.
- **Important toggle**: an outlined pill with an outline star in `secondary`; pressed, it becomes a `secondary-container` pill with a filled star and weight 600. The star shape and `aria-pressed` carry the state.
- **Disclosure card** (Questionnaire only, below the Statement card): a decorative shield (`aria-hidden`) in a 40px info tile, the title `Transparencia algorítmica y privacidad garantizada` and the unchanged AI/privacy note.
- **Election card** (Landing): one link per Election holding its name, date and a filled `Realizar cuestionario` pill with an arrow, so the whole card is the target and reads as actionable.
- **Summary card** (end screen and shared result, below the results title): a Level 1 card with a 64px donut of the answered share (`primary` arc on a `surface-container-highest` track, no arc at 0 %, the rounded percentage in its centre in label-md weight 600, decorative; the arc is 9.4 / 10.0 against the card in light / dark, the track is decorative like the ranking track), the title `Muestra evaluada: N/T afirmaciones contestadas` (title-md), the skipped count, and the Important sentence led by the Important star (`secondary`; filled when at least one Statement is marked, outline otherwise).
- **Ranking row**: the party-logo tile, party name + short name, percentage, a `primary` bar on a `surface-container-highest` track, and a `Baja cobertura` chip (info pair) when it applies. Every row looks the same.
- **Party logo** (ranking rows and breakdown positions only, on the end screen and the shared result): a decorative tile (`aria-hidden`, `alt=""`; the name stays as text next to it) with a fixed white `party-logo-tile` background in both themes, a 1px `outline-variant` border and the small (4px) corner. Ranking: 40px, 48px from 600px; breakdown: 32px at every width, filling the 48px summary row. The logo comes only from the API's same-origin `logoUrl` and fills the tile with `object-fit: contain`. Without a logo, or when it fails to load, the tile shows the short name in `on-party-logo-tile` (600 weight), scaled down by an SVG viewBox to fit inside the tile, on at most 2 lines (`EH`/`Bildu`, `EAJ-`/`PNV`). The swap happens inside the same fixed tile, so nothing moves. Logos are requested in Dataset Version Party order before the results render, never in ranking order.
- **Coverage chip and tooltip**: the `Baja cobertura` chip is a focusable button with an info icon. Its explanation appears in a tooltip (`inverse` pair: `on-surface` background with `surface` text) on hover, keyboard focus or tap, stays while hovered, and closes with Escape; the chip is described by the tooltip. There is no legend under the ranking.
- **Notice card**: the "not a voting recommendation" text on the end screen and the shared result, in a Level 1 card with a decorative info icon in a 40px info tile (same layout as the disclosure card).
- **External link**: the methodology link opening in a new tab ends in an external-link icon; `(se abre en una pestaña nueva)` stays in its accessible name as visually hidden text.
- **Breakdown row**: the Statement, the Voter's answer (Saltada / `Importante (cuenta el doble)` mark on `secondary-container`), and each party's position in ranking order as a native disclosure whose summary is the chevron, the 32px party-logo tile and one text box beside the tile with the name, short name and value (the text wraps inside the box, so the tile is never alone on its line) revealing the Evidence quote and its locator: a link to `url#page=N`, or the page alone for uploaded documents; `Sin posición en el programa` for no stance.
- **Evidence quote**: Public Sans body-lg on `surface-container-high` with a 4px `outline` left border; never serif, never italic.
- **Share card**: one Level 1 card with two sections, separated by a 1px `outline-variant` divider when both show.
  - **Comparte tu resultado** (end screen with scores only): a decorative share icon before the title; `Copiar enlace` (tonal, with a link icon) copies the Share Link to the clipboard; if copying fails, the link is shown in a read-only field, focused and selected, to copy by hand. A short note says that nothing is stored on any server and that anyone with the link can see the answers.
  - **Comparte IdeologiApp** (no title icon): the intro `Recomienda esta web a otras personas. Solo se comparte su dirección, sin ninguna respuesta.`, then a wrapping row of six share targets, in this order and with these captions: Copiar enlace, Facebook, WhatsApp, Instagram, X, Correo. They share only the home URL (`origin + '/'`), never a result. Each target is a 48px circle (1px `outline` border, `card` background, icon in `on-surface`) above a `label-md` caption in `on-surface-variant`; the whole tile is the hit area and gets the focus ring; hover adds an 8% `on-surface` state layer to the circle. Facebook, WhatsApp and X are plain links that open in a new tab; Correo is a `mailto:` link opened in place. Instagram has no web share link: it opens the system share sheet where the browser has one, otherwise it copies the home URL and says it is ready to paste in Instagram. Copy results are announced in the section's own status line; if copying fails, the home URL is shown in a read-only field, focused and selected. At 375px the row wraps (3 + 3); at about 700px and wider it fits on one line.
  - The end screen without scores and the shared result (`ready` only) show the IdeologiApp section alone.
- **Feedback button**: `Danos tu opinión`, an outlined pill (not tonal: gold stays for focus, Important and the result copy) with a decorative speech-bubble icon before the text and `aria-haspopup="dialog"`. On the Landing it is the last item of the page, after `Cómo funciona`, with no heading of its own. On the end screen it follows the `Cómo se calcula la afinidad` link and comes before the first `Volver al inicio`. It is not on the shared result, the methodology page, Statement steps or Not found.
- **Feedback dialog** (Level 4, a native modal `<dialog>`): a header with the title `Ayúdanos a mejorar` (title-lg) and a 48px close icon button (`Cerrar`) at its end, then the subtitle `Dinos qué te ha parecido IdeologiApp` (body-md, `on-surface-variant`); the title names the dialog and the subtitle describes it. Below, the form: the visible label `Tu opinión`, the text area, a privacy hint (note style), the counter `N/500` right-aligned in body-md `on-surface-variant` (weight 600 and `on-surface` when over the limit; it counts Unicode code points of the trimmed text, as the server does), a problem line when the text is too long or holds invisible characters, a polite status line that announces the limit bands (50, 25, 10, at and over the limit), the error alert (plain text, `role="alert"`; there is no error colour), the sending status `Enviando tu opinión…`, and an end-aligned actions row with the filled `Enviar`. Enviar is disabled while the text is empty, has a problem or a request is in flight. After sending, the form is replaced by a decorative check icon in `primary`, `¡Gracias por tu opinión!` (title-md), `Nos ayuda a mejorar IdeologiApp.` and a filled `Cerrar`, which gets focus. Focus starts in the text area, Tab and Shift+Tab wrap inside the dialog, and Escape, the close icon button, `Cerrar` or a click on the backdrop close it; focus then returns to `Danos tu opinión`. At 375px the dialog sits 16px from the edges and the actions wrap; from 600px it is at most 36rem wide and centred.
- **Text area** (feedback dialog): the text-field look (`card` background, 1px `outline` border, small corner, 16px text so iOS does not zoom), full width, at least 8rem tall, resizable vertically, with the focus ring like every control. No `maxlength`: a pasted text is never cut; the counter and Enviar enforce the limit.
- **Icon button**: a 48px transparent circle with a 24px icon in `on-surface-variant` and an `aria-label`; hover adds an 8% `on-surface` state layer. Used only for the dialog's close button.
- **Icons**: inline SVG drawn for this app, 24px (20px inside buttons and chips), `currentColor`, `aria-hidden`; meaning always lives in the adjacent text. Brand glyphs (Facebook, WhatsApp, Instagram, X) on the share targets are simplified filled marks drawn for this app in `currentColor`, never in brand colours and never copied from a brand kit or icon pack. They are the only icons without adjacent full text: the caption names the network and the accessible name says the action (`Compartir IdeologiApp en Facebook`).
- **Focus**: a 3px solid `secondary` ring with a 2px offset on every link, button, text field, text area, summary and scale option.

## Core Screens

1. Landing: brand title, choose an Election (election cards with a call to action), a short methodology summary, an "AI-generated" disclosure card, and the `Danos tu opinión` feedback button last.
2. Questionnaire: Statement card plus disclosure card.
3. Results: ranking + share card (Comparte tu resultado, Comparte IdeologiApp) + the `Danos tu opinión` feedback button (after the methodology link) + per-Statement breakdown.
4. Methodology: how Statements and Positions are generated and validated.
5. Shared result (`/resultados#…`): read-only ranking + breakdown from a Share Link, a neutral superseded notice (a card, not an alert), the share card with the Comparte IdeologiApp part only (before the breakdown), and friendly link errors.
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
| surface on on-surface (coverage tooltip) | 16.4 | 14.4 |
| on-party-logo-tile on party-logo-tile (placeholder) | 9.4 | 9.4 |
| on-surface on surface-container-highest (feedback dialog) | 13.3 | 9.5 |
| on-surface-variant on surface-container-highest (subtitle, hint, counter) | 7.2 | 7.2 |
| primary on surface-container-highest (check icon) | 7.2 | 7.2 |
| focus ring secondary on surface-container-highest (≥ 3) | 5.0 | 7.2 |
| outline (text-area border) on surface-container-highest (≥ 3) | 3.5 | 3.9 |
| on-surface on card (text-area text) | 17.2 | 13.3 |

The scale is a native radio group usable by keyboard and screen reader.

## Do's and Don'ts

- Do show party order by score only; ties are ordered alphabetically.
- Do label AI-generated content clearly.
- Do take every colour, font and shadow from `tokens.css`.
- Don't use party colours for bars or backgrounds.
- Don't recolour, crop or resize a logo per Party; every Party gets the same tile.
- Don't use red/green on the agreement scale.
- Don't load fonts, styles, scripts or images from another origin.
- Don't load share widgets, SDKs, scripts or brand images; share targets are plain links (or the system share sheet).

## Open Design Questions

- None. (Party logos: settled by the user on 2026-10-26, shown in a fixed white tile; logo licensing stays open in `docs/risks-and-open-questions.md`.)
