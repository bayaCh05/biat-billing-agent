"""Unit tests — sync_mongo_repository.journal_consistency_check_sync().

consistency_score used to be effectively binary (1.0 or 0.0) regardless of
how many journal entries were actually unbalanced, because total_checked
counted aggregation query *runs* (always 1), not journal entries. Fixed to
be proportional to the real entry count — see the function's own comment.
No real MongoDB connection: _get_db() is monkeypatched with an in-memory
fake, matching test_sync_mongo_invoice_status.py's convention.
"""
from __future__ import annotations

import pytest

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import journal_consistency_check_sync


class _FakeJournalCollection:
    """total_count = how many entries exist; unbalanced_rows = what the real
    Mongo aggregation pipeline would have returned (already pre-filtered to
    diff > 0.005) — the fake doesn't re-implement Mongo's aggregation
    semantics, it just stands in for its result, matching the sibling
    test file's convention (test_sync_mongo_invoice_status.py)."""

    def __init__(self, total_count: int, unbalanced_rows: list[dict]):
        self._total_count = total_count
        self._unbalanced_rows = unbalanced_rows

    def count_documents(self, _query: dict) -> int:
        return self._total_count

    def aggregate(self, _pipeline: list[dict]) -> list[dict]:
        return self._unbalanced_rows


def _patch(monkeypatch, coll: _FakeJournalCollection) -> None:
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"journal_entries": coll})


class TestJournalConsistencyCheckSync:
    def test_all_balanced_scores_1(self, monkeypatch):
        _patch(monkeypatch, _FakeJournalCollection(total_count=20, unbalanced_rows=[]))
        result = journal_consistency_check_sync()
        assert result["consistency_score"] == 1.0
        assert result["total_checked"] == 20
        assert result["issues"] == []

    def test_score_is_proportional_not_binary(self, monkeypatch):
        """The bug this fixes: 2 unbalanced out of 20 must NOT collapse to
        the same score as "everything unbalanced" — both used to score 0.0."""
        rows = [{"_id": "a", "reference": "JE-1"}, {"_id": "b", "reference": "JE-2"}]
        _patch(monkeypatch, _FakeJournalCollection(total_count=20, unbalanced_rows=rows))
        result = journal_consistency_check_sync()
        assert result["consistency_score"] == pytest.approx(0.9)  # 1 - 2/20
        assert result["total_checked"] == 20
        assert result["issues"][0]["count"] == 2

    def test_all_unbalanced_scores_0(self, monkeypatch):
        rows = [{"_id": str(i), "reference": f"JE-{i}"} for i in range(5)]
        _patch(monkeypatch, _FakeJournalCollection(total_count=5, unbalanced_rows=rows))
        result = journal_consistency_check_sync()
        assert result["consistency_score"] == 0.0

    def test_empty_collection_does_not_divide_by_zero(self, monkeypatch):
        _patch(monkeypatch, _FakeJournalCollection(total_count=0, unbalanced_rows=[]))
        result = journal_consistency_check_sync()
        assert result["consistency_score"] == 1.0
        assert result["total_checked"] == 0

    def test_mongo_error_returns_degraded_result_not_raise(self, monkeypatch):
        class _Boom:
            def count_documents(self, _q):
                raise RuntimeError("mongo down")

        monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"journal_entries": _Boom()})
        result = journal_consistency_check_sync()
        assert result["total_checked"] == 0
        assert result["issues"] == []
