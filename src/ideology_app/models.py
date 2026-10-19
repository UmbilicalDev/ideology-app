"""SQLAlchemy ORM models. The schema itself is created only by Alembic."""

import datetime as dt
from enum import StrEnum
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ideology_app.config import GenerationMode

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(column_0_label)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class ElectionType(StrEnum):
    GENERAL = "general"


class ElectionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


def _enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    return sa.Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        name=name,
    )


class Election(Base):
    __tablename__ = "elections"
    __table_args__ = (sa.UniqueConstraint("country", "type", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(sa.String(2))
    type: Mapped[ElectionType] = mapped_column(_enum(ElectionType, "election_type"))
    date: Mapped[dt.date] = mapped_column(sa.Date)
    name: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[ElectionStatus] = mapped_column(
        _enum(ElectionStatus, "election_status"), default=ElectionStatus.DRAFT
    )

    parties: Mapped[list["Party"]] = relationship(
        back_populates="election", order_by="Party.id", passive_deletes=True
    )
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="election", order_by="PipelineRun.id", passive_deletes=True
    )
    dataset_versions: Mapped[list["DatasetVersion"]] = relationship(
        back_populates="election", order_by="DatasetVersion.id", passive_deletes=True
    )


class Party(Base):
    __tablename__ = "parties"
    __table_args__ = (
        sa.UniqueConstraint("election_id", "name"),
        sa.UniqueConstraint("election_id", "short_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(
        sa.ForeignKey("elections.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(sa.String(200))
    short_name: Mapped[str] = mapped_column(sa.String(50))

    election: Mapped[Election] = relationship(back_populates="parties")
    source_documents: Mapped[list["SourceDocument"]] = relationship(
        back_populates="party", order_by="SourceDocument.id", passive_deletes=True
    )


class SourceDocumentOrigin(StrEnum):
    UPLOAD = "upload"
    URL = "url"


class SourceDocumentStatus(StrEnum):
    REGISTERED = "registered"
    FETCHED = "fetched"
    PARSED = "parsed"
    FAILED = "failed"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SourceDocument(Base):
    """A manifesto file of a Party. The stored file is ``<content_hash>.pdf``."""

    __tablename__ = "source_documents"
    __table_args__ = (
        sa.UniqueConstraint("party_id", "content_hash"),
        sa.CheckConstraint(
            "(origin = 'url' AND source_url IS NOT NULL) "
            "OR (origin = 'upload' AND source_url IS NULL)",
            name="source_url_matches_origin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    party_id: Mapped[int] = mapped_column(
        sa.ForeignKey("parties.id", ondelete="CASCADE"), index=True
    )
    origin: Mapped[SourceDocumentOrigin] = mapped_column(
        _enum(SourceDocumentOrigin, "source_document_origin")
    )
    status: Mapped[SourceDocumentStatus] = mapped_column(
        _enum(SourceDocumentStatus, "source_document_status")
    )
    original_filename: Mapped[str | None] = mapped_column(sa.String(255))
    # The URL as given by the Operator; set exactly when origin is ``url``.
    source_url: Mapped[str | None] = mapped_column(sa.String(2048))
    # Null only for a URL document whose download failed.
    content_hash: Mapped[str | None] = mapped_column(sa.String(64))
    page_count: Mapped[int | None] = mapped_column(sa.Integer)
    failure_reason: Mapped[str | None] = mapped_column(sa.String(500))
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )

    party: Mapped[Party] = relationship(back_populates="source_documents")
    pages: Mapped[list["SourceDocumentPage"]] = relationship(
        back_populates="source_document",
        order_by="SourceDocumentPage.page_number",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def stored_filename(self) -> str | None:
        return f"{self.content_hash}.pdf" if self.content_hash else None


class SourceDocumentPage(Base):
    """The extracted text of one page (1-based) of a Source Document."""

    __tablename__ = "source_document_pages"
    __table_args__ = (
        sa.UniqueConstraint("source_document_id", "page_number"),
        sa.CheckConstraint("page_number >= 1", name="page_number_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(
        sa.ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    page_number: Mapped[int] = mapped_column(sa.Integer)
    text: Mapped[str] = mapped_column(sa.Text)

    source_document: Mapped[SourceDocument] = relationship(back_populates="pages")


class PipelineRunStatus(StrEnum):
    """``queued`` -> ``running`` -> ``validating`` -> ``passed`` | ``failed``."""

    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    PASSED = "passed"
    FAILED = "failed"


class DatasetVersionStatus(StrEnum):
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class PipelineRun(Base):
    """One execution of the AI pipeline for an Election, with what it used."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(
        sa.ForeignKey("elections.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[PipelineRunStatus] = mapped_column(
        _enum(PipelineRunStatus, "pipeline_run_status")
    )
    llm_provider: Mapped[str] = mapped_column(sa.String(50))
    llm_model: Mapped[str] = mapped_column(sa.String(200))
    generation_mode: Mapped[GenerationMode] = mapped_column(
        _enum(GenerationMode, "generation_mode")
    )
    # task -> prompt version, e.g. {"generate_statements": "v1"}.
    prompt_versions: Mapped[dict[str, str]] = mapped_column(sa.JSON)
    llm_calls: Mapped[int] = mapped_column(sa.Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(sa.String(500))
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    generation_finished_at: Mapped[dt.datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )

    election: Mapped[Election] = relationship(back_populates="pipeline_runs")
    dataset_version: Mapped["DatasetVersion | None"] = relationship(
        back_populates="pipeline_run", uselist=False, passive_deletes=True
    )
    source_documents: Mapped[list["PipelineRunSourceDocument"]] = relationship(
        back_populates="pipeline_run",
        order_by="PipelineRunSourceDocument.source_document_id",
        passive_deletes=True,
    )
    validation_results: Mapped[list["ValidationResult"]] = relationship(
        back_populates="pipeline_run",
        order_by="ValidationResult.id",
        passive_deletes=True,
    )


class SourceDocumentRole(StrEnum):
    """How a run used a Source Document: a Party's main (joint) manifesto or not."""

    MAIN = "main"
    ADDITIONAL = "additional"


class PipelineRunSourceDocument(Base):
    """A parsed Source Document that a Pipeline Run read, with its role."""

    __tablename__ = "pipeline_run_source_documents"

    pipeline_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), primary_key=True
    )
    source_document_id: Mapped[int] = mapped_column(
        sa.ForeignKey("source_documents.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[SourceDocumentRole] = mapped_column(
        _enum(SourceDocumentRole, "source_document_role")
    )

    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="source_documents")


class DatasetVersion(Base):
    """An immutable Questionnaire snapshot produced by one Pipeline Run."""

    __tablename__ = "dataset_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    election_id: Mapped[int] = mapped_column(
        sa.ForeignKey("elections.id", ondelete="CASCADE"), index=True
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[DatasetVersionStatus] = mapped_column(
        _enum(DatasetVersionStatus, "dataset_version_status"),
        default=DatasetVersionStatus.CANDIDATE,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )

    election: Mapped[Election] = relationship(back_populates="dataset_versions")
    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="dataset_version")
    statements: Mapped[list["Statement"]] = relationship(
        back_populates="dataset_version",
        order_by="Statement.position",
        passive_deletes=True,
    )


class Statement(Base):
    """One AI-generated Questionnaire item: text, topic tag and 1-based order."""

    __tablename__ = "statements"
    __table_args__ = (
        sa.UniqueConstraint("dataset_version_id", "position"),
        sa.CheckConstraint("position >= 1", name="position_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(
        sa.ForeignKey("dataset_versions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(sa.Integer)
    text: Mapped[str] = mapped_column(sa.String(300))
    # Not an Enum: the topic list is versioned with the prompts.
    topic: Mapped[str] = mapped_column(sa.String(50))

    dataset_version: Mapped[DatasetVersion] = relationship(back_populates="statements")
    party_positions: Mapped[list["PartyPosition"]] = relationship(
        back_populates="statement", order_by="PartyPosition.party_id", passive_deletes=True
    )


# What ``match-score.js`` expects for a Party Position without a stance.
NO_STANCE = "no_stance"


class PartyPosition(Base):
    """Where a Party stands on a Statement: -2..+2 with Evidence, or ``no stance``.

    Evidence is a value object stored as columns: the quote exactly as the LLM
    returned it, the Source Document, its page and (for URL documents) the URL.
    The CHECKs make the database enforce that every stance has Evidence.
    """

    __tablename__ = "party_positions"
    __table_args__ = (
        sa.UniqueConstraint("statement_id", "party_id"),
        sa.CheckConstraint("value IS NULL OR value BETWEEN -2 AND 2", name="value_range"),
        sa.CheckConstraint(
            "evidence_page IS NULL OR evidence_page >= 1", name="evidence_page_positive"
        ),
        sa.CheckConstraint(
            "(value IS NULL AND evidence_source_document_id IS NULL "
            "AND evidence_quote IS NULL AND evidence_page IS NULL AND evidence_url IS NULL) "
            "OR (value IS NOT NULL AND evidence_source_document_id IS NOT NULL "
            "AND evidence_quote IS NOT NULL AND evidence_page IS NOT NULL)",
            name="evidence_matches_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        sa.ForeignKey("statements.id", ondelete="CASCADE")
    )
    party_id: Mapped[int] = mapped_column(
        sa.ForeignKey("parties.id", ondelete="CASCADE"), index=True
    )
    # Null means ``no stance``.
    value: Mapped[int | None] = mapped_column(sa.Integer)
    evidence_source_document_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    evidence_quote: Mapped[str | None] = mapped_column(sa.Text)
    evidence_page: Mapped[int | None] = mapped_column(sa.Integer)
    evidence_url: Mapped[str | None] = mapped_column(sa.String(2048))

    statement: Mapped[Statement] = relationship(back_populates="party_positions")

    @property
    def engine_value(self) -> int | Literal["no_stance"]:
        """The value as ``match-score.js`` consumes it: -2..+2 or ``"no_stance"``."""
        return NO_STANCE if self.value is None else self.value


class ValidationResult(Base):
    """The outcome of one Validation check on one Pipeline Run. Insert-only."""

    __tablename__ = "validation_results"
    __table_args__ = (sa.UniqueConstraint("pipeline_run_id", "check_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(
        sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    # ``check`` is an SQL reserved word.
    check_name: Mapped[str] = mapped_column(sa.String(50))
    passed: Mapped[bool] = mapped_column(sa.Boolean)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), default=_utcnow
    )

    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="validation_results")
    entries: Mapped[list["ValidationReportEntry"]] = relationship(
        back_populates="validation_result",
        order_by="ValidationReportEntry.id",
        passive_deletes=True,
    )


class ValidationReportEntry(Base):
    """One offending item of a failed check, e.g. a Party Position. Insert-only."""

    __tablename__ = "validation_report_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    validation_result_id: Mapped[int] = mapped_column(
        sa.ForeignKey("validation_results.id", ondelete="CASCADE"), index=True
    )
    statement_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("statements.id", ondelete="CASCADE")
    )
    party_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("parties.id", ondelete="CASCADE")
    )
    message: Mapped[str] = mapped_column(sa.String(500))

    validation_result: Mapped[ValidationResult] = relationship(back_populates="entries")
    statement: Mapped["Statement | None"] = relationship()
