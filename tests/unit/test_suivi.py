"""Unit tests for the suivi module."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from src.models.enums import InvoiceDirection, InvoiceStatus
from src.models.invoice import ConfidenceField, InvoiceRecord, ValidationFlag
from src.models.enums import FlagSeverity, FlagType
from src.suivi.aggregator import AgeingBucket, Aggregator, DashboardSnapshot
from src.suivi.lifecycle_tracker import LifecycleTracker
from src.suivi.reconciler import Reconciler


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cf(value, confidence=0.95):
    return ConfidenceField(value=value, confidence=confidence)


def _invoice(
    status: InvoiceStatus = InvoiceStatus.EXPORTED,
    direction: InvoiceDirection = InvoiceDirection.SUPPLIER,
    amount: float | None = 1190.0,
    due_days_from_today: int | None = None,
    human_review_required: bool = False,
    **kwargs,
) -> InvoiceRecord:
    inv = InvoiceRecord(
        file_hash=f"h{uuid4().hex[:6]}",
        raw_file_path="/tmp/inv.pdf",
        status=status,
        direction=direction,
        human_review_required=human_review_required,
        **kwargs,
    )
    if amount is not None:
        inv.amount_ttc = _cf(amount)
    if due_days_from_today is not None:
        inv.due_date = _cf(date.today() + timedelta(days=due_days_from_today))
    return inv


def _mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_pending_payment.return_value = []
    repo.get_pending_collection.return_value = []
    repo.get_overdue.return_value = []
    repo.get_flagged.return_value = []
    repo.get_by_status.return_value = []
    repo.count_by_status.return_value = {}
    repo.count_auto_approved.return_value = (0, 0)
    return repo


# ── LifecycleTracker ──────────────────────────────────────────────────────────

class TestLifecycleTrackerQueries:
    def setup_method(self):
        self.repo = _mock_repo()
        self.lt = LifecycleTracker(repository=self.repo)

    def test_get_pending_payment_delegates_to_repo(self):
        invoices = [_invoice()]
        self.repo.get_pending_payment.return_value = invoices
        result = self.lt.get_pending_payment()
        assert result == invoices
        self.repo.get_pending_payment.assert_called_once()

    def test_get_pending_collection_delegates_to_repo(self):
        invoices = [_invoice(direction=InvoiceDirection.CLIENT)]
        self.repo.get_pending_collection.return_value = invoices
        result = self.lt.get_pending_collection()
        assert result == invoices

    def test_get_overdue_delegates_to_repo(self):
        overdue = [_invoice(due_days_from_today=-5)]
        self.repo.get_overdue.return_value = overdue
        result = self.lt.get_overdue()
        assert result == overdue

    def test_get_pending_export_queries_validated_status(self):
        self.lt.get_pending_export()
        self.repo.get_by_status.assert_called_once_with(InvoiceStatus.VALIDATED)

    def test_get_flagged_for_review_delegates(self):
        flagged = [_invoice(status=InvoiceStatus.FLAGGED)]
        self.repo.get_flagged.return_value = flagged
        result = self.lt.get_flagged_for_review()
        assert result == flagged


class TestLifecycleTrackerMarkPaid:
    def setup_method(self):
        self.repo = _mock_repo()
        self.lt = LifecycleTracker(repository=self.repo)

    def test_mark_paid_sets_status_to_paid(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED)
        inv_id = inv.id
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        result = self.lt.mark_paid(inv_id, "REF-001", 1190.0)

        assert result.status == InvoiceStatus.PAID
        assert result.paid_at is not None
        assert result.export_reference == "REF-001"

    def test_mark_paid_saves_payment_orm(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED)
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        self.lt.mark_paid(inv.id, "REF-002", 500.0)

        self.repo.session.add.assert_called_once()

    def test_mark_paid_raises_if_not_found(self):
        self.repo.get_by_id.return_value = None
        with pytest.raises(LookupError):
            self.lt.mark_paid(uuid4(), "REF", 100.0)


class TestLifecycleTrackerMarkCollected:
    def setup_method(self):
        self.repo = _mock_repo()
        self.lt = LifecycleTracker(repository=self.repo)

    def test_mark_collected_sets_status_to_collected(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED, direction=InvoiceDirection.CLIENT)
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        result = self.lt.mark_collected(inv.id, "COL-001", 1190.0)

        assert result.status == InvoiceStatus.COLLECTED
        assert result.collected_at is not None


class TestLifecycleTrackerApproveFlagged:
    def setup_method(self):
        self.repo = _mock_repo()
        self.lt = LifecycleTracker(repository=self.repo)

    def test_approve_moves_to_validated(self):
        inv = _invoice(status=InvoiceStatus.FLAGGED)
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        result = self.lt.approve_flagged(inv.id, reviewer="analyst1")

        assert result.status == InvoiceStatus.VALIDATED
        assert result.reviewed_by == "analyst1"
        assert result.reviewed_at is not None

    def test_approve_resolves_all_flags(self):
        inv = _invoice(status=InvoiceStatus.FLAGGED)
        inv.flags = [
            ValidationFlag(
                flag_type=FlagType.MISSING_FIELD,
                severity=FlagSeverity.ERROR,
                message="missing",
            ),
            ValidationFlag(
                flag_type=FlagType.LOW_CONFIDENCE,
                severity=FlagSeverity.WARNING,
                message="low",
            ),
        ]
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        result = self.lt.approve_flagged(inv.id, reviewer="analyst1", notes="OK after review")

        assert all(f.resolved for f in result.flags)
        assert all(f.resolved_by == "analyst1" for f in result.flags)

    def test_approve_wrong_status_raises(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED)  # not FLAGGED
        self.repo.get_by_id.return_value = inv
        with pytest.raises(ValueError, match="expected FLAGGED"):
            self.lt.approve_flagged(inv.id, reviewer="analyst1")

    def test_reject_sets_rejected_status(self):
        inv = _invoice(status=InvoiceStatus.FLAGGED)
        self.repo.get_by_id.return_value = inv
        self.repo.save.return_value = inv

        result = self.lt.reject_invoice(inv.id, reviewer="manager", reason="Fraudulent")

        assert result.status == InvoiceStatus.REJECTED
        assert result.reviewed_by == "manager"
        assert "Fraudulent" in result.human_review_notes


# ── Reconciler ────────────────────────────────────────────────────────────────

class TestReconciler:
    def setup_method(self):
        self.repo = _mock_repo()
        self.rc = Reconciler(repository=self.repo)

    def test_match_by_export_reference(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED, export_reference="PAY-2024-001")
        self.repo.get_by_status.return_value = [inv]

        result = self.rc.match_payment({"reference": "PAY-2024-001"})

        assert result is inv

    def test_no_match_returns_none(self):
        self.repo.get_by_status.return_value = []
        self.repo.find_potential_duplicates.return_value = []
        self.repo.find_near_duplicates.return_value = []

        result = self.rc.match_payment({"reference": "NONEXISTENT"})

        assert result is None

    def test_match_by_invoice_number_and_issuer(self):
        inv = _invoice(status=InvoiceStatus.EXPORTED)
        self.repo.get_by_status.return_value = []  # no reference match
        self.repo.find_potential_duplicates.return_value = [inv]

        result = self.rc.match_payment({
            "invoice_number": "INV-001",
            "issuer_tax_id": "MF123",
        })

        assert result is inv

    def test_ambiguous_fuzzy_match_returns_none(self):
        inv1 = _invoice(status=InvoiceStatus.EXPORTED)
        inv2 = _invoice(status=InvoiceStatus.EXPORTED)
        self.repo.get_by_status.return_value = []
        self.repo.find_potential_duplicates.return_value = []
        self.repo.find_near_duplicates.return_value = [inv1, inv2]

        result = self.rc.match_payment({
            "issuer_tax_id": "MF123",
            "amount": 1190.0,
        })

        assert result is None

    def test_match_purchase_order_returns_invoice_unchanged(self):
        inv = _invoice()
        result = self.rc.match_purchase_order(inv)
        assert result is inv


# ── Aggregator ────────────────────────────────────────────────────────────────

class TestAgeingBucket:
    def test_total_overdue_sums_all_buckets(self):
        b = AgeingBucket(current=0, days_1_30=100, days_31_60=200, days_61_90=50, over_90=30)
        assert b.total_overdue == 380.0

    def test_total_includes_current(self):
        b = AgeingBucket(current=500, days_1_30=100)
        assert b.total == 600.0


class TestAggregator:
    def setup_method(self):
        self.repo = _mock_repo()
        self.agg = Aggregator(repository=self.repo)

    def test_snapshot_returns_dashboard(self):
        snap = self.agg.snapshot()
        assert isinstance(snap, DashboardSnapshot)

    def test_total_payables_sums_amounts(self):
        self.repo.get_pending_payment.return_value = [
            _invoice(amount=1000.0),
            _invoice(amount=500.0),
        ]
        snap = self.agg.snapshot()
        assert snap.total_payables == 1500.0

    def test_total_receivables_sums_amounts(self):
        self.repo.get_pending_collection.return_value = [
            _invoice(amount=2000.0, direction=InvoiceDirection.CLIENT),
        ]
        snap = self.agg.snapshot()
        assert snap.total_receivables == 2000.0

    def test_overdue_count(self):
        self.repo.get_overdue.return_value = [_invoice(), _invoice()]
        snap = self.agg.snapshot()
        assert snap.overdue_count == 2

    def test_flagged_count(self):
        self.repo.get_flagged.return_value = [_invoice(status=InvoiceStatus.FLAGGED)]
        snap = self.agg.snapshot()
        assert snap.flagged_count == 1

    def test_auto_approval_rate_all_auto(self):
        self.repo.count_auto_approved.return_value = (3, 3)
        snap = self.agg.snapshot()
        assert snap.auto_approval_rate == 1.0

    def test_auto_approval_rate_mixed(self):
        self.repo.count_auto_approved.return_value = (2, 1)
        snap = self.agg.snapshot()
        assert snap.auto_approval_rate == 0.5

    def test_ageing_bucket_current_not_due(self):
        inv = _invoice(amount=1000.0, due_days_from_today=10)
        self.repo.get_pending_payment.return_value = [inv]
        snap = self.agg.snapshot()
        assert snap.payables_ageing.current == 1000.0
        assert snap.payables_ageing.total_overdue == 0.0

    def test_ageing_bucket_overdue_1_30(self):
        inv = _invoice(amount=500.0, due_days_from_today=-15)
        self.repo.get_pending_payment.return_value = [inv]
        snap = self.agg.snapshot()
        assert snap.payables_ageing.days_1_30 == 500.0

    def test_ageing_bucket_over_90(self):
        inv = _invoice(amount=300.0, due_days_from_today=-100)
        self.repo.get_pending_payment.return_value = [inv]
        snap = self.agg.snapshot()
        assert snap.payables_ageing.over_90 == 300.0
