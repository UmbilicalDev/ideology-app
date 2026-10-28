# Feature Implementation Spec: Share section split: share your result and share IdeologiApp

## Source Feature

- `id`: share-ideologiapp (GitHub issue #79)
- `area`: web
- `depends_on`: results-summary-card (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json` (its `verification` list is binding; this spec adds detail, never removes a check)

## Goal

The end screen's share card gets two parts: **Comparte tu resultado** (the existing Share Link part, unchanged) and **Comparte IdeologiApp**, a row of six share targets that share only the IdeologiApp home URL (`location.origin + '/'`): Copiar enlace, Facebook, WhatsApp, Instagram, X and Correo. The shared result page (`/resultados#…`) shows the same card with the **IdeologiApp part only**. Nothing a Voter answered ever reaches a share target, a request or the clipboard through this part.

## Decisions

- **Shared result page: yes, IdeologiApp part only** (the feature-note default). It renders only in the `ready` state (not in missing / invalid / not-found / error states, which keep just their message and `Volver al inicio`). Place it after the `Haz tú el cuestionario` paragraph and before `ResultsBreakdown`, which mirrors the end screen, where the card sits after the ranking. The page still has no `Copiar enlace` for the result (share-link-open decision kept).
- **End screen without scores** (every answered Statement skipped or without stances): the card shows only the IdeologiApp part. Sharing the app does not depend on a result. `Comparte tu resultado` stays hidden exactly as today.
- **One card, two sections.** A wrapper `<div className="share-card">` is the Level 1 card. Inside it is `<ShareResults>` (unchanged component, still `<section className="share" aria-labelledby="share-title">`) followed by a new `<ShareApp>` (`<section className="share-app" aria-labelledby="share-app-title">`, `h3` `Comparte IdeologiApp`, no title icon). When both are present they are separated by a 1px `outline-variant` divider (`.share + .share-app`). CSS moves the card frame from `.share` to `.share-card` (`.card, .share` → `.card, .share-card`). The class name `share` and all ShareResults markup stay as they are, because `ShareResults.test.tsx` asserts `className === "share"`.
- **Copy (Spanish, exact):**
  - Intro under the title: `Recomienda esta web a otras personas. Solo se comparte su dirección, sin ninguna respuesta.`
  - `SHARE_TEXT` = `Compara tus opiniones con los programas electorales de los partidos en IdeologiApp.`
  - WhatsApp `text` = `${SHARE_TEXT} ${home}`. X `text` = `SHARE_TEXT`, `url` = home. Facebook takes only `u` = home.
  - Email subject: `IdeologiApp: compara tus opiniones con los programas electorales`. Body: `${SHARE_TEXT}\r\n\r\n${home}` (RFC 6068: line breaks encoded as `%0D%0A`).
  - `navigator.share` data: `{ title: "IdeologiApp", text: SHARE_TEXT, url: home }`.
  - Status (own `role="status"` live region, `share__status` style): copy OK → `Enlace de IdeologiApp copiado.`; Instagram copy OK → `Enlace de IdeologiApp copiado. Ya puedes pegarlo en Instagram.`; copy failed → `No se ha podido copiar el enlace automáticamente. Cópialo desde este campo:` (Instagram path: `… Cópialo desde este campo y pégalo en Instagram:`), with a read-only field labelled `Enlace de IdeologiApp` (`id="share-app-url"`, class `share__field`), focused and selected like the result fallback.
- **Targets, order, visible captions and accessible names** (`aria-label`; each name contains its visible caption, WCAG 2.5.3):

  | Caption | Element | Accessible name | Action |
  |---|---|---|---|
  | Copiar enlace | `button` | `Copiar enlace de IdeologiApp` | clipboard ← home |
  | Facebook | `a` new tab | `Compartir IdeologiApp en Facebook` | `https://www.facebook.com/sharer/sharer.php?u=<enc home>` |
  | WhatsApp | `a` new tab | `Compartir IdeologiApp en WhatsApp` | `https://wa.me/?text=<enc text+home>` |
  | Instagram | `button` | `Compartir IdeologiApp en Instagram` | Web Share API, else copy |
  | X | `a` new tab | `Compartir IdeologiApp en X` | `https://x.com/intent/post?url=<enc home>&text=<enc text>` |
  | Correo | `a` in place | `Compartir IdeologiApp por correo electrónico` | `mailto:?subject=<enc>&body=<enc>` |

  New-tab links get `target="_blank" rel="noopener noreferrer"` and `aria-describedby` pointing to one visually hidden `(se abre en una pestaña nueva)` span in the section (the external-link convention, while the names stay exact). The mailto link has no `target`. Encoding is `encodeURIComponent` everywhere (spaces become `%20`, never `+`). The exact name `Copiar enlace` stays unique to the result part, so existing `getByRole("button", { name: "Copiar enlace" })` queries keep working.
- **Instagram behaviour:** if `typeof navigator.share === "function"`, `await navigator.share(data)`. On resolve, the status is cleared and nothing else happens. On rejection or a synchronous throw whose `name === "AbortError"` (the user cancelled), nothing happens: no message and no copy. Any other error (`NotAllowedError`, `TypeError`, …) falls back to the copy path with the Instagram messages. Without `navigator.share`, the copy path runs at once. Copy path = the same rules as the result `Copiar enlace`: `navigator.clipboard.writeText`, and if it is missing, throws or rejects, show the field. The clipboard may refuse after a rejected share because user activation was used up; the field covers that.
- **Pure URL builder:** `apps/web/src/features/share/app-share-links.ts`, no React, no `window`/`navigator`/`location` access. It exports `SHARE_TEXT`, `EMAIL_SUBJECT`, `appHomeUrl(origin: string): string` = `new URL("/", origin).href` (so any path, query or fragment passed in is dropped) and `appShareLinks(origin) → { home, facebook, whatsapp, x, email }`. The component calls it with `window.location.origin` at click/render time. It lives in `apps/web`, not `packages/core`, because it holds UI copy and the parallel `feedback-api` branch edits `packages/core/src/index.ts`. It is tested from a `.test.tsx` file (the web Vitest project only includes `*.test.tsx`) as plain function calls, with no rendering.
- **Brand icons:** new components in `apps/web/src/ui/icons.tsx`, drawn for this app as simplified glyphs (no SVG copied from brand kits or icon packs). They use a filled `BrandIcon` wrapper (`fill="currentColor"`, `stroke="none"`, same `aria-hidden`, `focusable="false"`, 24px viewBox as `Icon`): `FacebookIcon`, `WhatsAppIcon`, `InstagramIcon`, `XIcon`. `MailIcon` (envelope) is a line icon in the existing `Icon` style. `LinkIcon` is reused for Copiar enlace. No brand colours anywhere.
- **No dependency, no migration, no backend change, no methodology copy change** (privacy model unchanged: only the home URL leaves, by a Voter-started navigation or the clipboard).

## Non-Goals

- Feedback button and dialog (`feedback-dialog`); feedback API (`feedback-api`, parallel branch). Do not touch `src/ideology_app/`, `packages/core`, or `MethodologyPage.tsx`.
- Any change to `ShareResults.tsx` copy or behaviour, the Share Link codec, the loss note (`RESULTS_NOTE_SHARE`), or the shared page's error states.
- Sharing the result to social networks, Open Graph/Twitter-card meta tags, share counters, native-app deep links (`whatsapp://`, `instagram://`), or a QR code.

## Job Story

When I have finished the questionnaire (or opened a friend's shared result),
I want to tell others about IdeologiApp in one tap on the network I use,
so they can take the questionnaire themselves without seeing my answers.

## Users And Permissions

- Voter (anonymous): can copy or share the home URL. No server state, no request carries anything.

## Acceptance Scenarios

1. **End screen, two parts.** Given a finished Questionnaire with scores, when the end screen shows, then one card holds region `Comparte tu resultado` (copy, button, note unchanged) then region `Comparte IdeologiApp` with the intro and six targets in the table's order, names and captions.
2. **Copiar enlace (app).** Given the clipboard works, when the Voter activates `Copiar enlace de IdeologiApp`, then `writeText` gets exactly `${location.origin}/` and the app status reads `Enlace de IdeologiApp copiado.`. The result part's status stays empty. Given the clipboard is missing or denied, then the field `Enlace de IdeologiApp` shows the home URL, focused and selected.
3. **Plain links.** Facebook, WhatsApp and X `href`s equal the builder's output, with `target="_blank"` and `rel="noopener noreferrer"`. Correo's `href` is the mailto with no `target`. Clicking them causes no `fetch`, and no `script`, `img`, `iframe` or `link` element is added to the document.
4. **Instagram.** With `navigator.share` resolving: it is called once with `{ title, text, url: home }`, no clipboard call, empty status. Rejecting with `AbortError`: no clipboard call, empty status. Rejecting with `NotAllowedError`: clipboard gets home and the Instagram copied message shows. Without `navigator.share`: the same copy and message. Clipboard also failing: the Instagram field message and the field.
5. **No answers leak.** Given jsdom's location is `/resultados#v1-1-dddddA` (set in the test with `history.replaceState`, restored afterwards), every built URL, the clipboard text and the share data contain no `#`, no `resultados`, no `v1-` and no answer letters. Here the home URL is `${origin}/`.
6. **End screen without scores.** Given all Statements skipped, then `Comparte tu resultado` is absent and `Comparte IdeologiApp` is present.
7. **Shared result.** Given a `ready` Share Link, then the page shows `Comparte IdeologiApp` (and not `Comparte tu resultado` / `Copiar enlace`) between the CTA and the breakdown. Given a missing/invalid link, then no share section shows.
8. **Unchanged.** `ShareResults.test.tsx` and `SharedResultsPage.test.tsx` pass without edits (`git diff` empty for both). The answers stay in memory after using any target: Back to review still works.
9. **Accessibility and layout.** Every target is ≥ 48×48px with the 3px `secondary` focus ring and is reachable by Tab in table order. At 375px the row wraps with no horizontal scroll. Icons are `aria-hidden` and use no colour other than `currentColor`.

## Repository Research

### Files Inspected

- `apps/web/src/features/share/ShareResults.tsx` + `.test.tsx`: the copy/fallback pattern to mirror; the tests pin `className="share"`, exact names, and that there is no `Copiar enlace` button when there are no scores.
- `apps/web/src/features/share/SharedResultsPage.tsx` + `.test.tsx`: `SharedResult` layout; Scenario 8 asserts that no `Copiar enlace` and no `Comparte tu resultado` exist (exact-name queries, so they are unaffected).
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx` (`EndScreen`, lines ~234-290): `ShareResults` is rendered only when `hasScores`.
- `apps/web/src/features/paths.ts` (`sharedResultsUrl`), `apps/web/src/ui/icons.tsx` (`Icon`: stroke, `aria-hidden`), `apps/web/src/ui/components.css` (`.card, .share` frame, `.share__*`, focus ring rule at line ~71, `.visually-hidden`, buttons), `tokens.css` (`--card-padding` 16px / 24px), `design-tokens.test.tsx` (no literal colours in CSS).
- `vite.config.ts` / `vitest.config.ts`: web tests run in jsdom and include only `src/**/*.test.tsx`; core tests run in node.
- `DESIGN.md` (Share card, Icons, Focus, Buttons, Colors), `docs/design/civic-horizon.md`, `CONSTRAINTS.md` (Client-side Matching, Web Client Styling), `CONTEXT.md` (Share Link), `docs/specs/share-link-create.md`, `docs/specs/share-link-open.md`, `docs/risks-and-open-questions.md` (no entry names this feature), `.agents/skills/github-flow/references/practical-notes.md` (browser checks of a worktree).

### Existing Patterns To Follow

- Copy-to-clipboard with a focused read-only fallback field and a `role="status"` line (ShareResults). Spanish copy as module constants. Tests render `App` in `MemoryRouter` with a mocked `FetchLike` and query by role. `navigator.clipboard` is defined with `Object.defineProperty` and deleted in `afterEach`, and `navigator.share` should be handled the same way.

### Current Gaps

- There are no brand or mail icons, no filled-icon wrapper and no icon-button style yet.

## Technical Approach

1. Add `app-share-links.ts` (pure).
2. Add `ShareApp.tsx`: a state machine like `CopyState` (`idle | copied | fallback{url, attempt}`) plus a `via: "copy" | "instagram"` flag for the message wording. Markup: `section.share-app` > `h3#share-app-title.share__title` > `p` intro > `ul.share-targets` of six `li`, each holding an `a`/`button.share-target` with `span.share-target__icon` (the icon) and `span.share-target__label` (the caption) > `p[role=status].share__status` > optional label + field > hidden new-tab span.
3. Edit `EndScreen` to render `div.share-card` > (`ShareResults` if `hasScores`) + `ShareApp`, and `SharedResult` to render `div.share-card` > `ShareApp`.
4. CSS: `.share-target` is a column flex with a fixed width of about 4.5rem, centred `label-md` caption in `on-surface-variant`, 48px circular icon area with a 1px `outline` border on `card`, icon `on-surface`, hover 8% `on-surface` state layer. `ul.share-targets` is a wrapping flex with `gap` sm/md, no list bullets or padding. Focus comes from the global rule (applies to the whole tile). Everything uses token variables only.

## Expected File Changes

- `DESIGN.md`: modify **first** (see Visual Design Impact).
- `apps/web/src/features/share/app-share-links.ts`: create; `app-share-links.test.tsx`: create.
- `apps/web/src/features/share/ShareApp.tsx`: create; `ShareApp.test.tsx`: create (Scenarios 1-7, 9 where jsdom can check: names, order, attributes, aria-hidden, no colour attributes other than `currentColor`/`none`).
- `apps/web/src/features/questionnaire/QuestionnaireFlow.tsx`, `apps/web/src/features/share/SharedResultsPage.tsx`: modify (wrapper and placement only).
- `apps/web/src/ui/icons.tsx`: modify (`BrandIcon`, four brand glyphs, `MailIcon`). `apps/web/src/ui/components.css`: modify.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`, `PROGRESS.md`, `feature_list.json`: modify (below).
- Must stay untouched: `ShareResults.tsx`, `ShareResults.test.tsx`, `SharedResultsPage.test.tsx`, `packages/core/**`, `src/**`, `MethodologyPage.tsx`.

## Visual Design Impact

- UI involved: yes. Source: `DESIGN.md` + `docs/design/civic-horizon.md`. Screens: end screen (Results), shared result. No new design artifact.
- `DESIGN.md` update (land it before the code, in the same PR):
  - Front matter `components`: `share-card` (level 1 card holding the `share` and `share-app` sections, `outline-variant` divider between them) and `share-target` (`icon: 48px circle, 1px outline, card background, icon on-surface`, `caption: label-md on-surface-variant`, `minTarget: 48px`, `hover: 8% on-surface`, `colours: neutral tokens only, never brand colours`).
  - Components → **Share card**: rewrite it for two sections; the result part is described as today; the IdeologiApp part lists the intro, the six targets in order with captions, links in a new tab (mailto in place), Instagram via the system share sheet else copy, and the status/field fallback. State that the shared result shows the IdeologiApp part only, and the end screen without scores too.
  - **Icons**: add that brand glyphs (Facebook, WhatsApp, Instagram, X) are simplified filled marks drawn for this app in `currentColor`, never in brand colours. They are the only icons without adjacent full text: the caption names the network and the accessible name says the action.
  - **Buttons**: `Copiar enlace` (tonal) remains the result button only; the share targets are not tonal. Colors: secondary (gold) is not used by share targets. Core Screens 3 and 5: mention the share card / IdeologiApp part.
  - Do's and Don'ts: "Don't load share widgets, SDKs, scripts or brand images; share targets are plain links".
- States the implementer must style: idle, hover, focus-visible, copied status, fallback field, both themes, wrap at 375px (expect 3 + 3 tiles), one row at about 700px and 1280px.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update Web Client → Shared result / share entries: `ShareApp`, `app-share-links.ts`, the `share-card` wrapper on both pages, test list.
- `CONSTRAINTS.md`: update "Client-side Matching" with one rule: the IdeologiApp share targets MUST share only `appHomeUrl(location.origin)` (built only by `app-share-links.ts`; never a path, query, fragment, Dataset Version id or Answers). Third-party share targets MUST be plain Voter-started navigations (links or `navigator.share`), with no SDK, script, image, iframe or preconnect. Reason: answers never leave, and the no-other-origin rule. (`feedback-api` edits another section of this file; rebase if it merges first.)
- `AGENTS.md`: not needed. `CONTEXT.md`: not needed (sharing the home URL is not a Share Link; the spec and ARCHITECTURE say so). Methodology copy: not needed (privacy model unchanged).
- `docs/risks-and-open-questions.md`: add under Risks / Accepted Low (owner `share-ideologiapp` unless stated): (a) third-party share endpoints (`sharer.php`, `wa.me`, `x.com/intent/post`) can change without notice, so check them when the share card is next touched; (b) brand-mark guidelines: the glyphs are simplified originals, and a brand owner could object, so revisit before a public launch; (c) a `mailto:` handler registered by webmail may open in the same tab in some browsers and lose the in-memory end screen (record what the browser check observed); (d) on desktop, `navigator.share` exists in some browsers and its sheet may not offer Instagram, which is accepted.

## Implementation Plan / Tasks

- [ ] 1. Update `DESIGN.md` as above.
- [ ] 2. Write `app-share-links.test.tsx` (exact strings for origin `https://ideologiapp.example`; `appHomeUrl("https://ideologiapp.example/resultados?x=1#v1-1-dddddA")` → `https://ideologiapp.example/`; decoding each link's params returns home and text; mailto has `%20` and no `+`, and `%0D%0A%0D%0A`; no output contains `#`), then implement the builder.
- [ ] 3. Add the icons; then `ShareApp.tsx` + `ShareApp.test.tsx` (Scenarios 1-7, 9; assert `fetch` call counts unchanged by clicks; restore `navigator.share`/`clipboard`/location in `afterEach`).
- [ ] 4. Wire `EndScreen` and `SharedResult`; CSS; confirm `ShareResults.test.tsx` and `SharedResultsPage.test.tsx` are unedited and green.
- [ ] 5. `./init.sh`; browser check; update ARCHITECTURE, CONSTRAINTS, risks, `feature_list.json` evidence, `PROGRESS.md`.

## Verification Plan

- `./init.sh` (pytest, typecheck, `npm test`, build; never starts a server) passes.
- E2E: no persistent E2E harness exists (Vitest + jsdom only). Component tests and the browser check below cover the flow.
- **Browser check** (worktree build served per practical-notes "Checking A Worktree's Build In A Browser", e.g. the committed `data/ideology.db`, a port other than 8000; remove the temporary launch entry afterwards). At 375px, about 700px and 1280px, each in light and dark:
  - Landing → Questionnaire → end screen with scores: both parts visible and the row wraps without horizontal scroll at 375px. Tab through the targets: the focus ring is visible on each and the order matches the table.
  - Copiar enlace: status shown, and pasting the clipboard (or reading the fallback field if the browser denies the clipboard) gives exactly `http://127.0.0.1:<port>/`.
  - Facebook, WhatsApp, X: each opens a new tab whose URL carries only the encoded home URL (and text). Close it, and the end screen is still there with its answers. If the browser tool cannot follow new tabs, read `href`/`target`/`rel` from the DOM and record that limitation.
  - Correo: the `href` is right; after clicking, the end screen and answers are still there (or record what the browser did, see risk (c)).
  - Instagram: record which path ran (share sheet or copy plus message). Cancelling the sheet shows no message.
  - Result part: `Copiar enlace` still copies the `/resultados#…` link as before.
  - End screen with all Statements skipped: only the IdeologiApp part. Shared result (`ready`): only the IdeologiApp part, before the breakdown, and its copy gives the home URL, not the address-bar fragment. An invalid link shows no share section.
  - Console: no errors. Network: only same-origin requests on the app tab, no request to Facebook/WhatsApp/X/Instagram from the page itself, no failed request, and no request URL, header or body contains Answers or the fragment.

## Evidence To Capture

- `./init.sh` summary and the new test names / counts; `git diff --stat` showing the untouched files list empty.
- Browser log: browser name, widths × themes, each scenario's result, observed new-tab URLs, Instagram path, mailto behaviour, console/network findings. Recorded in `feature_list.json` `evidence` and `PROGRESS.md` (never `docs/validations/`).

## Validator Checklist

- [ ] `DESIGN.md` updated with the two sections, the share-target row, brand glyphs in `currentColor`, neutral tokens, no brand colours, 48px targets, focus ring, wrap at 375px.
- [ ] Builder is pure, unit-tested, and the home URL is always `origin + '/'` (no fragment, Dataset Version id or answers).
- [ ] Links have exact `href`s, `target="_blank" rel="noopener noreferrer"` (mailto in place); no third-party script, SDK, image, iframe or preconnect.
- [ ] Instagram: share sheet → nothing else; AbortError → silent; other errors and missing API → copy with the Instagram message (field on failure).
- [ ] Accessible names exactly as in the table; the captions are visible; the icons are `aria-hidden`.
- [ ] `Comparte tu resultado` unchanged: its component and both existing test files have no diff and are green.
- [ ] Shared result shows the IdeologiApp part only, in `ready` only.
- [ ] ARCHITECTURE, CONSTRAINTS and risks updated; no backend, `packages/core` or methodology change.
- [ ] Browser check at 375 / ~700 / 1280, light and dark, recorded with console and network results.
