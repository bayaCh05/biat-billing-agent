"""Persistance du registre des immobilisations (SQLAlchemy).

AssetORM   : table SQL `assets`
AssetRepository : API CRUD — ne retourne que des objets Pydantic Asset.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from uuid import UUID as _UUID

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, func, select, and_
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, Session, mapped_column

from src.models.asset import Asset
from src.models.cost_allocation import AssetProjectLink
from src.storage.db import Base


# ── ORM ───────────────────────────────────────────────────────────────────────

class AssetORM(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("idx_assets_compte", "compte_immobilisation"),
        Index("idx_assets_active", "fully_depreciated"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    designation: Mapped[str] = mapped_column(Text, nullable=False)
    compte_immobilisation: Mapped[str] = mapped_column(String(16), nullable=False)
    compte_amortissement: Mapped[str] = mapped_column(String(16), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost_ht: Mapped[float] = mapped_column(Float, nullable=False)
    useful_life_years: Mapped[int] = mapped_column(Integer, nullable=False)
    depreciation_method: Mapped[str] = mapped_column(String(16), default="linear")
    supplier_invoice_id: Mapped[str | None] = mapped_column(Text)
    amortization_source: Mapped[str | None] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    fully_depreciated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


# ── Repository ────────────────────────────────────────────────────────────────

class AssetRepository:
    """CRUD pour le registre des immobilisations.

    L'API publique ne manipule que des objets Pydantic Asset.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, asset: Asset) -> Asset:
        existing = self.session.get(AssetORM, asset.id)
        if existing is None:
            self.session.add(self._to_orm(asset))
        else:
            self._update_orm(existing, asset)
        self.session.commit()
        return asset

    def get_by_id(self, asset_id: UUID) -> Asset | None:
        orm = self.session.get(AssetORM, asset_id)
        return self._to_pydantic(orm) if orm else None

    def list_all(self, include_fully_depreciated: bool = True) -> list[Asset]:
        stmt = select(AssetORM)
        if not include_fully_depreciated:
            stmt = stmt.where(AssetORM.fully_depreciated == False)  # noqa: E712
        stmt = stmt.order_by(AssetORM.acquisition_date.desc())
        orms = self.session.execute(stmt).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def list_by_compte(self, compte: str) -> list[Asset]:
        orms = self.session.execute(
            select(AssetORM)
            .where(AssetORM.compte_immobilisation == compte)
            .order_by(AssetORM.acquisition_date)
        ).scalars().all()
        return [self._to_pydantic(o) for o in orms]

    def mark_fully_depreciated(self, asset_id: UUID) -> None:
        orm = self.session.get(AssetORM, asset_id)
        if orm:
            orm.fully_depreciated = True
            self.session.commit()

    def delete(self, asset_id: UUID) -> bool:
        orm = self.session.get(AssetORM, asset_id)
        if orm is None:
            return False
        self.session.delete(orm)
        self.session.commit()
        return True

    def count(self) -> int:
        return self.session.execute(select(func.count(AssetORM.id))).scalar_one()

    def total_gross_value(self) -> float:
        result = self.session.execute(
            select(func.sum(AssetORM.acquisition_cost_ht))
        ).scalar_one()
        return float(result or 0.0)

    # ── AssetProjectLink ──────────────────────────────────────────────────────

    def save_link(self, link: AssetProjectLink) -> None:
        from src.storage.orm_models_projects import AssetProjectLinkORM
        asset_uuid = _UUID(link.asset_id) if isinstance(link.asset_id, str) else link.asset_id
        existing = self.session.get(AssetProjectLinkORM, (asset_uuid, link.project_id))
        if existing is None:
            self.session.add(AssetProjectLinkORM(
                asset_id=asset_uuid,
                project_id=link.project_id,
                allocation_pct=link.allocation_pct,
            ))
        else:
            existing.allocation_pct = link.allocation_pct
        self.session.commit()

    def get_links_by_project(self, project_id: str) -> list[AssetProjectLink]:
        from src.storage.orm_models_projects import AssetProjectLinkORM
        orms = self.session.execute(
            select(AssetProjectLinkORM).where(AssetProjectLinkORM.project_id == project_id)
        ).scalars().all()
        return [AssetProjectLink(
            asset_id=str(o.asset_id),
            project_id=o.project_id,
            allocation_pct=o.allocation_pct,
        ) for o in orms]

    def get_links_by_asset(self, asset_id: str) -> list[AssetProjectLink]:
        from src.storage.orm_models_projects import AssetProjectLinkORM
        asset_uuid = _UUID(asset_id)
        orms = self.session.execute(
            select(AssetProjectLinkORM).where(AssetProjectLinkORM.asset_id == asset_uuid)
        ).scalars().all()
        return [AssetProjectLink(
            asset_id=str(o.asset_id),
            project_id=o.project_id,
            allocation_pct=o.allocation_pct,
        ) for o in orms]

    # ── ORM ↔ Pydantic ────────────────────────────────────────────────────────

    @staticmethod
    def _to_orm(asset: Asset) -> AssetORM:
        supplier_id = asset.supplier_invoice_id
        if supplier_id is not None:
            supplier_id = str(supplier_id)
        return AssetORM(
            id=asset.id,
            designation=asset.designation,
            compte_immobilisation=asset.compte_immobilisation,
            compte_amortissement=asset.compte_amortissement,
            acquisition_date=asset.acquisition_date,
            acquisition_cost_ht=asset.acquisition_cost_ht,
            useful_life_years=asset.useful_life_years,
            depreciation_method=asset.depreciation_method,
            supplier_invoice_id=supplier_id,
            amortization_source=asset.amortization_source,
            notes=asset.notes,
            created_at=asset.created_at,
        )

    @staticmethod
    def _update_orm(orm: AssetORM, asset: Asset) -> None:
        orm.designation = asset.designation
        orm.compte_immobilisation = asset.compte_immobilisation
        orm.compte_amortissement = asset.compte_amortissement
        orm.acquisition_date = asset.acquisition_date
        orm.acquisition_cost_ht = asset.acquisition_cost_ht
        orm.useful_life_years = asset.useful_life_years
        orm.depreciation_method = asset.depreciation_method
        supplier_id = asset.supplier_invoice_id
        orm.supplier_invoice_id = str(supplier_id) if supplier_id is not None else None
        orm.amortization_source = asset.amortization_source
        orm.notes = asset.notes

    @staticmethod
    def _to_pydantic(orm: AssetORM) -> Asset:
        return Asset(
            id=orm.id,
            designation=orm.designation,
            compte_immobilisation=orm.compte_immobilisation,
            compte_amortissement=orm.compte_amortissement,
            acquisition_date=orm.acquisition_date,
            acquisition_cost_ht=orm.acquisition_cost_ht,
            useful_life_years=orm.useful_life_years,
            depreciation_method=orm.depreciation_method,
            supplier_invoice_id=orm.supplier_invoice_id,
            amortization_source=orm.amortization_source,
            notes=orm.notes or "",
            created_at=orm.created_at or datetime.utcnow(),
        )
