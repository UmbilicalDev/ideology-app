# Technical Discovery

## Product Surface

A responsive, mobile-first public website for Voters, plus a minimal Operator surface (CLI commands and/or a simple admin page). The web client is the only Voter client in the MVP. iOS and Android apps are a planned post-MVP client (see Clients).

## Candidate Stack

- **Backend**: Python, FastAPI. The AI pipeline lives in the same codebase as a reusable module.
- **Frontend**: a React + TypeScript single-page app built with Vite, talking to the FastAPI read-only API; matching runs client-side. See Clients.
- **Storage**: PostgreSQL (SQLite acceptable for local dev). Source Document files on local disk or object storage.
- **PDF text extraction**: `pypdf` (pure Python, BSD-3-Clause, installs on Python 3.15; chosen over PyMuPDF, which ships compiled wheels and is AGPL), with one text string per page. Only `ideology_app.pdf_text` imports it. OCR is out of scope for the MVP: a PDF without a text layer ends `failed`.

## Clients

Decision: React everywhere, web first.

- **Web (MVP)**: React + TypeScript, Vite, React Router, Vitest + Testing Library. A static build (HTML/JS/CSS) with no server rendering.
- **iOS + Android (post-MVP)**: a single React Native app built with Expo, rather than two native apps. The app is small (landing, Questionnaire, results, breakdown, methodology), so native code isn't worth it.
- **What is shared**: shared code is plain TypeScript (domain types, Match Score, Share Link codec, Questionnaire state, API client), not UI components. The web uses semantic HTML and CSS (accessible radio groups, `DESIGN.md` tokens); the mobile app uses React Native components. We chose this over one Expo + `react-native-web` codebase for all three because the MVP is web-only and the web should stay idiomatic, light and accessible. Screens are few, so writing them twice costs little.

Layout: npm workspaces at the repo root, with a committed `package-lock.json`:

```text
packages/core/   # pure TypeScript shared by every client; no React, DOM or platform APIs
  src/domain/          # entities (Statement, Party Position, Answer, Match Score...) and pure rules
  src/application/     # use cases and Questionnaire state, depending only on domain and ports
  src/infrastructure/  # adapters behind the ports: HTTP client for the public API (fetch), Share Link codec
apps/web/        # React web client (MVP)
  src/app/             # composition root: routing, providers, wiring core use cases to adapters
  src/features/        # one folder per user-facing feature (landing, questionnaire, results, share, methodology)
  src/ui/              # presentational components and DESIGN.md tokens; no data fetching
apps/mobile/     # Expo app (post-MVP), same structure as apps/web, reusing packages/core
```

Rules:

- Dependencies point inward: `ui` → `features` → `core/application` → `core/domain`. `core/domain` imports nothing, and `core` never imports React or platform APIs.
- Components hold no business rules. Scoring, encoding and flow state live in `core` and are tested there without a browser.
- Answers live only in client memory and in the Share Link fragment, never in a request.
- Keep it light: no global state library, CSS-in-JS runtime or extra layers unless a feature needs them.

## Configuration Points

| Setting | Values | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` / model | e.g. anthropic, openai, local | Provider abstraction with structured-output support; the provider and model are recorded per Pipeline Run. |
| `GENERATION_MODE` | `precomputed`, `live` | `precomputed` is the default (the Operator triggers runs). `live` regenerates automatically when a Source Document is added or changes. |
| URL re-fetch interval | `SOURCE_REFETCH_INTERVAL_HOURS`, default 6 | Whole hours. Applied by `ideology source refetch` in both modes (a due URL source is downloaded and hashed; changed bytes register a replacement document); only `live` queues a Pipeline Run. Scheduling the command belongs to the first deployment feature. |
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
- The FastAPI app serves the built web client (`apps/web/dist`) and the public API. In local development the Vite dev server proxies API calls to uvicorn.
- In `precomputed` mode the public site could be served from a cache or CDN.

## Testing and Verification

- Unit tests: matching rule, Share Link codec, each Validation check.
- Frontend: Vitest for `packages/core`, and Vitest + Testing Library for web components. Every UI feature also gets a real-browser check (`AGENTS.md`).
- Pipeline tests with a recorded/fake LLM provider (deterministic fixtures).
- One end-to-end test from the Source Documents fixture to the shared result.

## Observability

- A Pipeline Run log: provider, model, prompt version, token/cost estimate, duration, Validation report.
- No per-user analytics. Basic request metrics only, without query strings or fragments.

## Constraints

- GDPR: political opinions are special category data (Art. 9). Keeping answers out of the server avoids processing them.
- Cost: LLM cost per Pipeline Run must be visible; `live` mode cost must be capped.
