"""Agent 7 — Audit transversal périodique.

Composant délibérément séparé du pipeline temps réel
(InvoiceProcessingOrchestrator) : ne l'appelle jamais, et n'appelle aucun
autre agent (ExtractionAgent, ClassificationAgent, AnomalyAgent,
AccountingAgent, RiskAgent, InsightAgent). Il lit exclusivement ce que ces
agents ont déjà écrit en base — factures, journal, budget, échéancier,
risques, roadmap — comme un auditeur qui lit le grand livre, jamais le
comptable qui l'écrit.

Lot 1 : métriques par domaine + tendance vs snapshot précédent de même
granularité + alertes à seuils déterministes.

Lot 2 (ce fichier, 2026-07) : rapprochement transversal facture ↔ échéancier
↔ budget ↔ journal (_cross_check()) — comble des trous que les métriques
Lot 1 ne couvraient pas (ex: journal_consistency_check_sync vérifie
débit=crédit par écriture, jamais qu'une facture JOURNALED a une écriture du
tout). Toujours 100% déterministe. AUCUN RAG (Lot 3), AUCUNE synthèse LLM
(Lot 3) — narrative_summary/similar_incidents restent vides à ce stade.

Perception/Décision/Action (Russell-Norvig, voir design validé) :
  - Perception  : _collect_metrics(), _cross_check(), _get_previous_snapshot()
    — lecture seule via sync_mongo_repository.py, jamais d'appel à un autre agent.
  - Décision    : _compute_trend(), _evaluate_alerts(), _evaluate_reconciliation_alerts()
    — règles à seuils déterministes, zéro LLM.
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
            metrics, metrics_degraded = self._collect_metrics()
            reconciliation, reconciliation_degraded = self._cross_check()
            previous = self._get_previous_snapshot(granularity)
            trend = self._compute_trend(metrics, previous)
            alerts = self._evaluate_alerts(metrics)
            alerts += self._evaluate_reconciliation_alerts(reconciliation)
            degraded = metrics_degraded or reconciliation_degraded

            from src.storage.sync_mongo_repository import save_audit_snapshot_sync
            snapshot_id = save_audit_snapshot_sync({
                "granularity": granularity,
                "period_start": period_start,
                "period_end": period_end,
                "status": "DEGRADED" if degraded else "OK",
                "metrics": metrics,
                "trend": trend,
                "alerts": alerts,
                "reconciliation": reconciliation,
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

    def _cross_check(self) -> tuple[dict, bool]:
        """Rapprochement transversal facture ↔ échéancier ↔ budget ↔ journal
        (Lot 2). Évalué sur l'état courant complet (comme
        journal_consistency_check_sync), pas filtré à la période du snapshot —
        "une facture en retard" ne dépend pas de la granularité DAILY/WEEKLY/
        MONTHLY en cours."""
        from src.storage.sync_mongo_repository import (
            budget_overrun_top_invoices_sync, invoices_journal_mismatch_sync,
            invoices_overdue_without_installment_plan_sync,
            late_installments_invoice_not_flagged_sync,
        )

        reconciliation: dict = {}
        degraded = False
        for check, gather in (
            ("overdue_without_installment_plan", invoices_overdue_without_installment_plan_sync),
            ("late_installment_not_flagged", late_installments_invoice_not_flagged_sync),
            ("budget_overrun_attribution", budget_overrun_top_invoices_sync),
            ("journal_mismatch", invoices_journal_mismatch_sync),
        ):
            try:
                reconciliation[check] = gather()
            except Exception:
                logger.warning("audit_agent_reconciliation_error check=%s", check, exc_info=True)
                reconciliation[check] = None
                degraded = True
        return reconciliation, degraded

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

    def _evaluate_reconciliation_alerts(self, reconciliation: dict) -> list[dict]:
        """Règles à seuils déterministes sur le rapprochement transversal (Lot 2)
        — mêmes garanties que _evaluate_alerts() : aucun LLM impliqué."""
        alerts: list[dict] = []

        overdue_no_plan = reconciliation.get("overdue_without_installment_plan") or {}
        if overdue_no_plan.get("count", 0) > 0:
            alerts.append({
                "domain": "echeancier", "severity": "WARNING", "code": "MISSING_INSTALLMENT_PLAN",
                "message": (
                    f"{overdue_no_plan['count']} facture(s) en retard sans échéancier "
                    "(payment_installments)."
                ),
            })

        late_not_flagged = reconciliation.get("late_installment_not_flagged") or {}
        if late_not_flagged.get("count", 0) > 0:
            alerts.append({
                "domain": "echeancier", "severity": "WARNING", "code": "LATE_INSTALLMENT_NOT_FLAGGED",
                "message": (
                    f"{late_not_flagged['count']} échéance(s) en retard dont la facture "
                    "parente n'est pas marquée pour révision humaine."
                ),
            })

        journal_mismatch = reconciliation.get("journal_mismatch") or {}
        if journal_mismatch.get("missing_entry_count", 0) > 0:
            alerts.append({
                "domain": "journal", "severity": "CRITICAL", "code": "JOURNALED_WITHOUT_ENTRY",
                "message": (
                    f"{journal_mismatch['missing_entry_count']} facture(s) JOURNALED "
                    "sans écriture comptable correspondante."
                ),
            })
        if journal_mismatch.get("duplicate_entry_count", 0) > 0:
            alerts.append({
                "domain": "journal", "severity": "CRITICAL", "code": "DUPLICATE_JOURNAL_ENTRY",
                "message": (
                    f"{journal_mismatch['duplicate_entry_count']} facture(s) JOURNALED "
                    "avec plusieurs écritures comptables."
                ),
            })
        if journal_mismatch.get("amount_mismatch_count", 0) > 0:
            alerts.append({
                "domain": "journal", "severity": "CRITICAL", "code": "AMOUNT_MISMATCH_JOURNAL",
                "message": (
                    f"{journal_mismatch['amount_mismatch_count']} facture(s) dont le montant "
                    "ne correspond pas à l'écriture comptable (tolérance 0,005 TND)."
                ),
            })

        return alerts
