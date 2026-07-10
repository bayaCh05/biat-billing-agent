"""Unit tests — Fix 2 (security audit): unhandled unique-index collisions.

Each of these write paths does an optimistic find_one()-then-insert_one()
check with no atomicity guarantee — the real uniqueness guarantee is the
Mongo unique index, so two near-simultaneous requests can both pass the
find_one() check before either inserts. Before this fix, the loser's
insert_one() raised an unhandled pymongo.errors.DuplicateKeyError (→ 500).

Each test below simulates that race deterministically: two sequential
"requests" against one fake collection that enforces uniqueness like Mongo
would — the first insert succeeds, the second must be mapped to a clean,
already-established conflict signal instead of crashing.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.documents.service_bridge import (
    BudgetPlanConflict,
    create_budget_plan_entry_native,
    create_user_native,
)
from src.storage.sync_mongo_repository import InvoiceHashConflict, SyncMongoInvoiceRepository


class _FakeAsyncUniqueCollection:
    """In-memory async collection enforcing uniqueness on `key_fields`, like
    a real Mongo unique index would — used to drive a real race instead of
    just asserting on a canned side_effect."""

    def __init__(self, key_fields: tuple[str, ...]):
        self._docs: list[dict] = []
        self._key_fields = key_fields

    def _key(self, doc: dict):
        return tuple(doc.get(f) for f in self._key_fields)

    async def insert_one(self, doc: dict):
        if any(self._key(doc) == self._key(d) for d in self._docs):
            raise DuplicateKeyError("E11000 duplicate key error collection")
        self._docs.append(dict(doc))


class TestCreateUserNativeRace:
    def test_second_concurrent_signup_gets_none_not_a_crash(self):
        coll = _FakeAsyncUniqueCollection(key_fields=("email",))

        with (
            patch(
                "src.storage.documents.user.UserDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.user.UserDocument.find_one",
                new=AsyncMock(side_effect=[None, MagicMock(email="a@biat-it.tn"), None]),
            ),
        ):
            # Both "requests" pass the optimistic existence check (both see None
            # on their pre-insert find_one) — this is exactly the race window.
            first = asyncio.run(create_user_native(
                nom="A", prenom="A", email="a@biat-it.tn",
                hashed_password="x", role="Comptable",
            ))
            second = asyncio.run(create_user_native(
                nom="A", prenom="A", email="a@biat-it.tn",
                hashed_password="x", role="Comptable",
            ))

        assert first is not None
        assert second is None  # caller (admin.py) maps this to HTTP 409


class TestCreateBudgetPlanEntryRace:
    def test_second_concurrent_create_raises_conflict_not_a_crash(self):
        coll = _FakeAsyncUniqueCollection(key_fields=("catalog_id", "year"))
        body = MagicMock(catalog_id="licences_ms365", label="Licences", monthly=[0.0] * 12, note=None)

        with (
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.budget_plan.BudgetPlanDocument.find_one",
                new=AsyncMock(side_effect=[None, MagicMock(catalog_id="licences_ms365"), None]),
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ),
        ):
            first = asyncio.run(create_budget_plan_entry_native(body, 2026, {"sub": "u1"}))

            with pytest.raises(BudgetPlanConflict):
                asyncio.run(create_budget_plan_entry_native(body, 2026, {"sub": "u2"}))

        assert first is not None


class TestInvoiceUploadHashRace:
    def test_second_concurrent_upload_of_same_file_raises_conflict(self):
        repo = SyncMongoInvoiceRepository()
        coll = MagicMock()
        # Neither "request" has the invoice's fresh _id in the DB yet.
        coll.find_one.return_value = None
        real_docs: list[dict] = []

        def fake_insert_one(doc):
            if any(doc.get("file_hash") == d.get("file_hash") for d in real_docs):
                raise DuplicateKeyError("E11000 duplicate key error collection: file_hash")
            real_docs.append(dict(doc))

        coll.insert_one.side_effect = fake_insert_one

        invoice_1 = InvoiceRecord(
            file_hash="same-file-hash-abc123",
            raw_file_path="/tmp/a.pdf",
            status=InvoiceStatus.RECEIVED,
        )
        invoice_2 = InvoiceRecord(
            file_hash="same-file-hash-abc123",
            raw_file_path="/tmp/b.pdf",
            status=InvoiceStatus.RECEIVED,
        )

        with patch.object(SyncMongoInvoiceRepository, "_coll", new_callable=PropertyMock, return_value=coll):
            repo.save(invoice_1)  # first request wins the race
            with pytest.raises(InvoiceHashConflict):
                repo.save(invoice_2)  # second request must not crash with a raw 500
