"""Document Beanie pour les notifications — migration de NotificationORM."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import Field


class NotificationDocument(Document):
    """Notification système (facture reçue, alerte budget, etc.).

    Correspond à NotificationORM (table notifications).
    invoice_id : soft ref vers InvoiceDocument._id (pas de cascade — une
    notification survit à la suppression de la facture source).
    """

    id: UUID = Field(default_factory=uuid4)
    type: str
    title: str
    body: str
    is_read: Annotated[bool, Indexed()] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    invoice_id: UUID | None = None   # soft ref vers invoices._id

    class Settings:
        name = "notifications"
