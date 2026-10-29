"""``POST /api/v1/feedback``: the only write route (feedback-api).

It writes only the feedback store (``app.state.feedback_engine``) and never
touches the shared database Engine. The body is parsed by hand so the size
and media type are checked before anything is read or parsed. Order of
checks: 415 -> 413 -> 422 -> 429 -> honeypot -> store. Every response is
``Cache-Control: no-store``. Nothing about the request (address, headers,
message text) is logged.
"""

import datetime as dt
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ideology_app.api.http_cache import ERROR_CACHE_CONTROL
from ideology_app.api.request_body import _declared_too_large, _is_json, _read_body
from ideology_app.api.schemas import ErrorOut, FeedbackAcceptedOut, FeedbackIn
from ideology_app.feedback.message import trim
from ideology_app.feedback.store import add_message

# Any valid body fits: 500 astral characters as \uXXXX\uXXXX escapes is about 6000 bytes.
MAX_BODY_BYTES = 8192
NO_STORE = {"Cache-Control": ERROR_CACHE_CONTROL}

feedback_router = APIRouter(prefix="/api/v1", tags=["feedback"])


def _now() -> dt.datetime:
    """The current time (UTC). Tests patch this seam."""
    return dt.datetime.now(dt.UTC)


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
        headers={**NO_STORE, **(headers or {})},
    )


def _too_large() -> JSONResponse:
    return _error(413, "payload_too_large", f"The body must be at most {MAX_BODY_BYTES} bytes.")


_RESPONSES: dict[int | str, dict[str, Any]] = {
    201: {"model": FeedbackAcceptedOut, "description": "Received (also for the honeypot)."},
    413: {"model": ErrorOut, "description": "Body larger than 8192 bytes."},
    415: {"model": ErrorOut, "description": "Content-Type is not application/json."},
    422: {"description": "Invalid JSON, unknown key, or a message or origin that breaks the rule."},
    429: {"model": ErrorOut, "description": "Too many messages; see Retry-After."},
}


@feedback_router.post(
    "/feedback",
    operation_id="sendFeedback",
    status_code=201,
    response_model=None,
    responses=_RESPONSES,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": FeedbackIn.model_json_schema()}},
        }
    },
)
async def send_feedback(request: Request) -> Response:
    """Store one anonymous feedback message. Only ``message`` and ``origin`` are kept."""
    if not _is_json(request.headers.get("content-type")):
        return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
    if _declared_too_large(request, MAX_BODY_BYTES):
        return _too_large()
    body = await _read_body(request, MAX_BODY_BYTES)
    if body is None:
        return _too_large()
    try:
        feedback = FeedbackIn.model_validate_json(body)
    except ValidationError as exc:
        # FastAPI's own shape for body errors: ``loc`` starts with "body".
        # Invalid JSON reports the raw bytes as ``input``: decoded so they encode as JSON.
        errors = [
            {
                **error,
                "loc": ("body", *error["loc"]),
                **(
                    {"input": error["input"].decode("utf-8", "replace")}
                    if isinstance(error.get("input"), bytes)
                    else {}
                ),
            }
            for error in exc.errors(include_url=False)
        ]
        response = await request_validation_exception_handler(
            request, RequestValidationError(errors)
        )
        response.headers.update(NO_STORE)
        return response
    client_host = request.client.host if request.client else "unknown"
    retry_after = request.app.state.feedback_rate_limiter.check_and_consume(client_host)
    if retry_after is not None:
        return _error(
            429,
            "rate_limited",
            "Too many messages; try again later.",
            {"Retry-After": str(retry_after)},
        )
    if feedback.website is None or not trim(feedback.website):
        await run_in_threadpool(
            add_message,
            request.app.state.feedback_engine,
            feedback.message,
            feedback.origin,
            _now(),
        )
    return JSONResponse(status_code=201, content={"status": "received"}, headers=NO_STORE)
