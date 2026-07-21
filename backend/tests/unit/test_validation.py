"""Unit tests for the validation module."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock


from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem
from src.validation.anomaly_detector import AnomalyDetector
from src.validation.coherence_checker import CoherenceChecker
from src.validation.duplicate_detector import DuplicateDetector
from src.validation.field_validator import FieldValidator


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _invoice(**kwargs) -> InvoiceRecord:
    base = dict(file_hash="h1", raw_file_path="/tmp/inv.pdf")
    base.update(kwargs)
    return InvoiceRecord(**base)


def _cf(value, confidence=0.95, source=None):
    return ConfidenceField(value=value, confidence=confidence, source=source)


def _complete_invoice() -> InvoiceRecord:
    """Minimal valid invoice — passes all level-1 checks."""
    inv = _invoice()
    inv.issuer_name = _cf("Acme SARL")
    inv.invoice_number = _cf("INV-2024-001")
    inv.invoice_date = _cf(date(2024, 6, 1))
    inv.amount_ttc = _cf(1190.0)
    return inv


_THRESHOLDS = {
    "minimum_confidence": 0.5,
    "warning_confidence": 0.7,
}

_VALIDATION_CONFIG = {
    "validation": {
        "math_tolerance_absolute": 0.02,
        "math_tolerance_relative": 0.001,
        "tva_rates_allowed": [0, 7, 13, 19],
        "duplicate_window_days": 90,
        "high_value_threshold": 50000,
    }
}


# ── FieldValidator ────────────────────────────────────────────────────────────

class TestFieldValidatorRequiredFields:
    def setup_method(self):
        self.fv = FieldValidator(confidence_thresholds=_THRESHOLDS)

    def test_no_flags_when_all_required_fields_present(self):
        inv = _complete_invoice()
        inv = self.fv.validate(inv)
        missing = [f for f in inv.flags if f.flag_type == FlagType.MISSING_FIELD]
        assert not missing

    def test_flags_missing_issuer_name(self):
        inv = _invoice()
        inv.invoice_number = _cf("INV-001")
        inv.invoice_date = _cf(date(2024, 1, 1))
        inv.amount_ttc = _cf(100.0)
        inv = self.fv.validate(inv)
        flag_types = [f.flag_type for f in inv.flags]
        assert FlagType.MISSING_FIELD in flag_types

    def test_missing_field_is_error_severity(self):
        inv = _invoice()  # all required fields absent
        inv = self.fv.validate(inv)
        errors = [f for f in inv.flags if f.flag_type == FlagType.MISSING_FIELD]
        assert all(f.severity == FlagSeverity.ERROR for f in errors)

    def test_missing_field_triggers_human_review(self):
        inv = _invoice()
        inv = self.fv.validate(inv)
        assert inv.human_review_required is True


class TestFieldValidatorConfidence:
    def setup_method(self):
        self.fv = FieldValidator(confidence_thresholds=_THRESHOLDS)

    def test_low_confidence_error_flag(self):
        inv = _complete_invoice()
        inv.issuer_name = _cf("Acme", confidence=0.3)
        inv = self.fv.validate(inv)
        low_conf_errors = [
            f for f in inv.flags
            if f.flag_type == FlagType.LOW_CONFIDENCE and f.severity == FlagSeverity.ERROR
        ]
        assert low_conf_errors

    def test_borderline_confidence_warning_flag(self):
        inv = _complete_invoice()
        inv.issuer_name = _cf("Acme", confidence=0.6)
        inv = self.fv.validate(inv)
        low_conf_warnings = [
            f for f in inv.flags
            if f.flag_type == FlagType.LOW_CONFIDENCE and f.severity == FlagSeverity.WARNING
        ]
        assert low_conf_warnings

    def test_sufficient_confidence_no_flag(self):
        inv = _complete_invoice()
        inv = self.fv.validate(inv)
        low_conf = [f for f in inv.flags if f.flag_type == FlagType.LOW_CONFIDENCE]
        assert not low_conf


class TestFieldValidatorTaxId:
    def setup_method(self):
        self.fv = FieldValidator(confidence_thresholds=_THRESHOLDS)

    def test_valid_mf_no_flag(self):
        inv = _complete_invoice()
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv = self.fv.validate(inv)
        tax_id_flags = [f for f in inv.flags if f.flag_type == FlagType.INVALID_TAX_ID]
        assert not tax_id_flags

    def test_invalid_mf_format_adds_warning(self):
        inv = _complete_invoice()
        inv.issuer_tax_id = _cf("INVALID-FORMAT")
        inv = self.fv.validate(inv)
        tax_id_flags = [f for f in inv.flags if f.flag_type == FlagType.INVALID_TAX_ID]
        assert tax_id_flags
        assert tax_id_flags[0].severity == FlagSeverity.WARNING

    def test_none_tax_id_no_flag(self):
        inv = _complete_invoice()
        inv.issuer_tax_id = ConfidenceField(value=None)
        inv = self.fv.validate(inv)
        tax_id_flags = [f for f in inv.flags if f.flag_type == FlagType.INVALID_TAX_ID]
        assert not tax_id_flags


# ── CoherenceChecker ──────────────────────────────────────────────────────────

class TestCoherenceCheckerDates:
    def setup_method(self):
        self.cc = CoherenceChecker(config=_VALIDATION_CONFIG)

    def test_future_invoice_date_warning(self):
        inv = _complete_invoice()
        future = date.today() + timedelta(days=30)
        inv.invoice_date = _cf(future)
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.FUTURE_DATED for f in inv.flags)

    def test_past_invoice_date_no_flag(self):
        inv = _complete_invoice()
        inv.invoice_date = _cf(date(2023, 1, 1))
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.FUTURE_DATED for f in inv.flags)

    def test_due_before_issue_error(self):
        inv = _complete_invoice()
        inv.invoice_date = _cf(date(2024, 6, 15))
        inv.due_date = _cf(date(2024, 6, 1))  # before invoice_date
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.DUE_BEFORE_ISSUE for f in inv.flags)

    def test_due_after_issue_no_flag(self):
        inv = _complete_invoice()
        inv.invoice_date = _cf(date(2024, 6, 1))
        inv.due_date = _cf(date(2024, 7, 1))
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.DUE_BEFORE_ISSUE for f in inv.flags)


class TestCoherenceCheckerAmounts:
    def setup_method(self):
        self.cc = CoherenceChecker(config=_VALIDATION_CONFIG)

    def test_consistent_amounts_no_flag(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(1000.0)
        inv.tva_amount = _cf(190.0)
        inv.amount_ttc = _cf(1190.0)
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.TOTAL_MISMATCH for f in inv.flags)

    def test_inconsistent_amounts_error(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(1000.0)
        inv.tva_amount = _cf(190.0)
        inv.amount_ttc = _cf(1500.0)  # wrong
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.TOTAL_MISMATCH for f in inv.flags)

    def test_missing_one_amount_no_total_check(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(1000.0)
        # tva_amount not set → can't validate
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.TOTAL_MISMATCH for f in inv.flags)


class TestCoherenceCheckerLineItems:
    def setup_method(self):
        self.cc = CoherenceChecker(config=_VALIDATION_CONFIG)

    def test_line_items_sum_matches_ht(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(500.0)
        inv.line_items = [
            LineItem(line_number=1, description="Item A", line_total=300.0),
            LineItem(line_number=2, description="Item B", line_total=200.0),
        ]
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.LINEITEMS_SUM_MISMATCH for f in inv.flags)

    def test_line_items_sum_mismatch_warning(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(500.0)
        inv.line_items = [
            LineItem(line_number=1, description="Item A", line_total=300.0),
            LineItem(line_number=2, description="Item B", line_total=100.0),
        ]
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.LINEITEMS_SUM_MISMATCH for f in inv.flags)

    def test_per_line_qty_x_unit_price_mismatch_flags(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(300.0)
        inv.line_items = [
            LineItem(line_number=1, quantity=3.0, unit_price=100.0, line_total=999.0),
        ]
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.LINEITEMS_SUM_MISMATCH for f in inv.flags)

    def test_per_line_qty_x_unit_price_consistent_no_flag(self):
        inv = _complete_invoice()
        inv.amount_ht = _cf(300.0)
        inv.line_items = [
            LineItem(line_number=1, quantity=3.0, unit_price=100.0, line_total=300.0),
        ]
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.LINEITEMS_SUM_MISMATCH for f in inv.flags)


class TestCoherenceCheckerTVARate:
    def setup_method(self):
        self.cc = CoherenceChecker(config=_VALIDATION_CONFIG)

    def test_valid_tva_rate_no_flag(self):
        inv = _complete_invoice()
        inv.tva_rate = _cf(19.0)
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.INVALID_TVA_RATE for f in inv.flags)

    def test_invalid_tva_rate_warning(self):
        inv = _complete_invoice()
        inv.tva_rate = _cf(25.0)  # not a Tunisian rate
        inv = self.cc.check(inv)
        assert any(f.flag_type == FlagType.INVALID_TVA_RATE for f in inv.flags)

    def test_zero_tva_no_flag(self):
        inv = _complete_invoice()
        inv.tva_rate = _cf(0.0)
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.INVALID_TVA_RATE for f in inv.flags)

    def test_none_tva_no_flag(self):
        inv = _complete_invoice()
        inv = self.cc.check(inv)
        assert not any(f.flag_type == FlagType.INVALID_TVA_RATE for f in inv.flags)


# ── DuplicateDetector ─────────────────────────────────────────────────────────

class TestDuplicateDetector:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.dd = DuplicateDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo)

    def test_no_duplicates_no_flag(self):
        self.mock_repo.find_potential_duplicates.return_value = []
        self.mock_repo.find_near_duplicates.return_value = []
        inv = _complete_invoice()
        inv.invoice_number = _cf("INV-001")
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv = self.dd.detect(inv)
        assert not inv.flags

    def test_exact_duplicate_adds_error(self):
        duplicate = MagicMock()
        duplicate.id = "dup-uuid"
        self.mock_repo.find_potential_duplicates.return_value = [duplicate]
        self.mock_repo.find_near_duplicates.return_value = []
        inv = _complete_invoice()
        inv.invoice_number = _cf("INV-001")
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv = self.dd.detect(inv)
        assert any(f.flag_type == FlagType.DUPLICATE for f in inv.flags)
        dup_flags = [f for f in inv.flags if f.flag_type == FlagType.DUPLICATE]
        assert dup_flags[0].severity == FlagSeverity.ERROR

    def test_near_duplicate_adds_warning(self):
        self.mock_repo.find_potential_duplicates.return_value = []
        near = MagicMock()
        near.id = "near-uuid"
        self.mock_repo.find_near_duplicates.return_value = [near]
        inv = _complete_invoice()
        inv.issuer_name = _cf("Acme SARL")
        inv.amount_ttc = _cf(1190.0)
        inv = self.dd.detect(inv)
        assert any(f.flag_type == FlagType.NEAR_DUPLICATE for f in inv.flags)

    def test_missing_invoice_number_skips_exact_check(self):
        inv = _complete_invoice()
        inv.invoice_number = ConfidenceField(value=None)
        inv = self.dd.detect(inv)
        self.mock_repo.find_potential_duplicates.assert_not_called()

    def test_exact_duplicate_error_skips_near_check(self):
        duplicate = MagicMock()
        duplicate.id = "dup-uuid"
        self.mock_repo.find_potential_duplicates.return_value = [duplicate]
        inv = _complete_invoice()
        inv.invoice_number = _cf("INV-001")
        inv.issuer_tax_id = _cf("MF123")
        inv = self.dd.detect(inv)
        # Near-duplicate check skipped because has_errors is True
        self.mock_repo.find_near_duplicates.assert_not_called()


# ── AnomalyDetector ───────────────────────────────────────────────────────────

class TestAnomalyDetector:
    def setup_method(self):
        self.mock_repo = MagicMock()
        self.ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo)

    def test_high_value_adds_warning(self):
        self.mock_repo.get_historical_amounts.return_value = []
        inv = _complete_invoice()
        inv.amount_ttc = _cf(60000.0)
        inv = self.ad.detect(inv)
        assert any(f.flag_type == FlagType.HIGH_VALUE for f in inv.flags)

    def test_below_threshold_no_high_value_flag(self):
        self.mock_repo.get_historical_amounts.return_value = []
        inv = _complete_invoice()
        inv.amount_ttc = _cf(1000.0)
        inv = self.ad.detect(inv)
        assert not any(f.flag_type == FlagType.HIGH_VALUE for f in inv.flags)

    def test_round_amount_suspicious(self):
        self.mock_repo.get_historical_amounts.return_value = []
        inv = _complete_invoice()
        inv.amount_ttc = _cf(50000.0)
        inv = self.ad.detect(inv)
        suspicious = [f for f in inv.flags if f.flag_type == FlagType.SUSPICIOUS_AMOUNT]
        assert suspicious

    def test_non_round_amount_no_flag(self):
        self.mock_repo.get_historical_amounts.return_value = []
        inv = _complete_invoice()
        inv.amount_ttc = _cf(12345.67)
        inv = self.ad.detect(inv)
        suspicious = [f for f in inv.flags if f.flag_type == FlagType.SUSPICIOUS_AMOUNT]
        assert not suspicious

    def test_statistical_outlier_flagged(self):
        # Mean ~1000, std ~100 → amount 1400 is 4 std dev → outlier
        self.mock_repo.get_historical_amounts.return_value = [
            950, 1000, 1050, 980, 1020, 1010
        ]
        inv = _complete_invoice()
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv.amount_ttc = _cf(1400.0)
        inv = self.ad.detect(inv)
        suspicious = [f for f in inv.flags if f.flag_type == FlagType.SUSPICIOUS_AMOUNT]
        assert suspicious

    def test_normal_amount_no_outlier_flag(self):
        self.mock_repo.get_historical_amounts.return_value = [
            950, 1000, 1050, 980, 1020, 1010
        ]
        inv = _complete_invoice()
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv.amount_ttc = _cf(1005.0)  # well within normal range
        inv = self.ad.detect(inv)
        suspicious = [f for f in inv.flags if f.flag_type == FlagType.SUSPICIOUS_AMOUNT]
        assert not suspicious

    def test_fewer_than_3_historical_skips_outlier_check(self):
        self.mock_repo.get_historical_amounts.return_value = [500, 1500]
        inv = _complete_invoice()
        inv.issuer_tax_id = _cf("1234567A/M/P/000")
        inv.amount_ttc = _cf(99999.0)
        inv = self.ad.detect(inv)
        suspicious = [
            f for f in inv.flags
            if f.flag_type == FlagType.SUSPICIOUS_AMOUNT and "standard deviation" in f.message
        ]
        assert not suspicious


# ── AnomalyDetector — plausibility check ─────────────────────────────────────

class TestPlausibilityCheck:
    def _catalog_with_max(self, catalog_id: str, max_amount: float):
        entry = MagicMock()
        entry.max_plausible_amount = max_amount
        catalog = MagicMock()
        catalog.get.side_effect = lambda cid: entry if cid == catalog_id else None
        return catalog

    def setup_method(self):
        self.mock_repo = MagicMock()
        self.mock_repo.get_historical_amounts.return_value = []

    def test_amount_over_max_adds_warning(self):
        catalog = self._catalog_with_max("fournitures_bureau", 5000.0)
        ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo, catalog=catalog)
        inv = _complete_invoice()
        inv.cost_catalog_id = "fournitures_bureau"
        inv.amount_ttc = _cf(973420.0)  # Ollama decimal misparse
        result = ad.detect(inv)
        flags = [f for f in result.flags if f.flag_type == FlagType.AMOUNT_IMPLAUSIBLE]
        assert len(flags) == 1
        assert flags[0].severity == FlagSeverity.WARNING
        assert "973,420" in flags[0].message or "973420" in flags[0].message

    def test_amount_within_max_no_flag(self):
        catalog = self._catalog_with_max("fournitures_bureau", 5000.0)
        ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo, catalog=catalog)
        inv = _complete_invoice()
        inv.cost_catalog_id = "fournitures_bureau"
        inv.amount_ttc = _cf(973.420)
        result = ad.detect(inv)
        assert not any(f.flag_type == FlagType.AMOUNT_IMPLAUSIBLE for f in result.flags)

    def test_no_catalog_skips_check(self):
        ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo, catalog=None)
        inv = _complete_invoice()
        inv.cost_catalog_id = "fournitures_bureau"
        inv.amount_ttc = _cf(999999.0)
        result = ad.detect(inv)
        assert not any(f.flag_type == FlagType.AMOUNT_IMPLAUSIBLE for f in result.flags)

    def test_no_cost_catalog_id_skips_check(self):
        catalog = self._catalog_with_max("fournitures_bureau", 5000.0)
        ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo, catalog=catalog)
        inv = _complete_invoice()
        inv.cost_catalog_id = None
        inv.amount_ttc = _cf(999999.0)
        result = ad.detect(inv)
        assert not any(f.flag_type == FlagType.AMOUNT_IMPLAUSIBLE for f in result.flags)

    def test_entry_with_no_max_skips_check(self):
        entry = MagicMock()
        entry.max_plausible_amount = None
        catalog = MagicMock()
        catalog.get.return_value = entry
        ad = AnomalyDetector(config=_VALIDATION_CONFIG, repository=self.mock_repo, catalog=catalog)
        inv = _complete_invoice()
        inv.cost_catalog_id = "maintenance_informatique"
        inv.amount_ttc = _cf(999999.0)
        result = ad.detect(inv)
        assert not any(f.flag_type == FlagType.AMOUNT_IMPLAUSIBLE for f in result.flags)
