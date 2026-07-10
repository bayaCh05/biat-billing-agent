"""Document Beanie pour les paiements — migration de PaymentORM (table payments)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class PaymentDocument(Document):
    """Paiement reçu sur une facture fournisseur.

    Correspond à PaymentORM (table `payments`).
    invoice_id : soft reference vers invoices._id (pas de Link — simplification requêtes).
    """

    id: UUID = Field(default_factory=uuid4)
    invoice_id: Annotated[UUID, Indexed()]   # soft ref vers InvoiceDocument._id
    amount: float
    payment_date: date
    payment_reference: str | None = None
    payment_method: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "payments"
