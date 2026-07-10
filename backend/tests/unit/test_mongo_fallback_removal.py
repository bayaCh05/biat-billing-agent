"""Unit tests — post-audit follow-up (item 2/4): silent SQLite fallback removal.

roadmap, risks, livrables, notifications, and budget's get_budget_plan_entries
write Mongo-only now (see CLAUDE.md "MongoDB Migration Status") — their old
"if Mongo unavailable, fall back to SQLite" read paths could only ever have
served permanently stale data, so the fallback was deleted outright. When
Mongo is unavailable these endpoints must now return an empty/neutral result
AND log a clear warning — never silently return old data, never crash.

review.py::get_review_queue is the one deliberate exception (the daemon still
writes invoices SQLite-only), so its fallback was kept — but must now also
log a warning when it triggers.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from api.routers import budget, livrables, notifications, review, risks, roadmap


def _run(coro):
    return asyncio.run(coro)


class TestSilentFallbacksRemoved:
    def test_list_roadmap_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.list_roadmap_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(roadmap.list_roadmap(annee=2026))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_list_roadmap_with_risks_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.list_roadmap_with_risks_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(roadmap.list_roadmap_with_risks(annee=2026))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_list_risks_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.list_risks_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(risks.list_risks())

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_risk_summary_returns_neutral_shape_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.risk_summary_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(risks.risk_summary())

        assert result["total_active"] == 0
        assert result["by_criticite"] == {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0}
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_risks_par_projet_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.risks_par_projet_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(risks.risks_par_projet(_=None))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_risks_for_roadmap_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.risks_for_roadmap_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(risks.risks_for_roadmap("feuille-1"))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_risks_for_project_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.risks_for_project_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(risks.risks_for_project("projet-1"))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_list_livrables_returns_empty_and_warns_when_mongo_down(self, caplog):
        with patch(
            "src.storage.documents.service_bridge.list_livrables_mongo",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(logging.WARNING):
            result = _run(livrables.list_livrables("phase-1"))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_notifications_count_returns_zero_and_warns_when_mongo_down(self, caplog):
        session = MagicMock()
        with (
            patch(
                "src.storage.documents.service_bridge.sync_flagged_invoices_mirrored",
                new=AsyncMock(),
            ),
            patch(
                "src.storage.documents.service_bridge.count_unread_notifications_mongo",
                new=AsyncMock(return_value=None),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = _run(notifications.get_count(session=session))

        assert result.count == 0
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_list_notifications_returns_empty_and_warns_when_mongo_down(self, caplog):
        session = MagicMock()
        with (
            patch(
                "src.storage.documents.service_bridge.sync_flagged_invoices_mirrored",
                new=AsyncMock(),
            ),
            patch(
                "src.storage.documents.service_bridge.list_notifications_mongo",
                new=AsyncMock(return_value=None),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = _run(notifications.list_notifications(session=session))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)

    def test_get_budget_plan_entries_returns_empty_and_warns_when_mongo_down(self, caplog):
        with (
            patch(
                "src.storage.documents.service_bridge.seed_budget_plan_from_yaml_native",
                new=AsyncMock(),
            ),
            patch(
                "src.storage.documents.service_bridge.get_budget_plan_entries_mongo",
                new=AsyncMock(return_value=None),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = _run(budget.get_budget_plan_entries(year=2026))

        assert result == []
        assert any("MongoDB indisponible" in r.message for r in caplog.records)


class TestReviewQueueFallbackKeptButWarns:
    """The one deliberate exception: fallback stays (daemon writes SQLite-only
    invoices), but it must log loudly when it triggers instead of being silent."""

    def test_falls_back_to_sqlite_and_warns_when_mongo_down(self, caplog):
        session = MagicMock()
        fake_repo = MagicMock()
        fake_repo.get_review_queue.return_value = ["fake-invoice"]

        with (
            patch(
                "src.storage.documents.service_bridge.get_review_queue_mongo",
                new=AsyncMock(return_value=None),
            ),
            patch("api.routers.review.InvoiceRepository", return_value=fake_repo),
            patch("api.schemas.InvoiceSummary.from_record", side_effect=lambda inv: inv),
            caplog.at_level(logging.WARNING),
        ):
            result = _run(review.get_review_queue(session=session))

        assert result == ["fake-invoice"]
        fake_repo.get_review_queue.assert_called_once()
        assert any("MongoDB indisponible" in r.message for r in caplog.records)
