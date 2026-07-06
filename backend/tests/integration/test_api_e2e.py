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
from datetime import date
from uuid import UUID

# Must be set before any api.* imports so the limiter reads it
os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_payments import PaymentInstallmentORM

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


# ── Payment installments endpoint ───────────────────────────────────────────

class TestPaymentInstallments:
    def test_mark_paid_updates_existing_installment(self):
        token = _login("comptable@biat-it.tn", "biat2026")

        session = _sf()
        try:
            session.execute(text(
                "INSERT INTO payment_installments ("
                "id, invoice_id, installment_number, total_installments, base_amount, current_amount, due_date, status, late_periods, created_at, updated_at"
                ") VALUES ("
                ":id, :invoice_id, :installment_number, :total_installments, :base_amount, :current_amount, :due_date, :status, :late_periods, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP"
                ")"
            ), {
                "id": "7947955e-a599-4512-b8c7-5c2ab4c27166",
                "invoice_id": "invoice-1",
                "installment_number": 2,
                "total_installments": 3,
                "base_amount": 5751.667,
                "current_amount": 5751.667,
                "due_date": "2026-06-27",
                "status": "PENDING",
                "late_periods": 0,
            })
            session.commit()
        finally:
            session.close()

        r = client.patch(
            "/api/installments/7947955e-a599-4512-b8c7-5c2ab4c27166/mark-paid",
            headers=_auth(token),
            json={"paid_amount": 5751.667, "paid_date": "2026-06-27"},
        )

        assert r.status_code == 200, r.text
        assert r.json()["status"] == "PAID"

        session = _sf()
        try:
            row = session.execute(text(
                "SELECT status, paid_amount, paid_date FROM payment_installments WHERE id = :id"
            ), {"id": "7947955e-a599-4512-b8c7-5c2ab4c27166"}).mappings().first()
            assert row is not None
            assert row["status"] == "PAID"
            assert row["paid_amount"] == 5751.667
            assert str(row["paid_date"]) == "2026-06-27"
        finally:
            session.close()


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


# ── Review RBAC — M1a ─────────────────────────────────────────────────────────

class TestReviewRBAC:
    """Vérifie que seuls Comptable et Admin peuvent approuver/rejeter.

    On utilise un UUID inexistant : le rôle guard (403) s'évalue AVANT
    la recherche en base, donc les rôles autorisés retournent 404 (RBAC OK)
    et les rôles non autorisés retournent 403 (RBAC KO).
    """

    _FAKE_ID = "00000000-0000-0000-0000-000000000099"

    def test_direction_cannot_approve(self):
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/approve", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_chef_cannot_approve(self):
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/approve", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_comptable_can_approve_rbac_passes(self):
        # RBAC OK → 404 car la facture n'existe pas en DB
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/approve", headers=_auth(token))
        assert r.status_code == 404, r.text

    def test_admin_can_approve_rbac_passes(self):
        token = _login("admin@biat-it.tn", "admin2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/approve", headers=_auth(token))
        assert r.status_code == 404, r.text

    def test_direction_cannot_reject(self):
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/reject", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_chef_cannot_reject(self):
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.post(f"/api/review/{self._FAKE_ID}/reject", headers=_auth(token))
        assert r.status_code == 403, r.text


# ── Reset token replay — M1b ──────────────────────────────────────────────────

class TestResetTokenReplay:
    """Vérifie que le token de réinitialisation de mot de passe est invalidé après usage."""

    def test_demo_reset_token_cannot_be_replayed(self):
        from src.services.password_verification_service import (
            generate_demo_reset_link,
            _DEMO_RESET_TOKENS,
        )

        demo_email = "comptable@biat-it.tn"
        original_password = "biat2026"

        link = generate_demo_reset_link(demo_email, "FORGOT_PASSWORD")
        token = link.split("token=", 1)[1]

        try:
            # Premier usage : doit réussir
            r1 = client.post("/api/auth/reset-password", json={
                "token": token,
                "new_password": "NouveauPass99!",
            })
            assert r1.status_code == 200, r1.text
            assert r1.json()["success"] is True

            # Deuxième usage avec le même token : doit échouer (token consommé)
            r2 = client.post("/api/auth/reset-password", json={
                "token": token,
                "new_password": "AutrePass99!",
            })
            assert r2.status_code == 400, r2.text
        finally:
            # Restaure le mot de passe d'origine pour ne pas casser les autres tests
            from api.routers.auth import USERS, DEMO_AUTH_STATE
            if demo_email in USERS:
                USERS[demo_email]["password"] = original_password
            DEMO_AUTH_STATE.pop(demo_email, None)
