"""Agent 6 — insights.

Capability A: Natural language query (refactored from NLQueryEngine).
Capability B: Executive health summary for Direction dashboard.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.ai_agents.base_agent import BaseAgent
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class InsightAgent(BaseAgent):
    name = "InsightAgent"

    def __init__(self, engine) -> None:
        super().__init__()
        self._engine = engine

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
            engine = NLQueryEngine(self._engine)
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
        db: Session = context.get("db")

        kpis = self._gather_kpis(db) if db else {}

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

    def _gather_kpis(self, db: Session) -> dict:
        kpis = {}
        try:
            rows = db.execute(text(
                "SELECT "
                "COUNT(CASE WHEN status IN ('RECEIVED','EXTRACTING','EXTRACTED','CLASSIFYING','CLASSIFIED','VALIDATING') THEN 1 END) AS pending,"
                "COUNT(CASE WHEN status IN ('REJECTED','EXTRACTION_FAILED','ERROR') THEN 1 END) AS rejected,"
                "COUNT(*) AS total "
                "FROM invoices WHERE received_at >= date('now','-30 days')"
            )).fetchone()
            if rows:
                kpis["pending_count"] = rows[0] or 0
                kpis["rejection_rate"] = round((rows[1] or 0) / max(rows[2] or 1, 1) * 100, 1)
        except Exception:
            pass

        try:
            rows = db.execute(text(
                "SELECT COUNT(*) FROM feuilles_de_route WHERE date_fin < date('now') AND statut NOT IN ('TERMINE','ANNULE')"
            )).fetchone()
            kpis["n_overdue_milestones"] = rows[0] if rows else 0

            rows = db.execute(text(
                "SELECT COUNT(*) FROM feuilles_de_route WHERE statut = 'TERMINE'"
            )).fetchone()
            done = rows[0] if rows else 0
            rows = db.execute(text("SELECT COUNT(*) FROM feuilles_de_route")).fetchone()
            total = rows[0] if rows else 1
            kpis["pct_done"] = round(done / max(total, 1) * 100, 1)
        except Exception:
            pass

        try:
            rows = db.execute(text(
                "SELECT COUNT(*) FROM risques WHERE niveau_criticite = 'CRITIQUE' AND statut NOT IN ('CLOTURE','MAITRISE')"
            )).fetchone()
            kpis["n_critique"] = rows[0] if rows else 0
        except Exception:
            pass

        # Budget — n_over_budget, n_total, variance_pct
        try:
            from datetime import date as _date
            from sqlalchemy import and_, func, select
            from src.storage.orm_models import BudgetPlanORM, InvoiceORM

            _now = _date.today()
            _year = _now.year
            _month = _now.month

            entries = db.execute(
                select(BudgetPlanORM).where(BudgetPlanORM.year == _year)
            ).scalars().all()

            budget_ytd: dict[str, float] = {
                e.catalog_id: sum(float(m) for m in (e.monthly or [])[:_month])
                for e in entries
            }

            actual_rows = db.execute(
                select(
                    InvoiceORM.cost_catalog_id,
                    func.sum(InvoiceORM.amount_ht).label("total"),
                )
                .where(
                    and_(
                        InvoiceORM.status.in_(("VALIDATED", "EXPORTED", "PAID", "JOURNALED")),
                        InvoiceORM.direction == "SUPPLIER",
                        InvoiceORM.invoice_date >= _date(_year, 1, 1),
                        InvoiceORM.invoice_date <= _now,
                        InvoiceORM.cost_catalog_id.isnot(None),
                    )
                )
                .group_by(InvoiceORM.cost_catalog_id)
            ).all()
            actual_ytd: dict[str, float] = {r[0]: float(r[1] or 0) for r in actual_rows}

            total_budget = sum(budget_ytd.values())
            total_actual = sum(actual_ytd.get(cid, 0.0) for cid in budget_ytd)

            kpis["n_total"] = len(budget_ytd)
            kpis["n_over_budget"] = sum(
                1 for cid, b in budget_ytd.items() if actual_ytd.get(cid, 0.0) > b
            )
            kpis["variance_pct"] = (
                round((total_actual - total_budget) / total_budget * 100, 1)
                if total_budget else 0.0
            )
        except Exception:
            pass

        # Risques — n_overdue_mitigation
        try:
            row = db.execute(text(
                "SELECT COUNT(*) FROM risques "
                "WHERE date_echeance_mitigation < date('now') "
                "AND statut NOT IN ('CLOTURE','MAITRISE')"
            )).fetchone()
            kpis["n_overdue_mitigation"] = row[0] if row else 0
        except Exception:
            pass

        return kpis
