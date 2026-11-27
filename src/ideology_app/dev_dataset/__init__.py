"""The fictional dev dataset: ``seed(url)`` builds a published v2 Election in a SQLite file.

The seed drives the real phases with the scripted provider (``provider``):
render the bundle, import, Ingestion Ledger and reviews, Proposal extraction,
``no_manifesto``, conflict detection and the Operator decision, then ``run-v2``
(with the rewording file), Validation and publishing. It never inserts
Proposals, Statements, Positions or Dataset Versions directly.

It reads no environment configuration except the target URL (D3): default
``ValidationSettings()`` / ``ConstituencySettings()``, ``precomputed`` and its own
provider. It builds into ``.<stem>-seed-tmp/``, checks the result, fixes every
timestamp to ``dump.SEED_INSTANT`` and only then swaps the database and the
bundle into place (D5); on any failure the previous data stays untouched.

Nothing imports this package except ``cli``. The scripted provider is never in
``llm.PROVIDERS``. See ``docs/specs/dev-dataset.md``.
"""

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ideology_app import bundle_import
from ideology_app import ingestion_ledger as ledgers
from ideology_app.config import ConstituencySettings, GenerationMode, ValidationSettings
from ideology_app.db import make_engine, run_migrations, session_scope
from ideology_app.dev_dataset import bundle, content, dump, guard, provider
from ideology_app.dev_dataset.guard import GuardError, Target
from ideology_app.models import (
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    PipelineRunStatus,
    StatementRewording,
)
from ideology_app.pipeline import v2 as pipelines_v2
from ideology_app.pipeline.runs import RunOutcome
from ideology_app.proposals import conflicts, store
from ideology_app.source_bundle import read_bundle

REPORTED_CODES = ("08", "28", "15", "51")


class SeedError(Exception):
    """The seed failed at ``step``; the previous dev data is untouched."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step


@dataclass(frozen=True)
class SeedReport:
    """What ``seed`` built (plain data)."""

    database: Path
    bundle: Path
    election_id: int
    run_id: int
    dataset_version_id: int
    pool_size: int
    available: int
    unavailable: int
    counts: dict[str, int] = field(default_factory=dict)
    dump_sha256: str = ""


def _step(name: str, call: Callable[[], Any]) -> Any:
    try:
        return call()
    except SeedError:
        raise
    except Exception as exc:
        raise SeedError(name, f"{type(exc).__name__}: {exc}") from exc


def _ledger(directory: Path) -> None:
    ledgers.update_in_dir(directory)
    for document in content.DOCUMENTS:
        if document is content.PIZARRA_DOCUMENT:
            ledgers.review_in_dir(
                directory,
                document.file,
                decision=ledgers.ReviewDecision.DISCARDED,
                reason=ledgers.DiscardReason.INCOMPLETE,
                note=content.PIZARRA_NOTE,
            )
        else:
            ledgers.review_in_dir(directory, document.file, decision=ledgers.ReviewDecision.KEPT)


def _extract(engine: Engine, directory: Path, scripted: Any) -> None:
    plan = store.prepare_extraction(engine, directory, scripted)
    summary = store.execute_plan(engine, scripted, plan)
    if summary.error or summary.failed or summary.stopped:
        raise SeedError("extraction", summary.error or "; ".join(summary.failed) or "stopped")


def _conflicts(engine: Engine, directory: Path, scripted: Any) -> None:
    summary = conflicts.detect(engine, directory, scripted)
    if summary.error or summary.failed or summary.stopped:
        raise SeedError("conflicts", summary.error or "; ".join(summary.failed) or "stopped")
    decision = content.DECISION
    ledgers.decide_conflict_in_dir(
        directory, decision.party, prevails=decision.prevails, over=decision.over,
        reason=decision.reason,
    )


def _run(engine: Engine, directory: Path, scripted: Any) -> RunOutcome:
    with Session(engine) as session:
        phase4 = pipelines_v2.load_phase4(session, directory)
    if pipelines_v2.read_rewordings(directory) is None:
        raise SeedError("run-v2", "the rewording file is missing")
    with session_scope(engine) as session:
        run = pipelines_v2.queue_v2_run(
            session,
            phase4.election_id,
            llm_provider=scripted.name,
            llm_model=scripted.model,
            generation_mode=GenerationMode.PRECOMPUTED,
        )
        run_id = run.id
    return pipelines_v2.execute_v2_run(
        engine, run_id, scripted, directory, ValidationSettings(), ConstituencySettings()
    )


def _self_check(engine: Engine, directory: Path, outcome: Any) -> SeedReport:
    problems: list[str] = []
    if outcome.status is not PipelineRunStatus.PASSED or outcome.dataset_version_id is None:
        raise SeedError(
            "self-check",
            f"run {outcome.run_id} is {outcome.status.value}: {outcome.failure_reason} "
            f"{', '.join(outcome.failed_checks)}".strip(),
        )
    version_id = outcome.dataset_version_id
    loaded = read_bundle(directory)
    problems += ledgers.ledger_problems(loaded)
    with Session(engine) as session:
        problems += bundle_import.check_against_bundle(session, loaded)
        version = session.get(DatasetVersion, version_id)
        assert version is not None
        if version.status is not DatasetVersionStatus.PUBLISHED:
            problems.append(f"dataset version {version_id} is {version.status.value}")
        elections = session.scalars(select(Election)).all()
        if len(elections) != 1 or elections[0].status is not ElectionStatus.ACTIVE:
            problems.append("expected one active Election")
        rows = session.scalars(
            select(DatasetVersionConstituency).where(
                DatasetVersionConstituency.dataset_version_id == version_id
            )
        ).all()
        reasons = set(
            session.scalars(
                select(DatasetVersionCandidature.excluded_reason).where(
                    DatasetVersionCandidature.dataset_version_id == version_id,
                    DatasetVersionCandidature.excluded_reason.is_not(None),
                )
            )
        )
        rewordings = session.scalars(select(StatementRewording)).all()
        election_id = elections[0].id if elections else 0
    unavailable = [(r.constituency_code, r.unavailable_reason) for r in rows if not r.available]
    if unavailable != [("52", "fewer_than_two_parties")]:
        problems.append(f"unexpected unavailable Constituencies: {unavailable}")
    if reasons != {"no_manifesto", "too_few_proposals", "discarded_at_review"}:
        problems.append(f"unexpected Excluded reasons: {sorted(reasons)}")
    if len(rewordings) != 1:
        problems.append(f"{len(rewordings)} applied rewordings, expected 1")
    if problems:
        raise SeedError("self-check", "; ".join(problems))
    counts = {r.constituency_code: r.valid_statement_count for r in rows}
    return SeedReport(
        database=Path(),
        bundle=Path(),
        election_id=election_id,
        run_id=outcome.run_id,
        dataset_version_id=version_id,
        pool_size=outcome.statement_count,
        available=sum(r.available for r in rows),
        unavailable=len(unavailable),
        counts=counts,
    )


def _build(target: Target) -> SeedReport:
    tmp = target.temporary
    database = tmp / target.database.name
    bundle_root = tmp / target.bundle_root.name
    url = f"sqlite:///{database}"
    directory = _step("render", lambda: bundle.render(bundle_root))
    _step("migrate", lambda: run_migrations(url))
    engine = make_engine(url)
    try:
        scripted = provider.build_provider()

        def _import() -> None:
            with session_scope(engine) as session:
                bundle_import.import_bundle(session, read_bundle(directory))

        _step("import", _import)
        _step("ledger", lambda: _ledger(directory))
        _step("extraction", lambda: _extract(engine, directory, scripted))
        _step(
            "no-manifesto",
            lambda: ledgers.no_manifesto_in_dir(directory, "GRAFITO", note=content.GRAFITO_NOTE),
        )
        _step("conflicts", lambda: _conflicts(engine, directory, scripted))
        outcome = _step("run-v2", lambda: _run(engine, directory, scripted))
        report = _step("self-check", lambda: _self_check(engine, directory, outcome))
        _step("timestamps", lambda: dump.normalise_timestamps(engine))
    finally:
        engine.dispose()
    return report


def _swap(target: Target) -> None:
    tmp = target.temporary
    old_bundle = tmp / "previous-bundle"
    moved = False
    if target.bundle_root.exists():
        os.replace(target.bundle_root, old_bundle)
        moved = True
    try:
        os.replace(tmp / target.bundle_root.name, target.bundle_root)
        os.replace(tmp / target.database.name, target.database)
    except BaseException:
        if moved:
            if target.bundle_root.exists():
                shutil.rmtree(target.bundle_root)
            os.replace(old_bundle, target.bundle_root)
        raise


def seed(url: str | None = None) -> SeedReport:
    """Build the dev dataset at ``url`` (``None``: ``guard.DEFAULT_URL``).

    Raises ``GuardError`` (nothing written) or ``SeedError`` (previous data untouched).
    """
    target = guard.check_target(url)
    target.database.parent.mkdir(parents=True, exist_ok=True)
    if target.temporary.exists():
        shutil.rmtree(target.temporary)
    target.temporary.mkdir()
    try:
        report = _build(target)
        _step("swap", lambda: _swap(target))
    finally:
        shutil.rmtree(target.temporary, ignore_errors=True)
    return SeedReport(
        database=target.database,
        bundle=target.bundle,
        election_id=report.election_id,
        run_id=report.run_id,
        dataset_version_id=report.dataset_version_id,
        pool_size=report.pool_size,
        available=report.available,
        unavailable=report.unavailable,
        counts=report.counts,
        dump_sha256=dump.dump_sha256(target.database),
    )


__all__ = ["REPORTED_CODES", "GuardError", "SeedError", "SeedReport", "content", "seed"]
