"""Document Beanie pour le plan budgétaire — migration de BudgetPlanORM.

Note : BudgetPlanORM a une PK composite (catalog_id, year).
Dans MongoDB, on utilise un UUID comme _id et on crée un index unique composé
(catalog_id, year) pour garantir l'unicité métier.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field
from pymongo import ASCENDING, IndexModel


class BudgetPlanDocument(Document):
    """Ligne de plan budgétaire annuel par entrée catalogue.

    Correspond à BudgetPlanORM (table budget_plan_entries).
    Un document = un catalog_id pour une année donnée (12 valeurs mensuelles).
    """

    id: UUID = Field(default_factory=uuid4)
    catalog_id: Annotated[str, Indexed()]
    year: Annotated[int, Indexed()]
    label: str
    monthly: list[float]   # exactement 12 valeurs (validé à la création)
    note: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "budget_plan_entries"
        indexes = [
            IndexModel(
                [("catalog_id", ASCENDING), ("year", ASCENDING)],
                unique=True,
            ),
        ]
