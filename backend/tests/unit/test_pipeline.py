"""Unit tests for pipeline stage functions — export_file, post_journal, recover_interrupted."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.agent.pipeline import (
    PipelineComponents,
    export_file,
    post_journal,
    recover_interrupted,
)
from src.models.enums import FlagType, InvoiceStatus
from src.models.invoice import InvoiceRecord


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_invoice(status: InvoiceStatus = InvoiceStatus.VALIDATED) -> InvoiceRecord:
    inv = InvoiceRecord(file_hash="a" * 64, raw_file_path="/tmp/test.pdf", status=status)
    inv.cost_catalog_id = "maintenance_informatique"
    return inv


def _make_components(journal_raises=False) -> PipelineComponents:
    repo = MagicMock()
    repo.save = MagicMock(return_value=None)

    exporter = MagicMock()
    exporter.export.return_value = "REF-001"

    catalog = MagicMock()
    catalog.get.return_value = MagicMock(id="maintenance_informatique")

    entry_generator = MagicMock()
    if journal_raises:
        entry_generator.generate.side_effect = ValueError("Écriture non équilibrée")
    else:
        entry_generator.generate.return_value = MagicMock(reference="REF-001")

    journal_repo = MagicMock()
    journal_repo.save = MagicMock(return_value=None)

    return PipelineComponents(
        extractor=MagicMock(),
        classifier=MagicMock(),
        coder=MagicMock(),
        field_validator=MagicMock(),
        coherence_checker=MagicMock(),
        duplicate_detector=MagicMock(),
        anomaly_detector=MagicMock(),
        auto_corrector=MagicMock(),
        exporter=exporter,
        entry_generator=entry_generator,
        cost_catalog=catalog,
        repository=repo,
        journal_repository=journal_repo,
        max_retries=3,
    )


# ── export_file ───────────────────────────────────────────────────────────────

class TestExportFile:
    def test_success_sets_exported_status(self):
        inv = _make_invoice()
        c = _make_components()
        result = export_file(inv, c)
        assert result.status == InvoiceStatus.EXPORTED
        assert result.export_reference == "REF-001"

    def test_exporter_failure_sets_error_after_max_retries(self):
        inv = _make_invoice()
        c = _make_components()
        c.exporter.export.side_effect = RuntimeError("disk full")
        inv.retry_count = c.max_retries  # already at max
        result = export_file(inv, c)
        assert result.status == InvoiceStatus.ERROR


# ── post_journal ──────────────────────────────────────────────────────────────

class TestPostJournal:
    def test_success_sets_journaled_status(self):
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        c = _make_components()
        result = post_journal(inv, c)
        assert result.status == InvoiceStatus.JOURNALED

    def test_failure_reverts_to_exported(self):
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        c = _make_components(journal_raises=True)
        result = post_journal(inv, c)
        assert result.status == InvoiceStatus.EXPORTED

    def test_failure_adds_journal_failed_flag(self):
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        c = _make_components(journal_raises=True)
        result = post_journal(inv, c)
        flag_types = [f.flag_type for f in result.flags]
        assert FlagType.JOURNAL_FAILED in flag_types

    def test_failure_sets_last_error(self):
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        c = _make_components(journal_raises=True)
        result = post_journal(inv, c)
        assert result.last_error is not None
        assert "équilibrée" in result.last_error

    def test_no_catalog_id_skips_journal_and_succeeds(self):
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        inv.cost_catalog_id = None
        c = _make_components()
        result = post_journal(inv, c)
        assert result.status == InvoiceStatus.JOURNALED
        c.entry_generator.generate.assert_not_called()


# ── recover_interrupted ───────────────────────────────────────────────────────

class TestRecoverInterrupted:
    def _repo_with_invoices(self, invoices_by_status: dict) -> MagicMock:
        repo = MagicMock()
        repo.get_by_status.side_effect = lambda s: invoices_by_status.get(s, [])
        repo.save = MagicMock()
        return repo

    def test_resets_journaling_to_exported(self):
        inv = _make_invoice(InvoiceStatus.JOURNALING)
        repo = self._repo_with_invoices({InvoiceStatus.JOURNALING: [inv], InvoiceStatus.EXPORTED: []})
        recover_interrupted(repo)
        assert inv.status == InvoiceStatus.EXPORTED

    def test_resets_exporting_to_validated(self):
        inv = _make_invoice(InvoiceStatus.EXPORTING)
        repo = self._repo_with_invoices({InvoiceStatus.EXPORTING: [inv], InvoiceStatus.EXPORTED: []})
        recover_interrupted(repo)
        assert inv.status == InvoiceStatus.VALIDATED

    def test_does_not_touch_exported_invoices(self):
        # EXPORTED is a stable status — recover_interrupted must leave it alone
        inv = _make_invoice(InvoiceStatus.EXPORTED)
        repo = self._repo_with_invoices({InvoiceStatus.EXPORTED: [inv]})
        recover_interrupted(repo)
        assert inv.status == InvoiceStatus.EXPORTED
