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
- `apps/web/src/assets/ideologiapp-logo-light.svg`: the **light-theme** variant, the same drawing with the white (`#F9FBFA`) swapped for slate `#0F172A` (palette swap of the embedded PNGs, nothing else changed), because white vanishes on light surfaces. `ProductLogo` (`features/common/ProductLogo.tsx`) serves both through `<picture>` with `prefers-color-scheme: light`; it is used in the sidebar, the Landing hero (below 768px) and the focus bar.
- `apps/web/src/assets/ideologiapp-favicon.svg`: the tab icon (`<link rel="icon">` in `apps/web/index.html` and `apps/web/admin/index.html`): both variants in one SVG, switched by an inner `@media (prefers-color-scheme: light)`.
- `apps/web/src/assets/ideologiapp-touch-icon.png`: the home-screen icon (`apple-touch-icon`), 180x180, the dark variant on an opaque slate `#0F172A` square (iOS shows transparency as black). Regenerate it if the logo changes.
- `apps/web/public/favicon.ico`: 16/32/48px PNG-in-ICO fallback of the light variant (slate box, readable on light and dark tab bars). Regenerate it with the touch icon.
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
- **Highlight** (amber): only the Voter's Important flag (toggle, mark, summary star), the `Revisado` admin chip and the `Próximamente` status badge. Amber means "marked by you" or "not yet", never a party.
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

- **App shell** (every Voter page except the Questionnaire): a 256px sidebar (`bg-sidebar`, right hairline) with the brand (logo + `IdeologiApp`, a link home), the tagline `Comparador de programas electorales`, the section nav (`Ir al inicio` `/` with a house icon, a plain link never marked current, shown only on the shared result `/resultados`; `Elecciones` `/`, `Cómo funciona` `/metodologia`, `Transparencia IA` `/transparencia`; the current one gets `surface-raised`, a `border-strong` frame, accent text and `aria-current="page"`) and, in its footer, `Danos tu opinión`. The canvas has a sticky 56px top bar with the crumb `IDEOLOGIAPP / <SECCIÓN>` (its `IdeologiApp` root is a link home), the page in a column at most 72rem wide, and a footer line saying the tool is not a voting recommendation and the content is AI-generated.
- **Below 768px** the sidebar is a modal drawer (85vw, at most 256px) opened by the top bar's menu button (`Abrir menú`, `aria-expanded`, `aria-controls`). While open the canvas is `inert` and does not scroll, a scrim covers it, and focus moves into the drawer. Escape (unless the feedback dialog is open), the scrim, `Cerrar menú`, a link or growing past 768px close it. A link closes it in the same update as the navigation, so the new page can focus its `h1`; every other close (and a link to the current page) returns focus to the menu button.
- **Focus shell** (the Questionnaire, `/elecciones/:id/cuestionario`): no sidebar, so no stray navigation loses the in-memory Answers. A sticky bar with the brand (a link home, named `IdeologiApp, ir al inicio`) and `Salir` (a link home); both discard the in-memory Answers, and one centred 48rem column for the steps and the results.
- Landing elections: 1 column, 2 from 640px. Steps and Transparencia feature cards: 1 column, 3 from 640px. Methodology: a page index (`En esta página`) above the text, a sticky right column from 1024px.
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

- **Buttons.** Solid (`button-primary`, `accent-fill`): Siguiente, Revisar mis respuestas, Reintentar, Enviar, Cerrar (dialog), shared-result CTAs. Outlined (`button-secondary`, `surface` with `border-control`): Saltar esta afirmación, Anterior, Danos tu opinión, Volver al inicio (only on loading and error states). Soft (`button-tonal`, `accent-soft` with a `border-control` frame): only the result `Copiar enlace`. Disabled: `surface-raised`, `text-subtle` label. DOM order stays the reading and focus order.
- **Status badge**: `Disponible` (accent soft), `En preparación` (neutral, an Election with no published Dataset Version), `Próximamente` (amber soft).
- **Election card** (Landing grid): the status badge (outside the link), then one link stretched over the card with the name (`title-lg`, accent on hover), the date with a calendar icon above a hairline, and a solid `Realizar cuestionario →` bar (`--button-height-tall`); hover raises it (`border-strong`, `shadow-lg`), keyboard focus rings the whole card. The grid ends with a fixed **upcoming card** (`Próximamente`, `Elecciones generales 2026`, the trial notice and a decorative disabled bar of the same height), which is not a link.
- **Hero** (Landing): the tagline as an accent `overline` eyebrow, the `h1` and a `title-lg` muted lead, over a decorative blurred `hero-glow`.
- **Steps** (Landing `Cómo funciona`): three numbered tiles (`Responde a las afirmaciones`, `Comparamos con los programas`, `Consulta tu afinidad`), the checks/privacy sentence and the `Lee la metodología completa` link in the section head.
- **Page index**: `En esta página` with in-page links to each section heading (scroll margin clears the top bar).
- **Feature card** (Transparencia IA): an icon tile, a `title` heading and `body-sm` copy.
- **Statement card**: the progress label (accent `overline`) and a 6px bar, the Statement, the Important row, the 5-option scale, the skipped note and the controls under a hairline: one row of equal-width buttons in the order `Anterior` (leading back arrow, from the second Statement), `Saltar esta afirmación` (leading step-over icon), `Siguiente` (solid, trailing forward arrow), `--button-height-tall` tall (52px, 56px on coarse pointers); on the first Statement the two buttons take half each. Long labels wrap inside their button.
- **Step transition**: after Siguiente, Saltar or Anterior (and Revisar mis respuestas), only the Statement, the Important row, the scale and the skipped note fade in from 16px over 0.22s (`cubic-bezier(0.2, 0.7, 0.3, 1)`): from the right going forward, from the left going back. No transition on the first load. The progress label, the progress bar (whose fill widens with a 0.3s transition) and the controls never move, so repeated taps land on the same buttons. None under reduced motion.
- **Scale option**: a 48px row on `surface-sunken` with a `border-control` frame and a custom circle radio (native under forced colours), then the value's scale icon (32x24, `text-muted`, accent when checked) and the label. Checked: `accent-soft` with an `accent` frame, an accent dot and weight 600, the same for every value.
- **Important toggle**: outlined with an amber outline star; pressed, `highlight-soft` with a filled star and weight 600. The star shape and `aria-pressed` carry the state. Turning it on plays one subtle amber glow (0.6s ring and star pop; none under reduced motion). The hint `Las afirmaciones importantes cuentan el doble…` is a tooltip under the toggle on hover or keyboard focus, and always its `aria-describedby`.
- **Disclosure card / notice card**: a translucent `surface` panel with an accent icon tile (shield / info).
- **Summary card**: the 64px donut (accent arc, `surface-raised` track, decorative), `Muestra evaluada: N/T afirmaciones contestadas`, the skipped count, the Important sentence with the amber star.
- **Ranking row**: party-logo tile, name + short name, `title-lg` percentage, a 6px accent bar, `n afirmaciones en común` and the `Baja cobertura` chip (accent soft) with its tooltip (`surface-raised`, `shadow-lg`). Every row looks the same.
- **Party logo**: as before: fixed white tile, `border-strong` frame, `sm` corner; 40px (48px from 640px) in the ranking, 32px in the breakdown; placeholder on failure; requested in Dataset Version Party order.
- **Results dashboard** (end screen and shared result): below 1024px one column in reading order (summary, `Revisar mis respuestas`, ranking, share card, `Danos tu opinión` on the end screen, notice, links). From 1024px a two-column grid: summary and actions on the left; the ranking on the right as a sticky card (`surface`, `lg`) capped at the viewport height with its own scroll (a region `Afinidad por partido`, a tab stop only from 1024px, where it can scroll); ranking rows go compact on `surface-sunken`. The DOM order is the same at every width. On the Questionnaire the focus-shell column widens from 48rem to 72rem while the results show.
- **Breakdown filters**: single-choice chips (`aria-pressed`, a `role="group"` `Filtrar afirmaciones`) with their row count: `Todas`, `De acuerdo` (De acuerdo + Muy de acuerdo), `Neutral`, `En desacuerdo` (+ Muy en desacuerdo), `Saltadas`, `Importantes`. Pill chips with a `border-control` frame; pressed: `accent-soft` with an `accent` frame. A visually hidden status says `N de T afirmaciones`; an empty filter shows `Ninguna afirmación coincide con este filtro.` They filter the matrix and the cards alike.
- **Statement matrix** (from 1024px, user decision 2026-10-31; cards stay below): a table in a bordered scroll box (sticky header row; the `Afirmación` column, `--matrix-statement-width` 18rem, 24rem from 1280px, and the answer column, `--matrix-answer-width` 3.5rem, stay sticky on the left when a narrow canvas scrolls the Party columns sideways, as on the shared result at 1024px inside the app shell; the box's `scroll-padding` clears the sticky header and columns so a keyboard-focused cell is never hidden under them): `Afirmación` (number + text clamped to 2 lines, a button that opens every Party's Position), `Tú` / `Enlace` (clicking it opens the Statement like its button, a pointer shortcut with no extra tab stop; the Answer as its scale icon, the step-over icon when skipped, `—` when unanswered, the amber star when Important, full label for screen readers), then one column per Party in ranking order (32px logo tile + short name, full name hidden). Each cell is a button with the stance as its scale icon (`—` for no stance) and the full stance and coincidence in its accessible name (`PSOE: De acuerdo, coincidencia 75 %. Ver la cita`). **Cell tint = coincidence with the Answer** (the matching rule's per-Statement agreement), one accent hue at `--match-100` 60 %, `--match-75` 42 %, `--match-50` 26 %, `--match-25` 12 % over `surface`, 0 % plain `surface`; no rated Answer or no stance: `surface-sunken` with muted text. Never a colour per side of the scale or per Party; every column and cell has the same markup. A legend above the table shows each scale icon with its label, the step-over icon (`Saltada`), `—` (no stance) and the five swatches.
- **Inspector panel**: a modal side sheet (native `<dialog>`, right edge, at most 32rem, full height, `surface`, `border-strong` left rule, `shadow-lg`, blurred `scrim`). It shows `Afirmación N`, the Statement (`title-lg`), the Answer line, then for the chosen cell (or every Party, in ranking order) the tile, name, stance, `coincidencia contigo N %` and the Evidence (quote and locator, or the no-stance sentence); from a cell, `Ver todos los partidos en esta afirmación` switches to every Party and moves focus to the Statement heading. Focus starts on `Cerrar`; Escape, `Cerrar` or a backdrop click close it and focus returns to the cell or Statement that opened it (to the breakdown heading if the layout switched meanwhile). It shows only what the Dataset Version holds (stance, quote, page): there is no AI explanation to show. **Answer and stance icons** (inspector and mobile cards): the Answer value and every Party stance lead with their scale icon (step-over for a skipped Answer, none for unanswered or no stance), and the `Importante (cuenta el doble)` chip leads with the filled amber star; all decorative, the text carries the meaning.
- **Breakdown row**: the accent `overline` number, the Statement, the Voter's answer (and the amber `Importante (cuenta el doble)` mark), then one `<details>` per Party on `surface-sunken` with a chevron, the 32px tile and the name/short/value text box.
- **Evidence quote**: `body` on `surface` with a 3px accent left rule; never italic.
- **Share card**: one card, `Comparte tu resultado` (an info icon button `Privacidad del enlace` at the top right toggles the note on how the link carries the Answers; soft `Copiar enlace`, fallback field) then `Comparte IdeologiApp` (six 48px square tiles with `border-control`, captions in `caption`), separated by a hairline. Behaviour unchanged.
- **Feedback button**: `Danos tu opinión`, outlined, full width in the sidebar footer (every app-shell page; origin `landing`, shown as `General` to Operators) and on the results end screen (origin `results`). It is not in the Questionnaire steps.
- **Feedback dialog**: a native modal `<dialog>`, `surface` with a `border-strong` frame, `lg` corner, `shadow-lg`, over the blurred `scrim`; at most 32rem wide. Content and behaviour unchanged (title `Ayúdanos a mejorar`, subtitle, `Tu opinión`, counter, hint, Enviar, thanks state).
- **Text fields** (share fallback, feedback, admin): `surface-sunken`, `border-control`, `md` corner, 16px text.
- **Icon button**: 44px, `md` corner, `text-muted` icon, `surface-raised` hover; the dialog close, `Abrir menú` and `Cerrar menú`.
- **Icons**: inline SVG drawn for this app (now also menu, ballot, book, chip, calendar, shield, home, back arrow, step-over and the answer scale on a 32x24 canvas: line thumb down, thumb up and a thumb up/down pair; for the two `Muy` grades the filled double-thumb glyph supplied by the product owner, flipped vertically for `Muy en desacuerdo`), `currentColor`, `aria-hidden`; meaning in the adjacent text or `aria-label`. Brand glyphs on share targets stay neutral.
- **Focus**: a 2px solid `focus-ring` outline with a 2px offset on every link, button, field, summary and scale option.

## Core Screens

1. Landing (`/`, app shell): hero, `Elecciones disponibles` grid (API order, then the upcoming card), `Cómo funciona` steps. No AI card (user decision 2026-10-31): the shell footer states it on every page and `Transparencia IA` explains it.
2. Questionnaire (focus shell): Statement card plus disclosure card.
3. Results (focus shell, end of the Questionnaire): the results dashboard (summary, controls (`Revisar mis respuestas` only; the focus bar's `Salir` and brand go home), ranking, share card, `Danos tu opinión`, disclaimer, methodology link (new tab)), then the breakdown (`Comprueba de dónde salen tus coincidencias`, `headline`) with filters: the Statement matrix with the inspector from 1024px, cards below.
4. Methodology (`/metodologia`, `Cómo funciona` in the nav): page index plus the full method.
5. Shared result (`/resultados#…`, app shell): the same results dashboard and breakdown (answer column `Enlace`), superseded notice, Comparte IdeologiApp, link errors.
6. Transparencia IA (`/transparencia`, app shell): what the AI does, what is checked, what stays in the browser, and what cannot be guaranteed; links to the methodology. Static, no request.
7. Not found (app shell; inside the focus shell for a bad Questionnaire id).

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

## Open Design Questions

- None. (Party logos: settled by the user on 2026-10-26; logo licensing stays open in `docs/risks-and-open-questions.md`.)
