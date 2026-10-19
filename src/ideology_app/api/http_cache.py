"""Strong ETags, ``If-None-Match`` and Cache-Control for the public API.

Lifetimes are module constants, not configuration (see ``ARCHITECTURE.md``).
"""

import hashlib

from fastapi import Request, Response
from pydantic import BaseModel

# Pointers that change on publish (Election list, Election, Published version).
POINTER_CACHE_CONTROL = "public, max-age=60"
# A Dataset Version by id: its body is immutable.
IMMUTABLE_CACHE_CONTROL = "public, max-age=86400, immutable"
# Every error 404: an unknown or candidate id may become valid later.
ERROR_CACHE_CONTROL = "no-store"


def etag_for(body: bytes) -> str:
    """``"<first 32 hex chars of SHA-256(body)>"`` (a strong ETag)."""
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def if_none_match_matches(header: str | None, etag: str) -> bool:
    """Weak comparison (RFC 9110): ``W/`` is ignored; ``*`` matches anything."""
    if not header:
        return False
    for raw in header.split(","):
        tag = raw.strip()
        if tag == "*":
            return True
        if tag.startswith("W/"):
            tag = tag[2:]
        if tag == etag:
            return True
    return False


def cached_json(request: Request, model: BaseModel, cache_control: str) -> Response:
    """200 with the model's JSON and an ETag, or 304 when ``If-None-Match`` matches."""
    body = model.model_dump_json().encode()
    etag = etag_for(body)
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if if_none_match_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
