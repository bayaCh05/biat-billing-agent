"""Agent 3 — anomaly detection (8 checks).

Wraps the existing anomaly/duplicate detectors and adds:
- Category price comparison (historical p90)
- Payment term anomaly
- Semantic near-duplicate via ChromaDB
"""
from __future__ import annotations

import logging
import re
import time

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag

logger = logging.getLogger(__name__)

_HIGH_VALUE_TND = float(__import__("os").getenv("ANOMALY_HIGH_VALUE_TND", "50000"))
_CATEGORY_PCT = int(__import__("os").getenv("ANOMALY_CATEGORY_PERCENTILE_THRESHOLD", "90"))

_TN_MF_RE = re.compile(r"^\d{7}[A-Z]/[A-Z]/[A-Z]/\d{3}$", re.IGNORECASE)


class AnomalyAgent(BaseAgent):
    name = "AnomalyAgent"

    def __init__(self, field_validator, coherence_checker, duplicate_detector,
                 anomaly_detector) -> None:
        super().__init__()
        self._fv = field_validator
        self._cc = coherence_checker
        self._dd = duplicate_detector
        self._ad = anomaly_detector

    def run(self, context: dict) -> AgentResult:
        """context keys: invoice (InvoiceRecord)"""
        start = time.monotonic()
        invoice: InvoiceRecord = context["invoice"]

        try:
            # Run existing validators (field, coherence, duplicate, anomaly)
            invoice = self._fv.validate(invoice)
            invoice = self._cc.check(invoice)
            invoice = self._dd.detect(invoice)
            invoice = self._ad.detect(invoice)

            # New: category price comparison
            self._check_category_price(invoice)

            # New: payment term anomaly
            self._check_payment_term(invoice)

            # New: semantic near-duplicate via embeddings
            self._check_semantic_duplicate(invoice)

            all_flags = invoice.flags
            error_count = sum(1 for f in all_flags if f.severity == FlagSeverity.ERROR)
            requires_review = error_count > 0 or invoice.human_review_required

            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={
                    "anomaly_count": len(all_flags),
                    "error_count": error_count,
                    "requires_human_review": requires_review,
                    "flag_types": [f.flag_type.value for f in all_flags],
                },
                ollama_calls_made=self._call_count,
            )

        except Exception as exc:
            logger.error("anomaly_agent_error: %s", exc)
            return AgentResult(
                agent_name=self.name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )

    def _check_category_price(self, invoice: InvoiceRecord) -> None:
        catalog_id = invoice.cost_catalog_id
        amount_ht = invoice.amount_ht.value
        if not catalog_id or not amount_ht:
            return

        try:
            from src.storage.sync_mongo_repository import historical_amounts_for_catalog_sync
            amounts = historical_amounts_for_catalog_sync(catalog_id, invoice.id)
            if len(amounts) < 5:
                return

            import numpy as np
            arr = np.array(amounts)
            median = float(np.median(arr))
            p_threshold = float(np.percentile(arr, _CATEGORY_PCT))
            mean = float(np.mean(arr))
            std = float(np.std(arr))
            z = (amount_ht - mean) / std if std > 0 else 0.0

            if amount_ht > p_threshold and z > 2.0:
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.SUSPICIOUS_AMOUNT,
                    severity=FlagSeverity.WARNING,
                    field_name="amount_ht",
                    message=(
                        f"Montant {amount_ht/median:.1f}× la médiane historique "
                        f"pour {catalog_id} "
                        f"(médiane: {median:.3f} TND, n={len(amounts)} factures)"
                    ),
                ))
        except Exception as exc:
            logger.debug("category_price_check_error: %s", exc)

    def _check_payment_term(self, invoice: InvoiceRecord) -> None:
        term = getattr(invoice, "payment_term_days", None)
        if not term:
            return

        tax_id = invoice.issuer_tax_id.value
        if not tax_id:
            return

        try:
            from src.storage.sync_mongo_repository import historical_payment_terms_sync
            historical = historical_payment_terms_sync(tax_id, invoice.id)
            if len(historical) < 3:
                return

            import numpy as np
            median_days = float(np.median(historical))

            if abs(term - median_days) > 15:
                invoice.add_flag(ValidationFlag(
                    flag_type=FlagType.PAYMENT_TERM_ANOMALY,
                    severity=FlagSeverity.WARNING,
                    field_name="due_date",
                    message=(
                        f"Délai {term}j inhabituel "
                        f"(habituel: {median_days:.0f}j pour ce fournisseur)"
                    ),
                ))
        except Exception as exc:
            logger.debug("payment_term_check_error: %s", exc)

    def _check_semantic_duplicate(self, invoice: InvoiceRecord) -> None:
        try:
            from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
            store = PCEVectorStore.get()
            if not store.available:
                return

            issuer = invoice.issuer_name.value or ""
            inv_num = invoice.invoice_number.value or ""
            amount = str(invoice.amount_ttc.value or "")
            inv_date = str(invoice.invoice_date.value or "")
            query = f"{issuer} {inv_num} {amount} {inv_date}"

            results = store.search_similar_invoices(
                query, n_results=3, exclude_id=str(invoice.id)
            )
            for r in results:
                if r["similarity"] > 0.92:
                    invoice.add_flag(ValidationFlag(
                        flag_type=FlagType.NEAR_DUPLICATE,
                        severity=FlagSeverity.WARNING,
                        message=(
                            f"Similaire à la facture {r['invoice_number'] or r['invoice_id'][:8]} "
                            f"({r['similarity']:.0%} similaire)"
                        ),
                    ))
                    break
        except Exception as exc:
            logger.debug("semantic_duplicate_check_error: %s", exc)
