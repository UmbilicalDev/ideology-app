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
| `LLM_PROVIDER` / model | `anthropic` (default), `claude_code` (local Operator only), `fake` | Provider abstraction with structured-output support; the provider and model are recorded per Pipeline Run. `claude_code` also reads `LLM_CLAUDE_CODE_BIN` (default `claude`), `LLM_CLAUDE_CODE_TIMEOUT_SECONDS` (default 900) and `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` (default 48). |
| `GENERATION_MODE` | `precomputed`, `live` | `precomputed` is the default (the Operator triggers runs). `live` regenerates automatically when a Source Document is added or changes. |
| URL re-fetch interval | `SOURCE_REFETCH_INTERVAL_HOURS`, default 6 | Whole hours. Applied by `ideology source refetch` in both modes (a due URL source is downloaded and hashed; changed bytes register a replacement document); only `live` queues a Pipeline Run. Scheduling the command belongs to the first deployment feature. |
| `SOURCE_INGESTION` | `upload`, `url` (both allowed) | Per Source Document: chosen by the CLI flag `ideology source add --file` or `--url`, not an environment variable. |
| Validation thresholds | coverage %, statement range, topic share | Per Election overrides allowed. |

## Data and Storage

- No Voter data is stored on the server.
- Share Link: Dataset Version id plus compactly encoded Answers placed in the URL **fragment** (`#…`), so it isn't sent to the server or recorded in access logs.
- Dataset Versions are immutable and kept indefinitely.
- Source Text Bundles (`source-text-bundle`): the manifesto text of each Election is committed under `data/elections/<slug>/` (`election.toml` plus one `.md` per Party); PDFs are never committed. Runbook:
  - Add a Party's manifesto: put the PDF anywhere outside `data/`, run `ideology source extract <pdf> --party <SHORT> --out data/elections/<slug>/<file>.md [--url <public PDF URL>]`, list it in `election.toml`, commit both. Without `--url` its Evidence shows the page with no link.
  - Import into any database (fresh or existing): `ideology db upgrade`, then `ideology data import data/elections/<slug>`. It is idempotent; `ideology data check data/elections/<slug>` confirms the database holds exactly the committed text.
  - Once a `.md` is committed, the PDF is no longer needed by anyone (import, generation and Evidence read only the bundle), so a local-only PDF can be discarded.
  - Replace a manifesto: put the new PDF on your machine, run `source extract … --force` over that Party's `.md` (or delete the file and extract again), review the diff, commit it. Every machine's next `data import` registers a replacement Source Document (the old one stays for older Evidence); in `live` that queues a run.
  - Never edit a `.md` by hand: the import refuses a file that is not in canonical form or whose `text_sha256` does not match.

## Integrations

- LLM provider API(s).
- Local Claude Code CLI (`LLM_PROVIDER=claude_code`, `llm-provider-claude-code`): the Operator's own Claude subscription, no API key, local runs only (never a deployment). Runbook:
  1. Once: `claude auth login` with a Claude subscription (`claude auth status` must show `authMethod` `claude.ai`, or set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`). An API-key login is rejected before the run starts.
  2. Run: `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election N` (optionally `LLM_MODEL=…` and `LLM_CLAUDE_CODE_MAX_WAIT_HOURS=…`).
  3. Keep the process and the machine awake (on AC power, lid open): when the subscription usage limit is hit, the provider prints `claude_code: usage limit reached (task …); waiting until <time> …` on stderr and waits in-process for the reset, then retries the same call. A real 2023 run is about 176 calls and can take several usage-limit windows.
  4. If the process or the machine dies, or the run ends `failed` halfway (Ctrl-C ends it `failed: interrupted`; a killed run may stay `running`), every LLM call it completed is already recorded (`pipeline-run-checkpoint`). Resume with `ideology pipeline run --election N --resume-from R`: only the missing calls go to the CLI.
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
