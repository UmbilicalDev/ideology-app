# Feature Implementation Spec: Register a Source Document by URL

## Source Feature

- `id`: source-document-url
- `area`: ingestion
- `depends_on`: source-document-upload (`accepted`)
- `status`: not_started
- `source`: `feature_list.json`

## Goal

An Operator registers a manifesto by URL from the `ideology` CLI. The app downloads the PDF once (Python stdlib `urllib`, no new dependency), then runs the same pipeline as an upload: SHA-256 content hash, content-addressed storage, pypdf page text, and a final `parsed` or `failed` state. If the download fails (HTTP error status, network error, timeout, or a response that is empty, too large or not a PDF), a `failed` row is committed with the reason and no content hash. The origin is chosen per document: `source add` takes either `--file` or `--url`. The URL is stored on the row (`source_url`), so later Evidence locators and `live-mode-url-refetch` can use it.

## Non-Goals

- Periodic or manual re-fetching, hash-change detection and run triggers (`live-mode-url-refetch`, `live-mode-source-change-trigger`). A row is never re-fetched or updated after this command finishes.
- HTML pages or formats other than PDF. Finding the PDF link inside a party web page. Following `<meta refresh>` links.
- Retries, authentication, cookies, custom headers, a configurable timeout, size limit or proxy settings beyond urllib's standard `*_PROXY` environment variables.
- A global `SOURCE_INGESTION` setting. The origin is chosen per document by the CLI flag.
- Deleting or retrying `failed` rows. HTTP endpoints or UI. Anything in `llm/` or `match-score-engine`. Changes to `init.sh`.

## Job Story

When a Party publishes its manifesto as a PDF on its website,
I want to register the link instead of downloading the file myself,
so the app keeps the exact bytes, their hash and the original URL, and tells me straight away if the link is broken.

## Users And Permissions

- Operator: CLI only, no authentication (as before). Voter: not affected.

## Acceptance Scenarios

Every scenario runs with HTTP mocked at `ideology_app.http_fetch._open`. No test opens a socket.

### Scenario 1: A URL with a text PDF is parsed

Given a migrated database with Election 1 and Party 1, and `https://example.org/docs/programa%202023.pdf` mocked to return 200 with a 2-page text PDF
When the Operator runs `ideology source add --party 1 --url https://example.org/docs/programa%202023.pdf`
Then the command exits 0 and prints `Created source document 1: parsed (2 pages)`. The row has origin `url`, status `parsed`, `source_url` equal to the URL as given, `original_filename` `programa 2023.pdf` (last path segment, percent-decoded), `page_count` 2, and `content_hash` equal to the SHA-256 of the response body. The two page rows hold the text (accents included), and `<files_dir>/<hash>.pdf` is byte-identical to the body.

### Scenario 2: An HTTP error ends in `failed`

Given the URL is mocked to raise `HTTPError` 404 `Not Found` (or 500)
When the Operator runs `source add --url ...`
Then a row is committed with origin `url`, status `failed`, the `source_url`, `failure_reason` `HTTP 404: Not Found`, and a null `content_hash`, `page_count` and `original_filename`. It has no pages and no file is stored. The command prints `Error: source document 1 failed: HTTP 404: Not Found` to stderr and exits 1. The `HTTPError` is closed, so there is no `ResourceWarning`.

### Scenario 3: Other download failures end in `failed`

Given the mock raises `URLError("Name or service not known")`, `TimeoutError`, `ConnectionResetError` or `http.client.IncompleteRead`, or it returns an empty body, a body over 50 MiB (by `Content-Length` or by bytes read), or a body that doesn't start with `%PDF-` (e.g. an HTML page)
When the Operator runs `source add --url ...`
Then the row is committed as in Scenario 2, with one of these reasons:
- `could not fetch URL: <detail>`
- `response is empty`
- `response is too large (more than 52428800 bytes)`
- `response is not a PDF (it does not start with %PDF-)`

No file is stored and the command exits 1.

### Scenario 4: A PDF that can't be parsed

Given the URL returns a blank 2-page PDF (or a corrupt or encrypted one)
When the Operator runs `source add --url ...`
Then the outcome matches upload Scenarios 2 and 3. The row is `failed` with the `pdf_text` reason, `content_hash` and `page_count`. The file is stored, and the command exits 1.

### Scenario 5: Input rejected before anything is fetched or written

Given a migrated database
When the Operator passes `--party 999`, or a URL that is not absolute `http`/`https` (`ftp://…`, `file:///etc/passwd`, `example.org/x.pdf`, `https://` with no host), contains whitespace or control characters (C0, DEL, C1) inside it, cannot be encoded as UTF-8 (e.g. an undecodable `\xff` argv byte), contains credentials (`https://user:pw@host/x.pdf`), or is longer than 2048 characters
Then the command exits 1 with `party 999 not found` or a message that starts with `invalid URL`. The fetch mock is never called, and no row or file is created.

Passing both `--file` and `--url`, or neither, exits 2 with `pass exactly one of --file or --url` and writes nothing.

### Scenario 6: The same content twice for one Party

Given Party 1 already has a Source Document (uploaded or from a URL) with hash H
When the Operator registers a URL whose body has hash H for Party 1
Then the command exits 1 with the existing `party 1 already has a source document with content hash H` message, and nothing is added. Registering it for Party 2 works and shares the stored file.

### Scenario 7: Listing, and an older schema

Given Scenarios 1 and 2 have run
When the Operator runs `source list --party 1`
Then the header is `id origin status pages content_hash filename url failure_reason`, and the `url` cell holds `source_url`. It is empty for uploads.

Given a database at revision `0002`
When the Operator runs any `source` command
Then it exits 1 with `Database is not initialised; run "ideology db upgrade".`

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json` (this entry, `source-document-upload`, `live-mode-url-refetch`, `match-score-engine`, and `pipeline-generate-statements`, which depends on this feature).
- `CONTEXT.md` (Source Document: upload or URL; Evidence locator: page and/or URL), `docs/domain-model.md` (lifecycle `registered` → `fetched` (URL downloaded) → `parsed` | `failed`), `docs/technical-discovery.md` (`SOURCE_INGESTION` row; "HTTP fetch for URL-based Source Documents"), `docs/risks-and-open-questions.md`, `docs/build-brief.md`.
- `docs/specs/source-document-upload.md`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `pyproject.toml`, `init.sh`.
- `src/ideology_app/{config,db,models,cli,source_documents,pdf_text}.py`, `migrations/env.py`, `migrations/versions/0002_source_documents.py`.
- `tests/{conftest,test_cli_source,test_migrations,test_llm}.py` (the socket guard is in `test_llm.py`).

### Throwaway Experiments

These ran in a scratch venv outside the repo (Python 3.15.0, SQLAlchemy 2.1.5, Alembic 1.20.0) against a copy of `src/`:

- The hand-written `0003` below works on SQLite (batch recreate). It keeps both enum CHECKs, the unique constraint, the FK and `ix_source_documents_party_id`. The new CHECK rejects `url` without `source_url` and `upload` with one. `downgrade 0002` restores the previous DDL.
- The offline PostgreSQL render is a plain `ADD COLUMN` plus one `ADD CONSTRAINT ck_source_documents_source_url_matches_origin`.
- With the model updated, `compare_metadata` gives `[]`. Autogenerate ignores CHECKs on existing tables, so the CHECK must be written by hand.
- A custom `OpenerDirector` with only the Proxy, Unknown, HTTP, HTTPS, HTTPDefaultError, HTTPRedirect and HTTPErrorProcessor handlers rejects `file:`, `ftp:` and `data:` with `URLError("unknown url type: …")`. A redirect to `file:` raises `HTTPError 302 … not allowed`.
- **On 3.15, an `HTTPError` that is never closed emits `ResourceWarning: Implicitly cleaning up <HTTPError …>`, even with `fp=None`.** The gate runs with `filterwarnings = ["error"]`. Production code must close it, and test fakes must build it with `io.BytesIO(b"")` and close it.

### Existing Patterns To Follow

- The service functions take a `Session`, don't commit, and reuse the `elections` error classes. `DuplicateError` comes from `IntegrityError` on `flush()`, followed by a rollback.
- A `failed` row is committed first and then reported as `ClickException`, giving exit 1 (`cli.source_add`).
- The adapter-module rule: `pdf_text.py` is the only module that imports pypdf. Apply the same idea here: `http_fetch.py` is the only module that does HTTP for Source Documents.
- The LLM tests' autouse socket guard (`socket.socket.connect` and `socket.create_connection` blocked).

### Current Gaps

- There is no URL column, fetch code or `--url` option.
- `is_initialised` checks tables only, so a database at `0002` would pass it and then crash on the new column.

## Technical Approach

- **`src/ideology_app/http_fetch.py`** (new, stdlib only):
  - Constants: `FETCH_TIMEOUT_SECONDS = 60`, `USER_AGENT = "ideology-app/0.1 (+manifesto fetch)"`.
  - `_OPENER`: an `OpenerDirector` with exactly the handlers listed above.
  - `_open(request, timeout)` returns `_OPENER.open(request, timeout=timeout)`. This is the single test seam.
  - `class FetchError(Exception)` has `.reason`, truncated to 500 characters.
  - `fetch_url(url: str, *, max_bytes: int) -> bytes` does the following:
    1. Builds a `Request` with a `User-Agent` from an ASCII-safe form of the URL: non-ASCII characters in the path, query and fragment are UTF-8 percent-encoded, existing `%XX` escapes and all other ASCII characters are kept, and a non-ASCII hostname is IDNA-encoded. The caller keeps and stores the URL as given (e.g. `https://example.org/programa-año.pdf` is requested as `.../programa-a%C3%B1o.pdf`, stored as given, filename `programa-año.pdf`).
    2. Inside `with _open(...) as response`, rejects early if `Content-Length` is a number greater than `max_bytes`, then reads in 1 MiB chunks until EOF and stops with the "too large" error once more than `max_bytes` have been read.
    3. Maps errors to reasons:
       - `HTTPError` → `HTTP {code}: {reason}`. Close it in a `finally`, and catch it before `URLError`.
       - `URLError` → `could not fetch URL: {exc.reason}`.
       - `http.client.HTTPException`, `TimeoutError` and other `OSError` → `could not fetch URL: {type}: {msg}`.
       - Any other `ValueError` (`UnicodeError`, `http.client.InvalidURL`, ...) → `could not fetch URL: {type}: {msg}`, so no urllib or http.client error escapes as a traceback.
       - An empty body → `response is empty`.
  - It does not check `%PDF-` (the service does, as it does for uploads).
- **Service** (`source_documents.py`):
  - `MAX_SOURCE_URL_LENGTH = 2048`.
  - `_validate_url(url) -> str`: strip it, then `urlsplit`. Lowercase scheme in `{http, https}`, `hostname` present, no `username`/`password`, no character `<= " "` or in `\x7f`–`\x9f` (C0, DEL, C1), the URL must encode as UTF-8 (no lone surrogates from undecodable argv bytes), and length ≤ 2048. Otherwise raise `InvalidInputError("invalid URL …: <why>")`.
  - Factor the tail of `add_uploaded_document` (store the file → `fetched`, extract → `parsed`/`failed`) into `_store_and_parse(document, data, files_dir)`. Upload behaviour must not change.
  - `add_url_document(session, *, party_id, url, files_dir, fetch=None) -> SourceDocument`, where `fetch` defaults to `lambda u: http_fetch.fetch_url(u, max_bytes=MAX_UPLOAD_BYTES)`:
    1. `_get_party`, then `_validate_url`. Nothing has been fetched yet.
    2. Call `fetch(url)`.
       - On `FetchError`, or when the body doesn't start with `%PDF-`, add a row with origin `url`, status `failed`, `source_url` and `failure_reason`, flush, and return it.
    3. Otherwise compute `content_hash`. `original_filename` is the percent-decoded last path segment, truncated to 255 characters, or `None`. Insert the row as `registered` with `source_url`, flush (an `IntegrityError` gives the rollback and `DuplicateError` from Scenario 6), then call `_store_and_parse`.
  - Rename nothing public. `MAX_UPLOAD_BYTES` also caps downloads.
- **Model and migration**:
  - `SourceDocument.source_url: Mapped[str | None] = mapped_column(sa.String(2048))`.
  - Add `sa.CheckConstraint("(origin = 'url' AND source_url IS NOT NULL) OR (origin = 'upload' AND source_url IS NULL)", name="source_url_matches_origin")` to `__table_args__`.
  - New `versions/0003_source_document_url.py` (`down_revision = "0002"`), written by hand: inside `op.batch_alter_table("source_documents")`, `add_column` plus `create_check_constraint(op.f("ck_source_documents_source_url_matches_origin"), <expr>)`. Downgrade reverses it (drop the constraint, then the column). The data needs no backfill: existing rows are all uploads, so they have a null URL.
- **`db.is_initialised`**: return true only when the database's current Alembic revision equals the script head, using `MigrationContext.get_current_revision()` and `ScriptDirectory.from_config(alembic_config()).get_current_head()`. This replaces the table list and makes Scenario 7 hold for every future migration.
- **CLI** (`cli.py`):
  - `source add`: `--file` is no longer required. Add `--url TEXT` ("Manifesto PDF URL to fetch").
  - In the body, exactly one of the two must be given, otherwise raise `click.UsageError("pass exactly one of --file or --url")`.
  - Dispatch to `add_uploaded_document` or `add_url_document` (`files_dir=config.source_files_dir()`). Reporting is unchanged: success line, or a failed row committed, then `ClickException`.
  - `source list` gets the `url` column after `filename`.

## Expected File Changes

- `src/ideology_app/http_fetch.py`: create.
- `src/ideology_app/migrations/versions/0003_source_document_url.py`: create.
- `src/ideology_app/source_documents.py`, `models.py`, `db.py`, `cli.py`: modify.
- `tests/http_fakes.py`: create. It provides `FakeResponse(body, headers=None)`, a context manager with `read(n)` and `headers`, and `http_error(code, reason)`, which builds an `HTTPError` with `fp=io.BytesIO(b"")`.
- `tests/test_http_fetch.py` and `tests/test_source_url.py` (service and CLI): create. Each has an autouse socket guard copied from `test_llm.py`.
- `tests/test_cli_source.py`: modify (the list header gains `url`; add `0002` to `test_requires_current_schema`). `tests/test_migrations.py`: modify (head is `0003`; `downgrade 0002` drops the column; CHECK violations; `is_initialised` is false at `0002`; the PG render has the new CHECK once).
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/technical-discovery.md`, `PROGRESS.md`, `feature_list.json` (this entry only): update.
- No change to `pyproject.toml` (no new dependency), `init.sh` or `llm/`.

## Visual Design Impact

- UI involved: **no**. This is CLI and data only, so the browser-validation rule does not apply. Design source: not applicable.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Add the `http_fetch` adapter: stdlib urllib, http/https only, 60 s timeout, 50 MiB cap, and `_open` as the test seam.
  - Add `add_url_document`, the `source_url` column with its CHECK, `is_initialised` = at head, and the `source add --file|--url` and `list` columns.
- `CONSTRAINTS.md`: update.
  - Only `http_fetch.py` fetches Source Document URLs, and it allows only http/https (no `file:`/`ftp:`/`data:`).
  - Every `HTTPError` must be closed.
  - Tests mock `http_fetch._open` and keep the socket guard. They never open a network connection.
- `docs/technical-discovery.md`: update.
  - `SOURCE_INGESTION` is a per-document CLI choice (`--file`/`--url`), not an environment variable.
  - The HTTP fetch uses stdlib `urllib`.
- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`: not needed. The lifecycle and terms are unchanged.

## Implementation Plan

1. Run `./init.sh` (baseline green).
2. Write `http_fetch.py`, `tests/http_fakes.py` and `test_http_fetch.py`.
3. Add the model column and CHECK, the hand-written `0003`, and `is_initialised` at head. Update `test_migrations.py` and confirm `alembic check` shows no drift.
4. Refactor `_store_and_parse`, add `_validate_url` and `add_url_document`, and write the service tests. The existing upload tests must still pass unchanged.
5. Update the CLI `--url`, the exclusivity check and the `list` column. Write the CLI tests and adjust `test_cli_source.py`.
6. Run the manual smoke against a local `http.server`, update the docs and record the evidence (status `passing`).

## Implementation Tasks

- [ ] `http_fetch.fetch_url`, `FetchError` and `_OPENER`. Tests:
  - 200 body returned.
  - 404 and 500 give `HTTP N: …`, with the error closed.
  - The `URLError`, timeout, `ConnectionResetError` and `IncompleteRead` reasons.
  - `Content-Length` over the limit, and a streamed body over the limit (use a small `max_bytes`).
  - Empty body.
  - `User-Agent` sent.
  - `_OPENER.open("file:///…")` → `URLError` (no socket).
  - Reason truncated to 500.
- [ ] `source_url`, the CHECK and `0003`. `is_initialised` at head. Migration tests.
- [ ] `_validate_url` (every rejected form in Scenario 5) and `add_url_document`. Service tests for Scenarios 1 to 6, including the fetch fake not called on invalid input, a session that is still usable after `DuplicateError`, and a shared file across Parties.
- [ ] CLI `--url`, the exactly-one rule (exit 2) and the `list` `url` column. `CliRunner` tests for Scenarios 1 to 7 with `_open` monkeypatched.
- [ ] Docs and evidence.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → `All checks passed.`, exit 0.
- `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` → clean, with no `ResourceWarning`.
- `alembic -c alembic.ini history` shows `0002 -> 0003 (head)`. `alembic check` on a scratch database at head reports no drift.
- `grep -rn "urllib.request\|http.client" src/` matches only `http_fetch.py`.
- Manual smoke in a scratch directory outside the repo, with `DATABASE_URL` and `SOURCE_FILES_DIR` set there:
  1. Write the fixture PDFs with `tests/pdf_factory.py` (text and blank) into `$SCRATCH/www/`.
  2. Run `.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory $SCRATCH/www` in the background. This is loopback only, for the manual check; it is never used in tests.
  3. Run `db upgrade`, then create an Election and two Parties.
  4. `--url http://127.0.0.1:8765/text.pdf` → parsed, exit 0.
  5. `/missing.pdf` → `HTTP 404: File not found`, exit 1 (row committed).
  6. `/blank.pdf` → no text layer, exit 1.
  7. A non-PDF file → not a PDF, exit 1.
  8. `ftp://x` → `invalid URL`, exit 1.
  9. Both flags → exit 2.
  10. Re-adding `text.pdf` → duplicate, exit 1.
  11. `source list` shows the `url` column. `shasum -a 256` of the stored file equals the listed hash.
  12. Port 1 (`http://127.0.0.1:1/x.pdf`) → `could not fetch URL: …`, exit 1.
  13. Stop the server and delete the scratch directory.
- `git status` shows no `*.db` or `source_files/` in the repo.
- E2E: there is no E2E harness and no HTTP or UI flow, so `CliRunner` with mocked `_open` is the end-to-end coverage.

## Evidence To Capture

- The `init.sh` summary and exit code, the pass count, and the `-X dev -W error` result.
- `alembic history` and `alembic check`, and the PG render CHECK count.
- The smoke transcript: commands, key output lines, exit codes and the hash comparison.

## Validator Checklist

- [ ] Only the listed files changed. No new dependency. No re-fetch or trigger code. `llm/` and match-score files untouched.
- [ ] Scenarios 1 to 7 pass through pytest and a fresh manual smoke. No test opens a socket (the guard is present).
- [ ] A `url` row always has `source_url` (DB CHECK). A failed download leaves `content_hash` null and no file. A parsed row's hash equals the SHA-256 of the stored `<hash>.pdf`.
- [ ] Only http/https URLs are fetched, including after redirects. `HTTPError` is closed, and `-X dev -W error` is clean.
- [ ] Upload behaviour is unchanged (existing tests pass apart from the `list` header).
- [ ] The docs match the code. Evidence is only in `feature_list.json` and `PROGRESS.md`. No `docs/validations/`.

## Open Questions And Risks

- A failed download leaves a `failed` row, and a retry adds a new row: there is no delete or retry command yet. This is acceptable for the MVP and is listed in `PROGRESS.md` as a known limitation.
- Some party sites block non-browser clients or serve the PDF from behind a JavaScript page. Those cases end in `failed` with the HTTP reason, and the Operator can fall back to `--file`.
- Migration id collision: `match-score-engine` is not expected to add a migration. If any other branch lands a `0003` first, renumber this one to the next free id and point `down_revision` at the new head before merging.
