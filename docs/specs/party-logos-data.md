# Feature Implementation Spec: Party logos stored locally and served by the app

## Source Feature

- `id`: party-logos-data
- `area`: data
- `depends_on`: public-dataset-api, source-text-bundle, shared-database (all `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`. Follow-up: `party-logos-display` (web) shows the logos. This feature changes nothing a Voter sees.

## Goal

A Party can have a logo. The logo bytes are stored in the database on the Party row and come from a file committed in the Source Text Bundle (`data/elections/<slug>/logos/<file>`), declared in `election.toml`, or from the Operator CLI. The app serves the bytes itself at a same-origin URL, and the public dataset API gives every Party a `logo_url` (or `null`), so the web client never loads an image from another origin (`CONSTRAINTS.md`, Web Client). The feature ends with the user's real 2023 logos imported into the committed `data/ideology.db`.

User decisions (2026-10-26, binding): logos are local files, never remote URLs. Files are named after the Party's `.md` file (`pp`, `psoe`, `vox`, `sumar`, `erc`, `junts`, `eh-bildu`, `eaj-pnv`, `bng`) with extension `.svg`, or `.png` when only a raster exists. A Party without a logo is valid. Logo licensing stays an open question owned by the user (see Risks).

## Non-Goals

- Any web UI: logo tiles, short-name placeholder, `alt`, fallback, `DESIGN.md` changes (`party-logos-display`). `RankedParty` and `BreakdownPosition` in `packages/core` do not get a logo field here.
- Remote logo URLs, image resizing/conversion/optimisation, JPEG or GIF, several logos per Party.
- Putting logos in the Dataset Version snapshot or in Pipeline Runs. A logo change never queues a run.
- A `party list` logo column, an upload API, or editing the user's logo files (if one is refused, report it to the user).
- Settling logo licensing.

## Job Story

When I prepare an Election's data,
I want to commit each Party's logo next to its manifesto text and import it with the rest of the bundle,
so every machine and the deployed app serve the same logos from our own origin, safely.

## Users And Permissions

- Operator: CLI only (`data import`, `data check`, `party logo`), no authentication, like the other commands.
- Voter: may fetch `GET /api/v1/parties/{id}/logo` (public, read-only, carries only the Party id and a hash).

## Decisions

- **Media types (by content, never by extension):** `image/png`, `image/webp`, `image/svg+xml`. WebP is kept, as the feature entry lists it: it is small, keeps transparency and has a cheap header check. JPEG is refused: no transparency (a white box on the neutral tile that `party-logos-display` must keep identical for all Parties), and any JPEG converts to PNG.
- **Size:** `MAX_LOGO_BYTES = 256 * 1024` (262144 bytes), checked with `stat` before reading. Empty files are refused.
- **Content checks** (`party_logos.check_logo(data) -> Logo`): PNG = 8-byte signature, first chunk `IHDR` of length 13 with width and height ≥ 1, last 12 bytes are the `IEND` chunk. WebP = `RIFF`, little-endian size equal to `len(data) - 8`, `WEBP`, first chunk `VP8 `/`VP8L`/`VP8X`. Anything else is tried as SVG: UTF-8 (a BOM is allowed), first non-space character `<`, no `<!ENTITY` and no DOCTYPE internal subset (`[`; an external `<!DOCTYPE svg PUBLIC …>` as Illustrator writes is allowed and never fetched), no `<?xml-stylesheet`, parsed with `xml.etree.ElementTree.fromstring`, root `{http://www.w3.org/2000/svg}svg`, no element with local name `script` or `foreignObject`, no attribute whose local name starts with `on` (case-insensitive), every `href`/`xlink:href` starts with `#` or `data:image/png`, `data:image/jpeg`, `data:image/gif`, `data:image/webp`. Otherwise `not a PNG, WebP or SVG image`. No new dependency (no defusedxml): the entity ban removes expansion attacks and the size cap bounds parsing.
- **SVG safety, two layers:** the content checks above, and the response headers below (the primary defence: a `<img>` never runs SVG script, and a directly opened logo is sandboxed with no script source).
- **Storage:** three nullable columns on `parties`: `logo` (`LargeBinary`, ORM `deferred=True` so no Party query loads the bytes unless asked), `logo_media_type` (`String(20)`), `logo_sha256` (`String(64)`, lowercase hex). All three are set or all null; enforced by the single writer `elections.set_party_logo`, not by a CHECK: adding a table CHECK on SQLite needs recreating `parties`, which `ON DELETE CASCADE` children reference (`CONSTRAINTS.md`, Data And Migrations).
- **Bundle is authoritative for its Parties:** `data import` makes each listed Party's logo equal to the manifest (no `logo` key clears an existing one). Parties not in the bundle are untouched. `party logo` on a Party whose Election has a committed bundle works but prints a warning that `data check` / `db check` will report it until `election.toml` declares the same file.
- **URL and caching:** `logo_url = "/api/v1/parties/{id}/logo?v=" + logo_sha256[:16]`. The route reads `v` from `request.query_params` (not a declared parameter): when `v` equals the stored prefix the response is `Cache-Control: public, max-age=31536000, immutable`; otherwise (missing or old `v`) the current bytes with `Cache-Control: no-cache`. The body never depends on `v`.
- **Consequence for `getDatasetVersion`:** its by-id body (cached `immutable`, 1 day) now changes when a logo changes, only in `logo_url`. Accepted: the stale URL still serves the current logo (`no-cache`). The Dataset Version rows are unchanged. Because browsers may hold a cached body without `logo_url`, the client treats a missing `logo_url` as `null`.

## Acceptance Scenarios

### Scenario 1: migration
Given an empty database, and separately a copy of `data/ideology.db` at `0012`
When `ideology db upgrade` runs
Then revision `0013` adds the three nullable columns with plain `ADD COLUMN` (`recreate='never'`), every existing row is kept (same counts for every table), `alembic check`/`compare_metadata` reports no drift, and downgrading a test DB to `0012` drops only the columns and keeps Parties, Source Documents and Party Positions.

### Scenario 2: bundle import with logos
Given a fixture bundle where PP declares `logo = "logos/pp.svg"`, PSOE declares `logo = "logos/psoe.png"` and a third Party has none
When `ideology data import DIR` runs twice
Then the first run stores bytes, media type and sha256 for PP and PSOE, leaves the third null and prints `Party PP (id P): logo set (logos/pp.svg, image/svg+xml, B bytes)`; the second run prints no logo line and changes nothing; all existing output lines are unchanged and no Pipeline Run is queued for a logo.

### Scenario 3: logo changed or removed in the bundle
Given an imported bundle
When `logos/pp.svg` bytes change, or PP's `logo` key is removed (and the file deleted), and `data import` runs
Then PP's logo is replaced (`logo replaced (…)`) or cleared (`Party PP (id P): logo removed`).

### Scenario 4: bad bundle logo, nothing written
Given a manifest whose logo is a JPEG, a 256 KiB + 1 byte PNG, an SVG with `<script>`/`onload`/`<!ENTITY`, a `.png` path holding SVG bytes, a path outside `logos/` or with `..`, a missing or symlinked file, a duplicate logo path, an unreferenced non-dot file in `logos/`, or a subdirectory in `logos/`
When `data import` or `data check` runs
Then `read_bundle` raises `BundleError` (`<file>:<line>: <problem>`), the CLI exits 1, and the database is byte-identical (nothing stored). Dotfiles in `logos/` (e.g. `.DS_Store`) are ignored.

### Scenario 5: data check / db check
Given an imported bundle
When a Party's stored logo differs (sha256 or media type, or stored bytes whose SHA-256 is not `logo_sha256`), is missing while declared, or is present while undeclared
Then `check_against_bundle` reports one problem each (`party PP (id P): logo differs from logos/pp.svg`, `… no logo, election.toml declares logos/pp.svg`, `… has a logo but election.toml declares none`); `data check` exits 1 and `db check` prints `Safe to commit: no`.

### Scenario 6: CLI set and clear
Given an Election N with Party `PP`
When `ideology party logo PP --election N --file F` runs
Then the file is checked first (any extension; content decides) and the Party's logo is set: `Set logo of party PP (id P): image/png, B bytes, sha256 <first 12 hex>`. `--clear` prints `Removed logo of party PP (id P)` or `Party PP (id P) has no logo; nothing changed`. Neither or both of `--file`/`--clear` → usage error exit 2. Unknown Election or short name → `Error: …` exit 1. An invalid file → `Error: <reason>` exit 1, nothing written. A not-initialised DB → the usual message.

### Scenario 7: serving
Given Party P with an SVG logo
When `GET /api/v1/parties/P/logo?v=<prefix>` is requested
Then `200`, body = stored bytes, `Content-Type: image/svg+xml` (no charset), `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox`, `Cross-Origin-Resource-Policy: same-origin`, `ETag: "<sha256[:32]>"`, `Cache-Control: public, max-age=31536000, immutable`; a matching `If-None-Match` gives `304` with the same headers and no body; without `v` or with another `v`, the same body with `Cache-Control: no-cache`. A Party with no logo → `404 {"error": {"code": "party_logo_not_found", "message": "party P has no logo"}}`; an unknown Party → `party_not_found` / `party P not found`; both `Cache-Control: no-store`. Ids outside `1..2147483647` → `422`. Non-GET → `405`. The route is in the `/api/v1` router, so it is registered before `web_router`; only SELECTs run.

### Scenario 8: public dataset API and client
Given a published Dataset Version whose Parties have and lack logos
When it is fetched by id and as published
Then each Party has keys `id, name, short_name, logo_url, positions` with `logo_url` the path above or `null`; both endpoints stay byte-identical; `packages/core` maps it to `Party.logoUrl: string | null`, accepts a missing key as `null`, and rejects any other value than `null` or a string matching `^/api/v1/parties/[1-9][0-9]*/logo\?v=[0-9a-f]{16}$` (`parties[i].logo_url must be …`).

### Scenario 9: Dataset Versions unchanged
Given a published Dataset Version
When a logo is set, replaced or cleared
Then no row of `dataset_versions`, `statements`, `party_positions` or `pipeline_runs` changes and no run is queued.

## Repository Research

### Files Inspected

- `feature_list.json`, `AGENTS.md`, `PROGRESS.md` (tail), `CONSTRAINTS.md`, `ARCHITECTURE.md`, `CONTEXT.md` (Party, Source Text Bundle), `DESIGN.md` (logo lines only), `docs/risks-and-open-questions.md`, `docs/technical-discovery.md` (shared-database runbook), `docs/specs/source-text-bundle.md` (format).
- `src/ideology_app/source_bundle.py` — `_read_manifest`, `_check_keys` (all keys required today; needs an optional `logo`), `_FILE_RE`, `read_bundle` (rglob for PDFs, top-level `.md` must be listed), `BundleParty`.
- `src/ideology_app/bundle_import.py` — `_plan` (all conflicts before writes), `import_bundle`, `PartyOutcome`, `check_against_bundle`.
- `src/ideology_app/models.py` (`Party`), `src/ideology_app/elections.py` (services, error classes), `migrations/versions/0012_…py` (hand-written `ADD COLUMN`, `recreate='never'`).
- `src/ideology_app/cli.py` — `party add|list`, `data import|check` output.
- `src/ideology_app/api/{routes,schemas,queries,http_cache}.py`, `main.py`, `web.py` (catch-all reserves `api/…`).
- `packages/core/src/domain/dataset-version.ts`, `packages/core/src/infrastructure/http/public-api-client.ts` (`parseParty`).
- Tests: `tests/test_public_api.py` (route set, no-query-param assertion, exact bodies, key order), `tests/test_migrations.py`, `tests/test_committed_database.py` (bundle check on the committed DB), `tests/bundle_factory.py`, `tests/test_source_bundle.py` (reads the committed bundle), `apps/web/src/test/fetch-mocks.ts`.
- `data/elections/es-general-2023-07-23/` (no `logos/` yet), `data/ideology.db` (Parties 1–9: PP 1, PSOE 2, VOX 3, SUMAR 4, ERC 5, JUNTS 6, EH Bildu 7, EAJ-PNV 8, BNG 9), `.gitattributes`.

### Existing Patterns To Follow

- Pure checker modules raising `InvalidInputError` subclasses (`source_bundle`); services take a `Session` and never commit; CLI resolves and validates before opening a write session.
- Migrations by hand with `op.batch_alter_table(..., recreate='never')`, plus tests for upgrade with rows, downgrade keeping child rows, offline PostgreSQL render (`0008`/`0009` tests).
- API: `ApiNotFoundError` → 404 JSON with `no-store`; `etag_for` / `if_none_match_matches` in `http_cache.py`.
- Manifest errors as `<file>:<line>: <problem>` through `_ManifestLines`.

### Current Gaps

- No binary column anywhere yet (`LargeBinary` → `BLOB` / `BYTEA`); no non-JSON API route; no route with a query string.
- `ARCHITECTURE.md` says migration head `0011` though `0012` exists; fix while editing that line.

## Technical Approach

1. **`src/ideology_app/party_logos.py` (new, pure, stdlib only + `elections.InvalidInputError`):** `MAX_LOGO_BYTES`, media-type constants, `EXTENSION_MEDIA_TYPES = {".png", ".webp", ".svg"}` mapping, `Logo(data, media_type, sha256)` (frozen), `InvalidLogoError(InvalidInputError)`, `check_logo(data)`, `read_logo_file(path)` (regular file, not a symlink, size via `stat` first), `logo_version(sha256) -> sha256[:16]`, `LogoChange` StrEnum `set|replaced|removed|unchanged|none`. Messages are short and name the problem (e.g. `logo is larger than 262144 bytes`, `SVG logo must not contain <script>`, `SVG logo has an external reference 'https://…'`).
2. **Model + migration `0013_party_logo.py`:** three columns as in Decisions, hand-written `ADD COLUMN`/`DROP COLUMN` with `recreate='never'` and a comment explaining why.
3. **`elections.py`:** `get_party_by_short_name(session, election_id, short_name)` (`NotFoundError`: `election N not found` / `party 'X' not found in election N`) and `set_party_logo(party, logo: Logo | None) -> LogoChange` (the only writer of the three columns; compares `logo_sha256` and media type).
4. **`source_bundle.py`:** optional party key `logo` (`_check_keys` gains an `optional` set), regex `^logos/[a-z0-9][a-z0-9._-]*\.(png|webp|svg)$`, unique across Parties. `read_bundle` reads each declared logo through `read_logo_file` (errors become `BundleError` with the manifest line or the logo file), checks the extension's media type equals the sniffed one, and checks `logos/` (if present: a directory; every non-dot entry is a regular file referenced by a Party). `BundleParty.logo: BundleLogo(file, logo) | None` (default `None`). Update the module docstring.
5. **`bundle_import.py`:** in the write loop call `set_party_logo(party, entry.logo.logo if entry.logo else None)`; `PartyOutcome` gains `logo_change` and `logo_file`. `check_against_bundle` adds the three logo problems of Scenario 5 (comparing `logo_sha256`, media type, and SHA-256 of the stored bytes; load the deferred column explicitly). `_plan` needs nothing new (logos are validated in `read_bundle`).
6. **CLI:** `data import` prints one extra line per `set`/`replaced`/`removed` after that Party's line; `party logo SHORT_NAME --election N (--file F | --clear)` as in Scenario 6, with the bundle warning on stderr (`Warning: election N has a committed bundle (SLUG); "data check" will report this logo until election.toml declares it`) when `source_bundle.bundle_slug(election)` is not `None`.
7. **API:** `queries.get_party_logo(session, party_id) -> (bytes, media_type, sha256)` (one SELECT of the three columns); route `GET /parties/{party_id}/logo` (`operation_id="getPartyLogo"`, `response_class=Response`, OpenAPI 200 content for the three image types, 304/404 documented); constants `LOGO_CACHE_CONTROL`, `LOGO_STALE_CACHE_CONTROL = "no-cache"`, `LOGO_CSP` and the header set in `http_cache.py`. `PartyOut.logo_url: str | None` between `short_name` and `positions`, built in `_version_out` from `logo_sha256` (no bytes loaded). Update the routes module docstring.
8. **`packages/core`:** `Party.logoUrl: string | null` (documented as a same-origin path), `parseParty` check per Scenario 8; update fixtures in `packages/core/test/**` and `apps/web/src/**` that build `Party` objects or API bodies.
9. **Repo data:** `.gitattributes` adds `data/elections/**/logos/** binary` (bytes must be identical on every machine, or `data check` fails).
10. **Import of the real logos (last step, only when the files exist):** see Implementation Plan step 6.

## Expected File Changes

- `src/ideology_app/party_logos.py` — create.
- `src/ideology_app/models.py`, `src/ideology_app/migrations/versions/0013_party_logo.py` — modify / create.
- `src/ideology_app/elections.py`, `source_bundle.py`, `bundle_import.py`, `cli.py` — modify.
- `src/ideology_app/api/{routes,schemas,queries,http_cache}.py` — modify.
- `packages/core/src/domain/dataset-version.ts`, `packages/core/src/infrastructure/http/public-api-client.ts` — modify; tests and fixtures in `packages/core/test/`, `apps/web/src/test/fetch-mocks.ts` and other `Party` fixtures — modify.
- Tests: `tests/test_party_logos.py` (create; fixture logos generated in code: a tiny PNG from `zlib` + `struct`, a minimal WebP header, SVG strings), `tests/test_source_bundle.py`, `tests/test_bundle_import.py`, `tests/test_cli_data.py`, `tests/test_cli.py` (party logo), `tests/test_migrations.py`, `tests/test_public_api.py`, `tests/bundle_factory.py` (`PartySpec.logo`, write `logos/`) — modify.
- `.gitattributes` — modify.
- Last step: `data/elections/es-general-2023-07-23/election.toml` (`logo` keys), `data/elections/es-general-2023-07-23/logos/*` (the user's files), `data/ideology.db` — modify/add.
- Docs listed below.

## Visual Design Impact

- UI involved: no. `logoUrl` reaches the client model but nothing renders it (`party-logos-display`). No browser check required (CLI/data feature).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update — `party_logos` module and dependency direction, `Party` columns and head `0013`, bundle `logos/` and `logo` key, `import_bundle`/`check_against_bundle`, CLI `party logo` and the import lines, the logo route in the Public API table (headers, cache rule), `PartyOut`/`Party.logoUrl` in the contract and client sections, the "Endpoints" line.
- `CONSTRAINTS.md`: update — add: Party logo bytes MUST enter only through `party_logos.check_logo` (PNG/WebP/SVG by content, ≤ 256 KiB, SVG without script, entities or external references) and MUST be served only by the logo route with `nosniff` and the sandbox CSP; the web client MUST use only the API's `logo_url`. Reason: SVG is active content.
- `AGENTS.md`: not needed.
- `CONTEXT.md`: update the Party entry (may have a logo, a local image imported from the bundle or set by the Operator) and the Source Text Bundle entry (optional `logos/`).
- `docs/technical-discovery.md`: update the shared-database runbook (logo import is a bundle write: same pull → write → `db check` → commit cycle).
- `README.md`: update the operator CLI list if it lists `party` commands.
- `docs/risks-and-open-questions.md`: edit the party-logos entry: SVG safety settled here (checks + headers); file origin settled (user-provided, committed under `logos/`); licence stays open (user); the by-id body changing with `logo_url` noted as accepted.

## Implementation Plan

1. `party_logos.py` with unit tests (every accepted and refused case of Decisions).
2. Model, migration `0013`, migration tests; `set_party_logo`, `get_party_by_short_name`.
3. Bundle reader, import, check, CLI (`data import` lines, `party logo`) with tests built from `bundle_factory` in `tmp_path`.
4. Logo route, `logo_url`, API tests; then `packages/core` contract and fixtures.
5. Docs; `CI=true ./init.sh` green. Manual check on a scratch copy: `cp data/ideology.db <scratch>/ideology.db`; `DATABASE_URL=sqlite:///<scratch>/ideology.db .venv/bin/ideology db upgrade`, then `db check` (with `ELECTIONS_DATA_DIR` pointing at the repo's `data/elections`), and compare row counts per table before/after.
6. **Real logos into the shared DB** (CONSTRAINTS.md Shared Database, nobody generating, DB freshly pulled): confirm the user's files are in `data/elections/es-general-2023-07-23/logos/`; add `logo = "logos/<name>.<ext>"` to each Party that has a file in `election.toml`; rehearse on a scratch copy (`db upgrade`, `data import`, `data check`); then from the repo root with `export DATABASE_URL=sqlite:///data/ideology.db`: `.venv/bin/ideology db upgrade`, `.venv/bin/ideology data import data/elections/es-general-2023-07-23` (expect `9 unchanged` documents, one `logo set` line per file, no queued run), `.venv/bin/ideology data check data/elections/es-general-2023-07-23`, `.venv/bin/ideology db check` → `Safe to commit: yes`. The logo files, `election.toml` and `data/ideology.db` must be committed together (`tests/test_committed_database.py` checks the bundle against the DB). If a file is refused, do not edit it and do not loosen the checks: report the exact error to the user. If no files exist yet, upgrade and commit the DB only, leave the feature `in_progress` and ask the user whether to wait or defer the import.

## Implementation Tasks

- [ ] `party_logos.py` + `tests/test_party_logos.py`.
- [ ] `Party` columns, `0013`, migration tests (empty DB, rows kept, downgrade keeps children, PostgreSQL offline render `BYTEA`, no drift).
- [ ] `set_party_logo`, `get_party_by_short_name`.
- [ ] Manifest `logo` key, `logos/` checks, `BundleParty.logo`; tests for every Scenario 4 case.
- [ ] Import, check and CLI output; `party logo` command; tests (Scenarios 2, 3, 5, 6, 9).
- [ ] Logo route + headers + `logo_url`; update route set, OpenAPI, exact-body and key-order tests (Scenarios 7, 8).
- [ ] `packages/core` `logoUrl` + contract tests + fixtures.
- [ ] `.gitattributes`, docs, risks entry.
- [ ] Scratch-copy rehearsal, then the shared-DB import and `db check`.

## Verification Plan

- `CI=true ./init.sh` passes (pytest with `filterwarnings = ["error"]`, Vitest, typecheck, build).
- Focused: `.venv/bin/pytest tests/test_party_logos.py tests/test_source_bundle.py tests/test_bundle_import.py tests/test_cli_data.py tests/test_cli.py tests/test_migrations.py tests/test_public_api.py tests/test_committed_database.py`; `npm test -- packages/core`.
- No test reads the real logo files or writes `data/ideology.db` (grep tests for `logos/` paths under `REPO_ROOT`; fixtures are generated in `tmp_path`).
- Scratch-copy upgrade and `db check` per Implementation Plan step 5; real import per step 6.
- Optional manual: start uvicorn on the shared DB and `curl -sI 'http://127.0.0.1:8000/api/v1/parties/1/logo?v=…'` to see the headers.
- E2E: no persistent browser E2E harness exists and nothing is rendered; API and contract tests cover the flow.

## Evidence To Capture

- `CI=true ./init.sh` counts (pytest, Vitest, build).
- Scratch-copy upgrade: row counts before/after, `db check` output.
- Shared-DB step: `data import` output (logo lines), `data check` and `db check` (`Safe to commit: yes`), which Parties have a logo and which do not.
- `curl -sI` headers of one SVG logo (optional).

## Validator Checklist

- [ ] Only PNG/WebP/SVG by content, ≤ 262144 bytes; SVG with script, event handlers, entities or external references refused; nothing stored on refusal.
- [ ] Migration `0013` is `ADD COLUMN` only, nullable, tested on empty DB and a copy of `data/ideology.db`; committed DB at head and `Safe to commit: yes`.
- [ ] `data import` idempotent with logos; `data check`/`db check` report logo divergences; `party logo --file/--clear` behave per Scenario 6.
- [ ] Logo route headers (nosniff, CSP with `sandbox` and `default-src 'none'`, CORP, ETag, immutable only with the current `v`), 404 JSON codes, registered before `web_router`.
- [ ] `logo_url` in both Dataset Version endpoints; `packages/core` maps `logoUrl`, tolerates a missing key, rejects other origins.
- [ ] Dataset Versions and runs untouched by logo changes; no run queued.
- [ ] Tests use generated fixture logos only; no test writes `data/ideology.db`.
- [ ] Docs and the risks entry updated; no UI change; `feature_list.json` and `PROGRESS.md` updated.

## As Implemented (2026-10-26, implementer)

- **Scope of this run:** everything except Implementation Plan step 6. By the user's instruction the real logo files are not in the repo yet, so `data/elections/es-general-2023-07-23/logos/` does not exist, `election.toml` has no `logo` keys, and `data/ideology.db` was neither upgraded nor modified (it stays at `0012`). Consequence: `tests/test_committed_database.py` fails 3 tests (`test_is_at_migration_head`, and the two that read `parties` through the ORM) until step 6 runs, so `./init.sh` stops at pytest on this branch. Step 6 was rehearsed on a scratch copy (see `feature_list.json` evidence).
- **SVG checks, slightly stricter than Decisions (same intent: "no external references"):** CSS `url(…)` targets (in `<style>`, `style` or any attribute value) follow the same rule as `href` (`#…` or the four `data:image/…` prefixes), `@import` is refused, and any attribute containing `javascript:` (whitespace ignored, e.g. in `<set to=…>`) is refused. Gradients (`fill="url(#g)"`) and Illustrator `<style>` classes still pass.
- **Bundle error locations:** a declared logo file that is missing is reported on the manifest's `logo` line; a refused file (content, size, symlink, extension/content mismatch) as `<bundle>/logos/<file>:1: <problem>`; `logos/` problems (unreferenced file, subdirectory, symlink, `logos` not a directory) as `<path>:1: <problem>`.
- **`party logo`:** setting the logo a Party already has prints `Party S (id P) already has this logo; nothing changed` (not specified). The bundle warning is printed only when the logo actually changed (set, replaced or removed).
- **Tests:** logo checks, bundle reader, import/check and CLI tests are in one new module `tests/test_party_logos.py` (fixtures from the new `tests/logo_factory.py`); API tests (Scenarios 7-9) are appended to `tests/test_public_api.py`; `tests/bundle_factory.py` gained `PartySpec.logo`. `tests/test_source_bundle.py`, `test_bundle_import.py`, `test_cli_data.py` and `test_cli.py` were not changed.
- **Step 6 with normalised logos (2026-10-26, user request):** the user's 9 files (PNG and WebP, 512x512 to 1562x1600) were normalised before being declared: transparent margins trimmed (alpha > 8), fitted without distortion into a 256x256 transparent PNG with 6% padding, centred, saved as optimised PNG; `bildu.png` and `pnv.png` renamed `eh-bildu.png` and `eaj-pnv.png`. Originals are kept outside the repo. This overrides the "image resizing/conversion" non-goal for this one import only, because the user asked for it; the checks were not loosened.
- **Route order check:** FastAPI wraps included routers, so "registered before `web_router`" is tested by behaviour (with a built web client, `/api/v1/parties/{id}/logo` still serves the image and its JSON 404s).
