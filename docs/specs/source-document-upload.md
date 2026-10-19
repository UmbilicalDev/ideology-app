# Feature Implementation Spec: Register a Source Document by file upload

## Source Feature

- `id`: source-document-upload
- `area`: ingestion
- `depends_on`: db-schema-elections-parties (`accepted`)
- `status`: not_started
- `source`: `feature_list.json`

## Goal

An Operator attaches a PDF manifesto to a Party from the `ideology` CLI. The app keeps the original file, records a SHA-256 content hash, and extracts the text of each page, so later Evidence can say which page a quote is on. If extraction works, the Source Document ends in `parsed`. If the PDF has no text layer (for example a scanned manifesto), or it can't be read, the Source Document ends in `failed` and the reason is stored. There is no OCR. This feature adds the `source_documents` and `source_document_pages` tables that `source-document-url` and the pipeline features build on.

## Non-Goals

- Registering a Source Document by URL, or HTTP fetching (`source-document-url`). The `url` origin value exists in the enum, but no code path creates it.
- OCR, file formats other than PDF, layout or column reconstruction, and text normalisation for quote matching (that belongs to `validation-evidence-quotes`).
- Re-parsing, replacing, deleting or editing Source Documents. Marking a "main" Source Document for a coalition.
- Queuing Pipeline Runs on upload (`live-mode-source-change-trigger`), and any `GENERATION_MODE` handling.
- HTTP endpoints, an admin page or authentication. Object storage. Anything in the LLM provider area (`llm-provider-abstraction` is being built in parallel; don't touch it).
- Changes to `init.sh`.

## Job Story

When I have a Party's manifesto as a PDF,
I want to attach it to that Party and see straight away whether its text could be extracted,
so the next Pipeline Run can quote it page by page, or I know to find a text-based version.

## Users And Permissions

- Operator: has CLI-only access with no authentication, as in `db-schema-elections-parties`.
- Voter: not affected.

## Acceptance Scenarios

### Scenario 1: A text PDF is parsed

Given a migrated database with Election 1 and Party 1, and a 2-page PDF with text on both pages
When the Operator runs `ideology source add --party 1 --file manifesto.pdf`
Then the command exits 0 and prints `Created source document 1: parsed (2 pages)`. The row has origin `upload`, status `parsed`, `original_filename` `manifesto.pdf`, `page_count` 2, a `content_hash` equal to the lowercase hex SHA-256 of the file bytes, and no `failure_reason`. There are two page rows (page_number 1 and 2) with each page's extracted text, accents included (e.g. `mínimo`). The file is stored as `<files_dir>/<content_hash>.pdf` with identical bytes.

### Scenario 2: A PDF with no text layer fails

Given the same setup and a valid PDF whose pages have no extractable text (blank or image-only)
When the Operator runs `source add` with it
Then the row is committed with status `failed`, `failure_reason` = `no text layer found (scanned PDF?); OCR is not supported`, its `content_hash` and `page_count`, and no page rows. The command prints `Error: source document <id> failed: <reason>` to stderr and exits 1. The file is still stored, because the content hash identifies it.

### Scenario 3: Unreadable or encrypted PDF fails

Given a file that starts with `%PDF-` but is truncated or corrupt, or a PDF encrypted with a non-empty user password
When the Operator runs `source add`
Then the row ends `failed` with a reason that starts with `could not read PDF:` or is `PDF is encrypted`, and the command exits 1 as in Scenario 2. A PDF encrypted with an empty user password is read normally (pypdf decrypts it automatically).

### Scenario 4: Input rejected before anything is written

Given a migrated database
When the Operator passes a party id that doesn't exist (`--party 999`), a path that doesn't exist, an empty file, a file that doesn't start with `%PDF-` (e.g. a `.txt` renamed to `.pdf`), or a file over 50 MiB
Then the command exits non-zero (1 for service errors with `party 999 not found` or a message naming the file problem; 2 for click's missing-path error), and no row or stored file is created.

### Scenario 5: The same file twice for the same Party

Given Party 1 already has a Source Document with hash H
When the Operator uploads a file with the same bytes to Party 1
Then the command exits 1 with `Error: party 1 already has a source document with content hash H` and nothing changes. Uploading the same file to a different Party works, and both rows share the one stored file.

### Scenario 6: Listing and reading back

Given Scenarios 1 and 2 have run
When the Operator runs `ideology source list --party 1` and `ideology source text --document 1 [--page 2]`
Then `list` prints a tab-separated table with the header `id origin status pages content_hash filename failure_reason`, in id order (empty cells for nulls). `text` prints each page as `--- page N ---` followed by its text, or only page N when `--page` is given. An unknown document or page exits 1 with a "not found" message.

### Scenario 7: Database not at the new schema

Given a database migrated only to `0001`, or not migrated at all
When the Operator runs any `source` command
Then it exits 1 with the existing `Database is not initialised; run "ideology db upgrade".` message and no traceback.

## Repository Research

### Files Inspected

- `AGENTS.md`, `PROGRESS.md`, `feature_list.json`: the feature entry, the next-feature notes and the deferred Low findings.
- `CONTEXT.md`, `docs/domain-model.md`: Source Document (belongs to a Party in an Election; origin `upload`/`url`; text plus page mapping; content hash; lifecycle `registered` → `fetched` → `parsed` | `failed`), and Evidence (quote plus page locator).
- `docs/technical-discovery.md`: files on local disk or object storage; it suggests PyMuPDF and says OCR is out of scope. `docs/risks-and-open-questions.md`: scanned manifestos are an edge case, and OCR is "Later".
- `docs/specs/db-schema-elections-parties.md`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `pyproject.toml`, `.gitignore`, `init.sh`.
- `src/ideology_app/{config,db,models,elections,cli}.py`, `migrations/versions/0001_elections_parties.py`, `tests/conftest.py`.
- This worktree has no `.venv`. The main checkout's `.venv` (Python 3.15.0) was only inspected (`pip list`) and used for a `pip download` into a scratch directory. Nothing was installed into it.

### Throwaway-Venv Findings (Python 3.15.0, scratch venv outside the repo)

- `pypdf` 6.21.1: a pure-Python wheel (`py3-none-any`), `Requires-Python >=3.9`, a 3.15 classifier, no required dependencies, BSD-3-Clause licence. It installs and imports, and `-X dev -W error` is clean.
- Page text from a hand-built PDF using Helvetica with WinAnsiEncoding: `['Programa electoral\nSubir el salario mínimo por encima de la inflación.', 'Página dos: educación pública (gratuita).']`. Accents survive.
- Blank pages and pages with only drawn shapes extract as `''`. `PdfWriter().add_blank_page(612, 792)` gives a valid PDF with no text.
- `b"not a pdf"` and truncated files raise `PdfStreamError`, and `b""` raises `EmptyFileError`. Both subclass `pypdf.errors.PdfReadError`. pypdf also writes messages such as `EOF marker not found` through `logging`, not `warnings`.
- A password-encrypted PDF raises `FileNotDecryptedError` (a `PdfReadError`) when its text is extracted. With an empty user password, pypdf decrypts it automatically. AES-encrypted files need the optional `cryptography` package and otherwise raise `pypdf.errors.DependencyError`, which is **not** a `PdfReadError`.
- PyMuPDF was not evaluated: it ships compiled wheels (a 3.15 risk) and is AGPL-licensed.

### Existing Patterns To Follow

- The service is plain functions that take a `Session`, with no commit inside. The errors `InvalidInputError`, `NotFoundError` and `DuplicateError` come from `ideology_app.elections`, and duplicates are detected from `IntegrityError` on `flush()`.
- In the CLI, `requires_db` maps `ElectionsError` to `ClickException` (exit 1). Tables are tab-separated with a header. Engines are disposed through `call_on_close`.
- Models: the naming convention plus non-native enums with `length=20` and a single CHECK each. Migrations are autogenerated and then reviewed by hand (remove the duplicate `sa.CheckConstraint` lines).
- In tests, `conftest.py` changes into `tmp_path` and unsets `DATABASE_URL`. Use the `db_url`, `migrated_engine` and `session` fixtures.

### Current Gaps

- There is no PDF dependency, no file-storage location, and no Source Document tables or commands.
- `is_initialised` only checks `alembic_version` and `elections`, so a database at `0001` would pass it.

## Technical Approach

- **Dependency**: add `pypdf>=6.0` to `[project].dependencies`. No extras (no `cryptography`).
- **Config** (`config.py`): `source_files_dir() -> Path` returns `$SOURCE_FILES_DIR` if it is set, otherwise `Path("source_files")`, relative to the current directory like the default database. Add `source_files/` to `.gitignore`.
- **PDF extraction** (`src/ideology_app/pdf_text.py`, the only module that imports pypdf):
  - `extract_pages(data: bytes) -> list[str]` returns one string per page, 1:1 with page order, with `\x00` removed from each (PostgreSQL `text` rejects NUL).
  - It raises `PdfTextError(reason, page_count: int | None)` (`page_count` is set when the page tree was read) with these reasons:
    - `PDF is encrypted` for `FileNotDecryptedError` and `DependencyError`, or when `reader.is_encrypted` is true and decryption with `""` fails.
    - `could not read PDF: <ExcType>: <msg>` for any other exception from pypdf, truncated to 500 characters. Catching `Exception` is deliberate here: malformed PDFs raise assorted errors.
    - `PDF has no pages`.
    - `no text layer found (scanned PDF?); OCR is not supported` when every page is empty after `.strip()`.
  - Pages with no text inside a document that has text elsewhere stay as `""`, which keeps the page mapping.
  - Silence pypdf's log noise: `logging.getLogger("pypdf").setLevel(logging.ERROR)` at module import.
- **Models** (`models.py`):
  - `SourceDocumentOrigin(StrEnum)`: `upload`, `url`. `SourceDocumentStatus(StrEnum)`: `registered`, `fetched`, `parsed`, `failed`. Both use `_enum(...)` with the names `source_document_origin` and `source_document_status`.
  - `SourceDocument` (`source_documents`):
    - Columns: `id`; `party_id` FK `parties.id` `ON DELETE CASCADE`, not null, indexed; `origin` and `status` (not null); `original_filename` String(255), nullable; `content_hash` String(64), nullable (null only before fetch, for the URL feature); `page_count` Integer, nullable; `failure_reason` String(500), nullable; `created_at` DateTime(timezone=True), not null, Python-side default `datetime.now(UTC)`.
    - Unique `(party_id, content_hash)`. NULLs are distinct on both databases.
    - Relationship `pages`, ordered by `page_number`, with `cascade="all, delete-orphan"`. Add `Party.source_documents`, ordered by id, with `passive_deletes=True`.
  - `SourceDocumentPage` (`source_document_pages`): `id`; `source_document_id` FK, CASCADE, not null; `page_number` Integer, not null; `text` Text, not null. Unique `(source_document_id, page_number)` and `sa.CheckConstraint("page_number >= 1", name="page_number_positive")`.
  - The stored file name is not a column. It is derived as `f"{content_hash}.pdf"`.
- **Migration** `versions/0002_source_documents.py` (`--rev-id 0002`): autogenerate, then review it by hand as `CONSTRAINTS.md` requires. Keep one enum CHECK each plus the single `ck_source_document_pages_page_number_positive`. `alembic check` must report no drift.
- **`db.is_initialised`**: also require `source_documents` and `source_document_pages`. This way a database at `0001` gets the existing "not initialised" message (Scenario 7) for every command.
- **Service** (`src/ideology_app/source_documents.py`):
  - `MAX_UPLOAD_BYTES = 50 * 1024 * 1024`.
  - `add_uploaded_document(session, *, party_id: int, file_path: Path, files_dir: Path) -> SourceDocument` runs these steps in order:
    1. Fetch the Party (`NotFoundError("party N not found")`).
    2. Check the file: it must be a regular file (else `InvalidInputError("file … not found")`), its size must be > 0 and ≤ max, and its first 5 bytes must be `%PDF-` (else `InvalidInputError` naming the file and the problem). Then read the bytes and compute `sha256(...).hexdigest()`.
    3. Insert the row with `origin=upload`, `status=registered`, the hash and `original_filename=file_path.name` (truncated to 255 characters), then flush. An `IntegrityError` means rollback and `DuplicateError` (Scenario 5 message).
    4. Store the file: `files_dir.mkdir(parents=True, exist_ok=True)`. If `<hash>.pdf` doesn't already exist, write it to a temporary file in the same directory and `os.replace` it into place. Set `status=fetched`.
    5. Call `extract_pages`. On success, add the page rows, then set `page_count` and `status=parsed`. On `PdfTextError`, set `status=failed` and `failure_reason`, and set `page_count` from `PdfTextError.page_count`. Flush and return.
  - An `OSError` while storing is not caught: the session rolls back, and a content-addressed orphan file is harmless.
  - Also add `list_documents(session, party_id)` (raises `NotFoundError` for an unknown Party) and `get_document(session, document_id)` (`NotFoundError("source document N not found")`).
  - Note for later: Evidence quote matching and the URL feature reuse the page rows and `extract_pages`.
- **CLI** (`cli.py`): add a `source` group, "Manage Source Documents".
  - `source add --party ID --file PATH`: uses `click.Path(exists=True, dir_okay=False, path_type=Path)` and passes `files_dir=config.source_files_dir()`. It commits in `session_scope`, then prints `Created source document <id>: parsed (<n> pages)`. For a `failed` row, it raises `ClickException(f"source document {id} failed: {reason}")` **after** the commit.
  - `source list --party ID`: the table from Scenario 6.
  - `source text --document ID [--page N]`: as in Scenario 6.
  - All three commands use `@requires_db`.
- **Test fixtures** (`tests/pdf_factory.py`, a plain helper module with no binaries committed): `make_text_pdf(pages: list[str | None]) -> bytes` builds a minimal PDF by hand. It has one Helvetica/WinAnsiEncoding font, and each page's content stream is `BT /F1 12 Tf 72 y Td (<cp1252-escaped line>) Tj ET` per line, with `None` producing a page with no text (`0 0 1 rg 10 10 100 100 re f`). It writes the objects, the xref with 10-digit offsets, and the trailer. This is the generator the planner verified against pypdf 6.21.1. Encrypted fixtures come from `pypdf.PdfWriter(clone_from=...)` with `.encrypt("secret")` (RC4, no `cryptography` needed). The files are written into `tmp_path` per test.

## Expected File Changes

- `pyproject.toml`: modify (add `pypdf`). `.gitignore`: modify (add `source_files/`).
- `src/ideology_app/config.py`, `db.py`, `models.py`, `cli.py`: modify.
- `src/ideology_app/pdf_text.py`, `src/ideology_app/source_documents.py`: create.
- `src/ideology_app/migrations/versions/0002_source_documents.py`: create.
- `tests/pdf_factory.py`, `tests/test_pdf_text.py`, `tests/test_source_documents.py`, `tests/test_cli_source.py`: create. `tests/test_migrations.py`: modify (new tables, downgrade to `0001`, the offline PostgreSQL render contains each new CHECK once).
- `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/technical-discovery.md`: update.
- `PROGRESS.md`, `feature_list.json`: update this feature's entry only.

## Visual Design Impact

- UI involved: **no**. The only surface is the CLI. This feature has no browser-visible changes, so the browser-validation rule in `AGENTS.md` does not apply. Design source: not applicable.

## Durable Documentation Impact

- `ARCHITECTURE.md`: update.
  - Data layer: the `SourceDocument` and `SourceDocumentPage` models, the `pdf_text` adapter (the only module that imports pypdf), the `source_documents` service, `SOURCE_FILES_DIR` and content-addressed storage.
  - CLI: the `source` commands.
- `CONSTRAINTS.md`: update.
  - Only `pdf_text.py` imports pypdf.
  - Stored Source Document files are content-addressed and never overwritten or edited.
  - Page text is stored as extracted (NUL removed only). Any normalisation happens at match time.
  - Tests build PDFs with `tests/pdf_factory.py` and never use `./source_files`.
- `docs/technical-discovery.md`: update the PDF bullet to pypdf (pure Python, works on 3.15) instead of PyMuPDF.
- `AGENTS.md`: not needed.

## Implementation Plan

1. Add the dependency and the `.gitignore` entry, then run `./init.sh` (this creates the worktree `.venv`).
2. Write `pdf_text.py` and `tests/pdf_factory.py`, then `test_pdf_text.py`.
3. Add the models and generate migration `0002`. Review it, run `alembic check`, update `is_initialised`, and extend `test_migrations.py`.
4. Write the `source_documents.py` service and its tests.
5. Add the CLI `source` group and its tests, then do the manual smoke.
6. Update the docs, then record the evidence (status `passing`).

## Implementation Tasks

- [ ] `pyproject.toml`, `.gitignore`, `config.source_files_dir()`.
- [ ] `pdf_text.extract_pages` and `PdfTextError`, with the four reasons and NUL stripping.
- [ ] `tests/pdf_factory.py` and `test_pdf_text.py`:
  - Text on 2 pages with accents.
  - A mixed page keeps `""`.
  - Blank pages and `add_blank_page` give "no text layer".
  - `b"%PDF-"` plus garbage, and a truncated file, give `could not read PDF:`.
  - A password-encrypted PDF gives `PDF is encrypted`. An empty-password PDF is read.
  - `\x00` is stripped (monkeypatch the page text).
- [ ] The models, migration `0002` with each CHECK once, and `is_initialised`.
- [ ] `test_migrations.py`:
  - Upgrade creates both tables, with no drift.
  - `downgrade 0001` drops them.
  - Raw inserts with a bad status or origin, `page_number=0`, or an unknown `party_id` raise `IntegrityError`.
  - Deleting a Party cascades to its documents and pages.
  - The PostgreSQL render has each new CHECK once.
- [ ] `source_documents.py` and `test_source_documents.py`: Scenarios 1 to 5 at service level, including the stored-file bytes and name, the hash, no file or row on rejected input, a shared file across Parties, and a session that is still usable after `DuplicateError`.
- [ ] CLI `source add|list|text` and `test_cli_source.py`: Scenarios 1 to 7 through `CliRunner` with `--database-url` and `SOURCE_FILES_DIR=tmp_path/...`, checking exit codes and output lines.
- [ ] Docs and evidence.

## Verification Plan

- `CI=true ./init.sh; echo "exit=$?"` → `install` and `pytest` pass, followed by `All checks passed.` and exit 0.
- `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider` → clean, with no `ResourceWarning` from unclosed files, readers or engines.
- `.venv/bin/alembic -c alembic.ini history` shows `0002 (head)`. `alembic check` against a scratch database upgraded to head reports no drift.
- Manual CLI smoke in a scratch directory outside the repo, with `DATABASE_URL` and `SOURCE_FILES_DIR` pointing into it:
  1. `db upgrade`, then create an Election and a Party.
  2. Write fixture PDFs with `.venv/bin/python -c "import sys; sys.path.insert(0, 'tests'); from pdf_factory import make_text_pdf; ..."` run from the repo root, writing into the scratch directory.
  3. `source add` with the text PDF → parsed, exit 0. With the blank PDF → `Error: … failed: no text layer…`, exit 1.
  4. Re-add the text PDF → duplicate, exit 1.
  5. `source list` and `source text --page 1`.
  6. `ls` the stored files and compare `shasum -a 256` with the listed hashes.
  7. Delete the scratch directory.
- `git status` shows no `*.db` or `source_files/` in the repo afterwards.
- E2E: there is no E2E harness and no HTTP or UI flow. The `CliRunner` tests are the end-to-end coverage. Tests need no network and no LLM.

## Evidence To Capture

- The `init.sh` summary, its exit code and the pytest pass count. The `-X dev -W error` result. The installed pypdf version.
- The `alembic check` output and the offline PostgreSQL CHECK counts.
- The CLI smoke transcript: commands, key output lines, exit codes, and the hash comparison.

## Validator Checklist

- [ ] Only the listed files changed: no URL fetching, OCR, run triggers, HTTP endpoints, or changes in the LLM provider area.
- [ ] Scenarios 1 to 7 pass when the validator re-runs them, through pytest and the CLI smoke.
- [ ] `content_hash` is the SHA-256 of the original bytes, and the stored file is byte-identical and named `<hash>.pdf`.
- [ ] Every `failed` row has a `failure_reason`, and every `parsed` row has `page_count` page rows numbered 1..N.
- [ ] pypdf is imported only in `pdf_text.py`. The migration has each CHECK once and shows no drift. `-X dev -W error` is clean.
- [ ] Tests generate their PDFs (no network, no LLM) and never touch `./ideology.db` or `./source_files`.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md` and `docs/technical-discovery.md` match the code. `feature_list.json` (this entry only) and `PROGRESS.md` hold real evidence. No `docs/validations/`.
