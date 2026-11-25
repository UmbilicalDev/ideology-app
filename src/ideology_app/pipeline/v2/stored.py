"""Read-only views of the stored Constituency rows (constituency-selection-validation).

``constituency_summary`` is the one-line summary of ``pipeline run-v2`` and
``pipeline report``; ``dataset_version_problems`` is ``db check``'s
consistency check of the three tables (and, since ``statement-rewording``,
that no legacy version has ``statement_rewordings`` rows; since
``public-dataset-api-v2``, the frozen counted Proposals). Only ``SELECT``
statements; the 52-row table of ``pipeline report`` lives in ``inspection``
(v2-run-inspection).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    ModelGeneration,
    PartyPosition,
    PartyPositionProposal,
    Statement,
    StatementRewording,
)

_TABLES = (
    DatasetVersionConstituency,
    DatasetVersionCandidature,
    ConstituencyStatement,
    DatasetVersionProposal,
)


def constituency_summary(session: Session, dataset_version_id: int) -> str | None:
    """``50 available, 2 unavailable (31 fewer_than_two_parties, ...); 3 statements valid
    in no available constituency``, or ``None`` when the version has no Constituency rows."""
    rows = session.execute(
        select(
            DatasetVersionConstituency.constituency_code,
            DatasetVersionConstituency.available,
            DatasetVersionConstituency.unavailable_reason,
        )
        .where(DatasetVersionConstituency.dataset_version_id == dataset_version_id)
        .order_by(DatasetVersionConstituency.constituency_code)
    ).all()
    if not rows:
        return None
    unavailable = [f"{code} {reason}" for code, available, reason in rows if not available]
    listed = select(ConstituencyStatement.statement_id).where(
        ConstituencyStatement.dataset_version_id == dataset_version_id
    )
    nowhere = session.scalar(
        select(func.count())
        .select_from(Statement)
        .where(
            Statement.dataset_version_id == dataset_version_id,
            Statement.id.not_in(listed),
        )
    )
    line = f"{len(rows) - len(unavailable)} available, {len(unavailable)} unavailable"
    if unavailable:
        line += f" ({', '.join(unavailable)})"
    return f"{line}; {nowhere or 0} statements valid in no available constituency"


def dataset_version_problems(session: Session) -> list[str]:
    """Inconsistencies of the stored Constituency rows, one line each (``db check``).

    Every v2 Dataset Version has one row per seeded Constituency and at least
    one candidature row, and each available row's ranks are
    1..``valid_statement_count`` (an unavailable one lists none). A legacy
    version has no row in the three tables nor in ``statement_rewordings``
    nor in ``dataset_version_proposals``. A v2 version has frozen counted
    Proposals, and every Evidence row (``party_position_proposals``) of its
    Positions is frozen for the same Party with the same Constituencies.
    Live candidatures are never read.
    """
    problems: list[str] = []
    codes = [code for code, _ in CONSTITUENCIES]
    for version_id, generation in session.execute(
        select(DatasetVersion.id, DatasetVersion.model_generation).order_by(DatasetVersion.id)
    ):
        counts = {
            model.__tablename__: session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.dataset_version_id == version_id)
            )
            or 0
            for model in _TABLES
        }
        if generation is not ModelGeneration.V2:
            counts[StatementRewording.__tablename__] = (
                session.scalar(
                    select(func.count())
                    .select_from(StatementRewording)
                    .join(Statement, StatementRewording.statement_id == Statement.id)
                    .where(Statement.dataset_version_id == version_id)
                )
                or 0
            )
            problems.extend(
                f"dataset version {version_id} (legacy) has {count} rows in {table}"
                for table, count in counts.items()
                if count
            )
            continue
        stored = session.execute(
            select(
                DatasetVersionConstituency.constituency_code,
                DatasetVersionConstituency.available,
                DatasetVersionConstituency.valid_statement_count,
            ).where(DatasetVersionConstituency.dataset_version_id == version_id)
        ).all()
        found = sorted(code for code, _, _ in stored)
        if found != codes:
            problems.append(
                f"dataset version {version_id} has {len(found)} constituency rows, "
                f"expected one for each of the {len(codes)} constituencies"
            )
        if not counts[DatasetVersionCandidature.__tablename__]:
            problems.append(f"dataset version {version_id} has no candidature rows")
        problems.extend(_frozen_proposal_problems(session, version_id, counts))
        ranks: dict[str, list[int]] = {}
        for code, rank in session.execute(
            select(ConstituencyStatement.constituency_code, ConstituencyStatement.rank)
            .where(ConstituencyStatement.dataset_version_id == version_id)
            .order_by(ConstituencyStatement.constituency_code, ConstituencyStatement.rank)
        ):
            ranks.setdefault(code, []).append(rank)
        for code, available, count in sorted(stored):
            expected = list(range(1, count + 1)) if available else []
            if ranks.get(code, []) != expected:
                problems.append(
                    f"dataset version {version_id}, constituency {code}: ranks are not "
                    f"1..{count if available else 0}"
                )
    return problems


def _frozen_proposal_problems(
    session: Session, version_id: int, counts: dict[str, int]
) -> list[str]:
    """A v2 version's ``dataset_version_proposals`` checks (public-dataset-api-v2 A8)."""
    if not counts[DatasetVersionProposal.__tablename__]:
        return [f"dataset version {version_id} has no frozen counted proposals"]
    frozen = {
        (party_id, proposal_id): list(codes)
        for party_id, proposal_id, codes in session.execute(
            select(
                DatasetVersionProposal.party_id,
                DatasetVersionProposal.proposal_id,
                DatasetVersionProposal.constituencies,
            ).where(DatasetVersionProposal.dataset_version_id == version_id)
        )
    }
    # Deduplicated in Python: DISTINCT over a JSON column is not portable.
    reported: set[tuple[int, int]] = set()
    problems: list[str] = []
    for party_id, proposal_id, codes in session.execute(
        select(
            PartyPosition.party_id,
            PartyPositionProposal.proposal_id,
            PartyPositionProposal.constituencies,
        )
        .join(PartyPosition, PartyPositionProposal.party_position_id == PartyPosition.id)
        .join(Statement, PartyPosition.statement_id == Statement.id)
        .where(Statement.dataset_version_id == version_id)
        .order_by(PartyPosition.party_id, PartyPositionProposal.proposal_id)
    ):
        key = (party_id, proposal_id)
        if key not in reported and frozen.get(key) != list(codes):
            reported.add(key)
            problems.append(
                f"dataset version {version_id}: evidence proposal {proposal_id} of party "
                f"{party_id} is not frozen with the same constituencies"
            )
    return problems


__all__ = ["constituency_summary", "dataset_version_problems"]
