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
    published_dataset_version_generation: Literal["legacy", "v2"] | None = Field(
        description="Which model the Published Dataset Version follows: \"legacy\" "
        "(read /api/v1/dataset-versions/{id}) or \"v2\" (read "
        "/api/v1/dataset-versions/{id}/constituencies). Null exactly when "
        "published_dataset_version_id is null."
    )


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
    context_note: str | None = Field(
        description=(
            "Neutral AI-generated context note; null for Dataset Versions created "
            "before it existed."
        )
    )


class DatasetVersionOut(_Out):
    id: int
    election_id: int
    created_at: str = Field(description="UTC, YYYY-MM-DDTHH:MM:SSZ.")
    statements: list[StatementOut]
    parties: list[PartyOut]
    questionnaire_lengths: list[int] = Field(
        description=(
            "Offered questionnaire lengths, ascending; the last is the number of "
            "Statements. A questionnaire of length N is the first N Statements. "
            "Dataset Versions created before lengths existed offer only their full length."
        )
    )


# --- v2 Dataset Versions, one Constituency at a time (public-dataset-api-v2) ---------

UnavailableReasonOut = Literal["fewer_than_two_parties", "too_few_statements", "low_party_coverage"]
ExcludedReasonOut = Literal["no_manifesto", "discarded_at_review", "too_few_proposals"]
ConstituencyCodeOut = Annotated[str, Field(pattern="^[0-9]{2}$")]

_UNAVAILABLE_DESCRIPTION = (
    "Why the Constituency is unavailable, the first rule that fails: "
    "fewer_than_two_parties, too_few_statements or low_party_coverage. "
    "Null exactly when available."
)


class ConstituencySummaryOut(_Out):
    code: ConstituencyCodeOut = Field(description="INE province code, two digits.")
    name: str
    available: bool
    unavailable_reason: UnavailableReasonOut | None = Field(description=_UNAVAILABLE_DESCRIPTION)
    valid_statement_count: int = Field(
        description="Statements valid in this Constituency (at least one Party running "
        "there in favour and one against)."
    )
    offered_lengths: list[int] = Field(
        description="Offered questionnaire lengths, ascending (20, 30, 40, 50 up to the "
        "valid count, or only the valid count when it is below 20); empty when unavailable."
    )


class ConstituencyListOut(_Out):
    """Every Constituency of a v2 Dataset Version (52 rows, in code order)."""

    id: int
    election_id: int
    created_at: str = Field(description="UTC, YYYY-MM-DDTHH:MM:SSZ.")
    constituencies: list[ConstituencySummaryOut]


class ConstituencyStatementOut(_Out):
    id: int
    rank: int = Field(
        description="1-based priority in this Constituency. A questionnaire of length L "
        "is ranks 1..L."
    )
    text: str = Field(description="The final text of the Statement.")
    topic: str
    context_note: str | None


class ProposalOut(_Out):
    """A Proposal: a verbatim measure of a manifesto, on the page it starts on."""

    id: int
    text: str = Field(description="The Proposal exactly as extracted from the manifesto.")
    page: int
    url: str | None = Field(
        description="The Source Document's URL for URL documents, null for uploads and "
        "bundle files. Link as url + '#page=' + page."
    )
    source_document_id: int = Field(
        description="The Party's own Source Document row: a manifesto shared by several "
        "Parties gives the same Proposal id with a different source_document_id per Party."
    )


class ConstituencyPositionOut(_Out):
    statement_id: int
    value: PositionValue = Field(
        description="The Party's value in this Constituency (S5): its stored value only "
        "when one of its Evidence Proposals counts here, else \"no_stance\"."
    )
    evidence_proposal_ids: list[int] = Field(
        description="Ids (in the Party's evidence list) of the Evidence Proposals that "
        "count in this Constituency, in rank order. Empty exactly when value is "
        "\"no_stance\"; a neutral 0 has Evidence."
    )


class ConstituencyPartyOut(_Out):
    id: int
    name: str
    short_name: str
    logo_url: str | None = Field(
        description="Same-origin path of the Party's logo "
        "(/api/v1/parties/{id}/logo?v=<sha256 prefix>), or null when it has none."
    )
    positions: list[ConstituencyPositionOut] = Field(
        description="One per Statement, in the body's statements order; empty when the "
        "Constituency is unavailable."
    )
    evidence: list[ProposalOut] = Field(
        description="Every Proposal referenced by this Party's positions, once each, by id."
    )


class ExcludedPartyOut(_Out):
    id: int
    name: str
    short_name: str
    reason: ExcludedReasonOut = Field(
        description="Why the Party has no Positions: no_manifesto, discarded_at_review or "
        "too_few_proposals."
    )


class ConstituencyQuestionnaireOut(_Out):
    """One Constituency of a v2 Dataset Version: its ranked Statements and its Parties."""

    dataset_version_id: int
    code: ConstituencyCodeOut
    name: str
    available: bool
    unavailable_reason: UnavailableReasonOut | None = Field(description=_UNAVAILABLE_DESCRIPTION)
    offered_lengths: list[int] = Field(description="Ascending; empty when unavailable.")
    statements: list[ConstituencyStatementOut] = Field(
        description="All the Constituency's Statements in rank order; empty when unavailable."
    )
    parties: list[ConstituencyPartyOut] = Field(
        description="The non-Excluded Parties running in this Constituency, by id."
    )
    excluded_parties: list[ExcludedPartyOut] = Field(
        description="The Excluded Parties running in this Constituency, by id."
    )


class PartyProposalsOut(_Out):
    party_id: int
    proposals: list[ProposalOut] = Field(
        description="The Party's Proposals that count in this Constituency and carry the "
        "category (main or not), in counted order. May be empty."
    )


class ConstituencyProposalsOut(_Out):
    """Each running Party's Proposals in one category, for the Comparador."""

    dataset_version_id: int
    code: ConstituencyCodeOut
    category: str = Field(description="A topic catalog key.")
    parties: list[PartyProposalsOut] = Field(
        description="Every non-Excluded Party running in this Constituency, by id, "
        "including those with no Proposal in the category."
    )


class LegalHolderOut(_Out):
    name: str
    nif: str | None = Field(description="The holder's DNI or NIE, or null when not published.")


class LegalNoticeOut(_Out):
    """The site's holders and contact (legal-privacy-page), from the ``LEGAL_*`` settings.

    Empty (``holders: []``, nulls) when nothing is configured.
    """

    holders: list[LegalHolderOut]
    contact_email: str | None
    address: str | None


class DonationOut(_Out):
    """The project's donation link (donate-buymeacoffee), from ``DONATION_URL``.

    ``url`` is null when the setting is unset, blank or invalid.
    """

    url: str | None = Field(
        description="https://www.buymeacoffee.com/<perfil> or https://buymeacoffee.com/<perfil>, "
        "or null when no valid profile is configured."
    )


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
