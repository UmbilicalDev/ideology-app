# Feature Implementation Spec: Feedback button and 'Ayúdanos a mejorar' dialog

## Source Feature

- `id`: feedback-dialog (GitHub issue #83)
- `area`: web
- `depends_on`: feedback-api (accepted), share-ideologiapp (accepted; only to serialise edits to the end screen)
- `status`: not_started at planning time
- `source`: `feature_list.json` (its `verification` list is binding; this spec adds detail, never removes a check)

## Goal

The Landing and the Questionnaire end screen get a `Danos tu opinión` button. It opens a modal dialog titled `Ayúdanos a mejorar`, subtitled `Dinos qué te ha parecido IdeologiApp`, with a labelled plain-text box (500 characters, counted as the server counts them), a live counter and an `Enviar` button. Enviar calls `sendFeedback` from `packages/core` with only the message and the origin (`landing` / `results`). On success the form becomes a thank-you message; on error the text is kept and a retry message is shown. On the end screen the Answers stay in memory and the URL does not change.

## Decisions

1. **Button.** Label `Danos tu opinión`, an outlined `button-secondary` pill with a new decorative `FeedbackIcon` (speech bubble, line style, `ui/icons.tsx`) before the text, `aria-haspopup="dialog"`. Not tonal (gold is reserved for focus / Important / result copy).
   - **Landing:** the last child of `main`, after the `Cómo funciona` section, in `<div className="feedback-entry">` (no heading).
   - **End screen** (`EndScreen` in `QuestionnaireFlow.tsx`): right after the `Cómo se calcula la afinidad` link paragraph and before the first `<HomeButton />`. The share card, the controls and everything else keep their order and markup.
   - Not on `/resultados`, `/metodologia`, Statement steps or Not found (non-goal).
2. **Component.** New `apps/web/src/features/feedback/FeedbackButton.tsx` (`FeedbackButton({ api: FeedbackApi, origin: FeedbackOrigin })`) owns the button, the open flag and the form state (`text`, `phase: "editing" | "sending" | "sent"`, `error: FeedbackError | null`), and renders `FeedbackDialog` (same folder) **only while open**. State lives in `FeedbackButton`, so a draft survives close/reopen while the page stays mounted; opening after `sent` resets to an empty `editing` form. Closing during `sending` does not abort: the result is still applied to the state.
3. **Modal: native `<dialog>` + `showModal()`.** Native gives the top layer, `::backdrop` and an inert page (focus never reaches page content). Added on top:
   - **Open:** a layout effect calls `showModal()` when `!dialog.open` (StrictMode-safe), then focuses the textarea (in `sent`, the Cerrar button).
   - **Tab wrap:** `onKeyDown` on the dialog: Tab on the last focusable element goes to the first, Shift+Tab on the first goes to the last (focusables = enabled `button`, `textarea`, `a[href]` inside the dialog, excluding `tabIndex=-1`), so Tab never leaves for the browser chrome either.
   - **Escape:** `onCancel` → `preventDefault()` then `dialog.close()`; the same path in browsers and jsdom.
   - **Close button:** a 48px icon button `aria-label="Cerrar"` (new `CloseIcon`) at the header's end, in both phases; in `sent` also a filled `Cerrar` button.
   - **Backdrop:** a pointer click closes only if both `pointerdown` and `click` targeted the `<dialog>` element itself (the surface is an inner wrapper with the padding), so a text selection dragged out of the textarea never closes it.
   - **Every close** goes through `dialog.close()`; `onClose` sets `open=false` and focuses the trigger button (ref), never relying on the browser's own focus restoration.
   - **Name/description:** `aria-labelledby` → `h2#feedback-title` `Ayúdanos a mejorar`; `aria-describedby` → `p#feedback-subtitle` `Dinos qué te ha parecido IdeologiApp`.
   - **Scroll:** `:root:has(.feedback-dialog[open]) { overflow: hidden; }` (CSS only).
   - **jsdom** (29.1.1) has no `showModal`/`close`: `src/test/setup.ts` defines them on `HTMLDialogElement.prototype` only when missing (`showModal` sets `open`; `close` removes it and dispatches `close`).
4. **Form (`editing` / `sending`).** `<form noValidate>`:
   - `<label for="feedback-message">Tu opinión</label>` (visible), `<textarea id="feedback-message" rows={6}>` controlled, **no `maxLength`**, `aria-describedby="feedback-hint feedback-limit"` (plus `feedback-problem` when shown).
   - Hint `p#feedback-hint` (note style): `Solo se guarda el texto, la pantalla desde la que lo envías y la fecha. No escribas datos personales.` (consistent with the methodology `FEEDBACK_TEXT`; no methodology change).
   - `span#feedback-limit.visually-hidden`: `Máximo 500 caracteres.`
   - Visible counter `p.feedback__counter` `N/500`, `aria-hidden="true"`.
   - Polite announcer: a visually hidden `<p role="status">` (Decision 5).
   - Honeypot (Decision 7), error alert (Decision 6), sending status, then the actions row with `<button type="submit" className="button-primary">Enviar</button>`.
5. **Counting and the rule (risks-doc item).** `prepared = text.replace(/\t/g, " ")` (pasted tabs become spaces; nothing else is changed); `count = countFeedbackChars(trimFeedback(prepared))` (code points of what the server will store); `problem = feedbackProblem(prepared)`. Never `.length` or `maxLength`. Enviar is `disabled` while `problem !== null` or `phase === "sending"`. Typing past 500 is allowed (no truncation; a paste is never cut). Visible problem line `p#feedback-problem` (not live):
   - `too_long`: `Has superado el límite de 500 caracteres. Borra texto para poder enviar.`
   - `control_character`: `El texto tiene caracteres invisibles que no se pueden enviar. Prueba a escribirlo en lugar de pegarlo.`
   - `empty`: no message (the button is just disabled).
   Announcer text, by `remaining = 500 - count` (changes only when the band changes, so each band is announced once): `> 50` → empty; `26..50` → `Quedan 50 caracteres o menos.`; `11..25` → `Quedan 25 caracteres o menos.`; `1..10` → `Quedan 10 caracteres o menos.`; `0` → `Has llegado al límite de 500 caracteres.`; `< 0` → `Has superado el límite de 500 caracteres.` Pure helpers in `features/feedback/feedback-form.ts` (`prepareFeedback`, `counterText`, `limitAnnouncement`, `problemText`, `errorText`), tested directly.
6. **Send and errors.** Submit (when enabled; a ref guards double submit) → `phase="sending"`, error cleared, status line `Enviando tu opinión…` (`role="status"`), then `await api.sendFeedback({ message: trimFeedback(prepared), origin, website })`. Resolve → `phase="sent"`, `text=""`. Reject → `phase="editing"`, text kept, focus stays (or returns) on the textarea, `<p role="alert">` shows by `PublicApiError`:
   - `network`: `No se ha podido enviar tu opinión. Comprueba tu conexión e inténtalo de nuevo.`
   - `http` 429: `Se han enviado muchas opiniones en poco tiempo. Espera unos minutos e inténtalo de nuevo.` (`Retry-After` is not exposed by the client; not read.)
   - `http` 413 / 415 / 422: `El servidor no ha aceptado el mensaje. Revisa el texto e inténtalo de nuevo.`
   - any other status or non-`PublicApiError`: `No se ha podido enviar tu opinión. Inténtalo de nuevo más tarde.`
   The alert clears on the next edit or send. Retry = pressing Enviar again.
7. **Honeypot.** Inside the form, `<div className="visually-hidden" aria-hidden="true">` with `<label for="feedback-website">Sitio web (déjalo vacío)</label><input id="feedback-website" name="website" type="text" tabIndex={-1} autoComplete="off">` (controlled). Its value is passed as `website`; `sendFeedback` drops it when empty, so a real Voter's body is exactly `{message, origin}`. A filled honeypot gets the normal thank-you (the server answers 201).
8. **Thank-you (`sent`).** The form is replaced by a decorative `CheckCircleIcon` (primary), `p#feedback-thanks` (title-md) `¡Gracias por tu opinión!`, `p` `Nos ayuda a mejorar IdeologiApp.`, and a filled `Cerrar` button with `aria-describedby="feedback-thanks"`, which gets focus (so the thanks is read with it). Title, subtitle and the header close button stay.
9. **Answers and URL.** `FeedbackButton` never reads or receives Questionnaire state; it gets only `api` and `origin`. No navigation, no `history.*`, no hash, no storage. The draft text lives only in React state.
10. **Wiring.** `App` prop becomes `api: PublicApiClient`; `LandingPage` and `QuestionnairePage` take `PublicApi & FeedbackApi`; `QuestionnaireFlow` gets `feedbackApi: FeedbackApi` and passes it to `EndScreen`. `SharedResultsPage` keeps `PublicApi`. Components never call `fetch`.

## Implementation Notes (feedback-dialog implementer, 2026-10-29)

Found during the browser check; they refine Decision 3 without changing behaviour:

- Browsers fire the `close` event as a queued task after `dialog.close()`. The dialog's own close paths (Escape, both Cerrar buttons, backdrop) call `dialog.close()` and then report the close at once (`open=false`, focus on the trigger). `onClose` stays as a fallback, guarded so that it runs once. Otherwise a click on the trigger in that gap was lost, and the late event then closed the dialog again.
- `global.css` `main > * > :last-child { margin-bottom: 0 }` matched the dialog, which is the last child of `div.feedback-entry`, and pinned it to the bottom of the viewport. `dialog.feedback-dialog { margin: auto }` restores centring.
- While `sending`, the text area is `readOnly` and keeps focus (Enviar becomes disabled), so the text that a failed send keeps is the text that was sent.

## Non-Goals

- Any backend or `packages/core` change (the API, rule and client are accepted in `feedback-api`); retention, moderation, CAPTCHA.
- Feedback on `/resultados`, `/metodologia`, Statement steps or Not found; a floating/sticky button.
- Changing the share card, `ShareResults`/`ShareApp`, the methodology copy or the Landing privacy text.
- An error colour role, a dialog library, or a new dependency.

## Job Story

When I have used IdeologiApp (on the Landing or after my results),
I want to tell the team what I think in a short message,
so they can improve the tool without me losing my results or sharing anything else.

## Users And Permissions

- Voter (anonymous): opens the dialog, sends one message at a time under the server's rate limit. Nothing identifies them.

## Acceptance Scenarios

1. **Open/close (both screens).** Given the Landing (or the end screen), when the Voter activates `Danos tu opinión`, then a modal dialog named `Ayúdanos a mejorar` and described by `Dinos qué te ha parecido IdeologiApp` opens with focus in the `Tu opinión` textarea; Tab/Shift+Tab cycle inside it; Escape, the `Cerrar` icon button or a backdrop click close it and focus returns to `Danos tu opinión`. A drag-select ending on the backdrop does not close it.
2. **Counter and limit.** Typing `hola ` shows `4/500`; 500 `😀` show `500/500` and Enviar enabled; 501 characters show `501/500`, the too-long line, the announcer `Has superado el límite de 500 caracteres.`, and Enviar disabled. Empty or whitespace-only text disables Enviar. At 450 code points the announcer says `Quedan 50 caracteres o menos.`
3. **Tabs and controls.** Pasting `a\tb` sends `a b` (Enviar enabled). Pasting `a\u000Bb` disables Enviar and shows the invisible-characters line.
4. **Success.** With the POST answering 201, Enviar sends exactly one `POST /api/v1/feedback` whose parsed body equals `{ "message": "<trimmed text>", "origin": "landing" }` (`"results"` on the end screen); during the request Enviar is disabled and `Enviando tu opinión…` shows; then `¡Gracias por tu opinión!` and a focused `Cerrar` replace the form. Reopening shows an empty form.
5. **Errors.** For 429, 422, 500 and a rejected fetch, the matching Decision 6 alert shows, the text is unchanged and Enviar is enabled again; a second Enviar retries.
6. **Honeypot.** A filled `website` is sent as `website`; an empty one is absent from the body.
7. **End screen keeps the Answers.** Given answered Statements (one Important), when the Voter opens, sends, and closes the dialog, then the ranking text, summary and URL (`pathname+search+hash`, `history.length`) are unchanged, and `Volver a la última afirmación` still shows the previous answer checked. The body carries no Answers, Election or Dataset Version.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONSTRAINTS.md` (Client-side Matching, Web Client Styling, Voter Feedback, Public Copy), `ARCHITECTURE.md` (Web Client, Public API Client), `DESIGN.md`, `docs/design/civic-horizon.md` (Level 4 dialogs: `surface-container-highest` + `0 8px 24px -4px rgba(0, 31, 42, 0.16)`), `docs/risks-and-open-questions.md` ("Voter feedback" entry names this feature), `PROGRESS.md`, `feature_list.json`.
- `docs/specs/feedback-api.md`, `docs/specs/share-ideologiapp.md`, `.agents/skills/github-flow/references/practical-notes.md` (worktree browser check).
- `packages/core/src/domain/feedback.ts`, `src/application/feedback-api.ts`, `src/infrastructure/http/public-api-client.ts` (`sendFeedback`, `PublicApiError`), `src/index.ts` (exports present).
- `apps/web/src/main.tsx`, `app/App.tsx`, `features/landing/LandingPage.tsx` (+ test), `features/questionnaire/QuestionnaireFlow.tsx`, `QuestionnairePage.tsx` (+ test, URL capture at ~line 514), `features/share/ShareApp.tsx`, `ShareResults.tsx` (+ test, URL/history checks), `features/common/HomeButton.tsx`, `ui/icons.tsx`, `ui/tokens.css`, `ui/global.css`, `ui/components.css`, `ui/design-tokens.test.tsx`, `test/setup.ts`, `test/fetch-mocks.ts`.
- `node_modules/jsdom` 29.1.1 (main checkout, read only): `HTMLDialogElement` has no `showModal`/`close`.

### Existing Patterns To Follow

- Pages get `api` as a prop; tests inject a mocked `FetchLike` through `createPublicApiClient` and render `<App>` in a `MemoryRouter`.
- Status lines use `role="status"`, load errors `role="alert"` with plain text (no error colour exists in the palette).
- `button-primary` disabled style, `share__field` text-field style (16px font, small corner, `outline` border, `--color-card`), 3px `secondary` focus ring.
- Tokens only in `tokens.css`; `design-tokens.test.tsx` rejects literals elsewhere.

### Current Gaps

- No dialog, scrim, Level 4 elevation, textarea style or icon button exists; DESIGN.md says "there are no sticky bars or dialogs".
- `textarea:focus-visible` is not in the focus-ring rule.
- No persistent E2E harness (Vitest + jsdom only).

## Technical Approach

Pure helpers in `feedback-form.ts`; `FeedbackDialog` is presentational over props from `FeedbackButton` (state, handlers, refs). CSS in `components.css` under a `Feedback dialog` block: `.feedback-dialog` (padding 0, border 0, `width: min(36rem, 100% - 2 * var(--layout-margin))`, `max-height: calc(100dvh - 2 * var(--space-md))`, background `--md-sys-color-surface-container-highest`, `on-surface` text, `--md-sys-shape-corner-extra-large`, `box-shadow: var(--elevation-4)`), `::backdrop { background: var(--color-scrim) }`, `.feedback-dialog__surface` (padding `var(--space-lg)`, `overflow: auto`), header flex (title + icon button), `.feedback__field` (textarea: block, width 100%, `min-height: 8rem`, `resize: vertical`, `share__field` look, 16px font, padding `var(--space-sm)`), counter right-aligned body-md `on-surface-variant` (weight 600 and `on-surface` when over), actions end-aligned, `.icon-button` (48px circle, transparent, `on-surface-variant`, hover 8% `on-surface`). Tokens added in `tokens.css`: `--elevation-4` (light `0 8px 24px -4px rgba(0, 31, 42, 0.16)`, dark `0 8px 24px -4px rgba(0, 0, 0, 0.5)`), `--color-scrim` (`rgba(0, 0, 0, 0.32)`, both themes). Add `textarea:focus-visible` to the focus rule.

## Expected File Changes

- `DESIGN.md` — modify first (see Visual Design Impact).
- `apps/web/src/ui/tokens.css`, `components.css`, `icons.tsx` (`FeedbackIcon`, `CloseIcon`, `CheckCircleIcon`) — modify.
- `apps/web/src/features/feedback/FeedbackButton.tsx`, `FeedbackDialog.tsx`, `feedback-form.ts`, `FeedbackDialog.test.tsx`, `feedback-form.test.tsx` — create.
- `apps/web/src/app/App.tsx`, `features/landing/LandingPage.tsx`, `features/questionnaire/QuestionnairePage.tsx`, `QuestionnaireFlow.tsx` — modify (Decision 10, placement).
- `apps/web/src/features/landing/LandingPage.test.tsx`, `features/questionnaire/QuestionnairePage.test.tsx` — modify (button present, origin, Scenario 7).
- `apps/web/src/test/setup.ts` — dialog polyfill; `ui/design-tokens.test.tsx` only if a new token needs a guard.
- Docs listed below. No `src/ideology_app/`, `packages/core` or methodology change.

## Visual Design Impact

- UI involved: yes. Design source: `DESIGN.md` + `docs/design/civic-horizon.md`. No new design artifact.
- DESIGN.md updates (before code): frontmatter `components.feedback-button`, `feedback-dialog`, `text-area`, `icon-button`; `semantic.scrim` and `semantic.elevation-4`; Elevation section: levels 0–2 plus **Level 4: the feedback dialog** (remove "there are no … dialogs"); Components: Feedback button (placement per Decision 1), Feedback dialog (layout, close affordances, counter, problem line, alert, sending, thank-you), Text area, Icon button; Buttons list gains `Danos tu opinión` (outlined) and `Enviar`/`Cerrar` (filled); Core Screens 1 and 3 mention the button; Colors: errors use text only, no error role; contrast table rows (computed, light / dark): on-surface on surface-container-highest 13.3 / 9.5; on-surface-variant 7.2 / 7.2; primary 7.2 / 7.2; focus ring secondary on highest ≥ 3: 5.0 / 7.2; outline (field border) on highest ≥ 3: 3.5 / 3.9; on-surface on the field (`card`) 17.2 / 13.3.
- States to check: closed, editing empty, typing, near limit, over limit, invisible characters, sending, each error, sent; 375px (dialog 16px from the edges, actions wrap), ~700px, 1280px (36rem wide, centred); light and dark.

## Durable Documentation Impact

- `DESIGN.md`: update (above).
- `ARCHITECTURE.md`: update — Web Client: `features/feedback/` (button, dialog, helpers), `App` takes `PublicApiClient`, the jsdom dialog polyfill in `setup.ts`, the new test files; add `feedback-dialog` to "Current state".
- `CONSTRAINTS.md`: update — Voter Feedback: the dialog MUST count with `countFeedbackChars(trimFeedback(...))` and gate Enviar on `feedbackProblem`, never `maxLength`/`.length`; it MUST receive no Questionnaire state and send only through `sendFeedback`.
- `AGENTS.md`: not needed. `CONTEXT.md` / domain model: not needed. Methodology copy: not needed (privacy model unchanged).
- `docs/risks-and-open-questions.md`: edit the "Voter feedback" entry in place: replace the `For feedback-dialog:` tail with `Settled by feedback-dialog:` (tabs → spaces before sending, counter on `countFeedbackChars`, Enviar on `feedbackProblem`). Add Accepted Low: 429 says "unos minutos" (Retry-After not read); a browser autofill could fill the honeypot and silently drop a real message (`autoComplete="off"`, unusual name label; revisit if reported).

## Implementation Plan / Tasks

- [ ] 1. DESIGN.md, then tokens/CSS/icons.
- [ ] 2. `feedback-form.ts` + tests (bands, counts with emoji, tabs, error mapping).
- [ ] 3. `FeedbackButton`/`FeedbackDialog` + setup polyfill + component tests (Scenarios 1–6).
- [ ] 4. Wiring and placement (Decision 10, Decision 1); Landing and Questionnaire tests (Scenario 7).
- [ ] 5. `CI=true ./init.sh`; browser check; ARCHITECTURE, CONSTRAINTS, risks; `feature_list.json` evidence; `PROGRESS.md`.

## Verification Plan

- `CI=true ./init.sh` passes (pytest, typecheck, Vitest, build); `npm test` includes the new tests by name.
- Tests assert, via the mocked `FetchLike`: one POST per send, `init.method === "POST"`, parsed body keys exactly `message`, `origin` (+ `website` only in Scenario 6), never `answers`/ids; no `maxLength` attribute on the textarea; focus targets after open/close/success (`document.activeElement`); Escape via `fireEvent(dialog, new Event("cancel", { cancelable: true }))`; Tab wrap via `keyDown`.
- E2E: no harness exists; component tests plus the browser check cover the flow.
- **Browser check** (worktree build served per practical-notes, with `DATABASE_URL=sqlite:///<worktree>/data/ideology.db` read as in share-ideologiapp and `FEEDBACK_DATABASE_URL=sqlite:///<scratch>/feedback.db`, a free port; remove the temporary launch entry and scratch files afterwards). At 375px, ~700px and 1280px, light and dark, on the Landing and the end screen (after answering, with one Important):
  - Keyboard only: Tab to the button, Enter opens, focus in textarea, Tab/Shift+Tab wrap, Escape closes and focus returns; send with keyboard; Cerrar returns focus.
  - Pointer: open, close via icon button and backdrop; drag-select out of the textarea does not close; page does not scroll behind the dialog.
  - Counter near/over 500 (paste a long text), a pasted tab, success thank-you, 429 (6th send within 10 min), network error (stop the server, send, restart).
  - Network panel: the POST body is only `{message, origin}`; no other request fails unexpectedly; console clean. End screen: ranking and URL unchanged after closing; `Volver a la última afirmación` shows the answer.
  - `ideology feedback list --feedback-database-url sqlite:///<scratch>/feedback.db` shows the sent messages with the right origin.

## Evidence To Capture

- `CI=true ./init.sh` counts, the new test names per scenario, and the browser log (browser, widths × themes, keyboard and pointer results, observed POST bodies, 429/network copy, console/network findings, CLI listing). Record in `feature_list.json` `evidence` and `PROGRESS.md` (never `docs/validations/`).

## Validator Checklist

- [ ] All `feature_list.json` verification items met; Decisions 1–10 implemented as written (copy exact).
- [ ] DESIGN.md updated before code; tokens only in `tokens.css`.
- [ ] No `maxLength`/`.length` counting; Enviar gated on `feedbackProblem` and in-flight; tabs become spaces.
- [ ] Modal behaviour (focus in, wrap, Escape, close button, backdrop, focus return) checked in tests and a real browser.
- [ ] The POST carries only `message` + `origin` (+ non-empty `website`); Answers stay in memory, URL/history unchanged.
- [ ] Browser check at 375 / ~700 / 1280, light and dark, keyboard and pointer, both screens, recorded.
- [ ] ARCHITECTURE, CONSTRAINTS and the risks entry updated in place; no backend, core, share card or methodology change.
