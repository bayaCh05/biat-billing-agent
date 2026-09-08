"""Dépôts MongoDB synchrones — pour le pipeline IA (InvoiceProcessingOrchestrator + agents).

Pourquoi synchrone : InvoiceProcessingOrchestrator.process_invoice() et ses 4 agents sont
délibérément synchrones ("Built as synchronous to match the existing FastAPI +
SQLAlchemy patterns" — voir ai_agents/invoice_processing_orchestrator.py), alors que Beanie/Motor
est async-only. Plutôt que de faire remonter async/await dans toute la chaîne
d'agents, on utilise ici un client pymongo classique (synchrone), avec les
mêmes conventions que le reste de la migration : _id toujours une chaîne
UUID avec tirets, jamais un objet UUID natif BSON.

Ces classes exposent volontairement la MÊME API que leurs équivalents
SQLAlchemy historiques (InvoiceRepository, AssetRepository,
ClientInvoiceRepository — le SQLAlchemy JournalRepository/journal_store.py a
depuis été supprimé, dead code après ce portage) afin que DuplicateDetector,
AnomalyDetector, InvoiceNumberer, InvoiceBuilder n'aient besoin d'AUCUNE
modification — seul l'objet injecté change.

Portée : le chemin InvoiceProcessingOrchestrator (route API /invoices/upload) et la
génération de factures client (billing.py). Le daemon headless
(scripts/run_agent.py, agent/pipeline.py, agent/agent.py) et son
PipelineComponents SQLAlchemy ont été supprimés (Lot B, sub-lot 6) — ils
étaient confirmés superseded en pratique par le chemin API+InvoiceProcessingOrchestrator.
InvoiceProcessingOrchestrator utilise désormais AIComponents (agent/config_loader.py), un
sous-ensemble sans SQLAlchemy de ce que PipelineComponents fournissait.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pymongo

from src.models.asset import Asset
from src.models.client_invoice import ClientInvoice
from src.models.enums import (
    ChargeNature, ChargeType, ExtractionMethod, FlagSeverity, FlagType,
    InvoiceDirection, InvoiceStatus,
)
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
from src.models.journal import JournalEntry

if TYPE_CHECKING:
    from src.models.audit import AuditLogCreate

logger = logging.getLogger(__name__)

_CONFIDENCE_FIELD_NAMES = [
    "issuer_name", "issuer_tax_id",
    "recipient_name", "recipient_tax_id",
    "invoice_number", "invoice_date", "due_date",
    "amount_ht", "tva_rate", "tva_amount", "amount_ttc",
]
_DATE_FIELDS = {"invoice_date", "due_date"}

_client: "pymongo.MongoClient | None" = None


def _get_db():
    global _client
    if _client is None:
        from src.storage.mongodb import MONGODB_URI
        _client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    from src.storage.mongodb import MONGODB_DB
    return _client[MONGODB_DB]


def _to_midnight_utc(d) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _bson_to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    return v


# ── Invoices ────────────────────────────────────────────────────────────────

class InvoiceHashConflict(Exception):
    """Levée quand deux requêtes concurrentes uploadent le même fichier
    (même file_hash) et gagnent toutes deux le find_one() de vérification
    avant qu'une des deux n'insère — voir save()."""

    def __init__(self, file_hash: str):
        self.file_hash = file_hash
        super().__init__(file_hash)


class SyncMongoInvoiceRepository:
    """Même API que src.storage.repository.InvoiceRepository, backend Mongo sync."""

    @property
    def _coll(self):
        return _get_db()["invoices"]

    def save(self, invoice: InvoiceRecord, changed_by: str = "agent") -> InvoiceRecord:
        coll = self._coll
        doc_id = str(invoice.id)
        existing = coll.find_one({"_id": doc_id}, {"status": 1})

        scalar = self._scalar_dict(invoice)
        scalar["line_items"] = self._line_item_dicts(invoice)
        scalar["flags"] = self._flag_dicts(invoice)

        if existing is None:
            scalar["_id"] = doc_id
            scalar["history"] = [{
                "id": str(uuid4()), "from_status": None,
                "to_status": invoice.status.value,
                "changed_at": datetime.now(timezone.utc),
                "changed_by": changed_by, "notes": None,
            }]
            # get_by_hash() in the caller is an optimistic pre-check, not the
            # real guarantee — the unique index on file_hash (invoice.py) is.
            # Two concurrent uploads of the same file can both pass that
            # check before either inserts; the loser must get a clean
            # conflict here instead of an unhandled 500.
            try:
                coll.insert_one(scalar)
            except pymongo.errors.DuplicateKeyError:
                raise InvoiceHashConflict(invoice.file_hash)
        else:
            update: dict[str, Any] = {"$set": scalar}
            if existing.get("status") != invoice.status.value:
                update["$push"] = {"history": {
                    "id": str(uuid4()), "from_status": existing.get("status"),
                    "to_status": invoice.status.value,
                    "changed_at": datetime.now(timezone.utc),
                    "changed_by": changed_by, "notes": None,
                }}
            coll.update_one({"_id": doc_id}, update)
        return invoice

    def get_by_id(self, invoice_id: UUID) -> InvoiceRecord | None:
        doc = self._coll.find_one({"_id": str(invoice_id)})
        return self._to_pydantic(doc) if doc else None

    def get_by_hash(self, file_hash: str) -> InvoiceRecord | None:
        doc = self._coll.find_one({"file_hash": file_hash})
        return self._to_pydantic(doc) if doc else None

    def find_potential_duplicates(
        self, invoice_number: str, issuer_tax_id: str, window_days: int,
        exclude_id: UUID | None = None,
    ) -> list[InvoiceRecord]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
        query: dict[str, Any] = {
            "issuer_tax_id": issuer_tax_id,
            "invoice_number": invoice_number,
            "received_at": {"$gte": cutoff},
            "status": {"$ne": InvoiceStatus.REJECTED.value},
        }
        if exclude_id is not None:
            query["_id"] = {"$ne": str(exclude_id)}
        return [self._to_pydantic(d) for d in self._coll.find(query)]

    def find_near_duplicates(
        self, issuer_name: str, amount_ttc: float, window_days: int,
        exclude_id: UUID | None = None, relative_tolerance: float = 0.01,
    ) -> list[InvoiceRecord]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
        tol = max(0.02, amount_ttc * relative_tolerance)
        query: dict[str, Any] = {
            "issuer_name": issuer_name,
            "amount_ttc": {"$gte": amount_ttc - tol, "$lte": amount_ttc + tol},
            "received_at": {"$gte": cutoff},
            "status": {"$ne": InvoiceStatus.REJECTED.value},
        }
        if exclude_id is not None:
            query["_id"] = {"$ne": str(exclude_id)}
        return [self._to_pydantic(d) for d in self._coll.find(query)]

    def get_by_status(self, status: InvoiceStatus) -> list[InvoiceRecord]:
        return [self._to_pydantic(d) for d in self._coll.find({"status": status.value})]

    def count_by_status(self) -> dict[str, int]:
        """Return {status_value: count} — same shape as the SQLAlchemy
        InvoiceRepository.count_by_status() used by scheduler.py/ai.py."""
        rows = self._coll.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
        return {row["_id"]: row["count"] for row in rows}

    def get_historical_amounts(self, issuer_tax_id: str) -> list[float]:
        query = {
            "issuer_tax_id": issuer_tax_id,
            "amount_ttc": {"$ne": None},
            "status": {"$ne": InvoiceStatus.REJECTED.value},
        }
        return [
            d["amount_ttc"] for d in self._coll.find(query, {"amount_ttc": 1})
            if d.get("amount_ttc") is not None
        ]

    # ── dict <-> pydantic ──

    def _scalar_dict(self, invoice: InvoiceRecord) -> dict:
        d: dict[str, Any] = {
            "file_hash": invoice.file_hash,
            "raw_file_path": invoice.raw_file_path,
            "file_mime_type": invoice.file_mime_type,
            "direction": invoice.direction.value,
            "status": invoice.status.value,
            "extraction_method": invoice.extraction_method.value if invoice.extraction_method else None,
            "retry_count": invoice.retry_count,
            "last_error": invoice.last_error,
            "currency": invoice.currency,
            "raw_extracted_json": invoice.raw_extracted_json,
            "cost_catalog_id": invoice.cost_catalog_id,
            "accounting_compte": invoice.accounting_compte,
            "accounting_label": invoice.accounting_label,
            "charge_nature": invoice.charge_nature.value if invoice.charge_nature else None,
            "charge_type": invoice.charge_type.value if invoice.charge_type else None,
            "matched_po_id": invoice.matched_po_id,
            "matched_contract_id": invoice.matched_contract_id,
            "matched_client_id": invoice.matched_client_id,
            "payment_term_days": invoice.payment_term_days,
            "classification_reason": invoice.classification_reason,
            "classification_pass": invoice.classification_pass,
            "human_review_required": invoice.human_review_required,
            "human_review_notes": invoice.human_review_notes,
            "reviewed_by": invoice.reviewed_by,
            "reviewed_at": invoice.reviewed_at,
            "received_at": invoice.received_at,
            "extracted_at": invoice.extracted_at,
            "classified_at": invoice.classified_at,
            "validated_at": invoice.validated_at,
            "exported_at": invoice.exported_at,
            "export_reference": invoice.export_reference,
            "paid_at": invoice.paid_at,
            "collected_at": invoice.collected_at,
            "created_at": invoice.created_at,
            "updated_at": datetime.now(timezone.utc),
        }
        for field_name in _CONFIDENCE_FIELD_NAMES:
            cf = getattr(invoice, field_name)
            value = cf.value
            if field_name in _DATE_FIELDS:
                value = _to_midnight_utc(value)
            d[field_name] = value
            d[f"{field_name}_conf"] = cf.confidence if cf.value is not None else None
        return d

    @staticmethod
    def _line_item_dicts(invoice: InvoiceRecord) -> list[dict]:
        return [
            {
                "id": str(uuid4()), "line_number": li.line_number, "description": li.description,
                "quantity": li.quantity, "unit_price": li.unit_price,
                "line_total": li.line_total, "tva_rate": li.tva_rate,
            }
            for li in invoice.line_items
        ]

    @staticmethod
    def _flag_dicts(invoice: InvoiceRecord) -> list[dict]:
        return [
            {
                "id": str(uuid4()), "flag_type": f.flag_type.value, "severity": f.severity.value,
                "field_name": f.field_name, "message": f.message, "resolved": f.resolved,
                "resolved_at": f.resolved_at, "resolved_by": f.resolved_by,
                "created_at": datetime.now(timezone.utc),
            }
            for f in invoice.flags
        ]

    @staticmethod
    def _to_pydantic(doc: dict) -> InvoiceRecord:
        now = datetime.now(tz=timezone.utc)
        invoice = InvoiceRecord(
            id=UUID(doc["_id"]),
            file_hash=doc["file_hash"],
            raw_file_path=doc["raw_file_path"],
            file_mime_type=doc.get("file_mime_type"),
            direction=InvoiceDirection(doc["direction"]),
            status=InvoiceStatus(doc["status"]),
            extraction_method=ExtractionMethod(doc["extraction_method"]) if doc.get("extraction_method") else None,
            retry_count=doc.get("retry_count", 0),
            last_error=doc.get("last_error"),
            currency=doc.get("currency", "TND"),
            raw_extracted_json=doc.get("raw_extracted_json"),
            cost_catalog_id=doc.get("cost_catalog_id"),
            accounting_compte=doc.get("accounting_compte"),
            accounting_label=doc.get("accounting_label"),
            charge_nature=ChargeNature(doc["charge_nature"]) if doc.get("charge_nature") else None,
            charge_type=ChargeType(doc["charge_type"]) if doc.get("charge_type") else None,
            matched_po_id=doc.get("matched_po_id"),
            matched_contract_id=doc.get("matched_contract_id"),
            matched_client_id=doc.get("matched_client_id"),
            payment_term_days=doc.get("payment_term_days"),
            classification_reason=doc.get("classification_reason"),
            classification_pass=doc.get("classification_pass"),
            human_review_required=doc.get("human_review_required", False),
            human_review_notes=doc.get("human_review_notes"),
            reviewed_by=doc.get("reviewed_by"),
            reviewed_at=doc.get("reviewed_at"),
            received_at=doc.get("received_at") or now,
            extracted_at=doc.get("extracted_at"),
            classified_at=doc.get("classified_at"),
            validated_at=doc.get("validated_at"),
            exported_at=doc.get("exported_at"),
            export_reference=doc.get("export_reference"),
            paid_at=doc.get("paid_at"),
            collected_at=doc.get("collected_at"),
            created_at=doc.get("created_at") or now,
            updated_at=doc.get("updated_at") or now,
        )
        for field_name in _CONFIDENCE_FIELD_NAMES:
            value = doc.get(field_name)
            if field_name in _DATE_FIELDS:
                value = _bson_to_date(value)
            confidence = doc.get(f"{field_name}_conf") or 0.0
            setattr(invoice, field_name, ConfidenceField(value=value, confidence=confidence))

        invoice.line_items = [
            LineItem(
                line_number=li["line_number"], description=li.get("description"),
                quantity=li.get("quantity"), unit_price=li.get("unit_price"),
                line_total=li.get("line_total"), tva_rate=li.get("tva_rate"),
            )
            for li in doc.get("line_items", [])
        ]
        invoice.flags = [
            ValidationFlag(
                flag_type=FlagType(f["flag_type"]), severity=FlagSeverity(f["severity"]),
                field_name=f.get("field_name"), message=f["message"],
                resolved=f.get("resolved", False), resolved_at=f.get("resolved_at"),
                resolved_by=f.get("resolved_by"),
            )
            for f in doc.get("flags", [])
        ]
        return invoice


def historical_amounts_for_catalog_sync(catalog_id: str, exclude_id) -> list[float]:
    """Réplique AnomalyAgent._check_category_price's raw SQL, backend Mongo."""
    coll = _get_db()["invoices"]
    query = {
        "cost_catalog_id": catalog_id,
        "status": {"$in": ["VALIDATED", "EXPORTED", "JOURNALED", "PAID"]},
        "_id": {"$ne": str(exclude_id)},
        "amount_ht": {"$ne": None},
    }
    return [d["amount_ht"] for d in coll.find(query, {"amount_ht": 1})]


def historical_payment_terms_sync(issuer_tax_id: str, exclude_id) -> list[int]:
    """Réplique AnomalyAgent._check_payment_term's raw SQL, backend Mongo."""
    coll = _get_db()["invoices"]
    query = {
        "issuer_tax_id": issuer_tax_id,
        "status": {"$in": ["VALIDATED", "EXPORTED", "JOURNALED", "PAID"]},
        "due_date": {"$ne": None},
        "invoice_date": {"$ne": None},
        "_id": {"$ne": str(exclude_id)},
    }
    docs = list(coll.find(query, {"due_date": 1, "invoice_date": 1}).limit(20))
    out = []
    for d in docs:
        due = _bson_to_date(d.get("due_date"))
        inv = _bson_to_date(d.get("invoice_date"))
        if due is not None and inv is not None:
            out.append((due - inv).days)
    return out


# ── Audit (AI pipeline) ───────────────────────────────────────────────────────

def log_ai_audit_event_sync(entry: "AuditLogCreate") -> None:
    """Écrit un événement d'audit IA directement dans Mongo — équivalent synchrone
    de service_bridge.log_audit_event_native(), pour InvoiceProcessingOrchestrator._audit_ai()
    (pipeline synchrone — voir le docstring de ce module pour le pourquoi).

    Même collection ("audit_logs"), même formule de row_hash que le chemin async
    (api/security/audit_integrity.py::compute_row_hash_from_doc) — pas de
    dépendance à Motor/Beanie ici, uniquement pymongo synchrone.

    Lève toute exception pymongo à l'appelant — InvoiceProcessingOrchestrator._audit_ai() est
    responsable de l'avaler pour ne jamais interrompre le pipeline (comportement
    déjà en place côté SQLite, inchangé ici).
    """
    from api.security.audit_integrity import compute_row_hash_from_doc

    doc = {
        "_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc),
        "user_id": entry.user_id,
        "user_email": entry.user_email,
        "user_role": entry.user_role,
        "actor": entry.user_email or entry.user_id or "",
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "entity_id": entry.resource_id,
        "before_value": entry.before_value,
        "after_value": entry.after_value,
        "ip_address": entry.ip_address,
        "user_agent": entry.user_agent,
        "status": entry.status,
        "detail": entry.detail,
    }
    doc["row_hash"] = compute_row_hash_from_doc(doc)

    _get_db()["audit_logs"].insert_one(doc)


# ── Journal ─────────────────────────────────────────────────────────────────

class SyncMongoJournalRepository:
    """Backend Mongo sync pour la journalisation comptable — remplace l'ancien
    SQLAlchemy JournalRepository (src/accounting/journal_store.py, supprimé)."""

    @property
    def _coll(self):
        return _get_db()["journal_entries"]

    def save(self, entry: JournalEntry) -> JournalEntry:
        doc = {
            "_id": str(entry.id),
            "reference": entry.reference,
            "date_ecriture": _to_midnight_utc(entry.date_ecriture),
            "description": entry.description,
            "source_invoice_id": str(entry.source_invoice_id) if entry.source_invoice_id else None,
            "source_asset_id": str(entry.source_asset_id) if entry.source_asset_id else None,
            "accounting_explanation": entry.accounting_explanation,
            "created_at": entry.created_at,
            "lines": [
                {
                    "id": str(uuid4()), "compte": l.compte, "libelle": l.libelle,
                    "debit": l.debit, "credit": l.credit,
                }
                for l in entry.lines
            ],
        }
        self._coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return entry


def journal_consistency_check_sync() -> dict:
    """Réplique AccountingAgent.check_consistency's raw SQL, backend Mongo.

    Interroge directement la collection journal_entries — indépendant de
    l'objet JournalRepository injecté dans AccountingAgent, pour que
    scheduler.py et /ai/accounting-check voient toujours l'état Mongo réel.
    """
    coll = _get_db()["journal_entries"]
    issues: list[dict] = []
    total_checked = 0
    unbalanced_count = 0
    try:
        total_checked = coll.count_documents({})
        rows = list(coll.aggregate([
            {"$addFields": {
                "total_debit": {"$sum": "$lines.debit"},
                "total_credit": {"$sum": "$lines.credit"},
            }},
            {"$addFields": {
                "diff": {"$abs": {"$subtract": ["$total_debit", "$total_credit"]}},
            }},
            {"$match": {"diff": {"$gt": 0.005}}},
            {"$project": {"reference": 1}},
        ]))
        if rows:
            unbalanced_count = len(rows)
            issues.append({
                "type": "UNBALANCED_ENTRIES",
                "count": unbalanced_count,
                "detail": [{"id": r["_id"], "reference": r.get("reference")} for r in rows[:5]],
            })
    except Exception as exc:
        logger.warning("journal_consistency_check_sync_error: %s", exc, exc_info=True)

    # Proportionnel au nombre réel d'écritures, pas binaire — total_checked
    # comptait auparavant les exécutions de la requête (toujours 1), pas les
    # écritures, donc le score ne pouvait valoir que 1.0 ou 0.0 quel que soit
    # le nombre réel d'écritures déséquilibrées.
    return {
        "consistency_score": round(1 - unbalanced_count / max(total_checked, 1), 3),
        "total_checked": total_checked,
        "issues": issues,
    }


# ── CAPEX assets ────────────────────────────────────────────────────────────

class SyncMongoAssetRepository:
    """Même API (sous-ensemble .save()) que src.capex.asset_repository.AssetRepository."""

    @property
    def _coll(self):
        return _get_db()["assets"]

    def save(self, asset: Asset) -> Asset:
        doc = {
            "designation": asset.designation,
            "compte_immobilisation": asset.compte_immobilisation,
            "compte_amortissement": asset.compte_amortissement,
            "acquisition_date": _to_midnight_utc(asset.acquisition_date),
            "acquisition_cost_ht": asset.acquisition_cost_ht,
            "useful_life_years": asset.useful_life_years,
            "depreciation_method": asset.depreciation_method,
            "supplier_invoice_id": str(asset.supplier_invoice_id) if asset.supplier_invoice_id else None,
            "amortization_source": asset.amortization_source,
            "notes": asset.notes,
            "created_at": asset.created_at,
        }
        doc_id = str(asset.id)
        existing = self._coll.find_one({"_id": doc_id}, {"_id": 1})
        if existing is None:
            doc["_id"] = doc_id
            doc["fully_depreciated"] = False
            doc["project_links"] = []
            self._coll.insert_one(doc)
        else:
            self._coll.update_one({"_id": doc_id}, {"$set": doc})
        return asset


# ── Payment installments ─────────────────────────────────────────────────────

def save_payment_installments_sync(rows: list[dict]) -> list[str]:
    """rows: dicts with invoice_id, installment_number, total_installments,
    base_amount, current_amount, due_date (date). Retourne les ids créés."""
    coll = _get_db()["payment_installments"]
    now = datetime.now(timezone.utc)
    ids: list[str] = []
    docs = []
    for r in rows:
        _id = str(uuid4())
        ids.append(_id)
        docs.append({
            "_id": _id,
            "invoice_id": r["invoice_id"],
            "installment_number": r["installment_number"],
            "total_installments": r["total_installments"],
            "base_amount": r["base_amount"],
            "current_amount": r["current_amount"],
            "due_date": _to_midnight_utc(r["due_date"]),
            "paid_date": None,
            "paid_amount": None,
            "status": "PENDING",
            "late_periods": 0,
            "created_at": now,
            "updated_at": now,
        })
    if docs:
        coll.insert_many(docs)
    return ids


def recalculate_late_installments_sync(penalty_rate: float) -> int:
    """Réplique le job planifié _job_recalculate_installments (scheduler.py),
    backend Mongo. Retourne le nombre d'échéances mises à jour."""
    coll = _get_db()["payment_installments"]
    today = date.today()
    today_dt = _to_midnight_utc(today)

    pending = list(coll.find({
        "due_date": {"$lt": today_dt},
        "status": {"$in": ["PENDING", "LATE"]},
    }))

    updated = 0
    for inst in pending:
        due = _bson_to_date(inst["due_date"])
        days_overdue = (today - due).days
        late_periods = days_overdue // 30
        if late_periods > inst.get("late_periods", 0):
            new_amount = round(inst["base_amount"] * ((1 + penalty_rate) ** late_periods), 3)
            coll.update_one(
                {"_id": inst["_id"]},
                {"$set": {
                    "current_amount": new_amount, "late_periods": late_periods,
                    "status": "LATE", "updated_at": datetime.now(timezone.utc),
                }},
            )
            updated += 1
    return updated


# ── Client invoices (facturation) ────────────────────────────────────────────

class SyncMongoClientInvoiceRepository:
    """Même API (sous-ensemble) que src.billing.client_invoice_store.ClientInvoiceRepository."""

    @property
    def _coll(self):
        return _get_db()["client_invoices"]

    def save(self, invoice: ClientInvoice) -> ClientInvoice:
        doc = {
            "_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "invoice_date": _to_midnight_utc(invoice.invoice_date),
            "due_date": _to_midnight_utc(invoice.due_date),
            "issuer_name": invoice.issuer_name,
            "issuer_tax_id": invoice.issuer_tax_id,
            "issuer_address": invoice.issuer_address or None,
            "client_id": invoice.client_id,
            "client_name": invoice.client_name,
            "client_tax_id": invoice.client_tax_id,
            "client_address": invoice.client_address or None,
            "line_items": [
                {
                    "id": str(uuid4()), "description": li.description, "quantity": li.quantity,
                    "unit_price": li.unit_price, "line_total": li.line_total,
                    "tva_rate": li.tva_rate, "tva_amount": li.tva_amount,
                    "compte_produit": li.compte_produit,
                }
                for li in invoice.line_items
            ],
            "amount_ht": invoice.amount_ht,
            "tva_amount": invoice.tva_amount,
            "amount_ttc": invoice.amount_ttc,
            "status": invoice.status.value,
            "source_template_id": invoice.source_template_id,
            "notes": invoice.notes,
            "pdf_path": invoice.pdf_path,
            "created_at": invoice.created_at,
            "sent_at": invoice.sent_at,
            "paid_at": invoice.paid_at,
        }
        self._coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return invoice

    def get_max_sequence(self, year: int) -> int:
        from src.billing.invoice_numbering import InvoiceNumberer

        prefix = f"FAC-IT-{year}-"
        numbers = self._coll.distinct(
            "invoice_number", {"invoice_number": {"$regex": f"^{prefix}"}}
        )
        max_seq = 0
        for num in numbers:
            parsed = InvoiceNumberer.parse_sequence(num)
            if parsed and parsed[0] == year:
                max_seq = max(max_seq, parsed[1])
        return max_seq


# ── Insights (health-summary KPIs) ──────────────────────────────────────────
# Réplique InsightAgent._gather_kpis' raw SQL, backend Mongo synchrone (la route
# GET /ai/health-summary est sync — pas de Beanie/await ici, voir docstring en
# tête de fichier).

def invoice_pending_rejected_30d_sync() -> dict:
    """Compte les factures en attente / rejetées sur les 30 derniers jours."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    coll = _get_db()["invoices"]
    total = coll.count_documents({"received_at": {"$gte": cutoff}})
    pending = coll.count_documents({
        "received_at": {"$gte": cutoff},
        "status": {"$in": [
            "RECEIVED", "EXTRACTING", "EXTRACTED",
            "CLASSIFYING", "CLASSIFIED", "VALIDATING",
        ]},
    })
    rejected = coll.count_documents({
        "received_at": {"$gte": cutoff},
        "status": {"$in": ["REJECTED", "EXTRACTION_FAILED", "ERROR"]},
    })
    return {
        "pending_count": pending,
        "rejection_rate": round(rejected / max(total, 1) * 100, 1),
    }


def roadmap_kpis_sync() -> dict:
    """Jalons en retard et % complété — collection feuilles_de_route."""
    coll = _get_db()["feuilles_de_route"]
    today = _to_midnight_utc(date.today())
    n_overdue = coll.count_documents({
        "date_fin": {"$lt": today},
        "statut": {"$nin": ["TERMINE", "ANNULE"]},
    })
    done = coll.count_documents({"statut": "TERMINE"})
    total = coll.count_documents({})
    return {
        "n_overdue_milestones": n_overdue,
        "pct_done": round(done / max(total, 1) * 100, 1),
    }


def risks_kpis_sync() -> dict:
    """Risques critiques actifs et plans de mitigation en retard — collection risques."""
    coll = _get_db()["risques"]
    today = _to_midnight_utc(date.today())
    n_critique = coll.count_documents({
        "niveau_criticite": "CRITIQUE",
        "statut": {"$nin": ["CLOTURE", "MAITRISE"]},
    })
    n_overdue_mitigation = coll.count_documents({
        "date_echeance_mitigation": {"$lt": today},
        "statut": {"$nin": ["CLOTURE", "MAITRISE"]},
    })
    return {
        "n_critique": n_critique,
        "n_overdue_mitigation": n_overdue_mitigation,
    }


def budget_variance_kpis_sync() -> dict:
    """Lignes budgétaires en dépassement et écart global — année courante, YTD au mois courant.

    Même logique que service_bridge.budget_summary_mongo() (async) mais en pymongo
    synchrone, pour un appelant sync (InsightAgent._gather_kpis).
    """
    db = _get_db()
    today = date.today()
    year, month = today.year, today.month

    entries = list(db["budget_plan_entries"].find({"year": year}))
    budget_ytd = {
        e["catalog_id"]: sum(float(m) for m in (e.get("monthly") or [])[:month])
        for e in entries
    }

    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    rows = db["invoices"].aggregate([
        {"$match": {
            "status": {"$in": ["VALIDATED", "EXPORTED", "PAID", "JOURNALED"]},
            "direction": "SUPPLIER",
            "invoice_date": {"$gte": start, "$lte": end},
            "cost_catalog_id": {"$ne": None},
            "amount_ht": {"$ne": None},
        }},
        {"$group": {"_id": "$cost_catalog_id", "total": {"$sum": "$amount_ht"}}},
    ])
    actual_ytd = {r["_id"]: float(r["total"] or 0) for r in rows}

    total_budget = sum(budget_ytd.values())
    total_actual = sum(actual_ytd.get(cid, 0.0) for cid in budget_ytd)

    return {
        "n_total": len(budget_ytd),
        "n_over_budget": sum(
            1 for cid, b in budget_ytd.items() if actual_ytd.get(cid, 0.0) > b
        ),
        "variance_pct": (
            round((total_actual - total_budget) / total_budget * 100, 1)
            if total_budget else 0.0
        ),
    }


def echeancier_kpis_sync() -> dict:
    """Échéances de paiement en retard et pénalités cumulées — collection payment_installments.

    Utilisé par AuditAgent (domaine "echeancier") — voir ai_agents/audit_agent.py.
    """
    coll = _get_db()["payment_installments"]
    n_total = coll.count_documents({})
    n_late = coll.count_documents({"status": "LATE"})
    n_pending = coll.count_documents({"status": "PENDING"})

    late_rows = list(coll.find({"status": "LATE"}, {"base_amount": 1, "current_amount": 1}))
    total_penalty = sum(
        (r.get("current_amount", 0) or 0) - (r.get("base_amount", 0) or 0)
        for r in late_rows
    )

    return {
        "n_total": n_total,
        "n_late": n_late,
        "n_pending": n_pending,
        "total_penalty_amount": round(total_penalty, 3),
    }


# ── Rapprochement transversal (Audit Agent, Lot 2) ───────────────────────────
# Croisements facture ↔ échéancier ↔ budget ↔ journal — aucune jointure Mongo
# ($lookup, cohérent avec l'interdit déjà en place dans NLQueryEngine._is_safe()) :
# les rapprochements se font en Python, sur des volumes qui restent petits
# (factures d'une période). Purement déterministe, aucun LLM impliqué.

def invoices_overdue_without_installment_plan_sync() -> dict:
    """Factures en retard (due_date < aujourd'hui, statut non terminal) sans
    aucune échéance dans payment_installments — devraient en avoir une.
    Rapprochement facture ↔ échéancier (Lot 2a)."""
    db = _get_db()
    today_dt = _to_midnight_utc(date.today())
    overdue = list(db["invoices"].find(
        {"due_date": {"$lt": today_dt}, "status": {"$nin": ["PAID", "COLLECTED", "REJECTED"]}},
        {"invoice_number": 1},
    ))
    if not overdue:
        return {"count": 0, "detail": []}

    with_plan = {
        r["invoice_id"]
        for r in db["payment_installments"].find(
            {"invoice_id": {"$in": [inv["_id"] for inv in overdue]}}, {"invoice_id": 1}
        )
    }
    missing = [inv for inv in overdue if inv["_id"] not in with_plan]
    return {
        "count": len(missing),
        "detail": [
            {"invoice_id": inv["_id"], "invoice_number": inv.get("invoice_number")}
            for inv in missing[:5]
        ],
    }


def late_installments_invoice_not_flagged_sync() -> dict:
    """Échéances LATE dont la facture parente n'a pas human_review_required=True
    — incohérence de statut entre payment_installments et invoices.
    Rapprochement facture ↔ échéancier (Lot 2a)."""
    db = _get_db()
    late = list(db["payment_installments"].find({"status": "LATE"}, {"invoice_id": 1}))
    if not late:
        return {"count": 0, "detail": []}

    invoice_ids = list({r["invoice_id"] for r in late})
    flagged_by_id = {
        inv["_id"]: bool(inv.get("human_review_required", False))
        for inv in db["invoices"].find(
            {"_id": {"$in": invoice_ids}}, {"human_review_required": 1}
        )
    }
    not_flagged = [iid for iid in invoice_ids if not flagged_by_id.get(iid, False)]
    return {
        "count": len(not_flagged),
        "detail": [{"invoice_id": iid} for iid in not_flagged[:5]],
    }


def budget_overrun_top_invoices_sync(top_n: int = 3) -> list[dict]:
    """Pour chaque ligne budgétaire dépassée cette année (YTD), les factures
    qui contribuent le plus au dépassement. Rapprochement budget ↔ facture
    (Lot 2b) — complète budget_variance_kpis_sync (qui n'agrège que des
    totaux) avec l'attribution ligne-par-ligne nécessaire à un audit.

    Recalcule budget_ytd/actual_ytd par catalog_id (même logique que
    budget_variance_kpis_sync) — duplication acceptée : les deux fonctions
    répondent à des besoins différents (KPI agrégé vs détail auditable) et
    coupler les deux ferait dépendre le Lot 1 déjà testé du Lot 2.
    """
    db = _get_db()
    today = date.today()
    year, month = today.year, today.month

    entries = list(db["budget_plan_entries"].find({"year": year}))
    budget_ytd = {
        e["catalog_id"]: sum(float(m) for m in (e.get("monthly") or [])[:month])
        for e in entries
    }
    if not budget_ytd:
        return []

    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    base_match = {
        "status": {"$in": ["VALIDATED", "EXPORTED", "PAID", "JOURNALED"]},
        "direction": "SUPPLIER",
        "invoice_date": {"$gte": start, "$lte": end},
        "amount_ht": {"$ne": None},
    }

    result = []
    for catalog_id, budget in budget_ytd.items():
        match = {**base_match, "cost_catalog_id": catalog_id}
        invoices = list(db["invoices"].find(match, {"invoice_number": 1, "amount_ht": 1}))
        actual = sum(inv.get("amount_ht", 0) or 0 for inv in invoices)
        if actual <= budget:
            continue
        top = sorted(invoices, key=lambda i: i.get("amount_ht", 0) or 0, reverse=True)[:top_n]
        result.append({
            "catalog_id": catalog_id,
            "budget_ytd": round(budget, 3),
            "actual_ytd": round(actual, 3),
            "top_invoices": [
                {
                    "invoice_id": inv["_id"],
                    "invoice_number": inv.get("invoice_number"),
                    "amount_ht": inv.get("amount_ht"),
                }
                for inv in top
            ],
        })
    return result


def invoices_journal_mismatch_sync() -> dict:
    """Cohérence facture ↔ journal pour les factures JOURNALED : exactement
    une écriture par facture, et son montant (Σ lignes 401/411) cohérent avec
    invoice.amount_ttc (tolérance 0,005 TND — même convention PCE que le
    reste du projet). Rapprochement facture ↔ journal (Lot 2c) — comble un
    trou que journal_consistency_check_sync ne couvre pas (celui-ci vérifie
    débit=crédit par écriture, jamais qu'une facture JOURNALED a une écriture
    du tout).
    """
    db = _get_db()
    journaled = list(db["invoices"].find({"status": "JOURNALED"}, {"amount_ttc": 1}))
    if not journaled:
        return {
            "missing_entry_count": 0, "missing_entry": [],
            "duplicate_entry_count": 0, "duplicate_entry": [],
            "amount_mismatch_count": 0, "amount_mismatch": [],
        }

    invoice_ids = [inv["_id"] for inv in journaled]
    entries = list(db["journal_entries"].find(
        {"source_invoice_id": {"$in": invoice_ids}},
        {"source_invoice_id": 1, "lines": 1, "reference": 1},
    ))
    by_invoice: dict[str, list[dict]] = {}
    for e in entries:
        by_invoice.setdefault(e.get("source_invoice_id"), []).append(e)

    missing, duplicate, mismatch = [], [], []
    for inv in journaled:
        inv_id = inv["_id"]
        matches = by_invoice.get(inv_id, [])
        if len(matches) == 0:
            missing.append({"invoice_id": inv_id})
        elif len(matches) > 1:
            duplicate.append({
                "invoice_id": inv_id, "count": len(matches),
                "references": [m.get("reference") for m in matches],
            })
        else:
            lines = matches[0].get("lines", [])
            journal_amount = sum(
                (l.get("debit") or 0) + (l.get("credit") or 0)
                for l in lines
                if str(l.get("compte", "")).startswith(("401", "411"))
            )
            amount_ttc = inv.get("amount_ttc") or 0
            if abs(journal_amount - amount_ttc) > 0.005:
                mismatch.append({
                    "invoice_id": inv_id,
                    "invoice_amount_ttc": amount_ttc,
                    "journal_amount": round(journal_amount, 3),
                })

    return {
        "missing_entry_count": len(missing), "missing_entry": missing[:5],
        "duplicate_entry_count": len(duplicate), "duplicate_entry": duplicate[:5],
        "amount_mismatch_count": len(mismatch), "amount_mismatch": mismatch[:5],
    }


# ── Incidents pour le RAG narratif (Audit Agent, Lot 3) ──────────────────────
# Lecture seule — l'Audit Agent indexe ensuite lui-même dans ChromaDB
# (PCEVectorStore.index_incident), jamais RiskAgent/AnomalyAgent directement.

def risques_created_since_sync(since: datetime | None) -> list[dict]:
    """Risques créés depuis `since` (tous si None) — indexation RAG incrémentale."""
    coll = _get_db()["risques"]
    query = {"created_at": {"$gte": since}} if since else {}
    return list(coll.find(
        query, {"titre": 1, "description": 1, "niveau_criticite": 1, "created_at": 1}
    ))


def invoice_flags_created_since_sync(since: datetime | None) -> list[dict]:
    """Anomalies (ValidationFlagEmbed, embarquées dans invoices.flags) créées
    depuis `since` (toutes si None) — indexation RAG incrémentale.

    $unwind sur un sous-document embarqué d'UNE collection, pas un $lookup
    inter-collections (toujours interdit, cf. NLQueryEngine._is_safe())."""
    coll = _get_db()["invoices"]
    pipeline: list[dict] = [{"$unwind": "$flags"}]
    if since:
        pipeline.append({"$match": {"flags.created_at": {"$gte": since}}})
    pipeline.append({"$project": {
        "flag_id": "$flags.id",
        "invoice_id": "$_id",
        "flag_type": "$flags.flag_type",
        "message": "$flags.message",
        "severity": "$flags.severity",
        "created_at": "$flags.created_at",
    }})
    return list(coll.aggregate(pipeline))


# ── Risk Agent (scan roadmap → création de risques) ──────────────────────────
# RiskAgent._scan_roadmap() est un appelant sync (route FastAPI `def`, job
# APScheduler BackgroundScheduler) — utilise ce module (pymongo synchrone),
# jamais Beanie/Motor. Avant ce lot, _scan_roadmap_async() pontait vers
# Beanie via asyncio.run(), ce qui réutilisait le client Motor partagé
# (créé sur la boucle asyncio principale de FastAPI au démarrage) depuis une
# boucle neuve dans un thread différent — Motor rejette ça avec "Future
# attached to a different loop". Même cause que documentée pour
# InvoiceProcessingOrchestrator/AuditAgent : un appelant sync ne doit jamais
# passer par l'API async de Beanie.

def overdue_roadmap_items_sync(item_id_filter: str | None = None) -> list[dict]:
    """Jalons roadmap en retard (date_fin < aujourd'hui, statut pas terminal),
    optionnellement filtré à un seul jalon."""
    coll = _get_db()["feuilles_de_route"]
    query: dict = {
        "date_fin": {"$lt": _to_midnight_utc(date.today())},
        "statut": {"$nin": ["TERMINE", "ANNULE"]},
    }
    if item_id_filter:
        query["_id"] = str(UUID(item_id_filter))
    return list(coll.find(query))


def existing_ai_risk_for_item_sync(feuille_route_id: str) -> bool:
    """True si un risque IA (created_by="system:ai") encore IDENTIFIE existe
    déjà pour ce jalon — évite les doublons entre deux scans."""
    coll = _get_db()["risques"]
    return coll.find_one({
        "feuille_route_id": feuille_route_id,
        "created_by": "system:ai",
        "statut": "IDENTIFIE",
    }) is not None


def create_risk_sync(risk_data: dict) -> str:
    """Insère un risque IA — écriture brute pymongo (jamais Document(...).insert()),
    _id toujours une chaîne avec tirets (convention CLAUDE.md). Équivalent
    synchrone de service_bridge.create_risk_native() pour ce chemin d'écriture."""
    coll = _get_db()["risques"]
    now = datetime.now(timezone.utc)
    doc = {
        "_id": str(uuid4()),
        "titre": risk_data["titre"],
        "description": risk_data.get("description", ""),
        "type_risque": risk_data.get("type_risque", "AUTRE"),
        "probabilite": risk_data["probabilite"],
        "impact": risk_data["impact"],
        "niveau_criticite": risk_data["niveau_criticite"],
        "statut": risk_data.get("statut", "IDENTIFIE"),
        "plan_mitigation": risk_data.get("plan_mitigation", ""),
        "responsable_id": risk_data.get("responsable_id"),
        "date_identification": _to_midnight_utc(risk_data["date_identification"]),
        "date_echeance_mitigation": _to_midnight_utc(risk_data.get("date_echeance_mitigation")),
        "date_cloture": None,
        "feuille_route_id": risk_data.get("feuille_route_id"),
        "projet_id": risk_data.get("projet_id"),
        "created_by": risk_data.get("created_by", "system:ai"),
        "created_at": now,
        "updated_at": now,
    }
    coll.insert_one(doc)
    return doc["_id"]


# ── Audit Agent (rapport transversal périodique) ─────────────────────────────
# Voir ai_agents/audit_agent.py — l'Audit Agent ne lit QUE ce que les autres
# agents ont déjà écrit ; il ne les appelle jamais directement.

def save_audit_snapshot_sync(snapshot: dict) -> str:
    """Insère un AuditSnapshotDocument — écriture brute pymongo (jamais
    Document(...).insert()), cohérent avec le reste du pipeline synchrone.

    snapshot attend : granularity, period_start, period_end, status, metrics,
    trend, alerts. reconciliation/similar_incidents/narrative_summary
    (Lots 2/3) valent leur défaut si absents.
    """
    coll = _get_db()["audit_snapshots"]
    doc_id = str(uuid4())
    coll.insert_one({
        "_id": doc_id,
        "granularity": snapshot["granularity"],
        "period_start": snapshot["period_start"],
        "period_end": snapshot["period_end"],
        "generated_at": datetime.now(timezone.utc),
        "status": snapshot.get("status", "OK"),
        "metrics": snapshot.get("metrics", {}),
        "trend": snapshot.get("trend", {}),
        "alerts": snapshot.get("alerts", []),
        "reconciliation": snapshot.get("reconciliation", {}),
        "similar_incidents": snapshot.get("similar_incidents", []),
        "narrative_summary": snapshot.get("narrative_summary"),
    })
    return doc_id


def get_latest_snapshot_sync(granularity: str) -> dict | None:
    """Dernier AuditSnapshotDocument pour une granularité donnée (period_start décroissant)."""
    coll = _get_db()["audit_snapshots"]
    rows = list(
        coll.find({"granularity": granularity})
        .sort("period_start", pymongo.DESCENDING)
        .limit(1)
    )
    return rows[0] if rows else None


def list_audit_snapshots_sync(
    granularity: str | None = None, limit: int = 20, skip: int = 0,
) -> list[dict]:
    """Liste des AuditSnapshotDocument, plus récents d'abord — pour
    GET /audit-reports (api/routers/audit_reports.py)."""
    coll = _get_db()["audit_snapshots"]
    query = {"granularity": granularity} if granularity else {}
    return list(
        coll.find(query).sort("period_start", pymongo.DESCENDING).skip(skip).limit(limit)
    )


def count_audit_snapshots_sync(granularity: str | None = None) -> int:
    """Total de AuditSnapshotDocument (filtré par granularité si fourni) —
    pour la pagination de GET /audit-reports."""
    coll = _get_db()["audit_snapshots"]
    query = {"granularity": granularity} if granularity else {}
    return coll.count_documents(query)


def get_audit_snapshot_by_id_sync(snapshot_id: str) -> dict | None:
    """Un AuditSnapshotDocument par id — pour GET /audit-reports/{id}."""
    coll = _get_db()["audit_snapshots"]
    return coll.find_one({"_id": snapshot_id})


# ── Seed helpers (scripts/seed_demo.py) ──────────────────────────────────────
# create_user_sync has no live caller as of the demo-account removal (see
# CLAUDE.md "Section 1 — demo accounts") — kept as a general-purpose helper.
# Domaines sans écrivain Mongo dédié avant Lot A5 — les Documents Beanie
# existent déjà (mongodb.py::_all_document_models()), il ne manquait qu'un
# chemin d'écriture synchrone pour les scripts de seed (pas de boucle asyncio
# à porter, cohérent avec le reste de ce module).

def create_user_sync(
    nom: str, prenom: str, email: str, hashed_password: str,
    role: str, departement: str = "", is_first_login: bool = True,
) -> bool:
    """Retourne False si l'email existe déjà, True si créé."""
    coll = _get_db()["users"]
    if coll.find_one({"email": email}):
        return False
    coll.insert_one({
        "_id": str(uuid4()),
        "nom": nom, "prenom": prenom, "email": email,
        "hashed_password": hashed_password, "role": role, "departement": departement,
        "is_first_login": is_first_login, "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "failed_login_attempts": 0, "locked_until": None, "last_failed_login": None,
        "last_login_at": None, "last_login_ip": None, "profile_picture": None,
    })
    return True


def save_charte_projet_sync(
    id: str, project_id: str, project_name: str, client: str,
    valid_from: date, valid_until: date | None,
    budget_jh: float, taux_jh: float, is_active: bool = True,
) -> bool:
    """Retourne False si `id` existe déjà, True si créé."""
    coll = _get_db()["chartes_projet"]
    if coll.find_one({"_id": id}):
        return False
    coll.insert_one({
        "_id": id, "project_id": project_id, "project_name": project_name,
        "client": client,
        "valid_from": _to_midnight_utc(valid_from),
        "valid_until": _to_midnight_utc(valid_until),
        "budget_jh": budget_jh, "taux_jh": taux_jh, "is_active": is_active,
    })
    return True


def save_phase_sync(
    id: str, project_id: str, name: str, description: str,
    planned_jh: float, consumed_jh: float, status: str,
    closed_date: date | None, livrables: str = "[]",
) -> bool:
    """Retourne False si `id` existe déjà, True si créé."""
    coll = _get_db()["phases"]
    if coll.find_one({"_id": id}):
        return False
    coll.insert_one({
        "_id": id, "project_id": project_id, "name": name, "description": description,
        "planned_jh": planned_jh, "consumed_jh": consumed_jh, "status": status,
        "closed_date": _to_midnight_utc(closed_date), "livrables": livrables,
    })
    return True


def save_livrable_sync(
    phase_id: str, titre: str, description: str,
    date_prevue: date, date_reelle: date | None, statut: str, created_by: str,
) -> None:
    coll = _get_db()["livrables"]
    coll.insert_one({
        "_id": str(uuid4()), "phase_id": phase_id, "titre": titre, "description": description,
        "date_livraison_prevue": _to_midnight_utc(date_prevue),
        "date_livraison_reelle": _to_midnight_utc(date_reelle),
        "statut": statut, "fichier_path": None, "created_by": created_by,
    })


def phase_has_livrables_sync(phase_id: str) -> bool:
    return _get_db()["livrables"].find_one({"phase_id": phase_id}) is not None


def save_ligne_budget_sync(
    projet_id: str, categorie: str, montant_prevu: float,
    montant_consomme: float = 0.0, devise: str = "TND",
) -> bool:
    """Retourne False si une ligne (projet_id, categorie) existe déjà, True si créée."""
    coll = _get_db()["lignes_budget"]
    if coll.find_one({"projet_id": projet_id, "categorie": categorie}):
        return False
    coll.insert_one({
        "_id": str(uuid4()), "projet_id": projet_id, "categorie": categorie,
        "montant_prevu": montant_prevu, "montant_consomme": montant_consomme,
        "devise": devise, "created_at": datetime.now(timezone.utc),
    })
    return True


def save_risque_sync(
    titre: str, description: str, type_risque: str,
    probabilite: str, impact: str, statut: str, plan_mitigation: str,
    responsable_id: str | None, date_identification: date,
    date_echeance_mitigation: date | None, projet_id: str | None,
    created_by: str, feuille_route_id: str | None = None,
) -> bool:
    """Retourne False si un risque (titre) existe déjà, True si créé."""
    from src.services.risk_service import calculate_criticite

    coll = _get_db()["risques"]
    if coll.find_one({"titre": titre}):
        return False
    now = datetime.now(timezone.utc)
    coll.insert_one({
        "_id": str(uuid4()), "titre": titre, "description": description,
        "type_risque": type_risque, "probabilite": probabilite, "impact": impact,
        "niveau_criticite": calculate_criticite(probabilite, impact),
        "statut": statut, "plan_mitigation": plan_mitigation,
        "responsable_id": responsable_id,
        "date_identification": _to_midnight_utc(date_identification),
        "date_echeance_mitigation": _to_midnight_utc(date_echeance_mitigation),
        "date_cloture": None,
        "feuille_route_id": feuille_route_id,
        "projet_id": projet_id,
        "created_by": created_by, "created_at": now, "updated_at": now,
    })
    return True


def save_feuille_de_route_sync(
    titre: str, description: str, date_debut: date, date_fin: date,
    projet_id: str | None, statut: str, priorite: str, annee: int,
    responsable_id: str | None = None,
) -> bool:
    """Retourne False si un item (titre, annee) existe déjà, True si créé."""
    coll = _get_db()["feuilles_de_route"]
    if coll.find_one({"titre": titre, "annee": annee}):
        return False
    coll.insert_one({
        "_id": str(uuid4()), "titre": titre, "description": description,
        "date_debut": _to_midnight_utc(date_debut), "date_fin": _to_midnight_utc(date_fin),
        "projet_id": projet_id, "responsable_id": responsable_id,
        "statut": statut, "priorite": priorite, "annee": annee,
    })
    return True


# ── Classification feedback (PATCH /ai/invoices/{id}/classification) ────────

def save_classification_feedback_sync(
    invoice_id: str, original_compte: str, corrected_compte: str,
    original_catalog_id: str | None, corrected_catalog_id: str | None,
    invoice_text: str, corrected_by: str,
) -> None:
    _get_db()["classification_feedback"].insert_one({
        "_id": str(uuid4()), "invoice_id": invoice_id,
        "original_compte": original_compte, "corrected_compte": corrected_compte,
        "original_catalog_id": original_catalog_id, "corrected_catalog_id": corrected_catalog_id,
        "invoice_text": invoice_text, "corrected_by": corrected_by,
        "corrected_at": datetime.now(timezone.utc),
    })


def count_classification_feedback_sync() -> int:
    return _get_db()["classification_feedback"].count_documents({})
