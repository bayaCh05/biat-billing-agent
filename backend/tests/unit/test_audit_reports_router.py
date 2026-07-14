"""Unit tests — api/routers/audit_reports.py (Lot 4): list/detail/run.

Same convention as test_classification_feedback_mongo.py: endpoint functions
are called directly (bypassing FastAPI's dependency injection — role checks
are exercised elsewhere via integration tests), with sync_mongo_repository
and AuditAgent monkeypatched at their call sites.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.routers.audit_reports import (
    RunAuditReportRequest, get_audit_report, list_audit_reports, run_audit_report,
)


class TestListAuditReports:
    def test_returns_total_and_summarized_items(self, monkeypatch):
        docs = [{
            "_id": "s1", "granularity": "DAILY",
            "period_start": "2026-07-14", "period_end": "2026-07-14",
            "generated_at": "2026-07-14T02:00:00Z", "status": "OK",
            "alerts": [{"severity": "WARNING"}, {"severity": "CRITICAL"}],
        }]
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.list_audit_snapshots_sync",
            lambda granularity, limit, skip: docs,
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.count_audit_snapshots_sync",
            lambda granularity: 1,
        )

        result = list_audit_reports(granularity="DAILY", limit=20, skip=0)

        assert result["total"] == 1
        assert result["items"][0]["id"] == "s1"
        assert result["items"][0]["alert_count"] == 2
        assert result["items"][0]["critical_count"] == 1

    def test_invalid_granularity_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            list_audit_reports(granularity="YEARLY", limit=20, skip=0)
        assert exc_info.value.status_code == 400

    def test_none_granularity_is_allowed(self, monkeypatch):
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.list_audit_snapshots_sync",
            lambda granularity, limit, skip: [],
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.count_audit_snapshots_sync",
            lambda granularity: 0,
        )

        result = list_audit_reports(granularity=None, limit=20, skip=0)

        assert result == {"total": 0, "items": []}


class TestGetAuditReport:
    def test_returns_full_document_with_id_key(self, monkeypatch):
        doc = {"_id": "s1", "granularity": "DAILY", "metrics": {"invoices": {"pending_count": 3}}}
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.get_audit_snapshot_by_id_sync",
            lambda snapshot_id: doc,
        )

        result = get_audit_report("s1")

        assert result["id"] == "s1"
        assert "_id" not in result
        assert result["metrics"]["invoices"]["pending_count"] == 3

    def test_missing_snapshot_raises_404(self, monkeypatch):
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.get_audit_snapshot_by_id_sync",
            lambda snapshot_id: None,
        )

        with pytest.raises(HTTPException) as exc_info:
            get_audit_report("missing")
        assert exc_info.value.status_code == 404


class TestRunAuditReport:
    def test_triggers_audit_agent_and_returns_output(self, monkeypatch):
        fake_result = MagicMock(success=True, output={"snapshot_id": "s1", "alerts": []})
        monkeypatch.setattr(
            "src.ai_agents.audit_agent.AuditAgent.run", lambda self, context: fake_result
        )

        result = run_audit_report(RunAuditReportRequest(granularity="DAILY"))

        assert result == {"snapshot_id": "s1", "alerts": []}

    def test_invalid_granularity_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            run_audit_report(RunAuditReportRequest(granularity="YEARLY"))
        assert exc_info.value.status_code == 400

    def test_agent_failure_raises_500(self, monkeypatch):
        fake_result = MagicMock(success=False, error="mongo unreachable")
        monkeypatch.setattr(
            "src.ai_agents.audit_agent.AuditAgent.run", lambda self, context: fake_result
        )

        with pytest.raises(HTTPException) as exc_info:
            run_audit_report(RunAuditReportRequest(granularity="DAILY"))
        assert exc_info.value.status_code == 500

    def test_defaults_to_daily(self):
        req = RunAuditReportRequest()
        assert req.granularity == "DAILY"
