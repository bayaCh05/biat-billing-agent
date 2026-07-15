"""Unit tests — src/ai_agents/audit_report_pdf.py (Audit Agent Lot 5 PDF export)."""
from __future__ import annotations

from src.ai_agents.audit_report_pdf import AuditReportPDFGenerator


class TestAuditReportPDFGenerator:
    def test_generates_valid_pdf_bytes_for_full_snapshot(self):
        snapshot = {
            "_id": "s1", "granularity": "DAILY",
            "period_start": "2026-07-15T00:00:00Z", "period_end": "2026-07-15T00:00:00Z",
            "generated_at": "2026-07-15T02:00:00Z", "status": "OK",
            "metrics": {
                "invoices": {"pending_count": 6, "rejection_rate": 0.0},
                "journal": {"consistency_score": 1.0, "issues": []},
            },
            "alerts": [
                {"domain": "risks", "severity": "CRITICAL", "code": "X", "message": "2 risques critiques."},
                {"domain": "budget", "severity": "WARNING", "code": "Y", "message": "\xc9cart budg\xe9taire -34.4%."},
            ],
            "narrative_summary": "Synth\xe8se de test avec accents \xe9\xe8\xea.",
        }

        pdf_bytes = AuditReportPDFGenerator().generate_to_bytes(snapshot)

        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 500

    def test_handles_empty_snapshot_without_raising(self):
        snapshot = {
            "granularity": "MONTHLY", "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-07-31T00:00:00Z", "generated_at": "2026-08-01T03:00:00Z",
            "status": "DEGRADED", "metrics": {}, "alerts": [], "narrative_summary": None,
        }

        pdf_bytes = AuditReportPDFGenerator().generate_to_bytes(snapshot)

        assert pdf_bytes.startswith(b"%PDF")
