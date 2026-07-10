"""Document Beanie pour le journal comptable — migration de JournalEntryORM + JournalLineORM.

Décision Phase 0 : les lignes d'écriture (journal_lines) sont embarquées dans
le document — elles sont toujours accédées et sauvegardées conjointement avec
l'entrée, et la suppression d'une écriture doit supprimer ses lignes.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class JournalLineEmbed(BaseModel):
    """Ligne d'écriture comptable — correspond à JournalLineORM (table journal_lines)."""
    id: UUID = Field(default_factory=uuid4)
    compte: str
    libelle: str
    debit: float | None = None
    credit: float | None = None


class JournalEntryDocument(Document):
    """Écriture comptable en double partie.

    Correspond à JournalEntryORM (table journal_entries).
    Invariant : |Σ débits − Σ crédits| < 0,005 TND (validé à la génération).
    """

    id: UUID = Field(default_factory=uuid4)
    reference: str
    date_ecriture: Annotated[date, Indexed()]
    description: str
    source_invoice_id: Annotated[UUID | None, Indexed()] = None
    source_asset_id: UUID | None = None
    accounting_explanation: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    lines: list[JournalLineEmbed] = Field(default_factory=list)

    class Settings:
        name = "journal_entries"
        indexes = [
            IndexModel([("reference", ASCENDING)]),
        ]
