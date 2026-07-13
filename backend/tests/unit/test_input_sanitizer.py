"""Unit tests for api/security/input_sanitizer.py.

sanitize() had zero callers anywhere in the codebase at the time these tests
were written (grep across backend/api confirms it) — these tests validate
the function's own contract in isolation, not any wired-up endpoint.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.security.input_sanitizer import MAX_LENGTHS, sanitize


# ── Pass-through for empty/missing values ───────────────────────────────────

class TestEmptyValues:
    def test_none_returns_none(self):
        assert sanitize(None, "titre") is None

    def test_empty_string_returns_empty_string(self):
        assert sanitize("", "titre") == ""

    def test_empty_string_skips_length_and_forbidden_checks(self):
        # "" is falsy, so this must not raise even though "" would otherwise
        # be scrutinized against MAX_LENGTHS/_FORBIDDEN.
        assert sanitize("", "unknown_field_not_in_max_lengths") == ""


# ── Length validation ────────────────────────────────────────────────────────

class TestLengthValidation:
    def test_value_within_known_field_limit_is_accepted(self):
        assert sanitize("x" * 200, "titre") == "x" * 200

    def test_value_exceeding_known_field_limit_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            sanitize("x" * 201, "titre")
        assert exc_info.value.status_code == 422
        assert "titre" in exc_info.value.detail
        assert "200" in exc_info.value.detail

    def test_value_exactly_at_limit_is_accepted(self):
        # Boundary: len == max_len must pass (only len > max_len raises).
        assert sanitize("x" * MAX_LENGTHS["email"], "email") == "x" * MAX_LENGTHS["email"]

    def test_value_one_over_limit_raises(self):
        with pytest.raises(HTTPException):
            sanitize("x" * (MAX_LENGTHS["email"] + 1), "email")

    def test_unknown_field_uses_default_1000_limit(self):
        assert sanitize("x" * 1000, "some_unmapped_field") == "x" * 1000
        with pytest.raises(HTTPException) as exc_info:
            sanitize("x" * 1001, "some_unmapped_field")
        assert "1000" in exc_info.value.detail

    @pytest.mark.parametrize("field_name,limit", list(MAX_LENGTHS.items()))
    def test_each_declared_field_enforces_its_own_limit(self, field_name, limit):
        assert sanitize("a" * limit, field_name) == "a" * limit
        with pytest.raises(HTTPException):
            sanitize("a" * (limit + 1), field_name)


# ── Forbidden-content validation ────────────────────────────────────────────

class TestForbiddenContent:
    @pytest.mark.parametrize("payload", [
        "<script>alert(1)</script>",
        "javascript:alert(1)",
        "data:text/html,<h1>hi</h1>",
        "'; DROP TABLE users; --",
        "DELETE FROM invoices WHERE 1=1",
        "value -- trailing sql comment",
        "/* sql block comment */",
    ])
    def test_forbidden_pattern_raises_422(self, payload):
        with pytest.raises(HTTPException) as exc_info:
            sanitize(payload, "description")
        assert exc_info.value.status_code == 422
        assert "description" in exc_info.value.detail

    def test_forbidden_pattern_check_is_case_insensitive(self):
        with pytest.raises(HTTPException):
            sanitize("<SCRIPT>alert(1)</SCRIPT>", "description")
        with pytest.raises(HTTPException):
            sanitize("drop table users", "description")

    def test_clean_value_is_not_rejected(self):
        assert sanitize("Facture serveur Dell R740", "description") == "Facture serveur Dell R740"

    def test_length_is_checked_before_forbidden_content(self):
        # A too-long value containing a forbidden pattern must fail on length
        # first (422 with the length message), since the length check runs
        # before the forbidden-pattern loop.
        payload = ("<script>" + "a" * 300)
        with pytest.raises(HTTPException) as exc_info:
            sanitize(payload, "titre")
        assert "trop long" in exc_info.value.detail


# ── Stripping ────────────────────────────────────────────────────────────────

class TestStripping:
    def test_leading_and_trailing_whitespace_is_stripped(self):
        assert sanitize("  hello world  ", "titre") == "hello world"

    def test_internal_whitespace_is_preserved(self):
        assert sanitize("  hello   world  ", "titre") == "hello   world"
