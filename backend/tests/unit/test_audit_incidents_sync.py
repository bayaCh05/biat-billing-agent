"""Unit tests — lecture des incidents pour le RAG narratif de l'Audit Agent
(Lot 3) : risques_created_since_sync, invoice_flags_created_since_sync.

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_insight_agent_kpis_mongo.py's pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    invoice_flags_created_since_sync, risques_created_since_sync,
)


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def find(self, query: dict | None = None, projection: dict | None = None):
        query = query or {}
        return [d for d in self._docs if self._matches(d, query)]

    def aggregate(self, pipeline):
        docs = list(self._docs)
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._matches(d, stage["$match"])]
            elif "$unwind" in stage:
                field = stage["$unwind"].lstrip("$")
                unwound = []
                for d in docs:
                    for item in d.get(field, []):
                        merged = dict(d)
                        merged[field] = item
                        unwound.append(merged)
                docs = unwound
            elif "$project" in stage:
                docs = [self._project(d, stage["$project"]) for d in docs]
        return docs

    def _project(self, doc: dict, spec: dict) -> dict:
        out = {}
        for key, path in spec.items():
            field = path.lstrip("$")
            if "." in field:
                parent, child = field.split(".", 1)
                out[key] = (doc.get(parent) or {}).get(child)
            else:
                out[key] = doc.get(field)
        return out

    def _matches(self, doc: dict, query: dict) -> bool:
        for key, cond in query.items():
            if "." in key:
                parent, child = key.split(".", 1)
                value = (doc.get(parent) or {}).get(child)
            else:
                value = doc.get(key)
            if isinstance(cond, dict) and "$gte" in cond:
                if value is None or value < cond["$gte"]:
                    return False
            elif value != cond:
                return False
        return True


def _to_dt(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


# ── risques_created_since_sync ────────────────────────────────────────────────

def test_risques_created_since_filters_by_date(monkeypatch):
    old = _to_dt(2026, 1, 1)
    recent = _to_dt(2026, 7, 1)
    docs = [
        {"_id": "r1", "titre": "Retard fournisseur", "description": "...", "created_at": old},
        {"_id": "r2", "titre": "Dépassement budget", "description": "...", "created_at": recent},
    ]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"risques": _FakeCollection(docs)})

    result = risques_created_since_sync(_to_dt(2026, 6, 1))

    assert len(result) == 1
    assert result[0]["_id"] == "r2"


def test_risques_created_since_none_returns_all(monkeypatch):
    docs = [{"_id": "r1", "titre": "A", "created_at": _to_dt(2026, 1, 1)}]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"risques": _FakeCollection(docs)})

    result = risques_created_since_sync(None)

    assert len(result) == 1


# ── invoice_flags_created_since_sync ──────────────────────────────────────────

def test_invoice_flags_created_since_unwinds_and_filters(monkeypatch):
    old = _to_dt(2026, 1, 1)
    recent = _to_dt(2026, 7, 1)
    docs = [
        {
            "_id": "inv-1",
            "flags": [
                {"id": "f1", "flag_type": "TOTAL_MISMATCH", "message": "old flag",
                 "severity": "WARNING", "created_at": old},
                {"id": "f2", "flag_type": "SUSPICIOUS_AMOUNT", "message": "new flag",
                 "severity": "WARNING", "created_at": recent},
            ],
        },
    ]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"invoices": _FakeCollection(docs)})

    result = invoice_flags_created_since_sync(_to_dt(2026, 6, 1))

    assert len(result) == 1
    assert result[0]["flag_id"] == "f2"
    assert result[0]["invoice_id"] == "inv-1"
    assert result[0]["message"] == "new flag"


def test_invoice_flags_created_since_none_returns_all_flags(monkeypatch):
    docs = [
        {
            "_id": "inv-2",
            "flags": [
                {"id": "f3", "flag_type": "DUPLICATE", "message": "dup",
                 "severity": "ERROR", "created_at": _to_dt(2026, 1, 1)},
            ],
        },
    ]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"invoices": _FakeCollection(docs)})

    result = invoice_flags_created_since_sync(None)

    assert len(result) == 1
    assert result[0]["flag_id"] == "f3"


def test_invoice_flags_created_since_no_flags_returns_empty(monkeypatch):
    docs = [{"_id": "inv-3", "flags": []}]
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"invoices": _FakeCollection(docs)})

    assert invoice_flags_created_since_sync(None) == []
