"""Response models of the public API. Field order is the JSON key order.

The contract is snake_case and stable: ``/api/v1`` changes are additive only.
A ``DatasetVersionOut`` holds only immutable data (no status, no Published
pointer), so it can be cached as ``immutable``.
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ideology_app.feedback.message import clean_message

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
    logo_url: str | None = Field(
        description="Same-origin path of the Party's logo "
        "(/api/v1/parties/{id}/logo?v=<sha256 prefix>), or null when it has none."
    )
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


class FeedbackIn(BaseModel):
    """The body of ``POST /api/v1/feedback``. Any other key is refused (422)."""

    model_config = ConfigDict(strict=True, extra="forbid")

    message: str = Field(
        description="1..500 Unicode code points after trimming; no control characters "
        "other than newline. Stored trimmed."
    )
    origin: Literal["landing", "results"] = Field(description="The screen it was sent from.")
    website: str | None = Field(
        default=None, description="Leave empty. A non-empty value is accepted and discarded."
    )

    @field_validator("message")
    @classmethod
    def _clean(cls, value: str) -> str:
        return clean_message(value)


class FeedbackAcceptedOut(_Out):
    status: Literal["received"]
