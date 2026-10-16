"""SQLAlchemy ORM models. The schema itself is created only by Alembic."""

import datetime as dt
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
