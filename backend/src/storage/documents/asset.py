"""Document Beanie pour le registre des immobilisations — migration de AssetORM.

Décision Phase 0 : les AssetProjectLink (allocations projet) sont embarquées
dans le document Asset — accès toujours conjoints, taille bornée.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class AssetProjectLinkEmbed(BaseModel):
    """Allocation d'amortissement mensuel à un projet — correspond à AssetProjectLinkORM."""
    project_id: str
    allocation_pct: float   # 0.0 – 100.0


class AssetDocument(Document):
    """Immobilisation CAPEX.

    Correspond à AssetORM (table assets).
    Les allocations projet (asset_project_links) sont embarquées.
    """

    id: UUID = Field(default_factory=uuid4)
    designation: str
    compte_immobilisation: Annotated[str, Indexed()]
    compte_amortissement: str
    acquisition_date: date
    acquisition_cost_ht: float
    useful_life_years: int
    depreciation_method: str = "linear"
    supplier_invoice_id: str | None = None
    amortization_source: str | None = None
    notes: str = ""
    fully_depreciated: Annotated[bool, Indexed()] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    project_links: list[AssetProjectLinkEmbed] = Field(default_factory=list)

    class Settings:
        name = "assets"
        indexes = [
            IndexModel([("acquisition_date", ASCENDING)]),
        ]
