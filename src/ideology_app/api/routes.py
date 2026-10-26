"""The ``GET /api/v1`` routes. Path parameters only; no declared query or body.

Four JSON routes, plus ``getPartyLogo``, which serves a Party's logo bytes and
reads only the cache-busting ``v`` from the raw query string to choose its
Cache-Control (the body never depends on it).
"""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.orm import Session

from ideology_app.api import queries
from ideology_app.api.http_cache import (
    IMMUTABLE_CACHE_CONTROL,
    POINTER_CACHE_CONTROL,
    cached_json,
    logo_response,
)
from ideology_app.party_logos import MEDIA_TYPES, logo_version
from ideology_app.api.schemas import DatasetVersionOut, ElectionListOut, ElectionOut, ErrorOut

# Fits a 32-bit integer column; larger values would overflow SQLite (500).
MAX_ID = 2_147_483_647


def get_session(request: Request) -> Iterator[Session]:
    """A read-only Session on the app's Engine; closed with no commit."""
    session = Session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
ElectionId = Annotated[int, Path(ge=1, le=MAX_ID)]
DatasetVersionId = Annotated[int, Path(ge=1, le=MAX_ID)]
PartyId = Annotated[int, Path(ge=1, le=MAX_ID)]

_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "Not Modified"},
    404: {"model": ErrorOut, "description": "Not Found"},
}

_LOGO_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The logo bytes, with the stored media type.",
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in MEDIA_TYPES
        },
    },
    **_RESPONSES,
}

router = APIRouter(prefix="/api/v1", tags=["public"])


@router.get(
    "/elections",
    response_model=ElectionListOut,
    operation_id="listElections",
    responses=_RESPONSES,
)
def list_elections(request: Request, session: SessionDep) -> Response:
    """The ``active`` Elections, newest first."""
    return cached_json(request, queries.list_active_elections(session), POINTER_CACHE_CONTROL)


@router.get(
    "/elections/{election_id}",
    response_model=ElectionOut,
    operation_id="getElection",
    responses=_RESPONSES,
)
def get_election(request: Request, session: SessionDep, election_id: ElectionId) -> Response:
    """One Election (any status) with its Published Dataset Version id."""
    return cached_json(request, queries.get_election(session, election_id), POINTER_CACHE_CONTROL)


@router.get(
    "/elections/{election_id}/published-dataset-version",
    response_model=DatasetVersionOut,
    operation_id="getPublishedDatasetVersion",
    responses=_RESPONSES,
)
def get_published_dataset_version(
    request: Request, session: SessionDep, election_id: ElectionId
) -> Response:
    """The Election's Published Dataset Version (same body as by id)."""
    return cached_json(
        request, queries.get_published_version(session, election_id), POINTER_CACHE_CONTROL
    )


@router.get(
    "/dataset-versions/{dataset_version_id}",
    response_model=DatasetVersionOut,
    operation_id="getDatasetVersion",
    responses=_RESPONSES,
)
def get_dataset_version(
    request: Request, session: SessionDep, dataset_version_id: DatasetVersionId
) -> Response:
    """A Published or Superseded Dataset Version by id (old Share Links)."""
    return cached_json(
        request, queries.get_public_version(session, dataset_version_id), IMMUTABLE_CACHE_CONTROL
    )


@router.get(
    "/parties/{party_id}/logo",
    operation_id="getPartyLogo",
    response_class=Response,
    responses=_LOGO_RESPONSES,
)
def get_party_logo(request: Request, session: SessionDep, party_id: PartyId) -> Response:
    """A Party's logo (PNG, WebP or SVG), served with ``nosniff`` and a sandbox CSP.

    Immutable for a year when ``v`` is the current SHA-256 prefix (the
    ``logo_url`` of the dataset API); ``no-cache`` otherwise.
    """
    data, media_type, sha256 = queries.get_party_logo(session, party_id)
    return logo_response(request, data, media_type, sha256, logo_version(sha256))
