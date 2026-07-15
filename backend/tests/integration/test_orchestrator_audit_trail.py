"""Lot 8 — preuve de bout en bout : les 4 événements d'audit IA
(AI_EXTRACT/AI_CLASSIFY/AI_ANOMALY/AI_JOURNAL) atterrissent dans Mongo,
dans l'ordre, sans doublon ni perte, pour une facture qui va jusqu'au bout
du pipeline (JOURNALED) — pas seulement une facture FLAGGED en cours de
route (voir test_api_e2e.py::test_real_upload_writes_audit_trail_to_mongo_only
pour ce cas-là, qui ne couvre que 3 des 4 événements).

Les 4 agents IA sont mockés (résultats contrôlés, succès garanti, pas de
revue humaine requise) — ce test vérifie le comportement de l'orchestrateur
et de _audit_ai(), pas la justesse de l'extraction/classification réelle
(couverte ailleurs, hors périmètre du Lot 8).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# MONGODB_URI vit dans .env, chargé normalement par api.auth au premier import —
# mais ce test importe src.storage.mongodb directement, donc on le charge nous-
# mêmes ici en premier (même convention que api/auth.py).
_ROOT_DIR = Path(__file__).resolve().parents[3]
for _env_path in (_ROOT_DIR / ".env", _ROOT_DIR / "backend" / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ["MONGODB_DB"] = "biat_billing_test_orchestrator"

from unittest.mock import MagicMock, patch

import pymongo
import pytest

from api.security.audit_integrity import verify_row_hash_from_doc
from src.ai_agents.agent_schemas import AgentResult
from src.ai_agents.invoice_processing_orchestrator import InvoiceProcessingOrchestrator
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.mongodb import MONGODB_DB, MONGODB_URI


@pytest.fixture
def mongo_test_db():
    client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    client.drop_database(MONGODB_DB)
    yield client[MONGODB_DB]
    client.drop_database(MONGODB_DB)
    client.close()


def _fake_agent(output: dict, success: bool = True):
    class _Fake:
        def __init__(self, *a, **kw):
            pass

        def run(self, ctx):
            return AgentResult(
                agent_name="Fake", success=success, duration_ms=1.0,
                output=output, explanation="fake-ok",
            )
    return _Fake


def test_full_pipeline_produces_4_ordered_ai_audit_events_no_duplicate(mongo_test_db):
    invoice = InvoiceRecord(
        file_hash="deadbeef" * 8,
        raw_file_path="/tmp/does-not-matter.pdf",
        status=InvoiceStatus.RECEIVED,
    )

    components = MagicMock()

    orchestrator = InvoiceProcessingOrchestrator(components)

    with patch(
        "src.ai_agents.extraction_agent.ExtractionAgent",
        _fake_agent({"extraction_method": "native", "min_confidence": 0.95, "human_review_required": False}),
    ), patch(
        "src.ai_agents.classification_agent.ClassificationAgent",
        _fake_agent({"catalog_id": "telecom", "compte": "626", "pass_used": "A", "classification_confidence": 0.9}),
    ), patch(
        "src.ai_agents.anomaly_agent.AnomalyAgent",
        _fake_agent({"anomaly_count": 0, "error_count": 0, "flag_types": [], "requires_human_review": False}),
    ), patch(
        "src.ai_agents.accounting_agent.AccountingAgent",
        _fake_agent({"journal_entry_id": "je-fake-1", "is_balanced": True, "asset_created": False, "installments_created": 0}),
    ):
        result = orchestrator.process_invoice(invoice)

    assert result.final_status == "JOURNALED", (
        "la facture doit atteindre JOURNALED pour que les 4 événements existent — "
        f"obtenu: {result.final_status}"
    )

    rows = list(
        mongo_test_db.audit_logs.find({"resource_id": str(invoice.id)}).sort("created_at", 1)
    )
    actions = [r["action"] for r in rows]

    assert actions == ["AI_EXTRACT", "AI_CLASSIFY", "AI_ANOMALY", "AI_JOURNAL"], actions
    assert len(actions) == len(set(actions)), f"doublon détecté: {actions}"
    for row in rows:
        assert row["user_role"] == "AI"
        assert verify_row_hash_from_doc(row), f"HMAC invalide pour {row['action']}"


def test_audit_write_failure_does_not_break_pipeline(mongo_test_db):
    """Si l'écriture Mongo échoue en plein milieu du pipeline IA, _audit_ai()
    avale l'exception (log warning) et le traitement continue normalement —
    comportement hérité du code SQLite d'origine, inchangé par la conversion."""
    invoice = InvoiceRecord(
        file_hash="cafebabe" * 8,
        raw_file_path="/tmp/does-not-matter-2.pdf",
        status=InvoiceStatus.RECEIVED,
    )

    components = MagicMock()

    orchestrator = InvoiceProcessingOrchestrator(components)

    with patch(
        "src.ai_agents.extraction_agent.ExtractionAgent",
        _fake_agent({"extraction_method": "native", "min_confidence": 0.95, "human_review_required": False}),
    ), patch(
        "src.ai_agents.classification_agent.ClassificationAgent",
        _fake_agent({"catalog_id": "telecom", "compte": "626", "pass_used": "A", "classification_confidence": 0.9}),
    ), patch(
        "src.ai_agents.anomaly_agent.AnomalyAgent",
        _fake_agent({"anomaly_count": 0, "error_count": 0, "flag_types": [], "requires_human_review": False}),
    ), patch(
        "src.ai_agents.accounting_agent.AccountingAgent",
        _fake_agent({"journal_entry_id": "je-fake-2", "is_balanced": True, "asset_created": False, "installments_created": 0}),
    ), patch(
        "src.storage.sync_mongo_repository.log_ai_audit_event_sync",
        side_effect=ConnectionError("mongo unreachable"),
    ):
        result = orchestrator.process_invoice(invoice)

    # Le pipeline va au bout malgré l'échec total de l'audit IA
    assert result.final_status == "JOURNALED"
    rows = list(mongo_test_db.audit_logs.find({"resource_id": str(invoice.id)}))
    assert rows == [], "aucune ligne d'audit ne devrait exister si l'écriture échoue systématiquement"
