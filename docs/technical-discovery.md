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
| URL re-fetch interval | `SOURCE_REFETCH_INTERVAL_HOURS`, default 6 | Whole hours. Applied by `ideology source refetch` in both modes (a due URL source is downloaded and hashed; changed bytes register a replacement document); only `live` queues a Pipeline Run. Scheduling the command belongs to a future feature that runs the pipeline on a server (`deploy-container` runs none). |
| `SOURCE_INGESTION` | `upload`, `url` (both allowed) | Per Source Document: chosen by the CLI flag `ideology source add --file` or `--url`, not an environment variable. |
| Validation thresholds | coverage %, statement range, topic share | Per Election overrides allowed. |
| `DATABASE_URL` / `--database-url` | SQLAlchemy URL, default `sqlite:///ideology.db` | `sqlite:///data/ideology.db` (from the repo root) selects the shared database committed to git (`shared-database`); there is no other selector. On it, `pipeline run` / `run-queued` ask for confirmation (`--yes` skips it) and a missing file is refused instead of created. The default stays a local file so a stray command never writes the shared one. |
| `FEEDBACK_DATABASE_URL` / `ideology feedback --feedback-database-url` | SQLAlchemy URL, default `sqlite:///feedback.db` (current directory, git-ignored) | The anonymous Voter feedback store (`feedback-api`), separate from the shared database: pointing it at `data/ideology.db`, at the `DATABASE_URL` database or at an in-memory database is refused at startup and by the CLI. PostgreSQL URLs are allowed for a deployment. Its schema has its own Alembic environment (`feedback_alembic_version`), applied at startup and by `ideology feedback upgrade`. |
| `ADMIN_USERS` | `username:scrypt-hash` entries, comma-separated; unset = no Operator account | Operator accounts for the admin page (`feedback-admin`); hashes from `ideology admin hash-password`. Only in the deployment environment, never in git. Malformed values stop startup. Sessions are in memory, so one worker. |

## Data and Storage

- No Voter answers are stored on the server; anonymous feedback text is stored in a separate store (`feedback-api`): only the message, the screen it came from (`landing` / `results`) and the time.
- Share Link: Dataset Version id plus compactly encoded Answers placed in the URL **fragment** (`#…`), so it isn't sent to the server or recorded in access logs.
- Dataset Versions are immutable and kept indefinitely.
- One SQLite database for all Elections is committed at `data/ideology.db` (`shared-database`), beside the bundles in `data/elections/<slug>/`. It is the single source of truth for every developer: Elections, Parties, Source Documents, Pipeline Runs with their recorded LLM calls, Statements, Party Positions and Dataset Versions, so run ids, Dataset Version ids and `request_hash` values agree on every machine. It is built from scratch with `ideology db upgrade` + `ideology data import <bundle>` per Election, stays in `delete` journal mode, is tracked as `binary` and is never downgraded. `ideology db check` (read-only) is the safe-to-commit gate. The app never invokes git: the Operator commits and pushes it by hand (see "Shared database" under Integrations).
- Source Text Bundles (`source-text-bundle`): the manifesto text of each Election is committed under `data/elections/<slug>/` (`election.toml` plus one `.md` per Party); PDFs are never committed. Runbook:
  - Add a Party's manifesto: put the PDF anywhere outside `data/`, run `ideology source extract <pdf> --party <SHORT> --out data/elections/<slug>/<file>.md [--url <public PDF URL>]`, list it in `election.toml`, commit both. Without `--url` its Evidence shows the page with no link.
  - Import into any database (fresh or existing): `ideology db upgrade`, then `ideology data import data/elections/<slug>`. It is idempotent; `ideology data check data/elections/<slug>` confirms the database holds exactly the committed text.
  - Once a `.md` is committed, the PDF is no longer needed by anyone (import, generation and Evidence read only the bundle), so a local-only PDF can be discarded.
  - Replace a manifesto: put the new PDF on your machine, run `source extract … --force` over that Party's `.md` (or delete the file and extract again), review the diff, commit it. Every machine's next `data import` registers a replacement Source Document (the old one stays for older Evidence); in `live` that queues a run.
  - Never edit a `.md` by hand: the import refuses a file that is not in canonical form or whose `text_sha256` does not match.
  - Party logos (`party-logos-data`): put the user's file in `data/elections/<slug>/logos/` and declare `logo = "logos/<file>"` on that Party in `election.toml`; commit the files, the manifest and the upgraded/imported `data/ideology.db` together. Importing logos is a bundle write like any other (pull → `data import` → `data check` → `db check` → commit, never while someone is generating); it never queues a run or touches a Dataset Version. A refused file is reported to the user, never edited. Normalisation (only at the user's request, `CONSTRAINTS.md` Party Logos; the 2023 logos were done this way): trim transparent margins (alpha > 8), fit without distortion into a 256x256 transparent PNG with 6% padding, centred, and save as an optimised PNG; no script is committed yet (see `docs/risks-and-open-questions.md`). The web client shows each logo in a fixed white tile with `object-fit: contain` and no extra padding (`party-logos-display`), so the 6% padding is the logo's only margin.

## Integrations

- LLM provider API(s).
- Local Claude Code CLI (`LLM_PROVIDER=claude_code`, `llm-provider-claude-code`): the Operator's own Claude subscription, no API key, local runs only (never a deployment). Runbook:
  1. Once: `claude auth login` with a Claude subscription (`claude auth status` must show `authMethod` `claude.ai`, or set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`). An API-key login is rejected before the run starts. `claude auth status` does not prove the OAuth token is fresh: in the `e2e-real-2023-election` smoke run it reported `loggedIn`/`claude.ai` while every call got 401 "OAuth access token has expired" (the run failed before any call, `llm_calls` 0). Before a long run, ping it with `claude -p "responde solo: ok"` and re-run `claude auth login` on a 401.
  2. Run: `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election N` (optionally `LLM_MODEL=…` and `LLM_CLAUDE_CODE_MAX_WAIT_HOURS=…`).
  3. Keep the process and the machine awake (on AC power, lid open): when the subscription usage limit is hit, the provider prints `claude_code: usage limit reached (task …); waiting until <time> …` on stderr and waits in-process for the reset, then retries the same call. A real 2023 run (9 Parties) is about 168 calls and can take several usage-limit windows.
  4. If the process or the machine dies, or the run ends `failed` halfway (Ctrl-C ends it `failed: interrupted`; a killed run may stay `running`), every LLM call it completed is already recorded (`pipeline-run-checkpoint`). Resume with `ideology pipeline run --election N --resume-from R`: only the missing calls go to the CLI.
- Shared database (`shared-database`): commands run from the repo root with `export DATABASE_URL=sqlite:///data/ideology.db`. Runbook:
  1. Pull code and DB together (`git pull`) with no `ideology` process or web server open on the DB. Pulling or switching branch replaces the file: an open process would keep writing to the old copy, and those writes are lost.
  2. Tell the team you are generating. One active run at a time on the shared DB, for any Election.
  3. `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election N`. Confirm the prompt, or pass `--yes`. Use `--resume-from R` when the CLI or `db check` names an unfinished run (the CLI refuses a new run while the Election has one; `--fresh` starts from zero anyway). To re-run after a finished run (one with a Dataset Version, passed or failed), e.g. after a prompt or selection change, use `--reuse-from R`: identical calls of run R (such as every `statement_candidates` call) are reused with zero tokens and only the changed ones go to the provider (`pipeline-coverage-selection`).
  4. To stop (usage limit, end of day), press Ctrl-C once and wait for the process to exit. The run ends `failed: interrupted`.
  5. Run `.venv/bin/ideology db check`. It must print `Safe to commit: yes`.
  6. Commit only the DB (`git add data/ideology.db`), with a message naming the run and `--resume-from R`, then push. Tell the team. During generation the DB commits go on the branch doing the work, merged to `main` by PR.
  7. The next developer starts at step 1 and resumes with `--resume-from R` (or re-runs a finished run with `--reuse-from R`), using the same `LLM_PROVIDER`/`LLM_MODEL` and code revision.
  8. Other writes (`data import` of a new or changed bundle, `db upgrade` after a migration) follow the same pull → write → `db check` → commit → push cycle, never while someone is generating. A PR that adds a migration also upgrades and commits `data/ideology.db` (`tests/test_committed_database.py` fails until it does).
  9. A merge conflict on the DB means the rule was broken. Keep the side with the run that matters (`git checkout --ours|--theirs`), re-run `db upgrade` or `data import` if that side lacks them, and resume. Never try to merge two DB files.
  10. To serve locally: `DATABASE_URL=sqlite:///data/ideology.db .venv/bin/uvicorn ideology_app.main:app` (every Election).
- HTTP fetch for URL-based Source Documents: stdlib `urllib` (`ideology_app.http_fetch`), http/https only, no new dependency.

## Authentication and Authorization

- Voters: none.
- Operator: the CLI, plus per-Operator username and password accounts for the admin page (`feedback-admin`): salted scrypt hashes in `ADMIN_USERS`, a server-side in-memory session in an `HttpOnly`, `SameSite=Strict` cookie limited to `/admin/api`, CSRF and origin checks, and a sign-in rate limit.

## Deployment and Operations

- One container (`deploy-container`, `Dockerfile` at the repo root): the FastAPI app serves the built web client, the public API, the feedback POST and the admin page. It runs no pipeline: generation stays on Operator machines (`precomputed`), and the server only reads published data. In local development the Vite dev server proxies API calls to uvicorn.
- In `precomputed` mode the public site could be served from a cache or CDN.

Image (`deploy-container`):

- Two stages: Node (`npm ci`, `npm run build`) and Python (`pip install .`). Base images are exact versions.
- Published data is baked in: `data/ideology.db` → `/app/data/ideology.db`, owned by root and read-only for the server user (`app`, uid 10001). Publishing new data = build and deploy a new image from the commit that has it.
- Feedback: `FEEDBACK_DATABASE_URL=sqlite:////data/feedback.db` on the `/data` volume. Without a persistent volume every redeploy loses the messages.
- Command: `uvicorn ideology_app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --no-access-log`. One worker (admin sessions and both rate limiters are per process); no access log.
- `HEALTHCHECK` on `GET /health`.

Run-time settings (never in the image or git):

| Variable | Value | Why |
| --- | --- | --- |
| `ADMIN_USERS` | `miguel:scrypt…,enrique:scrypt…` from `ideology admin hash-password` | Operator accounts for `/admin`; unset = admin disabled |
| `FORWARDED_ALLOW_IPS` | `*`, only behind a proxy that is the sole way to reach the container | uvicorn then trusts `X-Forwarded-For`/`-Proto`, so the rate limiters key the real client. Unset, it trusts only loopback and every client shares the proxy's key (fail closed). uvicorn keys on the leftmost `X-Forwarded-For` entry, so `*` is safe only while the proxy replaces a client-sent `X-Forwarded-For` instead of appending to it: keep Traefik's entrypoint `forwardedHeaders` untrusted (Coolify's default, no `insecure`, no `trustedIPs`), and revisit before putting a CDN such as Cloudflare in front |

Runbook (VPS with Coolify, user decision 2026-11-08):

1. Build and check locally: `docker build -t ideology-app .`, then `docker run --rm -p 127.0.0.1:8000:8000 -v ideology-data:/data ideology-app` and open `http://127.0.0.1:8000/`.
2. In Coolify: a new resource from the GitHub repository, build pack Dockerfile, branch `main`, port `8000`. Do not publish the port on the host: only Coolify's proxy may reach it (that is what makes `FORWARDED_ALLOW_IPS=*` safe).
3. Add a persistent volume mounted at `/data`, and the two variables above (`ADMIN_USERS` as a secret).
4. Domains: `https://ideologiapp.es`, with `www` and `ideologiapp.com` redirecting to it. Coolify's proxy gets the Let's Encrypt certificates once DNS `A` records point at the VPS. TLS is required: the admin cookie is `Secure` off localhost.
5. Leave the proxy's own access log off, so no request line or client IP is recorded anywhere.
6. Check after each deploy: `/health` answers 200; the Landing, a Questionnaire, results, a Share Link and `/metodologia` work; no request carries Answers; a feedback message survives a redeploy; `/admin` signs in.
7. Backups: copy the feedback store off the server regularly (a consistent copy, not the raw file while it is open): `docker exec <container> python -c "import sqlite3; sqlite3.connect('/data/feedback.db').backup(sqlite3.connect('/data/feedback-backup.db'))"`, then copy `/data/feedback-backup.db` out (`docker cp <container>:/data/feedback-backup.db .`) and delete it from the volume (`docker exec <container> rm /data/feedback-backup.db`), so messages that Operators delete later do not stay on the server in an old copy. Restore by stopping the container and putting the copy back as `/data/feedback.db`.
8. Roll back by redeploying the previous commit; the feedback volume is untouched.

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
