"""Checks ``evidence_proposals`` and ``statement_sources`` (scenario 11), and ``checks_for``.

Pure: plain ``ValidationInput`` data, no database.
"""

import dataclasses

import pytest

from ideology_app.models import ModelGeneration, SourceDocumentRole
from ideology_app.validation import (
    CHECKS,
    V2_CHECKS,
    EvidenceRow,
    PositionRow,
    ProposalRow,
    RunDocument,
    StatementRow,
    ValidationInput,
    checks_for,
)
from ideology_app.validation.evidence_proposals import check_evidence_proposals
from ideology_app.validation.statement_sources import check_statement_sources

TEXT = "Bajar el precio del alquiler."
DOCS = {
    1: RunDocument(1, SourceDocumentRole.MAIN, "https://x/a.pdf", {1: "Intro. " + TEXT, 2: "Fin."}, "ha"),
    2: RunDocument(2, SourceDocumentRole.MAIN, None, {1: "Otra cosa."}, "hb"),
}
PROPOSALS = {
    10: ProposalRow("ha", 1, TEXT),
    11: ProposalRow("hb", 1, "Otra cosa."),
    12: ProposalRow("hz", 1, TEXT),
    13: ProposalRow("ha", 2, TEXT),
    14: ProposalRow("ha", 2, "Fin."),
}
STATEMENT = StatementRow(100, 1, "Debe limitarse el alquiler.", "housing", "Nota.")


def _sided(**changes: object) -> PositionRow:
    base = PositionRow(100, 1, 1, 2, 1, TEXT, 1, "https://x/a.pdf")
    return dataclasses.replace(base, **changes)


def _row(proposal_id: int = 10, document: int = 1, rank: int = 1, codes=("28",)) -> EvidenceRow:
    return EvidenceRow(rank, proposal_id, document, tuple(codes))


def _data(position: PositionRow, rows: tuple[EvidenceRow, ...], sources=(10,)) -> ValidationInput:
    return ValidationInput(
        statements=(STATEMENT,),
        positions=(position,),
        party_ids=(1, 2),
        documents=DOCS,
        generation=ModelGeneration.V2,
        statement_sources={100: tuple(sources)},
        evidence={(100, position.party_id): rows},
        proposals=PROPOSALS,
    )


def test_a_valid_position_passes_both_checks() -> None:
    data = _data(_sided(), (_row(), _row(14, rank=2, codes=("28", "31"))))
    assert check_evidence_proposals(data) == []
    assert check_statement_sources(data) == []
    no_stance = PositionRow(100, 1, 1, None, None, None, None, None)
    assert check_evidence_proposals(_data(no_stance, ())) == []


@pytest.mark.parametrize(
    ("position", "rows", "message"),
    [
        (_sided(), (), "sided position has no evidence proposals"),
        (PositionRow(100, 1, 1, None, None, None, None, None), (_row(),),
         "no stance position has 1 evidence proposals"),
        (_sided(), (_row(11, document=2),),
         "evidence proposal 11: source document 2 is not a source document of party 1 in this run"),
        (_sided(), (_row(12),),
         "evidence proposal 12 is not a proposal of source document 1 (content hash differs)"),
        (_sided(), (_row(13),),
         "evidence proposal 13 text not found on page 2 of source document 1"),
        (_sided(), (_row(codes=()),), "evidence proposal 10 has no constituencies"),
        (_sided(page=2), (_row(),),
         "rank 1 evidence proposal differs from the position's evidence columns"),
        (_sided(url=None), (_row(),),
         "rank 1 evidence proposal differs from the position's evidence columns"),
        (_sided(), (_row(rank=2),), "evidence proposal ranks are not 1..1"),
        (_sided(), (_row(99),), "evidence proposal 99 not found"),
    ],
    ids=[
        "sided-without-evidence", "no-stance-with-evidence", "other-party-document",
        "content-hash", "not-on-page", "no-constituencies", "mirror-page", "mirror-url",
        "ranks", "unknown-proposal",
    ],
)
def test_evidence_proposals_failures(
    position: PositionRow, rows: tuple[EvidenceRow, ...], message: str
) -> None:
    entries = check_evidence_proposals(_data(position, rows))
    assert [(e.message, e.statement_id, e.party_id) for e in entries] == [
        (message, 100, position.party_id)
    ]


def test_statement_sources_failures() -> None:
    no_sources = check_statement_sources(_data(_sided(), (_row(),), sources=()))
    assert [e.message for e in no_sources] == ["statement 1 has no source proposals"]
    foreign = check_statement_sources(_data(_sided(), (_row(),), sources=(10, 12, 77)))
    assert [e.message for e in foreign] == [
        "statement 1 source proposals 12, 77 are not from a source document of this run"
    ]


def test_registry() -> None:
    assert checks_for(ModelGeneration.LEGACY) is CHECKS
    assert checks_for(ModelGeneration.V2) is V2_CHECKS
    assert [c.name for c in V2_CHECKS] == [
        "evidence_quotes", "evidence_proposals", "statement_sources",
        "statement_uniqueness", "context_note", "constituency_snapshot",
        "constituency_validity", "constituency_availability", "constituency_order",
        "statement_rewording",
    ]
    assert [c.name for c in CHECKS] == [
        "evidence_quotes", "party_coverage", "statement_separation", "statement_uniqueness",
        "statement_count", "topic_spread", "context_note",
    ]
