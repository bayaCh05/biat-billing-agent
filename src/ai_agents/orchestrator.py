"""AI Orchestrator — coordinates all agents for invoice processing and secondary flows.

Integrates with the existing PipelineComponents system.
Built as synchronous to match the existing FastAPI + SQLAlchemy patterns.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from src.ai_agents.models import OrchestratorResult, PipelineStep
from src.ai_agents.ollama_client import OllamaClient
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord

if TYPE_CHECKING:
    from src.agent.pipeline import PipelineComponents

logger = logging.getLogger(__name__)


class AIOrchestrator:
    """Coordinates AI agents for the complete invoice processing pipeline."""

    def __init__(self, components: "PipelineComponents", db: Session) -> None:
        self._c = components
        self._db = db
        self._steps: list[PipelineStep] = []

    def process_invoice(self, invoice: InvoiceRecord) -> OrchestratorResult:
        """Run a pre-loaded InvoiceRecord through the full AI pipeline.

        The invoice should already be in RECEIVED status with raw_file_path set.
        """
        start = time.monotonic()
        self._steps = []
        degraded = not OllamaClient.get().is_available()

        if degraded:
            logger.warning("ollama_unavailable — running in degraded mode (no LLM calls)")

        # ── Step 1: Extraction ────────────────────────────────────────────────
        step1 = PipelineStep(step_number=1, agent_name="ExtractionAgent", status="running")
        self._steps.append(step1)

        try:
            from src.ai_agents.extraction_agent import ExtractionAgent
            agent = ExtractionAgent(self._c.extractor)
            result = agent.run({"invoice": invoice})

            if not result.success:
                step1.status = "failed"
                step1.summary = result.error
                return self._fail(invoice, "EXTRACTION_FAILED", start, degraded)

            invoice.status = InvoiceStatus.EXTRACTED
            self._c.repository.save(invoice)
            step1.status = "done"
            step1.duration_ms = result.duration_ms
            step1.summary = result.explanation

        except Exception as exc:
            step1.status = "failed"
            step1.summary = str(exc)
            return self._fail(invoice, "EXTRACTION_FAILED", start, degraded)

        # ── Step 2: Classification ────────────────────────────────────────────
        step2 = PipelineStep(step_number=2, agent_name="ClassificationAgent", status="running")
        self._steps.append(step2)

        try:
            from src.ai_agents.classification_agent import ClassificationAgent
            agent2 = ClassificationAgent(self._c.coder, self._c.classifier, self._c.cost_catalog)
            result2 = agent2.run({"invoice": invoice, "degraded_mode": degraded})

            if not result2.success:
                step2.status = "failed"
                step2.summary = result2.error
                return self._fail(invoice, "ERROR", start, degraded)

            invoice.status = InvoiceStatus.CLASSIFIED
            self._c.repository.save(invoice)
            step2.status = "done"
            step2.duration_ms = result2.duration_ms
            step2.summary = (
                f"Compte: {invoice.accounting_compte} via "
                f"{result2.output.get('pass_used','?')}"
            )

        except Exception as exc:
            step2.status = "failed"
            step2.summary = str(exc)
            logger.error("classification_agent_error invoice=%s: %s", invoice.id, exc)
            return self._fail(invoice, "ERROR", start, degraded)

        # ── Step 3: Anomaly detection ─────────────────────────────────────────
        step3 = PipelineStep(step_number=3, agent_name="AnomalyAgent", status="running")
        self._steps.append(step3)

        try:
            from src.ai_agents.anomaly_agent import AnomalyAgent
            agent3 = AnomalyAgent(
                self._c.field_validator,
                self._c.coherence_checker,
                self._c.duplicate_detector,
                self._c.anomaly_detector,
            )
            result3 = agent3.run({"invoice": invoice, "db": self._db})

            step3.status = "done"
            step3.duration_ms = result3.duration_ms
            n_flags = result3.output.get("anomaly_count", 0)
            step3.summary = f"{n_flags} anomalie(s)" if n_flags else "Aucune anomalie"

            if result3.output.get("requires_human_review"):
                invoice.status = InvoiceStatus.FLAGGED
                invoice.human_review_required = True
                self._c.repository.save(invoice)
                step4 = PipelineStep(step_number=4, agent_name="AccountingAgent",
                                     status="skipped", summary="En attente de révision humaine")
                self._steps.append(step4)

                return OrchestratorResult(
                    invoice_id=str(invoice.id),
                    final_status="FLAGGED",
                    pipeline_steps=self._steps,
                    total_duration_ms=(time.monotonic() - start) * 1000,
                    degraded_mode=degraded,
                    human_review_required=True,
                )

            invoice.status = InvoiceStatus.VALIDATED
            self._c.repository.save(invoice)

        except Exception as exc:
            step3.status = "failed"
            step3.summary = str(exc)
            logger.error("anomaly_agent_error invoice=%s: %s", invoice.id, exc)
            step4 = PipelineStep(step_number=4, agent_name="AccountingAgent",
                                 status="skipped",
                                 summary="Bloqué — échec de la détection d'anomalies")
            self._steps.append(step4)
            return self._fail(invoice, "ERROR", start, degraded)

        # ── Step 4: Accounting ────────────────────────────────────────────────
        step4 = PipelineStep(step_number=4, agent_name="AccountingAgent", status="running")
        self._steps.append(step4)

        try:
            from src.ai_agents.accounting_agent import AccountingAgent
            agent4 = AccountingAgent(
                self._c.entry_generator,
                self._c.journal_repository,
                self._c.cost_catalog,
            )
            result4 = agent4.run({"invoice": invoice, "db": self._db})

            invoice.status = InvoiceStatus.JOURNALED
            self._c.repository.save(invoice)
            step4.status = "done"
            step4.duration_ms = result4.duration_ms
            balanced = "équilibrée" if result4.output.get("is_balanced") else "DÉSÉQUILIBRÉE"
            n_installments = result4.output.get("installments_created", 0)
            step4.summary = (
                f"Écriture {balanced}, {n_installments} échéance(s)"
            )

            # Store invoice in semantic index for future duplicate detection
            self._embed_invoice(invoice)

        except Exception as exc:
            step4.status = "failed"
            step4.summary = str(exc)
            logger.error("accounting_agent_error invoice=%s: %s", invoice.id, exc)
            return self._fail(invoice, "ERROR", start, degraded)

        return OrchestratorResult(
            invoice_id=str(invoice.id),
            final_status=invoice.status.value,
            pipeline_steps=self._steps,
            total_duration_ms=(time.monotonic() - start) * 1000,
            degraded_mode=degraded,
            human_review_required=False,
        )

    # ── Secondary flows ───────────────────────────────────────────────────────

    def scan_risks(self, db: Session) -> dict:
        from src.ai_agents.risk_agent import RiskAgent
        result = RiskAgent().run({"task": "scan_roadmap", "db": db})
        return result.output

    def suggest_mitigation(self, titre: str, type_risque: str,
                            probabilite: str, impact: str) -> str:
        from src.ai_agents.risk_agent import RiskAgent
        result = RiskAgent().run({
            "task": "draft_mitigation",
            "titre": titre, "type_risque": type_risque,
            "probabilite": probabilite, "impact": impact,
        })
        return result.output.get("suggestion", "")

    def generate_health_summary(self, db: Session) -> dict:
        from src.ai_agents.insight_agent import InsightAgent
        agent = InsightAgent(self._c.repository.session.get_bind())
        result = agent.run({"task": "health_summary", "db": db})
        return result.output

    def check_accounting_consistency(self, db: Session) -> dict:
        from src.ai_agents.accounting_agent import AccountingAgent
        agent = AccountingAgent(
            self._c.entry_generator, self._c.journal_repository, self._c.cost_catalog
        )
        return agent.check_consistency(db)

    def retrain_models(self) -> dict:
        try:
            self._c.coder.ml_classifier.retrain_from_repo(self._c.repository)
            return {"status": "ok", "message": "ML model retrained."}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fail(self, invoice: InvoiceRecord, status: str,
              start: float, degraded: bool) -> OrchestratorResult:
        invoice.status = InvoiceStatus(status)
        try:
            self._c.repository.save(invoice)
        except Exception:
            pass
        return OrchestratorResult(
            invoice_id=str(invoice.id),
            final_status=status,
            pipeline_steps=self._steps,
            total_duration_ms=(time.monotonic() - start) * 1000,
            degraded_mode=degraded,
            human_review_required=False,
        )

    def _embed_invoice(self, invoice: InvoiceRecord) -> None:
        try:
            from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
            store = PCEVectorStore.get()
            if store.available:
                issuer = invoice.issuer_name.value or ""
                inv_num = invoice.invoice_number.value or ""
                amount = str(invoice.amount_ttc.value or "")
                inv_date = str(invoice.invoice_date.value or "")
                text = f"{issuer} {inv_num} {amount} {inv_date}"
                store.store_invoice_embedding(
                    invoice_id=str(invoice.id),
                    embedding_text=text,
                    invoice_number=inv_num,
                )
        except Exception as exc:
            logger.debug("invoice_embed_error: %s", exc)
