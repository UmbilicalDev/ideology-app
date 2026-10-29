# Feature Implementation Spec: Admin page to review, mark and delete Voter feedback

## Source Feature

- `id`: feedback-admin
- `area`: web (plus api, cli and the feedback store)
- `depends_on`: feedback-api (accepted)
- `status`: not_started at planning time (2026-10-29); tracking issue UmbilicalDev/ideology-app#85
- `source`: `feature_list.json`. Its `verification` list is binding.

## Goal

An Operator opens a private page, `/admin`, and signs in with their own username and password. The page lists the stored feedback messages, newest first, with their date (UTC) and origin. The Operator can filter by date and by reviewed state, mark a message as reviewed or undo that, and hard-delete a message after an inline confirmation. Voters are unaffected: no Voter page links to the admin page, no Voter request sets or carries a cookie, and `POST /api/v1/feedback` stays anonymous. The feedback store gets a `reviewed_at` column through its own Alembic environment. Existing `feedback.db` files keep every message.

## Decisions

1. **Accounts are configuration.** `ADMIN_USERS` is a comma-separated list of `username:hash` entries. Whitespace around an entry is trimmed. The real accounts are `miguel` and `enrique`, and they live only in the deployment's environment, never in git.
   - Username: `^[a-z0-9][a-z0-9._-]{0,31}$`. Duplicate usernames are refused.
   - Hash: `scrypt.<log2 n>.<r>.<p>.<salt>.<key>`, where salt (16 random bytes) and key (32 bytes) are base64url without padding. The format has no `$`, `:` or `,`, so the value needs no quoting in a shell, `.env` or docker compose file.
   - `hashlib.scrypt` from the standard library, so no new dependency. Defaults are `n = 2**15`, `r = 8`, `p = 1` and `maxmem = 64 MiB`. The default `maxmem` fails for `n = 2**15`; this was measured on Python 3.13 / OpenSSL in a throwaway run, at about 70 ms per hash.
   - The verifier accepts `log2 n` 14..20, `r` 1..16 and `p` 1..4, and nothing weaker.
   - The password is hashed as the UTF-8 bytes of `unicodedata.normalize("NFC", password)`.
   - The lifespan parses `ADMIN_USERS`. A malformed value fails startup with `ConfigError`, for example `ADMIN_USERS entry 2 is not <username>:<scrypt hash>; create one with "ideology admin hash-password"`. The message never echoes the value.
   - Unset or blank `ADMIN_USERS` means no Operator account. The app starts and every sign-in is refused (Decision 4).
2. **Hash CLI.** `ideology admin hash-password [--username NAME]` does not use `requires_db` and never opens a database.
   - It prompts with `click.prompt(hide_input=True, confirmation_prompt=True)`.
   - It refuses fewer than 12 or more than 1024 code points (`ClickException`, exit 1) and an invalid `--username` (exit 2).
   - It prints the hash, or `NAME:hash` when `--username` is given. Nothing else, and never the password.
3. **Constant-time sign-in check.** `admin.accounts.authenticate(accounts, username, password) -> str | None`:
   - It compares the given username with every account using `hmac.compare_digest` (no early exit).
   - It then runs exactly one scrypt verification: against the matched hash, or against a dummy hash made once per process with the default parameters.
   - It compares the derived keys with `hmac.compare_digest`.
   - Unknown user and wrong password take the same path and give the same `401 invalid_credentials` text: `Usuario o contraseña incorrectos.`
4. **Admin API.** All routes are under `/admin/api/v1`, outside the public `/api/` prefix, so the Public API GET-only rule and its tests stay as they are.
   - `admin_router` is `include_in_schema=False`, so the public OpenAPI never lists it.
   - Every response has `Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow` and `X-Content-Type-Options: nosniff`.
   - Errors use the existing shape `{"error": {"code", "message"}}`.
   - Bodies are JSON, read by hand with the 415/413 helpers of `feedback_routes`. Move `_is_json` and `_read_body(max_bytes)` into `api/request_body.py` and import them back, with no change in behaviour. The cap is 4096 bytes.

   | Route | Needs | Success | Errors |
   | --- | --- | --- | --- |
   | `POST /session` `{"username","password"}` (strict, `extra="forbid"`; username ≤ 64, password ≤ 1024) | origin check | `200 {"username","csrf_token"}` + Set-Cookie | 403 `csrf_failed`, 503 `admin_not_configured`, 415, 413, 422, 429 `rate_limited` + `Retry-After`, 401 `invalid_credentials` (in this order) |
   | `GET /session` | session | `200 {"username","csrf_token"}` (refreshes idle time) | 401 |
   | `DELETE /session` | session + CSRF | `204`, session removed, cookie cleared | 401, 403 |
   | `GET /feedback?from=YYYY-MM-DD&to=YYYY-MM-DD&reviewed=all\|yes\|no&before_id=N&limit=50` | session | `200 {"messages":[{"id","message","origin","created_at","reviewed_at"}],"next_before_id": int\|null}` | 401, 422 (FastAPI shape for bad params; error shape `invalid_filter` when `to < from`) |
   | `POST /feedback/{id}/review` | session + CSRF | `200` the message (idempotent: an existing `reviewed_at` is kept) | 401, 403, 404 `feedback_not_found` |
   | `DELETE /feedback/{id}/review` | session + CSRF | `200` the message with `reviewed_at: null` | 401, 403, 404 |
   | `DELETE /feedback/{id}` | session + CSRF | `204` hard delete | 401, 403, 404 |

   - **Without a valid session**, every route except `POST /session` answers 401 and clears the cookie. The code is `admin_not_configured` when there are no accounts, so the page can explain how to configure one; otherwise it is `not_signed_in`.
   - **Order and paging.** Newest first means `id DESC` (insertion order; `created_at` is set by the server at insert). `limit` is 1..100. The route fetches `limit+1` rows to set `next_before_id`.
   - **Date filters** are inclusive UTC days: `created_at >= from 00:00Z` and `< (to+1) 00:00Z`.
   - **Fields.** Times are ISO 8601 UTC with `Z`. Nothing is returned that is not stored: no IP or user agent.
5. **Session: server-side, in memory.** `admin.sessions.AdminSessionStore(idle_seconds=1800, absolute_seconds=28800, max_sessions=64, clock=time.monotonic)`:
   - The token is `secrets.token_urlsafe(32)`. The store keys sessions by the token's SHA-256 and keeps only that hash, the username, a `csrf_token` (`token_urlsafe(32)`), `created` and `last_seen`.
   - A session expires 30 minutes after the last authenticated request or 8 hours after sign-in, whichever comes first.
   - When the store is full, expired sessions are pruned first, then the oldest is evicted.
   - Sign-in removes the session the request's cookie carried, if any, and always creates a new token, so session fixation is not possible.
   - A restart signs everyone out, and so does an `ADMIN_USERS` change, which needs a restart. A signed cookie was rejected: it needs another secret to manage, and sign-out could not revoke it before expiry.
   - **Accepted constraint:** sessions and the sign-in limiter are per process, so a deployment runs one worker. Otherwise requests answer 401 and the Operator signs in again (fail closed). This is recorded for the deployment feature.
6. **Cookie.** `ideology_admin=<token>; Path=/admin/api; HttpOnly; SameSite=Strict`, with no `Max-Age`, so it is a browser-session cookie.
   - `Secure` is added unless the request `Host` (port ignored) is `localhost`, `127.0.0.1` or `[::1]`. A real host always gets `Secure`, even behind a TLS-terminating proxy.
   - The `Path` keeps the cookie off every Voter request, even in an Operator's own browser. The `__Host-` prefix needs `Path=/`, so it is not used.
   - Sign-out and every 401 send the same cookie with `Max-Age=0`.
7. **CSRF.**
   - **Every state-changing route**, sign-in included, is refused with 403 `csrf_failed` when an `Origin` header is present and its host:port differs from `Host`, or when `Sec-Fetch-Site` is present and is neither `same-origin` nor `none`.
   - **Session routes that change state** also need the `X-CSRF-Token` header, equal (`compare_digest`) to the session's `csrf_token`. The custom header also forces a CORS preflight, which fails because the app has no CORS.
   - **Sign-in** also needs `application/json`, which forces the same preflight.
   - **Together with `SameSite=Strict`**, this is defence in depth.
8. **Sign-in rate limit.** A second `FeedbackRateLimiter` instance on `app.state.admin_sign_in_limiter` allows `per_client=5` and `global_limit=30` per `window_seconds=900`. Every validated attempt counts, successful or not, so concurrent guesses cannot race the counter.
   - The limit is checked before scrypt runs, which also bounds CPU use.
   - Its docstring says it is now reused. The HMAC-keyed host rule stays the same.
   - **Accepted Low:** an attacker can use up the global budget and lock Operators out for 15 minutes. A restart clears it.
9. **No admin configured.** `POST /session` answers 503 `admin_not_configured` with the message `No Operator account is configured. Set ADMIN_USERS (see README, "ideology admin hash-password").` Other routes answer 401 with the same code. The page shows that instruction in a notice card and has no form.
10. **Store schema and upgrade path.** Add a second Alembic environment, `src/ideology_app/feedback/migrations/`, with `env.py`, `script.py.mako` and `versions/`. Its script location is `ideology_app.feedback:migrations`; there is no `__init__.py`, as in the shared env. It also has:
    - Its own `version_table="feedback_alembic_version"` and `render_as_batch=True`.
    - `target_metadata = FEEDBACK_METADATA`.
    - The connection from `config.attributes["connection"]` when it is given, else the URL.

    The revisions are written by hand:
    - `f0001_feedback_messages`: the table exactly as the current `create_all` builds it, including the one CHECK named `feedback_origin`.
    - `f0002_reviewed_at`: `reviewed_at DateTime(timezone=True)`, nullable, added with `batch_alter_table(recreate="never")`.

    `feedback.store.upgrade_schema(engine)` replaces `create_schema`. In one connection, it stamps `f0001` when `feedback_messages` exists without `feedback_alembic_version` (a store made before this feature), then runs `upgrade head`.

    The lifespan calls it where `create_schema` was called. The shared database, its head `0013`, `env.py`, `alembic.ini` and `ideology db check` are untouched.
11. **Store functions.**
    - `FeedbackMessage` gains `reviewed_at: dt.datetime | None` (UTC, whole seconds).
    - New functions: `list_for_admin(engine, *, from_day, to_day, reviewed, before_id, limit)`, `mark_reviewed(engine, id, now) -> FeedbackMessage | None`, `clear_reviewed(engine, id) -> FeedbackMessage | None` and `delete_message(engine, id) -> bool`.
    - `make_feedback_engine(url)` wraps `db.make_engine` and, for SQLite, adds a connect listener with `PRAGMA secure_delete=ON`, so a deleted message's text is overwritten in the file. On PostgreSQL, dead tuples remain until VACUUM; this is noted in the risks doc.
    - The app uses `make_feedback_engine`. The voter POST path is unchanged.
12. **CLI.**
    - `ideology feedback list` stays read-only. When a message is reviewed, its header line becomes `#<id>  <created>  <origin>  reviewed <YYYY-MM-DDTHH:MM:SSZ>`. Unreviewed lines are unchanged, so the existing format tests still hold.
    - On a store that is not at the feedback head, `list` exits 1 with `<where> needs an upgrade; run "ideology feedback upgrade" or start the server`.
    - New `ideology feedback upgrade` runs `check_separate`, refuses a missing SQLite file with the existing `no feedback store at …` error, runs `upgrade_schema`, and prints `Feedback store <where> is at revision f0002 (head).`
13. **Where the page lives: a separate Vite entry, served by its own route.** This leaves `App.tsx`, `main.tsx`, `paths.ts`, Landing and Questionnaire untouched, so the merge with `feedback-dialog` stays easy, and the Voter bundle contains no admin code.
    - **Build.** `apps/web/admin/index.html` is the second build input in `vite.config.ts` (`build.rolldownOptions.input` or the Vite 8 equivalent, with no deprecation warning) and is emitted as `dist/admin/index.html`. Its head has `lang="es"`, `<meta name="robots" content="noindex, nofollow">`, the same same-origin icon links, and the title `Administración · IdeologiApp`.
    - **Dev server.** The Vite proxy adds `"/admin/api"`. In dev the page is at `/admin/`.
    - **Serving.** `web.py` adds `"admin"` to `_RESERVED_PREFIXES`, so the catch-all never serves `admin/...`, `/admin/index.html` included. `admin_page_router(dist_dir)` serves `GET /admin` and `GET /admin/` from `dist/admin/index.html`; anything else is 404, and so is the page while it is not built.
    - **Page headers.** `Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and `Content-Security-Policy: default-src 'self'; img-src 'self' data:; font-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`.
    - **Route order.** `create_app` includes `admin_router` and `admin_page_router` after `feedback_router` and before `/health` and `web_router`.
    - **Not advertised.** No `robots.txt` is added, because listing `/admin` would advertise it.
14. **Admin client.** `apps/web/src/admin/admin-api.ts` holds `createAdminApiClient({ fetch, baseUrl? })`. It has its own `AdminFetchLike` (methods GET, POST and DELETE) and keeps the `csrf_token` from `signIn` and `getSession` in memory only, never in storage.
    - Methods: `getSession`, `signIn`, `signOut`, `listFeedback(filters, beforeId?)`, `markReviewed`, `unmarkReviewed`, `deleteFeedback`.
    - It rejects with `AdminApiError(kind, status?, retryAfterSeconds?)`, where `kind` is `network | not_signed_in | not_configured | invalid_credentials | rate_limited | csrf | not_found | http`. It checks response shapes like the public client does.
    - It lives in `apps/web`, not in `packages/core`, because core is the Voter and mobile domain. `apps/web/src/admin/main.tsx` is the only other place that passes `window.fetch`.
15. **Retention: deferred to the user, explicitly.** Nothing is deleted automatically; Operators delete messages by hand. The retention period is a user decision, and whether the methodology copy states it stays open in the risks doc. The methodology copy does not change: what is stored about Voters is the same, and the `reviewed_at` mark is Operator data.
16. **Logging.** Application code logs nothing about sign-in: no username, password, hash, token or CSRF token, and no message text. This adds to the existing Voter Feedback logging rule.

## Non-Goals

- Two-factor authentication, password reset or change through the UI, account management in the UI, a record of who reviewed a message, an audit log, bulk actions, search, export, editing or replying to messages, and notifications.
- Automatic retention or purge (Decision 15). CAPTCHA. Rate limits or sessions shared across processes. Deployment settings such as TLS, proxy headers and the worker count.
- Any change to the Voter pages, `App.tsx`, `main.tsx`, `paths.ts`, `tokens.css`, `components.css`, `icons.tsx`, the feedback dialog, `POST /api/v1/feedback` or the methodology copy.
- Any change to the shared DB, its migrations or `data/ideology.db`.

## Job Story

When Voters have sent feedback,
I want to sign in with my own account, triage the messages and remove the ones that should not be kept,
so I can act on what matters without a terminal and without Voters ever needing an account.

## Users And Permissions

- **Operator** (an `ADMIN_USERS` entry, each with their own credentials): signs in and out, lists, filters, marks or unmarks, and deletes. Both Operators have the same rights.
- **Voter:** unchanged and anonymous. Gets no cookie, and the admin routes refuse them without a session.

## Acceptance Scenarios

1. **Sign in.** Given `ADMIN_USERS` holds `prueba:<hash of "contraseña-de-prueba">`, when the Operator posts the correct credentials, then the response is 200 `{username, csrf_token}` and sets `ideology_admin` with `Path=/admin/api; HttpOnly; SameSite=Strict`. `Secure` is set for `https://testserver` and absent for `http://localhost`. Then `GET /feedback` with that cookie is 200.
2. **Wrong credentials.** A wrong password and an unknown username both give 401 `invalid_credentials` with an identical body. `authenticate` calls the scrypt verifier exactly once in both cases (spy). No cookie is set.
3. **Rate limit.** The 6th validated attempt from one client within 900 s gives 429 with `Retry-After ≥ 1`, even with the right password, and scrypt is not called. A fake clock allows the attempt again after the window. The global cap of 30 is covered by a limiter unit test with a fake clock.
4. **No admin.** With `ADMIN_USERS` unset, `POST /session` gives 503 `admin_not_configured` and every other admin route gives 401 `admin_not_configured`. A malformed `ADMIN_USERS` (bad hash, bad username, duplicate, empty entry) makes `TestClient(create_app(...))` raise `ConfigError`, and the message does not contain the value.
5. **401 everywhere.** Each admin route except `POST /session` is called without a cookie, with an unknown token, and after expiry. Expiry uses a fake clock and is checked both as idle (more than 1800 s) and as absolute (more than 28800 s while active). Each gives 401 with no-store and the cookie cleared. Signing out deletes the session, and the old cookie then gives 401.
6. **CSRF.** A state-changing session route with no `X-CSRF-Token`, a wrong one, or a token from another session gives 403 `csrf_failed`, and nothing changes. A sign-in or a state-changing route with `Origin: https://evil.example` or `Sec-Fetch-Site: cross-site` gives 403. Sign-in as `text/plain` gives 415.
7. **List and filter.** Given 60 messages over several days, some reviewed:
   - `GET /feedback` returns 50 messages, newest first, and `next_before_id`. The next page returns the remaining 10 and `null`.
   - `from`/`to` (inclusive UTC days) and `reviewed=yes|no` filter correctly.
   - `to < from` gives 422 `invalid_filter`, and `limit=0` or `101` gives 422.
   - The JSON keys are exactly `id, message, origin, created_at, reviewed_at`.
8. **Mark, unmark, delete.** Marking sets `reviewed_at` (whole seconds, UTC). Marking again keeps the first value. Unmarking clears it. Deleting gives 204, then 404 for every route on that id. The SQLite file no longer contains the deleted text (read its bytes; `secure_delete`). An unknown id gives 404 `feedback_not_found`.
9. **Upgrade keeps messages.**
   - A legacy store, built by `tests/feedback_factory.make_legacy_store` with the pre-feature table and 3 messages, is upgraded by app startup and by `ideology feedback upgrade`. All 3 messages are kept with `reviewed_at` null, at revision `f0002`.
   - `compare_metadata(FEEDBACK_METADATA)` reports no diff, both for a fresh store and for an upgraded legacy store.
   - Running the upgrade twice is a no-op.
   - The shared head is still `0013`, and `tests/test_migrations.py` passes.
10. **CLI.**
    - `admin hash-password` with the input `pw\npw\n`: under 12 characters it exits 1; with mismatched passwords click asks again; otherwise it prints one hash that `verify_password` accepts, and `--username Miguel` exits 2.
    - `feedback list` shows `reviewed <ts>` only on reviewed messages.
    - On a legacy store, `list` exits 1 with the upgrade message and does not modify the file (compare its bytes).
11. **Voters untouched.** `GET /`, `/metodologia`, `/api/v1/elections`, `/health` and `POST /api/v1/feedback` send no `Set-Cookie`. After an admin sign-in on the same client, a request to `/api/v1/elections` carries no `Cookie` header (inspect it through a request hook). `POST /api/v1/feedback` still needs nothing. The public OpenAPI has no `/admin` path.
12. **Page serving.** `GET /admin` and `/admin/` return the admin HTML with every Decision 13 header. `/admin/index.html`, `/admin/x` and `/admin/api/v1/nope` give 404. `/` is still the Voter `index.html`. Admin JSON carries no-store and `X-Robots-Tag`.
13. **UI (Vitest).** The admin client is given a mocked fetch:
    - **Loading and sign-in:** the checking state, the not-configured notice, the sign-in form and its errors (wrong credentials, rate limited with minutes, network).
    - **List:** the list with the date `29 oct 2026, 14:05 UTC`, the origin `Inicio` or `Resultados`, the `Revisado` chip, and text rendered as text (a `<b>` in a message shows literally).
    - **Filters and paging:** filter submission and its query, `Cargar más`, and the empty states.
    - **Mark and unmark:** the button pending state.
    - **Delete:** opens an inline confirmation with focus on `Cancelar`, `Escape` and `Cancelar` restore focus to `Borrar`, and confirming removes the card and announces `Mensaje borrado.`
    - **Session:** a 401 during any action returns to sign-in with `Tu sesión ha caducado. Vuelve a iniciar sesión.`, and sign-out works.
    - **Isolation:** a source-scan test shows that no file outside `src/admin/` imports from it and that no Voter source contains `"/admin"`.
14. **Browser.** See the Verification Plan.

## Repository Research

### Files Inspected

- The harness and docs: `AGENTS.md`, `CONTEXT.md` (Operator), `CONSTRAINTS.md` (Data And Migrations exception, Public API, Client-side Matching fetch rule, Web Client Serving, Styling, Voter Feedback), `ARCHITECTURE.md` (Data Layer, Public API, Web Client, Runtime Surface), `DESIGN.md`, `docs/technical-discovery.md` ("Operator: a single admin credential or CLI-only access"), `docs/risks-and-open-questions.md` (line 14 "Voter feedback"; the "Fetching manifests by URL" entry, which this feature does not trigger because it accepts no URL), `docs/specs/feedback-api.md`, `feature_list.json` and `PROGRESS.md`.
- `src/ideology_app/feedback/store.py`: `create_schema`/`create_all`, `list_messages` and `has_schema`.
- `src/ideology_app/feedback/rate_limit.py`: generic parameters, reused here.
- `src/ideology_app/api/feedback_routes.py`: the body helpers and the error shape.
- `src/ideology_app/main.py`, `web.py` (`_RESERVED_PREFIXES`), `config.py` and `db.py` (shared `SCRIPT_LOCATION`, single head).
- `src/ideology_app/migrations/env.py`, `alembic.ini` and `cli.py` (the `feedback` group).
- `pyproject.toml`: no new dependency is needed.
- `tests/conftest.py`, `tests/test_public_api.py` (`/api/` paths = `router` ∪ `feedback_router`) and `tests/test_web_client.py` (OpenAPI paths).
- `apps/web/{index.html,vite.config.ts,tsconfig.json}`, `src/main.tsx`, `src/app/App.tsx`, `src/app/index-html.test.tsx`, `src/ui/{components.css,design-tokens.test.tsx}`.
- Sibling `feature/feedback-dialog`, read-only through `git diff main...feature/feedback-dialog`. It touches DESIGN.md (dialog tokens `elevation-4` and `scrim`), `tokens.css`, `components.css`, `App.tsx`, `setup.ts`, CONSTRAINTS (two Voter Feedback rules) and risks line 14.

### Existing Patterns To Follow

- Lifespan checks before any Engine is created, then engines are disposed in `finally`. `app.state` holds replaceable limiters. The `_now()` seam. Errors use the `{"error":{...}}` shape with no-store.
- CLI errors are `ClickException`. SQLite is opened read-only for read commands. The `TestClient` uses `base_url="https://testserver"` or `http://localhost`, because httpx does not send a `Secure` cookie over plain http.
- Web: `api` is injected as a prop. Only an entry `main.tsx` touches `fetch`. Tests use mocked fetch, and CSS takes values from tokens only.

### Current Gaps

- No authentication exists. The feedback store has no migrations, and the web build has a single entry.

## Technical Approach

- **Server.**
  - New package `src/ideology_app/admin/`, which imports only the standard library and `config`: `accounts.py` (format, `hash_password`, `verify_password`, `parse_admin_users`, `authenticate`) and `sessions.py`.
  - `api/admin_routes.py`: dependencies `require_session` and `require_csrf`, an origin check, and sync handlers (run in the threadpool) over `request.app.state.feedback_engine`.
  - `create_app(..., admin_users: str | None = None)`: the lifespan resolves `admin_users or config.admin_users_raw()`, parses it into `app.state.admin_accounts` before the engines are created, then runs `make_feedback_engine` and `upgrade_schema`.
- **Web.** A separate admin entry renders `AdminApp`, a small state machine: `checking | not_configured | signed_out{notice?} | signed_in{username}`.
  - Its children are `SignInForm`, `FeedbackInbox` (filters, list, `Cargar más`) and `FeedbackMessageCard` (actions and inline confirmation). `format.ts` formats dates in UTC with `Intl.DateTimeFormat("es-ES", { timeZone: "UTC", ... })` and maps origins to labels.
  - There is no router. Filters live in component state.

## Expected File Changes

- **Python, create:**
  - `src/ideology_app/admin/{__init__,accounts,sessions}.py`
  - `src/ideology_app/api/{admin_routes,request_body}.py`
  - `src/ideology_app/feedback/migrations/{env.py,script.py.mako,versions/f0001_feedback_messages.py,versions/f0002_reviewed_at.py}`
  - tests: `tests/test_admin_accounts.py`, `test_admin_sessions.py`, `test_admin_api.py`, `test_feedback_migrations.py`, `test_cli_admin.py` and `tests/feedback_factory.py` (`make_legacy_store(path, messages)` builds the pre-feature table from a private copy of its old definition; `seed_legacy_store(path, count)` is for the browser walk)
- **Python, modify:**
  - `feedback/store.py` (Decisions 10 and 11), `feedback/rate_limit.py` (docstring only), `api/feedback_routes.py` (import the moved helpers) and `api/__init__.py`
  - `main.py`, `web.py`, `config.py` (`admin_users_raw()`) and `cli.py` (the `admin` group, `feedback upgrade`, the list suffix)
  - `tests/conftest.py` (`delenv("ADMIN_USERS")`), `tests/test_feedback_store.py`, `tests/test_cli_feedback.py` and `tests/test_web_client.py` (the `admin` reserved prefix)
- **Web, create:**
  - `apps/web/admin/index.html`
  - `apps/web/src/admin/{main.tsx,admin-api.ts,AdminApp.tsx,SignInForm.tsx,FeedbackInbox.tsx,FeedbackMessageCard.tsx,format.ts}`
  - tests: `admin-api.test.tsx`, `AdminApp.test.tsx`, `FeedbackInbox.test.tsx`, `admin-isolation.test.tsx` (includes the admin `index.html` head checks)
  - `apps/web/src/ui/admin.css`
- **Web, modify:** `apps/web/vite.config.ts` (input and proxy) and `apps/web/src/ui/design-tokens.test.tsx` (the expected list gains `./admin.css`).
- **Docs:** listed below. `package.json` and the lockfile do not change.

## Visual Design Impact

- UI involved: yes. The design source is `DESIGN.md`, updated **first** with a new `## Operator Admin Page` section inserted between `## Core Screens` and `## Accessibility Baseline`. The section is additive, which keeps it away from `feedback-dialog`'s hunks. No new token and no new design artifact.
- **Frame.** The same tokens and themes, Public Sans and the M3 grid, with the reading measure at most 75ch. There is no brand logo. The `h1` reads `Administración`, focused on load (`tabIndex=-1`). It is never linked from a Voter page.
- **Checking.** A `role="status"` line, `Cargando…`.
- **Not configured.** A notice card with the Decision 9 text in Spanish: `No hay ninguna cuenta de Operador configurada. Define ADMIN_USERS en el servidor; el README explica cómo (ideology admin hash-password).`
- **Sign-in.**
  - A Level 1 card titled `Iniciar sesión` (h2). Two labelled fields:
    - `Usuario`: `autocomplete="username"`, `autocapitalize="none"`, `spellcheck=false`.
    - `Contraseña`: `type="password"`, `autocomplete="current-password"`.
  - The fields use the text-field look: `card` background, 1px `outline` border, small corner, 16px text, 48px minimum height and the focus ring.
  - A filled `Entrar` button, disabled while the request runs.
  - The error is a `role="alert"` text line, either `Usuario o contraseña incorrectos.`, `Demasiados intentos. Vuelve a intentarlo en N minutos.` or `No se pudo conectar. Inténtalo de nuevo.`. On error the password is cleared and focused.
- **Signed in.**
  - **Header row.** `Sesión iniciada como <usuario>` and an outlined `Cerrar sesión`.
  - **Filters.** A `Filtrar` fieldset with `Desde` and `Hasta` (date inputs, labelled `(UTC)`) and `Estado` (a native select: `Todas` (the default), `Sin revisar`, `Revisadas`), then an outlined `Filtrar` button. `Hasta` earlier than `Desde` shows a text problem line and sends nothing. The fields stack at 375px and sit in one row from 600px.
  - **Status line.** A `role="status"` line, `N mensajes mostrados`.
  - **List.** An `<ol>` of Level 1 cards, one per message:
    - A meta line in body-md `on-surface-variant`: `#id · 29 oct 2026, 14:05 UTC · Inicio`.
    - A `Revisado` chip using the `important-mark` pair (`secondary-container`, which means "marked by you").
    - The message in body-lg, `white-space: pre-wrap` and `overflow-wrap: anywhere`, rendered as text.
    - Actions: outlined `Marcar como revisado` / `Marcar como no revisado`, and outlined `Borrar`.
  - **Paging.** `Cargar más` (outlined) when there are more messages.
  - **Empty states.** `Todavía no hay mensajes.` / `Ningún mensaje coincide con los filtros.`
  - **Load error.** An alert with `Reintentar`. An action error is an alert line inside its card.
- **Delete confirmation (inline, not a modal).** This avoids the dialog tokens that `feedback-dialog` adds. Inside the card, the actions are replaced by the text `¿Borrar este mensaje para siempre? No se puede deshacer.`, a filled `Borrar definitivamente` and an outlined `Cancelar`.
  - Focus goes to `Cancelar`. `Escape` or `Cancelar` closes the confirmation and focuses `Borrar` again.
  - After the delete, the card is gone, the status line says `Mensaje borrado.`, and focus moves to the next card's first action, or else to the status line.
- **Session expired.** The sign-in form returns with a notice line, `Tu sesión ha caducado. Vuelve a iniciar sesión.`
- **Tab title.** `Administración · IdeologiApp`.
- **Accessibility.** Every pair used is already in the contrast table. The 48px tap targets and DOM order give the focus order. The chip carries its state in text.

## Durable Documentation Impact

- **`CONSTRAINTS.md`: update, additively.** Keep the existing lines, except where a bullet below says to replace one.
  - **Data And Migrations:** replace the feedback `create_all` exception. The feedback schema changes only through `src/ideology_app/feedback/migrations/versions/`, applied by `feedback.store.upgrade_schema` and versioned in `feedback_alembic_version`. Feedback tables never join `Base.metadata`.
  - **Public API:** add one sentence. Operator routes live under `/admin/api/v1`, outside the public `/api/`, are not in the public OpenAPI, and every route needs a session except sign-in.
  - **Client-side Matching (fetch rule):** add that `apps/web/src/admin/main.tsx` passes `fetch` only to `createAdminApiClient`, and that Voter code never imports `src/admin/`.
  - **Web Client Serving:** `admin` is a reserved prefix.
  - **Voter Feedback:** amend the stored fields to add `reviewed_at`, an Operator mark that is not Voter data.
  - **New section "Operator Access":**
    - Only Operators authenticate. Voters never get an account or a cookie, and the admin cookie is limited to `Path=/admin/api`.
    - Accounts come only from `ADMIN_USERS`, as salted scrypt hashes, never in git or in code.
    - The CSRF and origin checks run on every state-changing admin route.
    - Comparisons are constant-time.
    - Nothing about sign-in is logged.
    - Admin responses are `no-store` and `noindex`.
    - Tests use throwaway hashes made in the test, never the real accounts.
- **`ARCHITECTURE.md`: update.** Add `feedback-admin` to the current-state list. Update the Data Layer (the feedback migrations env and the new store functions), add an Admin API subsection with the table, add the second entry and serving to Web Client, and add `/admin`, `ADMIN_USERS`, `admin hash-password` and `feedback upgrade` to the Runtime Surface.
- **`AGENTS.md`: not needed.** The invariants still hold.
- **`CONTEXT.md`: update.** The Operator also reads and moderates Voter feedback on the admin page, signed in with their own account. Add the term `Feedback Message`: an anonymous message a Voter sends about the tool, which an Operator may mark as reviewed or delete, and which is never Answers.
- **`docs/technical-discovery.md`: update.** In Authentication, replace the Operator line with per-Operator username and password accounts for the admin page (`feedback-admin`), and keep the CLI. Add an `ADMIN_USERS` row to Configuration.
- **`README.md` (Spanish): update.** Add a section "Cuentas de Operador y página de administración":
  - create a hash with `.venv/bin/ideology admin hash-password --username miguel`;
  - set `ADMIN_USERS=miguel:scrypt…,enrique:scrypt…` in the server environment (never in git);
  - restart, then open `/admin`;
  - one worker, HTTPS outside localhost, and `ideology feedback upgrade`.

  Also add the `ADMIN_USERS` row to the env table and the reviewed suffix to `feedback list`.
- **`docs/risks-and-open-questions.md`: update.**
  - **Line 14:** replace only the clause "retention and deletion, and who reads and moderates the messages (user decision, later feature)" with "retention (see Voter feedback moderation)", and delete the clause "any feedback-store schema change, which needs its own Alembic environment…". `feedback-dialog` edits the same line, so expect a one-line conflict. Resolve it by keeping its text and reapplying these two edits.
  - **New entry "Voter feedback moderation (`feedback-admin`)"**, placed after the Donations entry. Settled: Operators `miguel` and `enrique`, scrypt accounts in `ADMIN_USERS`, mark and delete. Open: the retention period (user), and whether `/metodologia` states it. Deployment: one worker (in-memory sessions and limiter), TLS, `--proxy-headers` for the sign-in key, and PostgreSQL deleted text remaining until VACUUM, plus backups.
  - **Accepted Low:** sign-in lockout through the global budget; no 2FA.

## Implementation Plan

1. Update DESIGN.md first (Visual Design Impact).
2. Store: the migrations env, `f0001` and `f0002`, `upgrade_schema`, the new functions, `make_feedback_engine`, `feedback_factory` and the migration and store tests.
3. `admin/accounts.py` and `admin/sessions.py`, with their tests (fake clock, scrypt spy).
4. `api/request_body.py` refactor (the feedback tests must stay green), then `admin_routes.py`, the `web.py` page router and prefix, the `main.py` wiring, and the API tests.
5. CLI: `admin hash-password`, `feedback upgrade` and the list suffix, with tests.
6. Web: the Vite entry and proxy, `admin-api.ts`, the components, `admin.css`, the tests and the token-test list.
7. Docs and the risks entries. Then run `CI=true ./init.sh`, the build checks and the browser walk, and record the evidence.

## Implementation Tasks

- [ ] DESIGN.md `## Operator Admin Page`
- [ ] Feedback migrations env, `f0001`, `f0002`, `upgrade_schema` (replaces `create_schema`), `make_feedback_engine` (`secure_delete`), store functions, `reviewed_at`
- [ ] `admin.accounts` (format, hash, verify, parse, authenticate) and `admin.sessions`
- [ ] `api/request_body.py`, `admin_router` (6 routes, CSRF and origin checks, headers), `admin_page_router`, reserved prefix, `create_app(admin_users=)`, sign-in limiter
- [ ] `ideology admin hash-password`, `ideology feedback upgrade`, `list` reviewed suffix and upgrade error
- [ ] `apps/web/admin/index.html`, Vite input and proxy, `src/admin/*`, `ui/admin.css`
- [ ] Python and Vitest tests for Scenarios 1–13
- [ ] CONSTRAINTS, ARCHITECTURE, CONTEXT, technical-discovery, README, risks

## Verification Plan

- **Gate.** `CI=true ./init.sh` passes (pytest, typecheck, Vitest, build). Focused runs:
  - `.venv/bin/pytest tests/test_admin_*.py tests/test_feedback_*.py tests/test_cli_admin.py tests/test_cli_feedback.py tests/test_public_api.py tests/test_web_client.py tests/test_migrations.py -q`
  - `npm test -w @ideology-app/web`
- **Build checks** after `npm run build`:
  - `dist/admin/index.html` exists.
  - `grep -l "admin/api" apps/web/dist/assets/*.js` matches only the admin chunk(s), never the chunk loaded by `dist/index.html`.
  - `git status` shows no `feedback.db` and no `migrations/versions/0014*`, and `data/ideology.db` is unchanged.
- **E2E.** There is no persistent E2E harness. TestClient and Vitest cover the flows, and the browser walk is mandatory.
- **Browser walk** (both implementer and validator; any automation tool, for example Chrome DevTools):
  1. Run in the worktree only:

     ```bash
     cd /Users/miguel.garcia/Documents/Development/AiExpert/IdeoliApp-worktrees/feedback-admin && CI=true ./init.sh
     S=$(mktemp -d) && cp data/ideology.db "$S/ideology.db"
     ```

  2. Seed a **legacy** store: `.venv/bin/python -c "import sys; sys.path.insert(0, 'tests'); from feedback_factory import seed_legacy_store; seed_legacy_store('$S/feedback.db', count=60)"`. The helper spreads 60 messages (several multi-line, one with `<b>`, emoji, both origins) over 10 days.
  3. Create a hash with `.venv/bin/ideology admin hash-password --username prueba` and a throwaway password typed at the prompt. Never use a real Operator password.
  4. Start the server:

     ```bash
     DATABASE_URL=sqlite:///$S/ideology.db FEEDBACK_DATABASE_URL=sqlite:///$S/feedback.db ADMIN_USERS=<printed entry> .venv/bin/uvicorn ideology_app.main:app --port 8010
     ```

     Use port 8010, not 8000, so it does not clash with a `feedback-dialog` server. Startup upgrades the legacy store; then `.venv/bin/ideology feedback --feedback-database-url sqlite:///$S/feedback.db list | tail -1` prints `60 message(s)`.
  5. At `http://127.0.0.1:8010/admin`, at 375px and 1280px, in light and dark (emulate `prefers-color-scheme`), once with the keyboard only (Tab, Enter, Escape, visible focus ring) and once with the pointer:
     1. Sign in with a wrong password, then the right one.
     2. Read the list, newest first, with UTC dates, origins, multi-line text and the literal `<b>`.
     3. Use `Cargar más`.
     4. Mark and unmark a message.
     5. Filter by date and by state, including the `Hasta`-before-`Desde` problem line.
     6. Delete: cancel once with `Escape` and once with `Cancelar`, then confirm.
     7. Sign out, reload, and see the sign-in form.
  6. Restart the server while signed in. The next action shows the session-expired notice. Restart without `ADMIN_USERS`, and the page shows the not-configured notice.
  7. Check the headers: `curl -sI http://127.0.0.1:8010/admin` shows the Decision 13 headers, and `/admin/index.html` gives 404.
  8. Run a Voter flow in a fresh profile: Landing, questionnaire, results, and the feedback POST if `feedback-dialog` is merged. DevTools Application shows no cookie for the origin, and Network shows no `Cookie` request header. In the Operator profile, the `ideology_admin` cookie shows `Path=/admin/api`, and Voter requests do not carry it.
  9. Throughout, the console shows no errors and no CSP violations, and no request fails except the expected 401s, 403s and 404s.

## Evidence To Capture

- The `CI=true ./init.sh` counts, the names of the tests for Scenarios 1–13, the build grep result, the CLI `60 message(s)` line after the legacy upgrade, the curl header output, and the browser and widths and themes walked, with the results.
- Record it in `feature_list.json` `evidence` and `PROGRESS.md` (never `docs/validations/`).

## Validator Checklist

- [ ] Every `verification` item is met and Decisions 1–16 are implemented as written.
- [ ] No plain-text password, real hash or `ADMIN_USERS` value is in git. Test hashes are made in the tests.
- [ ] Voter routes set no cookie, and the admin cookie never reaches Voter requests. `/api/v1/feedback` is unchanged. The Voter bundle has no admin code, and no Voter page links `/admin`.
- [ ] A legacy `feedback.db` keeps all its messages after the upgrade. The shared DB head is still `0013`, and `data/ideology.db` is unchanged.
- [ ] Admin page and API send no-store and noindex. The page also sends CSP, frame and referrer headers. There are no CSP violations in the console.
- [ ] Docs and risks are updated as listed, with line 14 edited in place and not duplicated.
- [ ] No out-of-scope work, such as Voter UI, 2FA or retention jobs.
- [ ] The browser walk is recorded with its widths, themes and input modes.
