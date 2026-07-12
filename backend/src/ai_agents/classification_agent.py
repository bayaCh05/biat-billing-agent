"""Agent 2 — three-pass PCE classification with explanation.

Pass A: CostCatalog fuzzy keyword match (existing)
Pass B: TF-IDF + LogisticRegression ML (existing)
Pass C: RAG + Ollama (new)

After any pass: Ollama generates classification_reason in French.
"""
from __future__ import annotations

import logging

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_CONF_THRESHOLD = float(__import__("os").getenv("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.80"))


class ClassificationAgent(BaseAgent):
    name = "ClassificationAgent"

    def __init__(self, coder, classifier, cost_catalog) -> None:
        super().__init__()
        self._coder = coder
        self._classifier = classifier
        self._catalog = cost_catalog

    def run(self, context: dict) -> AgentResult:
        """context keys: invoice (InvoiceRecord), degraded_mode (bool)"""
        invoice = context["invoice"]
        degraded = context.get("degraded_mode", False)

        def _do() -> dict:
            nonlocal invoice
            # Direction classification (rule-based, always)
            invoice = self._classifier.classify(invoice)

            # Pass A + B via existing AccountingCoder
            invoice = self._coder.assign(invoice)

            pass_used = "CATALOG_FUZZY"
            conf = 1.0

            # Determine which pass was actually used and its confidence
            if invoice.cost_catalog_id:
                # Try to detect pass B usage (no direct marker, but ML classifier logs it)
                pass_used = "CATALOG_FUZZY"
            else:
                pass_used = "NONE"
                conf = 0.0

            # Pass C: RAG if no match found and not degraded
            if not invoice.cost_catalog_id and not degraded:
                pass_used = self._try_rag_pass(invoice)
                conf = 0.5  # RAG result is lower confidence

            # Revue humaine si la confiance est sous le seuil configurable
            if conf < _CONF_THRESHOLD:
                invoice.human_review_required = True
                logger.info(
                    "classification_low_confidence invoice=%s conf=%.2f "
                    "threshold=%.2f → revue humaine requise",
                    invoice.id, conf, _CONF_THRESHOLD,
                )

            # Classification explanation via Ollama
            reason = ""
            if invoice.cost_catalog_id and not degraded and OllamaClient.get().is_available():
                reason = self._generate_explanation(invoice)

            # Store on invoice
            invoice.classification_reason = reason
            invoice.classification_pass = pass_used

            return dict(
                output={
                    "catalog_id": invoice.cost_catalog_id,
                    "compte": invoice.accounting_compte,
                    "label": invoice.accounting_label,
                    "charge_type": invoice.charge_type.value if invoice.charge_type else None,
                    "pass_used": pass_used,
                    "classification_confidence": conf,
                    "classification_reason": reason,
                },
                confidence=conf,
                explanation=reason,
            )

        return self._run_safely(_do)

    def _try_rag_pass(self, invoice) -> str:
        try:
            from src.ai_agents.rag.rag_classifier import RAGClassifier
            result = RAGClassifier().classify(
                invoice.raw_extracted_text or "",
                invoice.line_items,
            )
            if result and result.get("id"):
                entry = self._catalog.get(result["id"])
                if entry:
                    invoice.cost_catalog_id = entry.id
                    invoice.accounting_compte = entry.compte
                    invoice.accounting_label = entry.label
                    invoice.charge_type = entry.type_charge
                    invoice.charge_nature = entry.nature
                    return "RAG_LLM"
        except Exception as exc:
            logger.warning("rag_pass_error: %s", exc)
        return "NONE"

    def _generate_explanation(self, invoice) -> str:
        issuer = invoice.issuer_name.value or ""
        catalog_label = invoice.accounting_label or ""
        compte = invoice.accounting_compte or ""
        top_item = (
            invoice.line_items[0].description
            if invoice.line_items
            else (invoice.raw_extracted_text or "")[:80]
        )

        try:
            from src.ai_agents.prompt_loader import PromptLoader
            prompt = PromptLoader.get().format(
                "classification_explain",
                issuer=issuer, top_item=top_item,
                catalog_label=catalog_label, compte=compte,
            )
        except Exception:
            prompt = (
                f'Une facture tunisienne de "{issuer}" pour "{top_item}" '
                f"a été classifiée:\n"
                f"Catégorie: {catalog_label}\nCompte PCE: {compte}\n\n"
                f"En UNE phrase courte en français, explique pourquoi cette classification "
                f"est correcte selon le PCE tunisien. Cite les mots clés qui ont guidé ce choix. "
                f"Maximum 150 caractères."
            )
        self._call_count += 1
        raw = OllamaClient.get().complete(prompt, temperature=0.1, max_tokens=80)
        return (raw or "").strip()[:200]
