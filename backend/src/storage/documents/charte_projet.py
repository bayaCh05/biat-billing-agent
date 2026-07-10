"""Document Beanie pour les chartes projet — migration de CharteProjetORM."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from beanie import Document, Indexed


class CharteProjetDocument(Document):
    """Charte de projet IT (contrat interne BIAT IT ↔ métier).

    Correspond à CharteProjetORM (table chartes_projet).
    id : clé métier str (ex: "CHR-2026-0001") — fournie à la création.
    """

    id: str   # clé métier humaine (CHR-YYYY-NNNN)
    project_id: Annotated[str, Indexed()]
    project_name: str
    client: str = "BIAT"
    valid_from: date
    valid_until: date | None = None
    budget_jh: float
    taux_jh: float
    is_active: Annotated[bool, Indexed()] = True

    class Settings:
        name = "chartes_projet"
