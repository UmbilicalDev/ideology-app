# Feature Implementation Spec: Live mode periodically re-fetches URL sources

## Source Feature

- `id`: live-mode-url-refetch
- `area`: ingestion
- `depends_on`: live-mode-source-change-trigger (`accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json` (verification: "pytest with a mocked HTTP response and a controlled clock: changed content → new hash + run queued; same content → nothing"; notes: "The interval is configurable (e.g. 6h).")

## Goal

A new synchronous Operator command, `ideology source refetch [--election N]`, downloads again every current URL Source Document whose last check is older than a configured interval. If the bytes changed, it registers a **new** Source Document row for the same Party and URL, marks the old row as replaced, and calls the existing live trigger in the same transaction. In `live` that queues a Pipeline Run, or joins the one already queued. If the bytes did not change, only the check time is recorded. A failed download never touches the existing parsed document and never queues a run. Scheduling the command (cron or container) belongs to the first deployment feature.

## Decisions

- **A change is a new row; the old row is marked replaced.** `content_hash`, pages and stored files never change (`CONSTRAINTS.md`). Old Dataset Versions' Evidence points at the old row (`evidence_source_document_id`, `pipeline_run_source_documents`), so it must stay readable. The new row copies `party_id`, `origin=url`, `source_url` and `original_filename=_filename_from_url(url)`, and gets the new `content_hash`, its file `<hash>.pdf` and its pages. The old row gets `replaced_by_id = <new id>`. "Replaced" is a marker, not a new status: the status enum and CHECK stay as they are. The name `replaced` avoids clashing with the Dataset Version `superseded` status.
- **The pipeline reads only current documents.** `runs._parsed_documents_query` adds `SourceDocument.replaced_by_id IS NULL`, so `queue_run`'s "has parsed documents" check, `_start` and the trigger all see one version per URL lineage. Nothing else in `execute_run`, Validation or publishing changes.
- **The main manifesto stays main after a re-fetch.** Today `_start` makes each Party's lowest-id parsed document its `main` (joint) manifesto, and a replacement has a higher id. `_start` also loads `(id, replaced_by_id)` for every document of the Election's Parties and builds a predecessor map. Each current document gets a lineage root, the id of its first version. Documents are then ordered by `(party_id, root_id, id)` for role assignment and loading. Without replacements this is exactly today's order.
- **Where "last checked" lives.** New nullable column `source_documents.last_checked_at` (`DateTime(timezone=True)`). It is set to `now` on every check of a document: unchanged, changed, duplicate or failed. A failing site is therefore retried once per interval, not on every invocation. A replacement row starts with `last_checked_at = now`. A document is due when `(last_checked_at or created_at) <= now - interval`. Compare in Python and treat naive values from SQLite as UTC, as `api/queries.py` does.
- **Migration `0009` is needed.** It adds two nullable columns to `source_documents`, `replaced_by_id INTEGER` and `last_checked_at DATETIME`, using `op.batch_alter_table(..., recreate='never')` in both upgrade and downgrade (CONSTRAINTS: never recreate `source_documents`; `source_document_pages` cascades from it). `replaced_by_id` has **no FOREIGN KEY**: Alembic cannot add an FK column on SQLite without a table recreate. A throwaway check with alembic 1.20 and SQLite 3.53 raised `NotImplementedError` for the FK and succeeded for plain columns, with child rows kept. Integrity is kept by the service: it is set only by re-fetch, to a row of the same Party, in the same transaction. The model declares it without `ForeignKey` too, so the `compare_metadata` drift test stays empty. No backfill: null means "never checked" and "current".
- **Per-Party unique content hash (risk entry): kept.** `uq_source_documents_party_id_content_hash` stays. Dropping it would need a recreate. When the fetched hash differs from the current row's but equals *another* document of the same Party (the URL reverted to an earlier version, or the Operator uploaded the same file), the check records `last_checked_at`, writes no row or file, queues nothing, and reports `duplicate`. Known limitation: on a revert, the newer version stays current. This is recorded as an open risk with no owner. If the unique constraint is still hit in a race, the error is reported for that document only: its transaction rolls back and the command continues.
- **Interval config.** `SOURCE_REFETCH_INTERVAL_HOURS`: a positive integer, default `6`, parsed with the existing `_positive_int_env`. `config.source_refetch_interval() -> dt.timedelta`. An invalid value raises `ConfigError` (exit 1, nothing fetched). The variable uses whole hours rather than a `6h` string so it reuses the validated helper with no new parser. The command takes no `--force` flag. To force a check, set the variable to `1`.
- **Generation Mode: fetch in both modes, queue only in `live`.** The command never branches on mode. It calls `queue_run_for_source_change(session, new_document, generation_mode=mode, llm=llm)` and `QUEUE_ON_SOURCE_CHANGE` decides. Refusing in `precomputed` would need an `if mode == …` outside `triggers.py`, which `CONSTRAINTS.md` forbids. In `precomputed`, the replacement is read by the Operator's next `pipeline run`. Config is resolved before any fetch, exactly as `source add` does: interval, `generation_mode()`, and `llm_settings()` only if `queues_on_source_change(mode)`.
- **What is re-fetched.** Rows with `origin=url`, `status=parsed`, `replaced_by_id IS NULL` that are due, optionally only Parties of `--election N` (`NotFoundError` if unknown), in id order. `failed` URL rows are not retried; the Operator re-adds them with `source add --url`. The stored URL is passed through `_validate_url` again, and an invalid one counts as a failure. Elections are not filtered by status (nothing sets `archived` yet).
- **Failures.** A `FetchError`, a body without `%PDF-`, a `PdfTextError` (no text layer, encrypted, unreadable) or an invalid stored URL: extract pages **before** inserting anything, so no `failed` row, no file and no run is created. The only write is `last_checked_at`. The message goes to stderr. The command continues with the next document and exits 1 at the end.
- **URL allow-list / private-address block (risk entry): deferred, with a reason.** The command only re-fetches URLs that an Operator typed into `source add --url` and that passed `_validate_url`. It adds no new way for anyone else to supply a URL, and `http_fetch` still allows only http/https after redirects. The SSRF risk comes from untrusted URL input, which still does not exist. The entry is re-targeted to "before any web or admin surface accepts URLs (no such feature listed yet)".
- **Transactions and the clock.** One read session lists due ids. Then each document gets its own `session_scope`: re-load the row with `with_for_update()` (a no-op on SQLite), check that it is still current and due, fetch, compare, write, call the trigger, commit. One document's failure never rolls back another's. The fetch happens before any write in that transaction. `now` is injected: the service takes `now: dt.datetime`, and the CLI gets it from a new seam `cli._now()` (`dt.datetime.now(dt.UTC)`) that tests monkeypatch. Run one `source refetch` at a time; the unique constraint is the backstop.

## Non-Goals

- No worker, scheduler, cron entry, background thread or HTTP endpoint. No change to `main.py`, `api/`, `web.py`, `apps/web/` or `packages/`.
- No change to `pipeline/triggers.py` or coalescing, to `execute_run` beyond the input query and ordering in `_start`, or to Validation, publishing, prompts or `init.sh`.
- No host allow-list, no conditional GET (ETag / If-Modified-Since), no retry of `failed` rows, no `--force`, no deletion of replaced rows or files, no new dependency.

## Job Story

When a party quietly updates the manifesto PDF behind the URL I registered,
I want a periodic command to notice that the bytes changed and register the new version,
so that `live` mode regenerates from the current manifesto while old Dataset Versions keep their Evidence.

## Users And Permissions

- Operator (CLI only): runs `ideology source refetch`. Voters are unaffected: no request handler fetches, queues or executes anything.

## Acceptance Scenarios

All tests use temporary SQLite (`migrated_engine` / `db_url`), PDFs from `tests/pdf_factory.py`, `files_dir` / `SOURCE_FILES_DIR` in `tmp_path`, mocked HTTP (`fetch=` for service tests, `http_fetch._open` + `tests/http_fakes.py` for CLI tests), the autouse env/socket guard, `FakeProvider` only, no API key, and a fixed `now`.

1. **Changed content → new hash + run queued (live).** Given a parsed URL document D (hash H1) created at T0, `generation_mode=live`, and the URL now serving different text-PDF bytes (H2). When refetch runs at `T0 + 6h`, a new row N exists with `content_hash=H2`, `status=parsed`, the same `party_id` and `source_url`, its pages, and the file `<H2>.pdf`. D has `replaced_by_id=N`, unchanged hash and pages, its file still exists, and `last_checked_at=now`. Exactly one `queued` run exists, `FakeProvider.calls == []`. CLI output is `Source document D: replaced by source document N (P pages)` then `Queued pipeline run R for election E (generation mode live)`, exit 0.
2. **Same content → nothing.** Same setup, the URL serves the same bytes. There is no new row, no new file and no run. D is otherwise unchanged except `last_checked_at=now`. Output `Source document D: unchanged`, exit 0.
3. **Not due → not fetched.** At `T0 + 5h59m` with the default interval, the fetch stub is never called. Output is `No source documents due for re-fetch`, exit 0. At `T0 + 6h` it is fetched. After a check at T1, the next is due at `T1 + 6h`. `SOURCE_REFETCH_INTERVAL_HOURS=1` makes it due at `T0 + 1h`.
4. **Invalid interval.** `SOURCE_REFETCH_INTERVAL_HOURS` set to `0`, `-1`, `1.5` or `6h` exits 1 with `Invalid SOURCE_REFETCH_INTERVAL_HOURS …` and nothing is fetched or written. Unset or blank means 6.
5. **Failures keep the old document.** HTTP 404, a non-PDF body, and a blank (no text layer) PDF each leave: D current and `parsed` with the same pages and hash, no new row or file, no run, and `last_checked_at=now`. stderr has `Error: source document D: <reason>`. Other due documents are still processed. Exit 1 with `K of M source documents could not be re-fetched`.
6. **Duplicate hash.** D1 (H1) was replaced by D2 (H2), and the URL serves H1 again. No row, no run, D2 stays current. Output `Source document D2: content matches source document D1 of the same party; nothing changed`, exit 0.
7. **Coalescing and precomputed.** In live, two changed documents of the same Election give one `queued` run, and the second line is `Pipeline run R is already queued for election E`. In `precomputed`, a changed document is still replaced, no run is queued, and no queue line is printed. `GENERATION_MODE=live` with `LLM_PROVIDER=bogus` exits 1 before any fetch.
8. **Pipeline reads only current documents, roles stable.** A Party has URL document A (id 1, main) and upload B (id 2, additional). A is replaced by C (id 3). `execute_run` then records C as `main` and B as `additional`, and does not read A. `queue_run` still finds parsed input. A replaced document is never re-fetched again.
9. **Scope and atomicity.** `--election N` only fetches that Election's documents. An unknown election exits 1 with `election N not found`. Upload and `failed` documents are never fetched. If the trigger raises (monkeypatched `queue_run`), neither the replacement row nor `replaced_by_id` is committed.
10. **Migration 0009.** Upgrading from `0008` with existing documents and pages adds both nullable columns (values null), with no rows lost. Downgrade to `0008` drops them and keeps `source_document_pages` rows. Head is `0009`. The offline PostgreSQL render works, and `compare_metadata` drift is empty.

## Repository Research

### Files Inspected

- `src/ideology_app/source_documents.py`: `add_url_document`, `_validate_url`, `_store_and_parse`, `_store_file`, `_default_fetch`, `_filename_from_url`, the `fetch=` seam.
- `src/ideology_app/http_fetch.py`: `fetch_url`, `FetchError`, the `_open` seam.
- `src/ideology_app/pipeline/triggers.py`: `queue_run_for_source_change`, `SourceChangeOutcome`.
- `src/ideology_app/pipeline/runs.py`: `_parsed_documents_query`, `queue_run`, `_start` role assignment.
- `src/ideology_app/pipeline/positions.py`: role ordering (`_role_order`).
- `src/ideology_app/config.py`: `_positive_int_env`, `ConfigError`.
- `src/ideology_app/cli.py`: `source add/list`, `pipeline run-queued`.
- `src/ideology_app/models.py`: `SourceDocument`, `_enum` (non-native, CHECK).
- `src/ideology_app/migrations/versions/0002`, `0008`.
- `tests/http_fakes.py`, `tests/conftest.py`, the list of `tests/test_*`, `tests/test_migrations.py`.
- `AGENTS.md`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `docs/specs/live-mode-source-change-trigger.md`, `PROGRESS.md`.

### Existing Patterns To Follow

- Services take a `Session` and never commit; the CLI owns `session_scope`, resolves config first, and calls the trigger inside the same scope (`source add`).
- Batch error reporting is modelled on `pipeline run-queued`: `Error: …` on stderr per item, continue, then a final summary `ClickException`.
- Migrations: hand-reviewed autogenerate, `recreate='never'`, plus tests in `test_migrations.py` mirroring the `0008` tests.

### Current Gaps

- No "last checked" or "replaced" state on `source_documents`. No clock seam in the CLI. The pipeline reads every parsed document, and role is decided by raw id.

## Expected File Changes

- `src/ideology_app/migrations/versions/0009_source_document_refetch.py`: create.
- `src/ideology_app/models.py`: modify. Add `replaced_by_id: Mapped[int | None]` (`sa.Integer`, no FK) and `last_checked_at`.
- `src/ideology_app/config.py`: modify. Add `DEFAULT_SOURCE_REFETCH_INTERVAL_HOURS = 6` and `source_refetch_interval()`.
- `src/ideology_app/source_documents.py`: modify. Add:
  - `due_url_document_ids(session, *, now, interval, election_id=None) -> list[int]`;
  - `refetch_url_document(session, document_id, *, now, files_dir, fetch=None) -> RefetchOutcome`, a frozen dataclass with `document_id`, `result: RefetchResult` (`unchanged` | `replaced` | `duplicate` | `failed`), `replacement: SourceDocument | None`, `duplicate_of_id: int | None`, `reason: str | None`. It raises `InvalidInputError` if the row is not a current parsed URL document;
  - a small refactor so that pages are extracted before the replacement row is inserted, without changing `add_*` behaviour.
- `src/ideology_app/pipeline/runs.py`: modify. Add the `replaced_by_id IS NULL` filter and lineage-root ordering in `_start`.
- `src/ideology_app/cli.py`: modify. Add `_now()` and `source refetch [--election N]`. Append a `replaced_by` column to `source list`.
- `tests/test_source_refetch.py`: create (service scenarios 1–3, 5, 6, 9).
- `tests/test_cli_source_refetch.py`: create (CLI scenarios 1–7, mocked `_open`, patched `cli._now`).
- `tests/test_pipeline_runs.py`: add scenario 8.
- `tests/test_migrations.py`: modify. Change the head to `0009` and add the `0009` tests.
- `tests/test_config.py` or an existing config test module: add interval parsing tests. `tests/test_cli_source.py`: update the `source list` header.

## Visual Design Impact

- UI involved: no. The feature is CLI and data only, so browser validation does not apply (`AGENTS.md` exempts CLI, data and pipeline features).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Data Layer: the two columns, the replaced-row rule and migration head `0009`.
  - Config: `SOURCE_REFETCH_INTERVAL_HOURS`.
  - Pipeline: input is current documents only, and role uses the lineage root.
  - Runtime Surface: `source refetch` output and exit codes, and the `source list` `replaced_by` column.
- `CONSTRAINTS.md`: update (Source Documents). Add:
  - A changed URL document MUST become a new row; the old row only gets `replaced_by_id` and `last_checked_at`; hash, pages and file never change.
  - Pipeline input MUST be `replaced_by_id IS NULL` documents.
  - Re-fetch MUST NOT write a row, file or run on failure.
- `AGENTS.md`: not needed.
- `CONTEXT.md`: update. In Source Document, add: "a URL document whose content changed is replaced by a new one; the old one stays for the Evidence of older Dataset Versions".
- `docs/domain-model.md`: update.
  - Source Document lifecycle: add the `replaced` marker.
  - Run triggers: replace "will be re-fetched periodically" with the `source refetch` behaviour.
  - Coalition main: "first registered version".
- `docs/technical-discovery.md`: update the "URL re-fetch interval" row to `SOURCE_REFETCH_INTERVAL_HOURS` (default 6, applied by `ideology source refetch` in both modes; only `live` queues).
- `docs/risks-and-open-questions.md`: update in the same change.
  - "How often URL Source Documents are re-fetched…": mark it **Settled**, with the variable and command. Scheduling is deferred to the first deployment feature.
  - "Whether the per-Party unique content hash is right…": mark it **Settled**: kept, duplicate reported. Add an open item: a URL reverting to an earlier version is not applied (no owner).
  - "Which document is a coalition's joint manifesto": change to "lowest-id first version among current parsed documents".
  - "Fetching manifests by URL": allow-list **deferred** to whichever feature first accepts URLs from a web or admin surface. Reason: the re-fetch reuses only Operator-registered, re-validated URLs.
  - Add: run one `source refetch` at a time (the unique constraint is the backstop), and replaced rows and files are never deleted (storage grows per change).

## Implementation Plan

1. Write migration `0009`, the model columns and the migration tests.
2. Add the config interval and its tests.
3. Add the service functions `due_url_document_ids` and `refetch_url_document`, with service tests using `fetch=` and a fixed `now`.
4. Add the pipeline input filter and lineage ordering, with the runs test.
5. Add the CLI `source refetch`, the `_now` seam and the `source list` column, with CLI tests using mocked `_open`.
6. Update the docs listed above, then run `CI=true ./init.sh`.

## Implementation Tasks

- [ ] `0009` upgrade and downgrade with `recreate='never'`; head test plus a row-preservation test.
- [ ] `SourceDocument.replaced_by_id`, `last_checked_at`.
- [ ] `config.source_refetch_interval()` with `ConfigError` messages.
- [ ] `due_url_document_ids`: Python-side due comparison, naive values treated as UTC.
- [ ] `refetch_url_document`: validate the URL, fetch, check `%PDF-`, extract pages, compare the hash, check for a duplicate in the Party, insert the replacement and store the file, set `replaced_by_id` and `last_checked_at`.
- [ ] `_parsed_documents_query` filter, and `_start` root ordering.
- [ ] `cli source refetch`: config first, one session per document, trigger in the same scope, output lines as in the scenarios, summary exit 1 on failures.
- [ ] Docs and risks updates.

## Verification Plan

- `.venv/bin/pytest tests/test_source_refetch.py tests/test_cli_source_refetch.py tests/test_pipeline_runs.py tests/test_migrations.py -q`.
- `CI=true ./init.sh` passes, with alembic head `0009`.
- Manual smoke test, offline: `source refetch` on a fresh database with no URL documents prints `No source documents due for re-fetch`.
- No E2E: there is no browser-visible or API change.

## Evidence To Capture

- The pytest counts and the `init.sh` result. Name the tests for scenarios 1, 2, 5 and 8, which carry the verification line, in `feature_list.json` and `PROGRESS.md`.

## Validator Checklist

- [ ] Changed content creates a new row, sets `replaced_by_id` on the old one, and queues a run only in `live`. Same content writes only `last_checked_at`.
- [ ] Failures leave the old document untouched, with no row, file or run.
- [ ] The pipeline ignores replaced rows, and the `main` role survives replacement.
- [ ] There is no `if mode == …` outside `triggers.py`, no network or API key in tests, and the clock is injected.
- [ ] Migration `0009` is additive, the downgrade keeps pages, and drift is empty.
- [ ] Risks doc entries are settled or deferred as listed. `feature_list.json` and `PROGRESS.md` are updated.
