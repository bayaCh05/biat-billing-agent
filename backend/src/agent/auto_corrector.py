"""Correction automatique des factures après validation.

Passe unique, entièrement locale (aucun appel réseau) :

  MathCorrector :
    Déterministe. Si HT + TVA ≠ TTC et qu'un montant a une confiance
    nettement inférieure aux deux autres, il est recalculé sans appel LLM.

Tout traitement IA reste local (Ollama) — politique de résidence des
données BIAT IT (filiale bancaire, données confidentielles).
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.models.enums import FlagSeverity, FlagType, InvoiceStatus
from src.models.invoice import ConfidenceField, InvoiceRecord
from src.utils.logging import get_logger
from src.validation.anomaly_detector import AnomalyDetector
from src.validation.coherence_checker import CoherenceChecker
from src.validation.duplicate_detector import DuplicateDetector
from src.validation.field_validator import FieldValidator

logger = get_logger(__name__)

# Champs que la correction automatique est autorisée à modifier.
_CORRECTABLE: dict[str, type] = {
    "issuer_name":      str,
    "issuer_tax_id":    str,
    "recipient_name":   str,
    "recipient_tax_id": str,
    "invoice_number":   str,
    "amount_ht":        float,
    "tva_rate":         float,
    "tva_amount":       float,
    "amount_ttc":       float,
}


# ── Passe 1 : correcteur mathématique ────────────────────────────────────────

class MathCorrector:
    """Recompute le montant le moins fiable quand HT + TVA ≠ TTC."""

    def __init__(self, config: dict) -> None:
        self._abs_tol = config["validation"]["math_tolerance_absolute"]
        self._rel_tol = config["validation"]["math_tolerance_relative"]
        self._ratio_threshold = config["correction"]["math_confidence_ratio_threshold"]
        self._corrected_conf = config["correction"]["math_corrected_confidence"]

    def correct(self, invoice: InvoiceRecord) -> InvoiceRecord:
        if not any(
            f.flag_type == FlagType.TOTAL_MISMATCH and not f.resolved
            for f in invoice.flags
        ):
            return invoice

        ht, tva, ttc = invoice.amount_ht, invoice.tva_amount, invoice.amount_ttc
        if any(v.value is None for v in (ht, tva, ttc)):
            return invoice

        amounts = [("amount_ht", ht), ("tva_amount", tva), ("amount_ttc", ttc)]
        amounts.sort(key=lambda x: x[1].confidence)
        weakest_name, weakest = amounts[0]
        _, second = amounts[1]

        if weakest.confidence > second.confidence * self._ratio_threshold:
            return invoice

        if weakest_name == "amount_ttc":
            new_value = round(ht.value + tva.value, 3)
        elif weakest_name == "amount_ht":
            new_value = round(ttc.value - tva.value, 3)
        else:
            new_value = round(ttc.value - ht.value, 3)

        fixed = {"amount_ht": ht.value, "tva_amount": tva.value, "amount_ttc": ttc.value}
        fixed[weakest_name] = new_value
        tolerance = max(self._abs_tol, fixed["amount_ttc"] * self._rel_tol)
        if abs(fixed["amount_ht"] + fixed["tva_amount"] - fixed["amount_ttc"]) > tolerance:
            return invoice

        setattr(invoice, weakest_name, ConfidenceField(
            value=new_value, confidence=self._corrected_conf, source="math_correction",
        ))
        for f in invoice.flags:
            if f.flag_type == FlagType.TOTAL_MISMATCH:
                f.resolved = True
        logger.info("math_correction_applied",
                    invoice_id=str(invoice.id), field=weakest_name, new_value=new_value)
        return invoice


# ── Orchestrateur de correction ───────────────────────────────────────────────

class AutoCorrector:
    def __init__(self, config: dict, repository) -> None:
        self._math = MathCorrector(config)
        self._ai_conf = config["correction"]["ai_corrected_confidence"]
        self._validators = (
            FieldValidator(confidence_thresholds=config["extraction"]["confidence_thresholds"]),
            CoherenceChecker(config=config),
            DuplicateDetector(config=config, repository=repository),
            AnomalyDetector(config=config, repository=repository),
        )

    def correct(self, invoice: InvoiceRecord) -> InvoiceRecord:
        open_errors = sum(
            1 for f in invoice.flags if not f.resolved and f.severity == FlagSeverity.ERROR
        )
        logger.info("auto_correction_started",
                    invoice_id=str(invoice.id), open_errors=open_errors)

        invoice = self._math.correct(invoice)
        invoice = self._revalidate(invoice)
        if not invoice.has_errors:
            logger.info("auto_correction_resolved_by_math", invoice_id=str(invoice.id))

        return invoice

    def _revalidate(self, invoice: InvoiceRecord) -> InvoiceRecord:
        # Keep resolved flags (audit trail) and discard only the unresolved ones
        # that the math corrector may have fixed — validators will re-add any
        # errors that genuinely remain.
        invoice.flags = [f for f in invoice.flags if f.resolved]
        fv, cc, dd, ad = self._validators
        invoice = fv.validate(invoice)
        invoice = cc.check(invoice)
        invoice = dd.detect(invoice)
        invoice = ad.detect(invoice)
        invoice.validated_at = datetime.now(timezone.utc)
        invoice.status = InvoiceStatus.FLAGGED if invoice.has_errors else InvoiceStatus.VALIDATED
        return invoice

