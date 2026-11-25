"""Read-only views of the stored Constituency rows (constituency-selection-validation).

``constituency_summary`` is the one-line summary of ``pipeline run-v2`` and
``pipeline report``; ``dataset_version_problems`` is ``db check``'s
consistency check of the three tables (and, since ``statement-rewording``,
that no legacy version has ``statement_rewordings`` rows). Only ``SELECT`` statements; the 52-row
table belongs to ``v2-run-inspection``.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    ModelGeneration,
    Statement,
    StatementRewording,
)

_TABLES = (DatasetVersionConstituency, DatasetVersionCandidature, ConstituencyStatement)


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
    version has no row in the three tables nor in ``statement_rewordings``.
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


__all__ = ["constituency_summary", "dataset_version_problems"]
