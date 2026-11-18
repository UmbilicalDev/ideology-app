# Feature Implementation Spec: Legal notice, privacy policy and cookie statement page

## Source Feature

- `id`: legal-privacy-page
- `area`: web (plus one additive public API route and server configuration)
- `depends_on`: deploy-container (`accepted`), methodology-page (`accepted`)
- `status`: not_started (at planning time, 2026-11-18)
- `source`: `feature_list.json`. Its seven verification entries are binding. Its notes record the legal assessment of 2026-11-18. The site is live at `https://ideologiapp.es` on a Netcup VPS (Germany) behind Coolify/Traefik.

## Goal

Add a public page, `Aviso legal y privacidad` at `/legal`, linked from the shell footer and the sidebar of every app-shell page. It has four sections in Spanish:

1. Titulares y contacto: the legal notice under LSSI art. 10 and the controller identity under GDPR art. 13.1.a.
2. Condiciones de uso.
3. Política de privacidad: GDPR art. 13, with joint controllers under art. 26.
4. Cookies y almacenamiento: the LSSI art. 22.2 cookie statement.

The holder names, the contact email and the optional NIF and postal address are server configuration, never git. The server exposes them through one additive `GET /api/v1/legal-notice`. Everything else on the page is static copy. The `/metodologia` privacy section links to the page and stays consistent with it.

## Decisions

- **Route `/legal`**: `export const LEGAL_PATH = "/legal";` in `features/paths.ts`, rendered by `features/legal/LegalPage.tsx` inside `AppShell`. The path is one ASCII segment with no `.`. The tab title is `Aviso legal y privacidad · IdeologiApp`, and the crumb section is `Aviso legal`. The page sets and restores `document.title` and focuses the `h1 tabIndex={-1}` on mount, the same as `MethodologyPage`.
- **Configuration path: an additive public GET route.** There are three options. An index.html injection would break the static `no-cache`/SPA serving and add a template step. A build-time variable would put the data into the image and need a rebuild to change. The chosen option is `GET /api/v1/legal-notice` in `api/routes.py` (`router`), with operationId `getLegalNotice`, response model `LegalNoticeOut` and `cached_json(..., POINTER_CACHE_CONTROL)` (`public, max-age=60`, with an ETag). It takes no parameters, opens no Session and reads only `request.app.state.legal_notice`. Why this option:
  - It follows "components never call fetch": the client gets the data through `createPublicApiClient`.
  - It keeps `/api/` GET-only and read-only (`CONSTRAINTS.md` Public API).
  - It is additive to `/api/v1`.
  - A change takes effect on restart, with no rebuild.
- **Environment variables** (read by `config.legal_notice_settings()` and parsed once in `create_app`). `create_app(..., legal_notice: LegalNoticeSettings | None = None)` lets tests inject the settings. A malformed value raises `ConfigError` at startup, the same as a malformed `ADMIN_USERS`. Unset or blank means "not configured". Values are trimmed. Values with control characters, `<` or `>` are refused.

  | Variable | Format | Rule |
  |---|---|---|
  | `LEGAL_HOLDERS` | `Nombre Apellidos;Nombre Apellidos` | 1..10 names separated by `;`, each 1..120 code points |
  | `LEGAL_CONTACT_EMAIL` | `alias@dominio` | ≤ 254 chars, `^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$`. Domains `example.com/.net/.org` are refused (placeholder guard) |
  | `LEGAL_NIF` (optional) | `NIF;NIF` | Needs `LEGAL_HOLDERS`. Same count as holders, in the same order. Each value is a DNI `^\d{8}[A-Z]$` or NIE `^[XYZ]\d{7}[A-Z]$` with a valid mod-23 control letter, upper-cased before the check |
  | `LEGAL_ADDRESS` (optional) | one line | 1..300 code points |

  `LegalNoticeSettings` is a frozen dataclass with `holders: tuple[LegalHolder, ...]` (where `LegalHolder` is `name`, `nif: str | None`), `contact_email: str | None` and `address: str | None`. The values are never logged.
- **JSON** (snake_case, field order fixed): `{"holders": [{"name": str, "nif": str|null}], "contact_email": str|null, "address": str|null}`. When nothing is configured the body is `{"holders": [], "contact_email": null, "address": null}`.
- **Core client.** Add `domain/legal-notice.ts` with `LegalNotice { holders: readonly LegalHolder[]; contactEmail: string | null; address: string | null }` and `LegalHolder { name; nif: string | null }`. Add `PublicApi.getLegalNotice()`, which sends exactly `GET /api/v1/legal-notice` with an `Accept` header, no query and no body. `parseLegalNotice` checks the contract: `holders` is an array; each `name` is a non-empty string; each `nif` is null or a non-empty string; `contact_email` is null or a string that contains `@` and no whitespace; `address` is null or a non-empty string. Unknown keys are ignored. Export the new names from `index.ts`.
- **Missing configuration renders the page.** The four sections are always rendered. Only the dynamic lines of section 1 change:
  - When `holders` is empty, the page shows `Los nombres de los titulares están pendientes de publicación.`
  - When `contactEmail` is null, it shows `La dirección de contacto está pendiente de publicación.`
  - No placeholder text exists in the bundle or the server: no `TODO`, no `example`, no fake name.
  - While loading, the page shows `<p role="status">Cargando los datos de los titulares…</p>`.
  - On any `PublicApiError` it shows `<p role="alert">No se han podido cargar los datos de los titulares y de contacto.</p>` and a solid `Reintentar` button. The page uses a `useLegalNotice(api)` hook with the same shape as `useElections`: stale results are ignored and nothing is logged.
- **Retention: 12 months.** This is the main session's default; the final value is open (see User Decisions). It is one constant, `export const FEEDBACK_RETENTION_MONTHS = 12;`, in `packages/core/src/domain/feedback.ts`, exported from `index.ts`. The copy interpolates it, and the test asserts the sentence built from it. Changing it is a one-line change plus the test update required by the new Public Copy rule. Deletion stays manual: Operators delete in `/admin`, and the runbook gets a monthly step. An automatic purge is out of scope. A risks entry records it, and if a purge is built it must reuse this number. The policy copy depends on no request, so the value is not served by the API.
- **A narrow supporting fix makes the IP statement true.** `FeedbackRateLimiter` today deletes an expired HMAC key only when the 10,000-key map is full, so a key can stay in memory until a restart. Change: at the start of `check_and_consume`, call `_prune_keys(now)` when at least 60 s have passed since the last sweep (`self._last_sweep`). After that, an expired key is gone at the first limiter call after its 10-minute window. The copy says "se descarta a partir de los 10 minutos". The same class is used for the sign-in limiter, which also benefits. Nothing else changes in the limiter.
- **No cookie banner.** The only cookie is `ideology_admin`. It is set only for Operators and only on `/admin/api`, with `HttpOnly`, `SameSite=Strict`, `Secure` and browser-session lifetime. That makes it a technical cookie, exempt under LSSI art. 22.2 and the AEPD cookie guide. Public pages set no cookie and use no Web Storage or IndexedDB.
- **Provisional copy.** `LegalPage.tsx` starts with `// Provisional copy: pending review by a lawyer (docs/risks-and-open-questions.md, "Electoral and legal exposure").`. The visible text does not say "provisional".
- **Neutrality and isolation.** The page names no party, shows no logo and no image, and does not contain the string `/admin`. `admin-isolation.test.tsx` fails on any Voter source that does, so the copy says `página de administración`.

## Non-Goals

- No cookie or consent banner, no analytics, no new cookie or storage.
- No automatic feedback purge, no change to the feedback store schema, no new migration, and no change to the admin page or its copy.
- No legal review. A lawyer's review is a human task, recorded in the risks doc.
- No English version. No link from the Questionnaire focus shell or the results end screen: they have no footer or sidebar by design (`DESIGN.md` "Focus shell").
- No donation, Buy Me a Coffee or logo-licence wording. Those stay open in the risks doc.
- No data-processing agreement, joint-controller agreement or Traefik setting in code. They are user actions listed below.

## Job Story

When I use a voting advice tool built with AI by people I don't know,
I want to see who is behind it, on what terms I use it, what data it keeps and what it stores in my browser,
so I can trust it and exercise my rights.

## Users And Permissions

- Voter: anonymous and read-only. Opening the page sends one same-origin `GET /api/v1/legal-notice`, which carries no Answers.
- Operator: sets the `LEGAL_*` variables in Coolify. There is no in-app editing.

## Acceptance Scenarios

Exact copy. Tests assert the headings, the dynamic lines and the sentences marked (T). `%` is not used. `<main className="doc-page">` with `doc-page__header` contains:

- `<h1 tabIndex={-1}>Aviso legal y privacidad</h1>`.
- The lead: `Quién es responsable de IdeologiApp, en qué condiciones puedes usarla, qué datos tratamos y qué se guarda en tu navegador.`
- `<p className="doc-page__updated">Última actualización: {LEGAL_LAST_UPDATED}</p>`. `LEGAL_LAST_UPDATED` is a module constant holding the merge date, for example `18 de noviembre de 2026`.

The layout is `doc-page__layout` with `PageToc` (labels `Titulares y contacto`, `Condiciones de uso`, `Privacidad`, `Cookies`). The body has four `<section aria-labelledby="legal-<key>-title">` elements:

1. `holders`, **Titulares y contacto**:
   - With holders: `IdeologiApp es un proyecto de personas físicas, no de una empresa ni de una asociación. Sus titulares, que lo gestionan conjuntamente y son corresponsables del tratamiento de los datos descrito en esta página, son:` (T), then a `<ul className="plain-list">` with one `<li>` per holder: `{name}` or `{name}, NIF {nif}`.
   - Without holders: the pending sentence instead (T).
   - `Dirección postal: {address}` appears only when an address is configured.
   - With an email: `Contacto: <a className="text-link" href="mailto:{email}">{email}</a>. Escríbenos para cualquier consulta sobre esta página o para ejercer tus derechos.` (T).
   - Without an email: the pending sentence instead (T).
2. `terms`, **Condiciones de uso**:
   - `Puedes usar IdeologiApp gratis y sin registrarte. Al usarla aceptas estas condiciones, que se rigen por la ley española.`
   - `IdeologiApp no es una recomendación de voto. Las afirmaciones del cuestionario y las posiciones de los partidos las genera automáticamente una inteligencia artificial a partir de los programas electorales, sin revisión humana, y pueden contener errores. La afinidad solo refleja lo que dicen los programas, no lo que los partidos han hecho o votado. Cómo se generan y se comprueban se explica en <Link METHODOLOGY_PATH>Metodología</Link> y en <Link TRANSPARENCY_PATH>Transparencia IA</Link>.` (T)
   - `Cada posición se respalda con una cita literal del programa electoral del partido, con su página, reproducida con fines de análisis y comentario al amparo del derecho de cita (artículo 32 de la Ley de Propiedad Intelectual). Los programas pertenecen a sus autores. Los logotipos de los partidos se muestran solo para identificarlos: pertenecen a sus titulares y su uso no implica relación con ellos ni su apoyo.` (T)
   - `Ofrecemos la herramienta tal cual, sin garantía de que su contenido sea exacto, completo o actual. En la medida en que la ley lo permite, no respondemos de las decisiones que tomes a partir de ella ni de los daños derivados de su uso. Los enlaces a programas electorales y a otros sitios llevan a páginas de terceros, de cuyo contenido no somos responsables.`
3. `privacy`, **Política de privacidad**, with `<h3>` subsections:
   - **Responsables**: `Los responsables del tratamiento son los titulares indicados en «Titulares y contacto», como corresponsables. Han acordado que cualquiera de ellos atiende las solicitudes que se envíen a la dirección de contacto.`
   - **Tus respuestas no salen de tu dispositivo**: `Tus respuestas al cuestionario, las afirmaciones que marcas como importantes y tu resultado no se envían a ningún servidor ni se guardan: la afinidad se calcula en tu navegador, así que no tratamos tus opiniones políticas. Si compartes tu resultado, el enlace lleva tus respuestas tras el símbolo «#», una parte de la dirección que los navegadores no envían al servidor; quien tenga el enlace puede verlas.` (T)
   - **Qué datos tratamos**: a `plain-list` with two items:
     - `Las opiniones que nos envías con «Danos tu opinión», que es voluntario: guardamos solo el texto, desde dónde la envías (el menú general o la pantalla de resultados), la fecha y, cuando la revisamos, la fecha de revisión. No escribas en el mensaje datos personales ni opiniones políticas, tuyas o de otras personas.` (T)
     - `Tu dirección IP, que, como en cualquier web, recibe el servidor para enviarte la página. No guardamos registros de acceso. Al enviar una opinión, el servidor convierte tu dirección IP en un código del que no se puede recuperar para limitar los envíos masivos; ese código se guarda solo en la memoria del servidor, nunca en disco, y se descarta a partir de los 10 minutos.` (T)
   - **Para qué y con qué base legal**: `Usamos las opiniones para mejorar la herramienta, el código de tu dirección IP para protegerla de envíos masivos y tu dirección IP para servir la web. La base legal es nuestro interés legítimo en mantener un servicio útil y seguro (artículo 6.1.f del Reglamento General de Protección de Datos). No usamos los datos para nada más, no hacemos perfiles ni tomamos decisiones automatizadas sobre ti.`
   - **Cuánto tiempo los guardamos**: `Guardamos cada opinión un máximo de {FEEDBACK_RETENTION_MONTHS} meses desde que la recibimos, y después la borramos, también de las copias de seguridad. Podemos borrarla antes.` (T, built from the constant)
   - **Quién más accede a los datos**: `Solo los titulares, a través de una página de administración protegida con contraseña. La web se aloja en un servidor de Netcup GmbH en Alemania, que actúa como encargado del tratamiento. Los datos no salen de la Unión Europea y no los cedemos a nadie, salvo obligación legal. Si compartes IdeologiApp con los botones de otras redes o aplicaciones, se abre el servicio que elijas, que trata tus datos según su propia política; solo se comparte la dirección de IdeologiApp.` (T)
   - **Tus derechos**: `Puedes pedirnos el acceso a tus datos, su rectificación o supresión, la limitación de su tratamiento o su portabilidad, y oponerte a su tratamiento, escribiendo a la dirección de contacto. Como no guardamos nada que te identifique, para localizar una opinión indícanos su texto y la fecha aproximada de envío. También puedes reclamar ante la Agencia Española de Protección de Datos en <a className="text-link" href="https://www.aepd.es/">www.aepd.es</a>.` (T)
4. `cookies`, **Cookies y almacenamiento**:
   - `Las páginas públicas de IdeologiApp no instalan cookies ni usan el almacenamiento de tu navegador (almacenamiento local, de sesión o IndexedDB), y no cargan nada de otros sitios: ni analítica, ni publicidad, ni fuentes, ni redes sociales. Tu navegador solo guarda en su caché los archivos de la web, como en cualquier sitio, para cargarla más rápido.` (T)
   - `La única cookie es la de sesión de la página de administración, que solo reciben los titulares al iniciar sesión. Es técnica e imprescindible para ese acceso, no se envía en las páginas públicas y caduca al cerrar la sesión o el navegador, por lo que no requiere consentimiento.` (T)
   - `Si algún día añadimos estadísticas u otras cookies que no sean técnicas, te pediremos antes tu consentimiento y lo indicaremos aquí.` (T)
   - `HomeButton` follows the four sections.

The shell link text is `Aviso legal y privacidad` in both places:

- In the sidebar it is a `Link` in `sidebar__footer` below `Danos tu opinión`, with `onClick={() => closeFor(LEGAL_PATH)}`.
- In the footer it is a second `<p>` in `.app-footer` holding a `Link`.

Both are at least 44px tall. In `/metodologia` → `Tus respuestas`, append `<p>Quién es responsable, cuánto tiempo se guardan las opiniones y cómo ejercer tus derechos se explica en <Link className="text-link" to={LEGAL_PATH}>Aviso legal y privacidad</Link>.</p>`. The rest of that section is unchanged: it already states what the legal page states, and nothing on the legal page contradicts it.

### Scenario 1: configured
Given `LEGAL_HOLDERS`, `LEGAL_CONTACT_EMAIL`, `LEGAL_NIF` and `LEGAL_ADDRESS` are set
When the Voter opens `Aviso legal y privacidad` from the footer
Then `/legal` shows the h1 (focused), the four h2 sections in order, each holder with its NIF, the address and a `mailto:` link, and exactly one API request, `GET /api/v1/legal-notice`.

### Scenario 2: optional fields unset
Given only `LEGAL_HOLDERS` and `LEGAL_CONTACT_EMAIL` are set
Then the holders show without `NIF` and no `Dirección postal` line appears.

### Scenario 3: nothing configured
Given no `LEGAL_*` variable is set
Then the page renders all four sections plus the two pending sentences. No `mailto:` link, empty list, `null`, `undefined` or placeholder appears.

### Scenario 4: API failure
Given `/api/v1/legal-notice` fails (network error, 500 or a broken contract)
Then the alert and `Reintentar` show, the static sections still render, and `Reintentar` requests again.

### Scenario 5: navigation
Given any app-shell page (`/`, `/metodologia`, `/transparencia`, `/resultados#…`, not found)
When the Voter uses the sidebar link (the drawer at 375px) or the footer link, then Back
Then `/legal` opens with the crumb `Aviso legal`, the drawer is closed, Back returns to the previous page with its title, and the methodology link opens `/legal`. Deep link and reload work. `/legal/x` is not found.

### Scenario 6: bad configuration
Given a malformed `LEGAL_CONTACT_EMAIL`, a NIF with a wrong control letter, `LEGAL_NIF` without `LEGAL_HOLDERS`, or a NIF count that differs from the holder count
Then `create_app` startup raises `ConfigError`, and the message names the variable but not its value.

## Repository Research

### Files Inspected
- `AGENTS.md`, `CONTEXT.md`, `DESIGN.md` (App shell, Components, Core Screens), `CONSTRAINTS.md` (Public API, Client-side Matching, Web Client Serving/Styling, Public Copy, Voter Feedback, Operator Access), `ARCHITECTURE.md` (Public API, Public API Client, Web Client, Runtime Surface), `docs/risks-and-open-questions.md`, `docs/technical-discovery.md` (Deployment and Operations), `README.md` (Despliegue), `PROGRESS.md`, `docs/specs/{methodology-page,deploy-container}.md`, `.claude/launch.json`.
- `src/ideology_app/{main.py,config.py,web.py}`, `api/{__init__,routes,http_cache}.py`, `api/admin_routes.py` (`COOKIE_NAME`, `COOKIE_PATH`, `_cookie`), `admin/sessions.py`, `feedback/rate_limit.py` (key pruning only when full), `tests/{conftest.py,test_public_api.py}` (route set and OpenAPI tests at lines 663–760), `tests/test_admin_api.py` (cookie asserts).
- `packages/core/src/{index.ts,application/public-api.ts,application/feedback-api.ts,infrastructure/http/public-api-client.ts,domain/feedback.ts}`.
- `apps/web/src/{main.tsx,app/App.tsx,features/paths.ts,features/shell/AppShell.tsx,features/methodology/MethodologyPage.tsx,features/transparency/TransparencyPage.tsx,features/common/HomeButton.tsx,admin/admin-isolation.test.tsx,ui/icons.tsx}`. No `localStorage`, `sessionStorage`, `document.cookie` or `indexedDB` occurs in Voter sources or core.

### Existing Patterns To Follow
- Doc pages: the `doc-page` layout, `PageToc`, a `useEffect` for title and focus, and `HomeButton`.
- Data pages: an `api` prop and a hook with loading, loaded, error and retry states (`useElections`).
- Core: `getParsed(path, parse)` with a `ContractError`.
- Server: `cached_json`. Settings go through `config._env` and are parsed in `create_app` with a `ConfigError`. `tests/conftest.py` unsets environment variables. Tests render `<MemoryRouter><App api={createPublicApiClient({ fetch })} /></MemoryRouter>` with a mocked `FetchLike`.

### Current Gaps
- There is no legal page or legal configuration. The `/api/v1` route set is pinned by `test_api_routes_are_get_only_without_query_or_body`. Mock fetches in App, AppShell and other tests do not answer `/api/v1/legal-notice`, which matters only when `/legal` is rendered. No E2E harness exists.

## Expected File Changes
- Python: `config.py` (settings and parser), `api/schemas.py` (`LegalHolderOut`, `LegalNoticeOut`), `api/routes.py` (the route), `main.py` (the `legal_notice` param, `app.state.legal_notice`), `feedback/rate_limit.py` (the sweep). Tests: create `tests/test_legal_notice.py`; modify `tests/conftest.py` (unset `LEGAL_*`), `tests/test_public_api.py` (route set and OpenAPI) and `tests/test_feedback_rate_limit.py` (the sweep).
- Core: create `domain/legal-notice.ts`; modify `application/public-api.ts`, `infrastructure/http/public-api-client.ts`, `domain/feedback.ts` and `index.ts`, plus `test/infrastructure/public-api-client.test.ts`.
- Web:
  - create `features/legal/{LegalPage.tsx,LegalPage.test.tsx,useLegalNotice.ts}` and `features/legal/browser-storage.test.tsx` (the source scan);
  - modify `features/paths.ts`, `app/App.tsx`, `app/App.test.tsx`, `features/shell/AppShell.tsx`, `AppShell.test.tsx`, `features/methodology/MethodologyPage.tsx`, `MethodologyPage.test.tsx` and `ui/components.css` (sidebar and footer link, `doc-page__updated`, `h3` in doc pages if missing);
  - update any test mock that `/legal` now reaches.
- Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `DESIGN.md`, `README.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `feature_list.json`, `PROGRESS.md`.

## Visual Design Impact
- UI is involved. The design source is `DESIGN.md`. No new token or icon, and no new design artifact.
- The page reuses the Methodology doc layout: index above the text, sticky from 1024px, 72ch measure. `h3` uses `title`. The updated line is `body-sm` in `text-muted`.
- The sidebar link is `body-sm` `text-muted` with an accent hover, 44px tall, under the feedback button. The footer link is a `text-link` on its own line. Both meet AA; `text-muted` on `bg-sidebar`/`bg` is listed at 7.0 or more.
- Check both themes at 375px (drawer) and 1280px: no horizontal scroll, and a visible focus ring.
- `DESIGN.md` changes: App shell (sidebar footer link, footer link), Core Screens 8 `Aviso legal y privacidad (/legal, app shell)`.

## Durable Documentation Impact
- `CONSTRAINTS.md`:
  - Public Copy: `apps/web/src/features/legal/LegalPage.tsx` and its test MUST be updated in the same change whenever any of these change:
    - the feedback store fields or the abuse-guard key;
    - cookies or browser storage;
    - the hosting provider, any processor or recipient, or any request to another origin;
    - `FEEDBACK_RETENTION_MONTHS`;
    - the holders' data model.

    The copy MUST NOT contradict `MethodologyPage.tsx` "Tus respuestas". Reason: the page is the GDPR art. 13 information, and stale copy is a legal risk.
  - Voter Feedback: the abuse guard MUST drop expired keys within one window plus its sweep interval (no key kept until the map is full). Reason: the privacy copy promises it.
  - Operator Access, or a new Legal section:
    - Public pages MUST NOT set cookies or use Web Storage, IndexedDB or the Cookie Store API. A non-technical cookie needs a consent feature first. Reason: LSSI art. 22.2; the cookie statement says so.
    - `LEGAL_*` values (names, NIF, address, email) MUST NOT be in git or code. Tests use fictitious values such as `Persona Uno` and `contacto@ideologiapp.test`. Reason: personal data.
- Public API: add `GET /api/v1/legal-notice` to the GET-only list (not a write).
- `ARCHITECTURE.md`: add `/api/v1/legal-notice` to the Public API table, `getLegalNotice` to the client, `/legal` to the routes, and the `LEGAL_*` variables to Runtime Surface.
- `README.md` "Despliegue" and `docs/technical-discovery.md`: add the four variables (format, optional or not, never in git, what happens when they are malformed) to the run-time table. Add runbook steps:
  - set `LEGAL_*` as secrets;
  - after a deploy, check `/legal`;
  - each month, delete messages older than `FEEDBACK_RETENTION_MONTHS` in `/admin` (`Hasta` filter) and off-server backups older than that;
  - confirm Traefik's access log is off;
  - sign Netcup's data-processing agreement (AVV) in its customer panel.
- `docs/risks-and-open-questions.md`:
  - Voter feedback moderation: retention settled at 12 months by default (user may change it), stated on `/legal`. The open item becomes "no automatic purge; manual monthly deletion per runbook; a purge feature must reuse `FEEDBACK_RETENTION_MONTHS`".
  - Electoral and legal exposure: the legal page exists, all public copy is provisional, and the lawyer review is still open with its timing as a user decision.
  - "Query strings in server access logs": the Traefik log check is now a runbook step and the privacy copy depends on it.
  - Brand marks, logo licence and the landing recordings stay open and are deferred; the page does not address them.
  - The Research Task "legal check" stays open, pointing at the same review.
- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`: no change needed (no new domain term; Operator and Voter are unchanged).

## Implementation Plan
1. Server: settings and parser, schema, route, `create_app`, limiter sweep, and tests.
2. Core: the type, port, client method, constant and tests.
3. Web: path, route, `LegalPage`, the hook, the shell links, the methodology link, CSS and tests.
4. Docs, then `CI=true ./init.sh`, then the browser walk, then evidence.

## Implementation Tasks
- [ ] `tests/test_legal_notice.py`:
  - parser cases: valid inputs; unset or blank; each refusal in Scenario 6, including `example.com`, `<`, a control character, 11 holders and a 121-code-point name; the `ConfigError` text excludes the value;
  - the route serves the configured JSON and the empty JSON, with `Cache-Control: public, max-age=60`, an ETag and a 304 on `If-None-Match`;
  - none of `GET /`, `/legal`, `/metodologia`, `/api/v1/elections`, `/api/v1/legal-notice`, `/health` or `POST /api/v1/feedback` sends `Set-Cookie`.
- [ ] `test_public_api.py`: add the path to the route set and `getLegalNotice`/`LegalNoticeOut` to the OpenAPI expectations. Keep the existing 404 schema assert only for the routes that have one; the new route has no 404.
- [ ] `test_feedback_rate_limit.py`: with a fake clock, a key whose window expired is removed by another client's call after 60 s or more, and is not removed earlier than its window.
- [ ] Core client tests: exact URL and init; field mapping; each contract error names its field; `network`, `http` and `invalid_response` errors.
- [ ] `LegalPage.test.tsx`, rendered through `App` at `/legal`:
  - Scenarios 1–4 (the fetch is called once with `/api/v1/legal-notice`; Reintentar refetches);
  - h1 focus and title restore;
  - four h2 in order and named regions;
  - the (T) sentences;
  - the retention sentence equals the one built from `FEEDBACK_RETENTION_MONTHS`;
  - no `img`;
  - the body text contains no `undefined`, `null`, `TODO` or `example`.
- [ ] `browser-storage.test.tsx`: the `import.meta.glob` scan over Voter and core sources (the same glob as admin-isolation; tests and `src/admin/` excluded) finds no `localStorage`, `sessionStorage`, `document.cookie`, `indexedDB` or `cookieStore`. `index.html` has no `http://` or `https://` URL.
- [ ] `AppShell.test.tsx`/`App.test.tsx`:
  - the sidebar and footer links point to `/legal` on `/`, `/metodologia`, `/transparencia` and not found;
  - the crumb reads `Aviso legal`;
  - in the drawer, the link closes it;
  - `/legal/x` is added to the not-found `test.each`;
  - the Questionnaire still has no sidebar.
- [ ] `MethodologyPage.test.tsx`: the new paragraph and its link to `/legal`. The other links' asserts are updated.
- [ ] Docs per the section above. Run `git grep -nE "[0-9]{8}[A-Z]|@gmail|@hotmail"` and confirm no personal value is committed.

## Verification Plan
- `CI=true ./init.sh` exits 0, and the pytest and Vitest counts grow. `alembic` heads are unchanged. No `package*.json` change.
- No E2E harness exists. Vitest through `App` with `MemoryRouter` and pytest `TestClient` cover the flows. The browser walk covers the rest.
- **Browser** (Google Chrome via chrome-devtools, or the desktop preview):
  - Build, then serve with a temporary `.claude/launch.json` entry (port 8021 or another free one): `WEB_DIST_DIR=<repo>/apps/web/dist`, `DATABASE_URL=sqlite:///data/ideology.db` (read-only use) and `FEEDBACK_DATABASE_URL=sqlite:///$SCRATCH/feedback.db`. Set `LEGAL_HOLDERS=Persona Uno;Persona Dos`, `LEGAL_CONTACT_EMAIL=contacto@ideologiapp.test`, a valid fictitious `LEGAL_NIF=00000000T;00000001R` and an address.
  - Restart without `LEGAL_*` for Scenario 3.
  - At 375×812 and 1280×800, in dark and in light (`prefers-color-scheme` emulation):
    - open the page from the footer and from the sidebar (the drawer at 375) on `/`, `/metodologia` and `/transparencia`;
    - read every section; use the page index; Back and Forward; reload `/legal`;
    - follow the methodology link; use Tab and the focus ring;
    - check no horizontal scroll and 44px targets.
  - Console clean, and no failed request. Network: same-origin only; on `/legal`, only the document, assets and `GET /api/v1/legal-notice`; no request carries Answers. The Application panel shows no cookie and empty Local and Session Storage for the origin.
  - Remove the launch entry and `$SCRATCH`; `git status` shows only the feature's files.
- After merge and deploy (user): set the variables in Coolify, check `/legal` on `https://ideologiapp.es`, and run the existing post-deploy checks.

## Evidence To Capture
- `init.sh` step results, pytest and Vitest counts, and the new test names.
- Browser name and version; widths and themes; each scenario's result; console state; the request list for `/legal`; the storage and cookie panel.
- Record these in `feature_list.json` (`legal-privacy-page.evidence`) and `PROGRESS.md`, never in `docs/validations/`.

## Validator Checklist
- [ ] `/legal` from `LEGAL_PATH` in the shell. The copy matches this spec and is true of the code: feedback fields, limiter sweep, cookie attributes, no storage, Netcup, retention constant.
- [ ] The configuration comes only from `LEGAL_*`, with fail-fast parsing. Missing values show the pending sentences and leak nothing. No personal value is in git.
- [ ] The `/api/v1` addition is GET-only, parameterless and additive, and the OpenAPI tests are updated. Components never call `fetch`.
- [ ] Footer and sidebar links appear on every app-shell page. The methodology link exists and the methodology copy does not contradict the legal page. `admin-isolation` still passes.
- [ ] The cookie and no-storage tests exist, and the CONSTRAINTS rules are added.
- [ ] The real-browser walk was done at 375 and 1280, light and dark, with a clean console and network.
- [ ] README, runbook, ARCHITECTURE, DESIGN, the risks doc and `feature_list.json` are updated.

## User Decisions

Answered by the user on 2026-11-18:

1. **Settled:** feedback retention is 12 months (`FEEDBACK_RETENTION_MONTHS = 12`).
2. **Settled for now:** NIF and postal address are not published (`LEGAL_NIF` and `LEGAL_ADDRESS` stay unset in production). The user's view: the project has no economic activity. The planned Buy Me a Coffee link (`donate-buymeacoffee`) goes to a holder's personal account and takes voluntary donations, not payments. Keep both variables supported so they can be set later without code. The lawyer review (item 5) should confirm this LSSI reading.
3. **Open:** the contact email. It is probably a forwarding alias on `ideologiapp.es`; the user is checking whether the hosting or domain contract includes forwarding. Until then `LEGAL_CONTACT_EMAIL` stays unset and the page shows the pending sentence.
4. **Settled:** the holders' full names are known and are set only in the production environment (`LEGAL_HOLDERS`). They are never written to git.
5. **Open:** when a lawyer reviews all public copy (this page, `/metodologia`, `/transparencia`, the footer).
6. User actions outside code:
   - a short written joint-controller arrangement between the holders (GDPR art. 26; the page states its essence);
   - accepting Netcup's AVV;
   - confirming that Traefik's access log is off in Coolify.
