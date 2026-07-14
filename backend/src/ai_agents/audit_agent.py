"""Agent 7 — Audit transversal périodique.

Composant délibérément séparé du pipeline temps réel
(InvoiceProcessingOrchestrator) : ne l'appelle jamais, et n'appelle aucun
autre agent (ExtractionAgent, ClassificationAgent, AnomalyAgent,
AccountingAgent, RiskAgent, InsightAgent). Il lit exclusivement ce que ces
agents ont déjà écrit en base — factures, journal, budget, échéancier,
risques, roadmap — comme un auditeur qui lit le grand livre, jamais le
comptable qui l'écrit.

Lot 1 (ce fichier, 2026-07) : métriques par domaine + tendance vs snapshot
précédent de même granularité + alertes à seuils déterministes. AUCUN
rapprochement transversal (Lot 2), AUCUN RAG (Lot 3), AUCUNE synthèse LLM
(Lot 3) — narrative_summary reste toujours None à ce stade.

Perception/Décision/Action (Russell-Norvig, voir design validé) :
  - Perception  : _collect_metrics(), _get_previous_snapshot() — lecture
    seule via sync_mongo_repository.py, jamais d'appel à un autre agent.
  - Décision    : _compute_trend(), _evaluate_alerts() — règles à seuils
    déterministes, zéro LLM.
  - Action      : persistance du AuditSnapshotDocument (save_audit_snapshot_sync).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

_VALID_GRANULARITIES = {"DAILY", "WEEKLY", "MONTHLY"}

# Seuils d'alerte déterministes — aucun LLM impliqué dans leur évaluation.
_REJECTION_RATE_WARNING_PCT = 15.0
_BUDGET_VARIANCE_WARNING_PCT = 10.0
_JOURNAL_CONSISTENCY_SCORE_CRITICAL = 0.99


class AuditAgent(BaseAgent):
    name = "AuditAgent"

    def run(self, context: dict) -> AgentResult:
        """context keys: granularity ("DAILY" | "WEEKLY" | "MONTHLY", défaut DAILY)."""
        granularity = context.get("granularity", "DAILY")
        if granularity not in _VALID_GRANULARITIES:
            logger.warning("audit_agent_invalid_granularity value=%r → fallback=DAILY", granularity)
            granularity = "DAILY"

        def _do() -> dict:
            period_start, period_end = self._resolve_period(granularity)
            metrics, degraded = self._collect_metrics()
            previous = self._get_previous_snapshot(granularity)
            trend = self._compute_trend(metrics, previous)
            alerts = self._evaluate_alerts(metrics)

            from src.storage.sync_mongo_repository import save_audit_snapshot_sync
            snapshot_id = save_audit_snapshot_sync({
                "granularity": granularity,
                "period_start": period_start,
                "period_end": period_end,
                "status": "DEGRADED" if degraded else "OK",
                "metrics": metrics,
                "trend": trend,
                "alerts": alerts,
            })

            logger.info(
                "audit_snapshot_created id=%s granularity=%s alerts=%d degraded=%s",
                snapshot_id, granularity, len(alerts), degraded,
            )
            return dict(output={
                "snapshot_id": snapshot_id,
                "granularity": granularity,
                "alerts": alerts,
                "degraded": degraded,
            })

        return self._run_safely(_do)

    # ── Perception ────────────────────────────────────────────────────────────

    def _resolve_period(self, granularity: str) -> tuple[datetime, datetime]:
        """Bornes [period_start, period_end] (UTC minuit) de la période en cours."""
        today = date.today()
        if granularity == "DAILY":
            start = end = today
        elif granularity == "WEEKLY":
            start = today - timedelta(days=today.weekday())  # lundi de la semaine en cours
            end = start + timedelta(days=6)
        else:  # MONTHLY
            start = today.replace(day=1)
            next_month = start.replace(year=start.year + 1, month=1) if start.month == 12 \
                else start.replace(month=start.month + 1)
            end = next_month - timedelta(days=1)

        return (
            datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
            datetime(end.year, end.month, end.day, tzinfo=timezone.utc),
        )

    def _collect_metrics(self) -> tuple[dict, bool]:
        """Lit les métriques des 6 domaines. Ne s'interrompt jamais sur l'échec
        d'un domaine — le snapshot reste utile même partiel (status=DEGRADED)."""
        from src.storage.sync_mongo_repository import (
            budget_variance_kpis_sync, echeancier_kpis_sync,
            invoice_pending_rejected_30d_sync, journal_consistency_check_sync,
            risks_kpis_sync, roadmap_kpis_sync,
        )

        metrics: dict = {}
        degraded = False
        for domain, gather in (
            ("invoices", invoice_pending_rejected_30d_sync),
            ("journal", journal_consistency_check_sync),
            ("budget", budget_variance_kpis_sync),
            ("echeancier", echeancier_kpis_sync),
            ("risks", risks_kpis_sync),
            ("roadmap", roadmap_kpis_sync),
        ):
            try:
                metrics[domain] = gather()
            except Exception:
                logger.warning("audit_agent_metrics_error domain=%s", domain, exc_info=True)
                metrics[domain] = None
                degraded = True
        return metrics, degraded

    def _get_previous_snapshot(self, granularity: str) -> dict | None:
        from src.storage.sync_mongo_repository import get_latest_snapshot_sync
        return get_latest_snapshot_sync(granularity)

    # ── Décision ──────────────────────────────────────────────────────────────

    def _compute_trend(self, metrics: dict, previous: dict | None) -> dict:
        """Delta par métrique numérique vs le dernier snapshot de MÊME granularité.
        Snapshot immuable : ce delta est calculé une fois ici et persisté tel quel,
        jamais recalculé à la lecture."""
        if previous is None:
            return {}

        prev_metrics = previous.get("metrics") or {}
        trend: dict = {}
        for domain, current in metrics.items():
            prev = prev_metrics.get(domain)
            if not isinstance(current, dict) or not isinstance(prev, dict):
                continue
            deltas = {
                key: round(value - prev[key], 3)
                for key, value in current.items()
                if isinstance(value, (int, float)) and isinstance(prev.get(key), (int, float))
            }
            if deltas:
                trend[domain] = deltas
        return trend

    def _evaluate_alerts(self, metrics: dict) -> list[dict]:
        """Règles à seuils déterministes — aucun LLM impliqué."""
        alerts: list[dict] = []

        invoices = metrics.get("invoices") or {}
        rejection_rate = invoices.get("rejection_rate", 0)
        if rejection_rate > _REJECTION_RATE_WARNING_PCT:
            alerts.append({
                "domain": "invoices", "severity": "WARNING", "code": "HIGH_REJECTION_RATE",
                "message": (
                    f"Taux de rejet {rejection_rate:.1f}% "
                    f"(seuil {_REJECTION_RATE_WARNING_PCT:.0f}%)."
                ),
            })

        journal = metrics.get("journal") or {}
        consistency_score = journal.get("consistency_score", 1.0)
        if consistency_score < _JOURNAL_CONSISTENCY_SCORE_CRITICAL:
            alerts.append({
                "domain": "journal", "severity": "CRITICAL", "code": "JOURNAL_INCONSISTENCY",
                "message": (
                    f"Score de cohérence comptable {consistency_score:.3f} "
                    f"({len(journal.get('issues', []))} anomalie(s))."
                ),
            })

        budget = metrics.get("budget") or {}
        variance_pct = budget.get("variance_pct", 0)
        if abs(variance_pct) > _BUDGET_VARIANCE_WARNING_PCT:
            alerts.append({
                "domain": "budget", "severity": "WARNING", "code": "BUDGET_VARIANCE",
                "message": (
                    f"Écart budgétaire global {variance_pct:+.1f}% "
                    f"(seuil ±{_BUDGET_VARIANCE_WARNING_PCT:.0f}%)."
                ),
            })

        echeancier = metrics.get("echeancier") or {}
        n_late = echeancier.get("n_late", 0)
        if n_late > 0:
            alerts.append({
                "domain": "echeancier", "severity": "WARNING", "code": "LATE_INSTALLMENTS",
                "message": (
                    f"{n_late} échéance(s) en retard "
                    f"(pénalités cumulées : {echeancier.get('total_penalty_amount', 0):.3f} TND)."
                ),
            })

        risks = metrics.get("risks") or {}
        n_critique = risks.get("n_critique", 0)
        if n_critique > 0:
            alerts.append({
                "domain": "risks", "severity": "CRITICAL", "code": "CRITICAL_RISKS_ACTIVE",
                "message": f"{n_critique} risque(s) critique(s) actif(s).",
            })

        roadmap = metrics.get("roadmap") or {}
        n_overdue = roadmap.get("n_overdue_milestones", 0)
        if n_overdue > 0:
            alerts.append({
                "domain": "roadmap", "severity": "WARNING", "code": "OVERDUE_MILESTONES",
                "message": f"{n_overdue} jalon(s) roadmap en retard.",
            })

        return alerts
