"""Unit tests — AuditAgent : métriques par domaine (Lot 1), rapprochement
transversal facture ↔ échéancier ↔ budget ↔ journal (Lot 2), enrichissement
RAG + synthèse LLM (Lot 3), tendance vs snapshot précédent, alertes
déterministes.

Toutes les dépendances Mongo sont monkeypatchées au niveau du module
src.storage.sync_mongo_repository — AuditAgent les importe localement à
chaque appel, donc patcher l'attribut du module suffit (même pattern que
test_orchestrator_audit_trail.py pour les agents du pipeline). ChromaDB et
Ollama sont mockés à la frontière (PCEVectorStore.get()/OllamaClient.get()),
comme test_ai_agents.py le fait déjà pour AnomalyAgent.
"""
from __future__ import annotations

from unittest.mock import MagicMock

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


@pytest.fixture(autouse=True)
def _default_rag_and_llm(monkeypatch):
    """Par défaut : ChromaDB indisponible (RAG désactivé, comme le reste du
    projet en dégradé) et Ollama disponible avec une synthèse bidon — le
    "happy path" reste status=OK. Les tests Lot 3 dédiés surchargent l'un ou
    l'autre explicitement."""
    from src.ai_agents.ollama_client import OllamaClient
    from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

    fake_store = MagicMock()
    fake_store.available = False
    monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

    fake_ollama = MagicMock()
    fake_ollama.is_available.return_value = True
    fake_ollama.complete.return_value = "Synthèse de test."
    monkeypatch.setattr(OllamaClient, "get", staticmethod(lambda: fake_ollama))


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


class TestNarrativeGeneration:
    def test_narrative_persisted_when_ollama_available(self, monkeypatch):
        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        result = AuditAgent().run({"granularity": "DAILY"})

        assert saved["snapshot"]["narrative_summary"] == "Synthèse de test."
        assert result.output["degraded"] is False
        assert saved["snapshot"]["status"] == "OK"

    def test_narrative_none_and_degraded_when_ollama_unavailable(self, monkeypatch):
        from src.ai_agents.ollama_client import OllamaClient

        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        fake_ollama = MagicMock()
        fake_ollama.is_available.return_value = False
        monkeypatch.setattr(OllamaClient, "get", staticmethod(lambda: fake_ollama))

        result = AuditAgent().run({"granularity": "DAILY"})

        assert saved["snapshot"]["narrative_summary"] is None
        assert result.output["degraded"] is True
        assert saved["snapshot"]["status"] == "DEGRADED"

    def test_narrative_none_and_degraded_when_llm_returns_empty(self, monkeypatch):
        from src.ai_agents.ollama_client import OllamaClient

        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        fake_ollama = MagicMock()
        fake_ollama.is_available.return_value = True
        fake_ollama.complete.return_value = None
        monkeypatch.setattr(OllamaClient, "get", staticmethod(lambda: fake_ollama))

        result = AuditAgent().run({"granularity": "DAILY"})

        assert saved["snapshot"]["narrative_summary"] is None
        assert result.output["degraded"] is True

    def test_prompt_never_asks_llm_to_compute_only_to_synthesize(self, monkeypatch):
        """Vérifie que le prompt contient bien les métriques déjà calculées et
        l'instruction explicite de ne pas recalculer — pas une preuve totale
        que le LLM obéira, mais une garantie que le prompt le lui interdit."""
        from src.ai_agents.ollama_client import OllamaClient

        _patch_kpis(monkeypatch, invoices={"pending_count": 7, "rejection_rate": 12.0})
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        fake_ollama = MagicMock()
        fake_ollama.is_available.return_value = True
        fake_ollama.complete.return_value = "Synthèse."
        monkeypatch.setattr(OllamaClient, "get", staticmethod(lambda: fake_ollama))

        AuditAgent().run({"granularity": "DAILY"})

        prompt = fake_ollama.complete.call_args.kwargs["prompt"]
        assert "pending_count" in prompt or "7" in prompt
        assert "ne recalcule aucun chiffre" in prompt.lower() or "n'invente" in prompt.lower()


class TestRagIndexingAndRetrieval:
    def test_no_indexing_on_first_run_without_previous_snapshot(self, monkeypatch):
        """Pas de previous snapshot → rien à indexer (voir docstring
        _index_new_incidents : l'historique se peuple via le script de
        backfill, jamais dans ce job périodique)."""
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        _patch_save_snapshot(monkeypatch)

        fake_store = MagicMock()
        fake_store.available = True
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        AuditAgent().run({"granularity": "DAILY"})

        fake_store.index_incident.assert_not_called()

    def test_indexes_risques_and_flags_created_since_previous_snapshot(self, monkeypatch):
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "get_latest_snapshot_sync",
            lambda granularity: {"granularity": granularity, "metrics": {}, "generated_at": "T0"},
        )
        monkeypatch.setattr(
            sync_mongo_repository, "risques_created_since_sync",
            lambda since: [{"_id": "r1", "titre": "Retard", "description": "desc",
                             "niveau_criticite": "ELEVE", "created_at": "T1"}],
        )
        monkeypatch.setattr(
            sync_mongo_repository, "invoice_flags_created_since_sync",
            lambda since: [{"flag_id": "f1", "invoice_id": "inv-1", "flag_type": "SUSPICIOUS_AMOUNT",
                             "message": "montant élevé", "severity": "WARNING", "created_at": "T2"}],
        )

        fake_store = MagicMock()
        fake_store.available = True
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        AuditAgent().run({"granularity": "DAILY"})

        assert fake_store.index_incident.call_count == 2
        calls = {c.args[0]: c for c in fake_store.index_incident.call_args_list}
        assert "risque" in calls
        assert "anomaly" in calls
        assert calls["risque"].args[1] == "r1"
        assert calls["anomaly"].args[1] == "f1"

    def test_no_indexing_when_chromadb_unavailable(self, monkeypatch):
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch)
        _patch_save_snapshot(monkeypatch)
        monkeypatch.setattr(
            sync_mongo_repository, "get_latest_snapshot_sync",
            lambda granularity: {"granularity": granularity, "metrics": {}, "generated_at": "T0"},
        )

        fake_store = MagicMock()
        fake_store.available = False
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        AuditAgent().run({"granularity": "DAILY"})

        fake_store.index_incident.assert_not_called()

    def test_retrieves_similar_incidents_per_alert_above_threshold(self, monkeypatch):
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch, invoices={"pending_count": 10, "rejection_rate": 20.0})
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        fake_store = MagicMock()
        fake_store.available = True
        fake_store.search_similar_incidents.return_value = [
            {"source_type": "anomaly", "source_id": "f9", "date": "2026-06-01",
             "similarity": 0.88, "excerpt": "Taux de rejet déjà élevé le mois dernier."},
        ]
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        AuditAgent().run({"granularity": "DAILY"})

        similar = saved["snapshot"]["similar_incidents"]
        assert len(similar) == 1
        assert similar[0]["related_alert_code"] == "HIGH_REJECTION_RATE"
        assert similar[0]["source_id"] == "f9"

    def test_no_retrieval_when_no_alerts(self, monkeypatch):
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch)
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        fake_store = MagicMock()
        fake_store.available = True
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        AuditAgent().run({"granularity": "DAILY"})

        fake_store.search_similar_incidents.assert_not_called()
        assert saved["snapshot"]["similar_incidents"] == []

    def test_rag_never_suppresses_or_adds_alerts(self, monkeypatch):
        """Le RAG est un outil de récupération, pas une boucle de décision —
        peu importe ce que search_similar_incidents renvoie, les alertes
        déterministes restent inchangées (voir docstring de module)."""
        from src.ai_agents.rag.pce_vectorstore import PCEVectorStore

        _patch_kpis(monkeypatch, invoices={"pending_count": 10, "rejection_rate": 20.0})
        _patch_no_previous_snapshot(monkeypatch)
        saved = _patch_save_snapshot(monkeypatch)

        fake_store = MagicMock()
        fake_store.available = True
        fake_store.search_similar_incidents.side_effect = RuntimeError("chromadb query failed")
        monkeypatch.setattr(PCEVectorStore, "get", staticmethod(lambda: fake_store))

        result = AuditAgent().run({"granularity": "DAILY"})

        alert_codes = [a["code"] for a in result.output["alerts"]]
        assert alert_codes == ["HIGH_REJECTION_RATE"]
        assert saved["snapshot"]["similar_incidents"] == []


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
