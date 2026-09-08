"""Unit tests — api/routers/ai.py, the endpoints not already covered
elsewhere: get_health_summary, scan_roadmap_risks, scan_item_risk,
suggest_mitigation, accounting_check, get_ai_activity, plus the missing
error-path for retrain_model.

correct_classification is already covered by test_classification_feedback_mongo.py
and retrain_model's happy path by test_ml_retrain_wiring.py — not duplicated
here. Same convention as those two files and test_audit_reports_router.py:
endpoint functions called directly (role checks are Depends()-injected and
exercised via integration tests instead), agents/service_bridge monkeypatched
at their call sites.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from api.routers.ai import (
    MitigationRequest,
    accounting_check,
    get_ai_activity,
    get_health_summary,
    retrain_model,
    scan_item_risk,
    scan_roadmap_risks,
    suggest_mitigation,
)
from fastapi import HTTPException


def _fake_agent_result(success: bool, output: dict | None = None, error: str | None = None,
                        duration_ms: float = 12.5):
    return MagicMock(success=success, output=output or {}, error=error, duration_ms=duration_ms)


# ── get_health_summary ───────────────────────────────────────────────────────

class TestGetHealthSummary:
    def test_success_spreads_output_and_adds_metadata(self, monkeypatch):
        output = {"summary": "Satisfaisant.", "status_label": "Satisfaisant"}
        result = _fake_agent_result(True, output)
        monkeypatch.setattr(
            "src.ai_agents.insight_agent.InsightAgent.run", lambda self, ctx: result,
        )
        monkeypatch.setattr(
            "src.ai_agents.ollama_client.OllamaClient.get",
            lambda: MagicMock(is_available=lambda: True),
        )

        out = get_health_summary()

        assert out["summary"] == "Satisfaisant."
        assert out["status_label"] == "Satisfaisant"
        assert out["ollama_available"] is True
        assert "generated_at" in out

    def test_agent_failure_raises_500(self, monkeypatch):
        result = _fake_agent_result(False, error="mongo indisponible")
        monkeypatch.setattr(
            "src.ai_agents.insight_agent.InsightAgent.run", lambda self, ctx: result,
        )

        with pytest.raises(HTTPException) as exc_info:
            get_health_summary()
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "mongo indisponible"

    def test_agent_failure_without_error_uses_default_message(self, monkeypatch):
        result = _fake_agent_result(False, error=None)
        monkeypatch.setattr(
            "src.ai_agents.insight_agent.InsightAgent.run", lambda self, ctx: result,
        )

        with pytest.raises(HTTPException) as exc_info:
            get_health_summary()
        assert exc_info.value.detail == "Échec de la génération du résumé."


# ── scan_roadmap_risks / scan_item_risk ──────────────────────────────────────

class TestScanRoadmapRisks:
    def test_success_returns_agent_output(self, monkeypatch):
        output = {"items_scanned": 3, "risks_created": 1, "items_skipped": 2}
        result = _fake_agent_result(True, output)
        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", lambda self, ctx: result)

        out = scan_roadmap_risks()

        assert out == {"items_scanned": 3, "risks_created": 1, "items_skipped": 2}

    def test_agent_failure_raises_500(self, monkeypatch):
        result = _fake_agent_result(False, error="roadmap indisponible")
        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", lambda self, ctx: result)

        with pytest.raises(HTTPException) as exc_info:
            scan_roadmap_risks()
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "roadmap indisponible"


class TestScanItemRisk:
    def test_passes_item_id_through_to_agent_context(self, monkeypatch):
        captured = {}

        def fake_run(self, ctx):
            captured.update(ctx)
            return _fake_agent_result(True, {"risks_created": 1})

        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", fake_run)

        out = scan_item_risk("item-42")

        assert captured == {"task": "scan_roadmap", "item_id": "item-42"}
        assert out == {"risks_created": 1}

    def test_agent_failure_raises_500(self, monkeypatch):
        result = _fake_agent_result(False, error="jalon introuvable")
        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", lambda self, ctx: result)

        with pytest.raises(HTTPException) as exc_info:
            scan_item_risk("item-42")
        assert exc_info.value.status_code == 500


# ── suggest_mitigation ────────────────────────────────────────────────────────

class TestSuggestMitigation:
    def _body(self) -> MitigationRequest:
        return MitigationRequest(
            titre="Retard livraison serveur", type_risque="DELAI",
            probabilite="ELEVEE", impact="ELEVE",
        )

    def test_success_returns_suggestion_and_duration(self, monkeypatch):
        output = {"suggestion": "1. Analyser\n2. Escalader\n3. Réviser"}
        result = _fake_agent_result(True, output, duration_ms=42.0)
        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", lambda self, ctx: result)

        out = suggest_mitigation(self._body())

        assert out["suggestion"] == "1. Analyser\n2. Escalader\n3. Réviser"
        assert out["duration_ms"] == 42.0

    def test_agent_failure_raises_500(self, monkeypatch):
        result = _fake_agent_result(False, error="ollama boom")
        monkeypatch.setattr("src.ai_agents.risk_agent.RiskAgent.run", lambda self, ctx: result)

        with pytest.raises(HTTPException) as exc_info:
            suggest_mitigation(self._body())
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "ollama boom"


# ── accounting_check ──────────────────────────────────────────────────────────

class TestAccountingCheck:
    def test_delegates_to_agent_and_closes_components(self, monkeypatch):
        fake_components = MagicMock()
        monkeypatch.setattr("api.routers.ai.get_components", lambda: fake_components)

        fake_agent = MagicMock()
        fake_agent.check_consistency.return_value = {
            "consistency_score": 1.0, "total_checked": 10, "issues": [],
        }
        monkeypatch.setattr(
            "src.ai_agents.accounting_agent.AccountingAgent",
            lambda entry_generator, cost_catalog=None: fake_agent,
        )

        result = accounting_check()

        assert result == {"consistency_score": 1.0, "total_checked": 10, "issues": []}
        fake_components.close.assert_called_once()

    def test_components_closed_even_on_exception(self, monkeypatch):
        fake_components = MagicMock()
        monkeypatch.setattr("api.routers.ai.get_components", lambda: fake_components)
        monkeypatch.setattr(
            "src.ai_agents.accounting_agent.AccountingAgent",
            lambda entry_generator, cost_catalog=None: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        with pytest.raises(RuntimeError):
            accounting_check()
        fake_components.close.assert_called_once()


# ── retrain_model — missing error-path (happy path already covered by
#    test_ml_retrain_wiring.py) ────────────────────────────────────────────────

class TestRetrainModelErrorPath:
    def test_retrain_exception_raises_500_and_closes_components(self, monkeypatch):
        fake_components = MagicMock()
        fake_components.coder.ml_classifier.retrain_from_repo.side_effect = (
            RuntimeError("modèle corrompu")
        )
        monkeypatch.setattr("api.routers.ai.get_components", lambda: fake_components)
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository", lambda: MagicMock(),
        )

        with pytest.raises(HTTPException) as exc_info:
            retrain_model()
        assert exc_info.value.status_code == 500
        fake_components.close.assert_called_once()


# ── get_ai_activity ────────────────────────────────────────────────────────────

class TestGetAiActivity:
    def test_returns_ollama_stats_and_availability(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.get_stats.return_value = {"total_calls": 42, "success_rate": 0.95}
        fake_client.is_available.return_value = True
        monkeypatch.setattr("src.ai_agents.ollama_client.OllamaClient.get", lambda: fake_client)

        out = get_ai_activity()

        assert out["ollama_stats"] == {"total_calls": 42, "success_rate": 0.95}
        assert out["ollama_available"] is True
        assert "model" in out
