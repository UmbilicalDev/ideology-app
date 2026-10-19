# Feature Implementation Spec: Public API serves a Dataset Version

## Source Feature

- `id`: public-dataset-api (GitHub issue #27)
- `area`: api
- `depends_on`: auto-publish-dataset-version (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "pytest: the published version is returned; a superseded version is still returned by id; an unknown id → 404"; notes: "Read-only and cacheable. No voter data in requests.")

## Goal

The FastAPI app gets a small, read-only, cacheable JSON API under `/api/v1/`. Voter clients use it to list active Elections and load a Questionnaire with every Party's Positions and Evidence. A client can load the Election's Published Dataset Version, or any Published or Superseded version by id (old Share Links depend on this). The JSON contract is explicit and stable, so the React + TypeScript client (`packages/core` HTTP adapter, `web-client-skeleton`) can rely on it. The schema is published as OpenAPI.

## Decisions

- **Paths** (all `GET`, no query parameters, no request body):

  | Path | operationId | 200 body | Cache-Control on 200/304 |
  |---|---|---|---|
  | `/api/v1/elections` | `listElections` | `{"elections": [Election…]}`, only `active` Elections, ordered by `date` desc then `id` desc | `public, max-age=60` |
  | `/api/v1/elections/{election_id}` | `getElection` | `Election` (any status, `draft` too) | `public, max-age=60` |
  | `/api/v1/elections/{election_id}/published-dataset-version` | `getPublishedDatasetVersion` | `DatasetVersion` of the Election's Published version | `public, max-age=60` |
  | `/api/v1/dataset-versions/{dataset_version_id}` | `getDatasetVersion` | `DatasetVersion`, only if `published` or `superseded` | `public, max-age=86400, immutable` |

  OpenAPI moves from FastAPI's defaults to `/api/openapi.json` (docs UI at `/api/docs`, ReDoc off), so everything the API serves lives under `/api/`. `/health` is unchanged.
- **JSON contract (exact keys, snake_case).**
  - `Election` = `{"id", "country", "type", "date" ("YYYY-MM-DD"), "name", "status" ("draft"|"active"|"archived"), "published_dataset_version_id" (int or null)}`.
  - `DatasetVersion` = `{"id", "election_id", "created_at", "statements", "parties"}`:
    - `created_at` is UTC `YYYY-MM-DDTHH:MM:SSZ`. A naive value (SQLite) is read as UTC.
    - `statements` = `[{"id", "position", "text", "topic"}]`, ordered by `position`.
    - `parties` = `[{"id", "name", "short_name", "positions": [Position…]}]`. These are the Parties that have Party Positions in this version (not every current Party of the Election, so a Party added after the run does not appear), ordered by `id`. The order carries no meaning: `DESIGN.md` orders by score in the UI.
    - Each Party's `positions` has exactly one entry per Statement, ordered by Statement position: `{"statement_id", "value", "evidence"}`.
  - `Evidence` = `{"quote", "page", "url", "source_document_id"}`, or `null`. `quote` and `page` are exactly as stored. `url` is `evidence_url`: the Source Document's URL for URL documents, `null` for uploads. The client builds a link as `url + "#page=" + page`; the server does not compose links.
  - `Error` = `{"error": {"code", "message"}}`.
- **Party Position encoding (settles the risk entry naming this feature).** `value` is the JSON integer −2..+2 or the JSON string `"no_stance"`, taken from `PartyPosition.engine_value`, the single existing mapping. These are exactly the values `match-score.js` consumes, so the client does no value mapping. `evidence` is `null` exactly when `value` is `"no_stance"`. The only client-side mapping is key casing (`statement_id` → `statementId`, `id` → `partyId`), done once in the `packages/core` HTTP adapter (a later feature).
- **Immutable vs mutable data.** A `DatasetVersion` body contains only immutable data: its Statements, Positions and Evidence, plus Party names and the version's own fields. It has **no** `status` and no Published pointer. That lets it be cached as `immutable`. The mutable pointer lives only in `Election.published_dataset_version_id`. `share-link-open` detects a superseded version by comparing the Share Link's id with `GET /api/v1/elections/{election_id}`. The published endpoint returns the byte-identical body that the by-id endpoint returns for that version, so the ETag is the same; only Cache-Control differs.
- **Status codes.**
  - Unknown Election → `404 election_not_found`.
  - Known Election with no Published version (in practice `draft`) → `404 no_published_dataset_version`. The resource "the Published version" does not exist, and the distinct code lets the client show "no questionnaire yet". The choice is 404 rather than `200 null` or 204, so a client cannot mistake it for data.
  - Unknown Dataset Version id → `404 dataset_version_not_found`. A `candidate` version (never validated, or failed Validation) gets the same response, so it is indistinguishable from an unknown id and is never exposed.
  - Path ids are integers in `1..2147483647` (`Path(ge=1, le=2_147_483_647)`). Anything else (`abc`, `0`, `2**63`) → FastAPI's default `422`. Without the bound, an oversized int would make SQLite raise `OverflowError` → 500.
  - Unknown paths keep FastAPI's default `404 {"detail": "Not Found"}`.
- **Caching.**
  - Every 200 carries a strong `ETag`: `"` + the first 32 hex characters of the SHA-256 of the exact response bytes + `"`.
  - A request whose `If-None-Match` matches (comma list, `W/` prefix ignored as weak comparison requires, `*` matches) gets `304` with an empty body and the same `ETag` and `Cache-Control`.
  - Every `Error` 404 carries `Cache-Control: no-store`, because a 404 is heuristically cacheable by default, and an unknown id or a `candidate` version may become valid later.
  - Why these lifetimes:
    - Dataset Version bodies are immutable. One day, not one year, bounds the damage from a future serialisation fix or Party-name correction. Nothing updates Parties today.
    - The pointer endpoints (`elections`, `published-dataset-version`) may be 60 s stale after a publish. That is harmless: the old version stays valid and is pinned by id.
  - The values are module constants, not configuration. No `Vary` header (there is no content negotiation) and no compression.
- **No CORS middleware.** In production the FastAPI app serves the web build from the same origin. In development the Vite dev server proxies `/api` (`docs/technical-discovery.md`). Native mobile `fetch` is not subject to CORS. Adding CORS would only widen exposure.
- **No voter data.** The router declares only `GET` routes with path parameters. There is no endpoint that receives Answers (CONSTRAINTS.md, Client-side Matching). Unknown query strings are ignored and never logged by the app.

## Non-Goals

- No web pages, static mounting, SPA fallback, CORS, `HEAD`/`OPTIONS` handling, compression, rate limiting or CDN setup.
- No serving of stored Source Document PDFs, no Pipeline Run, Validation report or methodology data (provider, model, prompts) in the API.
- No change to the pipeline, Validation, publishing, models, migrations (head stays `0008`), CLI, `match-score.js` or `init.sh`.
- No TypeScript client or generated types (that is `web-client-skeleton` / `landing-election-picker`), and no archiving of Elections.

## Job Story

When a Voter opens the site or a Share Link,
I want the client to fetch the active Elections and the exact Dataset Version it needs, with every Party Position and its quote,
so I can answer the Questionnaire and see a reproducible, source-backed ranking without sending my Answers anywhere.

## Users And Permissions

- Voter / any client: anonymous, read-only `GET`. No authentication.
- Operator: unaffected (CLI only). No write path is exposed.

## Acceptance Scenarios

Test data:
- Seed Election 1 with `tests/pipeline_fixtures.seed_election`, publish through the real `execute_run` + `fake_provider()` path, and add a URL document via `add_parsed_document(..., source_url=...)` where needed.
- For exact-body tests, a small hand-seeded `published` version (ORM rows in the test only) is fine.

### Scenario 1: Active Elections are listed

Given Election 1 is `active` with Published version V1, and Election 2 is `draft`
When a client requests `GET /api/v1/elections`
Then the response is `200`, the body is exactly `{"elections": [{"id": 1, "country": "ES", "type": "general", "date": "2023-07-23", "name": "Generales 2023", "status": "active", "published_dataset_version_id": V1}]}`, and the response has an `ETag` and `Cache-Control: public, max-age=60`. Two active Elections are ordered by date desc.

### Scenario 2: One Election, including a draft

Given the same data
When a client requests `GET /api/v1/elections/1`, `/api/v1/elections/2` and `/api/v1/elections/999`
Then the first is the Election 1 object above. The second is `200` with `"status": "draft"` and `"published_dataset_version_id": null`. The third is `404` `{"error": {"code": "election_not_found", "message": "election 999 not found"}}` with `Cache-Control: no-store`.

### Scenario 3: The Published version is returned with Evidence

Given V1 has Statements and both Parties' Positions: some stances from an uploaded document, at least one from a URL document, and at least one `no stance`
When a client requests `GET /api/v1/elections/1/published-dataset-version`
Then the response is `200` and the body follows the contract:
- `id == V1` and `election_id == 1`;
- the Statements are in position order;
- each Party lists one Position per Statement, in position order;
- every stance has `value` in −2..2 (a JSON int, never a bool or string) and Evidence with the stored quote, page and `source_document_id`, with `url` `null` for the upload and equal to the document's `source_url` for the URL document;
- every `no stance` has `"value": "no_stance", "evidence": null`.

The body bytes equal `GET /api/v1/dataset-versions/{V1}`'s body, and both responses have the same `ETag`. The by-id response has `Cache-Control: public, max-age=86400, immutable`.

### Scenario 4: A superseded version is still returned by id

Given a second passing run publishes V2 and V1 becomes `superseded`
When a client requests the published endpoint, `GET /api/v1/dataset-versions/{V1}` and `GET /api/v1/elections/1`
Then the published endpoint returns V2. V1 returns `200` with a body byte-identical to the one before the supersede (same `ETag`). The Election's `published_dataset_version_id` is V2, and the list's and the published endpoint's `ETag`s changed.

### Scenario 5: Unknown, candidate and malformed ids

Given V1 is Published, and run 3 failed Validation with `candidate` version V3 (e.g. `fake_provider(generate_statements=statements_payload(20))`)
When a client requests `/api/v1/dataset-versions/999999`, `/api/v1/dataset-versions/{V3}`, `/api/v1/dataset-versions/abc`, `/0` and `/9223372036854775808`
Then the first two are `404` with code `dataset_version_not_found` and the same message shape (`dataset version N not found`), with `Cache-Control: no-store`. The last three are `422`, not 500.

### Scenario 6: Election with no Published version

Given Election 2 is `draft` with no Dataset Version (or only a `candidate`)
When a client requests `GET /api/v1/elections/2/published-dataset-version` and `GET /api/v1/elections/999/published-dataset-version`
Then the first is `404 {"error": {"code": "no_published_dataset_version", "message": "election 2 has no published dataset version"}}`, the second `404 election_not_found`, both `no-store`.

### Scenario 7: Conditional requests

Given any 200 response with ETag `E`
When the same request is repeated with `If-None-Match: E`, with `If-None-Match: W/E`, with `If-None-Match: "x", E`, or with `If-None-Match: *`
Then the response is `304` with an empty body and the same `ETag` and `Cache-Control`. A non-matching tag gives `200`.

### Scenario 8: Read-only, GET-only, no voter data

Given the app
When the routes are enumerated and a test records every SQL statement during all of the requests above (`before_cursor_execute` listener on the engine)
Then every `/api/` route allows only `GET` and has no query or body parameters, and every statement executed by the API is a `SELECT` (connection `PRAGMA`s excepted). Adding `?answers=…` to a request changes nothing in the response.

### Scenario 9: OpenAPI is exposed

Given the app
When a client requests `GET /api/openapi.json`
Then it is `200`. It lists the four paths with the operationIds above, each with its 200 response model and a 404 `Error` model. The Position `value` schema is an `anyOf` of an integer with `minimum -2` and `maximum 2` and the string constant `"no_stance"`. `GET /openapi.json` is `404`, and `GET /health` is still `200 {"status": "ok"}`.

## Repository Research

### Files Inspected

- `src/ideology_app/main.py`: `app = FastAPI(title="ideology-app")` with only `GET /health`; no DB access yet.
- `src/ideology_app/db.py`: `make_engine`, `session_scope`; callers own and dispose Engines.
- `src/ideology_app/models.py`:
  - `Election`, `Party`, `DatasetVersion` (status, partial unique Published index), `Statement` (position order);
  - `PartyPosition` (Evidence columns, `engine_value`, `NO_STANCE`);
  - `SourceDocument.source_url`.
- `src/ideology_app/pipeline/publishing.py`: `get_published_dataset_version(session, election_id)`, a read helper to reuse.
- `src/ideology_app/pipeline/runs.py`: `get_dataset_version` and `list_positions` (Operator helpers; they do not filter `candidate`, so the API does not use them).
- `src/ideology_app/static/js/match-score.js` and `ARCHITECTURE.md` (Client-side Matching): the engine expects `{ partyId, positions: [{ statementId, value: -2..2 | "no_stance" }] }`.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `CONTEXT.md`, `DESIGN.md` (party order rule), `docs/domain-model.md` (superseded versions stay readable), `docs/technical-discovery.md` (Clients, Deployment), `docs/risks-and-open-questions.md`.
- `tests/conftest.py` (`db_url`, `migrated_engine`), `tests/pipeline_fixtures.py` (`seed_election`, `add_parsed_document`, `fake_provider`, `statements_payload`, `offline_guard`), `tests/test_publishing.py`, `tests/test_health.py`.
- Installed: FastAPI 0.149.0, pydantic 2.14.1, Starlette 1.9.0, Python 3.15 (`.venv`). No new dependency is needed.

### Existing Patterns To Follow

- Plain service functions taking a `Session`; frozen/plain data out; an Engine is always disposed.
- Tests use temporary SQLite (`migrated_engine`), `FakeProvider` and the autouse `offline_guard`; `filterwarnings = ["error"]` makes leaked engines fail.
- `TestClient` is backed by `httpx2` (already a dev dependency).

### Current Gaps

- The app has no database wiring, lifespan or router, and there is no read model that excludes `candidate` versions.

## Technical Approach

1. **App factory.** `main.create_app(database_url: str | None = None) -> FastAPI`, with `openapi_url="/api/openapi.json"`, `docs_url="/api/docs"` and `redoc_url=None`. A lifespan creates `make_engine(database_url or config.database_url())` on `app.state.engine` and disposes it in `finally`. The app registers the `ApiNotFoundError` handler and includes the router. `app = create_app()` stays the uvicorn target, and `/health` stays as is (it needs no DB, so `TestClient(app)` without lifespan still works).
2. **`api/schemas.py`**: pydantic response models `ElectionOut`, `ElectionListOut`, `EvidenceOut`, `PositionOut` (`value: Annotated[int, Field(ge=-2, le=2, strict=True)] | Literal["no_stance"]`), `PartyOut`, `StatementOut`, `DatasetVersionOut`, `ErrorOut`. Field order equals the contract key order.
3. **`api/queries.py`** (SELECT only; imports `models` and `pipeline.publishing.get_published_dataset_version`, never `pipeline.runs` or `llm`):
   - `list_active_elections`, `get_election`, `get_published_version`, `get_public_version`;
   - a `PUBLIC_STATUSES = {published, superseded}` filter;
   - one query each for Statements, Positions (joined to Statements, ordered by position then party_id) and Parties (ids appearing in those Positions);
   - raises `ApiNotFoundError(code, message)`.
4. **`api/http_cache.py`**: `etag_for(body: bytes)`, `if_none_match_matches(header, etag)`, `cached_json(request, model, cache_control) -> Response` (serialises with `model.model_dump_json()`, returns 200 or 304), and the constants `POINTER_CACHE_CONTROL`, `IMMUTABLE_CACHE_CONTROL`, `ERROR_CACHE_CONTROL`.
5. **`api/routes.py`**: `APIRouter(prefix="/api/v1", tags=["public"])`, four sync `def` routes with `response_model`, `operation_id` and `responses={404: {"model": ErrorOut}, 304: {"description": "Not Modified"}}`. The dependency `get_session(request)` yields `Session(request.app.state.engine)` and closes it with no commit. Each route reads within one session, so the pointer and the content are consistent.

## Expected File Changes

- `src/ideology_app/main.py`: modify (factory, lifespan, OpenAPI URLs, handler, router).
- `src/ideology_app/api/__init__.py`, `schemas.py`, `queries.py`, `http_cache.py`, `routes.py`: create.
- `tests/test_public_api.py`: create (Scenarios 1–9; autouse `offline_guard`; `with TestClient(create_app(db_url)) as client`).
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`: update (below).
- `feature_list.json`, `PROGRESS.md`: evidence and status.

## Visual Design Impact

- UI involved: no. API only; the Browser Validation rule in `AGENTS.md` does not apply (no browser-visible change). `DESIGN.md` is not touched.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Data Layer: drop "The FastAPI app does not touch the database yet" and add `api` to the dependency direction (`db`/`models`/`pipeline.publishing` → `api` → `main`).
  - Add a "Public API" section: paths, contract, status codes, caching, OpenAPI at `/api/openapi.json`.
  - Runtime Surface: the new endpoints.
- `CONSTRAINTS.md`: add a "Public API" section:
  - `/api/` routes MUST be `GET`-only and read-only (SELECT only) and MUST NOT accept Answers.
  - They MUST NOT serve `candidate` versions.
  - A `DatasetVersion` body MUST NOT contain mutable fields (status, Published pointer), because it is cached `immutable`.
  - `value` MUST come from `PartyPosition.engine_value`.
  - `/api/v1` changes MUST be additive; a breaking change needs `/api/v2`.
- `AGENTS.md`: not needed (workflow unchanged).
- `docs/risks-and-open-questions.md`: update in this feature's change. The planner may write only the spec, so the implementer applies these edits:
  1. Replace the "Party Position encoding the browser expects (`public-dataset-api`)" entry with: "Settled (`public-dataset-api`): the API emits `value` as an integer −2..+2 or the string `"no_stance"` (from `PartyPosition.engine_value`), exactly what `match-score.js` consumes; `evidence` is `null` exactly when `value` is `"no_stance"`. JSON keys are snake_case; the `packages/core` HTTP adapter maps keys to camelCase once at load."
  2. Append to the "Shipping the web build (`web-client-skeleton`)" entry: "The API (`/api/v1/…`), its OpenAPI schema (`/api/openapi.json`) and docs (`/api/docs`) live under `/api/`; the SPA fallback must exclude `/api/` and `/health`."
  3. Add (Implementation-Time): "Evidence links for uploaded Source Documents (`results-breakdown-evidence`): the API gives `url` only for URL documents (link `url#page=N`); uploaded manifestos have no public URL or file endpoint, so their Evidence shows the page only. Decide whether to serve stored PDFs."
  4. Add (Implementation-Time): "Archived Elections (`landing-election-picker` or the feature that archives): `GET /api/v1/elections` lists only `active` Elections; `/api/v1/elections/{id}` and Dataset Versions by id still serve archived ones. Nothing sets `archived` yet."
  5. Add (Risks): "**Public API caching (`public-dataset-api`).** Dataset Version bodies are cached for one day as `immutable`, so a serialisation fix or Party-name correction reaches browsers that cached a version only after expiry; the Election list and Published pointer can be 60 s stale after a publish. A feature that lets Party or Election fields change must revisit this."
  6. Add (Accepted Low): "The public API on a database not migrated to head answers `500` (no `503` or initialisation check per request)."

## Implementation Plan

1. Schemas and queries, unit-tested through the API on seeded SQLite.
2. HTTP cache helper, app factory, router and error handler.
3. Tests for Scenarios 1–9, then the doc updates, `CI=true ./init.sh`, and a manual smoke test.

## Implementation Tasks

- [ ] `api/schemas.py` with the exact contract; `api/queries.py` with the public-status filter and ordering.
- [ ] `api/http_cache.py` (ETag, If-None-Match, 304, constants).
- [ ] `api/routes.py` and `main.create_app` (lifespan disposes the engine; OpenAPI under `/api/`).
- [ ] `tests/test_public_api.py`: exact bodies, headers, 304, 404/422, SELECT-only listener, GET-only route scan, OpenAPI shape.
- [ ] Update `ARCHITECTURE.md`, `CONSTRAINTS.md` and `docs/risks-and-open-questions.md` (edits 1–6).
- [ ] Record evidence in `feature_list.json` and `PROGRESS.md`.

## Verification Plan

- `CI=true ./init.sh` exits 0 (pytest, including `tests/test_public_api.py` and the unchanged `tests/test_health.py`; js-test unchanged; alembic head still `0008`).
- `.venv/bin/python -X dev -W error -m pytest tests/test_public_api.py` is clean: no `ResourceWarning`, the engine is disposed.
- Manual smoke test, outside the repo DB. A CLI `pipeline run` with `LLM_PROVIDER=fake` has no canned responses, so seed a scratch SQLite file with a throwaway script outside the repo that reuses `tests/pipeline_fixtures` (`seed_election` + `execute_run` with `fake_provider()`). Then run `DATABASE_URL=sqlite:///<scratch>/s.db .venv/bin/uvicorn ideology_app.main:app`, then `curl -i` each path, a 304 with `If-None-Match`, and a 404, and check `/api/openapi.json`.
- No E2E harness exists. The API flows are covered end to end in-process by `TestClient` against a migrated SQLite database, which is enough here.
- Browser validation: not applicable (no browser-visible change).
- `init.sh` is unchanged and still starts no server.

## Evidence To Capture

- pytest totals and the names of the Scenario 1–9 tests; the `-X dev -W error` run; the curl status lines and headers from the smoke test; confirmation that the risk-doc edits were made.

## Validator Checklist

- [ ] Only the files listed changed; no pipeline, Validation, publishing, model, migration or CLI change.
- [ ] Exact JSON bodies, status codes and headers match the Decisions, including 304, no-store on 404, and 422 for bad ids.
- [ ] `candidate` versions are never served; superseded versions are, byte-identically.
- [ ] `value` is only ints −2..2 or `"no_stance"`; Evidence is `null` iff no stance; the URL is present for URL documents.
- [ ] GET-only, SELECT-only, no query or body parameters, no CORS, no real LLM, network or API key in tests.
- [ ] OpenAPI at `/api/openapi.json` with stable operationIds.
- [ ] Docs and the risk entries updated; evidence recorded in `feature_list.json` and `PROGRESS.md`; no `docs/validations/`.
