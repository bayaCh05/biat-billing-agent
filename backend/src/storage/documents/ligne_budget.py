"""Document Beanie pour les lignes budgétaires projet — migration de LigneBudgetORM."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class LigneBudgetDocument(Document):
    """Ligne budgétaire d'un projet.

    Correspond à LigneBudgetORM (table lignes_budget).
    """

    id: UUID = Field(default_factory=uuid4)
    projet_id: Annotated[str, Indexed()]
    categorie: str
    montant_prevu: float
    montant_consomme: float = 0.0
    devise: str = "TND"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "lignes_budget"
