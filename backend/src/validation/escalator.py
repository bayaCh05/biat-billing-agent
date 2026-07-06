"""Compound flag escalation — promotes multiple warnings to a blocking ERROR."""
from __future__ import annotations

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

logger = get_logger(__name__)


class FlagEscalator:
    """Escalates an invoice to human review when too many warnings accumulate.

    After all individual validators run, counts open WARNING-severity flags.
    If the count reaches the threshold, adds a FlagType.ESCALATED ERROR flag
    which blocks auto-export and routes the invoice to the review queue.
    """

    def __init__(self, threshold: int = 2) -> None:
        self.threshold = threshold

    def escalate(self, invoice: InvoiceRecord) -> InvoiceRecord:
        open_warnings = [
            f for f in invoice.flags
            if f.severity == FlagSeverity.WARNING and not f.resolved
        ]
        if len(open_warnings) >= self.threshold:
            flag_names = ", ".join(f.flag_type.value for f in open_warnings)
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.ESCALATED,
                severity=FlagSeverity.ERROR,
                field_name="validation",
                message=(
                    f"{len(open_warnings)} warnings exceeded escalation threshold "
                    f"({self.threshold}): {flag_names}"
                ),
            ))
            logger.info(
                "invoice_escalated",
                invoice_id=str(invoice.id),
                warning_count=len(open_warnings),
                threshold=self.threshold,
                flags=flag_names,
            )
        return invoice
