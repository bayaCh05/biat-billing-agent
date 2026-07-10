"""Document Beanie pour les fiches mensuelles — migration de FicheMensuelleORM + enfants.

Décision Phase 0 : FichePhase et AvanceProgrammee sont embarquées
(relation cascade all, delete-orphan, accès toujours conjoints).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class FichePhaseEmbed(BaseModel):
    """Lien M2M fiche ↔ phase — correspond à FichePhaseORM (table fiche_phases)."""
    fiche_id: str
    phase_id: str


class AvanceProgrammeeEmbed(BaseModel):
    """Avance programmée sur une charte — correspond à AvanceProgrammeeORM."""
    id: UUID = Field(default_factory=uuid4)
    project_id: str
    charte_id: str
    description: str
    montant_ht: float
    schedule_reference: str


class FicheMensuelleDocument(Document):
    """Fiche mensuelle de facturation intra-groupe.

    Correspond à FicheMensuelleORM (table fiches_mensuelles).
    id : clé métier str — fournie à la création.
    Contrainte unique : (period_year, period_month, prepared_by) → index composé.
    """

    id: str   # clé métier str
    period_month: Annotated[int, Indexed()]
    period_year: Annotated[int, Indexed()]
    prepared_by: str
    prepared_at: datetime
    status: Annotated[str, Indexed()] = "draft"
    invoice_number: str | None = None

    phase_links: list[FichePhaseEmbed] = Field(default_factory=list)
    avances: list[AvanceProgrammeeEmbed] = Field(default_factory=list)

    class Settings:
        name = "fiches_mensuelles"
        indexes = [
            IndexModel(
                [
                    ("period_year", ASCENDING),
                    ("period_month", ASCENDING),
                    ("prepared_by", ASCENDING),
                ],
                unique=True,
            ),
        ]
