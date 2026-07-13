"""SQLAlchemy ORM tables for project management and cost allocation.

Only AssetProjectLinkORM remains live here — CharteProjetORM, PhaseORM,
FicheMensuelleORM, FichePhaseORM and AvanceProgrammeeORM were the SQLite
side of project management before the Mongo/Beanie migration (see
CharteProjetDocument, PhaseDocument, FicheMensuelleDocument) and were
removed as dead code (Lot C, 2026-07) — zero live callers, the underlying
SQLite tables/data are untouched and still queried via raw SQL by
verify_migration_integrity.py / migrate_sqlite_to_mongodb.py.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


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
