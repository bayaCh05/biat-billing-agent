from __future__ import annotations

import re

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import ConfidenceField, InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Tunisian MF pattern: 7 digits + uppercase letter / uppercase letter / 3 digits
# Example: 1234567/A/M/000
_MF_PATTERN = re.compile(r"^\d{7}[A-Z]/[A-Z]/[A-Z]/\d{3}$")

_REQUIRED_FIELDS = [
    "issuer_name",
    "invoice_number",
    "invoice_date",
    "amount_ttc",
]


class FieldValidator:
    """Level-1 validation: mandatory fields, confidence thresholds, MF format, TVA rates."""

    def __init__(self, confidence_thresholds: dict) -> None:
        self.thresholds = confidence_thresholds

    def validate(self, invoice: InvoiceRecord) -> InvoiceRecord:
        invoice = self._check_required_fields(invoice)
        invoice = self._check_confidence(invoice)
        invoice = self._check_tax_id_format(invoice)
        return invoice

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_required_fields(self, invoice: InvoiceRecord) -> InvoiceRecord:
        for field_name in _REQUIRED_FIELDS:
            cf: ConfidenceField = getattr(invoice, field_name)
            if cf.value is None:
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.MISSING_FIELD,
                    severity=FlagSeverity.ERROR,
                    field_name=field_name,
                    message=f"Required field '{field_name}' is missing or could not be extracted.",
                ))
                logger.debug(
                    "missing_required_field",
                    invoice_id=str(invoice.id),
                    field=field_name,
                )
        return invoice

    def _check_confidence(self, invoice: InvoiceRecord) -> InvoiceRecord:
        min_conf: float = self.thresholds.get("minimum_confidence", 0.5)
        warn_conf: float = self.thresholds.get("warning_confidence", 0.7)

        for field_name in _REQUIRED_FIELDS:
            cf: ConfidenceField = getattr(invoice, field_name)
            if cf.value is None:
                continue  # already flagged above
            if cf.confidence < min_conf:
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.LOW_CONFIDENCE,
                    severity=FlagSeverity.ERROR,
                    field_name=field_name,
                    message=(
                        f"Field '{field_name}' confidence {cf.confidence:.2f} "
                        f"is below minimum {min_conf}."
                    ),
                ))
            elif cf.confidence < warn_conf:
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.LOW_CONFIDENCE,
                    severity=FlagSeverity.WARNING,
                    field_name=field_name,
                    message=(
                        f"Field '{field_name}' confidence {cf.confidence:.2f} "
                        f"is below warning threshold {warn_conf}."
                    ),
                ))
        return invoice

    def _check_tax_id_format(self, invoice: InvoiceRecord) -> InvoiceRecord:
        for field_name in ("issuer_tax_id", "recipient_tax_id"):
            cf: ConfidenceField = getattr(invoice, field_name)
            if cf.value and not _MF_PATTERN.match(cf.value):
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.INVALID_TAX_ID,
                    severity=FlagSeverity.WARNING,
                    field_name=field_name,
                    message=(
                        f"'{field_name}' value '{cf.value}' does not match "
                        "expected Tunisian MF format (1234567/A/M/000)."
                    ),
                ))
        return invoice
