---
name: ideology-app (Civic Slate)
description: Neutral, civic voting advice web app. A web-app layout (sidebar + canvas) on slate neutrals with one cyan accent, dark first with a light mirror. Calm and trustworthy; no party colours in the base UI (only a party logo image carries its own colours).
designAssets:
  sourceOfTruth:
    - DESIGN.md (this file; apps/web/src/ui/tokens.css mirrors it)
  reference:
    - docs/design/web-redesign-prototype.html (user prototype, 2026-10-30)
  retired:
    - docs/design/civic-horizon.md (Material 3 theme used until web-redesign)
    - docs/design/questionnaire-prototype.png
themes:
  dark: "colors (reference theme, the default)"
  light: "colorsLight, via prefers-color-scheme: light"
colors:
  bg: "#020617"
  bg-sidebar: "#0b1222"
  surface: "#0f172a"
  surface-raised: "#1e293b"
  surface-sunken: "#020617"
  border: "#1e293b"
  border-strong: "#334155"
  border-control: "#64748b"
  text: "#f1f5f9"
  text-muted: "#94a3b8"
  text-subtle: "#64748b"
  accent: "#22d3ee"
  accent-fill: "#06b6d4"
  accent-fill-hover: "#22d3ee"
  on-accent: "#020617"
  accent-soft: "rgba(6, 182, 212, 0.1)"
  accent-border: "rgba(6, 182, 212, 0.35)"
  on-accent-soft: "#67e8f9"
  highlight: "#fbbf24"
  highlight-soft: "rgba(245, 158, 11, 0.12)"
  highlight-border: "rgba(245, 158, 11, 0.35)"
  on-highlight-soft: "#fcd34d"
  focus-ring: "#22d3ee"
  scrim: "rgba(2, 6, 23, 0.8)"
colorsLight:
  bg: "#f8fafc"
  bg-sidebar: "#ffffff"
  surface: "#ffffff"
  surface-raised: "#f1f5f9"
  surface-sunken: "#f8fafc"
  border: "#e2e8f0"
  border-strong: "#cbd5e1"
  border-control: "#7c8ba1"
  text: "#0f172a"
  text-muted: "#475569"
  text-subtle: "#64748b"
  accent: "#0e7490"
  accent-fill: "#0e7490"
  accent-fill-hover: "#155e75"
  on-accent: "#ffffff"
  accent-soft: "rgba(8, 145, 178, 0.08)"
  accent-border: "rgba(8, 145, 178, 0.35)"
  on-accent-soft: "#155e75"
  highlight: "#b45309"
  highlight-soft: "rgba(245, 158, 11, 0.12)"
  highlight-border: "rgba(217, 119, 6, 0.4)"
  on-highlight-soft: "#92400e"
  focus-ring: "#0891b2"
  scrim: "rgba(15, 23, 42, 0.5)"
fixed:
  party-logo-tile: { value: "#ffffff", note: "both themes" }
  on-party-logo-tile: { value: "#334155", note: "placeholder text, both themes" }
  shadow-sm: { dark: "0 1px 2px rgba(0, 0, 0, 0.4)", light: "0 1px 2px rgba(15, 23, 42, 0.06)" }
  shadow-lg: { dark: "0 24px 48px -12px rgba(0, 0, 0, 0.6)", light: "0 24px 48px -12px rgba(15, 23, 42, 0.18)", note: "Statement card, hovered election card, drawer, dialog, tooltip" }
  hero-glow: { dark: "rgba(6, 182, 212, 0.14)", light: "rgba(6, 182, 212, 0.12)", note: "decorative blurred circle behind the Landing hero" }
typography:
  fontFamily: "Inter (self-hosted variable font, @fontsource-variable/inter), system-ui, sans-serif"
  display: { font: "700 28px/36px", from1024: "700 32px/40px (hero) and 700 28px/36px (page titles)", tracking: "-0.02em" }
  headline: { font: "700 24px/32px", note: "page title below 1024px" }
  title-lg: "600 18px/28px"
  title: "600 16px/24px"
  statement: "500 20px/30px"
  body: "400 16px/26px"
  body-sm: "400 14px/22px"
  label: "600 14px/20px"
  caption: "500 12px/16px"
  overline: "600 11px/16px, uppercase, 0.08em tracking"
rounded:
  sm: 6px
  md: 8px
  lg: 12px
  full: 9999px
spacing: { xs: 4px, sm: 8px, md: 16px, lg: 24px, xl: 32px, 2xl: 48px }
layout:
  sidebar: "256px, fixed beside the canvas from 768px; a modal drawer below"
  topbar: "56px, sticky, translucent bg with blur"
  contentMaxWidth: 72rem
  readingMaxWidth: "48rem (Questionnaire column)"
  gutter: { compact: 16px, from640: 24px, from1024: 32px }
  electionColumns: { compact: 1, from640: 2 }
  stepColumns: { compact: 1, from640: 3 }
  textMeasure: 72ch
---

# Design Direction

## Overview

A calm, civic **web app** (decision of the user, 2026-10-30, `web-redesign`): Material 3 is retired. The layout is a sidebar plus a canvas, on slate neutrals with a single cyan accent, dark first. The UI must never suggest a preference: identical treatment for every party, and no party colours anywhere except inside a party's own logo image.

## Existing Design Assets

- `apps/web/src/assets/ideologiapp-logo.svg`: the product logo (user-provided 2026-10-31, `ic_ideologiapp.svg`): a white ballot box with a bulb cut out and a gold (`#F0C442`) ballot, on a transparent background. It is the **dark-theme** variant and the default. It is the product's mark, never a party's, and it is never used next to a party.
- `apps/web/src/assets/ideologiapp-logo-light.svg`: the **light-theme** (negative) variant, slate `#0F172A` on a transparent background. It is not a plain colour swap of the white mark (a solid slate box would read heavier and lose the drawing's figure/ground, user decision 2026-11-03): the box is a slate outline (18/563 of the drawing, close to the bulb's line weight), the bulb and slot cut-outs become slate lines (1px thinner), the bulb base stops just short of the box's bottom edge, the slot is one clean bar behind the ballot, and the gold ballot is unchanged. `ProductLogo` (`features/common/ProductLogo.tsx`) serves both through `<picture>` with `prefers-color-scheme: light`; it is used in the sidebar, the Landing hero (below 768px) and the focus bar.
- `apps/web/src/assets/ideologiapp-favicon.svg`: the tab icon (`<link rel="icon">` in `apps/web/index.html` and `apps/web/admin/index.html`): both variants in one SVG, switched by an inner `@media (prefers-color-scheme: light)`.
- `apps/web/src/assets/ideologiapp-touch-icon.png`: the home-screen icon (`apple-touch-icon`), 180x180, the dark variant on an opaque slate `#0F172A` square (iOS shows transparency as black). Regenerate it if the logo changes.
- `apps/web/public/favicon.ico`: 16/32/48px PNG-in-ICO fallback, kept as the solid slate box (at 16px the outline variant is too faint; a solid mark reads on light and dark tab bars). Regenerate it with the touch icon.
- Tab title: `IdeologiApp`; pages with their own title use `<Page> · IdeologiApp` (`Metodología · IdeologiApp`, `Transparencia IA · IdeologiApp`, `Resultado compartido · IdeologiApp`).
- `docs/design/web-redesign-prototype.html`: the user's prototype of this direction. Adopted: the sidebar + canvas layout, the slate/cyan palette, Inter, moderate corners, the hero, the election grid with status badges, the numbered steps. Not adopted: its Tailwind CDN and Google Fonts (third-party requests), the Questionnaire as a modal over the shell (it is a focus page), the 3-option answer list (the scale keeps 5 options), the `Programas 2023 listos` and `v2.0 Web` badges, the emoji rating in the feedback dialog, and copy that does not match the method (statement counts, human validation, "distancia vectorial", "código abierto").

## Product Feel

Trustworthy, quiet, readable, like a modern public-service web app: dense enough on desktop to avoid dead space, one clear action per screen. Evidence (quotes) is a first-class element, not hidden detail.

## Neutrality Rules (unchanged)

- Every party row and every party position looks the same, in every state. No winner styling: the first row is not emphasised (no number, medal, colour or size change).
- No party colours for bars, backgrounds or text. The only exception: the logo image itself carries a Party's colours.
- Every Party gets the same party-logo tile (same size, shape, border and white background, in both themes), with its logo or a short-name placeholder. A logo is never recoloured, cropped or resized per Party.
- No red/green on the agreement scale. Every checked option uses the same accent frame; the side of the scale is never a colour.
- The meaning of the scale never relies on colour alone: the label text and the filled radio dot carry it.

## Themes

Exactly two themes, chosen by the operating system; there is no in-app toggle.

- **Dark** (`colors`) is the reference theme and the default.
- **Light** (`colorsLight`) applies under `prefers-color-scheme: light`.
- `color-scheme: dark light` is declared so native controls follow the theme.

## Colors

- **Accent** (cyan): links, the active nav item, filled buttons (`accent-fill` with `on-accent`), progress and ranking bars, the checked scale option, the donut, the evidence rule, icon tiles, the focus ring. One accent only.
- **Highlight** (amber): only the Voter's Important flag (toggle, mark, summary star) and the `Revisado` admin chip. Amber means "marked by you" or "not yet", never a party.
- **Neutrals**: `bg` page, `bg-sidebar` sidebar, `surface` cards, `surface-raised` hover and nested tiles, `surface-sunken` inputs, options and positions. `border` hairlines separate; `border-control` frames anything you can operate.
- **Party logo tile**: fixed white with `on-party-logo-tile` placeholder text, in both themes.
- **Errors** use text only (`role="alert"`); there is no error colour.

## Typography

**Inter** is the only typeface, self-hosted (`@fontsource-variable/inter`, latin subset); no third-party font request. Evidence quotes use it too, told apart by layout (an accent left rule), never italics.

- `h1`: `headline` below 1024px, `display` from 1024px; the Landing `h1` is the brand title (`IdeologiApp`, with the logo below 768px only, where the sidebar is hidden). The Questionnaire `h1` is the Election name in `overline` style (`Cuestionario` while loading).
- Statement text (`h2` on the Questionnaire): `statement`, at most about 34em per line.
- Other `h2`: `title-lg`. `h3`, `h4`: `title`.
- Body: `body`. Notes, hints, dates, card copy: `body-sm` in `text-muted`. Badges and captions: `caption`. Eyebrows, the top-bar crumb, progress label, breakdown number: `overline`.
- Running text is capped at 72ch.

## Layout

- **App shell** (every Voter page except the Questionnaire): a 256px sidebar (`bg-sidebar`, right hairline) with the brand (logo + `IdeologiApp`, a link home), the tagline `Comparador de programas electorales`, the section nav (`Ir al inicio` `/` with a house icon, a plain link never marked current, shown only on the shared result `/resultados`; `Elecciones` `/`, `Cómo funciona` `/metodologia`, `Transparencia IA` `/transparencia`; the current one gets `surface-raised`, a `border-strong` frame, accent text and `aria-current="page"`) and, in its footer, `Danos tu opinión`, then (`donate-buymeacoffee`, only when `DONATION_URL` is configured) the `Invítanos a un café` link, then the `Aviso legal y privacidad` link (`legal-privacy-page`: `body-sm`, `text-muted`, accent and underline on hover, 44px tall, centred; not a nav item, never marked current; closes the drawer like the nav links). The canvas has a sticky 56px top bar with the crumb `IDEOLOGIAPP / <SECCIÓN>` (its `IdeologiApp` root is a link home), the page in a column at most 72rem wide, and a footer line saying the tool is not a voting recommendation and the content is AI-generated, followed by a second line with the `Aviso legal y privacidad` `text-link`.
- **Below 768px** the sidebar is a modal drawer (85vw, at most 256px) opened by the top bar's menu button (`Abrir menú`, `aria-expanded`, `aria-controls`). While open the canvas is `inert` and does not scroll, a scrim covers it, and focus moves into the drawer. Escape (unless the feedback dialog is open), the scrim, `Cerrar menú`, a link or growing past 768px close it. A link closes it in the same update as the navigation, so the new page can focus its `h1`; every other close (and a link to the current page) returns focus to the menu button.
- **Focus shell** (the Questionnaire, `/elecciones/:id/cuestionario`): no sidebar, so no stray navigation loses the in-memory Answers. A sticky bar with the brand (a link home, named `IdeologiApp, ir al inicio`) and `Salir` (a link home); both discard the in-memory Answers, and one centred 48rem column for the steps and the results.
- Landing elections: 1 column, 2 from 640px (one card today). Transparencia feature cards: 1 column, 3 from 640px. How-it-works carousel: text over the recording with the arrows at the ends of the dots row; from 1024px text (1/3, top-aligned with a `xl` offset) beside the recording (2/3), whose height is capped at `max(18rem, 100svh - 38rem)` (`--how-media-max-height`) so the Elections and the carousel fit a 900px-tall desktop screen; a capped recording is centred in its column and the text takes the width it frees with the arrows at the card's left and right edges. Methodology and Aviso legal y privacidad: a page index (`En esta página`) above the text, a sticky right column from 1024px.
- One Statement per screen. The results breakdown stays stacked. No horizontal scroll at any width (the canvas clips the decorative hero glow).

## Elevation & Depth

Flat by default: borders, not shadows.

- **Flat:** cards, rows, the sidebar, steps.
- **`shadow-lg`:** the Questionnaire's Statement card, an election card on hover, the mobile drawer, the coverage tooltip and the feedback dialog (over the `scrim` with a light blur).

## Shapes

- Cards, rows, the dialog and the page index: `lg` (12px).
- Buttons, fields, options, nav items, the Important toggle, positions, share tiles: `md` (8px).
- Badges, chips, the party-logo tile: `sm` (6px). Progress and ranking bars: full.
- Minimum target: 44px, 48px for buttons and the Important toggle on coarse pointers; scale options, position summaries and share tiles are 48px.

## Components

- **Buttons.** Solid (`button-primary`, `accent-fill`): Siguiente, Revisar mis respuestas, Reintentar, Enviar, Cerrar (dialog), shared-result CTAs. Outlined (`button-secondary`, `surface` with `border-control`): Anterior, Danos tu opinión, Volver al inicio (only on loading and error states). Soft (`button-tonal`, `accent-soft` with a `border-control` frame): only the result `Copiar enlace`. Disabled: `surface-raised`, `text-subtle` label. DOM order stays the reading and focus order.
- **Status badge**: only `En preparación` (neutral, an Election with no published Dataset Version); the `Disponible` and `Próximamente` chips were removed on 2026-11-03.
- **Election card** (Landing grid, compact since 2026-11-03: `md` top padding, 44px bars, no `Disponible`/`Próximamente` chips by user decision): one link stretched over the card with the name (`--election-title-font`: 700 1.25rem, 700 2rem from 1024px; accent on hover), the date with a calendar icon above a hairline, and a solid `Realizar cuestionario →` bar; from 1024px the card is one full-width row (user decision 2026-11-20, `landing-card-results-notes`): name and date (no hairline) on the left and a larger button (60px, `title-lg`) on the right, so the card is shorter and the carousel fits on more desktop screens; below 1024px it stays stacked; hover raises it (`border-strong`, `shadow-lg`), keyboard focus rings the whole card. An Election without a published Dataset Version keeps a muted `En preparación` badge outside the link. The Landing shows only the most recent Election by date (the higher id on equal dates; `ui-2026-focus-tweaks`, user decision 2026-11-20) in a region named `Elecciones` with no section heading; older Elections stay in the database and open by URL (`/elecciones/:id/cuestionario`) and Share Links.
- **Hero** (Landing): the tagline as an accent `overline` eyebrow, the `h1` and a `body` muted lead (`md` below it; since 2026-11-06 a three-point bulleted list, `landing-upcoming-copy`), over a decorative blurred `hero-glow`. The Landing spacing is kept tight (`lg` after the Elections grid, no extra margin above the carousel) so the Elections and the carousel fit one desktop screen where possible.
- **How-it-works carousel** (Landing, user decision 2026-11-03, replaces the numbered steps): no section title and no methodology link (it is in the sidebar); one card the width of the content column, named `Cómo funciona` (`aria-roledescription="carrusel"`). Three pages in an endless loop, each an accent `overline` `Paso N de 3`, an `h2` title, accent-check bullet points and a muted, decorative (`aria-hidden`) screen recording of the app in a framed 3:2 box: 1 `Responde a las afirmaciones` (answer, Important, Siguiente), 2 `Revisa tus resultados` (scrolling the ranking, Copiar enlace), 3 `Comprueba de dónde vienen los resultados` (opening a Statement's detail from the matrix). Each recording exists for the dark and the light theme (`assets/how-it-works/`, 960×640 H.264 with a WebP poster). A page moves on when its recording ends; pointer hover and keyboard focus (`:focus-visible`) hold it (the recording replays), and so does being off screen. Controls: round `Página anterior` / `Página siguiente` arrows, a `Pausar el carrusel` / `Reanudar el carrusel` button and three dots (`Ir a la página N: <título>`, `aria-current`); the current dot is a pill whose accent fill follows the recording. Swipe changes page on touch. Pages share one grid cell (no height jump); the new one slides in 24px from the side it comes from over 0.35s. Under reduced motion it starts paused on each recording's first frame and has no slide. It ends the page: the checks/privacy sentence was removed (user decision 2026-11-03).
- **Page index**: `En esta página` with in-page links to each section heading (scroll margin clears the top bar). The section being read is marked as the Voter scrolls (user decision 2026-11-06, `page-toc-scrollspy`): `aria-current="location"`, an `accent` left rule, `accent` text and weight 600. A section is current once its heading reaches 30 % of the viewport height; before the first heading the first entry is current, and at the end of the page the last one. A clicked entry is marked at once and stays marked while the jump scrolls, until the Voter scrolls by hand.
- **Feature card** (Transparencia IA): an icon tile, a `title` heading and `body-sm` copy.
- **Statement card**: the progress label (accent `overline`) and a 6px bar, the Statement, the Important row, the 3-option scale and the controls under a hairline: one row of equal-width buttons in the order `Anterior` (leading back arrow, from the second Statement), `Siguiente` (solid, trailing forward arrow), `--button-height-tall` tall (52px, 56px on coarse pointers); on the first Statement `Siguiente` takes the full row. There is no `Saltar` (user decision 2026-11-21, `three-option-scale`): `Neutral / No lo sé` replaces it. Long labels wrap inside their button.
- **Step transition**: after Siguiente or Anterior (and Revisar mis respuestas), only the Statement, the Important row and the scale fade in from 16px over 0.22s (`cubic-bezier(0.2, 0.7, 0.3, 1)`): from the right going forward, from the left going back. No transition on the first load. The progress label, the progress bar (whose fill widens with a 0.3s transition) and the controls never move, so repeated taps land on the same buttons. None under reduced motion.
- **Scale option**: a 48px row on `surface-sunken` with a `border-control` frame and a custom circle radio (native under forced colours), then the option's side icon (32x24, `text-muted`, accent when checked) and the label. Checked: `accent-soft` with an `accent` frame, an accent dot and weight 600, the same for every value. **Order**: three options, `De acuerdo` (thumb up), `Neutral / No lo sé` (up-down pair), `En desacuerdo` (thumb down) (user decision 2026-11-21, `three-option-scale`; it replaces the five-point order of `questionnaire-scale-order`); arrow keys follow that order. `Neutral / No lo sé` leaves the Statement without a value for the affinity.
- **Important toggle**: outlined with an amber outline star; pressed, `highlight-soft` with a filled star and weight 600. The star shape and `aria-pressed` carry the state. Turning it on plays one subtle amber glow (0.6s ring and star pop; none under reduced motion). The hint `Las afirmaciones importantes cuentan el doble…` is a tooltip under the toggle on hover or keyboard focus, and always its `aria-describedby`.
- **Disclosure card / notice card**: a translucent `surface` panel with an accent icon tile (shield / info). The notice card is now only the admin "not configured" notice. The Share Link info toggle leaves `space-sm` between its hover area and the note it opens.
- **Summary card**: the 64px donut (accent arc, `surface-raised` track, decorative), `Muestra evaluada: N/T afirmaciones con opinión` (N = De acuerdo or En desacuerdo Answers), the Neutral sentence (`Has respondido «Neutral / No lo sé» en K afirmaciones.`, `Se respondió…` on a shared result), the Important sentence with the amber star (only Important flags on sided Answers count).
- **Ranking row**: party-logo tile, name + short name, `title-lg` percentage, a 6px accent bar, `N de M coincidencias` (M = Statements compared with that Party, N = same side; `coincidencia` when M = 1; a Party with M = 0 shows `Sin afirmaciones comparables` in place of the percent) and the `Baja cobertura` chip (shown when M < 5) (accent soft) with its tooltip (`surface-raised`, `shadow-lg`). Every row looks the same.
- **Party logo**: as before: fixed white tile, `border-strong` frame, `sm` corner; 40px (48px from 640px) in the ranking, 32px in the breakdown; placeholder on failure; requested in Dataset Version Party order.
- **Results dashboard** (end screen and shared result): below 1024px one column in reading order (summary, `Revisar mis respuestas`, ranking, share card, `Danos tu opinión` on the end screen, links). From 1024px a two-column grid: summary and actions on the left; the ranking on the right as a sticky card (`surface`, `lg`) capped at the viewport height with its own scroll (a region `Afinidad por partido`, a tab stop only from 1024px, where it can scroll); ranking rows go compact on `surface-sunken`. **Ranking warning**: the ranking card opens with its intro and, at the top right, an alert icon button (circle with an exclamation, `Aviso sobre estos resultados`, `aria-expanded`) that shows or hides the "not a voting recommendation" warning just below it, in a `highlight-soft` box with a `highlight-border` frame; it replaces the former notice card. **Excluded Parties note** (user decision 2026-11-20, `landing-card-results-notes`): for an Election that left a Party out of its Dataset Version (today only the 2026 general election, EAJ-PNV), a neutral `surface-raised` note titled `Partidos no incluidos en el cálculo` with the reason sits between the intro and the ranking, on the end screen and the shared result; the copy lives in `ExcludedPartiesNotice.tsx`, keyed by Election type and date. The DOM order is the same at every width. On the Questionnaire the focus-shell column widens from 48rem to 72rem while the results show.
- **Breakdown first-sight cue**: the breakdown intro reads `Pulsa sobre una afirmación o posición para ver las citas coincidentes extraídas de los programas electorales.` The first time the section's top reaches the upper 70 % of the viewport, its title and intro make one small bounce (scale up to 1.04 and back, 0.9s, from the left edge) and, at the same time, the first matrix row (cells tinted with `accent-fill` 22 %, Party cell frames in `accent`) or the first card (from 1024px down: `accent-soft` fill and a 2px `accent-border` ring) lights up twice (0.8s each). It plays once per visit to the end screen or shared result (never again on a filter change) and not under reduced motion.
- **Breakdown filters**: single-choice chips (`aria-pressed`, a `role="group"` `Filtrar afirmaciones`) with their row count: `Todas`, `De acuerdo`, `Neutral` (Neutral / No lo sé), `En desacuerdo`, `Importantes` (the `Saltadas` chip was removed with Saltar, `three-option-scale`). Pill chips with a `border-control` frame; pressed: `accent-soft` with an `accent` frame. A visually hidden status says `N de T afirmaciones`; an empty filter shows `Ninguna afirmación coincide con este filtro.` They filter the matrix and the cards alike.
- **Statement matrix** (from 1024px, user decision 2026-10-31; cards stay below): a table in a bordered scroll box (sticky header row; the `Afirmación` column, `--matrix-statement-width` 18rem, 24rem from 1280px, and the answer column, `--matrix-answer-width` 3.5rem, stay sticky on the left when a narrow canvas scrolls the Party columns sideways, as on the shared result at 1024px inside the app shell; the box's `scroll-padding` clears the sticky header and columns so a keyboard-focused cell is never hidden under them): `Afirmación` (number + text clamped to 2 lines, a button that opens every Party's Position), `Tú` / `Enlace` (clicking it opens the Statement like its button, a pointer shortcut with no extra tab stop; the Answer as its side icon (the up-down pair for Neutral), `—` when unanswered, the amber star when Important, full label for screen readers), then one column per Party in ranking order (32px logo tile only, full name hidden as the header's accessible name; every Party column, header and cells, is at least `--matrix-party-width` 3.25rem wide (the 2.75rem cell button plus padding) and all Party columns are equal (they stretch equally when the table has room), `ui-2026-focus-tweaks`). Each cell is a button with the stance read by side as its side icon (+1/+2 `De acuerdo`, −1/−2 `En desacuerdo`, 0 `Neutral`; `—` for no stance) and the stance and coincidence in its accessible name (`PSOE: De acuerdo, coincide contigo. Ver la cita` / `…, no coincide contigo. Ver la cita`; `con el enlace` on a shared result). **Cell tint = coincidence with the Answer** (the matching rule's per-Statement agreement, `three-option-scale`): `data-match="100"` (same side) one accent hue at `--match-100` 60 % over `surface`; `"0"` (opposite sides) plain `surface`; `"none"` (no Answer, Neutral Answer, position 0 or no stance) `surface-sunken` with muted text. Never a colour per side or per Party; every column and cell has the same markup. A legend above the table shows the three side icons (`De acuerdo`, `Neutral`, `En desacuerdo`), `—` (no stance) and two swatches, `Coincide` and `No coincide`.
- **Inspector panel**: a modal side sheet (native `<dialog>`, right edge, at most 32rem, full height, `surface`, `border-strong` left rule, `shadow-lg`, blurred `scrim`). It shows `Afirmación N`, the Statement (`title-lg`), the Answer line, then for the chosen cell (or every Party, in ranking order) the tile, name, stance (by side), `· coincide contigo` / `· no coincide contigo` (`con el enlace` on a shared result; nothing when there is no coincidence to show) and the Evidence (quote and locator, or the no-stance sentence); from a cell, `Ver todos los partidos en esta afirmación` switches to every Party and moves focus to the Statement heading. Focus starts on `Cerrar`; Escape, `Cerrar` or a backdrop click close it and focus returns to the cell or Statement that opened it (to the breakdown heading if the layout switched meanwhile). It shows only what the Dataset Version holds (stance, quote, page): there is no AI explanation to show. **Answer and stance icons** (inspector and mobile cards): the Answer value and every Party stance lead with their side icon (the up-down pair for Neutral and position 0, none for unanswered or no stance), and the `Importante (cuenta el doble)` chip leads with the filled amber star; all decorative, the text carries the meaning.
- **Breakdown row**: the accent `overline` number, the Statement, the Voter's answer (and the amber `Importante (cuenta el doble)` mark), then one `<details>` per Party on `surface-sunken` with a chevron, the 32px tile and the name/short/value text box.
- **Evidence quote**: `body` on `surface` with a 3px accent left rule; never italic.
- **Share card**: one card, `Comparte tu resultado` (an info icon button `Privacidad del enlace` at the top right toggles the note on how the link carries the Answers; soft `Copiar enlace`, fallback field) then `Comparte IdeologiApp` (six 48px square tiles with `border-control`, captions in `caption`), separated by a hairline. Behaviour unchanged.
- **Copy feedback**: after a successful copy, `Copiar enlace` (result) turns into a check and `¡Copiado!`, and the `Copiar enlace` tile of `Comparte IdeologiApp` swaps its icon for a check and its caption for `¡Copiado!`, both with an `accent` frame and a 0.3s pop; after 2s they go back. Both faces share one grid cell so the control never changes size. The status line is then only announced (visually hidden); the Instagram hint and the clipboard fallback (text plus field) stay visible. No pop under reduced motion.
- **Feedback button**: `Danos tu opinión`, outlined, full width in the sidebar footer (every app-shell page; origin `landing`, shown as `General` to Operators) and on the results end screen (origin `results`). It is not in the Questionnaire steps.
- **Donation link and block** (`donate-buymeacoffee`, shown only when the server has a valid `DONATION_URL`; otherwise nothing, not even an empty container): one plain external link `Invítanos a un café` with a leading 20px coffee icon, the visually hidden ` (se abre en una pestaña nueva)` and the trailing external-link icon; its href is exactly the configured URL, `target="_blank"`, `rel="noopener noreferrer"`; it never closes the drawer. **Sidebar**: below `Danos tu opinión`, styled like the legal link (`body-sm`, `text-muted`, accent and underline on hover, at least 44px tall, centred, `space-xs` gaps, never wraps at 256px); no disclosure there and none in the canvas footer. **End block** (`.donate-block`, the last element of the end screen, after the breakdown): a `border` hairline on top, `space-2xl` above and `space-lg` padding-top, 72ch measure, `body-sm` `text-muted`: the line `¿Quieres apoyar el proyecto?` with the link (`text-link`, accent; at 375px it may wrap under the question), then a native `<details>` closed by default whose summary `¿Para qué se usan las donaciones?` is `body-sm` `text-muted`, accent on hover, at least 44px tall, with the `.position__summary` style chevron in `text-muted`; the opened text is two `body-sm` `text-muted` paragraphs. No card, surface, button styling or highlight. Opening it never moves the link (it sits below the line).
- **Feedback dialog**: a native modal `<dialog>`, `surface` with a `border-strong` frame, `lg` corner, `shadow-lg`, over the blurred `scrim`; at most 32rem wide. Content and behaviour unchanged (title `Ayúdanos a mejorar`, subtitle, `Tu opinión`, counter, hint, Enviar, thanks state).
- **Text fields** (share fallback, feedback, admin): `surface-sunken`, `border-control`, `md` corner, 16px text.
- **Icon button**: 44px, `md` corner, `text-muted` icon, `surface-raised` hover; the dialog close, `Abrir menú` and `Cerrar menú`.
- **Icons**: inline SVG drawn for this app (now also menu, ballot, book, chip, calendar, shield, home, back arrow, a coffee cup with steam (an original line drawing, not the Buy Me a Coffee mark) and the three answer sides on a 32x24 canvas: line thumb up (De acuerdo), thumb down (En desacuerdo) and a thumb up/down pair (Neutral); the double-thumb and step-over glyphs were removed with the five-point scale and Saltar, `three-option-scale`), `currentColor`, `aria-hidden`; meaning in the adjacent text or `aria-label`. Brand glyphs on share targets stay neutral.
- **Focus**: a 2px solid `focus-ring` outline with a 2px offset on every link, button, field, summary and scale option.

## Core Screens

1. Landing (`/`, app shell): hero, the most recent Election's card (no section heading; region named `Elecciones`), and the `Cómo funciona` carousel. No AI card (user decision 2026-10-31): the shell footer states it on every page and `Transparencia IA` explains it.
2. Questionnaire (focus shell): Statement card plus disclosure card.
3. Results (focus shell, end of the Questionnaire): the results dashboard (summary, controls (`Revisar mis respuestas` only; the focus bar's `Salir` and brand go home), ranking, share card, `Danos tu opinión`, methodology link (new tab); the disclaimer sits behind the ranking's alert button), then the breakdown (`Comprueba de dónde salen tus coincidencias`, `headline`) with filters: the Statement matrix with the inspector from 1024px, cards below; last, only when `DONATION_URL` is configured, the donation block.
4. Methodology (`/metodologia`, `Cómo funciona` in the nav): page index plus the full method.
5. Shared result (`/resultados#…`, app shell): the same results dashboard and breakdown (answer column `Enlace`), superseded notice, Comparte IdeologiApp, link errors. **Outdated-link notice** (`three-option-scale`, user decision 2026-11-21): a `v1` link (made before the three-option scale) shows, in the same `card shared-notice` style as the superseded notice, the h2 `Este enlace es de una versión anterior`, the text that it belongs to an earlier version of the questionnaire and can no longer be shown, a solid `Haz el nuevo cuestionario` link (to that Election's current Questionnaire when available, else `/`) and `Volver al inicio`; never a broken page or the generic invalid-link message. No donation block (`donate-buymeacoffee`, user decision 2026-11-18): donation is only in the sidebar and drawer here.
6. Transparencia IA (`/transparencia`, app shell): what the AI does, what is checked, what stays in the browser, and what cannot be guaranteed; links to the methodology. Static, no request.
7. Not found (app shell; inside the focus shell for a bad Questionnaire id).
8. Aviso legal y privacidad (`/legal`, app shell, crumb `Aviso legal`; `legal-privacy-page`): the Methodology doc layout (h1, lead, a `body-sm` `text-muted` `Última actualización: …` line, page index with `Titulares y contacto`, `Condiciones de uso`, `Privacidad`, `Cookies`), four sections; the privacy section uses `h3` (`title`) subsections; `Volver al inicio` at the end. Only `Titulares y contacto` depends on a request (loading status; alert + solid `Reintentar`; "pendiente de publicación" sentences when not configured). Only when `DONATION_URL` is configured (`donate-buymeacoffee`): a donation-terms paragraph in `Condiciones de uso` and an `h3` `Donaciones` in the privacy section, after `Quién más accede a los datos`. No image, no party name or logo. Not linked from the focus shell.

## Operator Admin Page

A private page for Operators at `/admin` (`feedback-admin`), never linked from a Voter page and never indexed (`noindex`). It is a separate build entry (`apps/web/admin/index.html`), so the Voter bundle holds no admin code. Same tokens, both themes and Inter as every other page, without the app shell: one centred column at most 72rem wide; running text keeps the 72ch measure. No new token.

- **Frame.** No brand logo. The `h1` reads `Administración` and is focused on load (`tabIndex=-1`, no ring). Tab title `Administración · IdeologiApp`.
- **Checking.** A `role="status"` line, `Cargando…`.
- **Not configured.** A notice card (info tile, as the results notice) with `No hay ninguna cuenta de Operador configurada. Define ADMIN_USERS en el servidor; el README explica cómo (ideology admin hash-password).` No form.
- **Sign-in.** A card titled `Iniciar sesión` (h2) with two labelled fields, `Usuario` (`autocomplete="username"`, `autocapitalize="none"`, no spellcheck) and `Contraseña` (`type="password"`, `autocomplete="current-password"`), then a filled `Entrar` button, disabled while the request runs.
  - **Text field.** `surface-sunken` background, 1px `border-control`, 8px corner, 16px body text, 48px minimum height, the focus ring. Label above in `label`.
  - **Errors.** One `role="alert"` text line: `Usuario o contraseña incorrectos.`, `Demasiados intentos. Vuelve a intentarlo en N minutos.` or `No se pudo conectar. Inténtalo de nuevo.` On error the password is cleared and focused.
  - **Session expired.** The form returns with the notice line `Tu sesión ha caducado. Vuelve a iniciar sesión.`
- **Signed in.**
  - **Header row.** `Sesión iniciada como <usuario>` (body-sm, `text-muted`) and an outlined `Cerrar sesión`; the row wraps at 375px.
  - **Filters.** A `Filtrar` fieldset (card, legend in `title`) with `Desde (UTC)` and `Hasta (UTC)` date fields and `Estado` (native select: `Todas` by default, `Sin revisar`, `Revisadas`), then an outlined `Filtrar` button. The fields use the text-field look, stack at compact and sit in one row from 600px. `Hasta` earlier than `Desde` shows a text problem line (`role="alert"`) and sends nothing.
  - **Status line.** A `role="status"` line, `N mensajes mostrados`, or `Mensaje borrado.` after a delete.
  - **List.** An `<ol>` of cards, one per message, newest first:
    - Meta line in body-sm `text-muted`: `#id · 29 oct 2026, 14:05 UTC · General` (origin `General` for the sidebar button, stored as `landing`, or `Resultados`).
    - `Revisado` chip when reviewed: the `important-mark` look (amber soft badge): amber means "marked by you". The state is in the chip's text.
    - The message in body, `white-space: pre-wrap`, `overflow-wrap: anywhere`, always rendered as text (markup shows literally).
    - Actions (wrap at 375px): outlined `Marcar como revisado` / `Marcar como no revisado` (disabled while pending) and outlined `Borrar`.
    - An action error is a `role="alert"` line inside its card.
  - **Paging.** An outlined `Cargar más` when there are more messages.
  - **Empty states.** `Todavía no hay mensajes.` with no filters, `Ningún mensaje coincide con los filtros.` with filters.
  - **Load error.** An alert line `No se pudieron cargar los mensajes.` with a filled `Reintentar`.
- **Delete confirmation (inline, not a modal).** Inside the card the actions are replaced by `¿Borrar este mensaje para siempre? No se puede deshacer.`, a filled `Borrar definitivamente` and an outlined `Cancelar`. Focus goes to `Cancelar`; `Escape` or `Cancelar` closes it and focuses `Borrar` again. After the delete the card is gone, the status line says `Mensaje borrado.`, and focus moves to the next card's first action, or else to the status line.
- **Accessibility.** Every pair used is already in the contrast table (`text` / `text-muted` on surface, `border-control` borders, `on-highlight-soft` on `highlight-soft`, the focus ring). 48px targets; DOM order is the focus order.

## Accessibility Baseline

WCAG 2.1 AA contrast for every text pair in both themes, and at least 3:1 for borders that identify a control and for the focus ring. Checked pairs (dark / light):

| Pair | Dark | Light |
|---|---|---|
| text on surface / bg | 16.3 / 18.4 | 17.9 / 17.1 |
| text-muted on surface / bg / surface-raised | 7.0 / 7.9 / 5.7 | 7.6 / 7.2 / 6.9 |
| accent (links, active nav) on surface / bg | 9.9 / 11.2 | 5.4 / 5.1 |
| on-accent on accent-fill (buttons, CTA) | 8.3 | 5.4 |
| on-accent-soft on accent-soft (badges, chip, Copiar enlace) | 10.6 | 6.6 |
| text on accent-soft (checked option) | 16.4 | 15.6 |
| on-highlight-soft on highlight-soft (Important, Próximamente) | 10.3 | 6.5 |
| highlight (star) on surface (≥ 3) | 10.7 | 5.0 |
| text on surface-raised (tooltip, nested) | 13.4 | 16.3 |
| on-party-logo-tile on party-logo-tile | 10.4 | 10.4 |
| border-control on surface / surface-sunken (≥ 3) | 3.8 / 4.2 | 3.5 / 3.3 |
| text-subtle radio circle on surface-sunken (≥ 3) | 4.2 | 4.6 |
| focus-ring on surface / bg (≥ 3) | 9.9 / 11.2 | 3.7 / 3.5 |
| text on matrix cell, 100 % tint (60 % accent-fill over surface) | 4.8 | 7.0 |
| text on matrix cell, 75 % / 50 % / 25 % tint | 7.1 / 10.1 / 13.5 | 9.6 / 12.3 / 15.1 |

`text-subtle` is used only for decorative marks, icons beside text and disabled labels, never for running text. `border` and `border-strong` are hairlines that separate, never the only cue for a control.

The scale is a native radio group usable by keyboard and screen reader. The drawer is a labelled `aside` with a labelled `nav`; the canvas is `inert` while it is open.

## Do's and Don'ts

- Do show party order by score only; ties are ordered alphabetically.
- Do label AI-generated content clearly.
- Do take every colour, font and shadow from `tokens.css`.
- Don't use party colours for bars or backgrounds.
- Don't recolour, crop or resize a logo per Party; every Party gets the same tile.
- Don't use red/green or per-side colours on the agreement scale.
- Don't put navigation on the Questionnaire steps; the Answers live only in page state.
- Don't load fonts, styles, scripts or images from another origin (the prototype's CDNs are not used).
- Don't load share widgets, SDKs, scripts or brand images; share targets are plain links (or the system share sheet).
- Don't use a Buy Me a Coffee widget, button image, script, logo or brand colours; the donation link is a plain link with the app's own coffee icon and neutral tokens.

## Open Design Questions

- None. (Party logos: settled by the user on 2026-10-26; logo licensing stays open in `docs/risks-and-open-questions.md`.)
