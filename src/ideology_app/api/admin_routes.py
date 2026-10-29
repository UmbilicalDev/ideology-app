"""The Operator admin API under ``/admin/api/v1`` (feedback-admin, Decisions 4-9).

Outside the public ``/api/`` prefix and never in the public OpenAPI. Every
route needs a server-side session (``ideology_admin`` cookie, ``Path=/admin/api``)
except ``POST /session``; every state-changing route also passes the origin
check, and the session routes need ``X-CSRF-Token``. Every response is
``no-store``, ``noindex`` and ``nosniff``. Nothing about sign-in (username,
password, hash, token, CSRF token) and no message text is logged.
"""

import datetime as dt
import hmac
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ideology_app.admin.accounts import authenticate
from ideology_app.admin.sessions import AdminSession
from ideology_app.api.request_body import _declared_too_large, _is_json, _read_body
from ideology_app.feedback.store import (
    FeedbackMessage,
    clear_reviewed,
    delete_message,
    list_for_admin,
    mark_reviewed,
)

COOKIE_NAME = "ideology_admin"
COOKIE_PATH = "/admin/api"
CSRF_HEADER = "x-csrf-token"
MAX_BODY_BYTES = 4096
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})

ADMIN_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}

INVALID_CREDENTIALS = "Usuario o contraseña incorrectos."
NOT_CONFIGURED = (
    'No Operator account is configured. Set ADMIN_USERS (see README, "ideology admin hash-password").'
)


def _now() -> dt.datetime:
    """The current time (UTC). Tests patch this seam."""
    return dt.datetime.now(dt.UTC)


class AdminRefusal(Exception):
    """Raised by a dependency; the route answers with ``response``."""

    def __init__(self, response: Response) -> None:
        self.response = response


class _AdminRoute(APIRoute):
    """Turns refusals and FastAPI's 422 into responses and adds the admin headers to all."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except AdminRefusal as refusal:
                response = refusal.response
            except RequestValidationError as exc:
                response = await request_validation_exception_handler(request, exc)
            response.headers.update(ADMIN_HEADERS)
            return response

        return handler


admin_router = APIRouter(
    prefix="/admin/api/v1", include_in_schema=False, route_class=_AdminRoute
)


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={**ADMIN_HEADERS, **(headers or {})},
    )


# --- cookie -----------------------------------------------------------------


def _request_host(request: Request) -> str:
    """The ``Host`` header without its port, lower case."""
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def _cookie(request: Request, value: str, *, clear: bool = False) -> str:
    parts = [f"{COOKIE_NAME}={value}", f"Path={COOKIE_PATH}"]
    if clear:
        parts.append("Max-Age=0")
    parts += ["HttpOnly", "SameSite=Strict"]
    if _request_host(request) not in LOCAL_HOSTS:
        parts.append("Secure")
    return "; ".join(parts)


def _clear_cookie(request: Request, response: Response) -> Response:
    response.headers.append("set-cookie", _cookie(request, "", clear=True))
    return response


def _accounts(request: Request) -> dict[str, Any]:
    return getattr(request.app.state, "admin_accounts", {}) or {}


def _unauthorised(request: Request) -> JSONResponse:
    if not _accounts(request):
        response = _error(401, "admin_not_configured", NOT_CONFIGURED)
    else:
        response = _error(401, "not_signed_in", "Sign in to use the admin API.")
    _clear_cookie(request, response)
    return response


# --- dependencies -----------------------------------------------------------


def _origin_ok(request: Request) -> bool:
    """False when ``Origin`` names another host:port than ``Host``, or ``Sec-Fetch-Site`` is cross."""
    origin = request.headers.get("origin")
    if origin is not None:
        host = request.headers.get("host", "").strip().lower()
        try:
            netloc = urlsplit(origin.strip()).netloc.lower()
        except ValueError:
            return False
        if not netloc or not hmac.compare_digest(netloc.encode(), host.encode()):
            return False
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site.strip().lower() not in ("same-origin", "none"):
        return False
    return True


def _csrf_failed() -> AdminRefusal:
    return AdminRefusal(_error(403, "csrf_failed", "The request failed the CSRF check."))


def require_session(request: Request) -> AdminSession:
    """The caller's live session, else 401 (cookie cleared)."""
    if not _accounts(request):
        raise AdminRefusal(_unauthorised(request))
    session = request.app.state.admin_sessions.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise AdminRefusal(_unauthorised(request))
    return session


def require_csrf(
    request: Request, session: Annotated[AdminSession, Depends(require_session)]
) -> AdminSession:
    """The session, after the origin check and ``X-CSRF-Token`` (constant time), else 403."""
    if not _origin_ok(request):
        raise _csrf_failed()
    given = request.headers.get(CSRF_HEADER, "")
    if not given or not hmac.compare_digest(given.encode(), session.csrf_token.encode()):
        raise _csrf_failed()
    return session


Session = Annotated[AdminSession, Depends(require_session)]
CsrfSession = Annotated[AdminSession, Depends(require_csrf)]


# --- serialisation ----------------------------------------------------------


def _timestamp(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message_out(message: FeedbackMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "message": message.message,
        "origin": message.origin,
        "created_at": _timestamp(message.created_at),
        "reviewed_at": _timestamp(message.reviewed_at),
    }


def _session_out(session: AdminSession) -> dict[str, str]:
    return {"username": session.username, "csrf_token": session.csrf_token}


def _not_found() -> JSONResponse:
    return _error(404, "feedback_not_found", "No feedback message with this id.")


# --- session ----------------------------------------------------------------


class SignInIn(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


@admin_router.post("/session")
async def sign_in(request: Request) -> Response:
    """Sign in. Checks, in order: 403, 503, 415, 413, 422, 429, 401."""
    if not _origin_ok(request):
        return _csrf_failed().response
    accounts = _accounts(request)
    if not accounts:
        return _error(503, "admin_not_configured", NOT_CONFIGURED)
    if not _is_json(request.headers.get("content-type")):
        return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
    too_large = _error(413, "payload_too_large", f"The body must be at most {MAX_BODY_BYTES} bytes.")
    if _declared_too_large(request, MAX_BODY_BYTES):
        return too_large
    body = await _read_body(request, MAX_BODY_BYTES)
    if body is None:
        return too_large
    try:
        credentials = SignInIn.model_validate_json(body)
    except ValidationError as exc:
        # FastAPI's shape for body errors, without echoing the input (it may hold a password).
        errors = [
            {key: value for key, value in error.items() if key not in ("input", "ctx")}
            | {"loc": ("body", *error["loc"])}
            for error in exc.errors(include_url=False)
        ]
        return await request_validation_exception_handler(request, RequestValidationError(errors))
    client_host = request.client.host if request.client else "unknown"
    retry_after = request.app.state.admin_sign_in_limiter.check_and_consume(client_host)
    if retry_after is not None:
        return _error(
            429,
            "rate_limited",
            "Too many sign-in attempts; try again later.",
            {"Retry-After": str(retry_after)},
        )
    username = await run_in_threadpool(
        authenticate, accounts, credentials.username, credentials.password
    )
    if username is None:
        return _error(401, "invalid_credentials", INVALID_CREDENTIALS)
    token, session = request.app.state.admin_sessions.create(
        username, replacing=request.cookies.get(COOKIE_NAME)
    )
    response = JSONResponse(_session_out(session), headers=ADMIN_HEADERS)
    response.headers.append("set-cookie", _cookie(request, token))
    return response


@admin_router.get("/session")
def get_session(session: Session) -> Response:
    """The signed-in Operator and the session's CSRF token (refreshes the idle time)."""
    return JSONResponse(_session_out(session))


@admin_router.delete("/session")
def sign_out(request: Request, session: CsrfSession) -> Response:
    """Sign out: the session is removed and the cookie cleared."""
    request.app.state.admin_sessions.remove(request.cookies.get(COOKIE_NAME))
    return _clear_cookie(request, Response(status_code=204))


# --- feedback ---------------------------------------------------------------


@admin_router.get("/feedback")
def list_feedback(
    request: Request,
    session: Session,
    from_day: Annotated[dt.date | None, Query(alias="from")] = None,
    to_day: Annotated[dt.date | None, Query(alias="to")] = None,
    reviewed: Literal["all", "yes", "no"] = "all",
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Response:
    """Messages newest first (``id DESC``), ``limit`` per page; ``from``/``to`` are inclusive UTC days."""
    if from_day is not None and to_day is not None and to_day < from_day:
        return _error(422, "invalid_filter", "'to' must not be earlier than 'from'.")
    rows = list_for_admin(
        request.app.state.feedback_engine,
        from_day=from_day,
        to_day=to_day,
        reviewed=reviewed,
        before_id=before_id,
        limit=limit + 1,
    )
    page = rows[:limit]
    next_before_id = page[-1].id if len(rows) > limit else None
    return JSONResponse(
        {"messages": [_message_out(m) for m in page], "next_before_id": next_before_id}
    )


@admin_router.post("/feedback/{message_id}/review")
def review(request: Request, session: CsrfSession, message_id: int) -> Response:
    """Mark as reviewed; an existing ``reviewed_at`` is kept (idempotent)."""
    message = mark_reviewed(request.app.state.feedback_engine, message_id, _now())
    return _not_found() if message is None else JSONResponse(_message_out(message))


@admin_router.delete("/feedback/{message_id}/review")
def unreview(request: Request, session: CsrfSession, message_id: int) -> Response:
    """Clear the reviewed mark."""
    message = clear_reviewed(request.app.state.feedback_engine, message_id)
    return _not_found() if message is None else JSONResponse(_message_out(message))


@admin_router.delete("/feedback/{message_id}")
def delete(request: Request, session: CsrfSession, message_id: int) -> Response:
    """Hard-delete one message."""
    if not delete_message(request.app.state.feedback_engine, message_id):
        return _not_found()
    return Response(status_code=204)


__all__ = ["ADMIN_HEADERS", "COOKIE_NAME", "admin_router"]
