"""Agent 1 — invoice extraction.

Wraps the existing HybridExtractor and adds:
- payment_term_days extraction
- quality-scored extraction method logging
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class ExtractionAgent(BaseAgent):
    name = "ExtractionAgent"

    def __init__(self, extractor) -> None:
        super().__init__()
        self._extractor = extractor  # HybridExtractor from AIComponents

    def run(self, context: dict) -> AgentResult:
        """context keys: invoice (InvoiceRecord)"""
        start = time.monotonic()
        invoice = context["invoice"]

        try:
            invoice = self._extractor.extract(invoice)

            # Extract payment_term_days if due_date and invoice_date are both present
            inv_date = invoice.invoice_date.value
            due = invoice.due_date.value
            if inv_date and due:
                delta = (due - inv_date).days
                if 0 < delta <= 365:
                    invoice.payment_term_days = delta

            min_conf = self._min_confidence(invoice)
            method = invoice.extraction_method.value if invoice.extraction_method else "unknown"

            if min_conf < 0.75:
                invoice.human_review_required = True
                logger.info(
                    "extraction_low_confidence invoice=%s conf=%.2f → revue humaine requise",
                    invoice.id, min_conf,
                )

            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={
                    "extraction_method": method,
                    "min_confidence": min_conf,
                    "human_review_required": min_conf < 0.75,
                    "payment_term_days": getattr(invoice, "payment_term_days", None),
                },
                confidence=min_conf,
                explanation=f"Méthode: {method}, confiance min: {min_conf:.0%}",
                ollama_calls_made=self._call_count,
            )

        except Exception as exc:
            logger.error("extraction_agent_error: %s", exc)
            return AgentResult(
                agent_name=self.name,
                success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )

    @staticmethod
    def _min_confidence(invoice) -> float:
        confs = []
        for field_name in ("issuer_name", "invoice_number", "amount_ht", "amount_ttc"):
            cf = getattr(invoice, field_name, None)
            if cf is not None:
                confs.append(cf.confidence)
        return min(confs) if confs else 0.0
