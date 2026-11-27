"""Check ``evidence_proposals`` (domain check 2 on Proposal Evidence, v2 runs).

For every Party Position of a v2 Dataset Version:

- a sided Position (value set) has one or more Evidence Proposals, ranked
  1..n, and a ``no stance`` Position has none;
- each Evidence row's Source Document is a document of that Party in this
  run, the Proposal's ``content_hash`` equals that document's, and the
  Proposal text starts on the Proposal's page of that document
  (``find_quote_miss``, the one matcher);
- each Evidence row lists at least one Constituency;
- rank 1 equals the Position's mirrored Evidence columns: document, quote (the
  Proposal text exactly), page and the document's URL.

One entry per failing Position (its first failure). Pure.
"""

from ideology_app.validation.base import (
    Check,
    EvidenceRow,
    PositionRow,
    ReportEntry,
    ValidationInput,
)
from ideology_app.validation.evidence_quotes import find_quote_miss, normalize_pages

NAME = "evidence_proposals"


def _row_failure(
    position: PositionRow,
    row: EvidenceRow,
    data: ValidationInput,
    normalised: dict[int, dict[int, str]],
) -> str | None:
    document_id = row.source_document_id
    document = data.documents.get(document_id)
    if document is None or document.party_id != position.party_id:
        return (
            f"evidence proposal {row.proposal_id}: source document {document_id} is not a "
            f"source document of party {position.party_id} in this run"
        )
    proposal = data.proposals.get(row.proposal_id)
    if proposal is None:
        return f"evidence proposal {row.proposal_id} not found"
    if proposal.content_hash != document.content_hash:
        return (
            f"evidence proposal {row.proposal_id} is not a proposal of source document "
            f"{document_id} (content hash differs)"
        )
    if proposal.page not in document.pages:
        return (
            f"evidence proposal {row.proposal_id}: page {proposal.page} does not exist in "
            f"source document {document_id}"
        )
    if document_id not in normalised:
        normalised[document_id] = normalize_pages(document.pages.items())
    if find_quote_miss(proposal.text, normalised[document_id], proposal.page) is not None:
        return (
            f"evidence proposal {row.proposal_id} text not found on page {proposal.page} "
            f"of source document {document_id}"
        )
    if not row.constituencies:
        return f"evidence proposal {row.proposal_id} has no constituencies"
    return None


def _first_failure(
    position: PositionRow, data: ValidationInput, normalised: dict[int, dict[int, str]]
) -> str | None:
    rows = data.evidence.get((position.statement_id, position.party_id), ())
    if position.value is None:
        if rows:
            return f"no stance position has {len(rows)} evidence proposals"
        return None
    if not rows:
        return "sided position has no evidence proposals"
    if [row.rank for row in rows] != list(range(1, len(rows) + 1)):
        return "evidence proposal ranks are not 1.." + str(len(rows))
    for row in rows:
        message = _row_failure(position, row, data, normalised)
        if message is not None:
            return message
    first = rows[0]
    proposal = data.proposals[first.proposal_id]
    document = data.documents[first.source_document_id]
    mirror = (first.source_document_id, proposal.text, proposal.page, document.source_url)
    if (position.document_id, position.quote, position.page, position.url) != mirror:
        return "rank 1 evidence proposal differs from the position's evidence columns"
    return None


def check_evidence_proposals(data: ValidationInput) -> list[ReportEntry]:
    """One entry per Position whose Proposal Evidence fails a rule."""
    normalised: dict[int, dict[int, str]] = {}
    entries: list[ReportEntry] = []
    for position in data.positions:
        message = _first_failure(position, data, normalised)
        if message is not None:
            entries.append(ReportEntry(message, position.statement_id, position.party_id))
    return entries


EVIDENCE_PROPOSALS = Check(NAME, check_evidence_proposals)
