"""Publishing: a passing run's Dataset Version replaces the Election's Published one.

This module is the only place that changes ``DatasetVersion.status`` or
``Election.status``. ``publish_dataset_version`` runs inside the caller's
session (``validate_run``'s ``passed`` path) and never commits, so the
supersede, the publish and the Election change share the commit that stores
the Validation results.

Publish order is the Pipeline Run id (queue order): a version never replaces a
Published version of a newer run. Concurrency: the Election row is locked
(``FOR UPDATE``; a no-op on SQLite, where the caller's earlier write already
holds the database write lock), and the partial unique index
``uq_dataset_versions_published_election_id`` (migration ``0007``) rejects a
second Published version if anything gets past the lock.
"""

from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ideology_app.models import DatasetVersion, DatasetVersionStatus, Election, ElectionStatus


@dataclass(frozen=True)
class PublishOutcome:
    """What publishing a passed run's version did (plain data, safe after the session).

    ``published_*`` always names the version that is live after the call: the
    run's own when ``published``, else the newer run's version that stays live.
    """

    election_id: int
    published: bool
    published_dataset_version_id: int
    published_run_id: int
    superseded_dataset_version_id: int | None = None


def election_lock_statement(election_id: int) -> Select[tuple[Election]]:
    """Select the Election row ``FOR UPDATE`` (serialises publishers on PostgreSQL)."""
    return select(Election).where(Election.id == election_id).with_for_update()


def get_published_dataset_version(session: Session, election_id: int) -> DatasetVersion | None:
    """The Election's Published Dataset Version, or ``None`` before its first publish."""
    return session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.election_id == election_id,
            DatasetVersion.status == DatasetVersionStatus.PUBLISHED,
        )
    )


def publish_dataset_version(session: Session, version: DatasetVersion) -> PublishOutcome:
    """Publish a ``candidate`` version unless a newer run's version is Published. Flushes.

    Supersedes the current Published version (if any) and sets a ``draft``
    Election ``active``. Never commits: the caller's commit holds it all.
    """
    if version.status is not DatasetVersionStatus.CANDIDATE:
        raise ValueError(
            f"dataset version {version.id} is {version.status.value}, expected candidate"
        )
    election = session.scalars(election_lock_statement(version.election_id)).one()
    current = get_published_dataset_version(session, version.election_id)
    if current is not None and current.pipeline_run_id > version.pipeline_run_id:
        return PublishOutcome(
            election_id=election.id,
            published=False,
            published_dataset_version_id=current.id,
            published_run_id=current.pipeline_run_id,
        )
    superseded_id: int | None = None
    if current is not None:
        current.status = DatasetVersionStatus.SUPERSEDED
        superseded_id = current.id
        # Flush before publishing: the unit of work orders UPDATEs by primary key,
        # so without it the partial unique index could see two Published rows.
        session.flush()
    version.status = DatasetVersionStatus.PUBLISHED
    if election.status is ElectionStatus.DRAFT:
        election.status = ElectionStatus.ACTIVE
    session.flush()
    return PublishOutcome(
        election_id=election.id,
        published=True,
        published_dataset_version_id=version.id,
        published_run_id=version.pipeline_run_id,
        superseded_dataset_version_id=superseded_id,
    )
