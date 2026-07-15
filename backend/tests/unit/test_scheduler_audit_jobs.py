"""Regression tests for the WEEKLY/MONTHLY audit scheduler jobs (Audit Agent Lot 5).

Before this, only _job_audit_daily was wired into scheduler.py — WEEKLY/MONTHLY
AuditSnapshotDocument granularities could only ever be produced via the manual
POST /audit-reports/run endpoint, never on a schedule.
"""
from __future__ import annotations

from unittest.mock import MagicMock


class TestJobAuditWeekly:
    def test_runs_audit_agent_with_weekly_granularity(self, monkeypatch):
        fake_agent = MagicMock()
        fake_agent.run.return_value = MagicMock(output={"snapshot_id": "s1"})
        monkeypatch.setattr("src.ai_agents.audit_agent.AuditAgent", lambda: fake_agent)

        from api.scheduler import _job_audit_weekly
        _job_audit_weekly()

        fake_agent.run.assert_called_once_with({"granularity": "WEEKLY"})

    def test_swallows_exceptions(self, monkeypatch):
        fake_agent = MagicMock()
        fake_agent.run.side_effect = RuntimeError("boom")
        monkeypatch.setattr("src.ai_agents.audit_agent.AuditAgent", lambda: fake_agent)

        from api.scheduler import _job_audit_weekly
        _job_audit_weekly()  # must not raise


class TestJobAuditMonthly:
    def test_runs_audit_agent_with_monthly_granularity(self, monkeypatch):
        fake_agent = MagicMock()
        fake_agent.run.return_value = MagicMock(output={"snapshot_id": "s2"})
        monkeypatch.setattr("src.ai_agents.audit_agent.AuditAgent", lambda: fake_agent)

        from api.scheduler import _job_audit_monthly
        _job_audit_monthly()

        fake_agent.run.assert_called_once_with({"granularity": "MONTHLY"})

    def test_swallows_exceptions(self, monkeypatch):
        fake_agent = MagicMock()
        fake_agent.run.side_effect = RuntimeError("boom")
        monkeypatch.setattr("src.ai_agents.audit_agent.AuditAgent", lambda: fake_agent)

        from api.scheduler import _job_audit_monthly
        _job_audit_monthly()  # must not raise


class TestSchedulerRegistersAuditJobs:
    def test_start_scheduler_registers_weekly_and_monthly_audit_jobs(self, monkeypatch):
        import api.scheduler as scheduler_module

        monkeypatch.setattr(scheduler_module, "_scheduler", None)
        sched = scheduler_module.start_scheduler()
        try:
            job_ids = {job.id for job in sched.get_jobs()}
            assert "audit_weekly" in job_ids
            assert "audit_monthly" in job_ids
            assert "audit_daily" in job_ids
        finally:
            scheduler_module.stop_scheduler()
