"""Document Beanie pour les feuilles de route — migration de FeuilleDeRouteORM."""
from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class FeuilleDeRouteDocument(Document):
    """Feuille de route projet (roadmap).

    Correspond à FeuilleDeRouteORM (table feuilles_de_route).
    Les risques associés sont dans RisqueDocument (soft ref feuille_route_id).
    """

    id: UUID = Field(default_factory=uuid4)
    titre: str
    description: str = ""
    date_debut: date
    date_fin: date
    projet_id: Annotated[str | None, Indexed()] = None
    responsable_id: str | None = None
    statut: Annotated[str, Indexed()] = "PLANIFIE"
    priorite: str = "MOYENNE"
    annee: int = 2026

    class Settings:
        name = "feuilles_de_route"
