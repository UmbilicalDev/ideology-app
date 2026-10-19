"""Response models of the public API. Field order is the JSON key order.

The contract is snake_case and stable: ``/api/v1`` changes are additive only.
A ``DatasetVersionOut`` holds only immutable data (no status, no Published
pointer), so it can be cached as ``immutable``.
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# What ``packages/core`` match-score consumes: -2..+2 or ``"no_stance"`` (``PartyPosition.engine_value``).
PositionValue = Annotated[int, Field(ge=-2, le=2, strict=True)] | Literal["no_stance"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ElectionOut(_Out):
    id: int
    country: str
    type: str
    date: dt.date
    name: str
    status: Literal["draft", "active", "archived"]
    published_dataset_version_id: int | None


class ElectionListOut(_Out):
    elections: list[ElectionOut]


class EvidenceOut(_Out):
    quote: str
    page: int
    url: str | None = Field(
        description="The Source Document's URL for URL documents, null for uploads. "
        "Link as url + '#page=' + page."
    )
    source_document_id: int


class PositionOut(_Out):
    statement_id: int
    value: PositionValue
    evidence: EvidenceOut | None = Field(description='Null exactly when value is "no_stance".')


class PartyOut(_Out):
    id: int
    name: str
    short_name: str
    positions: list[PositionOut]


class StatementOut(_Out):
    id: int
    position: int
    text: str
    topic: str


class DatasetVersionOut(_Out):
    id: int
    election_id: int
    created_at: str = Field(description="UTC, YYYY-MM-DDTHH:MM:SSZ.")
    statements: list[StatementOut]
    parties: list[PartyOut]


class ErrorBody(_Out):
    code: str
    message: str


class ErrorOut(_Out):
    error: ErrorBody
