# Spec: deploy-container

## Goal

A container image that serves IdeologiApp in production: the web client, the public API, the feedback POST and the admin page, from one process. It is the first deployment feature (user request, 2026-11-08: a Netcup VPS with Coolify, `ideologiapp.es`). It settles the risks entries "The container image" and "how published data in the committed SQLite DB reaches the deployed database", and decides the deployment items of the feedback and admin entries.

## Decisions

- **One image, two stages** (`Dockerfile` at the repo root). A Node stage (`node:24.22.2-slim`) runs `npm ci` from the committed lockfile and `npm run build`. A Python stage (`python:3.15.2-slim-trixie`, the Python the team's `.venv` uses) installs the package with `pip install .` (no `[dev]`) and copies the built client to `/app/web` (`WEB_DIST_DIR=/app/web`). Base image tags are exact versions.
- **Published data travels inside the image.** The committed `data/ideology.db` is copied to `/app/data/ideology.db` (`DATABASE_URL=sqlite:////app/data/ideology.db`), owned by root and read-only for the server user, so the server cannot write it (SQLite opens a file it cannot write read-only). Publishing new data is a new image built from a commit with the new database. No PostgreSQL in this feature: the deployed server only reads published data, and generation stays an Operator task on a developer machine (`precomputed`). The PostgreSQL target is deferred until a deployment needs a writer.
- **Feedback lives on a volume.** `FEEDBACK_DATABASE_URL=sqlite:////data/feedback.db`; `/data` is a declared volume owned by the server user, so a named volume starts with the right owner. Without a persistent volume every redeploy loses the messages; the runbook says so.
- **Process:** `uvicorn ideology_app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --no-access-log`, as a non-root user (`app`, uid 10001).
  - One worker: admin sessions, the sign-in limiter and the feedback limiter are per process.
  - `--no-access-log`: access logs are off, which settles "Query strings in server access logs" and the feedback entry's "access logs that pair the time of `POST /api/v1/feedback` with an IP". Errors still go to stderr.
  - Proxy headers: uvicorn trusts `X-Forwarded-For` / `X-Forwarded-Proto` only from `FORWARDED_ALLOW_IPS` (uvicorn's own variable, default `127.0.0.1,::1`). The image keeps that default, so a forgotten setting fails closed (every client shares the proxy's rate-limit key) rather than open (spoofable). The runbook sets `FORWARDED_ALLOW_IPS=*` behind Coolify's proxy, where the container port is not published and only the proxy can reach it.
- **Health check:** a Docker `HEALTHCHECK` on `GET /health` with the Python standard library (no curl in the image).
- **Build context:** `.dockerignore` keeps out `.git`, `.env`, `.venv`, `node_modules`, built output, every `*.db` except `data/ideology.db`, SQLite sidecars, `source_files/`, `data/elections/` (the server reads only the database) and the tests.
- **TLS** is the proxy's job (Coolify/Traefik with Let's Encrypt). The admin cookie is already `Secure` on any non-local host.
- **Deferred to a future feature that runs the pipeline on a server** (none is planned; the deployed server runs no pipeline command): scheduling `source refetch` and `pipeline run-queued`, the LLM price table and money cap, the atomic queue claim, recovery of stuck `running` runs, queued runs pinned to an old provider, and the PostgreSQL publish lock.
- **Not in this feature:** the Coolify and VPS setup themselves (done by the user, following the runbook), a proxy-level sign-in limit, automated feedback backups, a Python lockfile.

## Acceptance

- `docker build -t ideology-app .` succeeds from a clean checkout.
- `docker run` with only a volume on `/data` serves `/health` (200), `/` (the Landing), `/api/v1/elections` (Election 1), the Dataset Version and a Party logo; the container reports `healthy`.
- The server user cannot write `/app/data/ideology.db`; it creates `/data/feedback.db` on startup; a `POST /api/v1/feedback` survives a container restart with the same volume.
- No access-log lines are printed for requests.
- With `FORWARDED_ALLOW_IPS` unset, a forged `X-Forwarded-For` does not change the rate-limit key; with it set, the forwarded client is used.
- `ADMIN_USERS` set at run time enables `/admin` sign-in; nothing secret is in the image.
- Static tests (`tests/test_deploy_container.py`) pin the CMD flags (one worker, no access log, proxy headers), the non-root user, the image paths and the `.dockerignore` exclusions.
- `CI=true ./init.sh` passes.
- Browser check against the container at 375px and 1280px: Landing, a full Questionnaire, results, a Share Link and `/metodologia`; console clean, no failed request, no request carries Answers.
- Runbook in `docs/technical-discovery.md` (Deployment and Operations) and `README.md` (Spanish, "Despliegue").
