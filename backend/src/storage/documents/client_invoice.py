"""Document Beanie pour les factures émises — migration de ClientInvoiceORM + ClientLineItemORM.

Décision Phase 0 : les lignes (client_line_items) sont embarquées dans le document.
Note : ClientLineItemORM utilisait un Integer autoincrement comme PK — remplacé
par UUID pour cohérence avec le reste du projet Beanie.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class ClientLineItemEmbed(BaseModel):
    """Ligne de facture émise — correspond à ClientLineItemORM (table client_line_items)."""
    id: UUID = Field(default_factory=uuid4)
    description: str
    quantity: float
    unit_price: float
    line_total: float
    tva_rate: float
    tva_amount: float
    compte_produit: str


class ClientInvoiceDocument(Document):
    """Facture émise vers un client intra-groupe.

    Correspond à ClientInvoiceORM (table client_invoices).
    """

    id: UUID = Field(default_factory=uuid4)
    invoice_number: Annotated[str, Indexed(unique=True)]
    invoice_date: Annotated[date, Indexed()]
    due_date: date

    issuer_name: str
    issuer_tax_id: str
    issuer_address: str | None = None

    client_id: Annotated[str, Indexed()]
    client_name: str
    client_tax_id: str
    client_address: str | None = None

    amount_ht: float
    tva_amount: float
    amount_ttc: float

    status: Annotated[str, Indexed()]
    source_template_id: str | None = None
    notes: str | None = None
    pdf_path: str | None = None

    created_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at: datetime | None = None
    paid_at: datetime | None = None

    line_items: list[ClientLineItemEmbed] = Field(default_factory=list)

    class Settings:
        name = "client_invoices"
        indexes = [
            IndexModel([("invoice_date", ASCENDING)]),
        ]
