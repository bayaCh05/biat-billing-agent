from __future__ import annotations

from datetime import date, datetime, timezone

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

logger = get_logger(__name__)


class CoherenceChecker:
    """Level-2 validation: mathematical and logical coherence checks.

    Checks:
    - invoice_date not in the future
    - due_date >= invoice_date
    - HT + TVA ≈ TTC
    - Line-item totals sum ≈ amount_ht
    - TVA rate is an accepted Tunisian rate
    """

    def __init__(self, config: dict) -> None:
        self.abs_tolerance = config["validation"]["math_tolerance_absolute"]
        self.rel_tolerance = config["validation"]["math_tolerance_relative"]
        self.allowed_tva_rates: list[float] = [
            float(r) for r in config["validation"]["tva_rates_allowed"]
        ]

    def check(self, invoice: InvoiceRecord) -> InvoiceRecord:
        invoice = self._check_dates(invoice)
        invoice = self._check_amounts(invoice)
        invoice = self._check_line_items(invoice)
        invoice = self._check_tva_rate(invoice)
        return invoice

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_dates(self, invoice: InvoiceRecord) -> InvoiceRecord:
        today = datetime.now(tz=timezone.utc).date()

        inv_date: date | None = invoice.invoice_date.value
        due: date | None = invoice.due_date.value

        if inv_date is not None and inv_date > today:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.FUTURE_DATED,
                severity=FlagSeverity.WARNING,
                field_name="invoice_date",
                message=f"Invoice date {inv_date} is in the future.",
            ))

        if inv_date is not None and due is not None and due < inv_date:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.DUE_BEFORE_ISSUE,
                severity=FlagSeverity.ERROR,
                field_name="due_date",
                message=(
                    f"Due date {due} is before invoice date {inv_date}."
                ),
            ))

        return invoice

    def _check_amounts(self, invoice: InvoiceRecord) -> InvoiceRecord:
        ht = invoice.amount_ht.value
        tva = invoice.tva_amount.value
        ttc = invoice.amount_ttc.value

        if ht is None or tva is None or ttc is None:
            return invoice

        tolerance = self._tolerance(ttc)
        if abs(ht + tva - ttc) > tolerance:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.TOTAL_MISMATCH,
                severity=FlagSeverity.ERROR,
                field_name="amount_ttc",
                message=(
                    f"HT ({ht}) + TVA ({tva}) = {ht + tva:.4f} "
                    f"but TTC = {ttc} (diff {abs(ht + tva - ttc):.4f}, "
                    f"tolerance {tolerance:.4f})."
                ),
            ))
        return invoice

    def _check_line_items(self, invoice: InvoiceRecord) -> InvoiceRecord:
        if not invoice.line_items:
            return invoice

        # Per-line consistency: qty × unit_price ≈ line_total
        for li in invoice.line_items:
            if li.quantity is not None and li.unit_price is not None and li.line_total is not None:
                computed = round(li.quantity * li.unit_price, 3)
                tol = self._tolerance(li.line_total)
                if abs(computed - li.line_total) > tol:
                    invoice.add_flag(ValidationFlag(
                        flag_type=FlagType.LINEITEMS_SUM_MISMATCH,
                        severity=FlagSeverity.WARNING,
                        field_name="amount_ht",
                        message=(
                            f"Line {li.line_number}: {li.quantity} × {li.unit_price} "
                            f"= {computed:.3f} but line_total = {li.line_total} "
                            f"(diff {abs(computed - li.line_total):.3f})."
                        ),
                    ))

        ht = invoice.amount_ht.value
        if ht is None:
            return invoice

        line_sum = sum(
            li.line_total for li in invoice.line_items if li.line_total is not None
        )
        if line_sum == 0:
            return invoice  # no totals on any line — can't validate

        tolerance = self._tolerance(ht)
        if abs(line_sum - ht) > tolerance:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.LINEITEMS_SUM_MISMATCH,
                severity=FlagSeverity.WARNING,
                field_name="amount_ht",
                message=(
                    f"Sum of line items ({line_sum:.4f}) does not match "
                    f"amount_ht ({ht}) — diff {abs(line_sum - ht):.4f}."
                ),
            ))
        return invoice

    def _check_tva_rate(self, invoice: InvoiceRecord) -> InvoiceRecord:
        rate = invoice.tva_rate.value
        if rate is None:
            return invoice
        if rate not in self.allowed_tva_rates:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.INVALID_TVA_RATE,
                severity=FlagSeverity.WARNING,
                field_name="tva_rate",
                message=(
                    f"TVA rate {rate}% is not in the accepted Tunisian rates "
                    f"{self.allowed_tva_rates}."
                ),
            ))
        return invoice

    def _tolerance(self, reference: float) -> float:
        return max(self.abs_tolerance, abs(reference) * self.rel_tolerance)
