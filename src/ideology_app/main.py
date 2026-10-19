"""ASGI app: ``/health`` and the public read-only API under ``/api/``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ideology_app.api import ApiNotFoundError, router
from ideology_app.api.http_cache import ERROR_CACHE_CONTROL
from ideology_app.db import make_engine


async def _api_not_found(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiNotFoundError)
    return JSONResponse(
        status_code=404,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={"Cache-Control": ERROR_CACHE_CONTROL},
    )


def create_app(database_url: str | None = None) -> FastAPI:
    """Build the app; the Engine (``database_url`` or ``$DATABASE_URL``) lives in the lifespan."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(database_url)
        app.state.engine = engine
        try:
            yield
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
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
