# Technical Discovery

## Product Surface

A responsive, mobile-first public website for Voters, plus a minimal Operator surface (CLI commands and/or a simple admin page).

## Candidate Stack

- **Backend**: Python, FastAPI. The AI pipeline lives in the same codebase as a reusable module.
- **Frontend**: light server-rendered pages (Jinja + HTMX) or a small SPA; matching runs client-side.
- **Storage**: PostgreSQL (SQLite acceptable for local dev). Source Document files on local disk or object storage.
- **PDF text extraction**: `pypdf` (pure Python, BSD-3-Clause, installs on Python 3.15; chosen over PyMuPDF, which ships compiled wheels and is AGPL), with one text string per page. Only `ideology_app.pdf_text` imports it. OCR is out of scope for the MVP: a PDF without a text layer ends `failed`.

## Configuration Points

| Setting | Values | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` / model | e.g. anthropic, openai, local | Provider abstraction with structured-output support; the provider and model are recorded per Pipeline Run. |
| `GENERATION_MODE` | `precomputed`, `live` | `precomputed` is the default (the Operator triggers runs). `live` regenerates automatically when a Source Document is added or changes. |
| URL re-fetch interval | e.g. 6h | `live` only: how often URL sources are re-fetched and hashed. |
| `SOURCE_INGESTION` | `upload`, `url` (both allowed) | Per Source Document: chosen by the CLI flag `ideology source add --file` or `--url`, not an environment variable. |
| Validation thresholds | coverage %, statement range, topic share | Per Election overrides allowed. |

## Data and Storage

- No Voter data is stored on the server.
- Share Link: Dataset Version id plus compactly encoded Answers placed in the URL **fragment** (`#…`), so it isn't sent to the server or recorded in access logs.
- Dataset Versions are immutable and kept indefinitely.

## Integrations

- LLM provider API(s).
- HTTP fetch for URL-based Source Documents: stdlib `urllib` (`ideology_app.http_fetch`), http/https only, no new dependency.

## Authentication and Authorization

- Voters: none.
- Operator: a single admin credential or CLI-only access for the MVP.

## Deployment and Operations

- A single container (web + pipeline worker) plus a database. Pipeline Runs are a background task or a CLI command.
- In `precomputed` mode the public site could be served from a cache or CDN.

## Testing and Verification

- Unit tests: matching rule, Share Link codec, each Validation check.
- Pipeline tests with a recorded/fake LLM provider (deterministic fixtures).
- One end-to-end test from the Source Documents fixture to the shared result.

## Observability

- A Pipeline Run log: provider, model, prompt version, token/cost estimate, duration, Validation report.
- No per-user analytics. Basic request metrics only, without query strings or fragments.

## Constraints

- GDPR: political opinions are special category data (Art. 9). Keeping answers out of the server avoids processing them.
- Cost: LLM cost per Pipeline Run must be visible; `live` mode cost must be capped.
