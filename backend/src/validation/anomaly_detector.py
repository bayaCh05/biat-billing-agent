from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag

if TYPE_CHECKING:
    from src.cost_catalog.catalog import CostCatalog
from src.utils.logging import get_logger

logger = get_logger(__name__)

# A round number is divisible by this with zero remainder
_ROUND_DIVISOR = 1000.0
_ROUND_MIN_AMOUNT = 10_000.0  # only flag if amount is large enough to be suspicious


class AnomalyDetector:
    """Level-3 anomaly detection: high-value amounts, suspiciously round numbers,
    statistical outliers versus historical average per issuer.
    """

    def __init__(self, config: dict, repository, catalog: "CostCatalog | None" = None) -> None:
        self.high_value_threshold: float = float(
            config["validation"]["high_value_threshold"]
        )
        self.repository = repository
        self.catalog = catalog

    def detect(self, invoice: InvoiceRecord) -> InvoiceRecord:
        invoice = self._check_high_value(invoice)
        invoice = self._check_plausible_amount(invoice)
        invoice = self._check_round_amount(invoice)
        invoice = self._check_statistical_outlier(invoice)
        return invoice

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_high_value(self, invoice: InvoiceRecord) -> InvoiceRecord:
        amount = invoice.amount_ttc.value
        if amount is not None and amount >= self.high_value_threshold:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.HIGH_VALUE,
                severity=FlagSeverity.ERROR,
                field_name="amount_ttc",
                message=(
                    f"Invoice amount {amount:.3f} TND exceeds high-value "
                    f"threshold {self.high_value_threshold:.0f} TND — "
                    "requires human approval before export."
                ),
            ))
            logger.info(
                "high_value_invoice",
                invoice_id=str(invoice.id),
                amount=amount,
                threshold=self.high_value_threshold,
            )
        return invoice

    def _check_plausible_amount(self, invoice: InvoiceRecord) -> InvoiceRecord:
        """Flag amounts that exceed the catalog entry's max_plausible_amount."""
        if self.catalog is None:
            return invoice
        catalog_id = invoice.cost_catalog_id
        amount = invoice.amount_ttc.value
        if catalog_id is None or amount is None:
            return invoice
        entry = self.catalog.get(catalog_id)
        if entry is None or entry.max_plausible_amount is None:
            return invoice
        if amount > entry.max_plausible_amount:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.AMOUNT_IMPLAUSIBLE,
                severity=FlagSeverity.WARNING,
                field_name="amount_ttc",
                message=(
                    f"{amount:,.3f} TND exceeds max plausible amount for "
                    f"{catalog_id} ({entry.max_plausible_amount:,.0f} TND)"
                ),
            ))
            logger.info(
                "amount_implausible",
                invoice_id=str(invoice.id),
                catalog_id=catalog_id,
                amount=amount,
                max_plausible=entry.max_plausible_amount,
            )
        return invoice

    def _check_round_amount(self, invoice: InvoiceRecord) -> InvoiceRecord:
        amount = invoice.amount_ttc.value
        if (
            amount is not None
            and amount >= _ROUND_MIN_AMOUNT
            and amount % _ROUND_DIVISOR == 0
        ):
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.SUSPICIOUS_AMOUNT,
                severity=FlagSeverity.WARNING,
                field_name="amount_ttc",
                message=(
                    f"Invoice amount {amount:.0f} TND is suspiciously round "
                    f"(divisible by {_ROUND_DIVISOR:.0f})."
                ),
            ))
        return invoice

    def _check_statistical_outlier(self, invoice: InvoiceRecord) -> InvoiceRecord:
        issuer_tax_id = invoice.issuer_tax_id.value
        amount = invoice.amount_ttc.value

        if issuer_tax_id is None or amount is None:
            return invoice

        historical = self.repository.get_historical_amounts(issuer_tax_id=issuer_tax_id)
        if len(historical) < 3:
            return invoice  # not enough data to establish a baseline

        mean = sum(historical) / len(historical)
        variance = sum((x - mean) ** 2 for x in historical) / len(historical)
        std = variance ** 0.5

        if std == 0:
            return invoice

        z_score = abs(amount - mean) / std
        if z_score > 3.0:
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.SUSPICIOUS_AMOUNT,
                severity=FlagSeverity.WARNING,
                field_name="amount_ttc",
                message=(
                    f"Amount {amount:.3f} TND is {z_score:.1f} standard deviations "
                    f"from the historical mean ({mean:.3f} ± {std:.3f}) "
                    f"for issuer '{issuer_tax_id}'."
                ),
            ))
            logger.info(
                "statistical_outlier",
                invoice_id=str(invoice.id),
                z_score=z_score,
                mean=mean,
                std=std,
                issuer_tax_id=issuer_tax_id,
            )

        return invoice
