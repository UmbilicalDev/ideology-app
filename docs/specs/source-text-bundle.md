# Feature Implementation Spec: Source Text Bundle (extract a PDF to Markdown, import an Election from a committed bundle)

## Source Feature

- `id`: source-text-bundle
- `area`: sources
- `depends_on`: source-document-upload, source-document-url (both `accepted`)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`. Sibling planned in parallel: `pipeline-checkpoint-shared` (depends on this feature; see "Shared contract").

## Goal

Several developers on several machines run Pipeline Runs. Today the manifestos exist only as PDFs (about 60 MB, VOX alone 30 MB) and as rows in a gitignored local SQLite DB, so no other machine can reproduce the sources. This feature commits a light text extraction of each manifesto, a **Source Text Bundle**, under `data/elections/<slug>/`. `ideology source extract` writes one Markdown file per Party manifesto with the page text exactly as `pdf_text.extract_pages` returns it. `ideology data import <dir>` builds the Election, its Parties and `parsed` Source Documents from the bundle in any database, idempotently. The real 2023 general election bundle (9 Parties) is committed as part of this feature. No PDF is committed.

User decisions (2026-10-21, binding): one Markdown file per Party manifesto with YAML front matter; the body is pypdf's page text, unchanged (no cleaning, no headings, no LLM rewriting), with each page under a `<!-- page N -->` marker; `source_url` is optional; no PDFs in git. Coalición Canaria (CCa) and Unión del Pueblo Navarro (UPN) are excluded from the bundle. Both hold one seat each, and the user excluded them for the same reason (user decision 2026-10-21), so the 2023 bundle has 9 Parties. pypdf: use the latest release, with a fixed pin only as a fallback (see Technical Approach, "pypdf version").

## Non-Goals

- Shared checkpoints and JSONL files (`pipeline-checkpoint-shared`; that spec no longer has auto-commit). This feature only fixes the directory and slug contract they use.
- Text cleaning or normalisation, OCR, other input formats, several files per Party (coalition member manifestos), and deleting Parties or documents that are missing from a bundle.
- Exporting existing DB rows to a bundle (`source extract` from the PDF is the only writer), serving stored PDFs, and changing Evidence rendering, the API or the web client.
- Changing the `source_document_origin` enum or the `source_url_matches_origin` CHECK (see Technical Approach: on SQLite it needs a forbidden table recreate).
- Running a Pipeline Run on the 2023 data (`e2e-real-2023-election`).

## Job Story

When I work on another machine, or start from a fresh database,
I want to pull the repo and import the committed manifesto texts with one command,
so my Pipeline Runs read exactly the same source text as everyone else's, without passing PDFs or databases around.

## Users And Permissions

- Operator / developer: CLI only, no authentication, as for the other `source` commands. `source extract` needs no database.
- Voter: not affected. Evidence of a bundle document with `source_url` links to `url#page=N` like a URL document. Without `source_url` it shows quote and page with no link, like an upload (`evidenceHref` returns `null`). Rendering is unchanged.

## File Format (normative)

A Source Text file is UTF-8 without a BOM. It is read and written as **bytes**: never text-mode universal newlines and never `str.splitlines()`. Only `"\n"` separates lines. `"\r"`, form feeds and Unicode line separators are page text. Layout:

```
---
bundle_format: 1
party: "PP"
source_url: "https://www.pp.es/.../programa.pdf"      <- line omitted when there is no URL
pdf_sha256: "c93b...3108"
page_count: 112
extractor: "pypdf <exact version>"
text_sha256: "<sha256 hex of the body bytes>"
---
<!-- page 1 -->
<page 1 text, escaped>
<!-- page 2 -->
...
```

- **Front matter**: exactly these keys, in this order, one per line, as `key: value`. A string value is `json.dumps(value, ensure_ascii=True)`, which is also a valid YAML double-quoted scalar. An integer is written in decimal. `pdf_sha256` and `text_sha256` are 64 lowercase hex characters. `page_count` is at least 1. `extractor` is `pdf_text.EXTRACTOR`.
- **Body** (every byte after the closing `---\n`): for each page N = 1..page_count, the marker line `<!-- page N -->\n`, then the page text with each `"\n"`-separated line escaped, then one `"\n"` terminator. An empty page is therefore one empty line. A text ending in `"\n"` leaves a blank line before the next marker.
- **Escaping**: a text line that matches `^\\*<!-- page` gets one extra leading `\`. When parsing, a line that starts with `<!-- page` must be exactly the next expected marker. Anything else (a wrong number, extra characters) is an error. A line that matches `^\\+<!-- page` loses one leading `\`. Every other line is taken verbatim.
- **Parse rule**: split the body on `"\n"`. The last element must be `""` (the file ends with the terminator). The first line must be `<!-- page 1 -->`. A page's text is its lines joined with `"\n"`.
- **Canonical check**: `parse` then `serialise` must give the input bytes exactly. Otherwise it fails with `not in canonical form (files are written by "ideology source extract", never edited)`. The check also requires: `text_sha256` equals the SHA-256 of the body, the number of markers equals `page_count`, at least one page has non-whitespace text, and the file is at most 50 MiB.
- Every error names `<file>:<line>: <problem>`.

**Manifest** `election.toml` (read with stdlib `tomllib`; written by hand). Exactly these keys:

```toml
format = 1
[election]
country = "ES"
type = "general"
date = 2023-07-23
name = "Elecciones generales 2023"
[[parties]]                       # one table per Party, in import order
short_name = "PP"
name = "Partido Popular"
file = "pp.md"
```

- The `election` values follow `elections.create_election` rules. `date` is a TOML date.
- `short_name`, `name` and `file` are unique within the manifest. `file` matches `^[a-z0-9][a-z0-9._-]*\.md$`, sits in the bundle directory, and its front-matter `party` equals `short_name`.
- Every top-level `*.md` file must be listed. Dotfiles and other top-level files are ignored. A `*.pdf` anywhere under the bundle is an error. Subdirectories (reserved: `checkpoints/`) are ignored.
- **Slug**: the bundle directory name must equal `election_slug(country, type, date)` = `f"{country.lower()}-{type}-{date.isoformat()}"`, e.g. `es-general-2023-07-23`.

## Acceptance Scenarios

### Scenario 1: Extract a PDF

Given a 3-page PDF from `tests/pdf_factory.py`: page 2 has no text, and page 3 has a line `<!-- page 2 -->` and a line `\<!-- page 9 -->`.
When `ideology source extract manifesto.pdf --party PP --url https://example.org/p.pdf --out pp.md` runs (no database needed)
Then it exits 0 and prints `Wrote pp.md: 3 pages, <n> bytes`. The file is canonical: `pdf_sha256` is the SHA-256 of the PDF bytes and `page_count` is 3. Page 2 is an empty line. Page 3's lines are written as `\<!-- page 2 -->` and `\\<!-- page 9 -->`. Parsing the file gives exactly `extract_pages(pdf bytes)`. Without `--url` the `source_url` line is absent.

### Scenario 2: Extract refuses bad input and writes nothing

Given a scanned (no text layer), encrypted, corrupt, non-PDF or empty file, an invalid `--url` (the same rules as `source add --url`), or an existing `--out` without `--force`
When `source extract` runs
Then it exits 1 with the existing reason (e.g. `no text layer found …`, `invalid URL …`, `… exists; pass --force to overwrite`), and no file is created or changed. The output is written atomically (temp file + `os.replace`).

### Scenario 3: The format round-trips byte for byte

Given page lists that include `""`, `"\n"`, `"a\n\n"`, `"\r\n"` lines, `"\x0c"`, `" "`, accents, a line `<!-- page 1 -->`, a line `\\<!-- page` and trailing spaces
When each list is serialised and parsed
Then `parse(serialise(x)).pages == x` and `serialise(parse(b)) == b`.

### Scenario 4: Import into an empty database

Given a migrated empty DB and a bundle `es-general-2023-07-23/` with 2 Parties: `pp.md` with `source_url` and `psoe.md` without
When `ideology data import data/elections/es-general-2023-07-23` runs
Then it exits 0. It creates the `draft` Election (natural key ES/general/2023-07-23) and the Parties in manifest order. For each file it creates a `parsed` Source Document:
- `origin` is `url` with that `source_url` (PP) or `upload` with null `source_url` (PSOE);
- `bundle_file` is the file name, which is also `original_filename`;
- `content_hash` is the SHA-256 of the `.md` bytes;
- `page_count` is set and the page rows equal the parsed pages;
- no file is stored under `SOURCE_FILES_DIR`.

It prints one line per Party (`Party PP: created (id 1); source document 1: added (3 pages)`) and a summary (`Imported election es-general-2023-07-23 (id 1): 2 added, 0 replaced, 0 unchanged`).

### Scenario 5: Re-import is a no-op

Given Scenario 4 has run
When the same import runs again, in `precomputed` or `live` mode
Then it exits 0 with `0 added, 0 replaced, 2 unchanged`. No row is inserted or updated, and no run is queued.

### Scenario 6: A changed file registers a replacement

Given Scenario 4, then `psoe.md` is re-extracted from a different PDF
When the import runs
Then a new `parsed` bundle row is created for PSOE, and the old row gets only `replaced_by_id` (its hash and pages never change). The output says `source document 3: replaces source document 2 (<n> pages)`. The next run reads only the new row, as PSOE's `main` (lineage root). With `GENERATION_MODE=live`, one run is queued for the Election in the same transaction (or an already queued one is joined) and the output prints the usual trigger line once. In `precomputed` nothing is queued.

### Scenario 7: Evidence without a URL

Given the Scenario 4 database and a FakeProvider run citing both documents
When the run finishes
Then PP's `evidence_url` is its `source_url` and PSOE's is null. `/api/v1` emits `url: null` for PSOE, so the web client shows the page with no link (unchanged behaviour).

### Scenario 8: Malformed input imports nothing

Given any one of these:
- `election.toml` is missing, invalid TOML, has a missing or unknown key, a bad country, type or date, or duplicate short names;
- a listed file is missing, or a top-level `.md` is not listed;
- the directory name does not match the slug;
- the bundle contains a `.pdf`;
- in a Source Text file: no front matter, an unknown, reordered or missing key, a bad JSON value, `party` not equal to the manifest `short_name`, a `page_count` mismatch, a `text_sha256` mismatch, a skipped or bad marker, an unescaped marker-like line, a missing final newline, invalid UTF-8 or a BOM, or no text on any page.

When `data import` runs, into an empty DB and into the Scenario 4 DB
Then it exits 1 with `Error: <file>:<line>: <problem>`, and the database is unchanged: no Election, Party, document or run rows are added or updated. The whole bundle is parsed and checked before the first write. The writes happen in one transaction, so a database-phase error rolls everything back.

### Scenario 9: Conflicts with the existing database are refused

Given an existing DB where any of these holds:
- the Election exists with another `name`;
- a manifest `short_name` exists with another `name`, or the name exists under another short name;
- a listed Party has a current `parsed` document without `bundle_file` (e.g. the old e2e DB with its `source add` rows);
- a file's bytes equal those of an older, replaced bundle row of that Party (a reverted file).

When `data import` runs
Then it exits 1 with a message that names the Party or Election, the document id and the fix (`import into a fresh database`). Nothing changes. Parties in the DB that are not in the manifest are left alone, with one line `Party UPN (id 10) is not in the bundle; left unchanged`.

### Scenario 10: Bundle documents are never re-fetched

Given a bundle document with `source_url` whose last check is long overdue
When `ideology source refetch` runs
Then the document is not due (`No source documents due for re-fetch`). Calling `refetch_url_document` on it raises `InvalidInputError` (`… was imported from a source text bundle; it is never re-fetched`). Its text changes only through a new committed file and `data import`.

### Scenario 11: The committed 2023 bundle

Given a fresh migrated DB
When `ideology data import data/elections/es-general-2023-07-23` runs
Then 9 Parties and 9 parsed documents exist. For every file, `pdf_sha256` equals the `content_hash` of the same Party's document in `/Users/miguel.garcia/Documents/Development/AiExpert/ideology-app-data/e2e-2023/ideology.db`, and the imported page texts equal that document's page rows exactly. `git ls-files 'data/**'` lists no PDF. A pytest checks that every committed bundle under `data/elections/` parses and passes the canonical check.

## Repository Research

### Files Inspected

- `AGENTS.md`, `CONTEXT.md`, `docs/domain-model.md`, `docs/risks-and-open-questions.md` (no entry names this feature; the SQLite recreate risk and the deferred stored-PDF entry are relevant), `CONSTRAINTS.md`, `ARCHITECTURE.md`, `PROGRESS.md`, `feature_list.json`, `.gitignore`, `pyproject.toml` (`requires-python >=3.12`, so `tomllib` is in the stdlib; `pypdf>=6.0` is unpinned).
- `src/ideology_app/pdf_text.py`, `source_documents.py` (`_read_pdf_file`, `_validate_url`, `_set_parsed_pages`, the refetch functions), `models.py` (`SourceDocument`, its CHECK `source_url_matches_origin`, `stored_filename` (unused elsewhere)), `elections.py`, `db.py`, `config.py`, `cli.py` (`source add|refetch|list|text`, `_echo_trigger`), `pipeline/runs.py` (`_parsed_documents_query`, `_lineage_roots`, `_start`), `pipeline/positions.py:169` (`url=cited.document.source_url`, which becomes `evidence_url` in `runs._finish`), `pipeline/generation.py` (chunks are ordered by `(party_id, document_id)`), `pipeline/triggers.py`, `migrations/versions/0003`, `0009`, `migrations/env.py`, `api/schemas.py` (`EvidenceOut.url` nullable), `packages/core/src/domain/breakdown.ts` (`evidenceHref`: `null` URL means no link).
- `docs/specs/source-document-upload.md`, `pipeline-run-checkpoint.md`, and `git show origin/feature/e2e-real-2023-election:docs/specs/e2e-real-2023-election.md`. That spec uses the same Party set (9 Parties, 348 seats; the CCa and UPN exclusion is the user decision recorded in Goal) and the same documents: the full PP and BNG programmes and EH Bildu's 16-page document.

### Planner Experiments (scratch venv outside the repo, `pypdf==6.21.1`, the version in the project `.venv`)

- The local data DB (read-only) holds Election 1 (ES/general/2023-07-23, "Elecciones generales 2023") and 10 Parties, including UPN (doc 1, 6 pages). Each has one `parsed` document: 8 `url` and 2 `upload` (PSOE doc 9, VOX doc 10). There are about 2.93 MB of UTF-8 page text in total.
- Extracting the 8 local PDFs (PP, PSOE, VOX, SUMAR, ERC, JUNTS, EH Bildu, EAJ-PNV; their SHA-256 equals the DB `content_hash`) gives page lists **identical** to the DB rows. BNG's PDF is not in `source_files/`. Downloading its recorded URL gave the same hash (`b8994dee…`) and identical text (68 pages).
- Across all DB pages: 16 empty pages, 46 pages that end with `"\n"`, no `"\r"`, no marker-like lines, no lone surrogates.

### Existing Patterns To Follow

- Services take a `Session` and never commit. The CLI owns `session_scope` and calls `queue_run_for_source_change` in the same transaction (`source add`, `source refetch`). Errors are `ElectionsError` subclasses, which become exit 1.
- Replacement follows the refetch rule: a new row, and the old row gets only `replaced_by_id`. `_lineage_roots` keeps it `main`.
- Migrations add columns with `batch_alter_table(..., recreate='never')` (`0009`). CHECK or enum changes on `source_documents` would recreate the table and cascade-delete pages and Party Positions (`CONSTRAINTS.md`).

### Current Gaps

- There is no `data/` directory, no bundle module, no `data` CLI group, no `source extract`, no way to mark a document as bundle-imported, and no `.gitattributes`.

## Technical Approach

- **Origin decision: reuse `upload`/`url`, plus a new nullable column `source_documents.bundle_file` (String 255).** A new origin value would need the enum CHECK and `source_url_matches_origin` rewritten. On SQLite that is a table recreate, and `CONSTRAINTS.md` forbids it (it cascade-deletes pages and Party Positions).
  - `origin` says where the manifesto lives: `url` when the file has `source_url` (Evidence links to it), else `upload`. Both existing CHECKs hold.
  - `bundle_file` (the `.md` name) marks the row as imported from a bundle.
  - `stored_filename` returns `None` for bundle rows: no PDF is stored.
- **Slug decision: derived from the natural key, no column.** `elections (country, type, date)` is already unique, and the manifest has the same fields. A slug that is a pure function of them maps a DB Election to its bundle with no migration, no backfill, and no stale value after a directory rename. It also works for Elections created with `election create` (e.g. the existing e2e DB). The import rejects a directory whose name is not that slug, so the mapping holds in both directions.
- **`content_hash` of a bundle row** is the SHA-256 of the whole `.md` file. Any change to the file (text, URL, extractor) is a replacement, and the per-Party unique hash makes "same file again" detectable. `pdf_sha256` stays in the file only.
- **Modules**:
  - `pdf_text.py`: adds `EXTRACTOR = f"pypdf {pypdf.__version__}"`. pypdf is still imported only here.
  - `source_bundle.py` (new; pure, no DB, no pypdf): `SourceText` (frozen: party, source_url, pdf_sha256, page_count, extractor, pages, content_hash), `serialise_source_text(...) -> bytes`, `parse_source_text(data, *, name) -> SourceText`, `Bundle`/`BundleParty`, `read_bundle(path) -> Bundle` (the full Scenario 8 check set), `election_slug(country, type, date)`, `election_slug_for(election)`, `bundle_dir_for(root, election) -> Path`, `bundle_slug(election, root=None)`. Errors: `BundleError(InvalidInputError)`.
  - `bundle_import.py` (new service): `import_bundle(session, bundle) -> ImportReport`. It finds or creates the Election by natural key, then each Party by short name (via `elections.create_election` / `add_party`). It applies the Scenario 9 checks and validates `source_url` with `source_documents._validate_url` (renamed public `validate_url`). For each file it then:
    - creates a bundle row when the Party has no current bundle row;
    - reports `unchanged` when the current row's `content_hash` matches;
    - otherwise inserts a replacement and sets the old row's `replaced_by_id`.

    Rows are created directly as `parsed` with pages (`_set_parsed_pages`). There is no `registered`/`fetched` step and no stored file. It returns per-Party outcomes and the list of new rows. It never commits.
- **Refetch**: `due_url_document_ids` and `_is_current_parsed_url` also require `bundle_file IS NULL`. `refetch_url_document` gives the Scenario 10 message for bundle rows.
- **CLI**:
  - `source extract PDF --party SHORT --out FILE [--url URL] [--force]`: no `requires_db`. It reuses `_read_pdf_file` checks and `extract_pages`, and writes atomically.
  - New group `data`, "Shared election data". `data import DIR` (`requires_db`) resolves `generation_mode()` / `llm_settings()` before any write, as `source add` does. It calls `read_bundle`, then in one `session_scope` it runs `import_bundle` and calls `queue_run_for_source_change` for every added or replacing row. It prints the Scenario 4/6/9 lines, with the trigger line deduplicated.
  - `source list` appends a `bundle_file` column.
- **Determinism**: on a fresh DB the import creates Parties and documents in manifest order. Ids, and therefore chunk order and prompt inputs, are the same on every machine. `pipeline-checkpoint-shared` relies on this.
- **Shared contract with `pipeline-checkpoint-shared`**:
  - `config.elections_data_dir()` returns `$ELECTIONS_DATA_DIR`, default `Path("data/elections")` relative to the current directory, like the DB default.
  - The bundle of an Election is `source_bundle.bundle_dir_for(config.elections_data_dir(), election)`.
  - `source_bundle.bundle_slug(election, root=None) -> str | None` returns the slug only when `<root>/<slug>/election.toml` exists (`root` `None` means `config.elections_data_dir()`). An Election with no committed bundle has no slug. This is the name the sibling spec uses.
  - `checkpoints/` inside it is ignored by the import.
- **Git hygiene**: `.gitattributes` gets `data/elections/**/*.md -text linguist-generated`, so there is no EOL conversion and GitHub collapses the diffs. `.gitignore` gets `data/**/*.pdf`.
- **2023 bundle**: `data/elections/es-general-2023-07-23/` with `election.toml` and 9 files, in DB id order: `pp.md`, `psoe.md`, `vox.md`, `sumar.md`, `erc.md`, `junts.md`, `eh-bildu.md`, `eaj-pnv.md`, `bng.md`.
  - Names and short names as in the e2e DB.
  - `source_url` from the DB for the 7 URL documents. PSOE and VOX have none.
  - UPN and CCa are excluded (user decision 2026-10-21, see Goal).
  - Produced with `source extract` from the PDFs in `.../e2e-2023/source_files/`. For BNG, download its recorded URL into a new empty scratch directory outside the repo first, and check the SHA-256 against `b8994deec0bbc45cdcbef5d7c5395cabf30b0509706303c3d8e76058c48eebfd`.
  - Extract with the pypdf version chosen in the next bullet. **STOP and ask** if a PDF hash differs from the DB `content_hash`.
- **pypdf version (user decision 2026-10-21: latest, pin only as a fallback)**:
  1. The implementer upgrades to the latest pypdf release.
  2. They re-extract the 9 committed 2023 PDFs with it and compare each page list with the stored DB text. "Works" means identical text; the planner checked 6.21.1, and it gives identical text.
  3. If it works, raise the `pyproject.toml` lower bound to that release (`pypdf>=X.Y.Z`).
  4. If it does not, pin `pypdf==` to the newest release that gives identical text. Record why in the `pyproject.toml` comment and in evidence: which document and page differ, and how.
  5. The `extractor` front-matter field records the exact version used.

  The committed `.md` files are the source of truth for page text. Import and Pipeline Runs never call pypdf on them, so the version only matters when someone re-extracts a PDF.

## Expected File Changes

- `src/ideology_app/pdf_text.py`, `models.py`, `config.py`, `source_documents.py`, `cli.py`: modify.
- `pyproject.toml`: modify; set the pypdf bound or the fallback pin (see "pypdf version").
- `src/ideology_app/source_bundle.py`, `bundle_import.py`, `migrations/versions/0011_source_document_bundle_file.py`: create.
- `data/elections/es-general-2023-07-23/{election.toml,*.md}`, `.gitattributes`: create. `.gitignore`: modify.
- `tests/test_source_bundle.py` (format, manifest, Scenarios 1–3, 8, and the committed-bundle check), `tests/test_bundle_import.py` (Scenarios 4–7, 9, 10, including a FakeProvider run), `tests/test_cli_data.py`: create. `tests/test_migrations.py` (head `0011`; downgrade with page rows keeps them), `tests/test_cli_source.py` (`list` header), `tests/test_source_refetch.py`: modify.

## Visual Design Impact

- UI involved: no. The API and client are unchanged. Evidence of a document without a URL already renders page-only (`evidenceHref` → `null`), and a URL document links as before. No browser validation is needed (CLI and data feature, exempt under `AGENTS.md`).

## Durable Documentation Impact

- `CONTEXT.md`: update.
  - Add a **Source Text Bundle** entry: the committed text of an Election's manifestos plus its manifest, imported with `ideology data import`.
  - Source Document: "registered as an uploaded file or a URL, or imported from a Source Text Bundle".
- `docs/domain-model.md`: update.
  - Source Document: an optional `bundle_file`; bundle rows are created `parsed` with no stored file; `content_hash` is the hash of the `.md` file; they are replaced by a re-import of a changed file and are never re-fetched.
  - Run triggers: an import that adds or replaces a document counts as "added / content changes".
- `ARCHITECTURE.md`: update. The modules, `bundle_file`, migration head `0011`, the `data/elections/<slug>/` layout, `ELECTIONS_DATA_DIR`, and the CLI.
- `CONSTRAINTS.md`: update with these rules:
  - Source Text files are written only by `source extract`, never edited, and read and written as bytes. Only `source_bundle` parses or serialises them.
  - No PDF under `data/`.
  - Bundle rows are never re-fetched, and are replaced only by import (same rule as the refetch replacement).
  - Tests build bundles in `tmp_path`, apart from the read-only check of the committed bundle.
- `docs/risks-and-open-questions.md`: add one short Risks entry, **Re-extracting a PDF with another pypdf version (`source-text-bundle`)**. The committed `.md` is the source of truth, so version drift only matters when someone runs `source extract` again. Different text in a committed file then replaces Source Documents on import and invalidates shared checkpoints. Mitigation: the `extractor` field, and comparing the diff before committing a re-extraction. If the fallback pin was needed, name the version and the reason. Otherwise this entry is not needed.
- `PROGRESS.md` (Operator CLI line), `feature_list.json` (this entry only): update. `AGENTS.md`: not needed.

## Implementation Plan

1. `source_bundle.py` with the format and manifest rules and their unit tests (Scenarios 3, 8). Add `pdf_text.EXTRACTOR`.
2. Migration `0011` (`bundle_file`, `recreate='never'`) and the model. `alembic check` must be clean.
3. `bundle_import.py`, the refetch exclusion, and their tests (Scenarios 4–7, 9, 10).
4. CLI `source extract`, `data import` and the `source list` column, with `CliRunner` tests (Scenarios 1, 2, 4–6, 8).
5. Upgrade pypdf and choose its version ("pypdf version"). Then produce and verify the 2023 bundle (Scenario 11), commit-ready. Add `.gitattributes` and `.gitignore`.
6. Docs and evidence.

## Implementation Tasks

- [ ] Serialiser, parser, canonical check, manifest reader, `election_slug`, `bundle_dir_for`, `bundle_slug` (tested with and without `election.toml`), `config.elections_data_dir`.
- [ ] Migration `0011` and model field. `stored_filename` returns `None` for bundle rows.
- [ ] `import_bundle` with created, unchanged, replaced and conflict paths. Refetch excludes bundle rows.
- [ ] CLI commands and output. Live trigger in the same transaction.
- [ ] 2023 bundle (9 files plus manifest), with a comparison script in the scratchpad (never in the repo).
- [ ] Docs, risk entry, evidence.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → passes. `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` → clean. `alembic check` on a scratch DB at head → no drift.
- Manual smoke in a scratch directory outside the repo:
  1. `db upgrade`, then `data import <repo>/data/elections/es-general-2023-07-23`.
  2. Re-run it (expect `0 added … 9 unchanged`).
  3. `source list` for one Party.
  4. Compare with the e2e DB, read-only: for each Party, pages equal and `pdf_sha256` equals `content_hash`.
  5. Run `GENERATION_MODE=live` on a second fresh DB: one queued run.
- `git ls-files data | grep -i '\.pdf$'` → empty. Record `du -sk data/elections/es-general-2023-07-23` and the per-file sizes (expected about 3 MB).
- E2E: there is no browser-visible change. `CliRunner` and service tests are the end-to-end coverage. Tests never call a real LLM (FakeProvider) and open no network.

## Evidence To Capture

- `init.sh` summary and pass count, `-X dev -W error` result, `alembic check`.
- The latest pypdf release tried, the version kept (`>=` bound or fallback `==` pin with its reason), and the per-document comparison with the DB text.
- Smoke transcript (commands, key lines, exit codes), the 9-Party equality table (pages, characters, hash match), bundle size, and that no PDF is tracked.

## Validator Checklist

- [ ] Scenarios 1–11 pass on re-run. The round-trip is byte-exact. Malformed bundles change nothing.
- [ ] The page text in the bundle equals the e2e DB rows. 9 Parties (no UPN, no CCa). No PDF in git.
- [ ] pypdf is the latest release with a `>=` bound, or a recorded fallback `==` pin. Every file's `extractor` names that exact version.
- [ ] No enum or CHECK change on `source_documents`. The migration uses `recreate='never'` and its downgrade keeps page rows. pypdf is imported only in `pdf_text.py`.
- [ ] Bundle rows are never re-fetched. Replacement leaves old rows intact. The live trigger runs in the import transaction.
- [ ] Docs above updated. `feature_list.json` (this entry) and `PROGRESS.md` hold real evidence. No `docs/validations/`.
