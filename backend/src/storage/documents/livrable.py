"""Document Beanie pour les livrables de phase — migration de LivrableORM."""
from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class LivrableDocument(Document):
    """Livrable d'une phase de projet.

    Correspond à LivrableORM (table livrables).
    phase_id : soft ref vers PhaseDocument._id (str, pas UUID).
    """

    id: UUID = Field(default_factory=uuid4)
    phase_id: Annotated[str, Indexed()]   # soft ref vers phases._id
    titre: str
    description: str = ""
    date_livraison_prevue: date
    date_livraison_reelle: date | None = None
    statut: Annotated[str, Indexed()] = "EN_ATTENTE"
    fichier_path: str | None = None
    created_by: str = ""

    class Settings:
        name = "livrables"
