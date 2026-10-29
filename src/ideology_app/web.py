"""Serves the built web client (``apps/web/dist``) with an SPA fallback.

``web_router`` has one catch-all ``GET`` route and MUST be included last in
``create_app``, after the API router and ``/health``, so every other route
matches first. Rules, in order:

1. ``api``, ``api/...``, ``health``, ``health/...``, ``admin`` and
   ``admin/...`` -> 404 (FastAPI's default ``{"detail": "Not Found"}``); the
   fallback never answers for them. ``/admin`` and ``/admin/`` are served by
   ``admin_page_router`` (feedback-admin), included before this router.
2. ``index.html`` is not built -> 404 (checked per request, so a build made
   while the server runs needs no restart).
3. A file inside the dist directory -> that file. ``assets/`` (Vite's
   content-hashed files) are cached for a year; anything else is ``no-cache``.
   Paths that resolve outside the directory (``..``, symlinks) never match.
4. A missing path whose last segment has a ``.`` -> 404, never HTML in place
   of a script or an image.
5. Anything else -> ``index.html`` (``no-cache``); client-side routing takes
   over. The query string is ignored.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger("ideology_app.web")

ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

_RESERVED_PREFIXES = ("api", "health", "admin")

# The Operator admin page (feedback-admin, Decision 13): never cached, never
# indexed, never framed, no Referer, and a CSP that allows only this origin.
ADMIN_PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; font-src 'self' data:; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
}


def _is_reserved(path: str) -> bool:
    return any(path == p or path.startswith(f"{p}/") for p in _RESERVED_PREFIXES)


def _file_inside(dist_dir: Path, path: str) -> Path | None:
    """The file ``path`` names inside ``dist_dir``, or ``None``."""
    try:
        candidate = (dist_dir / path).resolve()
        if candidate.is_relative_to(dist_dir) and candidate.is_file():
            return candidate
    except (OSError, ValueError):
        pass
    return None


def warn_if_not_built(dist_dir: Path) -> None:
    """Log one warning when ``dist_dir`` has no ``index.html``."""
    if not (dist_dir / "index.html").is_file():
        logger.warning("web client not built: %s not found; run ./init.sh", dist_dir / "index.html")


def admin_page_router(dist_dir: Path) -> APIRouter:
    """``GET``/``HEAD`` ``/admin`` and ``/admin/``: ``dist/admin/index.html``, 404 while it is not built."""
    router = APIRouter()
    page = dist_dir / "admin" / "index.html"

    # HEAD too, so ``curl -I`` shows the headers (feedback-admin browser check).
    @router.api_route("/admin", methods=["GET", "HEAD"], include_in_schema=False)
    @router.api_route("/admin/", methods=["GET", "HEAD"], include_in_schema=False)
    def serve_admin_page() -> FileResponse:
        if not page.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(page, headers=ADMIN_PAGE_HEADERS)

    return router


def web_router(dist_dir: Path) -> APIRouter:
    """The catch-all route serving ``dist_dir`` (an absolute, resolved path)."""
    router = APIRouter()
    index = dist_dir / "index.html"

    @router.get("/{path:path}", include_in_schema=False)
    def serve_web_client(path: str) -> FileResponse:
        if _is_reserved(path):
            raise HTTPException(status_code=404)
        if not index.is_file():
            raise HTTPException(status_code=404)
        found = _file_inside(dist_dir, path)
        if found is not None:
            in_assets = found.relative_to(dist_dir).parts[0] == "assets"
            cache = ASSET_CACHE_CONTROL if in_assets else NO_CACHE
            return FileResponse(found, headers={"Cache-Control": cache})
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": NO_CACHE})

    return router
