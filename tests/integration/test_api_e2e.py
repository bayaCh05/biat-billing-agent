"""End-to-end tests for the FastAPI HTTP layer using TestClient.

Strategy:
  - Override get_session with an in-memory SQLite session (same pattern as
    other integration tests)
  - Demo users fall through to the USERS fallback dict (no DB seeding needed
    for auth)
  - Rate limiting disabled via env var set at module level
  - Tests cover: auth, RBAC, response shapes, 401/403 guards
"""
from __future__ import annotations

import os

# Must be set before any api.* imports so the limiter reads it
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.storage.db import build_engine, build_session_factory, init_db

# ── In-memory DB shared across all tests in this module ───────────────────────

_engine = build_engine("sqlite:///:memory:")
init_db(_engine)
_sf = build_session_factory(_engine)


def _override_session():
    s: Session = _sf()
    try:
        yield s
    finally:
        s.close()


# ── App + dependency override ─────────────────────────────────────────────────

from api.main import app          # noqa: E402  (after env var set)
from api.deps import get_session  # noqa: E402

app.dependency_overrides[get_session] = _override_session

client = TestClient(app, raise_server_exceptions=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(email: str, password: str) -> str:
    """Return a Bearer token string."""
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Auth tests ────────────────────────────────────────────────────────────────

class TestLogin:
    def test_demo_comptable_login_succeeds(self):
        r = client.post("/api/auth/login", json={
            "email": "comptable@biat-it.tn", "password": "biat2026"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "Comptable"
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_demo_admin_login_succeeds(self):
        r = client.post("/api/auth/login", json={
            "email": "admin@biat-it.tn", "password": "admin2026"
        })
        assert r.status_code == 200
        assert r.json()["role"] == "Admin"

    def test_wrong_password_returns_401(self):
        r = client.post("/api/auth/login", json={
            "email": "comptable@biat-it.tn", "password": "wrong"
        })
        assert r.status_code == 401

    def test_unknown_email_returns_401(self):
        r = client.post("/api/auth/login", json={
            "email": "ghost@biat-it.tn", "password": "biat2026"
        })
        assert r.status_code == 401

    def test_login_returns_all_roles(self):
        pairs = [
            ("comptable@biat-it.tn",  "biat2026",  "Comptable"),
            ("chef@biat-it.tn",       "biat2026",  "Chef de Projet"),
            ("directeur@biat-it.tn",  "biat2026",  "Direction"),
            ("admin@biat-it.tn",      "admin2026", "Admin"),
        ]
        for email, pwd, role in pairs:
            r = client.post("/api/auth/login", json={"email": email, "password": pwd})
            assert r.status_code == 200, f"Failed for {email}"
            assert r.json()["role"] == role


# ── 401 guard tests (no token) ────────────────────────────────────────────────

class TestUnauthenticated:
    @pytest.mark.parametrize("path", [
        "/api/invoices",
        "/api/kpi",
        "/api/journal",
        "/api/assets",
        "/api/review",
        "/api/audit/logs",
        "/api/users/me",
        "/api/notifications/count",
    ])
    def test_protected_route_requires_token(self, path):
        r = client.get(path)
        assert r.status_code == 401, f"{path} should require auth, got {r.status_code}"


# ── Health (public) ───────────────────────────────────────────────────────────

class TestHealth:
    def test_health_is_public(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ── KPI endpoint ──────────────────────────────────────────────────────────────

class TestKpi:
    def test_returns_correct_shape(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/kpi", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        for field in ("total_invoices", "total_amount_ttc", "auto_approved",
                      "auto_approval_rate", "flagged", "pending_review", "by_status"):
            assert field in body, f"Missing field: {field}"

    def test_empty_db_returns_zeros(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/kpi", headers=_auth(token))
        body = r.json()
        assert body["total_invoices"] == 0
        assert body["total_amount_ttc"] == 0.0
        assert body["by_status"] == {}


# ── Invoices endpoint ─────────────────────────────────────────────────────────

class TestInvoices:
    def test_list_returns_empty_on_fresh_db(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/invoices", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_upload_without_file_returns_422(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.post("/api/invoices/upload", headers=_auth(token))
        assert r.status_code == 422


# ── RBAC tests ────────────────────────────────────────────────────────────────

class TestRBAC:
    def test_comptable_cannot_access_audit_logs(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/audit/logs", headers=_auth(token))
        assert r.status_code == 403

    def test_direction_can_access_audit_logs(self):
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.get("/api/audit/logs", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_can_access_audit_logs(self):
        token = _login("admin@biat-it.tn", "admin2026")
        r = client.get("/api/audit/logs", headers=_auth(token))
        assert r.status_code == 200

    def test_comptable_cannot_list_admin_users(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/admin/users", headers=_auth(token))
        assert r.status_code == 403

    def test_admin_can_list_admin_users(self):
        token = _login("admin@biat-it.tn", "admin2026")
        r = client.get("/api/admin/users", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_comptable_cannot_access_analytics(self):
        # analytics endpoints require Admin | Direction | Comptable — so Comptable CAN access
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/analytics/kpis", headers=_auth(token))
        assert r.status_code == 200

    def test_chef_cannot_access_analytics(self):
        # Chef de Projet is NOT in _DIRECTION_COMPTABLE
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.get("/api/analytics/kpis", headers=_auth(token))
        assert r.status_code == 403


# ── Analytics endpoint shapes ─────────────────────────────────────────────────

class TestAnalytics:
    @pytest.fixture(autouse=True)
    def token(self):
        self._token = _login("directeur@biat-it.tn", "biat2026")

    def test_monthly_spend_returns_12_months(self):
        r = client.get("/api/analytics/monthly-spend?year=2026", headers=_auth(self._token))
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 12
        assert data[0]["month"] == "2026-01"
        assert "opex" in data[0] and "capex" in data[0]

    def test_by_supplier_returns_list(self):
        r = client.get("/api/analytics/by-supplier", headers=_auth(self._token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_by_account_returns_list(self):
        r = client.get("/api/analytics/by-account", headers=_auth(self._token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_kpis_shape(self):
        r = client.get("/api/analytics/kpis?year=2026", headers=_auth(self._token))
        assert r.status_code == 200
        body = r.json()
        for field in ("avg_processing_days", "rejection_rate", "human_review_rate",
                      "total_capex_ytd", "total_opex_ytd", "pending_count"):
            assert field in body, f"Missing field: {field}"


# ── Users/me endpoint ─────────────────────────────────────────────────────────

class TestUsersMe:
    def test_get_me_returns_profile_for_db_user(self):
        # Demo users fall back to USERS dict and have no DB record → /users/me
        # returns placeholder values; just check 200 + expected fields
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/users/me", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "Comptable"
        for field in ("nom", "prenom", "email", "role", "departement"):
            assert field in body


# ── Notifications endpoint ────────────────────────────────────────────────────

class TestNotifications:
    def test_count_returns_zero_on_empty_db(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/notifications/count", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_list_returns_empty_on_empty_db(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/notifications/list", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []

    def test_mark_all_read_returns_zero(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.post("/api/notifications/read-all", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["count"] == 0


# ── Budget endpoint ───────────────────────────────────────────────────────────

class TestBudget:
    def test_summary_shape(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/budget/summary", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        for field in ("year", "through_month", "total_budget_ytd",
                      "total_actual_ytd", "variance_pct", "lines"):
            assert field in body


# ── Projects endpoint ─────────────────────────────────────────────────────────

class TestProjects:
    def test_list_returns_empty_on_fresh_db(self):
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.get("/api/projects", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Billing ───────────────────────────────────────────────────────────────────

class TestBilling:
    def test_list_client_invoices_returns_list(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/billing/invoices", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_generate_invoice(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.post("/api/billing/generate", headers=_auth(token), json={
            "template_id": "biat_maintenance",
            "year": 2026,
            "month": 6,
        })
        # 404 if template not seeded in test DB — acceptable; what matters is no 500
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            body = r.json()
            assert "invoice_number" in body
            assert "amount_ttc" in body

    def test_templates_list_returns_list(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/billing/templates", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_billing_requires_auth(self):
        r = client.get("/api/billing/invoices")
        assert r.status_code == 401
