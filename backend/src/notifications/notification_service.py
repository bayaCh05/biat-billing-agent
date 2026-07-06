"""Notification service — creates DB-persisted notifications for pipeline events."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.orm_models_notifications import NotificationORM

_TYPE_LABELS = {
    "INVOICE_FLAGGED":   "Facture signalée",
    "INVOICE_ESCALATED": "Facture escaladée",
    "PAYMENT_OVERDUE":   "Paiement en retard",
    "BUDGET_EXCEEDED":   "Budget dépassé",
}


def sync_flagged_invoices(session: Session) -> None:
    """Lazily seed notifications for any flagged invoice that has none yet.

    Called on notification list/count endpoints so existing flagged invoices
    are visible even if the pipeline didn't create notifications for them.
    """
    from src.storage.repository import InvoiceRepository
    from src.models.enums import InvoiceStatus

    repo = InvoiceRepository(session)
    _TERMINAL = {InvoiceStatus.REJECTED, InvoiceStatus.ERROR}
    for inv in repo.list_all():
        if inv.human_review_required and inv.status not in _TERMINAL:
            issuer = inv.issuer_name.value if inv.issuer_name else None
            ensure_invoice_notification(session, inv.id, issuer, inv.status.value)


def create_notification(
    session: Session,
    *,
    notif_type: str,
    title: str,
    body: str,
    invoice_id: UUID | None = None,
) -> NotificationORM:
    notif = NotificationORM(
        type=notif_type,
        title=title,
        body=body,
        invoice_id=invoice_id,
    )
    session.add(notif)
    session.flush()
    return notif


def ensure_invoice_notification(session: Session, invoice_id: UUID, issuer: str | None, status: str) -> None:
    """Create a notification for a flagged/escalated invoice if one doesn't exist yet."""
    existing = session.execute(
        select(NotificationORM).where(NotificationORM.invoice_id == invoice_id)
    ).scalar_one_or_none()
    if existing:
        return

    notif_type = "INVOICE_ESCALATED" if status == "ESCALATED" else "INVOICE_FLAGGED"
    label = issuer or "Fournisseur inconnu"
    create_notification(
        session,
        notif_type=notif_type,
        title=f"{_TYPE_LABELS[notif_type]} — {label}",
        body=f"La facture de {label} requiert une révision humaine (statut : {status}).",
        invoice_id=invoice_id,
    )
    session.commit()
