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

Lot 2 : rapprochement transversal facture ↔ échéancier ↔ budget ↔ journal
(_cross_check()) — comble des trous que les métriques Lot 1 ne couvraient
pas (ex: journal_consistency_check_sync vérifie débit=crédit par écriture,
jamais qu'une facture JOURNALED a une écriture du tout). Toujours 100%
déterministe.

Lot 3 (ce fichier, 2026-07) : enrichissement narratif par RAG. L'agent
indexe lui-même (jamais RiskAgent/AnomalyAgent) les risques et anomalies
créés depuis le dernier snapshot dans une collection ChromaDB dédiée
(audit_incidents, voir rag/pce_vectorstore.py), retrouve les incidents
passés similaires aux alertes du jour, et ne demande au LLM QU'UNE
synthèse en langage naturel à partir de métriques déjà calculées et
d'incidents déjà retrouvés — jamais un calcul ou une estimation de chiffre
(voir _build_narrative_prompt()). Le RAG est un outil de récupération : il
n'influence aucune alerte, toutes déjà décidées avant qu'il n'intervienne.

Perception/Décision/Action (Russell-Norvig, voir design validé) :
  - Perception  : _collect_metrics(), _cross_check(), _get_previous_snapshot(),
    _retrieve_similar_incidents() — lecture seule via sync_mongo_repository.py
    et ChromaDB, jamais d'appel à un autre agent.
  - Décision    : _compute_trend(), _evaluate_alerts(), _evaluate_reconciliation_alerts()
    — règles à seuils déterministes, zéro LLM.
  - Action      : _index_new_incidents() (écriture ChromaDB), _generate_narrative()
    (texte, jamais de chiffre), persistance du AuditSnapshotDocument
    (save_audit_snapshot_sync).
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

            self._index_new_incidents(previous)
            similar_incidents = self._retrieve_similar_incidents(alerts)
            narrative_summary, narrative_degraded = self._generate_narrative(
                metrics, trend, alerts, reconciliation, similar_incidents
            )
            degraded = metrics_degraded or reconciliation_degraded or narrative_degraded

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
                "similar_incidents": similar_incidents,
                "narrative_summary": narrative_summary,
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

    def _index_new_incidents(self, previous: dict | None) -> None:
        """Indexe dans ChromaDB (audit_incidents) les risques/anomalies créés
        depuis le dernier snapshot de même granularité. Rien à indexer au tout
        premier run (previous is None) — l'historique complet se peuple une
        fois via scripts/backfill_audit_incidents.py, jamais dans ce job
        périodique (coût d'indexation potentiellement important sur un
        historique jamais indexé — voir ce script pour le détail)."""
        if previous is None:
            return

        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
        store = PCEVectorStore.get()
        if not store.available:
            return

        since = previous.get("generated_at")
        from src.storage.sync_mongo_repository import (
            invoice_flags_created_since_sync, risques_created_since_sync,
        )

        try:
            for r in risques_created_since_sync(since):
                store.index_incident(
                    "risque", r["_id"],
                    f"{r.get('titre', '')} {r.get('description', '')}".strip(),
                    {"date": str(r.get("created_at", "")), "severity": r.get("niveau_criticite", "")},
                )
            for f in invoice_flags_created_since_sync(since):
                store.index_incident(
                    "anomaly", f.get("flag_id") or f"{f['invoice_id']}:{f.get('flag_type', '')}",
                    f"{f.get('flag_type', '')} {f.get('message', '')}".strip(),
                    {"date": str(f.get("created_at", "")), "severity": f.get("severity", "")},
                )
        except Exception:
            logger.warning("audit_agent_indexing_error", exc_info=True)

    def _retrieve_similar_incidents(self, alerts: list[dict]) -> list[dict]:
        """RAG : jusqu'à 3 incidents passés similaires par alerte CRITICAL/
        WARNING. Retrieval seul — n'influence aucune alerte, toutes déjà
        décidées avant cet appel (voir docstring de module)."""
        if not alerts:
            return []
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
        store = PCEVectorStore.get()
        if not store.available:
            return []

        similar: list[dict] = []
        for alert in alerts:
            try:
                # 0.40, not 0.75: cosine similarity between a short aggregate
                # alert sentence and an indexed incident's "{flag_type} {message}"/
                # "{titre} {description}" text tops out well under 0.75 with
                # paraphrase-multilingual-MiniLM-L12-v2 — calibrated empirically
                # against known same-domain/different-domain message pairs.
                found = store.search_similar_incidents(
                    alert["message"], n_results=3, min_similarity=0.40
                )
            except Exception:
                logger.warning(
                    "audit_agent_retrieval_error alert_code=%s", alert.get("code"), exc_info=True
                )
                continue
            similar.extend({**item, "related_alert_code": alert["code"]} for item in found)
        return similar

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

    # ── Action (RAG déjà récupéré ci-dessus, texte à produire ici) ─────────────

    def _generate_narrative(
        self, metrics: dict, trend: dict, alerts: list[dict], reconciliation: dict,
        similar_incidents: list[dict],
    ) -> tuple[str | None, bool]:
        """Synthèse en langage naturel — le LLM ne reçoit QUE des métriques déjà
        calculées et des incidents déjà retrouvés par le RAG ; il ne recalcule
        ni n'invente aucun chiffre (voir _build_narrative_prompt()).
        Retourne (résumé | None, narrative_degraded: bool)."""
        from src.ai_agents.ollama_client import OllamaClient
        if not OllamaClient.get().is_available():
            return None, True

        prompt = self._build_narrative_prompt(metrics, trend, alerts, reconciliation, similar_incidents)
        raw = self._call_ollama(prompt, temperature=0.3, max_tokens=250)
        if not raw:
            return None, True
        return raw.strip(), False

    def _format_reconciliation_detail(self, reconciliation: dict) -> list[str]:
        """Échantillon détaillé (factures/montants) du rapprochement transversal
        (Lot 2) pour le prompt narratif — jamais seulement le compte agrégé,
        pour permettre au LLM de relier des domaines entre eux (ex: quelle(s)
        facture(s) précisément alimentent un dépassement budgétaire)."""
        out: list[str] = []

        overdue = reconciliation.get("overdue_without_installment_plan") or {}
        if overdue.get("count", 0) > 0:
            examples = ", ".join(
                d.get("invoice_number") or d.get("invoice_id", "?")
                for d in overdue.get("detail", [])[:3]
            )
            out.append(
                f"- {overdue['count']} facture(s) en retard sans échéancier (ex: {examples})."
            )

        late_nf = reconciliation.get("late_installment_not_flagged") or {}
        if late_nf.get("count", 0) > 0:
            examples = ", ".join(d.get("invoice_id", "?") for d in late_nf.get("detail", [])[:3])
            out.append(
                f"- {late_nf['count']} échéance(s) en retard non signalée(s) (ex: {examples})."
            )

        for overrun in reconciliation.get("budget_overrun_attribution") or []:
            top = ", ".join(
                f"{inv.get('invoice_number') or inv.get('invoice_id', '?')} "
                f"({(inv.get('amount_ht') or 0):.3f} TND)"
                for inv in overrun.get("top_invoices", [])[:3]
            )
            out.append(
                f"- Dépassement budgétaire ligne '{overrun['catalog_id']}' : "
                f"réalisé {overrun['actual_ytd']:.3f} TND vs budget {overrun['budget_ytd']:.3f} TND. "
                f"Principales factures contributrices : {top}."
            )

        jm = reconciliation.get("journal_mismatch") or {}
        if jm.get("missing_entry_count", 0) > 0:
            examples = ", ".join(d.get("invoice_id", "?") for d in jm.get("missing_entry", [])[:3])
            out.append(
                f"- {jm['missing_entry_count']} facture(s) journalisée(s) sans écriture "
                f"comptable (ex: {examples})."
            )
        if jm.get("duplicate_entry_count", 0) > 0:
            examples = ", ".join(d.get("invoice_id", "?") for d in jm.get("duplicate_entry", [])[:3])
            out.append(
                f"- {jm['duplicate_entry_count']} facture(s) avec écritures en double (ex: {examples})."
            )
        if jm.get("amount_mismatch_count", 0) > 0:
            examples = ", ".join(
                f"{d.get('invoice_id', '?')} (facture {(d.get('invoice_amount_ttc') or 0):.3f} TND / "
                f"journal {(d.get('journal_amount') or 0):.3f} TND)"
                for d in jm.get("amount_mismatch", [])[:3]
            )
            out.append(
                f"- {jm['amount_mismatch_count']} facture(s) avec montant incohérent "
                f"vs écriture (ex: {examples})."
            )

        return out

    def _build_narrative_prompt(
        self, metrics: dict, trend: dict, alerts: list[dict], reconciliation: dict,
        similar_incidents: list[dict],
    ) -> str:
        lines = [
            "Voici les métriques d'audit de la période (ne les recalcule pas, "
            "utilise-les telles quelles) :"
        ]
        for domain, values in metrics.items():
            if values:
                lines.append(f"- {domain}: {values}")

        if trend:
            lines.append("\nTendance vs la période précédente de même granularité :")
            for domain, deltas in trend.items():
                lines.append(f"- {domain}: {deltas}")

        if alerts:
            lines.append("\nAlertes détectées :")
            for a in alerts:
                lines.append(f"- [{a['severity']}] {a['message']}")
        else:
            lines.append("\nAucune alerte détectée sur cette période.")

        recon_lines = self._format_reconciliation_detail(reconciliation)
        if recon_lines:
            lines.append("\nRapprochement transversal détaillé (échantillon, ne pas recalculer) :")
            lines.extend(recon_lines)

        if similar_incidents:
            lines.append("\nIncidents similaires trouvés dans l'historique :")
            for inc in similar_incidents[:5]:
                lines.append(f"- ({inc.get('date', '?')}) {inc.get('excerpt', '')}")

        lines.append(
            "\nRédige une synthèse de 5 phrases maximum en français, factuelle et directe, "
            "à destination de la direction. N'invente et ne recalcule aucun chiffre — "
            "utilise exactement les valeurs données ci-dessus."
        )
        return "\n".join(lines)
