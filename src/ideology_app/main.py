"""ASGI app: ``/health``, the public API under ``/api/`` (read-only plus the feedback POST) and the web client."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ideology_app.api import ApiNotFoundError, feedback_router, router
from ideology_app.api.http_cache import ERROR_CACHE_CONTROL
from ideology_app.config import database_url as default_database_url
from ideology_app.config import feedback_database_url as default_feedback_database_url
from ideology_app.config import web_dist_dir as default_web_dist_dir
from ideology_app.db import make_engine
from ideology_app.feedback.rate_limit import FeedbackRateLimiter
from ideology_app.feedback.store import check_separate, create_schema
from ideology_app.web import warn_if_not_built, web_router


async def _api_not_found(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiNotFoundError)
    return JSONResponse(
        status_code=404,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": ERROR_CACHE_CONTROL},
    )


def create_app(
    database_url: str | None = None,
    web_dist_dir: Path | None = None,
    feedback_database_url: str | None = None,
) -> FastAPI:
    """Build the app; the Engines live in the lifespan.

    The shared Engine reads ``database_url`` (default ``$DATABASE_URL``); the
    feedback Engine writes ``feedback_database_url`` (default
    ``$FEEDBACK_DATABASE_URL`` or ``sqlite:///feedback.db``). Startup fails with
    ``FeedbackStoreError`` before any Engine is created when the feedback store
    is not a database of its own. The web client is served from
    ``web_dist_dir`` (default ``$WEB_DIST_DIR`` or ``apps/web/dist`` in the
    current directory), resolved once here.
    """
    dist_dir = (web_dist_dir if web_dist_dir is not None else default_web_dist_dir()).resolve()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        main_url = database_url or default_database_url()
        feedback_url = feedback_database_url or default_feedback_database_url()
        check_separate(feedback_url, main_url)
        engine = make_engine(main_url)
        app.state.engine = engine
        try:
            feedback_engine = make_engine(feedback_url)
            app.state.feedback_engine = feedback_engine
            try:
                create_schema(feedback_engine)
                yield
            finally:
                feedback_engine.dispose()
        finally:
            engine.dispose()

    app = FastAPI(
        title="ideology-app",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_exception_handler(ApiNotFoundError, _api_not_found)
    # Per process; a test may replace it before the first request.
    app.state.feedback_rate_limiter = FeedbackRateLimiter()
    app.include_router(router)
    app.include_router(feedback_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Last: the catch-all must not shadow any route registered above.
    warn_if_not_built(dist_dir)
    app.include_router(web_router(dist_dir))

    return app


app = create_app()
