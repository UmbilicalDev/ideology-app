"""Check ``statement_sources`` (v2 runs): every Statement has its source Proposals.

Every Statement has one or more source Proposals, and each one is a Proposal
of a Source Document the run read (its ``content_hash`` is one of the run
documents'). One entry per failing Statement, in Statement order. Pure.
"""

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "statement_sources"


def check_statement_sources(data: ValidationInput) -> list[ReportEntry]:
    """Entries for Statements without sources or with a source from outside the run."""
    hashes = {d.content_hash for d in data.documents.values() if d.content_hash}
    entries: list[ReportEntry] = []
    for statement in data.statements:
        sources = data.statement_sources.get(statement.id, ())
        if not sources:
            entries.append(
                ReportEntry(
                    f"statement {statement.position} has no source proposals",
                    statement_id=statement.id,
                )
            )
            continue
        foreign = [
            pid
            for pid in sources
            if pid not in data.proposals or data.proposals[pid].content_hash not in hashes
        ]
        if foreign:
            entries.append(
                ReportEntry(
                    f"statement {statement.position} source proposals "
                    f"{', '.join(map(str, foreign))} are not from a source document of this run",
                    statement_id=statement.id,
                )
            )
    return entries


STATEMENT_SOURCES = Check(NAME, check_statement_sources)
