# Feature Implementation Spec: Store anonymous Voter feedback

## Source Feature

- `id`: feedback-api
- `area`: api
- `depends_on`: public-dataset-api (accepted)
- `status`: not_started at planning time
- `source`: `feature_list.json` (its `verification` list is binding)

## Goal

`POST /api/v1/feedback` accepts an anonymous message of 1 to 500 characters, with the screen it came from, and stores it in a feedback store that is separate from the shared database. An Operator reads the messages with `ideology feedback list [--since DATE]`. `packages/core` gets `sendFeedback` so the future dialog (`feedback-dialog`) never calls `fetch` itself. CONSTRAINTS.md and the methodology privacy copy stop saying that nothing is stored.

## Decisions

1. **Message rule (one rule for the server and client).** These steps run in order on the JSON string `message`:
   - (a) **Refused characters** are checked on the raw value: C0/C1 controls `U+0000–U+0009`, `U+000B–U+001F` and `U+007F–U+009F`. This includes `\t` (`U+0009`) and `\r` (`U+000D`); only `\n` (`U+000A`) is allowed. Unpaired surrogates (`U+D800–U+DFFF`, which can reach Python through a JSON `\ud800` escape) are also refused. The binding text allows only newlines. Browsers turn line breaks in a `<textarea>` into `\n`, so `\r` never comes from the web client. Tabs in pasted text are left to `feedback-dialog` (see Non-Goals).
   - (b) **Trim**: leading and trailing characters are removed only from this explicit set, which equals ECMAScript `String.prototype.trim`: `\t \n \v \f \r`, `U+0020`, `U+00A0`, `U+1680`, `U+2000–U+200A`, `U+2028`, `U+2029`, `U+202F`, `U+205F`, `U+3000`, `U+FEFF`. Python must use `str.strip(TRIM_CHARS)`, never bare `strip()`, because Python's whitespace set differs: it lacks `U+FEFF` and has `U+001C–U+001F` and `U+0085`.
   - (c) **Count** the trimmed text in **Unicode code points**: Python `len(s)`, JS `Array.from(s).length`. UTF-16 code units are not used, so an emoji counts 1. There is no Unicode normalisation (`e` + `U+0301` counts 2) and no grapheme clustering. An empty result fails as `empty` and more than 500 fails as `too_long`.
   - (d) **The trimmed text is stored.** Nothing else changes it.
2. **Request.** `Content-Type` must be `application/json` (case-insensitive, parameters allowed), else **415**. Requiring it means a cross-site form or `text/plain` post needs a CORS preflight, which fails because there is no CORS. The body is at most **8192 bytes**, else **413**:
   - `Content-Length > 8192` is refused before the body is read.
   - A body without that header is read from `request.stream()` and refused as soon as it passes 8192 bytes.
   - 8192 bytes holds any valid body. The worst case is 500 astral characters as `\uXXXX\uXXXX` escapes, about 6000 bytes.

   The body is parsed with `FeedbackIn.model_validate_json` (pydantic: `strict=True`, `extra="forbid"`):
   - `message: str`, checked by the rule above.
   - `origin: Literal["landing", "results"]`.
   - optional honeypot `website: str | None = None`.

   Unknown keys (for example `answers`) and invalid JSON give **422** in FastAPI's `{"detail": [...]}` shape (raise `RequestValidationError(exc.errors())`).

   The route parses the body by hand, so it declares the schema with `openapi_extra` (required `application/json` requestBody = `FeedbackIn` schema). It has `operation_id="sendFeedback"`.
3. **Responses.**
   - `201 {"status": "received"}`. The body never carries an id, so it reveals nothing about volume.
   - 413 / 415 / 429 use the existing error shape `{"error": {"code", "message"}}` with codes `payload_too_large`, `unsupported_media_type` and `rate_limited`.
   - Every response of this route has `Cache-Control: no-store`.

   Order of checks: 415 → 413 → 422 → 429 → honeypot → store.
4. **Storage.**
   - Table `feedback_messages`: `id` (integer PK, a surrogate row counter, not Voter data), `message` (Text, not null), `origin` (`sa.Enum("landing", "results", name="feedback_origin", native_enum=False, create_constraint=True)`), and `created_at` (`DateTime(timezone=True)`, UTC, truncated to whole seconds).
   - Nothing else is stored: no IP, user agent, cookie, Election, Dataset Version, answers or honeypot value.
5. **Schema management: separate MetaData + `create_all`, no Alembic.** `ideology_app.feedback.store` owns `FEEDBACK_METADATA = sa.MetaData()` and a Core `Table`, never `models.Base`. `create_schema(engine)` runs `FEEDBACK_METADATA.create_all(engine)` (checkfirst) when the app starts.
   - The shared DB stays untouched: there is no new migration, the head stays `0013`, and `alembic check` / `ideology db check` see nothing new because `env.py` targets `Base.metadata` only.
   - An Alembic branch in the same script directory was rejected. It gives two heads, which breaks `db.head_revision()` / `is_initialised`.
   - A second Alembic environment was rejected as too heavy for one append-only table.
   - The first schema change to the feedback store must add its own Alembic environment that stamps the existing table. This is recorded in the risks doc.
6. **Configuration.** `config.feedback_database_url()` returns `$FEEDBACK_DATABASE_URL` (trimmed, if non-empty), else `DEFAULT_FEEDBACK_DATABASE_URL = "sqlite:///feedback.db"`, which is relative to the current directory. `.gitignore` already ignores it (`*.db`). Add the comment line `# feedback.db (FEEDBACK_DATABASE_URL default) is ignored by *.db; never commit it.` PostgreSQL URLs are allowed (deployment).
7. **Refusing the shared database.** `feedback.store.check_separate(feedback_url, database_url)` raises `FeedbackStoreError` (a `config.ConfigError` subclass) in these cases:
   - **(i)** `shared_db.is_shared(feedback_url)`. The path resolves to `config.SHARED_DATABASE_PATH`, following symlinks.
   - **(ii)** the feedback SQLite path and the `database_url` SQLite path (`shared_db.sqlite_path`) resolve to the same file.
   - **(iii)** both files exist and `os.path.samefile` is true (hard links).
   - **(iv)** one of them is not SQLite and the two URLs, rendered by `make_url(...).render_as_string(hide_password=False)`, are equal.
   - **(v)** the feedback URL is in-memory SQLite (`sqlite_path` is `None` and the backend is SQLite). Messages would vanish.

   The message names the variable, never the password: `FEEDBACK_DATABASE_URL must point at its own database, not at <data/ideology.db | the DATABASE_URL database>; use e.g. sqlite:///feedback.db` (in-memory: `... must not be an in-memory database`). Two places run it:
   - **App startup**, in the `create_app` lifespan, before any engine is created. The exception propagates, so uvicorn prints `Application startup failed` and exits non-zero.
   - **CLI**: `ideology feedback list` raises a `ClickException` with the same message, exit 1.
8. **Abuse guard** (`feedback.rate_limit`, per process, documented in ARCHITECTURE.md):
   - **Per client:** 5 accepted requests per 600 s (sliding window).
   - **Global:** 120 per 600 s.
   - **Memory:** at most 10,000 tracked keys. Expired entries are pruned when that is reached. If the map is still full, the request gets 429 (fails closed).
   - **Budget:** only requests that passed validation consume budget (including honeypot hits); a request is counted only when both limits allow it. A 422 stores nothing and consumes nothing.
   - **429:** sent with `Retry-After` = whole seconds, rounded up and at least 1, until the window lets the request through again.
   - **Key:** `hmac.new(process_key, client_host, sha256).digest()[:16]`. `process_key` is `secrets.token_bytes(32)` per limiter instance. `client_host` is `request.client.host`, or `"unknown"`. The key lives only in memory and is never logged, stored or put in an error.

   **Why the IP is used at all.** The rule is that no IP is *stored*: none in the feedback store, the app's logs or messages. Without the per-client key, a single sender could use up the global budget and silence every Voter. A keyed hash under a random per-process key that is never persisted cannot be linked back to an IP after a restart, and entries expire after 10 minutes. Behind a reverse proxy every client shares the proxy's host. The deployment feature must set uvicorn `--proxy-headers` / `--forwarded-allow-ips`; this is deferred.

   **Honeypot:**
   - A non-empty `website` (after the trim in Decision 1b) returns the same `201` and stores nothing.
   - The clock is injectable (`time.monotonic` by default).
   - `create_app` builds one `FeedbackRateLimiter` on `app.state.feedback_rate_limiter`, so a test can replace it.
9. **CLI.** The `ideology feedback` group has the option `--feedback-database-url` (envvar `FEEDBACK_DATABASE_URL`, default from `config`). Run `check_separate` against the main group's URL.

   `feedback list [--since YYYY-MM-DD]` (`click.DateTime(["%Y-%m-%d"])`, as in `election create`) shows messages with `created_at >= DATE 00:00:00 UTC`, oldest first (`created_at`, then `id`). It opens SQLite read-only (`shared_db.read_only_url`), so it never creates or writes a file:
   - **Missing file:** `Error: no feedback store at <path>; the server creates it on startup` (exit 1).
   - **File without the table:** `Error: <path> is not a feedback store` (exit 1).

   Output for each message:

   ```text
   #<id>  <created_at as YYYY-MM-DDTHH:MM:SSZ>  <origin>
     <each message line, indented by 2 spaces>

   ```

   Messages are separated by one blank line, and the output ends with `N message(s)`. With no matches it prints only `No feedback messages.` and exits 0. The output is safe in a terminal because escape codes cannot get in (all C0/C1 controls are refused).
10. **Client.** `packages/core` has these parts:
    - **Domain module.** `src/domain/feedback.ts` (pure) exports:
      - `FEEDBACK_MAX_CHARS = 500`
      - `FeedbackOrigin = "landing" | "results"`
      - `trimFeedback(text)` (`text.trim()`)
      - `countFeedbackChars(text)` (`Array.from(text).length`)
      - `feedbackProblem(text): "control_character" | "empty" | "too_long" | null` (Decision 1 order; regexes `/[\u0000-\u0009\u000B-\u001F\u007F-\u009F]/` and an unpaired-surrogate regex, ES2022 lib, so no `isWellFormed`)
    - **Port.** `src/application/feedback-api.ts`: `interface FeedbackApi { sendFeedback(feedback: FeedbackInput): Promise<void> }`, with `FeedbackInput { message: string; origin: FeedbackOrigin; website?: string }`. It is a separate port so the existing `PublicApi` fakes (`open-share-link.test.ts`) do not change.
    - **Client.** `createPublicApiClient` returns `PublicApiClient = PublicApi & FeedbackApi`.
    - **Request.** `sendFeedback` sends exactly one `POST ${baseUrl}/api/v1/feedback` with `{ method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ message, origin, website? }) }`. `website` is included only when it is a non-empty string. The message is sent as given, because the server is the authority. Nothing else goes in the body: no Election, Dataset Version or Answers.
    - **Errors.** A rejected fetch is `PublicApiError("network", "POST /api/v1/feedback failed: network error")`. `!ok` is `PublicApiError("http", "POST /api/v1/feedback failed: HTTP <status>", status)`. Any `ok` resolves with no value, and the body is never read.
    - **Type change.** `FetchLike`'s `init` widens to `{ method: "GET" | "POST"; headers; body?: string }`. GET calls keep their exact current `init` (no `body` key), so the existing `toHaveBeenCalledWith` tests stay unchanged. `main.tsx` keeps passing `window.fetch`.
11. **Copy.**
    - The methodology section `Tus respuestas` keeps its heading (the 8 headings stay the same) and its two paragraphs. Add a third paragraph, `FEEDBACK_TEXT`, after the share paragraph: «Si nos envías tu opinión sobre la herramienta, se guarda solo el texto que escribas, la pantalla desde la que la envías (la de inicio o la de resultados) y la fecha. No se guardan tus respuestas, tu dirección IP ni ningún otro dato sobre ti. Para frenar los envíos masivos, el servidor cuenta durante unos minutos, solo en memoria, los envíos de cada conexión. No escribas datos personales en el mensaje.»
    - Retention is not stated (open, see risks).

## Non-Goals

- Any UI: the button, the dialog, the counter, and what to do with tabs in pasted text are left to `feedback-dialog`. Guidance for it: count with `countFeedbackChars`, never `maxLength` or `.length`, which count UTF-16 units; disable Enviar on `feedbackProblem`; replacing `\t` with a space before sending is acceptable. No DESIGN.md change here.
- Retention, deletion, moderation, Operator notification, CAPTCHA, a shared rate limit across processes, and deployment logging and proxy settings.
- Any change to the shared DB, its migrations or `data/ideology.db`.

## Job Story

When I have used IdeologiApp and want to say what I think,
I want to send a short anonymous message,
so the team can improve the tool without learning anything else about me (and the Operator can read it from the CLI).

## Users And Permissions

- Voter (anonymous): may POST feedback under the rate limit. Nothing identifies them.
- Operator: reads feedback with the CLI. The API has no read endpoint.

## Acceptance Scenarios

1. **Stored.** Given a running app with a temporary `FEEDBACK_DATABASE_URL`, when `{"message":"  Muy útil 👍\n","origin":"results"}` is posted as `application/json`, then the response is `201 {"status":"received"}` with `no-store`, and exactly one row holds `Muy útil 👍`, `results` and a UTC `created_at` in whole seconds. The main DB gets no statement.
2. **Rule vectors** (the server and `feedback.test.ts` both use them):

   | Input | Result |
   | --- | --- |
   | `"x"*500` | ok |
   | `"😀"*500` | ok (1000 UTF-16 units) |
   | `"x"*500 + "  \n"` | ok |
   | `"x"*501` | too_long |
   | `"😀"*501` | too_long |
   | `""`, `"   "`, `"\n\n"` | empty |
   | `" 　﻿ hola  "` | stored `hola` |
   | `"a\nb"` | ok |
   | `"a\tb"`, `"a\r\nb"`, `"a\u0000"`, `"a\u0085"`, `"a\u001b[31m"`, lone `"\ud800"` | control_character |
   | `"é"` | ok, counts 2 |

   On the server every failing vector gives 422.
3. **Bad shape.** Given the app, when the body has an unknown key (`answers`), a bad `origin`, a non-string `message`, a missing field or invalid JSON, then it gets 422 and nothing is stored.
4. **Media type and size.** `text/plain` or a missing Content-Type gives 415. A 9000-byte body gives 413, both with `Content-Length` and as a chunked stream (a generator body in TestClient). In every case nothing is stored.
5. **Rate limit.** 5 valid posts from one client give 201. The 6th gives `429` with `rate_limited`, an integer `Retry-After ≥ 1` and nothing stored. With a fake clock, the limiter allows the request again after 600 s. The global cap and the key-map cap behave as in Decision 8 (unit tests on the limiter). Neither a 422 nor a 415 consumes budget.
6. **Honeypot.** `website: "http://spam"` gives `201` with the same body and nothing stored, and it counts toward the limit. `website: ""` stores normally.
7. **Refusal.** `FEEDBACK_DATABASE_URL` is set to `sqlite:///data/ideology.db`, to a symlink to it, to the same file as `DATABASE_URL`, or to `sqlite://`:
   - Entering `TestClient(create_app(...))` raises `FeedbackStoreError` with the message from Decision 7, and no feedback file is created.
   - `ideology feedback list` exits 1 with that message.
   - `data/ideology.db` is never opened for write.
8. **Shared DB untouched.** `models.Base.metadata` has no `feedback_messages`, `db.head_revision()` is still `0013`, `tests/test_migrations.py` (drift) passes, and there is no new file in `migrations/versions/`.
9. **CLI.** For a store with 3 messages on 2026-10-01, 2026-10-05 and 2026-10-05, one of them multi-line, `feedback list` prints all three in the Decision 9 format plus `3 message(s)`, and `--since 2026-10-05` prints 2. `--since 05/10/2026` is a usage error (exit 2). An empty store prints `No feedback messages.` A missing file is an error, and no file is created.
10. **Client.** `sendFeedback({message:"hola", origin:"landing"})` makes one call with the exact Decision 10 `init`, and the parsed body equals `{message:"hola",origin:"landing"}` (no other key). `website` is sent only when non-empty. 201 resolves with `undefined` and `json` is not called. 429 and 500 reject `http` with that status. A rejected fetch rejects `network`. `baseUrl` is prefixed and its trailing `/` trimmed.
11. **Copy.** `/metodologia` shows `FEEDBACK_TEXT` as the third paragraph of `Tus respuestas`. The 8 headings stay the same and the page makes no request.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONSTRAINTS.md`, `ARCHITECTURE.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md` (entry "Voter feedback" names this feature), `docs/specs/shared-database.md`, `docs/specs/public-dataset-api.md`, `feature_list.json`.
- `src/ideology_app/config.py`: defaults, `ConfigError`, `SHARED_DATABASE_PATH`.
- `src/ideology_app/shared_db.py`: `sqlite_path`, `is_shared` and `read_only_url`, reused here.
- `src/ideology_app/db.py`: `make_engine`, and `head_revision` (a single head is assumed).
- `src/ideology_app/migrations/env.py`: `target_metadata = Base.metadata`.
- `src/ideology_app/main.py`: the lifespan engine, router order, and `app = create_app()` at import.
- `src/ideology_app/api/{__init__,routes,schemas,http_cache}.py`: the GET-only router and the error shape.
- `src/ideology_app/cli.py`: the `main` group with `AppContext.url`, `requires_db`, and `click.DateTime` usage.
- `tests/conftest.py`: the autouse env cleanup and `chdir(tmp_path)`.
- `tests/test_public_api.py`: around lines 662–686, `router` routes are asserted GET-only and the app's `/api/` paths must equal them.
- `tests/test_web_client.py`: around lines 136–140, the OpenAPI paths are compared with `router`.
- `packages/core/src/infrastructure/http/public-api-client.ts`, `src/application/public-api.ts`, `src/index.ts`, `test/infrastructure/public-api-client.test.ts`.
- `apps/web/src/features/methodology/MethodologyPage.tsx` and its test (`PRIVACY_TEXT`, `SHARE_TEXT`).
- `.gitignore` (`*.db`), `init.sh`, `tsconfig.base.json` (lib ES2022).

### Existing Patterns To Follow

- Error JSON shape and `no-store` come from `main._api_not_found` / `http_cache.ERROR_CACHE_CONTROL`.
- Engines are disposed in the lifespan's `finally`.
- Config getters trim env values. The CLI reports errors as `ClickException`.
- In packages/core, contract and HTTP errors are `PublicApiError` kinds, and the injected `fetch` is called as a plain function.

### Current Gaps

- No write endpoint exists, and the CONSTRAINTS Public API rule forbids one. This feature amends that rule.
- No second store exists.

## Technical Approach

- **New package `src/ideology_app/feedback/`.** It imports only `config`, `db.make_engine` and `shared_db`, and never `models`.
  - `message.py` (pure): `TRIM_CHARS`, `MAX_CHARS = 500`, `clean_message(raw) -> str`. It raises `ValueError` with these messages: `message must not contain control characters other than newline`, `message must not be empty`, `message must be at most 500 characters`.
  - `store.py`: `FEEDBACK_METADATA`, `feedback_messages`, `FeedbackStoreError`, `check_separate`, `create_schema`, `add_message(engine, message, origin, now)`, and `list_messages(engine, since) -> list[FeedbackMessage]`.
  - `rate_limit.py`: `FeedbackRateLimiter(per_client=5, global_limit=120, window_seconds=600, max_keys=10_000, clock=time.monotonic)` with `check_and_consume(client_host) -> int | None`, which returns the Retry-After seconds when refused.
- **API.**
  - `api/schemas.py` gets `FeedbackIn` (the validator calls `clean_message`) and `FeedbackAcceptedOut`.
  - New `api/feedback_routes.py` holds `feedback_router = APIRouter(prefix="/api/v1", tags=["feedback"])` with one `async def send_feedback(request: Request)`. It does the checks of Decision 3, then runs `await run_in_threadpool(add_message, request.app.state.feedback_engine, ...)`.
  - `api/__init__.py` re-exports it.
  - The read-only `router` stays GET-only.
- **App.** `main.create_app(database_url=None, web_dist_dir=None, feedback_database_url=None)`:
  - It creates the limiter on `app.state`.
  - The lifespan resolves both URLs, calls `check_separate`, then creates the main engine and the feedback engine and calls `create_schema`. Both engines are disposed in `finally`.
  - It includes `feedback_router` after `router`, before `/health` and the web catch-all.
- **CLI.** A `feedback` group and a `list` command in `cli.py`. They do not use `requires_db` and never connect to the main DB.

## Expected File Changes

- Create `src/ideology_app/feedback/{__init__,message,store,rate_limit}.py` and `src/ideology_app/api/feedback_routes.py`.
- Modify:
  - `src/ideology_app/api/{__init__,schemas}.py`, `src/ideology_app/main.py`, `src/ideology_app/config.py`, `src/ideology_app/cli.py`.
  - `tests/conftest.py`: add `delenv("FEEDBACK_DATABASE_URL")`.
  - `tests/test_public_api.py` and `tests/test_web_client.py`: the `router` stays GET-only, and the app's `/api/` paths = `router` ∪ `feedback_router`.
  - `.gitignore` (comment only).
- Create the tests `tests/test_feedback_message.py`, `test_feedback_store.py`, `test_feedback_rate_limit.py`, `test_feedback_api.py` and `test_cli_feedback.py`. Each one that touches `data/ideology.db` builds it under `tmp_path/data/` (`chdir` is already `tmp_path`).
- Create `packages/core/src/domain/feedback.ts`, `src/application/feedback-api.ts` and `test/domain/feedback.test.ts`. Modify `src/infrastructure/http/public-api-client.ts`, `src/index.ts` (export the new types and functions) and `test/infrastructure/public-api-client.test.ts`.
- Modify `apps/web/src/features/methodology/MethodologyPage.tsx` and `.test.tsx` (`FEEDBACK_TEXT`).
- Modify the docs below.

## Visual Design Impact

- UI involved: only a static copy paragraph on `/metodologia`, with no new component or style. DESIGN.md: not needed. No new design artifact.

## Durable Documentation Impact

- **`CONSTRAINTS.md`: update.**
  - Data And Migrations: allow `create_all` only for `feedback.store.FEEDBACK_METADATA` through `create_schema`. Feedback tables MUST NOT join `models.Base.metadata` or the shared-DB migrations.
  - Public API: make `POST /api/v1/feedback` the single exception to GET-only/read-only. It writes only the feedback store, and the body is limited to `message`, `origin` and `website` (extra keys refused).
  - Client-side Matching: the feedback POST is the only request that carries free text, and it carries no Answers. `sendFeedback` sends only those fields.
  - New "Voter Feedback" section:
    - Only `message`, `origin`, `created_at` and a surrogate id are stored. No IP, UA, cookie, Election, Dataset Version or answers.
    - `FEEDBACK_DATABASE_URL` MUST NOT point at the shared or `DATABASE_URL` database (`check_separate`).
    - Application code MUST NOT log message text or client addresses.
    - The rate limiter keeps only per-process HMAC keys in memory.
    - The message rule lives only in `feedback/message.py` and `packages/core/src/domain/feedback.ts`, kept equal by the shared vectors.
    - Tests use a temporary feedback store.
- **`ARCHITECTURE.md`: update.** Add `feedback-api` to the "Current state" list. Data Layer: the feedback store and its dependency direction. Public API: the POST row, the error codes and the abuse guard numbers. Public API Client: `sendFeedback`. Runtime Surface: the endpoint, `FEEDBACK_DATABASE_URL` and `ideology feedback list`.
- **`AGENTS.md`: not needed.** The invariant "never store voter answers" still holds.
- **`docs/technical-discovery.md`:**
  - Configuration table: add a `FEEDBACK_DATABASE_URL` row.
  - Data and Storage: "No Voter answers are stored on the server; anonymous feedback text is stored in a separate store (`feedback-api`)."
- **`README.md`:** add the env table row and the `ideology feedback list` usage.
- **`docs/risks-and-open-questions.md`:** edit the existing "Voter feedback" entry in place. Do not add a second one. The new entry:
  - Begins `Settled by feedback-api:` and lists the separate store and its refusal, the stored fields, the message rule, the abuse guard and the privacy copy.
  - Then `Open:` lists:
    - retention and deletion, and who reads and moderates (user decision, later feature);
    - spam beyond the per-process limit and honeypot, for example CAPTCHA;
    - deployment items: where `FEEDBACK_DATABASE_URL` lives, uvicorn `--proxy-headers` for the rate-limit key, limits multiplying with workers, and access logs that pair the time of `POST /api/v1/feedback` with an IP;
    - feedback-store schema changes, which need their own Alembic environment.
  - Then `For feedback-dialog:` lists tabs in pasted text and counting with `countFeedbackChars`.
  - Add an Accepted Low: the CLI prints bidi and format characters (`Cf`) as stored, because refusing them would break emoji ZWJ sequences.
- `CONTEXT.md` / `docs/domain-model.md`: not needed. Feedback is not a domain entity of the matching model.

## Implementation Plan

1. Add the config getter, `feedback/message.py` and its tests (the vectors).
2. Add `feedback/store.py` (`check_separate` and the store functions) and its tests, including symlink, hard-link, in-memory and same-as-`DATABASE_URL` cases.
3. Add `feedback/rate_limit.py` and its tests with a fake clock.
4. Add the schemas, `feedback_routes.py` and the `main.py` wiring, then the API tests. Update the GET-only and OpenAPI tests and conftest.
5. Add the CLI command and its tests.
6. In packages/core: add `feedback.ts`, the port, `sendFeedback` and the type widening, with tests.
7. Change the methodology copy and its test.
8. Update the docs and the risks entry. Run `CI=true ./init.sh` and record the evidence.

## Implementation Tasks

- [ ] `config.DEFAULT_FEEDBACK_DATABASE_URL`, `feedback_database_url()`
- [ ] `feedback/message.py`
- [ ] `feedback/store.py`
- [ ] `feedback/rate_limit.py`
- [ ] `FeedbackIn` / `FeedbackAcceptedOut`, `feedback_router`, `create_app` lifespan and limiter
- [ ] `ideology feedback list [--since]`
- [ ] Python tests (5 new files plus the conftest, `test_public_api` and `test_web_client` edits)
- [ ] `feedback.ts`, `feedback-api.ts`, `sendFeedback`, `FetchLike` widening, index exports, Vitest tests
- [ ] Methodology `FEEDBACK_TEXT` and its test
- [ ] CONSTRAINTS, ARCHITECTURE, technical-discovery, README, risks entry, `.gitignore` comment

## Verification Plan

- `CI=true ./init.sh` passes: pytest, typecheck, Vitest and build.
- `.venv/bin/pytest tests/test_feedback_*.py tests/test_cli_feedback.py tests/test_public_api.py tests/test_web_client.py tests/test_migrations.py tests/test_committed_database.py -q`
- `npm test -w @ideology-app/core` and `npm test -w @ideology-app/web` (methodology).
- `git check-ignore feedback.db` prints `feedback.db`. `git status` shows no `migrations/versions/0014*` and no change to `data/ideology.db`.
- Optional manual smoke test with `FEEDBACK_DATABASE_URL` pointed at a scratch file: `curl -s -XPOST -H 'Content-Type: application/json' -d '{"message":"hola","origin":"landing"}' http://127.0.0.1:8000/api/v1/feedback` returns 201, then `ideology feedback list` shows it. With `FEEDBACK_DATABASE_URL=sqlite:///data/ideology.db`, uvicorn refuses to start.
- No E2E harness exists. Unit and integration tests through TestClient and the mocked `FetchLike` cover the API flow.
- Browser check: not applicable (API/CLI feature). The methodology copy is covered by its unit test, per the feature notes.

## Evidence To Capture

- The `CI=true ./init.sh` counts (pytest and Vitest), the test names for Scenarios 1–11, the refusal message output, and the `git check-ignore` result. Record them in `feature_list.json` `evidence` and `PROGRESS.md` (never `docs/validations/`).

## Validator Checklist

- [ ] All `verification` items of `feature_list.json` are met, and Decisions 1–11 are implemented as written. In particular, the code-point count, the explicit trim set, `\t` and `\r` refused, 8192 bytes → 413, 415, the 5/600 s and 120/600 s limits, the `website` honeypot and the read-only CLI.
- [ ] No row or log line holds an IP, UA, cookie, Election, Dataset Version, answers or the honeypot value. The main DB gets no statement during a POST.
- [ ] The shared DB head is still `0013`, `Base.metadata` has no feedback table, and `data/ideology.db` is unchanged.
- [ ] Server and client agree on every vector of Scenario 2.
- [ ] The CONSTRAINTS, ARCHITECTURE, README and technical-discovery docs and the risks entry are updated as listed. The risks entry is edited in place, not duplicated.
- [ ] No UI beyond the copy paragraph (no feedback button or dialog).
- [ ] `feature_list.json` and `PROGRESS.md` updated with evidence.
