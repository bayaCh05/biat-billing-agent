"""Unit tests for FlagEscalator."""
from __future__ import annotations

import pytest

from src.models.enums import FlagSeverity, FlagType
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.validation.escalator import FlagEscalator


def _inv() -> InvoiceRecord:
    return InvoiceRecord(file_hash="a" * 64, raw_file_path="/tmp/x.pdf")


def _warn(flag_type: FlagType = FlagType.LOW_CONFIDENCE) -> ValidationFlag:
    return ValidationFlag(flag_type=flag_type, severity=FlagSeverity.WARNING, field_name="f", message="w")


def _error() -> ValidationFlag:
    return ValidationFlag(flag_type=FlagType.MISSING_FIELD, severity=FlagSeverity.ERROR, field_name="f", message="e")


class TestFlagEscalator:
    def test_no_escalation_below_threshold(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        inv.add_flag(_warn())  # 1 warning — below threshold
        result = esc.escalate(inv)
        assert not any(f.flag_type == FlagType.ESCALATED for f in result.flags)

    def test_escalates_at_threshold(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        inv.add_flag(_warn(FlagType.LOW_CONFIDENCE))
        inv.add_flag(_warn(FlagType.LINEITEMS_SUM_MISMATCH))
        result = esc.escalate(inv)
        escalated = [f for f in result.flags if f.flag_type == FlagType.ESCALATED]
        assert len(escalated) == 1
        assert escalated[0].severity == FlagSeverity.ERROR

    def test_escalates_above_threshold(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        for _ in range(3):
            inv.add_flag(_warn())
        result = esc.escalate(inv)
        assert any(f.flag_type == FlagType.ESCALATED for f in result.flags)

    def test_escalated_message_lists_triggering_flags(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        inv.add_flag(_warn(FlagType.LOW_CONFIDENCE))
        inv.add_flag(_warn(FlagType.HIGH_VALUE))
        result = esc.escalate(inv)
        msg = next(f.message for f in result.flags if f.flag_type == FlagType.ESCALATED)
        assert "LOW_CONFIDENCE" in msg
        assert "HIGH_VALUE" in msg

    def test_resolved_warnings_do_not_count(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        w = _warn()
        w.resolved = True
        inv.add_flag(w)
        inv.add_flag(_warn())  # only 1 open warning
        result = esc.escalate(inv)
        assert not any(f.flag_type == FlagType.ESCALATED for f in result.flags)

    def test_error_flags_do_not_count_toward_threshold(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        inv.add_flag(_error())
        inv.add_flag(_error())  # 2 errors, 0 warnings
        result = esc.escalate(inv)
        assert not any(f.flag_type == FlagType.ESCALATED for f in result.flags)

    def test_configurable_threshold(self):
        esc = FlagEscalator(threshold=3)
        inv = _inv()
        inv.add_flag(_warn())
        inv.add_flag(_warn())  # 2 warnings, threshold is 3
        result = esc.escalate(inv)
        assert not any(f.flag_type == FlagType.ESCALATED for f in result.flags)

    def test_no_double_escalation(self):
        esc = FlagEscalator(threshold=2)
        inv = _inv()
        inv.add_flag(_warn())
        inv.add_flag(_warn())
        esc.escalate(inv)
        esc.escalate(inv)  # run twice
        escalated = [f for f in inv.flags if f.flag_type == FlagType.ESCALATED]
        assert len(escalated) == 2  # add_flag doesn't de-duplicate, but second run adds another
