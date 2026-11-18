# Feature Implementation Spec: Donate to the project with Buy Me a Coffee

## Source Feature

- `id`: donate-buymeacoffee
- `area`: web (plus one additive public API route and one server setting)
- `depends_on`: feedback-dialog (`accepted`; only to serialise edits to the end screen and the sidebar)
- `status`: not_started (at planning time, 2026-11-18)
- `source`: `feature_list.json`. `user_visible_behavior`, `verification` and `notes` were updated by the user on 2026-11-18 and are binding. This spec adds detail and never removes a check.

## Goal

When a Buy Me a Coffee profile is configured on the server, Voters get a quiet way to support IdeologiApp:

1. In the app-shell sidebar (and the drawer), the link `Invítanos a un café` sits directly below `Danos tu opinión`. There is no disclosure here.
2. At the end of the Questionnaire results screen, a low-key block shows the line `¿Quieres apoyar el proyecto?`, the same link and a closed-by-default disclosure, `¿Para qué se usan las donaciones?`.
3. `/legal` states the donation terms: donations are voluntary, they go through Buy Me a Coffee under its own terms and privacy policy, IdeologiApp gets no data from the visit, and donations made on behalf of political parties are not accepted.

When no valid profile is configured, none of this appears. The profile URL is server configuration (`DONATION_URL`), never code. The real URL is set later in Coolify, and the feature is complete with the link hidden.

## Decisions

1. **Setting: `DONATION_URL`.** It is read at startup by `config.parse_donation_url(raw)`, which runs in the `create_app` lifespan the same way the `LEGAL_*` settings do. `create_app(..., donation_url: str | None = None)` lets tests inject the raw value; `None` means read the environment. The value is trimmed, and blank means unset. After trimming, it must fully match `^https://(www\.)?buymeacoffee\.com/[A-Za-z0-9_-]{1,64}$` (user decision 2026-11-18: both `https://www.buymeacoffee.com/<perfil>` and `https://buymeacoffee.com/<perfil>`, with the same profile rules): lower-case scheme and host, exactly one path segment, and no port, userinfo, query, fragment or trailing slash. The result is `app.state.donation_url: str | None`, holding the configured form unchanged (no host rewriting).
2. **An invalid value hides the link. It does not stop startup.** The binding verification says "unset or invalid hides the link". `LEGAL_*` fails closed for a different reason: a half-configured legal notice must never be published. A donation link is optional and not legal information. For it, the conservative state is hidden, and a typo in Coolify must not take the site down during a campaign. An invalid value is therefore parsed to `None`, and the server logs exactly one warning: `Ignoring DONATION_URL: expected https://www.buymeacoffee.com/<perfil> or https://buymeacoffee.com/<perfil>; the donation link stays hidden.` The warning goes through `logging` (not `warnings`, because pytest runs with `filterwarnings=error`) and never echoes the value. The post-deploy runbook step catches it. The binding verification line was updated on 2026-11-18 to allow both host forms; "unset or invalid hides the link" is unchanged.
3. **Delivery: a new route, `GET /api/v1/donation`.** It has operationId `getDonation`, response model `DonationOut {url: str | null}` and `cached_json(..., POINTER_CACHE_CONTROL)` (public, max-age=60, ETag). It takes no parameters, opens no Session and reads only `app.state.donation_url`. Why not extend `/api/v1/legal-notice`? Every page needs the URL (sidebar, end screen), while only `/legal` needs the holders. Extending it would make every page load fetch personal data it does not show, and it would mix two concerns in one contract. Why not index.html injection or a build-time variable? `legal-privacy-page` rejected both for the same reasons (static `no-cache` serving; a rebuild per change).
4. **Core.** `packages/core/src/domain/donation.ts` exports `DONATION_URL_PATTERN` (the same regex, both host forms) and `isDonationUrl(value)`. `PublicApi.getDonationUrl(): Promise<string | null>` sends exactly `GET /api/v1/donation` with the usual `Accept` init, no query and no body. `parseDonation` requires a record whose `url` is `null` or a string that passes `isDonationUrl`; anything else is a `ContractError` naming `donation.url`. This is defence in depth, because the href is used verbatim. Export the new names from `index.ts`, and add the method to the `PublicApi` literal in `test/application/open-share-link.test.ts`.
5. **One request per page load, at the App level.** `apps/web/src/features/donate/useDonationUrl.ts` (`useDonationUrl(api)`) is called once in `App`. It returns `string | null`, which is `null` while loading, on any error and when unset. Stale results are ignored, nothing is logged and there is no retry. `App` wraps `<Routes>` in `DonationUrlContext.Provider`, defined in `features/donate/donation-context.ts` with default `null`. The sidebar, the end screen and `LegalPage` read the URL with `useContext`. Why the App level: the Questionnaire is outside `AppShell`, so one hook in `App` covers every consumer. It sends one request per load, which carries nothing and does not depend on the Answers, and it never fires at the moment the end screen appears. Because `admin/main.tsx` does not render `App`, the admin bundle never sends it.
6. **The link.** `features/donate/DonationLink.tsx` renders `<a href={url} target="_blank" rel="noopener noreferrer">` with the new `CoffeeIcon`, the text `Invítanos a un café`, `<span className="visually-hidden"> (se abre en una pestaña nueva)</span>` and the existing `ExternalLinkIcon`. Its accessible name is `Invítanos a un café (se abre en una pestaña nueva)`. The href is exactly the configured URL, in whichever host form was configured: no query, no `utm`, no fragment, no Dataset Version and no Answers. `noreferrer` means Buy Me a Coffee does not even learn the page path. Nothing from Buy Me a Coffee is loaded: no script, widget, iframe, image, font, preconnect or brand colour. It is a plain Voter-started navigation, like the share targets (`CONSTRAINTS.md`). It does not close the drawer, because the current tab does not navigate.
7. **Placement.**
   - Sidebar (`AppShell` `sidebar__footer`): `FeedbackButton`, then the donation link (`className="sidebar__donate-link"`, only when the URL is non-null), then the legal link. There is no donation link in `.app-footer`, because the user chose the sidebar only.
   - End screen (`EndScreen` in `QuestionnaireFlow.tsx`): `<DonationBlock />` is the last child, after `<ResultsBreakdown />`. Everything else keeps its order and markup. It receives no Questionnaire state, only the context value.
8. **The Shared Results page does not get the end block.** It is still covered by the sidebar and drawer link, because `/resultados` is an app-shell page. Reasons:
   - The ask is for the Voter who just used the tool. The person viewing someone else's result has not, and that page already has its own call to action (`Haz tú el cuestionario`).
   - A fundraising line placed under another person's political result could read as tied to that result. Neutrality and "non-invasive" both argue against it.
   - Donation stays one tap away in the sidebar, so no reach is lost.
   - `DonationBlock` is a separate component, not part of the shared results components (`ResultsSummary`, `ResultsRanking`, `ResultsBreakdown`), so nothing on `/resultados` changes.
9. **Disclosure: native `<details>`/`<summary>`, closed by default.** It is keyboard operable through Enter and Space on the summary, and the existing `summary:focus-visible` ring applies. It sits below the link line, so opening it never moves the link. It is shown only when the link is shown.
10. **`/legal` mentions donations only when the URL is configured.** This keeps the copy true: it never describes a channel that does not exist, and `LegalPage` reads the same context as the link. `LEGAL_LAST_UPDATED` becomes the merge date. Under `CONSTRAINTS.md` "Public Copy", `LegalPage.tsx` and its test change together. `Quién más accede a los datos` stays as it is: Buy Me a Coffee is not a recipient of the data that paragraph lists, because the visit happens on its site. A new `h3` explains that instead. `/metodologia` does not repeat the rule; it describes the method, not funding. This settles the open "whether the methodology page repeats it" in the risks doc.
11. **No real profile in git.** Tests and docs use only `https://www.buymeacoffee.com/perfil_de_prueba`.

## Exact Copy

Tests assert each line marked (T).

- Link text, in both places: `Invítanos a un café` (T), with its accessible name as in Decision 6 (T).
- Results line: `<p className="donate-block__line">¿Quieres apoyar el proyecto? <DonationLink /></p>` (T).
- Disclosure summary: `¿Para qué se usan las donaciones?` (T).
- Disclosure body:
  1. `Donar es una forma sencilla de apoyar IdeologiApp y de ayudarla a crecer: con las donaciones añadimos funciones nuevas o mejoramos las que ya hay, y pagamos el alojamiento de la web.` (T)
  2. `No aceptamos donaciones hechas en nombre de partidos políticos. Si detectamos una donación hecha en nombre de un partido político, la devolveremos.` (T)
- `/legal` → `Condiciones de uso`: a new paragraph right after `Puedes usar IdeologiApp gratis…`, shown only when configured: `Las donaciones son voluntarias: puedes usar IdeologiApp igual sin donar, y donar no cambia las afirmaciones, las posiciones de los partidos ni ningún resultado. No aceptamos donaciones hechas en nombre de partidos políticos. Si detectamos una donación hecha en nombre de un partido político, la devolveremos.` (T)
- `/legal` → `Política de privacidad`: a new `<h3>Donaciones</h3>` after `Quién más accede a los datos` and before `Tus derechos`, shown only when configured:
  1. `El enlace «Invítanos a un café» abre en una pestaña nueva la página del proyecto en Buy Me a Coffee, un servicio de otra empresa. Es un enlace normal: IdeologiApp no carga nada de Buy Me a Coffee, no registra si lo abres y no le envía tus respuestas ni la página desde la que llegas.` (T)
  2. `Si donas, lo haces en Buy Me a Coffee, con sus propias condiciones y su política de privacidad, y es ese servicio el que trata tus datos de pago. Las donaciones las recibe uno de los titulares en su cuenta de Buy Me a Coffee; de cada donación solo vemos lo que ese servicio muestra a quien la recibe y lo usamos únicamente para gestionarla y agradecerla.` (T). The holder is not named (User Decision 2).

## Non-Goals

- No Buy Me a Coffee widget, button image, script, iframe, brand colour or logo. No click counting or analytics. No server-side redirect.
- No donation link on the Landing body, the footer, the Questionnaire steps, `/metodologia`, `/transparencia` or the Shared Results body.
- No change to `Quién más accede`, the cookie section, `/metodologia` or the feedback flow.
- No automated enforcement of the no-party rule. The refund promise (User Decision 4) is a manual process for the receiving holder, recorded in the risks doc and the runbook.
- No admin UI for the setting.

## Job Story

When I have found IdeologiApp useful,
I want to see a discreet way to support it and to know what the money is for,
so I can contribute without feeling pushed and trust that parties cannot buy influence.

## Users And Permissions

- Voter: anonymous. Each page load sends one same-origin `GET /api/v1/donation` with no query, no body and no Answers. Following the link is the Voter's own new-tab navigation.
- Operator: sets `DONATION_URL` in Coolify. A restart applies it; no rebuild is needed.

## Acceptance Scenarios

### Scenario 1: configured, sidebar
Given `DONATION_URL=https://www.buymeacoffee.com/perfil_de_prueba`
When the Voter opens `/`, `/metodologia`, `/transparencia`, `/legal`, `/resultados#…` or a not-found path (at 375px and ~700px through `Abrir menú`)
Then the sidebar footer shows `Danos tu opinión`, `Invítanos a un café` and `Aviso legal y privacidad`, in that order. The link's href equals the configured URL, with `target="_blank"` and `rel="noopener noreferrer"`. There is no disclosure there. Activating the link opens a new tab and leaves the drawer and the page unchanged.

### Scenario 2: configured, end of the results
Given the same setting and a Voter who has answered and reached `Tus resultados`
Then the last element of the end screen is the block with the line, the link and the closed disclosure. Opening the summary by Enter, Space or pointer shows the two paragraphs, and closing it hides them. The link's position does not change. After the link is activated, the URL (`pathname+search+hash`), `history.length`, the ranking and the Answers are unchanged (`Revisar mis respuestas` shows them).

### Scenario 3: Shared Results
Given the same setting and a valid Share Link
Then `/resultados#…` shows the sidebar link but no `¿Quieres apoyar el proyecto?` block.

### Scenario 4: unset, invalid or failing
Given `DONATION_URL` is unset, blank, or any refused vector below, or `/api/v1/donation` fails or breaks the contract
Then there is no donation link, no block, no disclosure and no `/legal` donation copy anywhere, and no empty container or placeholder. With an invalid value the server starts (`/health` 200), logs the single warning, and `GET /api/v1/donation` returns `{"url": null}`.

### Scenario 5: /legal
Given the URL is configured, the `Condiciones de uso` paragraph and the `Donaciones` subsection appear with the exact copy. Given it is unset, neither appears and the rest of the page is unchanged.

### Shared Validation Vectors (server and client tests)
- Accepted:
  - `https://www.buymeacoffee.com/perfil_de_prueba`
  - `https://buymeacoffee.com/perfil_de_prueba`
  - `https://www.buymeacoffee.com/Perfil-2`
  - `https://buymeacoffee.com/Perfil-2`
  - a 64-character profile
  - (server only) the first value with surrounding spaces, which is trimmed
- Refused:
  - `http://www.buymeacoffee.com/perfil_de_prueba`
  - `http://buymeacoffee.com/perfil_de_prueba`
  - `https://www.buymeacoffee.com/`
  - `https://buymeacoffee.com/`
  - `https://m.buymeacoffee.com/perfil`
  - `https://wwwbuymeacoffee.com/perfil`
  - `https://buymeacoffee.com.evil.test/perfil`
  - `https://BuyMeACoffee.com/perfil`
  - `…/perfil_de_prueba/`
  - `…/a/b`
  - `…/perfil?ref=x`
  - `…/perfil#x`
  - `https://WWW.BUYMEACOFFEE.COM/perfil`
  - `https://www.buymeacoffee.com.evil.test/perfil`
  - `https://www.buymeacoffee.com@evil.test/perfil`
  - `https://www.buymeacoffee.com:443/perfil`
  - `…/perfil%20x`
  - `…/perfíl`
  - a 65-character profile
  - a profile containing `\n`
  - `javascript:alert(1)`

## Repository Research

### Files Inspected
- `AGENTS.md`, `CONTEXT.md` (no donation term needed), `DESIGN.md` (App shell, Components, Icons, Core Screens 3/5/8, Do's and Don'ts), `CONSTRAINTS.md` (Public API, Client-side Matching, Web Client Styling, Public Copy, Voter Feedback, Legal), `docs/risks-and-open-questions.md` (lines 15, 85, 136), `README.md` (variables table, Despliegue), `docs/technical-discovery.md` (configuration and run-time tables, runbook 3/6), `ARCHITECTURE.md` (lines 95–97, 147–148, 161, 179–183), `PROGRESS.md`, `docs/specs/{legal-privacy-page,feedback-dialog}.md`.
- `src/ideology_app/{config.py (LEGAL_* parser, lines 284–414), main.py (lifespan, app.state), api/routes.py (getLegalNotice), api/schemas.py, web.py (logger.warning pattern)}`, `tests/{conftest.py, test_public_api.py (route set at 664), test_legal_notice.py}`.
- `packages/core/src/{application/public-api.ts, infrastructure/http/public-api-client.ts (getParsed, parseLegalNotice), domain/legal-notice.ts, index.ts}`, `packages/core/test/application/open-share-link.test.ts:67` (a `PublicApi` literal).
- `apps/web/src/{app/App.tsx, features/shell/{AppShell,FocusShell}.tsx, features/questionnaire/{QuestionnairePage,QuestionnaireFlow}.tsx (EndScreen), features/share/SharedResultsPage.tsx, features/feedback/FeedbackButton.tsx, features/legal/{LegalPage.tsx,useLegalNotice.ts,browser-storage.test.tsx}, ui/icons.tsx, ui/components.css (.sidebar__legal-link, .position__summary chevron, summary:focus-visible), test/fetch-mocks.ts}`.

### Existing Patterns To Follow
- The `useLegalNotice`/`useElections` hook shape with an `active` flag. Settings parsed in the lifespan into `app.state`. `cached_json` with `POINTER_CACHE_CONTROL`.
- Native `<details>` (`.position`) with a CSS chevron. External links use `ExternalLinkIcon` plus visually hidden text (the methodology link on the end screen).
- `conftest.py` unsets environment variables. Tests render `<MemoryRouter><App api={createPublicApiClient({ fetch })} /></MemoryRouter>`.

### Current Gaps
- About 35 web test assertions pin exact fetch call lists or counts (`App.test`, `LandingPage`, `QuestionnairePage`, `ResultsBreakdownFlow`, `SharedResultsPage`, `LegalPage`, `ShareApp`, `ShareResults`, `FeedbackDialog`, `Methodology`, `Transparency`). The App-level request changes them (Decision 5). React runs child effects first, so the donation call comes after a page's first call.
- Tests that queue `mockResolvedValueOnce` (`LandingPage`, `FeedbackDialog`) must route by URL.
- No E2E harness exists.

## Technical Approach

Server: the parser, the logged warning, `DonationOut`, the route and `app.state.donation_url` all follow the shape of `legal-privacy-page`. Core: the domain pattern, the port method and the parser. Web: the hook in `App`, the context, `DonationLink`, `DonationBlock`, the sidebar slot, the end-screen slot and the conditional `/legal` copy. Add a test helper `apiPaths(fetch)` in `test/fetch-mocks.ts`. It returns the requested URLs without `/api/v1/donation`. Existing "no request" and order assertions switch to it, so their intent is kept: no Election or Dataset request, and the logo order is unchanged. One dedicated test then pins that the donation request is exactly one bare GET per `App` mount.

## Expected File Changes

- Python:
  - modify `config.py` (`DONATION_URL_RE`, `parse_donation_url`, `donation_url()`), `api/schemas.py` (`DonationOut`), `api/routes.py` (the route; update the module docstring count) and `main.py` (the parameter and `app.state`);
  - create `tests/test_donation.py`;
  - modify `tests/conftest.py` (unset `DONATION_URL`), `tests/test_public_api.py` (route set, OpenAPI `getDonation`/`DonationOut`) and `tests/test_legal_notice.py` (no `Set-Cookie` on `/api/v1/donation`).
- Core: create `src/domain/donation.ts` and `test/domain/donation.test.ts`; modify `application/public-api.ts`, `infrastructure/http/public-api-client.ts`, `index.ts`, `test/infrastructure/public-api-client.test.ts` and `test/application/open-share-link.test.ts`.
- Web:
  - create `features/donate/{useDonationUrl.ts, donation-context.ts, DonationLink.tsx, DonationBlock.tsx, DonationBlock.test.tsx, donate-sources.test.tsx}`;
  - modify `app/App.tsx`, `features/shell/AppShell.tsx`, `features/questionnaire/QuestionnaireFlow.tsx`, `features/legal/LegalPage.tsx` and `ui/icons.tsx` (`CoffeeIcon`, an original line cup with steam on the 24px `Icon` frame, not the Buy Me a Coffee mark);
  - modify `ui/components.css` and `test/fetch-mocks.ts`;
  - update the tests listed in Current Gaps, plus `AppShell.test.tsx`, `QuestionnairePage.test.tsx`, `SharedResultsPage.test.tsx` and `LegalPage.test.tsx` for the new scenarios.
- Docs: `DESIGN.md` (first), `CONSTRAINTS.md`, `ARCHITECTURE.md`, `README.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `feature_list.json`, `PROGRESS.md`.

## Visual Design Impact

- UI is involved. The source is `DESIGN.md`, updated first. No new token, no new contrast pair, no design artifact.
- Sidebar link: like `.sidebar__legal-link` (`body-sm`, `text-muted`, accent and underline on hover, at least 44px, centred), with a 20px coffee icon and the external icon, `space-xs` gaps. It must not wrap at 256px.
- End block (`.donate-block`): a `border` hairline on top, `space-2xl` above and `space-lg` padding-top, 72ch measure, `body-sm` `text-muted`. The link uses `text-link` (accent). There is no card, surface, button styling or highlight. The summary is `body-sm` `text-muted`, accent on hover, at least 44px, with the `.position__summary` style chevron in `text-muted`. Opened text is `body-sm` `text-muted`. At 375px the line wraps (the link may drop under the question), and the details sit below with no horizontal scroll.
- `DESIGN.md` edits:
  - Layout "App shell" footer order.
  - A new Components entry "Donation link and block".
  - Icons list (coffee).
  - Core Screens 3 (block last), 5 (no block, sidebar only) and 8 (conditional donation copy).
  - Don'ts: no Buy Me a Coffee widget, button image or brand colours.

## Durable Documentation Impact

- `CONSTRAINTS.md`:
  - Public API: add `GET /api/v1/donation` to the read-only surface.
  - Client-side Matching (or a new "Donations" section): the donation link MUST be a plain `<a target="_blank" rel="noopener noreferrer">` whose href is exactly `DONATION_URL`. It must carry no query, fragment, Dataset Version or Answers, and nothing from Buy Me a Coffee may load. The donation components MUST receive only the URL, never Questionnaire state. The URL rule MUST live only in `config.py` and `donation.ts`, kept equal by the shared vectors. `DONATION_URL` MUST NOT hold a real profile in git; tests use `perfil_de_prueba`. An invalid value hides the link and never stops startup.
  - Public Copy (the Legal rule): add "the donation channel (`DONATION_URL` rule, the donation link or its copy)" to the triggers for updating `LegalPage.tsx` and its test.
- `ARCHITECTURE.md`: the route in the Public API table, `getDonationUrl` in the client, the App-level hook and context in Web Client, `DONATION_URL` in Runtime Surface.
- `README.md`: a variables-table row and a Despliegue bullet covering the format, that a restart applies it, that invalid means hidden plus a log line, and to check the sidebar after deploy. This is required by the verification list.
- `docs/technical-discovery.md`: the configuration and run-time table rows; runbook step 3 (set it, not a secret), step 6 (check the link or its absence) and a note that the receiving holder refunds any donation identified as made on behalf of a political party (the copy promises it).
- `docs/risks-and-open-questions.md`:
  - line 15: settle the placement, the setting, the copy and the decision that `/metodologia` does not repeat the rule. Record the user decisions of 2026-11-18 (both host forms, holder not named, no block on Shared Results, refund promise). Keep open: the profile (user) and how party donations are detected (donors are not verified; manual review by the receiving holder, who refunds through Buy Me a Coffee).
  - line 85: add the donation copy to the provisional public copy for the lawyer review, which should also cover only two donation points: the donor data that the receiving holder sees on Buy Me a Coffee (a US company) and the "no economic activity" reading.
- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`: no change. No new domain term; this is a site setting.

## Implementation Plan

1. `DESIGN.md`.
2. Server and its tests.
3. Core and its tests.
4. Web: icon, hook, context, link, block, sidebar and end-screen slots, `/legal` copy and CSS.
5. The test helper and the churn in existing tests.
6. Docs, then `CI=true ./init.sh`, then the browser walk, then evidence.

## Implementation Tasks

- [ ] `tests/test_donation.py`:
  - every shared vector through `parse_donation_url` (accepted values are returned trimmed; refused values give `None`, and `caplog` shows one warning that contains `DONATION_URL` but not the value);
  - unset and blank give `None` with no warning;
  - the route returns the configured JSON and `{"url": null}`, with `public, max-age=60`, an ETag and a 304;
  - a query string is ignored, and `POST` gets 405;
  - with an invalid value the app starts and `/health` returns 200.
- [ ] `test_public_api.py`: route set and OpenAPI. `conftest.py`: unset the variable. `test_legal_notice.py`: add `/api/v1/donation` to the no-`Set-Cookie` list.
- [ ] Core: the vectors through `isDonationUrl`; `getDonationUrl` URL and init; `null` and configured mapping; `ContractError` for a missing `url`, a number or a refused string; network, http and invalid_response errors.
- [ ] `DonationBlock.test.tsx`, through `App` with a URL-routed fetch:
  - Scenario 2: copy, attributes, accessible name, disclosure closed then opened by click and by keyboard (Enter/Space on the summary, or the `toggle` event in jsdom), `href` unchanged with Answers present, URL, `history.length` and Answers unchanged, no storage;
  - Scenario 4: `null`, 500, a contract break and an unanswered request all render nothing;
  - the rendered DOM has no `img`, `iframe` or `script` pointing at another origin.
- [ ] `AppShell.test.tsx`: Scenario 1 order and attributes on each shell route; no link when `null`; a drawer click does not close the drawer. `SharedResultsPage.test.tsx`: Scenario 3. `LegalPage.test.tsx`: Scenario 5, both states.
- [ ] `donate-sources.test.tsx`: in the `import.meta.glob` scan (same glob as `browser-storage`), `buymeacoffee` appears only in `packages/core/src/domain/donation.ts`, and no Voter source sets `utm_` or builds a donation href by concatenation.
- [ ] Add `apiPaths(fetch)` and switch the pinned assertions to it. Add one test: an `App` mount sends exactly one `GET /api/v1/donation` with no query and no body.
- [ ] Docs per the section above. Run `git grep -n buymeacoffee` and confirm that only the pattern, `perfil_de_prueba` and the docs' format text appear.

## Verification Plan

- `CI=true ./init.sh` exits 0, and the pytest and Vitest counts grow. Alembic heads are unchanged. No `package*.json` change.
- No E2E harness exists. Vitest through `App` and pytest `TestClient` cover the flows; the browser walk covers the rest.
- **Browser** (Chromium via the desktop Browser pane or chrome-devtools):
  - Build, then serve with a temporary `.claude/launch.json` entry on a free port with `WEB_DIST_DIR`, `DATABASE_URL=sqlite:///data/ideology.db` (read-only use) and a scratch `FEEDBACK_DATABASE_URL`.
  - Run three servers in turn: (a) `DONATION_URL=https://www.buymeacoffee.com/perfil_de_prueba`, (b) unset, (c) `https://buymeacoffee.com/perfil_de_prueba/` (invalid, trailing slash: check for the single log line and that nothing is shown).
  - At 375×812 and ~700×900 (drawer) and 1280×800, in dark and light:
    - the sidebar or drawer on `/`, `/metodologia`, `/legal` and a Shared Results page: order, 44px targets and focus ring, a new tab on activation, the drawer staying open;
    - the end of the results after answering about 26 Statements with one marked Important: the block is last; open and close the disclosure by keyboard (Tab to the summary, Enter, Space) and by pointer; the link does not move; it wraps at 375 with no horizontal scroll; after activating the link and returning, `Revisar mis respuestas` still shows the Answers and the URL is unchanged;
    - the Shared Results body has no block;
    - `/legal` shows the two donation texts only on (a).
  - Console clean. Network for the app tab: one `GET /api/v1/donation` per load, every request same-origin, no request to `buymeacoffee.com` from the app tab, no request carrying Answers. Do not log in or donate on the fictitious profile; the new tab's own traffic is out of scope.
  - Remove the launch entry and the scratch files.
- After merge (user): set the real `DONATION_URL` in Coolify, restart, and check the sidebar, the end of the results and `/legal` on `https://ideologiapp.es`.

## Evidence To Capture

- `init.sh` results, test counts and new test names.
- Browser and version, widths and themes, results per scenario and server mode, the warning log line (without the value), console state, and the request list.
- Record these in `feature_list.json` (`donate-buymeacoffee.evidence`) and `PROGRESS.md` only.

## Validator Checklist

- [ ] `DESIGN.md` was updated first. Placement and copy match this spec exactly. There is no block on the Shared Results body and no Buy Me a Coffee asset or colour.
- [ ] `DONATION_URL` is the only source of the URL. The shared vectors pass on both sides. Invalid means hidden plus one warning without the value, and startup is not blocked. No real profile is in git.
- [ ] The route is GET-only, parameterless, additive, in the OpenAPI and in `CONSTRAINTS.md`. Components never call `fetch`. The donation components get only the URL.
- [ ] The href is exact, with `target="_blank" rel="noopener noreferrer"`. The Answers survive. No request carries Answers. The disclosure is native or ARIA-correct, closed by default and keyboard operable.
- [ ] `/legal` donation copy appears only when configured, and `LegalPage` and its test changed together.
- [ ] The browser walk was done at 375, ~700 and 1280, light and dark, in the configured, unset and invalid modes.
- [ ] README, runbook, ARCHITECTURE, CONSTRAINTS, the risks doc, `feature_list.json` and `PROGRESS.md` are updated.

## User Decisions

Answered by the user on 2026-11-18:

1. **Both host forms.** `DONATION_URL` accepts `https://www.buymeacoffee.com/<perfil>` and `https://buymeacoffee.com/<perfil>`, with the same profile rules. The link uses exactly the configured URL. The `feature_list.json` verification line was updated to match.
2. **Holder not named.** `/legal` says the donations are received by "uno de los titulares en su cuenta de Buy Me a Coffee".
3. **No end block on the Shared Results page** (Decision 8 confirmed). The sidebar and drawer link still appear there.
4. **Refunds.** The no-party rule promises a refund. The disclosure and the `/legal` `Condiciones de uso` paragraph both end with the same sentence: `Si detectamos una donación hecha en nombre de un partido político, la devolveremos.` Tests assert it in both places.

Left for the lawyer review, recorded in `docs/risks-and-open-questions.md` "Electoral and legal exposure":
- the donor data the receiving holder sees on Buy Me a Coffee (a US company);
- the reading that, with donations only, there is no economic activity.
