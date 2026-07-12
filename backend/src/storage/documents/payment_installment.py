"""Document Beanie pour les échéances de paiement — migration de PaymentInstallmentORM."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class PaymentInstallmentDocument(Document):
    """Échéance d'un plan de paiement échelonné (avec suivi des pénalités de retard).

    Correspond à PaymentInstallmentORM (table payment_installments).
    """

    id: UUID = Field(default_factory=uuid4)
    invoice_id: Annotated[str, Indexed()]   # soft ref vers invoices._id (str UUID)
    installment_number: int
    total_installments: int
    base_amount: float
    current_amount: float
    due_date: Annotated[date, Indexed()]
    paid_date: date | None = None
    paid_amount: float | None = None
    status: Annotated[str, Indexed()] = "PENDING"
    late_periods: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "payment_installments"
