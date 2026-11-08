# Production image (deploy-container): the web client, the public API, the
# feedback POST and the admin page in one process. Published data is baked in
# read-only; feedback lives on the /data volume. Runbook: docs/technical-discovery.md.

# --- web client -------------------------------------------------------------
FROM node:24.22.2-slim AS web
WORKDIR /build
# Manifests first, so the npm ci layer is reused while only sources change.
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages/core/package.json packages/core/
COPY apps/web/package.json apps/web/
RUN npm ci --no-audit --no-fund
COPY packages/core packages/core
COPY apps/web apps/web
RUN npm run build

# --- server -----------------------------------------------------------------
FROM python:3.15.2-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml ./
COPY src src
RUN pip install . && rm -rf src pyproject.toml build

# Owned by root and not writable by the server user: SQLite opens it read-only.
COPY data/ideology.db data/ideology.db
COPY --from=web /build/apps/web/dist web

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data
VOLUME /data

ENV DATABASE_URL=sqlite:////app/data/ideology.db \
    FEEDBACK_DATABASE_URL=sqlite:////data/feedback.db \
    WEB_DIST_DIR=/app/web

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# One worker: admin sessions and both rate limiters are per process.
# Proxy headers are trusted only from FORWARDED_ALLOW_IPS (uvicorn's default
# 127.0.0.1,::1); set it to * only where the proxy is the sole way in.
# No access log: request lines and client IPs are not recorded.
CMD ["uvicorn", "ideology_app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--no-access-log"]
