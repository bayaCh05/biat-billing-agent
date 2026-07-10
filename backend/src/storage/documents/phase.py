"""Document Beanie pour les phases de projet — migration de PhaseORM."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from beanie import Document, Indexed
from pymongo import ASCENDING, IndexModel


class PhaseDocument(Document):
    """Phase d'un projet IT.

    Correspond à PhaseORM (table phases).
    id : clé métier str — fournie à la création.
    livrables : JSON array sérialisé en str (conservé tel quel depuis l'ORM).
    """

    id: str   # clé métier (ex: "PHASE-2026-001")
    project_id: Annotated[str, Indexed()]
    name: str
    description: str = ""
    planned_jh: float
    consumed_jh: float = 0.0
    status: Annotated[str, Indexed()] = "open"
    closed_date: date | None = None
    livrables: str = "[]"   # JSON array str (compatibilité ORM)

    class Settings:
        name = "phases"
        indexes = [
            IndexModel([("project_id", ASCENDING), ("status", ASCENDING)]),
        ]
