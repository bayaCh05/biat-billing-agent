"""SQLAlchemy ORM tables for project management and cost allocation."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.db import Base


class CharteProjetORM(Base):
    __tablename__ = "chartes_projet"
    __table_args__ = (
        Index("idx_chartes_project_id", "project_id"),
        Index("idx_chartes_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)   # CHR-YYYY-NNNN
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_name: Mapped[str] = mapped_column(Text, nullable=False)
    client: Mapped[str] = mapped_column(String(64), nullable=False, default="BIAT")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    budget_jh: Mapped[float] = mapped_column(Float, nullable=False)
    taux_jh: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    phases: Mapped[list[PhaseORM]] = relationship(
        "PhaseORM",
        primaryjoin="CharteProjetORM.project_id == foreign(PhaseORM.project_id)",
        viewonly=True,
    )


class PhaseORM(Base):
    __tablename__ = "phases"
    __table_args__ = (
        Index("idx_phases_project_id", "project_id"),
        Index("idx_phases_status", "status"),
        Index("idx_phases_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    planned_jh: Mapped[float] = mapped_column(Float, nullable=False)
    consumed_jh: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    closed_date: Mapped[date | None] = mapped_column(Date)
    livrables: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array


class FicheMensuelleORM(Base):
    __tablename__ = "fiches_mensuelles"
    __table_args__ = (
        Index("idx_fiches_period", "period_year", "period_month"),
        Index("idx_fiches_status", "status"),
        UniqueConstraint("period_year", "period_month", "prepared_by",
                         name="uq_fiche_period_preparer"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    prepared_by: Mapped[str] = mapped_column(String(128), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    invoice_number: Mapped[str | None] = mapped_column(String(32))

    phase_links: Mapped[list[FichePhaseORM]] = relationship(
        "FichePhaseORM",
        back_populates="fiche",
        cascade="all, delete-orphan",
    )
    avances: Mapped[list[AvanceProgrammeeORM]] = relationship(
        "AvanceProgrammeeORM",
        back_populates="fiche",
        cascade="all, delete-orphan",
    )


class FichePhaseORM(Base):
    """M2M link between a fiche mensuelle and the phases it closes."""
    __tablename__ = "fiche_phases"

    fiche_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("fiches_mensuelles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    phase_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("phases.id", ondelete="CASCADE"),
        primary_key=True,
    )

    fiche: Mapped[FicheMensuelleORM] = relationship("FicheMensuelleORM", back_populates="phase_links")
    phase: Mapped[PhaseORM] = relationship("PhaseORM")


class AvanceProgrammeeORM(Base):
    __tablename__ = "avances_programmees"
    __table_args__ = (
        Index("idx_avances_fiche_id", "fiche_id"),
        Index("idx_avances_project_id", "project_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fiche_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("fiches_mensuelles.id", ondelete="CASCADE"), nullable=False,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    charte_id: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    montant_ht: Mapped[float] = mapped_column(Float, nullable=False)
    schedule_reference: Mapped[str] = mapped_column(Text, nullable=False)

    fiche: Mapped[FicheMensuelleORM] = relationship("FicheMensuelleORM", back_populates="avances")


class AssetProjectLinkORM(Base):
    """Allocation of a CAPEX asset's monthly depreciation to a project (0–100%)."""
    __tablename__ = "asset_project_links"
    __table_args__ = (
        Index("idx_apl_asset_id", "asset_id"),
        Index("idx_apl_project_id", "project_id"),
    )

    asset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    allocation_pct: Mapped[float] = mapped_column(Float, nullable=False)
