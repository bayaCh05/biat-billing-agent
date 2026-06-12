from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.orm_models import PaymentORM
from src.utils.logging import get_logger

logger = get_logger(__name__)


class LifecycleTracker:
    """Queries and advances invoice lifecycle state: payments, collections, overdue."""

    def __init__(self, repository) -> None:
        self.repository = repository

    # ── Query methods ─────────────────────────────────────────────────────────

    def get_pending_export(self) -> list[InvoiceRecord]:
        """VALIDATED invoices not yet exported."""
        return self.repository.get_by_status(InvoiceStatus.VALIDATED)

    def get_pending_payment(self) -> list[InvoiceRecord]:
        """Supplier invoices EXPORTED but not yet paid."""
        return self.repository.get_pending_payment()

    def get_pending_collection(self) -> list[InvoiceRecord]:
        """Client invoices EXPORTED but not yet collected."""
        return self.repository.get_pending_collection()

    def get_overdue(self) -> list[InvoiceRecord]:
        """Invoices past their due_date with no payment recorded."""
        return self.repository.get_overdue()

    def get_flagged_for_review(self) -> list[InvoiceRecord]:
        """Invoices awaiting human review."""
        return self.repository.get_flagged()

    # ── State transitions ─────────────────────────────────────────────────────

    def mark_paid(
        self,
        invoice_id: UUID,
        payment_reference: str,
        amount: float,
        payment_method: str | None = None,
    ) -> InvoiceRecord:
        """Record payment for a supplier invoice and advance its status to PAID."""
        invoice = self._get_or_raise(invoice_id)

        payment = PaymentORM(
            invoice_id=invoice_id,
            amount=amount,
            payment_date=datetime.now(tz=timezone.utc).date(),
            payment_reference=payment_reference,
            payment_method=payment_method,
        )
        self.repository.session.add(payment)

        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = datetime.now(tz=timezone.utc)
        invoice.export_reference = payment_reference
        self.repository.save(invoice, changed_by="lifecycle_tracker")

        logger.info(
            "invoice_marked_paid",
            invoice_id=str(invoice_id),
            payment_reference=payment_reference,
            amount=amount,
        )
        return invoice

    def mark_collected(
        self,
        invoice_id: UUID,
        collection_reference: str,
        amount: float,
    ) -> InvoiceRecord:
        """Record collection for a client invoice and advance its status to COLLECTED."""
        invoice = self._get_or_raise(invoice_id)

        payment = PaymentORM(
            invoice_id=invoice_id,
            amount=amount,
            payment_date=datetime.now(tz=timezone.utc).date(),
            payment_reference=collection_reference,
            payment_method="bank_transfer",
        )
        self.repository.session.add(payment)

        invoice.status = InvoiceStatus.COLLECTED
        invoice.collected_at = datetime.now(tz=timezone.utc)
        self.repository.save(invoice, changed_by="lifecycle_tracker")

        logger.info(
            "invoice_marked_collected",
            invoice_id=str(invoice_id),
            collection_reference=collection_reference,
            amount=amount,
        )
        return invoice

    def approve_flagged(
        self,
        invoice_id: UUID,
        reviewer: str,
        notes: str | None = None,
    ) -> InvoiceRecord:
        """Human approves a FLAGGED invoice as-is → advances to VALIDATED."""
        invoice = self._get_or_raise(invoice_id)
        if invoice.status != InvoiceStatus.FLAGGED:
            raise ValueError(
                f"Invoice {invoice_id} is in status {invoice.status}, expected FLAGGED."
            )

        invoice.status = InvoiceStatus.VALIDATED
        invoice.reviewed_by = reviewer
        invoice.reviewed_at = datetime.now(tz=timezone.utc)
        invoice.human_review_notes = notes
        for flag in invoice.flags:
            flag.resolved = True
            flag.resolved_by = reviewer
            flag.resolved_at = datetime.now(tz=timezone.utc)

        self.repository.save(invoice, changed_by=reviewer)
        logger.info("flagged_invoice_approved", invoice_id=str(invoice_id), reviewer=reviewer)
        return invoice

    def reject_invoice(
        self,
        invoice_id: UUID,
        reviewer: str,
        reason: str,
    ) -> InvoiceRecord:
        """Human rejects an invoice → terminal REJECTED status."""
        invoice = self._get_or_raise(invoice_id)
        invoice.status = InvoiceStatus.REJECTED
        invoice.reviewed_by = reviewer
        invoice.reviewed_at = datetime.now(tz=timezone.utc)
        invoice.human_review_notes = reason
        self.repository.save(invoice, changed_by=reviewer)
        logger.info("invoice_rejected", invoice_id=str(invoice_id), reviewer=reviewer)
        return invoice

    # ── Helper ────────────────────────────────────────────────────────────────

    def _get_or_raise(self, invoice_id: UUID) -> InvoiceRecord:
        invoice = self.repository.get_by_id(invoice_id)
        if invoice is None:
            raise LookupError(f"Invoice {invoice_id} not found.")
        return invoice
