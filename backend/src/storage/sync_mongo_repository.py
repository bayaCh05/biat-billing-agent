"""Dépôts MongoDB synchrones — pour le pipeline IA (AIOrchestrator + agents).

Pourquoi synchrone : AIOrchestrator.process_invoice() et ses 4 agents sont
délibérément synchrones ("Built as synchronous to match the existing FastAPI +
SQLAlchemy patterns" — voir ai_agents/orchestrator.py), alors que Beanie/Motor
est async-only. Plutôt que de faire remonter async/await dans toute la chaîne
d'agents (et dans le daemon headless qui appelle le même PipelineComponents
partagé — voir agent/pipeline.py), on utilise ici un client pymongo classique
(synchrone), avec les mêmes conventions que le reste de la migration :
_id toujours une chaîne UUID avec tirets, jamais un objet UUID natif BSON.

Ces classes exposent volontairement la MÊME API que leurs équivalents
SQLAlchemy (InvoiceRepository, JournalRepository, AssetRepository,
ClientInvoiceRepository) afin que DuplicateDetector, AnomalyDetector,
InvoiceNumberer, InvoiceBuilder n'aient besoin d'AUCUNE modification — seul
l'objet injecté change.

Portée : uniquement le chemin AIOrchestrator (route API /invoices/upload) et
la génération de factures client (billing.py). Le daemon headless
(scripts/run_agent.py) et Streamlit continuent d'utiliser PipelineComponents
partagé (SQLAlchemy) via agent/pipeline.py — hors périmètre de cette
conversion, volontairement non touché pour ne pas les rendre inconsistants
avec des données Mongo qu'ils ne lisent jamais.
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
from src.models.journal import JournalEntry, JournalLine

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
    de service_bridge.log_audit_event_native(), pour AIOrchestrator._audit_ai()
    (pipeline synchrone — voir le docstring de ce module pour le pourquoi).

    Même collection ("audit_logs"), même formule de row_hash que le chemin async
    (api/security/audit_integrity.py::compute_row_hash_from_doc) — pas de
    dépendance à Motor/Beanie ici, uniquement pymongo synchrone.

    Lève toute exception pymongo à l'appelant — AIOrchestrator._audit_ai() est
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
    """Même API que src.accounting.journal_store.JournalRepository, backend Mongo sync."""

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
    try:
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
        total_checked += 1
        if rows:
            issues.append({
                "type": "UNBALANCED_ENTRIES",
                "count": len(rows),
                "detail": [{"id": r["_id"], "reference": r.get("reference")} for r in rows[:5]],
            })
    except Exception as exc:
        logger.warning("journal_consistency_check_sync_error: %s", exc)

    return {
        "consistency_score": round(1 - len(issues) / max(total_checked, 1), 3),
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
