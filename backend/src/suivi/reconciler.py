from __future__ import annotations

from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.utils.logging import get_logger

logger = get_logger(__name__)

_AMOUNT_TOLERANCE = 0.02  # TND


class Reconciler:
    """Matches incoming payment notifications to open invoices.

    Matching strategy (in order):
      1. Exact export_reference match
      2. Exact invoice_number + issuer_tax_id match
      3. Amount + issuer_tax_id within tolerance (ambiguous — logs warning)
    Returns the matched InvoiceRecord or None if no match.
    """

    def __init__(self, repository) -> None:
        self.repository = repository

    def match_payment(self, payment_data: dict) -> InvoiceRecord | None:
        """Try to find the invoice that corresponds to an incoming payment notification.

        payment_data keys (all optional):
          reference   — payment/export reference string
          invoice_number — invoice number string
          issuer_tax_id  — issuer MF string
          amount      — float amount paid
        """
        reference: str | None = payment_data.get("reference")
        invoice_number: str | None = payment_data.get("invoice_number")
        issuer_tax_id: str | None = payment_data.get("issuer_tax_id")
        amount: float | None = payment_data.get("amount")

        # 1. Exact export reference
        if reference:
            match = self._by_export_reference(reference)
            if match:
                logger.info(
                    "payment_matched_by_reference",
                    reference=reference,
                    invoice_id=str(match.id),
                )
                return match

        # 2. Exact invoice_number + issuer_tax_id
        if invoice_number and issuer_tax_id:
            candidates = self.repository.find_potential_duplicates(
                invoice_number=invoice_number,
                issuer_tax_id=issuer_tax_id,
                exclude_id=None,
                window_days=365,
            )
            exported = [c for c in candidates if c.status == InvoiceStatus.EXPORTED]
            if len(exported) == 1:
                logger.info(
                    "payment_matched_by_invoice_number",
                    invoice_number=invoice_number,
                    invoice_id=str(exported[0].id),
                )
                return exported[0]

        # 3. Fuzzy: amount + issuer_tax_id
        if amount is not None and issuer_tax_id:
            matches = self.repository.find_near_duplicates(
                issuer_name=issuer_tax_id,
                amount_ttc=amount,
                exclude_id=None,
                window_days=365,
            )
            exported = [m for m in matches if m.status == InvoiceStatus.EXPORTED]
            if len(exported) == 1:
                logger.warning(
                    "payment_matched_by_amount_fuzzy",
                    issuer_tax_id=issuer_tax_id,
                    amount=amount,
                    invoice_id=str(exported[0].id),
                )
                return exported[0]
            if len(exported) > 1:
                logger.warning(
                    "payment_match_ambiguous",
                    issuer_tax_id=issuer_tax_id,
                    amount=amount,
                    candidate_count=len(exported),
                )

        return None

    def match_purchase_order(self, invoice: InvoiceRecord) -> InvoiceRecord:
        """Stub: PO matching requires an external PO database.
        Returns the invoice unchanged until PO data is wired in.
        """
        return invoice

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _by_export_reference(self, reference: str) -> InvoiceRecord | None:
        """Find an EXPORTED invoice whose export_reference equals the given string."""
        all_exported = self.repository.get_by_status(InvoiceStatus.EXPORTED)
        for inv in all_exported:
            if inv.export_reference == reference:
                return inv
        return None
