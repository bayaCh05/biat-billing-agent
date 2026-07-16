"""Unit tests for src/ai_agents/* — all Ollama/network calls mocked."""
from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_ollama(available: bool = True, response: str | None = None):
    mock = MagicMock()
    mock.is_available.return_value = available
    mock.complete.return_value = response
    return mock


def _reset_ollama_singleton():
    import src.ai_agents.ollama_client as mod
    mod.OllamaClient._instance = None


# ── OllamaClient ─────────────────────────────────────────────────────────────

class TestOllamaClient:
    def setup_method(self):
        _reset_ollama_singleton()

    def test_complete_success(self):
        import requests
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"message": {"content": "bonjour"}}
            mock_post.return_value.raise_for_status.return_value = None
            result = client.complete("test")
        assert result == "bonjour"

    def test_complete_returns_none_on_timeout(self):
        import requests
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.post", side_effect=requests.exceptions.Timeout()):
            result = client.complete("test")
        assert result is None

    def test_complete_returns_none_on_generic_error(self):
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.post", side_effect=RuntimeError("boom")):
            result = client.complete("test")
        assert result is None

    def test_complete_increments_call_count(self):
        import requests
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.post") as mock_post:
            mock_post.return_value.json.return_value = {"message": {"content": "ok"}}
            mock_post.return_value.raise_for_status.return_value = None
            client.complete("first")
            client.complete("second")
        assert client._stats["calls"] == 2
        assert client._stats["success"] == 2

    def test_is_available_true(self):
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            assert client.is_available() is True

    def test_is_available_false_on_error(self):
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        with patch("requests.get", side_effect=RuntimeError("no server")):
            assert client.is_available() is False

    def test_is_available_cached_within_30s(self):
        from src.ai_agents.ollama_client import OllamaClient
        client = OllamaClient()
        client._available = True
        client._available_checked_at = time.monotonic()
        with patch("requests.get", side_effect=Exception("should not be called")):
            assert client.is_available() is True

    def test_get_stats_zero_calls(self):
        from src.ai_agents.ollama_client import OllamaClient
        stats = OllamaClient().get_stats()
        assert stats["total_calls"] == 0
        assert stats["success_rate"] == 1.0
        assert stats["avg_duration_ms"] == 0

    def test_get_returns_same_instance(self):
        from src.ai_agents.ollama_client import OllamaClient
        a = OllamaClient.get()
        b = OllamaClient.get()
        assert a is b


# ── BaseAgent helpers ─────────────────────────────────────────────────────────

@pytest.fixture
def base_agent():
    """Return a BaseAgent instance with OllamaClient mocked."""
    _reset_ollama_singleton()
    with patch("src.ai_agents.base_agent.OllamaClient.get", return_value=_mock_ollama()):
        from src.ai_agents.risk_agent import RiskAgent  # concrete subclass
        yield RiskAgent()


class TestBaseAgentHelpers:
    def test_parse_json_plain(self, base_agent):
        result = base_agent._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_with_markdown_fence(self, base_agent):
        result = base_agent._parse_json_response("```json\n{\"k\": 1}\n```")
        assert result == {"k": 1}

    def test_parse_json_extracts_from_surrounding_text(self, base_agent):
        result = base_agent._parse_json_response('prefix {"key": "val"} suffix')
        assert result == {"key": "val"}

    def test_parse_json_returns_none_on_invalid(self, base_agent):
        assert base_agent._parse_json_response("not json") is None

    def test_parse_json_returns_none_on_empty(self, base_agent):
        assert base_agent._parse_json_response("") is None

    def test_parse_json_returns_none_on_none(self, base_agent):
        assert base_agent._parse_json_response(None) is None


# ── RiskAgent ─────────────────────────────────────────────────────────────────

@pytest.fixture
def risk_agent():
    _reset_ollama_singleton()
    with patch("src.ai_agents.base_agent.OllamaClient.get", return_value=_mock_ollama()):
        from src.ai_agents.risk_agent import RiskAgent
        yield RiskAgent()


class TestRiskAgentMitigation:
    def test_ollama_unavailable_returns_fallback(self, risk_agent):
        with patch("src.ai_agents.risk_agent.OllamaClient.get", return_value=_mock_ollama(available=False)):
            result = risk_agent.run({
                "task": "draft_mitigation",
                "titre": "Retard livraison serveur",
                "type_risque": "DELAI",
                "probabilite": "ELEVEE",
                "impact": "ELEVE",
            })
        assert result.success is True
        suggestion = result.output["suggestion"]
        assert "1." in suggestion

    def test_ollama_available_returns_llm_text(self, risk_agent):
        llm_response = "1. Analyser\n2. Escalader\n3. Réviser le planning"
        with patch("src.ai_agents.risk_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response=llm_response)):
            result = risk_agent.run({
                "task": "draft_mitigation",
                "titre": "Risque budget",
                "type_risque": "BUDGET",
                "probabilite": "MOYENNE",
                "impact": "MOYEN",
            })
        assert result.success is True
        assert result.output["suggestion"] == llm_response

    def test_ollama_returns_none_falls_back(self, risk_agent):
        with patch("src.ai_agents.risk_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response=None)):
            result = risk_agent.run({
                "task": "draft_mitigation",
                "titre": "Risque test",
                "type_risque": "AUTRE",
                "probabilite": "FAIBLE",
                "impact": "FAIBLE",
            })
        assert result.success is True
        assert "1." in result.output["suggestion"]

    def test_result_has_duration_ms(self, risk_agent):
        with patch("src.ai_agents.risk_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            result = risk_agent.run({
                "task": "draft_mitigation",
                "titre": "Test",
                "type_risque": "AUTRE",
                "probabilite": "FAIBLE",
                "impact": "FAIBLE",
            })
        assert result.duration_ms >= 0


def _overdue_item(projet_id: str = "proj-1"):
    """Shape returned by sync_mongo_repository.overdue_roadmap_items_sync() —
    a raw pymongo dict, not a Beanie document (see risk_agent.py docstring on
    why this path is sync pymongo, never Beanie/Motor)."""
    return {
        "_id": str(uuid4()), "titre": "Jalon test", "description": "Jalon en retard",
        "date_fin": datetime(2020, 1, 1), "projet_id": projet_id,
    }


class TestRiskAgentScanRoadmap:
    def test_no_overdue_items_returns_zero_created(self, risk_agent):
        with (
            patch("src.storage.sync_mongo_repository.overdue_roadmap_items_sync",
                  return_value=[]),
            patch("src.ai_agents.risk_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
        ):
            result = risk_agent.run({"task": "scan_roadmap"})

        assert result.success is True
        assert result.output["risks_created"] == 0
        assert result.output["items_scanned"] == 0

    def test_mongo_error_returns_failure(self, risk_agent):
        with (
            patch("src.storage.sync_mongo_repository.overdue_roadmap_items_sync",
                  side_effect=RuntimeError("Mongo error")),
            patch("src.ai_agents.risk_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
        ):
            result = risk_agent.run({"task": "scan_roadmap"})

        assert result.success is False
        assert result.error is not None

    def test_creates_risk_for_overdue_item_without_existing_ai_risk(self, risk_agent):
        item = _overdue_item()
        with (
            patch("src.storage.sync_mongo_repository.overdue_roadmap_items_sync",
                  return_value=[item]),
            patch("src.storage.sync_mongo_repository.existing_ai_risk_for_item_sync",
                  return_value=False),
            patch("src.storage.sync_mongo_repository.create_risk_sync",
                  return_value="new-risk-id") as mock_create,
            patch("src.storage.sync_mongo_repository.log_ai_audit_event_sync") as mock_audit,
            patch("src.ai_agents.risk_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
        ):
            result = risk_agent.run({"task": "scan_roadmap"})

        assert result.success is True
        assert result.output["items_scanned"] == 1
        assert result.output["risks_created"] == 1
        assert result.output["items_skipped"] == 0
        mock_create.assert_called_once()
        risk_data = mock_create.call_args[0][0]
        assert risk_data["feuille_route_id"] == item["_id"]
        assert risk_data["projet_id"] == "proj-1"
        assert risk_data["created_by"] == "system:ai"
        mock_audit.assert_called_once()

    def test_skips_item_with_existing_ai_risk(self, risk_agent):
        item = _overdue_item()
        with (
            patch("src.storage.sync_mongo_repository.overdue_roadmap_items_sync",
                  return_value=[item]),
            patch("src.storage.sync_mongo_repository.existing_ai_risk_for_item_sync",
                  return_value=True),
            patch("src.storage.sync_mongo_repository.create_risk_sync") as mock_create,
            patch("src.ai_agents.risk_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
        ):
            result = risk_agent.run({"task": "scan_roadmap"})

        assert result.success is True
        assert result.output["risks_created"] == 0
        assert result.output["items_skipped"] == 1
        mock_create.assert_not_called()

    def test_item_id_filter_passed_through_to_query(self, risk_agent):
        item_id = str(uuid4())
        with (
            patch("src.storage.sync_mongo_repository.overdue_roadmap_items_sync",
                  return_value=[]) as mock_query,
            patch("src.ai_agents.risk_agent.OllamaClient.get",
                  return_value=_mock_ollama(available=False)),
        ):
            risk_agent.run({"task": "scan_roadmap", "item_id": item_id})

        mock_query.assert_called_once_with(item_id)


# ── InsightAgent ──────────────────────────────────────────────────────────────

@pytest.fixture
def insight_agent():
    _reset_ollama_singleton()
    with patch("src.ai_agents.base_agent.OllamaClient.get", return_value=_mock_ollama()):
        from src.ai_agents.insight_agent import InsightAgent
        yield InsightAgent()


class TestInsightAgentNLQuery:
    def test_ollama_unavailable_returns_error(self, insight_agent):
        with patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            result = insight_agent.run({"task": "nl_query", "question": "Combien?"})
        assert result.success is False
        assert result.error is not None
        assert "Ollama" in result.error

    def test_ollama_available_delegates_to_nl_engine(self, insight_agent):
        mock_result = {
            "question": "Combien?",
            "sql": "SELECT COUNT(*) FROM invoices",
            "result": [{"nb": 5}],
            "answer": "Il y a 5 factures.",
            "explanation": "Comptage",
        }
        with patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True)):
            with patch("src.query.nl_query_engine.NLQueryEngine.query",
                       return_value=mock_result):
                result = insight_agent.run({"task": "nl_query", "question": "Combien?"})
        assert result.success is True
        assert result.explanation == "Il y a 5 factures."

    def test_engine_exception_returns_failure(self, insight_agent):
        with patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True)):
            with patch("src.query.nl_query_engine.NLQueryEngine.query",
                       side_effect=RuntimeError("engine failure")):
                result = insight_agent.run({"task": "nl_query", "question": "test"})
        assert result.success is False


class TestInsightAgentHealthSummary:
    """_gather_kpis() reads MongoDB (sync_mongo_repository) — mocked here so these
    stay hermetic unit tests, independent of a live Mongo connection."""

    def _patched_kpis(self, insight_agent):
        return patch.object(insight_agent, "_gather_kpis", return_value={})

    def test_ollama_unavailable_returns_degraded_summary(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            result = insight_agent.run({"task": "health_summary"})
        assert result.success is True
        assert "Ollama" in result.output["summary"]

    def test_status_label_satisfaisant(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="Satisfaisant. Tout va bien.")):
            result = insight_agent.run({"task": "health_summary"})
        assert result.output["status_label"] == "Satisfaisant"

    def test_status_label_vigilance(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="Vigilance requise. Budget tendu.")):
            result = insight_agent.run({"task": "health_summary"})
        assert result.output["status_label"] == "Vigilance requise"

    def test_status_label_critique(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="Situation critique. 3 risques.")):
            result = insight_agent.run({"task": "health_summary"})
        assert result.output["status_label"] == "Critique"

    def test_kpis_in_output(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=True, response="Satisfaisant. Tout va bien.")):
            result = insight_agent.run({"task": "health_summary"})
        # When Ollama available, KPIs are grouped under kpis_snapshot
        assert "kpis_snapshot" in result.output
        assert "summary" in result.output

    def test_no_db_still_returns_success(self, insight_agent):
        with self._patched_kpis(insight_agent), \
             patch("src.ai_agents.insight_agent.OllamaClient.get",
                   return_value=_mock_ollama(available=False)):
            result = insight_agent.run({"task": "health_summary"})
        assert result.success is True

    def test_gather_kpis_survives_partial_mongo_failure(self, insight_agent):
        """If one KPI collector raises, the others still populate the dict."""
        with patch("src.storage.sync_mongo_repository.invoice_pending_rejected_30d_sync",
                   side_effect=RuntimeError("mongo down")), \
             patch("src.storage.sync_mongo_repository.roadmap_kpis_sync",
                   return_value={"n_overdue_milestones": 2, "pct_done": 50.0}), \
             patch("src.storage.sync_mongo_repository.risks_kpis_sync",
                   return_value={"n_critique": 1, "n_overdue_mitigation": 0}), \
             patch("src.storage.sync_mongo_repository.budget_variance_kpis_sync",
                   return_value={"n_total": 3, "n_over_budget": 1, "variance_pct": 5.0}):
            kpis = insight_agent._gather_kpis()
        assert kpis["n_overdue_milestones"] == 2
        assert kpis["n_critique"] == 1
        assert kpis["n_total"] == 3
        assert "pending_count" not in kpis


# ── AnomalyAgent ──────────────────────────────────────────────────────────────

def _make_invoice():
    from src.models.invoice import InvoiceRecord
    return InvoiceRecord(file_hash="a" * 64, raw_file_path="/tmp/test.pdf")


def _make_validators(invoice):
    """Each validator simply returns the invoice unchanged."""
    fv = MagicMock()
    fv.validate.return_value = invoice
    cc = MagicMock()
    cc.check.return_value = invoice
    dd = MagicMock()
    dd.detect.return_value = invoice
    ad = MagicMock()
    ad.detect.return_value = invoice
    return fv, cc, dd, ad


@pytest.fixture
def anomaly_agent():
    _reset_ollama_singleton()
    with patch("src.ai_agents.base_agent.OllamaClient.get", return_value=_mock_ollama()):
        from src.ai_agents.anomaly_agent import AnomalyAgent
        inv = _make_invoice()
        fv, cc, dd, ad = _make_validators(inv)
        yield AnomalyAgent(fv, cc, dd, ad), inv, fv, cc, dd, ad


class TestAnomalyAgent:
    def test_run_no_flags_success(self, anomaly_agent):
        agent, invoice, fv, cc, dd, ad = anomaly_agent
        mock_db = MagicMock()
        # Simulate no historical data (< 5 entries) for category check
        mock_db.execute.return_value.fetchall.return_value = []

        with patch("src.ai_agents.rag.pce_vectorstore.PCEVectorStore.get") as mock_store:
            mock_store.return_value.available = False
            result = agent.run({"invoice": invoice, "db": mock_db})

        assert result.success is True
        assert result.output["anomaly_count"] == 0
        assert result.output["requires_human_review"] is False

    def test_run_calls_all_four_validators(self, anomaly_agent):
        agent, invoice, fv, cc, dd, ad = anomaly_agent
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        with patch("src.ai_agents.rag.pce_vectorstore.PCEVectorStore.get") as mock_store:
            mock_store.return_value.available = False
            agent.run({"invoice": invoice, "db": mock_db})

        fv.validate.assert_called_once_with(invoice)
        cc.check.assert_called_once_with(invoice)
        dd.detect.assert_called_once_with(invoice)
        ad.detect.assert_called_once_with(invoice)

    def test_run_validator_exception_returns_failure(self, anomaly_agent):
        agent, invoice, fv, cc, dd, ad = anomaly_agent
        fv.validate.side_effect = RuntimeError("validator crashed")
        mock_db = MagicMock()

        result = agent.run({"invoice": invoice, "db": mock_db})
        assert result.success is False
        assert "validator crashed" in result.error

    def test_category_price_check_skipped_with_no_catalog_id(self, anomaly_agent):
        agent, invoice, *_ = anomaly_agent
        invoice.cost_catalog_id = None
        mock_db = MagicMock()

        with patch("src.ai_agents.rag.pce_vectorstore.PCEVectorStore.get") as mock_store:
            mock_store.return_value.available = False
            result = agent.run({"invoice": invoice, "db": mock_db})

        assert result.success is True
        # DB should not be queried for category check
        mock_db.execute.assert_not_called()

    def test_result_has_flag_types_list(self, anomaly_agent):
        agent, invoice, fv, cc, dd, ad = anomaly_agent
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        with patch("src.ai_agents.rag.pce_vectorstore.PCEVectorStore.get") as mock_store:
            mock_store.return_value.available = False
            result = agent.run({"invoice": invoice, "db": mock_db})

        assert isinstance(result.output["flag_types"], list)


# ── AgentResult model ─────────────────────────────────────────────────────────

class TestAgentResult:
    def test_defaults(self):
        from src.ai_agents.agent_schemas import AgentResult
        r = AgentResult(agent_name="Test", success=True, duration_ms=10.0)
        assert r.output == {}
        assert r.confidence is None
        assert r.explanation is None
        assert r.error is None
        assert r.ollama_calls_made == 0

    def test_failure_result(self):
        from src.ai_agents.agent_schemas import AgentResult
        r = AgentResult(agent_name="Test", success=False, duration_ms=5.0, error="boom")
        assert r.success is False
        assert r.error == "boom"
