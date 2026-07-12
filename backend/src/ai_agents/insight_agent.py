"""Agent 6 — insights.

Capability A: Natural language query (refactored from NLQueryEngine).
Capability B: Executive health summary for Direction dashboard.
"""
from __future__ import annotations

import logging
import time

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class InsightAgent(BaseAgent):
    name = "InsightAgent"

    def run(self, context: dict) -> AgentResult:
        task = context.get("task", "nl_query")
        if task == "health_summary":
            return self._health_summary(context)
        return self._nl_query(context)

    # ── Capability A — NL query ───────────────────────────────────────────────

    def _nl_query(self, context: dict) -> AgentResult:
        start = time.monotonic()
        question = context.get("question", "")

        if not OllamaClient.get().is_available():
            return AgentResult(
                agent_name=self.name, success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error="Ollama non disponible.",
                ollama_calls_made=0,
            )

        try:
            from src.query.nl_query_engine import NLQueryEngine
            engine = NLQueryEngine()
            result = engine.query(question)

            return AgentResult(
                agent_name=self.name,
                success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output=result,
                explanation=result.get("answer"),
                ollama_calls_made=self._call_count + 1,
            )
        except Exception as exc:
            return AgentResult(
                agent_name=self.name, success=False,
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(exc),
                ollama_calls_made=self._call_count,
            )

    # ── Capability B — executive health summary ───────────────────────────────

    def _health_summary(self, context: dict) -> AgentResult:
        start = time.monotonic()

        kpis = self._gather_kpis()

        if not OllamaClient.get().is_available():
            return AgentResult(
                agent_name=self.name, success=True,
                duration_ms=(time.monotonic() - start) * 1000,
                output={"summary": "Ollama non disponible — résumé IA indisponible.", **kpis},
                ollama_calls_made=0,
            )

        prompt = (
            f"Tu es assistant de direction financière de BIAT IT.\n"
            f"Rédige un résumé exécutif EN 3 PHRASES MAXIMUM.\n\n"
            f"Situation actuelle:\n"
            f"- Factures: {kpis.get('pending_count', 0)} en attente, "
            f"{kpis.get('rejection_rate', 0):.1f}% rejetées ce mois\n"
            f"- Budget: {kpis.get('n_over_budget', 0)} lignes dépassées / {kpis.get('n_total', 0)}, "
            f"écart global {kpis.get('variance_pct', 0):+.1f}%\n"
            f"- Roadmap 2026: {kpis.get('pct_done', 0):.0f}% complétée, "
            f"{kpis.get('n_overdue_milestones', 0)} jalons en retard\n"
            f"- Risques: {kpis.get('n_critique', 0)} critiques actifs, "
            f"{kpis.get('n_overdue_mitigation', 0)} plans de mitigation en retard\n\n"
            f"Commence par: \"Satisfaisant\" | \"Vigilance requise\" | \"Situation critique\"\n"
            f"Puis les 2 points les plus importants. Sois factuel et direct."
        )
        self._call_count += 1
        raw = OllamaClient.get().complete(prompt, temperature=0.3, max_tokens=200)
        summary = (raw or "Données insuffisantes pour générer un résumé.").strip()

        status_label = "Satisfaisant"
        if "critique" in summary.lower():
            status_label = "Critique"
        elif "vigilance" in summary.lower():
            status_label = "Vigilance requise"

        return AgentResult(
            agent_name=self.name,
            success=True,
            duration_ms=(time.monotonic() - start) * 1000,
            output={
                "summary": summary,
                "status_label": status_label,
                "kpis_snapshot": kpis,
            },
            explanation=summary,
            ollama_calls_made=self._call_count,
        )

    def _gather_kpis(self) -> dict:
        from src.storage.sync_mongo_repository import (
            budget_variance_kpis_sync,
            invoice_pending_rejected_30d_sync,
            risks_kpis_sync,
            roadmap_kpis_sync,
        )

        kpis: dict = {}
        for name, gather in (
            ("invoices", invoice_pending_rejected_30d_sync),
            ("roadmap", roadmap_kpis_sync),
            ("risques", risks_kpis_sync),
            ("budget", budget_variance_kpis_sync),
        ):
            try:
                kpis.update(gather())
            except Exception:
                logger.warning("insight_agent: échec collecte KPI %s", name, exc_info=True)

        return kpis
