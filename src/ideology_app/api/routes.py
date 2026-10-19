"""The four ``GET /api/v1`` routes. Path parameters only; no query or body."""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.orm import Session

from ideology_app.api import queries
from ideology_app.api.http_cache import (
    IMMUTABLE_CACHE_CONTROL,
    POINTER_CACHE_CONTROL,
    cached_json,
)
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

_RESPONSES: dict[int | str, dict[str, Any]] = {
    304: {"description": "Not Modified"},
    404: {"model": ErrorOut, "description": "Not Found"},
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
