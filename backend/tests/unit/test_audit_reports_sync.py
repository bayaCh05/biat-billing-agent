"""Unit tests — sync Mongo helpers backing GET /audit-reports (Lot 4):
list_audit_snapshots_sync, count_audit_snapshots_sync, get_audit_snapshot_by_id_sync.

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_audit_snapshot_sync.py's pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    count_audit_snapshots_sync, get_audit_snapshot_by_id_sync, list_audit_snapshots_sync,
)


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def count_documents(self, query: dict) -> int:
        return len(self._match(query))

    def find(self, query: dict | None = None):
        return _FakeCursor(self._match(query or {}))

    def find_one(self, query: dict):
        matches = self._match(query)
        return matches[0] if matches else None

    def _match(self, query: dict) -> list[dict]:
        return [d for d in self._docs if all(d.get(k) == v for k, v in query.items())]


class _FakeCursor(list):
    def sort(self, key, direction):
        return _FakeCursor(sorted(self, key=lambda d: d[key], reverse=direction < 0))

    def skip(self, n):
        return _FakeCursor(self[n:])

    def limit(self, n):
        return _FakeCursor(self[:n])


def _to_dt(d: int) -> datetime:
    return datetime(2026, 7, d, tzinfo=timezone.utc)


def _snapshot(id_: str, granularity: str, day: int) -> dict:
    return {"_id": id_, "granularity": granularity, "period_start": _to_dt(day)}


def test_list_returns_most_recent_first(monkeypatch):
    docs = [_snapshot("s1", "DAILY", 10), _snapshot("s2", "DAILY", 12), _snapshot("s3", "DAILY", 11)]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection(docs)})

    result = list_audit_snapshots_sync(granularity="DAILY")

    assert [d["_id"] for d in result] == ["s2", "s3", "s1"]


def test_list_filters_by_granularity(monkeypatch):
    docs = [_snapshot("s1", "DAILY", 10), _snapshot("s2", "WEEKLY", 10)]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection(docs)})

    result = list_audit_snapshots_sync(granularity="WEEKLY")

    assert len(result) == 1
    assert result[0]["_id"] == "s2"


def test_list_respects_limit_and_skip(monkeypatch):
    docs = [_snapshot(f"s{i}", "DAILY", i) for i in range(1, 6)]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection(docs)})

    result = list_audit_snapshots_sync(granularity="DAILY", limit=2, skip=1)

    assert len(result) == 2
    assert result[0]["_id"] == "s4"  # most recent is s5, skip 1 -> s4, s3


def test_count_reflects_granularity_filter(monkeypatch):
    docs = [_snapshot("s1", "DAILY", 1), _snapshot("s2", "DAILY", 2), _snapshot("s3", "WEEKLY", 1)]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection(docs)})

    assert count_audit_snapshots_sync(granularity="DAILY") == 2
    assert count_audit_snapshots_sync() == 3


def test_get_by_id_returns_matching_document(monkeypatch):
    docs = [_snapshot("s1", "DAILY", 1), _snapshot("s2", "DAILY", 2)]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection(docs)})

    result = get_audit_snapshot_by_id_sync("s2")

    assert result["_id"] == "s2"


def test_get_by_id_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": _FakeCollection([])})

    assert get_audit_snapshot_by_id_sync("missing") is None
