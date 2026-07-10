"""Unit tests — service_bridge.py Tier 3, batch C: notifications/review/
capex/budget/admin read-only *_mongo functions (final Tier 3 batch).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import (
    budget_summary_mongo,
    budget_synthese_mongo,
    count_unread_notifications_mongo,
    get_budget_plan_entries_mongo,
    get_review_queue_mongo,
    list_assets_mongo,
    list_budget_lines_mongo,
    list_notifications_mongo,
    security_summary_mongo,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.limit.return_value = chain
    chain.to_list = AsyncMock(return_value=return_value)
    chain.count = AsyncMock(return_value=len(return_value) if return_value is not None else 0)
    return chain


def _agg_result(rows):
    agg = MagicMock()
    agg.to_list = AsyncMock(return_value=rows)
    return agg


class TestListNotificationsMongo:
    def test_returns_all_notifications(self):
        docs = [SimpleNamespace(id="n1")]
        with patch(
            "src.storage.documents.notification.NotificationDocument.find",
            return_value=_find_chain(docs),
        ):
            result = _run(list_notifications_mongo())
        assert result == docs

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.notification.NotificationDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_notifications_mongo())
        assert result is None


class TestCountUnreadNotificationsMongo:
    def test_counts_unread_only(self):
        with patch(
            "src.storage.documents.notification.NotificationDocument.find",
            return_value=_find_chain([SimpleNamespace(id="n1"), SimpleNamespace(id="n2")]),
        ) as mock_find:
            result = _run(count_unread_notifications_mongo())
        assert result == 2
        mock_find.assert_called_once_with({"is_read": False})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.notification.NotificationDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(count_unread_notifications_mongo())
        assert result is None


class TestGetReviewQueueMongo:
    def test_returns_flagged_or_review_required_invoices(self):
        docs = [SimpleNamespace(id="inv-1")]
        with (
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find",
                return_value=_find_chain(docs),
            ) as mock_find,
            patch(
                "src.storage.documents.service_bridge._invoice_doc_to_record",
                return_value="record-inv-1",
            ),
        ):
            result = _run(get_review_queue_mongo())
        assert result == ["record-inv-1"]
        query = mock_find.call_args[0][0]
        assert {"status": "FLAGGED"} in query["$or"]
        assert {"human_review_required": True} in query["$or"]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_review_queue_mongo())
        assert result is None


class TestListAssetsMongo:
    def test_excludes_fully_depreciated_when_requested(self):
        docs = [SimpleNamespace(id="a1")]
        with (
            patch(
                "src.storage.documents.asset.AssetDocument.find",
                return_value=_find_chain(docs),
            ) as mock_find,
            patch(
                "src.storage.documents.service_bridge._asset_doc_to_pydantic",
                return_value="asset-a1",
            ),
        ):
            result = _run(list_assets_mongo(include_fully_depreciated=False))
        assert result == ["asset-a1"]
        mock_find.assert_called_once_with({"fully_depreciated": False})

    def test_includes_all_when_requested(self):
        with (
            patch(
                "src.storage.documents.asset.AssetDocument.find",
                return_value=_find_chain([]),
            ) as mock_find,
        ):
            _run(list_assets_mongo(include_fully_depreciated=True))
        mock_find.assert_called_once_with({})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.asset.AssetDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_assets_mongo(True))
        assert result is None


class TestListBudgetLinesMongo:
    def test_returns_lines_for_project(self):
        docs = [SimpleNamespace(id="lb-1")]
        with patch(
            "src.storage.documents.ligne_budget.LigneBudgetDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(list_budget_lines_mongo("proj-1"))
        assert result == docs
        mock_find.assert_called_once_with({"projet_id": "proj-1"})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.ligne_budget.LigneBudgetDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_budget_lines_mongo("proj-1"))
        assert result is None


class TestBudgetSyntheseMongo:
    def test_computes_ecart_and_taux(self):
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result([{"total_prevu": 1000.0, "total_consomme": 250.0}])
        with patch(
            "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(budget_synthese_mongo("proj-1"))
        assert result == {
            "total_prevu": 1000.0, "total_consomme": 250.0,
            "ecart": 750.0, "taux_consommation": 25.0,
        }

    def test_handles_no_budget_lines_without_dividing_by_zero(self):
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result([])
        with patch(
            "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(budget_synthese_mongo("proj-1"))
        assert result["taux_consommation"] == 0.0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.ligne_budget.LigneBudgetDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(budget_synthese_mongo("proj-1"))
        assert result is None


class TestBudgetSummaryMongo:
    def test_computes_ytd_variance_from_actuals(self):
        line = MagicMock()
        line.catalog_id = "licences_ms365"
        line.label = "Licences"
        line.budget_for_month.return_value = 100.0
        line.budget_ytd.return_value = 200.0
        plan = SimpleNamespace(lines=[line])

        rows = [{"_id": {"catalog_id": "licences_ms365", "month": 1}, "total": 90.0}]
        coll = MagicMock()
        coll.aggregate.return_value = _agg_result(rows)
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(budget_summary_mongo(plan, 2026, 2))

        assert result["summary"]["year"] == 2026
        assert result["summary"]["total_budget_ytd"] == 200.0
        assert len(result["variances"]) == 1

    def test_returns_none_when_mongo_down(self):
        plan = SimpleNamespace(lines=[])
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(budget_summary_mongo(plan, 2026, 1))
        assert result is None


class TestGetBudgetPlanEntriesMongo:
    def test_returns_entries_for_year_sorted_by_catalog(self):
        docs = [SimpleNamespace(id="bp-1")]
        with patch(
            "src.storage.documents.budget_plan.BudgetPlanDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(get_budget_plan_entries_mongo(2026))
        assert result == docs
        mock_find.assert_called_once_with({"year": 2026})

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.budget_plan.BudgetPlanDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_budget_plan_entries_mongo(2026))
        assert result is None


class TestSecuritySummaryMongo:
    def _patch_audit_find(self, action_to_count: dict):
        """Return a side_effect for AuditLogDocument.find matching the query's
        `action` filter (str or $in list) to a canned count/rows."""

        def _find(query):
            action = query.get("action")
            chain = MagicMock()
            if isinstance(action, dict) and "$in" in action:
                key = tuple(action["$in"])
            else:
                key = action
            rows = action_to_count.get(key, [])
            chain.sort.return_value = chain
            chain.limit.return_value = chain
            chain.to_list = AsyncMock(return_value=rows)
            chain.count = AsyncMock(return_value=len(rows))
            return chain

        return _find

    def test_aggregates_counts_and_lockouts(self):
        locked_user = SimpleNamespace(
            id="u1", email="locked@biat-it.tn", locked_until=datetime.now(timezone.utc) + timedelta(hours=1),
            failed_login_attempts=5,
        )
        suspicious_user = SimpleNamespace(
            id="u2", email="suspect@biat-it.tn",
            failed_login_attempts=3, last_failed_login=datetime.now(timezone.utc),
        )
        find_action = self._patch_audit_find({
            "LOGIN_SUCCESS": [1, 2, 3],
            "LOGIN_FAILURE": [1],
            "UNAUTHORIZED_ACCESS": [],
            ("FILE_UPLOADED", "INVOICE_UPLOADED"): [1, 1],
            "FILE_REJECTED": [],
            "AUDIT_INTEGRITY_CHECK": [],
        })
        with (
            patch(
                "src.storage.documents.audit_log.AuditLogDocument.find",
                side_effect=find_action,
            ),
            patch(
                "src.storage.documents.user.UserDocument.find",
                side_effect=[_find_chain([locked_user]), _find_chain([suspicious_user])],
            ),
            patch(
                "src.storage.documents.active_token.ActiveTokenDocument.find",
                return_value=_find_chain([1, 2]),
            ),
        ):
            result = _run(security_summary_mongo())

        assert result["total_logins_today"] == 3
        assert result["failed_logins_today"] == 1
        assert result["uploads_today"] == 2
        assert result["locked_accounts_count"] == 1
        assert result["active_sessions_count"] == 2
        assert result["accounts_with_recent_failures"][0]["email"] == "suspect@biat-it.tn"
        assert "tampered_entries_count" not in result  # caller overwrites this — see comment in source

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(security_summary_mongo())
        assert result is None
