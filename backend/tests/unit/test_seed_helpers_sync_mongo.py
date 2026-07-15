"""Unit tests — sync Mongo seed-writer helpers (scripts/seed_demo.py).

create_user_sync has no live caller as of the demo-account removal (see
CLAUDE.md "Section 1 — demo accounts") — kept, and still tested here, as a
general-purpose Mongo user-creation helper available for future seed
scripts, not dead code slated for deletion.

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_sync_mongo_invoice_status.py's pattern.
"""
from __future__ import annotations

from datetime import date

import pytest
from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    create_user_sync,
    phase_has_livrables_sync,
    save_charte_projet_sync,
    save_feuille_de_route_sync,
    save_ligne_budget_sync,
    save_livrable_sync,
    save_phase_sync,
    save_risque_sync,
)


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def find_one(self, query: dict):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None

    def insert_one(self, doc: dict):
        self.docs.append(doc)


class _FakeDB(dict):
    def __getitem__(self, name):
        return super().setdefault(name, _FakeCollection())


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: fake)
    return fake


def test_create_user_sync_creates_then_skips_duplicate(db):
    assert create_user_sync("N", "P", "a@biat-it.tn", "hash", "Admin") is True
    assert create_user_sync("N", "P", "a@biat-it.tn", "hash", "Admin") is False
    assert len(db["users"].docs) == 1
    assert db["users"].docs[0]["is_first_login"] is True


def test_save_charte_projet_sync_creates_then_skips_duplicate(db):
    assert save_charte_projet_sync(
        "CHR-1", "PRJ-A", "Projet A", "BIAT", date(2026, 1, 1), None, 100.0, 850.0,
    ) is True
    assert save_charte_projet_sync(
        "CHR-1", "PRJ-A", "Projet A", "BIAT", date(2026, 1, 1), None, 100.0, 850.0,
    ) is False
    assert len(db["chartes_projet"].docs) == 1


def test_save_phase_sync_creates_then_skips_duplicate(db):
    assert save_phase_sync("PH-1", "PRJ-A", "Phase 1", "desc", 10.0, 5.0, "open", None) is True
    assert save_phase_sync("PH-1", "PRJ-A", "Phase 1", "desc", 10.0, 5.0, "open", None) is False
    assert len(db["phases"].docs) == 1


def test_save_livrable_sync_and_phase_has_livrables(db):
    assert phase_has_livrables_sync("PH-1") is False
    save_livrable_sync(
        "PH-1", "Titre", "desc", date(2026, 3, 1), None, "EN_ATTENTE", "user@biat-it.tn",
    )
    assert phase_has_livrables_sync("PH-1") is True
    assert db["livrables"].docs[0]["phase_id"] == "PH-1"


def test_save_ligne_budget_sync_creates_then_skips_duplicate(db):
    assert save_ligne_budget_sync("PRJ-A", "RH", 1000.0, 500.0) is True
    assert save_ligne_budget_sync("PRJ-A", "RH", 1000.0, 500.0) is False
    assert len(db["lignes_budget"].docs) == 1


def test_save_feuille_de_route_sync_creates_then_skips_duplicate(db):
    assert save_feuille_de_route_sync(
        "Titre", "desc", date(2026, 1, 1), date(2026, 2, 1), "PRJ-A", "PLANIFIE", "HAUTE", 2026,
    ) is True
    assert save_feuille_de_route_sync(
        "Titre", "desc", date(2026, 1, 1), date(2026, 2, 1), "PRJ-A", "PLANIFIE", "HAUTE", 2026,
    ) is False
    assert len(db["feuilles_de_route"].docs) == 1


def test_save_risque_sync_creates_then_skips_duplicate(db):
    kwargs = dict(
        titre="Risque X", description="desc", type_risque="TECHNIQUE",
        probabilite="ELEVEE", impact="CRITIQUE", statut="IDENTIFIE",
        plan_mitigation="plan", responsable_id="chef@biat-it.tn",
        date_identification=date(2026, 1, 1), date_echeance_mitigation=None,
        projet_id="PRJ-A", created_by="admin@biat-it.tn",
    )
    assert save_risque_sync(**kwargs) is True
    assert save_risque_sync(**kwargs) is False
    assert len(db["risques"].docs) == 1
    doc = db["risques"].docs[0]
    assert doc["niveau_criticite"] == "CRITIQUE"
    assert doc["feuille_route_id"] is None
