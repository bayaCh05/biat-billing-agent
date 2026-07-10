"""Document Beanie pour les risques projet — migration de RisqueORM."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class RisqueDocument(Document):
    """Risque projet (probabilité / impact / plan de mitigation).

    Correspond à RisqueORM (table risques).
    feuille_route_id : soft ref vers FeuilleDeRouteDocument._id (UUID | None).
    """

    id: UUID = Field(default_factory=uuid4)
    titre: str
    description: str = ""
    type_risque: str = "AUTRE"
    probabilite: str
    impact: str
    niveau_criticite: str
    statut: Annotated[str, Indexed()] = "IDENTIFIE"
    plan_mitigation: str = ""
    responsable_id: str | None = None
    date_identification: date
    date_echeance_mitigation: date | None = None
    date_cloture: date | None = None
    feuille_route_id: Annotated[UUID | None, Indexed()] = None   # soft ref
    projet_id: Annotated[str | None, Indexed()] = None
    created_by: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "risques"
