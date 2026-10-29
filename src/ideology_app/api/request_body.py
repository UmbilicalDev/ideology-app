"""Hand-read JSON bodies: the media-type check and a size-capped read.

Shared by ``feedback_routes`` (the Voter POST) and ``admin_routes`` so the
size and media type are checked before anything is parsed.
"""

from fastapi import Request


def _is_json(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


def _declared_too_large(request: Request, max_bytes: int) -> bool:
    length = request.headers.get("content-length")
    return length is not None and length.strip().isdigit() and int(length) > max_bytes


async def _read_body(request: Request, max_bytes: int) -> bytes | None:
    """The body, or ``None`` as soon as it passes ``max_bytes``."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            return None
    return bytes(body)
