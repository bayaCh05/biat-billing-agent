"""Regression tests — ML retrain job/endpoint must read invoice data from
Mongo, not the SQLAlchemy repository.

Before this fix, scheduler.py::_job_retrain_classifier and
ai.py::retrain_model both called components.repository.count_by_status()/
retrain_from_repo(components.repository) — the SQLAlchemy repository,
which only ever sees a frozen migration-time snapshot since invoices
uploaded through the real API (AIOrchestrator) land in Mongo only. These
tests prove components.repository is never touched anymore, and that the
Mongo repository is what actually gets passed to retrain_from_repo().
"""
from __future__ import annotations

from unittest.mock import MagicMock

_ABOVE_THRESHOLD_COUNTS = {"VALIDATED": 60, "EXPORTED": 0, "PAID": 0, "JOURNALED": 0}
_BELOW_THRESHOLD_COUNTS = {"VALIDATED": 1}


class TestSchedulerRetrainJob:
    def test_uses_mongo_repo_and_never_touches_sqlalchemy_repository(self, monkeypatch):
        fake_components = MagicMock()
        monkeypatch.setattr("api.deps.get_components", lambda: fake_components)

        fake_mongo_repo = MagicMock()
        fake_mongo_repo.count_by_status.return_value = _ABOVE_THRESHOLD_COUNTS
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_mongo_repo,
        )

        from api.scheduler import _job_retrain_classifier
        _job_retrain_classifier()

        fake_mongo_repo.count_by_status.assert_called_once()
        fake_components.coder.ml_classifier.retrain_from_repo.assert_called_once_with(fake_mongo_repo)
        fake_components.repository.count_by_status.assert_not_called()
        fake_components.repository.get_by_status.assert_not_called()
        fake_components.close.assert_called_once()

    def test_skips_retrain_below_threshold(self, monkeypatch):
        fake_components = MagicMock()
        monkeypatch.setattr("api.deps.get_components", lambda: fake_components)

        fake_mongo_repo = MagicMock()
        fake_mongo_repo.count_by_status.return_value = _BELOW_THRESHOLD_COUNTS
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_mongo_repo,
        )

        from api.scheduler import _job_retrain_classifier
        _job_retrain_classifier()

        fake_components.coder.ml_classifier.retrain_from_repo.assert_not_called()
        fake_components.close.assert_called_once()


class TestRetrainEndpoint:
    def test_uses_mongo_repo_and_never_touches_sqlalchemy_repository(self, monkeypatch):
        fake_components = MagicMock()
        monkeypatch.setattr("api.routers.ai.get_components", lambda: fake_components)

        fake_mongo_repo = MagicMock()
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_mongo_repo,
        )

        from api.routers.ai import retrain_model
        result = retrain_model()

        assert result == {"status": "ok", "message": "Modèle ML réentraîné avec succès."}
        fake_components.coder.ml_classifier.retrain_from_repo.assert_called_once_with(fake_mongo_repo)
        fake_components.repository.count_by_status.assert_not_called()
        fake_components.close.assert_called_once()
