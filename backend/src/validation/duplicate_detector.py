from __future__ import annotations

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

logger = get_logger(__name__)


class DuplicateDetector:
    """Detects exact and near-duplicate invoices.

    Exact match: same invoice_number + issuer_tax_id within window_days.
    Near match:  same amount + issuer_name (fuzzy) within window_days.
    """

    def __init__(self, config: dict, repository) -> None:
        self.window_days: int = config["validation"]["duplicate_window_days"]
        self.near_dup_tolerance: float = config["validation"].get(
            "near_duplicate_tolerance_relative", 0.01
        )
        self.repository = repository

    def with_repository(self, repository) -> "DuplicateDetector":
        """Retourne une copie superficielle avec un autre repository injecté.

        Utilisé par AIOrchestrator pour brancher un repository Mongo-natif
        sans muter l'instance partagée de PipelineComponents (encore utilisée
        par le daemon headless via agent/pipeline.py).
        """
        import copy
        clone = copy.copy(self)
        clone.repository = repository
        return clone

    def detect(self, invoice: InvoiceRecord) -> InvoiceRecord:
        invoice = self._check_exact_duplicates(invoice)
        if not invoice.has_errors:
            invoice = self._check_near_duplicates(invoice)
        return invoice

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_exact_duplicates(self, invoice: InvoiceRecord) -> InvoiceRecord:
        inv_num = invoice.invoice_number.value
        issuer_id = invoice.issuer_tax_id.value

        if inv_num is None or issuer_id is None:
            return invoice

        duplicates = self.repository.find_potential_duplicates(
            invoice_number=inv_num,
            issuer_tax_id=issuer_id,
            exclude_id=invoice.id,
            window_days=self.window_days,
        )

        if duplicates:
            dup_ids = [str(d.id) for d in duplicates]
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.DUPLICATE,
                severity=FlagSeverity.ERROR,
                field_name="invoice_number",
                message=(
                    f"Invoice number '{inv_num}' from issuer '{issuer_id}' "
                    f"already exists: {dup_ids}."
                ),
            ))
            logger.warning(
                "duplicate_detected",
                invoice_id=str(invoice.id),
                duplicate_ids=dup_ids,
            )

        return invoice

    def _check_near_duplicates(self, invoice: InvoiceRecord) -> InvoiceRecord:
        issuer = invoice.issuer_name.value
        amount = invoice.amount_ttc.value

        if issuer is None or amount is None:
            return invoice

        near = self.repository.find_near_duplicates(
            issuer_name=issuer,
            amount_ttc=amount,
            exclude_id=invoice.id,
            window_days=self.window_days,
            relative_tolerance=self.near_dup_tolerance,
        )

        if near:
            near_ids = [str(d.id) for d in near]
            invoice.add_flag(ValidationFlag(
                flag_type=FlagType.NEAR_DUPLICATE,
                severity=FlagSeverity.WARNING,
                field_name="amount_ttc",
                message=(
                    f"Invoice is suspiciously similar (same issuer + amount) "
                    f"to existing invoice(s): {near_ids}."
                ),
            ))
            logger.info(
                "near_duplicate_detected",
                invoice_id=str(invoice.id),
                near_ids=near_ids,
            )

        return invoice
