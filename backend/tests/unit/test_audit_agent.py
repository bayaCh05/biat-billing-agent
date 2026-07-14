"""Unit tests — AuditAgent : métriques par domaine (Lot 1), rapprochement
transversal facture ↔ échéancier ↔ budget ↔ journal (Lot 2), tendance vs
snapshot précédent, alertes déterministes. Aucun RAG, aucune synthèse LLM à
ce stade (Lot 3) — narrative_summary/similar_incidents ne sont pas exercés ici.

Toutes les dépendances Mongo sont monkeypatchées au niveau du module
src.storage.sync_mongo_repository — AuditAgent les importe localement à
chaque appel, donc patcher l'attribut du module suffit (même pattern que
test_orchestrator_audit_trail.py pour les agents du pipeline).
"""
from __future__ import annotations

import pytest

from src.ai_agents.audit_agent import AuditAgent
from src.storage import sync_mongo_repository


@pytest.fixture(autouse=True)
def _default_reconciliation(monkeypatch):
    """Rapprochement transversal (Lot 2) sans aucune anomalie par défaut —
    les tests qui veulent en exercer une la surchargent explicitement."""
    monkeypatch.setattr(
        sync_mongo_repository, "invoices_overdue_without_installment_plan_sync",
        lambda: {"count": 0, "detail": []},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "late_installments_invoice_not_flagged_sync",
        lambda: {"count": 0, "detail": []},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "budget_overrun_top_invoices_sync",
        lambda top_n=3: [],
    )
    monkeypatch.setattr(
        sync_mongo_repository, "invoices_journal_mismatch_sync",
        lambda: {
            "missing_entry_count": 0, "missing_entry": [],
            "duplicate_entry_count": 0, "duplicate_entry": [],
            "amount_mismatch_count": 0, "amount_mismatch": [],
        },
    )


def _patch_kpis(monkeypatch, *, invoices=None, journal=None, budget=None,
                 echeancier=None, risks=None, roadmap=None):
    monkeypatch.setattr(
        sync_mongo_repository, "invoice_pending_rejected_30d_sync",
        lambda: invoices or {"pending_count": 0, "rejection_rate": 0.0},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "journal_consistency_check_sync",
        lambda: journal or {"consistency_score": 1.0, "total_checked": 1, "issues": []},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "budget_variance_kpis_sync",
        lambda: budget or {"n_total": 0, "n_over_budget": 0, "variance_pct": 0.0},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "echeancier_kpis_sync",
        lambda: echeancier or {"n_total": 0, "n_late": 0, "n_pending": 0, "total_penalty_amount": 0.0},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "risks_kpis_sync",
        lambda: risks or {"n_critique": 0, "n_overdue_mitigation": 0},
    )
    monkeypatch.setattr(
        sync_mongo_repository, "roadmap_kpis_sync",
        lambda: roadmap or {"n_overdue_milestones": 0, "pct_done": 100.0},
    )


def _patch_no_previous_snapshot(monkeypatch):
    monkeypatch.setattr(sync_mongo_repository, "get_latest_snapshot_sync", lambda granularity: None)


def _patch_save_snapshot(monkeypatch):
    saved = {}

    def _fake_save(snapshot: dict) -> str:
        saved["snapshot"] = snapshot
        return "fake-snapshot-id"

    monkeypatch.setattr(sync_mongo_repository, "save_audit_snapshot_sync", _fake_save)
    return saved


class TestRunHappyPath:
    def test_returns_success_with_snapshot_id(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        result = AuditAgent().run({"granularity": "DAILY"})

        assert result.success is True
        assert result.output["snapshot_id"] == "fake-snapshot-id"
        assert result.output["granularity"] == "DAILY"
        assert result.output["degraded"] is False
        assert saved["snapshot"]["status"] == "OK"

    def test_defaults_to_daily_when_granularity_missing(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        result = AuditAgent().run({})

        assert result.output["granularity"] == "DAILY"
        assert saved["snapshot"]["granularity"] == "DAILY"

    def test_invalid_granularity_falls_back_to_daily(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        result = AuditAgent().run({"granularity": "YEARLY"})

        assert result.output["granularity"] == "DAILY"

    def test_no_alerts_when_all_metrics_within_thresholds(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        result = AuditAgent().run({"granularity": "DAILY"})

        assert result.output["alerts"] == []


class TestDegradedMode:
    def test_domain_failure_sets_degraded_true_but_still_succeeds(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        def _broken():
            raise ConnectionError("mongo unreachable")

        monkeypatch.setattr(sync_mongo_repository, "roadmap_kpis_sync", _broken)

        result = AuditAgent().run({"granularity": "DAILY"})

        assert result.success is True
        assert result.output["degraded"] is True
        assert saved["snapshot"]["status"] == "DEGRADED"
        assert saved["snapshot"]["metrics"]["roadmap"] is None
        # other domains still collected despite the roadmap failure
        assert saved["snapshot"]["metrics"]["invoices"] is not None


class TestAlerts:
    def test_high_rejection_rate_triggers_warning(self, monkeypatch):
        _patch_kpis(monkeypatch, invoices={"pending_count": 10, "rejection_rate": 20.0})
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "HIGH_REJECTION_RATE" and a["severity"] == "WARNING" for a in alerts)

    def test_journal_inconsistency_triggers_critical(self, monkeypatch):
        _patch_kpis(monkeypatch, journal={
            "consistency_score": 0.90, "total_checked": 1,
            "issues": [{"type": "UNBALANCED_ENTRIES", "count": 1}],
        })
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "JOURNAL_INCONSISTENCY" and a["severity"] == "CRITICAL" for a in alerts)

    def test_budget_variance_triggers_warning(self, monkeypatch):
        _patch_kpis(monkeypatch, budget={"n_total": 5, "n_over_budget": 2, "variance_pct": 15.0})
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "BUDGET_VARIANCE" for a in alerts)

    def test_late_installments_trigger_warning(self, monkeypatch):
        _patch_kpis(monkeypatch, echeancier={
            "n_total": 10, "n_late": 3, "n_pending": 2, "total_penalty_amount": 45.5,
        })
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "LATE_INSTALLMENTS" for a in alerts)

    def test_critical_risks_trigger_critical_alert(self, monkeypatch):
        _patch_kpis(monkeypatch, risks={"n_critique": 2, "n_overdue_mitigation": 1})
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "CRITICAL_RISKS_ACTIVE" and a["severity"] == "CRITICAL" for a in alerts)

    def test_overdue_milestones_trigger_warning(self, monkeypatch):
        _patch_kpis(monkeypatch, roadmap={"n_overdue_milestones": 4, "pct_done": 50.0})
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "OVERDUE_MILESTONES" for a in alerts)


class TestTrend:
    def test_trend_computed_against_previous_same_granularity_snapshot(self, monkeypatch):
        _patch_kpis(monkeypatch, invoices={"pending_count": 8, "rejection_rate": 5.0})
        monkeypatch.setattr(
            sync_mongo_repository, "get_latest_snapshot_sync",
            lambda granularity: {
                "granularity": granularity,
                "metrics": {"invoices": {"pending_count": 3, "rejection_rate": 2.0}},
            },
        )
        saved = _patch_save_snapshot(monkeypatch)

        AuditAgent().run({"granularity": "DAILY"})

        trend = saved["snapshot"]["trend"]
        assert trend["invoices"]["pending_count"] == 5
        assert trend["invoices"]["rejection_rate"] == 3.0

    def test_trend_empty_when_no_previous_snapshot(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        AuditAgent().run({"granularity": "DAILY"})

        assert saved["snapshot"]["trend"] == {}

    def test_trend_skips_domain_that_failed_this_run(self, monkeypatch):
        _patch_kpis(monkeypatch)
        monkeypatch.setattr(sync_mongo_repository, "roadmap_kpis_sync", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(
            sync_mongo_repository, "get_latest_snapshot_sync",
            lambda granularity: {
                "granularity": granularity,
                "metrics": {"roadmap": {"n_overdue_milestones": 1, "pct_done": 40.0}},
            },
        )
        saved = _patch_save_snapshot(monkeypatch)

        AuditAgent().run({"granularity": "DAILY"})

        assert "roadmap" not in saved["snapshot"]["trend"]


class TestReconciliation:
    def test_reconciliation_persisted_in_snapshot(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        AuditAgent().run({"granularity": "DAILY"})

        assert "overdue_without_installment_plan" in saved["snapshot"]["reconciliation"]
        assert "late_installment_not_flagged" in saved["snapshot"]["reconciliation"]
        assert "budget_overrun_attribution" in saved["snapshot"]["reconciliation"]
        assert "journal_mismatch" in saved["snapshot"]["reconciliation"]

    def test_no_reconciliation_alerts_when_all_clear(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert alerts == []

    def test_missing_installment_plan_triggers_warning(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "invoices_overdue_without_installment_plan_sync",
            lambda: {"count": 2, "detail": [{"invoice_id": "inv-1", "invoice_number": "F001"}]},
        )

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "MISSING_INSTALLMENT_PLAN" and a["severity"] == "WARNING" for a in alerts)

    def test_late_installment_not_flagged_triggers_warning(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "late_installments_invoice_not_flagged_sync",
            lambda: {"count": 1, "detail": [{"invoice_id": "inv-2"}]},
        )

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "LATE_INSTALLMENT_NOT_FLAGGED" for a in alerts)

    def test_journaled_without_entry_triggers_critical(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "invoices_journal_mismatch_sync",
            lambda: {
                "missing_entry_count": 1, "missing_entry": [{"invoice_id": "inv-3"}],
                "duplicate_entry_count": 0, "duplicate_entry": [],
                "amount_mismatch_count": 0, "amount_mismatch": [],
            },
        )

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "JOURNALED_WITHOUT_ENTRY" and a["severity"] == "CRITICAL" for a in alerts)

    def test_duplicate_journal_entry_triggers_critical(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "invoices_journal_mismatch_sync",
            lambda: {
                "missing_entry_count": 0, "missing_entry": [],
                "duplicate_entry_count": 1, "duplicate_entry": [{"invoice_id": "inv-4", "count": 2}],
                "amount_mismatch_count": 0, "amount_mismatch": [],
            },
        )

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "DUPLICATE_JOURNAL_ENTRY" and a["severity"] == "CRITICAL" for a in alerts)

    def test_amount_mismatch_journal_triggers_critical(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "invoices_journal_mismatch_sync",
            lambda: {
                "missing_entry_count": 0, "missing_entry": [],
                "duplicate_entry_count": 0, "duplicate_entry": [],
                "amount_mismatch_count": 1,
                "amount_mismatch": [{"invoice_id": "inv-5", "invoice_amount_ttc": 100.0, "journal_amount": 90.0}],
            },
        )

        alerts = AuditAgent().run({"granularity": "DAILY"}).output["alerts"]

        assert any(a["code"] == "AMOUNT_MISMATCH_JOURNAL" and a["severity"] == "CRITICAL" for a in alerts)

    def test_budget_overrun_attribution_stored_but_no_dedicated_alert(self, monkeypatch):
        """budget_overrun_attribution enrichit reconciliation avec le détail
        par facture, mais l'alerte de dépassement budgétaire reste portée par
        BUDGET_VARIANCE (Lot 1) — pas de doublon d'alerte pour le même fait."""
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "budget_overrun_top_invoices_sync",
            lambda top_n=3: [{
                "catalog_id": "licences_ms365", "budget_ytd": 1000.0, "actual_ytd": 1500.0,
                "top_invoices": [{"invoice_id": "inv-6", "invoice_number": "F010", "amount_ht": 800.0}],
            }],
        )

        result = AuditAgent().run({"granularity": "DAILY"})

        assert saved["snapshot"]["reconciliation"]["budget_overrun_attribution"][0]["catalog_id"] == "licences_ms365"
        assert not any(a["code"] == "BUDGET_OVERRUN_ATTRIBUTED" for a in result.output["alerts"])

    def test_reconciliation_failure_sets_degraded_true(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "invoices_journal_mismatch_sync",
            lambda: (_ for _ in ()).throw(ConnectionError("mongo unreachable")),
        )

        result = AuditAgent().run({"granularity": "DAILY"})

        assert result.output["degraded"] is True
        assert saved["snapshot"]["status"] == "DEGRADED"
        assert saved["snapshot"]["reconciliation"]["journal_mismatch"] is None
        # other reconciliation checks still ran despite the journal_mismatch failure
        assert saved["snapshot"]["reconciliation"]["overdue_without_installment_plan"] is not None


class TestAgentNeverCallsOtherAgents:
    def test_never_imports_another_agent_or_the_orchestrator(self):
        """Checks actual import statements (not prose/docstrings) — AuditAgent's
        module docstring legitimately names the other agents to explain why it
        must never call them, which would false-positive on a plain substring check."""
        import ast
        import inspect

        import src.ai_agents.audit_agent as module
        tree = ast.parse(inspect.getsource(module))

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_modules = {
            "src.ai_agents.extraction_agent",
            "src.ai_agents.classification_agent",
            "src.ai_agents.anomaly_agent",
            "src.ai_agents.accounting_agent",
            "src.ai_agents.risk_agent",
            "src.ai_agents.insight_agent",
            "src.ai_agents.invoice_processing_orchestrator",
        }
        assert not (imported_modules & forbidden_modules), (
            f"AuditAgent imports another agent module: {imported_modules & forbidden_modules} — "
            "it must only read what other agents already wrote to Mongo."
        )
