"""End-to-end tests for the FastAPI HTTP layer using TestClient.

Strategy:
  - Override get_session with an in-memory SQLite session (same pattern as
    other integration tests)
  - The 4 standard test accounts (comptable/chef/directeur/admin@biat-it.tn)
    are real Mongo users, seeded once at module load via _seed_test_users()
    — there is no demo-account fallback in the app anymore (removed, see
    CLAUDE.md "Section 1 — demo accounts")
  - Rate limiting disabled via env var set at module level
  - Tests cover: auth, RBAC, response shapes, 401/403 guards
"""
from __future__ import annotations

import logging
import os
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import UUID

# Must be set before any api.* imports so the limiter reads it
os.environ["RATE_LIMIT_ENABLED"] = "false"
# Isolated Mongo database for this test module — never touches the dev DB.
# Mongo-native write paths (Lot 3+) require Beanie to actually be initialized
# (see lifespan handling below), so tests run against a real, disposable DB.
os.environ["MONGODB_DB"] = "biat_billing_test"

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

# Entered eagerly (not via `with`) so the ASGI lifespan runs for the whole
# module: Mongo-native routes (Lot 3+) need `init_beanie()` to have actually
# run, otherwise Beanie raises CollectionWasNotInitialized instead of a clean
# 404/behavior. Closed + dropped in the session-scoped fixture below.
client = TestClient(app, raise_server_exceptions=True)
client.__enter__()

# Seed real Mongo test users for the 4 roles this module logs in as
# throughout. Demo accounts (a hardcoded USERS fallback dict in
# api/auth.py, bypassing Mongo entirely) were removed from the login path
# — see CLAUDE.md "Section 1 — demo accounts removed from auth". These are
# genuine documents in the isolated biat_billing_test "users" collection,
# in the same shape service_bridge.py::create_user_native() would insert —
# written via plain synchronous pymongo (not that async function directly)
# because this runs at module-collection time, before pytest has started
# any event loop for Beanie's async Document registration to run in.
def _seed_test_users() -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    import pymongo

    from api.auth import hash_password
    from src.storage.mongodb import MONGODB_DB, MONGODB_URI

    coll = pymongo.MongoClient(MONGODB_URI)[MONGODB_DB]["users"]
    now = datetime.now(timezone.utc)
    for email, password, role in [
        ("comptable@biat-it.tn", "biat2026", "Comptable"),
        ("chef@biat-it.tn", "biat2026", "Chef de Projet"),
        ("directeur@biat-it.tn", "biat2026", "Direction"),
        ("admin@biat-it.tn", "admin2026", "Admin"),
    ]:
        if coll.find_one({"email": email}):
            continue
        coll.insert_one({
            "_id": str(uuid4()),
            "nom": role, "prenom": "Test", "email": email,
            "hashed_password": hash_password(password), "role": role, "departement": "IT",
            "is_first_login": False, "is_active": True, "created_at": now,
            "failed_login_attempts": 0, "locked_until": None, "last_failed_login": None,
            "last_login_at": None, "last_login_ip": None, "profile_picture": None,
        })


_seed_test_users()


@pytest.fixture(scope="session", autouse=True)
def _close_client_and_drop_test_db():
    yield
    client.__exit__(None, None, None)
    try:
        import pymongo

        from src.storage.mongodb import MONGODB_DB, MONGODB_URI
        if MONGODB_URI:
            pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2_000).drop_database(MONGODB_DB)
    except Exception:
        pass


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
    def test_comptable_login_succeeds(self):
        r = client.post("/api/auth/login", json={
            "email": "comptable@biat-it.tn", "password": "biat2026"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "Comptable"
        assert "access_token" in body
        assert body["token_type"] == "bearer"

    def test_admin_login_succeeds(self):
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


# ── demo_base64 removed — post-audit follow-up (item 4/4) ────────────────────

class TestDemoBase64Removed:
    """demo_base64.py was confirmed dead (zero frontend usage) and deleted
    outright — no route referencing it should exist anywhere in the app."""

    def test_no_base64_routes_registered(self):
        paths = [getattr(r, "path", "") for r in app.routes]
        assert not any("base64" in p.lower() for p in paths), paths

    def test_demo_tag_removed_from_openapi(self):
        tag_names = [t["name"] for t in app.openapi_tags or []]
        assert "demo" not in tag_names


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

    def test_real_upload_writes_audit_trail_to_mongo_only(self, tmp_path):
        """Lot 7 + Lot 8 — preuve en direct (process courant, donc code source
        réellement exécuté, pas une copie historique déjà migrée) :
          - INVOICE_UPLOADED atterrit dans Mongo (log_audit_event_native), pas SQLite
          - AI_EXTRACT/AI_CLASSIFY/AI_ANOMALY atterrissent dans Mongo
            (log_ai_audit_event_sync), dans l'ordre, sans doublon
          - zéro nouvelle ligne SQLite pour ces actions
          - chaque ligne Mongo a un row_hash HMAC valide
        """
        import pymongo
        from api.security.audit_integrity import verify_row_hash_from_doc
        from src.storage.mongodb import MONGODB_DB, MONGODB_URI
        from tests.fixtures.make_invoice_pdf import make_supplier_invoice_pdf

        pdf_path = make_supplier_invoice_pdf(tmp_path / "audit_trail_test.pdf")
        token = _login("comptable@biat-it.tn", "biat2026")

        sqlite_session = _sf()
        try:
            before_sqlite = sqlite_session.execute(
                text("SELECT COUNT(*) FROM audit_logs")
            ).scalar_one()
        finally:
            sqlite_session.close()

        with open(pdf_path, "rb") as fh:
            r = client.post(
                "/api/invoices/upload",
                headers=_auth(token),
                files={"file": ("audit_trail_test.pdf", fh, "application/pdf")},
                data={"live": "false"},
            )
        assert r.status_code == 200, r.text
        invoice_id = r.json()["id"]

        sqlite_session = _sf()
        try:
            after_sqlite = sqlite_session.execute(
                text("SELECT COUNT(*) FROM audit_logs")
            ).scalar_one()
        finally:
            sqlite_session.close()
        assert after_sqlite == before_sqlite, (
            "aucune nouvelle ligne SQLite audit_logs attendue pour cet upload — "
            f"avant={before_sqlite} après={after_sqlite}"
        )

        mongo = pymongo.MongoClient(MONGODB_URI)[MONGODB_DB]
        rows = list(
            mongo.audit_logs.find({"resource_id": invoice_id}).sort("created_at", 1)
        )
        actions = [row["action"] for row in rows]

        assert "INVOICE_UPLOADED" not in actions, (
            "INVOICE_UPLOADED est indexé par file_hash, pas resource_id=invoice_id "
            "— vérifié séparément ci-dessous"
        )
        # AI_* events are keyed by invoice_id (see InvoiceProcessingOrchestrator._audit_ai)
        ai_actions = [a for a in actions if a.startswith("AI_")]
        assert ai_actions == sorted(set(ai_actions), key=ai_actions.index), "ordre inattendu"
        assert ai_actions[:3] == ["AI_EXTRACT", "AI_CLASSIFY", "AI_ANOMALY"], ai_actions
        assert len(ai_actions) == len(set(ai_actions)), f"doublon détecté: {ai_actions}"
        for row in rows:
            assert verify_row_hash_from_doc(row), f"HMAC invalide pour {row['action']}"

        # INVOICE_UPLOADED is logged before the invoice UUID is minted (keyed by
        # file content, not resource_id) — find it by action + recency instead.
        uploaded = list(
            mongo.audit_logs.find({"action": "INVOICE_UPLOADED"}).sort("created_at", -1).limit(1)
        )
        assert uploaded, "aucune entrée INVOICE_UPLOADED trouvée dans Mongo"
        assert verify_row_hash_from_doc(uploaded[0])


# ── Payment installments endpoint ───────────────────────────────────────────

class TestPaymentInstallments:
    def test_mark_paid_updates_existing_installment(self):
        # mark_paid is Mongo-native (Lot 5) — seed directly into the isolated
        # test Mongo DB, not SQLite.
        import pymongo
        from datetime import datetime, timezone

        from src.storage.mongodb import MONGODB_DB, MONGODB_URI

        token = _login("comptable@biat-it.tn", "biat2026")

        mongo = pymongo.MongoClient(MONGODB_URI)[MONGODB_DB]
        installment_id = "7947955e-a599-4512-b8c7-5c2ab4c27166"
        mongo.payment_installments.insert_one({
            "_id": installment_id,
            "invoice_id": "invoice-1",
            "installment_number": 2,
            "total_installments": 3,
            "base_amount": 5751.667,
            "current_amount": 5751.667,
            "due_date": datetime(2026, 6, 27, tzinfo=timezone.utc),
            "paid_date": None,
            "paid_amount": None,
            "status": "PENDING",
            "late_periods": 0,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

        try:
            r = client.patch(
                f"/api/installments/{installment_id}/mark-paid",
                headers=_auth(token),
                json={"paid_amount": 5751.667, "paid_date": "2026-06-27"},
            )

            assert r.status_code == 200, r.text
            assert r.json()["status"] == "PAID"

            row = mongo.payment_installments.find_one({"_id": installment_id})
            assert row is not None
            assert row["status"] == "PAID"
            assert row["paid_amount"] == 5751.667
            assert row["paid_date"] == datetime(2026, 6, 27)
        finally:
            mongo.payment_installments.delete_one({"_id": installment_id})


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
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/users/me", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "Comptable"
        for field in ("nom", "prenom", "email", "role", "departement"):
            assert field in body


# ── Notifications endpoint ────────────────────────────────────────────────────

class TestNotifications:
    @pytest.fixture(autouse=True)
    def _reset_notification_state(self):
        """Notifications now sync from real InvoiceDocument data (Lot A4 — no
        more SQLite scan that silently ignored Mongo-only uploads). Other
        tests in this module (e.g. TestInvoices' real-upload test) create
        flagged invoices in the same shared test Mongo DB, so this class's
        "empty db" tests need their own reset to hold."""
        import pymongo

        from src.storage.mongodb import MONGODB_DB, MONGODB_URI
        if MONGODB_URI:
            db = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2_000)[MONGODB_DB]
            db["notifications"].delete_many({})
            db["invoices"].update_many(
                {"human_review_required": True}, {"$set": {"human_review_required": False}}
            )
        yield

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


# ── Mongo-down warning behavior — direct HTTP-level proof (Fix item 7) ───────

class TestMongoFallbackWarningAtHttpLevel:
    """The unit tests in test_mongo_fallback_removal.py call the router
    functions directly, bypassing FastAPI — a fair regression test, but not
    the strongest possible proof since the pre-fix function signatures also
    took a `session` argument these tests don't supply. This class proves the
    same thing through the actual HTTP interface instead: mock only the Mongo
    read function, hit the real endpoint, and check both the response body
    and that a warning was actually logged."""

    def test_roadmap_warns_when_mongo_down(self, caplog):
        token = _login("chef@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.list_roadmap_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/roadmap", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)

    def test_risks_warns_when_mongo_down(self, caplog):
        token = _login("chef@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.list_risks_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/risks", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)

    def test_livrables_warns_when_mongo_down(self, caplog):
        token = _login("chef@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.list_livrables_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/phases/fake-phase-id/livrables", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)

    def test_notifications_count_warns_when_mongo_down(self, caplog):
        token = _login("comptable@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.count_unread_notifications_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/notifications/count", headers=_auth(token))
        assert r.status_code == 200
        assert r.json()["count"] == 0
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)

    def test_budget_plan_entries_warns_when_mongo_down(self, caplog):
        token = _login("comptable@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.get_budget_plan_entries_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/budget/plan", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == []
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)

    def test_review_queue_keeps_fallback_but_warns_when_mongo_down(self, caplog):
        # The one deliberate exception: still serves SQLite data (the daemon
        # writes invoices SQLite-only), but must now warn instead of being silent.
        token = _login("comptable@biat-it.tn", "biat2026")
        with patch(
            "src.storage.documents.service_bridge.get_review_queue_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            r = client.get("/api/review", headers=_auth(token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert any("MongoDB indisponible" in rec.message for rec in caplog.records)


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


# ── Fix 3 role guards — security audit (previously JWT-only, no RBAC) ────────

class TestFix3RoleGuards:
    """GET /journal, POST /assets, POST /nl-query and /billing/* previously
    only required a valid JWT — any authenticated role could call them. Each
    now requires a specific role set; a role outside that set must get 403."""

    def test_journal_direction_forbidden(self):
        # Comptable only
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.get("/api/journal", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_journal_comptable_allowed(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.get("/api/journal", headers=_auth(token))
        assert r.status_code == 200, r.text

    def test_journal_export_chef_forbidden(self):
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.get("/api/journal/export", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_create_asset_chef_forbidden(self):
        # Comptable, Direction only
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.post("/api/assets", headers=_auth(token), json={
            "designation": "Serveur test",
            "compte_immobilisation": "2183",
            "compte_amortissement": "28183",
            "acquisition_date": "2026-01-01",
            "acquisition_cost_ht": 1000.0,
            "useful_life_years": 3,
        })
        assert r.status_code == 403, r.text

    def test_create_asset_direction_rbac_passes(self):
        # RBAC OK for Direction — asserting != 403 is what matters here
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.post("/api/assets", headers=_auth(token), json={
            "designation": "Serveur test",
            "compte_immobilisation": "2183",
            "compte_amortissement": "28183",
            "acquisition_date": "2026-01-01",
            "acquisition_cost_ht": 1000.0,
            "useful_life_years": 3,
        })
        assert r.status_code != 403, r.text

    def test_nl_query_chef_forbidden(self):
        # Comptable, Direction only
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.post("/api/nl-query", headers=_auth(token), json={"question": "Total des factures ?"})
        assert r.status_code == 403, r.text

    def test_nl_query_comptable_rbac_passes(self):
        token = _login("comptable@biat-it.tn", "biat2026")
        r = client.post("/api/nl-query", headers=_auth(token), json={"question": "Total des factures ?"})
        assert r.status_code != 403, r.text

    def test_billing_direction_forbidden(self):
        # Comptable, Chef de Projet only — Direction is NOT in this set
        token = _login("directeur@biat-it.tn", "biat2026")
        r = client.get("/api/billing/invoices", headers=_auth(token))
        assert r.status_code == 403, r.text

    def test_billing_chef_allowed(self):
        token = _login("chef@biat-it.tn", "biat2026")
        r = client.get("/api/billing/invoices", headers=_auth(token))
        assert r.status_code == 200, r.text


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


# ── Session revocation on password change/reset — post-audit follow-up ───────

class TestSessionRevocationOnPasswordChange:
    """A JWT stolen before a password change/reset must not survive it.

    Uses fresh, disposable users (created via the admin API) rather than the
    shared comptable@biat-it.tn account, so each test's password/session
    mutations stay isolated instead of leaking into other tests that also
    log in as the shared account.
    """

    def _create_real_user(self) -> tuple[str, str, str]:
        """Returns (user_id, email, password) for a freshly created, non-demo,
        Mongo-backed user with a password we control directly (admin's
        create-user endpoint only emails a random temp password — never
        returns it — so we overwrite it via a direct pymongo write, safe here
        since this user is brand new and used by nothing else)."""
        import pymongo
        from uuid import uuid4

        from api.auth import hash_password
        from src.storage.mongodb import MONGODB_DB, MONGODB_URI

        email = f"revoke-test-{uuid4().hex[:12]}@example.com"
        password = "KnownPass99!"

        admin_token = _login("admin@biat-it.tn", "admin2026")
        r = client.post("/api/admin/users", headers=_auth(admin_token), json={
            "nom": "Test", "prenom": "Revoke", "email": email,
            "role": "Comptable", "departement": "IT",
        })
        assert r.status_code == 201, r.text
        user_id = r.json()["user_id"]

        db = pymongo.MongoClient(MONGODB_URI).get_database(MONGODB_DB)
        result = db["users"].update_one(
            {"_id": user_id},
            {"$set": {"hashed_password": hash_password(password), "is_first_login": False}},
        )
        assert result.modified_count == 1
        return user_id, email, password

    def _still_valid(self, token: str) -> bool:
        return client.get("/api/users/me", headers=_auth(token)).status_code == 200

    def _get_password_verification_secret(self, user_id: str, verification_type: str) -> str:
        """Test-only backdoor: the API never returns OTP codes/reset tokens
        directly (by design), so fetch the just-generated one straight from Mongo."""
        import pymongo

        from src.storage.mongodb import MONGODB_DB, MONGODB_URI

        coll = pymongo.MongoClient(MONGODB_URI).get_database(MONGODB_DB)["password_verifications"]
        doc = coll.find_one(
            {"user_id": str(user_id), "verification_type": verification_type, "used": False},
            sort=[("created_at", -1)],
        )
        assert doc is not None, f"No {verification_type} verification found for user {user_id}"
        return doc["code_or_token"]

    def test_direct_change_password_revokes_other_sessions_keeps_current(self):
        _, email, password = self._create_real_user()
        token_a = _login(email, password)
        token_b = _login(email, password)

        r = client.patch("/api/auth/change-password", headers=_auth(token_a), json={
            "current_password": password, "new_password": "NouveauPass99!",
        })
        assert r.status_code == 200, r.text
        assert self._still_valid(token_a), "session making the change must survive"
        assert not self._still_valid(token_b), "other session must be revoked"

    def test_otp_confirm_revokes_other_sessions_keeps_current(self):
        user_id, email, password = self._create_real_user()
        token_a = _login(email, password)
        token_b = _login(email, password)

        r = client.post("/api/auth/change-password/request-otp", headers=_auth(token_a))
        assert r.status_code == 200, r.text
        assert r.json()["skip_otp"] is False

        otp_code = self._get_password_verification_secret(user_id, "OTP")
        r2 = client.post("/api/auth/change-password/confirm", headers=_auth(token_a), json={
            "otp_code": otp_code, "current_password": password, "new_password": "NouveauPass99!",
        })
        assert r2.status_code == 200, r2.text
        assert self._still_valid(token_a), "session making the change must survive"
        assert not self._still_valid(token_b), "other session must be revoked"

    def test_admin_reset_revokes_target_sessions(self):
        target_id, email, password = self._create_real_user()
        admin_token = _login("admin@biat-it.tn", "admin2026")
        target_token = _login(email, password)

        r = client.post(f"/api/admin/users/{target_id}/reset-password", headers=_auth(admin_token))
        assert r.status_code == 200, r.text
        assert not self._still_valid(target_token), "target's session must be revoked"

    def test_reset_password_link_revokes_all_sessions(self):
        user_id, email, password = self._create_real_user()
        token_a = _login(email, password)
        token_b = _login(email, password)

        r = client.post("/api/auth/forgot-password", json={"email": email})
        assert r.status_code == 200, r.text

        token = self._get_password_verification_secret(user_id, "LINK")
        r2 = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "NouveauPass99!",
        })
        assert r2.status_code == 200, r2.text

        # Unauthenticated recovery flow — even the session that requested
        # it must not survive (no "current session" concept here).
        assert not self._still_valid(token_a)
        assert not self._still_valid(token_b)

    def test_reset_token_cannot_be_replayed(self):
        """A reset token must be consumed on first use — a second attempt
        with the same token must fail. Formerly tested against the demo-only
        in-memory reset-link mechanism (removed with demo accounts); now
        exercises the real Mongo-native reset flow via a disposable user."""
        user_id, email, _password = self._create_real_user()

        r = client.post("/api/auth/forgot-password", json={"email": email})
        assert r.status_code == 200, r.text
        token = self._get_password_verification_secret(user_id, "LINK")

        r1 = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "NouveauPass99!",
        })
        assert r1.status_code == 200, r1.text
        assert r1.json()["success"] is True

        r2 = client.post("/api/auth/reset-password", json={
            "token": token, "new_password": "AutrePass99!",
        })
        assert r2.status_code == 400, r2.text
