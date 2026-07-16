"""Pont SQLAlchemy ↔ Beanie pour la migration progressive.

Fournit des fonctions async qui tentent d'abord MongoDB (si disponible)
puis retournent None/False pour signaler le fallback SQLAlchemy — ce
pattern couvre les domaines encore en coexistence (voir CLAUDE.md
"MongoDB Migration Status"). Les domaines déjà bascules Mongo-primaire
utilisent les fonctions *_native de ce module à la place (aucun fallback
SQL, la fonction native fait autorité).

Usage dans une route FastAPI :
    result = await list_roadmap_mongo(annee)
    if result is None:
        # fallback SQLAlchemy
        result = session.execute(select(FeuilleDeRouteORM)...).scalars().all()
"""
from __future__ import annotations

import hmac
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ── Étape 5, Lot 1 : audit_logs (lecture seule) ───────────────────────────────

def _parse_bound_date(v: str) -> datetime:
    """Parse une borne de date (ex: '2026-01-01') en datetime UTC minuit."""
    d = date.fromisoformat(v[:10])
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def list_audit_logs_mongo(
    action: str | None = None,
    resource_type: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    status: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list | None:
    """Retourne les AuditLogDocument correspondant aux filtres, ou None si Mongo indisponible."""
    try:
        from src.storage.documents.audit_log import AuditLogDocument

        query: dict[str, Any] = {}
        if action:
            query["action"] = action.upper()
        if resource_type:
            query["resource_type"] = resource_type
        if user_id:
            query["user_id"] = user_id
        if user_email:
            pattern = re.compile(re.escape(user_email), re.IGNORECASE)
            query["$or"] = [{"user_email": pattern}, {"actor": pattern}]
        if status:
            query["status"] = status.upper()
        date_filter: dict[str, datetime] = {}
        if from_date:
            date_filter["$gte"] = _parse_bound_date(from_date)
        if to_date:
            end = _parse_bound_date(to_date)
            date_filter["$lte"] = end.replace(hour=23, minute=59, second=59)
        if date_filter:
            query["created_at"] = date_filter

        return await (
            AuditLogDocument.find(query)
            .sort("-created_at")
            .skip(offset)
            .limit(limit)
            .to_list()
        )
    except Exception as exc:
        logger.debug("list_audit_logs_mongo: MongoDB indisponible — %s", exc)
        return None


async def resource_history_mongo(
    resource_type: str, resource_id: str, limit: int = 200,
) -> list | None:
    """Historique d'audit d'une ressource, ou None si Mongo indisponible."""
    try:
        from src.storage.documents.audit_log import AuditLogDocument

        query = {
            "resource_type": resource_type,
            "$or": [{"resource_id": resource_id}, {"entity_id": resource_id}],
        }
        return await (
            AuditLogDocument.find(query).sort("-created_at").limit(limit).to_list()
        )
    except Exception as exc:
        logger.debug("resource_history_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 1 : journal_entries (lecture seule) ──────────────────────────

async def list_journal_entries_mongo(
    start: date | None = None, end: date | None = None, limit: int = 200,
) -> list | None:
    """Retourne les JournalEntryDocument (triées comme JournalRepository), ou None."""
    try:
        from src.storage.documents.journal_entry import JournalEntryDocument

        if start and end:
            start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
            end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
            query = {"date_ecriture": {"$gte": start_dt, "$lte": end_dt}}
            return await (
                JournalEntryDocument.find(query).sort("+date_ecriture").to_list()
            )
        return await (
            JournalEntryDocument.find()
            .sort("-date_ecriture")
            .limit(limit)
            .to_list()
        )
    except Exception as exc:
        logger.debug("list_journal_entries_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 1 : kpi (lecture seule) ──────────────────────────────────────

_TERMINAL_STATUSES = ["EXPORTED", "JOURNALED", "PAID", "COLLECTED"]


async def get_kpi_mongo() -> dict | None:
    """Réplique exactement l'agrégation SQL de kpi.get_kpi(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        coll = InvoiceDocument.get_pymongo_collection()

        main = await coll.aggregate([
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "total_ttc": {"$sum": {
                    "$cond": [{"$in": ["$status", _TERMINAL_STATUSES]}, {"$ifNull": ["$amount_ttc", 0]}, 0]
                }},
                "flagged": {"$sum": {"$cond": [{"$eq": ["$status", "FLAGGED"]}, 1, 0]}},
                "pending": {"$sum": {"$cond": [
                    {"$and": [
                        {"$eq": ["$human_review_required", True]},
                        {"$ne": ["$status", "FLAGGED"]},
                    ]}, 1, 0,
                ]}},
                "exposed_ttc": {"$sum": {
                    "$cond": [{"$eq": ["$status", "FLAGGED"]}, {"$ifNull": ["$amount_ttc", 0]}, 0]
                }},
            }},
        ]).to_list(length=1)
        agg = main[0] if main else {}

        status_rows = await coll.aggregate([
            {"$group": {"_id": "$status", "cnt": {"$sum": 1}}},
        ]).to_list(length=None)
        by_status = {r["_id"]: r["cnt"] for r in status_rows}

        auto = await coll.aggregate([
            {"$match": {"status": {"$in": _TERMINAL_STATUSES}}},
            {"$group": {
                "_id": None,
                "total_processed": {"$sum": 1},
                "auto_approved": {"$sum": {"$cond": [{"$eq": ["$human_review_required", False]}, 1, 0]}},
            }},
        ]).to_list(length=1)
        total_processed = auto[0]["total_processed"] if auto else 0
        auto_approved = auto[0]["auto_approved"] if auto else 0

        # Réplique le JOIN SQL : chaque flag DUPLICATE/SUSPECTED_DUPLICATE non résolu
        # ajoute amount_ttc (une facture avec 2 flags qualifiants est comptée 2 fois,
        # comme dans la requête SQL d'origine — comportement reproduit à l'identique).
        blocked = await coll.aggregate([
            {"$unwind": "$flags"},
            {"$match": {
                "flags.flag_type": {"$in": ["DUPLICATE", "SUSPECTED_DUPLICATE"]},
                "flags.resolved": False,
            }},
            {"$group": {"_id": None, "blocked": {"$sum": {"$ifNull": ["$amount_ttc", 0]}}}},
        ]).to_list(length=1)
        blocked_ttc = blocked[0]["blocked"] if blocked else 0

        total = int(agg.get("total") or 0)
        return {
            "total_invoices": total,
            "total_amount_ttc": round(float(agg.get("total_ttc") or 0), 3),
            "auto_approved": auto_approved,
            "auto_approval_rate": round(auto_approved / max(total_processed, 1) * 100, 1),
            "flagged": int(agg.get("flagged") or 0),
            "pending_review": int(agg.get("pending") or 0),
            "by_status": by_status,
            "exposed_amount_ttc": round(float(agg.get("exposed_ttc") or 0), 3),
            "blocked_amount_ttc": round(float(blocked_ttc or 0), 3),
        }
    except Exception as exc:
        logger.debug("get_kpi_mongo: MongoDB indisponible — %s", exc)
        return None


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    return (
        datetime(year, 1, 1, tzinfo=timezone.utc),
        datetime(year + 1, 1, 1, tzinfo=timezone.utc),
    )


async def monthly_spend_mongo(year: int) -> list[dict] | None:
    """Réplique kpi.monthly_spend() (GROUP BY mois, OPEX/CAPEX), ou None."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        coll = InvoiceDocument.get_pymongo_collection()
        start, end = _year_bounds(year)
        rows = await coll.aggregate([
            {"$match": {
                "direction": "SUPPLIER",
                "status": {"$in": _TERMINAL_STATUSES},
                "invoice_date": {"$gte": start, "$lt": end},
            }},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m", "date": "$invoice_date"}},
                "total_ht": {"$sum": {"$ifNull": ["$amount_ht", 0]}},
                "total_ttc": {"$sum": {"$ifNull": ["$amount_ttc", 0]}},
                "cnt": {"$sum": 1},
                "opex": {"$sum": {"$cond": [{"$eq": ["$charge_type", "OPEX"]}, {"$ifNull": ["$amount_ht", 0]}, 0]}},
                "capex": {"$sum": {"$cond": [{"$eq": ["$charge_type", "CAPEX"]}, {"$ifNull": ["$amount_ht", 0]}, 0]}},
            }},
        ]).to_list(length=None)
        return [
            {
                "month": r["_id"],
                "total_ht": round(float(r["total_ht"] or 0), 3),
                "total_ttc": round(float(r["total_ttc"] or 0), 3),
                "invoice_count": int(r["cnt"]),
                "opex": round(float(r["opex"] or 0), 3),
                "capex": round(float(r["capex"] or 0), 3),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("monthly_spend_mongo: MongoDB indisponible — %s", exc)
        return None


async def by_supplier_mongo(year: int | None) -> list[dict] | None:
    """Réplique kpi.by_supplier() (top 10 fournisseurs), ou None."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        coll = InvoiceDocument.get_pymongo_collection()
        match: dict[str, Any] = {
            "direction": "SUPPLIER",
            "status": {"$in": _TERMINAL_STATUSES},
            "issuer_name": {"$ne": None},
        }
        if year:
            start, end = _year_bounds(year)
            match["invoice_date"] = {"$gte": start, "$lt": end}

        rows = await coll.aggregate([
            {"$match": match},
            {"$group": {
                "_id": "$issuer_name",
                "total_ttc": {"$sum": {"$ifNull": ["$amount_ttc", 0]}},
                "total_ht": {"$sum": {"$ifNull": ["$amount_ht", 0]}},
                "cnt": {"$sum": 1},
            }},
            {"$sort": {"total_ttc": -1}},
            {"$limit": 10},
        ]).to_list(length=None)
        return [
            {
                "supplier": r["_id"] or "Inconnu",
                "total_ttc": round(float(r["total_ttc"] or 0), 3),
                "total_ht": round(float(r["total_ht"] or 0), 3),
                "count": int(r["cnt"]),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("by_supplier_mongo: MongoDB indisponible — %s", exc)
        return None


async def by_account_mongo(year: int | None) -> list[dict] | None:
    """Réplique kpi.by_account() (répartition par compte PCE), ou None."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        coll = InvoiceDocument.get_pymongo_collection()
        match: dict[str, Any] = {
            "direction": "SUPPLIER",
            "status": {"$in": _TERMINAL_STATUSES},
            "accounting_compte": {"$ne": None},
        }
        if year:
            start, end = _year_bounds(year)
            match["invoice_date"] = {"$gte": start, "$lt": end}

        rows = await coll.aggregate([
            {"$match": match},
            {"$group": {
                "_id": {"compte": "$accounting_compte", "label": "$accounting_label"},
                "total_ht": {"$sum": {"$ifNull": ["$amount_ht", 0]}},
            }},
            {"$sort": {"total_ht": -1}},
        ]).to_list(length=None)
        grand_total = sum(float(r["total_ht"] or 0) for r in rows) or 1.0
        return [
            {
                "compte": r["_id"]["compte"] or "",
                "label": r["_id"]["label"] or r["_id"]["compte"] or "",
                "total_ht": round(float(r["total_ht"] or 0), 3),
                "pct": round(float(r["total_ht"] or 0) / grand_total * 100, 1),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("by_account_mongo: MongoDB indisponible — %s", exc)
        return None


async def analytics_kpis_mongo(year: int) -> dict | None:
    """Réplique kpi.analytics_kpis() (délai moyen, taux de rejet/revue, CAPEX/OPEX), ou None."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        coll = InvoiceDocument.get_pymongo_collection()
        start, end = _year_bounds(year)

        proc = await coll.aggregate([
            {"$match": {
                "exported_at": {"$ne": None}, "received_at": {"$ne": None}, "direction": "SUPPLIER",
            }},
            {"$group": {
                "_id": None,
                "avg_days": {"$avg": {"$divide": [
                    {"$subtract": ["$exported_at", "$received_at"]}, 1000 * 60 * 60 * 24,
                ]}},
            }},
        ]).to_list(length=1)
        avg_days = round(float(proc[0]["avg_days"] or 0), 1) if proc else 0.0

        counts = await coll.aggregate([
            {"$match": {"invoice_date": {"$gte": start, "$lt": end}, "direction": "SUPPLIER"}},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "rejected": {"$sum": {"$cond": [{"$eq": ["$status", "REJECTED"]}, 1, 0]}},
                "reviewed": {"$sum": {"$cond": [{"$eq": ["$human_review_required", True]}, 1, 0]}},
            }},
        ]).to_list(length=1)
        total = int(counts[0]["total"]) if counts else 0
        total = total or 1
        rejection_rate = round((int(counts[0]["rejected"]) if counts else 0) / total * 100, 1)
        human_review_rate = round((int(counts[0]["reviewed"]) if counts else 0) / total * 100, 1)

        capex_opex = await coll.aggregate([
            {"$match": {
                "invoice_date": {"$gte": start, "$lt": end},
                "status": {"$in": _TERMINAL_STATUSES},
                "direction": "SUPPLIER",
            }},
            {"$group": {
                "_id": None,
                "capex": {"$sum": {"$cond": [{"$eq": ["$charge_type", "CAPEX"]}, {"$ifNull": ["$amount_ht", 0]}, 0]}},
                "opex": {"$sum": {"$cond": [{"$eq": ["$charge_type", "OPEX"]}, {"$ifNull": ["$amount_ht", 0]}, 0]}},
            }},
        ]).to_list(length=1)
        total_capex = round(float(capex_opex[0]["capex"] or 0), 3) if capex_opex else 0.0
        total_opex = round(float(capex_opex[0]["opex"] or 0), 3) if capex_opex else 0.0

        excluded = ["REJECTED", "ERROR", "EXTRACTION_FAILED", "ESCALATED"]
        pending_count = await coll.count_documents({
            "status": {"$nin": _TERMINAL_STATUSES + excluded},
            "direction": "SUPPLIER",
        })

        return {
            "avg_processing_days": avg_days,
            "rejection_rate": rejection_rate,
            "human_review_rate": human_review_rate,
            "total_capex_ytd": total_capex,
            "total_opex_ytd": total_opex,
            "pending_count": int(pending_count),
        }
    except Exception as exc:
        logger.debug("analytics_kpis_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 1 : suivi (lecture seule) ────────────────────────────────────

_CONFIDENCE_FIELD_NAMES = [
    "issuer_name", "issuer_tax_id",
    "recipient_name", "recipient_tax_id",
    "invoice_number", "invoice_date", "due_date",
    "amount_ht", "tva_rate", "tva_amount", "amount_ttc",
]


def _invoice_doc_to_record(doc) -> Any:
    """Convertit un InvoiceDocument (Beanie) en InvoiceRecord Pydantic.

    Miroir de InvoiceRepository._to_pydantic() — même structure de sortie,
    pour que le code appelant (ageing, InvoiceSummary.from_record) fonctionne
    sans changement, que la source soit SQLAlchemy ou MongoDB.
    """
    from src.models.enums import (
        ChargeNature, ChargeType, ExtractionMethod, FlagSeverity, FlagType, InvoiceDirection,
    )
    from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
    from src.models.enums import InvoiceStatus

    now = datetime.now(tz=timezone.utc)
    invoice = InvoiceRecord(
        id=doc.id,
        file_hash=doc.file_hash,
        raw_file_path=doc.raw_file_path,
        file_mime_type=doc.file_mime_type,
        direction=InvoiceDirection(doc.direction),
        status=InvoiceStatus(doc.status),
        extraction_method=ExtractionMethod(doc.extraction_method) if doc.extraction_method else None,
        retry_count=doc.retry_count,
        last_error=doc.last_error,
        currency=doc.currency,
        raw_extracted_json=doc.raw_extracted_json,
        cost_catalog_id=doc.cost_catalog_id,
        accounting_compte=doc.accounting_compte,
        accounting_label=doc.accounting_label,
        charge_nature=ChargeNature(doc.charge_nature) if doc.charge_nature else None,
        charge_type=ChargeType(doc.charge_type) if doc.charge_type else None,
        matched_po_id=doc.matched_po_id,
        matched_contract_id=doc.matched_contract_id,
        matched_client_id=doc.matched_client_id,
        payment_term_days=doc.payment_term_days,
        classification_reason=doc.classification_reason,
        classification_pass=doc.classification_pass,
        human_review_required=doc.human_review_required,
        human_review_notes=doc.human_review_notes,
        reviewed_by=doc.reviewed_by,
        reviewed_at=doc.reviewed_at,
        received_at=doc.received_at or now,
        extracted_at=doc.extracted_at,
        classified_at=doc.classified_at,
        validated_at=doc.validated_at,
        exported_at=doc.exported_at,
        export_reference=doc.export_reference,
        paid_at=doc.paid_at,
        collected_at=doc.collected_at,
        created_at=doc.created_at or now,
        updated_at=doc.updated_at or now,
    )

    for field_name in _CONFIDENCE_FIELD_NAMES:
        value = getattr(doc, field_name)
        confidence = getattr(doc, f"{field_name}_conf", None) or 0.0
        setattr(invoice, field_name, ConfidenceField(value=value, confidence=confidence))

    invoice.line_items = [
        LineItem(
            line_number=li.line_number,
            description=li.description,
            quantity=li.quantity,
            unit_price=li.unit_price,
            line_total=li.line_total,
            tva_rate=li.tva_rate,
        )
        for li in doc.line_items
    ]

    invoice.flags = [
        ValidationFlag(
            flag_type=FlagType(f.flag_type),
            severity=FlagSeverity(f.severity),
            field_name=f.field_name,
            message=f.message,
            resolved=f.resolved,
            resolved_at=f.resolved_at,
            resolved_by=f.resolved_by,
        )
        for f in doc.flags
    ]

    return invoice


async def get_suivi_invoices_mongo() -> dict | None:
    """Retourne {pending_payment, pending_collection, overdue} en InvoiceRecord, ou None.

    Réplique InvoiceRepository.get_pending_payment/get_pending_collection/get_overdue().
    """
    try:
        from src.storage.documents.invoice import InvoiceDocument

        today = datetime.now(tz=timezone.utc)
        today_midnight = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)

        pending_payment = await InvoiceDocument.find({
            "direction": "SUPPLIER", "status": "EXPORTED", "paid_at": None,
        }).to_list()
        pending_collection = await InvoiceDocument.find({
            "direction": "CLIENT", "status": "EXPORTED", "collected_at": None,
        }).to_list()
        overdue = await InvoiceDocument.find({
            "due_date": {"$lt": today_midnight}, "paid_at": None, "status": "EXPORTED",
        }).to_list()

        return {
            "pending_payment": [_invoice_doc_to_record(d) for d in pending_payment],
            "pending_collection": [_invoice_doc_to_record(d) for d in pending_collection],
            "overdue": [_invoice_doc_to_record(d) for d in overdue],
        }
    except Exception as exc:
        logger.debug("get_suivi_invoices_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 2 : projects / roadmap / livrables / risks (lecture seule) ──

async def _consumed_jh_by_project() -> dict[str, float]:
    from src.storage.documents.phase import PhaseDocument

    coll = PhaseDocument.get_pymongo_collection()
    rows = await coll.aggregate([
        {"$group": {"_id": "$project_id", "total": {"$sum": "$consumed_jh"}}},
    ]).to_list(length=None)
    return {r["_id"]: r["total"] for r in rows}


async def list_projects_mongo() -> list[dict] | None:
    """Réplique projects.list_projects(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.charte_projet import CharteProjetDocument

        chartes = await CharteProjetDocument.find().sort("-valid_from").to_list()
        consumed_by_project = await _consumed_jh_by_project()

        result = []
        for c in chartes:
            consumed_jh = consumed_by_project.get(c.project_id, 0.0)
            result.append({
                "id": c.project_id, "name": c.project_name, "client": c.client,
                "budget_jh": c.budget_jh, "consumed_jh": consumed_jh, "taux_jh": c.taux_jh,
                "status": "ACTIVE" if c.is_active else "COMPLETED",
                "start_date": c.valid_from.isoformat(),
                "end_date": c.valid_until.isoformat() if c.valid_until else None,
                "budget_tnd": round(c.budget_jh * c.taux_jh, 3),
                "spent_tnd": round(consumed_jh * c.taux_jh, 3),
            })
        return result
    except Exception as exc:
        logger.debug("list_projects_mongo: MongoDB indisponible — %s", exc)
        return None


async def get_project_mongo(project_id: str) -> dict | None:
    """Réplique projects.get_project(), ou None si Mongo indisponible.

    Retourne {} si Mongo est disponible mais le projet n'existe pas (404 côté route).
    """
    try:
        from src.storage.documents.charte_projet import CharteProjetDocument
        from src.storage.documents.phase import PhaseDocument

        charte = await CharteProjetDocument.find_one({"project_id": project_id})
        if charte is None:
            return {}

        coll = PhaseDocument.get_pymongo_collection()
        agg = await coll.aggregate([
            {"$match": {"project_id": project_id}},
            {"$group": {"_id": None, "total": {"$sum": "$consumed_jh"}}},
        ]).to_list(length=1)
        consumed_jh = agg[0]["total"] if agg else 0.0

        return {
            "id": charte.project_id, "name": charte.project_name, "client": charte.client,
            "budget_jh": charte.budget_jh, "consumed_jh": consumed_jh, "taux_jh": charte.taux_jh,
            "status": "ACTIVE" if charte.is_active else "COMPLETED",
            "start_date": charte.valid_from.isoformat(),
            "end_date": charte.valid_until.isoformat() if charte.valid_until else None,
            "budget_tnd": round(charte.budget_jh * charte.taux_jh, 3),
            "spent_tnd": round(consumed_jh * charte.taux_jh, 3),
        }
    except Exception as exc:
        logger.debug("get_project_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_phases_mongo(project_id: str) -> list | None:
    """Réplique projects.list_phases() (PhaseDocument bruts), ou None."""
    try:
        from src.storage.documents.phase import PhaseDocument

        return await (
            PhaseDocument.find({"project_id": project_id}).sort("+id").to_list()
        )
    except Exception as exc:
        logger.debug("list_phases_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_roadmap_mongo(annee: int) -> list | None:
    """Réplique roadmap.list_roadmap() (FeuilleDeRouteDocument bruts), ou None."""
    try:
        from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument

        return await (
            FeuilleDeRouteDocument.find({"annee": annee}).sort("+date_debut").to_list()
        )
    except Exception as exc:
        logger.debug("list_roadmap_mongo: MongoDB indisponible — %s", exc)
        return None


_CRITICITE_NUM_BRIDGE = {4: "CRITIQUE", 3: "ELEVEE", 2: "MOYENNE", 1: "FAIBLE"}
_CRITICITE_TO_NUM_BRIDGE = {"CRITIQUE": 4, "ELEVEE": 3, "MOYENNE": 2, "FAIBLE": 1}


async def list_roadmap_with_risks_mongo(annee: int) -> dict | None:
    """Réplique roadmap.list_roadmap_with_risks() : items + résumé risques, ou None."""
    try:
        from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument
        from src.storage.documents.risque import RisqueDocument

        items = await (
            FeuilleDeRouteDocument.find({"annee": annee}).sort("+date_debut").to_list()
        )

        coll = RisqueDocument.get_pymongo_collection()
        risk_rows = await coll.aggregate([
            {"$match": {"feuille_route_id": {"$ne": None}}},
            {"$group": {
                "_id": "$feuille_route_id",
                "risk_count": {"$sum": 1},
                "max_criticite_num": {"$max": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": ["$niveau_criticite", "CRITIQUE"]}, "then": 4},
                            {"case": {"$eq": ["$niveau_criticite", "ELEVEE"]}, "then": 3},
                            {"case": {"$eq": ["$niveau_criticite", "MOYENNE"]}, "then": 2},
                            {"case": {"$eq": ["$niveau_criticite", "FAIBLE"]}, "then": 1},
                        ],
                        "default": 0,
                    }
                }},
            }},
        ]).to_list(length=None)

        risk_by_item = {
            str(r["_id"]): {
                "count": r["risk_count"],
                "highest_criticite": _CRITICITE_NUM_BRIDGE.get(r["max_criticite_num"]),
            }
            for r in risk_rows
        }
        return {"items": items, "risk_by_item": risk_by_item}
    except Exception as exc:
        logger.debug("list_roadmap_with_risks_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_livrables_mongo(phase_id: str) -> list | None:
    """Réplique livrables.list_livrables(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.livrable import LivrableDocument

        return await (
            LivrableDocument.find({"phase_id": phase_id})
            .sort("+date_livraison_prevue")
            .to_list()
        )
    except Exception as exc:
        logger.debug("list_livrables_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_risks_mongo(
    projet_id: str | None = None,
    feuille_route_id: str | None = None,
    statut: str | None = None,
    niveau_criticite: str | None = None,
) -> list | None:
    """Réplique risks.list_risks(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.risque import RisqueDocument

        query: dict[str, Any] = {}
        if projet_id:
            query["projet_id"] = projet_id
        if feuille_route_id:
            query["feuille_route_id"] = str(UUID(feuille_route_id))
        if statut:
            query["statut"] = statut
        if niveau_criticite:
            query["niveau_criticite"] = niveau_criticite
        return await RisqueDocument.find(query).sort("-created_at").to_list()
    except Exception as exc:
        logger.debug("list_risks_mongo: MongoDB indisponible — %s", exc)
        return None


async def risk_summary_mongo() -> dict | None:
    """Réplique risk_service.get_risk_summary(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.risque import RisqueDocument

        all_risks = await RisqueDocument.find().to_list()
        today = date.today()

        by_criticite: dict[str, int] = {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0}
        by_statut: dict[str, int] = {}
        overdue: list[dict] = []

        for r in all_risks:
            if r.statut != "CLOTURE":
                by_criticite[r.niveau_criticite] = by_criticite.get(r.niveau_criticite, 0) + 1
            by_statut[r.statut] = by_statut.get(r.statut, 0) + 1
            if (
                r.statut not in ("CLOTURE", "MAITRISE")
                and r.date_echeance_mitigation
                and r.date_echeance_mitigation < today
            ):
                overdue.append({
                    "id": str(r.id), "titre": r.titre,
                    "date_echeance_mitigation": r.date_echeance_mitigation.isoformat(),
                })

        top_critical = sorted(
            [r for r in all_risks if r.niveau_criticite == "CRITIQUE" and r.statut not in ("CLOTURE", "MAITRISE")],
            key=lambda r: r.created_at,
            reverse=True,
        )[:5]

        return {
            "by_criticite": by_criticite,
            "by_statut": by_statut,
            "overdue": overdue,
            "top_critical": [
                {"id": str(r.id), "titre": r.titre, "statut": r.statut, "projet_id": r.projet_id}
                for r in top_critical
            ],
            "total_active": sum(by_criticite.values()),
        }
    except Exception as exc:
        logger.debug("risk_summary_mongo: MongoDB indisponible — %s", exc)
        return None


async def risks_par_projet_mongo() -> list | None:
    """Réplique risks.risks_par_projet(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.risque import RisqueDocument
        from src.storage.documents.charte_projet import CharteProjetDocument

        risks = await (
            RisqueDocument.find({"projet_id": {"$ne": None}})
            .sort("+projet_id", "-created_at")
            .to_list()
        )
        chartes = await CharteProjetDocument.find().to_list()
        proj_names = {c.project_id: c.project_name for c in chartes}

        grouped: dict[str, list] = {}
        for r in risks:
            grouped.setdefault(r.projet_id, []).append(r)

        result = []
        for projet_id, proj_risks in grouped.items():
            by_criticite: dict[str, int] = {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0}
            for r in proj_risks:
                by_criticite[r.niveau_criticite] = by_criticite.get(r.niveau_criticite, 0) + 1
            result.append({
                "projet_id": projet_id,
                "project_name": proj_names.get(projet_id, projet_id),
                "total": len(proj_risks),
                "by_criticite": by_criticite,
                "risks": proj_risks,
            })

        _order = {"CRITIQUE": 3, "ELEVEE": 2, "MOYENNE": 1, "FAIBLE": 0}
        result.sort(
            key=lambda g: max((_order.get(c, 0) * n) for c, n in g["by_criticite"].items()),
            reverse=True,
        )
        return result
    except Exception as exc:
        logger.debug("risks_par_projet_mongo: MongoDB indisponible — %s", exc)
        return None


async def risks_for_roadmap_mongo(feuille_route_id: str) -> list | None:
    """Réplique risk_service.get_risks_for_roadmap_item(), ou None."""
    try:
        from src.storage.documents.risque import RisqueDocument

        return await (
            RisqueDocument.find({
                "feuille_route_id": str(UUID(feuille_route_id)),
                "statut": {"$ne": "CLOTURE"},
            }).sort("-created_at").to_list()
        )
    except Exception as exc:
        logger.debug("risks_for_roadmap_mongo: MongoDB indisponible — %s", exc)
        return None


async def risks_for_project_mongo(projet_id: str) -> list | None:
    """Réplique risk_service.get_risks_for_project(), ou None."""
    try:
        from src.storage.documents.risque import RisqueDocument

        return await (
            RisqueDocument.find({
                "projet_id": projet_id,
                "statut": {"$ne": "CLOTURE"},
            }).sort("-created_at").to_list()
        )
    except Exception as exc:
        logger.debug("risks_for_project_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 3 : notifications (100% Mongo — plus de source SQLite) ──────

_NOTIFICATION_TYPE_LABELS = {
    "INVOICE_FLAGGED":   "Facture signalée",
    "INVOICE_ESCALATED": "Facture escaladée",
    "PAYMENT_OVERDUE":   "Paiement en retard",
    "BUDGET_EXCEEDED":   "Budget dépassé",
}


async def _ensure_invoice_notification_native(invoice_id: UUID, issuer: str | None, status: str) -> None:
    """Crée une notification pour une facture signalée si elle n'existe pas déjà.

    100% Mongo : InvoiceDocument est déjà la source primaire des factures, et
    NotificationDocument sert à la fois de source de vérité pour la dédup et
    de store de lecture (list/count) — plus de SQLAlchemy dans ce chemin.
    """
    from src.storage.documents.notification import NotificationDocument

    existing = await NotificationDocument.find_one({"invoice_id": str(invoice_id)})
    if existing:
        return

    notif_type = "INVOICE_ESCALATED" if status == "ESCALATED" else "INVOICE_FLAGGED"
    label = issuer or "Fournisseur inconnu"

    # Insertion via pymongo brut (pas Document.insert()) : Beanie encoderait
    # les champs UUID en BSON Binary natif, alors que le reste de la migration
    # stocke tous les _id/soft-refs comme des chaînes (voir "Conventions" —
    # CLAUDE.md). Mélanger les deux formats casserait toute requête future
    # filtrant par _id ou invoice_id.
    coll = NotificationDocument.get_pymongo_collection()
    await coll.insert_one({
        "_id": str(uuid4()),
        "type": notif_type,
        "title": f"{_NOTIFICATION_TYPE_LABELS[notif_type]} — {label}",
        "body": f"La facture de {label} requiert une révision humaine (statut : {status}).",
        "is_read": False,
        "created_at": datetime.now(timezone.utc),
        "invoice_id": str(invoice_id),
    })


async def sync_flagged_invoices_mirrored(session=None) -> None:
    """Crée les notifications manquantes pour les factures signalées.

    `session` n'est plus utilisé — conservé uniquement pour ne pas casser les
    appelants existants (routes notifications.py) tant qu'ils n'ont pas été
    nettoyés (Lot B, suppression SQLAlchemy).
    """
    from src.models.enums import InvoiceStatus
    from src.storage.documents.invoice import InvoiceDocument

    terminal = {InvoiceStatus.REJECTED.value, InvoiceStatus.ERROR.value}
    docs = await InvoiceDocument.find({
        "human_review_required": True,
        "status": {"$nin": list(terminal)},
    }).to_list()

    for inv in docs:
        await _ensure_invoice_notification_native(inv.id, inv.issuer_name, inv.status)


async def list_notifications_mongo() -> list | None:
    """Réplique notifications.list_notifications() (non lues d'abord), ou None."""
    try:
        from src.storage.documents.notification import NotificationDocument

        return await (
            NotificationDocument.find()
            .sort("+is_read", "-created_at")
            .to_list()
        )
    except Exception as exc:
        logger.debug("list_notifications_mongo: MongoDB indisponible — %s", exc)
        return None


async def count_unread_notifications_mongo() -> int | None:
    """Réplique notifications.get_count(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.notification import NotificationDocument

        return await NotificationDocument.find({"is_read": False}).count()
    except Exception as exc:
        logger.debug("count_unread_notifications_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 3 : review (lecture seule) ───────────────────────────────────

async def get_review_queue_mongo() -> list | None:
    """Réplique InvoiceRepository.get_review_queue(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        docs = await (
            InvoiceDocument.find({
                "$or": [
                    {"status": "FLAGGED"},
                    {"human_review_required": True},
                ],
            }).sort("+received_at").to_list()
        )
        return [_invoice_doc_to_record(d) for d in docs]
    except Exception as exc:
        logger.debug("get_review_queue_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 4 : capex / projet_budget / budget (lecture seule) ──────────

def _asset_doc_to_pydantic(doc) -> Any:
    """Convertit un AssetDocument en Asset Pydantic (miroir de AssetRepository._to_pydantic)."""
    from src.models.asset import Asset

    return Asset(
        id=doc.id,
        designation=doc.designation,
        compte_immobilisation=doc.compte_immobilisation,
        compte_amortissement=doc.compte_amortissement,
        acquisition_date=doc.acquisition_date,
        acquisition_cost_ht=doc.acquisition_cost_ht,
        useful_life_years=doc.useful_life_years,
        depreciation_method=doc.depreciation_method,
        supplier_invoice_id=doc.supplier_invoice_id,
        amortization_source=doc.amortization_source,
        notes=doc.notes or "",
        created_at=doc.created_at,
    )


async def list_assets_mongo(include_fully_depreciated: bool) -> list | None:
    """Réplique AssetRepository.list_all(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.asset import AssetDocument

        query: dict[str, Any] = {}
        if not include_fully_depreciated:
            query["fully_depreciated"] = False
        docs = await AssetDocument.find(query).sort("-acquisition_date").to_list()
        return [_asset_doc_to_pydantic(d) for d in docs]
    except Exception as exc:
        logger.debug("list_assets_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_budget_lines_mongo(projet_id: str) -> list | None:
    """Réplique projet_budget.list_budget() (LigneBudgetDocument bruts), ou None."""
    try:
        from src.storage.documents.ligne_budget import LigneBudgetDocument

        return await (
            LigneBudgetDocument.find({"projet_id": projet_id}).sort("+created_at").to_list()
        )
    except Exception as exc:
        logger.debug("list_budget_lines_mongo: MongoDB indisponible — %s", exc)
        return None


async def budget_synthese_mongo(projet_id: str) -> dict | None:
    """Réplique projet_budget.budget_synthese(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.ligne_budget import LigneBudgetDocument

        coll = LigneBudgetDocument.get_pymongo_collection()
        agg = await coll.aggregate([
            {"$match": {"projet_id": projet_id}},
            {"$group": {
                "_id": None,
                "total_prevu": {"$sum": "$montant_prevu"},
                "total_consomme": {"$sum": "$montant_consomme"},
            }},
        ]).to_list(length=1)
        total_prevu = agg[0]["total_prevu"] if agg else 0.0
        total_consomme = agg[0]["total_consomme"] if agg else 0.0
        ecart = total_prevu - total_consomme
        taux = round(total_consomme / total_prevu * 100, 1) if total_prevu > 0 else 0.0
        return {
            "total_prevu": total_prevu, "total_consomme": total_consomme,
            "ecart": ecart, "taux_consommation": taux,
        }
    except Exception as exc:
        logger.debug("budget_synthese_mongo: MongoDB indisponible — %s", exc)
        return None


async def budget_summary_mongo(plan, year: int, through_month: int) -> dict | None:
    """Réplique BudgetTracker.summary()/ytd_variance(), ou None si Mongo indisponible.

    `plan` (BudgetPlan) est chargé depuis le YAML — inchangé, pas de dépendance Mongo.
    Seules les données réelles (dépenses factures) sont lues depuis MongoDB.
    """
    try:
        from src.budget.budget_tracker import MonthlyVariance, YearVariance
        from src.storage.documents.invoice import InvoiceDocument

        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_month_last_day = _last_day_of_month(year, through_month)
        end = datetime(
            end_month_last_day.year, end_month_last_day.month, end_month_last_day.day,
            23, 59, 59, tzinfo=timezone.utc,
        )

        coll = InvoiceDocument.get_pymongo_collection()
        rows = await coll.aggregate([
            {"$match": {
                "status": {"$in": ["VALIDATED", "EXPORTED", "PAID", "JOURNALED"]},
                "direction": "SUPPLIER",
                "invoice_date": {"$gte": start, "$lte": end},
                "cost_catalog_id": {"$ne": None},
                "amount_ht": {"$ne": None},
            }},
            {"$group": {
                "_id": {
                    "catalog_id": "$cost_catalog_id",
                    "month": {"$month": "$invoice_date"},
                },
                "total": {"$sum": "$amount_ht"},
            }},
        ]).to_list(length=None)

        actuals_by_month: dict[int, dict[str, float]] = {m: {} for m in range(1, through_month + 1)}
        for r in rows:
            m = r["_id"]["month"]
            actuals_by_month.setdefault(m, {})[r["_id"]["catalog_id"]] = float(r["total"] or 0)

        variances: list = []
        for line in plan.lines:
            monthly_variances = [
                MonthlyVariance(
                    catalog_id=line.catalog_id, label=line.label, year=year, month=m,
                    budget=line.budget_for_month(m),
                    actual=actuals_by_month.get(m, {}).get(line.catalog_id, 0.0),
                )
                for m in range(1, through_month + 1)
            ]
            variances.append(YearVariance(
                catalog_id=line.catalog_id, label=line.label, year=year, through_month=through_month,
                budget_ytd=line.budget_ytd(through_month),
                actual_ytd=sum(mv.actual for mv in monthly_variances),
                monthly=monthly_variances,
            ))

        total_budget = sum(yv.budget_ytd for yv in variances)
        total_actual = sum(yv.actual_ytd for yv in variances)
        over_lines = [yv for yv in variances if yv.status == "over"]
        warning_lines = [yv for yv in variances if yv.status == "warning"]

        summary = {
            "year": year, "through_month": through_month,
            "total_budget_ytd": round(total_budget, 3),
            "total_actual_ytd": round(total_actual, 3),
            "total_variance_ytd": round(total_actual - total_budget, 3),
            "variance_pct": round(((total_actual - total_budget) / total_budget * 100) if total_budget else 0, 2),
            "lines_over_budget": len(over_lines),
            "lines_warning": len(warning_lines),
        }
        return {"summary": summary, "variances": variances}
    except Exception as exc:
        logger.debug("budget_summary_mongo: MongoDB indisponible — %s", exc)
        return None


def _last_day_of_month(year: int, month: int) -> date:
    from src.utils.date_utils import last_day_of_month
    return last_day_of_month(year, month)


async def get_budget_plan_entries_mongo(year: int) -> list | None:
    """Réplique budget.get_budget_plan_entries() (BudgetPlanDocument bruts), ou None."""
    try:
        from src.storage.documents.budget_plan import BudgetPlanDocument

        return await (
            BudgetPlanDocument.find({"year": year}).sort("+catalog_id").to_list()
        )
    except Exception as exc:
        logger.debug("get_budget_plan_entries_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 5 : invoices / billing / payments (lecture seule) ──────────

async def list_invoices_mongo(limit: int) -> list | None:
    """Réplique InvoiceRepository.list_all(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.invoice import InvoiceDocument

        docs = await (
            InvoiceDocument.find().sort("-received_at").limit(limit).to_list()
        )
        return [_invoice_doc_to_record(d) for d in docs]
    except Exception as exc:
        logger.debug("list_invoices_mongo: MongoDB indisponible — %s", exc)
        return None


async def get_invoice_mongo(invoice_id) -> Any:
    """Réplique InvoiceRepository.get_by_id(), ou None si Mongo indisponible.

    Retourne l'objet sentinel _NOT_FOUND si Mongo répond mais la facture n'existe pas
    (pour distinguer "Mongo down" de "facture absente" côté route).

    Note : le script de migration stocke tous les _id comme des chaînes
    (str(_uuid(...))), alors que les modèles Beanie déclarent `id: UUID`.
    Document.get(uuid) interroge avec un objet UUID natif (BSON Binary) et ne
    matche donc jamais ces documents migrés — d'où find_one({"_id": str(...)})
    plutôt que InvoiceDocument.get(). Cette même précaution est nécessaire
    partout où un _id est recherché par valeur UUID (voir Étape 6 si les
    écritures Mongo natives remplacent un jour les _id texte du script).
    """
    try:
        from src.storage.documents.invoice import InvoiceDocument

        doc = await InvoiceDocument.find_one({"_id": str(invoice_id)})
        if doc is None:
            return _NOT_FOUND
        return _invoice_doc_to_record(doc)
    except Exception as exc:
        logger.debug("get_invoice_mongo: MongoDB indisponible — %s", exc)
        return None


class _NotFoundSentinel:
    def __repr__(self) -> str:
        return "<NOT_FOUND>"


_NOT_FOUND = _NotFoundSentinel()


async def get_journal_entry_for_invoice_mongo(invoice_id: str) -> dict | None:
    """Réplique la jointure journal_entries+journal_lines de get_pipeline_status(), ou None.

    source_invoice_id est stocké comme chaîne par le script de migration —
    voir la note dans get_invoice_mongo() sur les _id/soft-refs UUID en texte.
    """
    try:
        from src.storage.documents.journal_entry import JournalEntryDocument

        entry = await JournalEntryDocument.find_one({"source_invoice_id": str(invoice_id)})
        if entry is None:
            return {}

        lines = sorted(entry.lines, key=lambda ln: ln.debit or 0, reverse=True)
        total_debit = sum(float(ln.debit or 0) for ln in lines)
        total_credit = sum(float(ln.credit or 0) for ln in lines)
        is_balanced = abs(total_debit - total_credit) < 0.005
        return {
            # Sans tirets pour matcher le format renvoyé par la requête SQL brute
            # (rows[0][0] tel que stocké en SQLite, sans passer par le type UUID ORM).
            "id": str(entry.id).replace("-", ""),
            "reference": entry.reference,
            "date_ecriture": str(entry.date_ecriture),
            "description": entry.description,
            "accounting_explanation": entry.accounting_explanation,
            "is_balanced": is_balanced,
            "lines": [
                {
                    "compte": ln.compte or "", "libelle": ln.libelle or "",
                    "debit": float(ln.debit or 0), "credit": float(ln.credit or 0),
                }
                for ln in lines
            ],
            "summary": f"Écriture {entry.reference} — {'équilibrée ✓' if is_balanced else 'DÉSÉQUILIBRÉE ⚠'}",
        }
    except Exception as exc:
        logger.debug("get_journal_entry_for_invoice_mongo: MongoDB indisponible — %s", exc)
        return None


def _client_invoice_doc_to_pydantic(doc) -> Any:
    """Convertit un ClientInvoiceDocument en ClientInvoice Pydantic."""
    from src.models.client_invoice import ClientInvoice, ClientInvoiceStatus, ClientLineItem

    return ClientInvoice(
        id=doc.id,
        invoice_number=doc.invoice_number,
        invoice_date=doc.invoice_date,
        due_date=doc.due_date,
        issuer_name=doc.issuer_name,
        issuer_tax_id=doc.issuer_tax_id,
        issuer_address=doc.issuer_address or "",
        client_id=doc.client_id,
        client_name=doc.client_name,
        client_tax_id=doc.client_tax_id,
        client_address=doc.client_address or "",
        line_items=[
            ClientLineItem(
                description=li.description, quantity=li.quantity, unit_price=li.unit_price,
                line_total=li.line_total, tva_rate=li.tva_rate, tva_amount=li.tva_amount,
                compte_produit=li.compte_produit,
            )
            for li in doc.line_items
        ],
        amount_ht=doc.amount_ht,
        tva_amount=doc.tva_amount,
        amount_ttc=doc.amount_ttc,
        status=ClientInvoiceStatus(doc.status),
        source_template_id=doc.source_template_id,
        notes=doc.notes,
        pdf_path=doc.pdf_path,
        created_at=doc.created_at or datetime.now(timezone.utc),
        sent_at=doc.sent_at,
        paid_at=doc.paid_at,
    )


async def list_client_invoices_mongo() -> list | None:
    """Réplique ClientInvoiceRepository.list_all(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.client_invoice import ClientInvoiceDocument

        docs = await ClientInvoiceDocument.find().sort("-invoice_date").to_list()
        return [_client_invoice_doc_to_pydantic(d) for d in docs]
    except Exception as exc:
        logger.debug("list_client_invoices_mongo: MongoDB indisponible — %s", exc)
        return None


async def get_installments_summary_mongo() -> dict | None:
    """Réplique payments.get_summary(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.payment_installment import PaymentInstallmentDocument

        today = date.today()
        docs = await PaymentInstallmentDocument.find().to_list()

        total = len(docs)
        late = [d for d in docs if d.status == "LATE"]
        pending = [d for d in docs if d.status == "PENDING"]
        paid = [d for d in docs if d.status == "PAID"]
        total_penalties = sum((d.current_amount or 0) - (d.base_amount or 0) for d in late)

        upcoming = [d for d in pending if d.due_date and d.due_date >= today]
        upcoming.sort(key=lambda d: d.due_date)
        next_due_date = upcoming[0].due_date.isoformat() if upcoming else None
        next_due_amount = upcoming[0].current_amount if upcoming else None

        return {
            "total": total,
            "late_count": len(late),
            "pending_count": len(pending),
            "paid_count": len(paid),
            "total_penalties": round(total_penalties, 3),
            "next_due_date": next_due_date,
            "next_due_amount": next_due_amount,
        }
    except Exception as exc:
        logger.debug("get_installments_summary_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_installments_mongo(statuses: list[str]) -> list[dict] | None:
    """Réplique payments.list_installments() (LEFT JOIN invoices), ou None."""
    try:
        from src.storage.documents.payment_installment import PaymentInstallmentDocument
        from src.storage.documents.invoice import InvoiceDocument

        today = date.today()
        docs = await PaymentInstallmentDocument.find().to_list()

        invoice_ids = {d.invoice_id for d in docs if d.invoice_id}
        invoices = await InvoiceDocument.find({"_id": {"$in": list(invoice_ids)}}).to_list()
        inv_by_id = {str(i.id): i for i in invoices}

        _status_order = {"LATE": 0, "PENDING": 1}
        docs.sort(key=lambda d: (_status_order.get(d.status, 2), d.due_date))

        result = []
        for d in docs:
            if statuses and d.status not in statuses:
                continue
            inv = inv_by_id.get(d.invoice_id)
            due = d.due_date or today
            days_overdue = max(0, (today - due).days) if d.status in ("LATE", "PENDING") else 0
            penalty = round((d.current_amount or d.base_amount) - d.base_amount, 3)
            penalty_pct = round((penalty / d.base_amount) * 100, 1) if d.base_amount else 0.0

            result.append({
                "id": str(d.id),
                # SQLite stocke invoice_id sans tirets (CHAR(32) brut) — le
                # chemin SQL le renvoie tel quel ; on aligne le format Mongo
                # dessus pour que la sortie soit identique pendant la coexistence.
                "invoice_id": str(d.invoice_id).replace("-", ""),
                "issuer_name": inv.issuer_name if inv else None,
                "invoice_number": inv.invoice_number if inv else None,
                "installment_number": d.installment_number,
                "total_installments": d.total_installments,
                "base_amount": round(d.base_amount, 3),
                "current_amount": round(d.current_amount, 3),
                "penalty_amount": penalty,
                "penalty_pct": penalty_pct,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "paid_date": d.paid_date.isoformat() if d.paid_date else None,
                "paid_amount": d.paid_amount,
                "status": d.status,
                "late_periods": d.late_periods,
                "days_overdue": days_overdue,
            })
        return result
    except Exception as exc:
        logger.debug("list_installments_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Étape 5, Lot 6 : admin / users / security / auth (lecture seule) ────────
# ⚠️  Fraîcheur : ces collections (users, active_tokens, audit_logs) sont
# écrites en continu via des routes restées 100% SQLAlchemy (login, création
# de compte, édition de profil, révocation de session...). Aucun miroir n'est
# en place ici (contrairement à notifications/budget_plan) : une lecture Mongo
# peut donc renvoyer un compte/une session périmée jusqu'à la prochaine
# migration complète. Voir le rapport de fin de Lot 6 pour le détail.

async def list_users_mongo() -> list | None:
    """Réplique admin.list_users() côté base (UserDocument bruts), ou None."""
    try:
        from src.storage.documents.user import UserDocument

        return await UserDocument.find().sort("-created_at").to_list()
    except Exception as exc:
        logger.debug("list_users_mongo: MongoDB indisponible — %s", exc)
        return None


async def get_user_by_email_mongo(email: str) -> Any:
    """Réplique la recherche par email de users.get_me()/update_me().

    Retourne _NOT_FOUND si Mongo répond mais qu'aucun utilisateur ne correspond
    (pour distinguer "Mongo down" de "compte démo sans ligne en base" — voir
    get_invoice_mongo() pour le même motif).
    """
    try:
        from src.storage.documents.user import UserDocument

        doc = await UserDocument.find_one({"email": email})
        return doc if doc is not None else _NOT_FOUND
    except Exception as exc:
        logger.debug("get_user_by_email_mongo: MongoDB indisponible — %s", exc)
        return None


async def list_active_sessions_mongo(user_id: str) -> list | None:
    """Réplique auth.list_sessions(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.active_token import ActiveTokenDocument

        now = datetime.now(timezone.utc)
        return await (
            ActiveTokenDocument.find({
                "user_id": user_id, "revoked": False, "expires_at": {"$gt": now},
            }).sort("-created_at").to_list()
        )
    except Exception as exc:
        logger.debug("list_active_sessions_mongo: MongoDB indisponible — %s", exc)
        return None


async def security_summary_mongo() -> dict | None:
    """Réplique security.security_summary(), ou None si Mongo indisponible."""
    try:
        from src.storage.documents.audit_log import AuditLogDocument
        from src.storage.documents.user import UserDocument
        from src.storage.documents.active_token import ActiveTokenDocument

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        now = datetime.now(timezone.utc)

        async def _count_action(action_or_list, since):
            query: dict[str, Any] = {"created_at": {"$gte": since}}
            if isinstance(action_or_list, list):
                query["action"] = {"$in": action_or_list}
            else:
                query["action"] = action_or_list
            return await AuditLogDocument.find(query).count()

        total_logins_today = await _count_action("LOGIN_SUCCESS", today_start)
        failed_logins_today = await _count_action("LOGIN_FAILURE", today_start)
        unauthorized_today = await _count_action("UNAUTHORIZED_ACCESS", today_start)
        uploads_today = await _count_action(["FILE_UPLOADED", "INVOICE_UPLOADED"], today_start)
        rejected_files_today = await _count_action("FILE_REJECTED", today_start)

        locked_users = await UserDocument.find({
            "locked_until": {"$gt": now}, "is_active": True,
        }).to_list()

        suspicious = await (
            UserDocument.find({
                "failed_login_attempts": {"$gt": 0},
                "last_failed_login": {"$gte": now - timedelta(hours=24)},
            }).sort("-failed_login_attempts").limit(10).to_list()
        )

        last_check = await (
            AuditLogDocument.find({"action": "AUDIT_INTEGRITY_CHECK"})
            .sort("-created_at").limit(1).to_list()
        )
        last_integrity_score: float | None = None
        last_integrity_check: str | None = None
        if last_check:
            entry = last_check[0]
            last_integrity_check = entry.created_at.isoformat()
            detail = entry.detail or ""
            try:
                score_part = detail.split("Score:")[1].split("%")[0].strip()
                last_integrity_score = float(score_part)
            except Exception:
                pass

        active_sessions = await ActiveTokenDocument.find({
            "revoked": False, "expires_at": {"$gt": now},
        }).count()

        return {
            "total_logins_today": total_logins_today,
            "failed_logins_today": failed_logins_today,
            "locked_accounts_count": len(locked_users),
            "uploads_today": uploads_today,
            "rejected_files_today": rejected_files_today,
            "last_integrity_check": last_integrity_check,
            "last_integrity_score": last_integrity_score,
            # tampered_entries_count is intentionally absent — the caller
            # (api/routers/security.py::security_summary) always overwrites it
            # with a live, merged SQLite+Mongo count via compute_integrity_summary().
            "active_sessions_count": active_sessions,
            "unauthorized_access_attempts_today": unauthorized_today,
            "accounts_with_recent_failures": [
                {
                    "email": u.email,
                    "failed_attempts": u.failed_login_attempts,
                    "last_attempt": u.last_failed_login.isoformat() if u.last_failed_login else None,
                }
                for u in suspicious
            ],
            "locked_accounts": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "locked_until": u.locked_until.isoformat() if u.locked_until else None,
                    "failed_attempts": u.failed_login_attempts,
                }
                for u in locked_users
            ],
        }
    except Exception as exc:
        logger.debug("security_summary_mongo: MongoDB indisponible — %s", exc)
        return None


# ── Helper de conversion de date partagé ──────────────────────────────────────
# Anciennement utilisé aussi par le layer de miroirs best-effort (Lots 2-6),
# entièrement retiré (0 appelant réel — tous les domaines concernés sont
# passés Mongo-primaire, voir *_native ci-dessous). Reste utilisé par les
# fonctions *_native qui ont besoin de dates BSON (minuit UTC).

def _to_midnight_utc(d) -> datetime | None:
    """Convertit une date Python en datetime minuit UTC (format BSON, voir migrate script _date())."""
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def revoke_all_user_tokens_native(
    user_id: str, except_jti: str | None = None, reason: str = "password_change",
) -> int:
    """Révoque toutes les sessions actives de l'utilisateur — appelé après tout
    changement de mot de passe (OTP, lien de reset, reset forcé par un Admin)
    pour qu'un JWT déjà volé ne survive pas au changement.

    `except_jti` préserve une session courante quand l'appelant est authentifié
    en tant que cet utilisateur (ex: changement de mot de passe volontaire) ;
    laissé à None quand il n'y a pas de session courante à préserver (reset via
    lien — flux non authentifié — ou reset forcé par un Admin sur un autre
    utilisateur).

    Révoque via les DEUX mécanismes : jwt_handler.revoke_token() (le blocklist
    RevokedTokenDocument réellement vérifié par verify_access_token — sans ça
    le JWT resterait utilisable) et ActiveTokenDocument.revoked (cohérence de
    la liste de sessions affichée à l'utilisateur). Contrairement à l'ancienne
    mirror_revoke_all_user_tokens() qu'elle remplace (jamais appelée, erreurs
    Mongo avalées en silence), cette fonction est authoritative — comme les
    autres *_native de ce module — et ne doit pas avaler ses erreurs.
    """
    from api.security import jwt_handler
    from src.storage.documents.active_token import ActiveTokenDocument

    now = datetime.now(timezone.utc)
    query: dict[str, Any] = {
        "user_id": str(user_id), "revoked": False, "expires_at": {"$gt": now},
    }
    if except_jti:
        query["_id"] = {"$ne": except_jti}

    active = await ActiveTokenDocument.find(query).to_list()
    for token in active:
        await jwt_handler.revoke_token(token.id, reason, str(user_id))

    if active:
        coll = ActiveTokenDocument.get_pymongo_collection()
        await coll.update_many(
            {"_id": {"$in": [t.id for t in active]}}, {"$set": {"revoked": True}},
        )
    return len(active)


# ══════════════════════════════════════════════════════════════════════════════
# Mongo PRIMAIRE — Étape 6 (Lot 2) : roadmap / livrables / risks
#
# À partir d'ici, MongoDB est la SOURCE DE VÉRITÉ pour ces trois collections :
# plus aucune écriture SQLAlchemy n'a lieu (SQLite reste figé pour ces tables).
# Contrairement aux miroirs ci-dessus (best-effort, ne bloquent jamais), ces
# fonctions PROPAGENT leurs exceptions — un échec Mongo doit faire échouer la
# requête, exactement comme un échec SQLAlchemy l'aurait fait avant.
#
# Convention _id : chaîne avec tirets (str(uuid4())), pas de type BSON UUID
# natif — cohérence avec toutes les données déjà migrées (voir la note dans
# get_invoice_mongo() sur Document.insert() vs pymongo brut).
# ══════════════════════════════════════════════════════════════════════════════

async def _get_by_str_id(doc_class, id_str: str) -> Any:
    """Comme Document.get(), mais sans la coercition de type de Beanie.

    Document.get(x) convertit toujours x vers le type déclaré du champ `id`
    (UUID ici) avant de construire le filtre — donc même en lui passant une
    chaîne, Beanie interroge avec un objet UUID (BSON Binary), qui ne matche
    jamais nos documents dont le _id est stocké comme chaîne. Voir la note
    dans get_invoice_mongo(). Sans objet pour ce cas précis (id: str, ex.
    PhaseDocument), Document.get() reste sûr et peut être utilisé directement.
    """
    return await doc_class.find_one({"_id": id_str})

async def create_roadmap_item_native(body) -> Any:
    from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument

    doc = {
        "_id": str(uuid4()),
        "titre": body.titre,
        "description": body.description,
        "date_debut": _to_midnight_utc(body.date_debut),
        "date_fin": _to_midnight_utc(body.date_fin),
        "projet_id": body.projet_id,
        "responsable_id": body.responsable_id,
        "statut": body.statut,
        "priorite": body.priorite,
        "annee": body.annee,
    }
    coll = FeuilleDeRouteDocument.get_pymongo_collection()
    await coll.insert_one(doc)
    return await _get_by_str_id(FeuilleDeRouteDocument, doc["_id"])


async def update_roadmap_item_native(item_id: str, body) -> Any:
    from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument

    normalized = str(UUID(item_id))
    item = await _get_by_str_id(FeuilleDeRouteDocument, normalized)
    if item is None:
        return None

    updates: dict[str, Any] = {}
    if body.titre is not None:        updates["titre"] = body.titre
    if body.description is not None:  updates["description"] = body.description
    if body.date_debut is not None:   updates["date_debut"] = _to_midnight_utc(body.date_debut)
    if body.date_fin is not None:     updates["date_fin"] = _to_midnight_utc(body.date_fin)
    if body.statut is not None:       updates["statut"] = body.statut
    if body.priorite is not None:     updates["priorite"] = body.priorite
    if body.projet_id is not None:    updates["projet_id"] = body.projet_id

    if updates:
        coll = FeuilleDeRouteDocument.get_pymongo_collection()
        await coll.update_one({"_id": normalized}, {"$set": updates})
    return await _get_by_str_id(FeuilleDeRouteDocument, normalized)


async def delete_roadmap_item_native(item_id: str) -> bool:
    """Supprime le jalon + ses risques liés (cascade). Retourne False si non trouvé."""
    from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument
    from src.storage.documents.risque import RisqueDocument

    normalized = str(UUID(item_id))
    item = await _get_by_str_id(FeuilleDeRouteDocument, normalized)
    if item is None:
        return False

    coll_fr = FeuilleDeRouteDocument.get_pymongo_collection()
    await coll_fr.delete_one({"_id": normalized})
    coll_risk = RisqueDocument.get_pymongo_collection()
    await coll_risk.delete_many({"feuille_route_id": normalized})
    return True


async def create_livrable_native(phase_id: str, body, created_by: str) -> Any:
    """Retourne None si la phase n'existe pas (réplique le 404 de la route)."""
    from src.storage.documents.phase import PhaseDocument
    from src.storage.documents.livrable import LivrableDocument

    phase = await PhaseDocument.get(phase_id)
    if phase is None:
        return None

    doc = {
        "_id": str(uuid4()),
        "phase_id": phase_id,
        "titre": body.titre,
        "description": body.description,
        "date_livraison_prevue": _to_midnight_utc(body.date_livraison_prevue),
        "date_livraison_reelle": None,
        "statut": body.statut,
        "fichier_path": None,
        "created_by": created_by,
    }
    coll = LivrableDocument.get_pymongo_collection()
    await coll.insert_one(doc)
    return await _get_by_str_id(LivrableDocument, doc["_id"])


async def update_livrable_native(livrable_id: str, body) -> Any:
    from src.storage.documents.livrable import LivrableDocument

    normalized = str(UUID(livrable_id))
    lv = await _get_by_str_id(LivrableDocument, normalized)
    if lv is None:
        return None

    updates: dict[str, Any] = {}
    if body.titre is not None:                 updates["titre"] = body.titre
    if body.description is not None:           updates["description"] = body.description
    if body.statut is not None:                updates["statut"] = body.statut
    if body.date_livraison_reelle is not None: updates["date_livraison_reelle"] = _to_midnight_utc(body.date_livraison_reelle)

    if updates:
        coll = LivrableDocument.get_pymongo_collection()
        await coll.update_one({"_id": normalized}, {"$set": updates})
    return await _get_by_str_id(LivrableDocument, normalized)


class PhaseValidationError(Exception):
    """Levée quand des livrables non terminés bloquent la validation d'une phase."""
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"{count} livrable(s) non terminé(s)")


async def valider_phase_native(phase_id: str) -> Any:
    """Retourne None si phase non trouvée. Lève PhaseValidationError si bloquée."""
    from src.storage.documents.phase import PhaseDocument
    from src.storage.documents.livrable import LivrableDocument
    from datetime import date as date_cls

    phase = await PhaseDocument.get(phase_id)
    if phase is None:
        return None

    livrables = await LivrableDocument.find({"phase_id": phase_id}).to_list()
    non_termines = [lv for lv in livrables if lv.statut not in ("LIVRE", "VALIDE")]
    if non_termines:
        raise PhaseValidationError(len(non_termines))

    coll = PhaseDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": phase_id},
        {"$set": {"status": "VALIDEE", "closed_date": _to_midnight_utc(date_cls.today())}},
    )
    return await PhaseDocument.get(phase_id)


async def log_audit_event_native(entry) -> None:
    """Écrit un événement d'audit directement dans Mongo — équivalent natif de
    audit_service.log_action(), pour les événements auth/admin/security (Lot 6).

    Prend un AuditLogCreate déjà construit (src.models.audit) pour minimiser
    le delta aux points d'appel — mêmes champs que log_action(), avec un
    row_hash HMAC réel (voir api/security/audit_integrity.py::compute_row_hash_from_doc
    — même formule que SQLite, appliquée à ce document avant insertion).
    """
    try:
        from api.security.audit_integrity import compute_row_hash_from_doc
        from src.storage.documents.audit_log import AuditLogDocument

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

        coll = AuditLogDocument.get_pymongo_collection()
        await coll.insert_one(doc)
    except Exception as exc:
        logger.debug("log_audit_event_native: écriture Mongo échouée — %s", exc)


async def verify_integrity_native(limit: int = 5000) -> dict | None:
    """Équivalent Mongo-natif de api/routers/audit.py::verify_integrity() —
    recalcule le HMAC de chaque document audit_logs stocké dans Mongo.

    Retourne None si Mongo est indisponible (l'appelant se limite alors au
    résultat SQLite). Ce n'est PAS une vérification de chaîne — chaque
    document est vérifié indépendamment, comme côté SQLite (voir
    audit_integrity.py pour le détail de cette décision de conception).
    """
    try:
        from api.security.audit_integrity import compute_row_hash_from_doc
        from src.storage.documents.audit_log import AuditLogDocument

        coll = AuditLogDocument.get_pymongo_collection()
        rows = await coll.find().sort("created_at", -1).limit(limit).to_list(length=limit)
    except Exception as exc:
        logger.debug("verify_integrity_native: MongoDB indisponible — %s", exc)
        return None

    valid = 0
    null_hash_entries: list[dict] = []
    tampered: list[dict] = []
    for doc in rows:
        stored = doc.get("row_hash")
        created_at = doc.get("created_at")
        entry_summary = {
            "id": str(doc.get("_id")),
            "created_at": created_at.isoformat() if created_at else "",
            "action": doc.get("action"),
        }
        if not stored:
            null_hash_entries.append(entry_summary)
            valid += 1
            continue
        expected = compute_row_hash_from_doc(doc)
        if hmac.compare_digest(expected, stored):
            valid += 1
        else:
            tampered.append(entry_summary)

    total = len(rows)
    return {
        "total_checked": total,
        "valid": valid,
        "null_hash_count": len(null_hash_entries),
        "tampered_count": len(tampered),
        "tampered_entries": tampered,
    }


async def _create_audit_log_native(
    user: dict, action: str, resource_type: str, resource_id: str, detail: str = "",
) -> None:
    """Réplique le _log_audit local de risks.py, mais écrit directement dans Mongo
    (pas de secours SQLite — cohérent avec le reste du Lot 2 en écriture native).
    """
    try:
        from api.security.audit_integrity import compute_row_hash_from_doc
        from src.storage.documents.audit_log import AuditLogDocument

        doc = {
            "_id": str(uuid4()),
            "created_at": datetime.now(timezone.utc),
            "user_id": user.get("sub", ""),
            "user_email": user.get("email", ""),
            "user_role": user.get("role", ""),
            "actor": user.get("email", "") or user.get("sub", ""),
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "entity_id": resource_id,
            "before_value": None,
            "after_value": None,
            "ip_address": None,
            "user_agent": None,
            "status": "SUCCESS",
            "detail": detail,
        }
        doc["row_hash"] = compute_row_hash_from_doc(doc)

        coll = AuditLogDocument.get_pymongo_collection()
        await coll.insert_one(doc)
    except Exception as exc:
        logger.debug("_create_audit_log_native: écriture Mongo échouée — %s", exc)


async def create_risk_native(body, user: dict) -> Any:
    from src.storage.documents.risque import RisqueDocument
    from src.services.risk_service import calculate_criticite

    criticite = calculate_criticite(body.probabilite, body.impact)
    now = datetime.now(timezone.utc)
    doc = {
        "_id": str(uuid4()),
        "titre": body.titre,
        "description": body.description,
        "type_risque": body.type_risque,
        "probabilite": body.probabilite,
        "impact": body.impact,
        "niveau_criticite": criticite,
        "statut": body.statut,
        "plan_mitigation": body.plan_mitigation,
        "responsable_id": body.responsable_id,
        "date_identification": _to_midnight_utc(body.date_identification),
        "date_echeance_mitigation": _to_midnight_utc(body.date_echeance_mitigation),
        "date_cloture": None,
        "feuille_route_id": str(UUID(body.feuille_route_id)) if body.feuille_route_id else None,
        "projet_id": body.projet_id,
        "created_by": user.get("email", ""),
        "created_at": now,
        "updated_at": now,
    }
    coll = RisqueDocument.get_pymongo_collection()
    await coll.insert_one(doc)
    r = await _get_by_str_id(RisqueDocument, doc["_id"])
    await _create_audit_log_native(user, "RISK_CREATED", "RISK", doc["_id"], f"Risque créé: {r.titre}")
    return r


async def update_risk_native(risk_id: str, body, user: dict) -> Any:
    from src.storage.documents.risque import RisqueDocument
    from src.services.risk_service import calculate_criticite
    from datetime import date as date_cls

    normalized = str(UUID(risk_id))
    r = await _get_by_str_id(RisqueDocument, normalized)
    if r is None:
        return None

    old_statut = r.statut
    probabilite = body.probabilite if body.probabilite is not None else r.probabilite
    impact = body.impact if body.impact is not None else r.impact
    recompute = body.probabilite is not None or body.impact is not None

    updates: dict[str, Any] = {}
    if body.titre is not None:                    updates["titre"] = body.titre
    if body.description is not None:              updates["description"] = body.description
    if body.type_risque is not None:               updates["type_risque"] = body.type_risque
    if body.plan_mitigation is not None:           updates["plan_mitigation"] = body.plan_mitigation
    if body.responsable_id is not None:            updates["responsable_id"] = body.responsable_id
    if body.date_echeance_mitigation is not None:  updates["date_echeance_mitigation"] = _to_midnight_utc(body.date_echeance_mitigation)
    if body.probabilite is not None:               updates["probabilite"] = body.probabilite
    if body.impact is not None:                    updates["impact"] = body.impact
    if body.statut is not None:
        updates["statut"] = body.statut
        if body.statut == "CLOTURE" and not r.date_cloture:
            updates["date_cloture"] = _to_midnight_utc(date_cls.today())
    if recompute:
        updates["niveau_criticite"] = calculate_criticite(probabilite, impact)
    updates["updated_at"] = datetime.now(timezone.utc)

    coll = RisqueDocument.get_pymongo_collection()
    await coll.update_one({"_id": normalized}, {"$set": updates})

    if body.statut and body.statut != old_statut:
        await _create_audit_log_native(user, "RISK_STATUS_CHANGED", "RISK", risk_id, f"{old_statut} → {body.statut}")
    elif body.plan_mitigation is not None:
        await _create_audit_log_native(user, "RISK_MITIGATION_UPDATED", "RISK", risk_id, r.titre)
    if body.statut == "CLOTURE":
        await _create_audit_log_native(user, "RISK_CLOSED", "RISK", risk_id, r.titre)

    return await _get_by_str_id(RisqueDocument, normalized)


async def close_risk_native(risk_id: str, user: dict) -> Any:
    from src.storage.documents.risque import RisqueDocument
    from datetime import date as date_cls

    normalized = str(UUID(risk_id))
    r = await _get_by_str_id(RisqueDocument, normalized)
    if r is None:
        return None

    coll = RisqueDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": normalized},
        {"$set": {
            "statut": "CLOTURE",
            "date_cloture": _to_midnight_utc(date_cls.today()),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    await _create_audit_log_native(user, "RISK_CLOSED", "RISK", risk_id, r.titre)
    return r


# ── Lot 3 (Mongo primaire) : notifications / review ──────────────────────────

async def mark_notification_read_native(notif_id: str) -> Any:
    from src.storage.documents.notification import NotificationDocument

    normalized = str(UUID(notif_id))
    notif = await _get_by_str_id(NotificationDocument, normalized)
    if notif is None:
        return None
    coll = NotificationDocument.get_pymongo_collection()
    await coll.update_one({"_id": normalized}, {"$set": {"is_read": True}})
    return await _get_by_str_id(NotificationDocument, normalized)


async def mark_all_notifications_read_native() -> None:
    from src.storage.documents.notification import NotificationDocument

    coll = NotificationDocument.get_pymongo_collection()
    await coll.update_many({"is_read": False}, {"$set": {"is_read": True}})


def _flag_to_dict(f) -> dict:
    fd = f.model_dump()
    fd["id"] = str(fd["id"])  # UUID -> str, cohérence avec le reste de la collection
    return fd


async def approve_invoice_native(invoice_id: str, notes: str | None, user: dict) -> Any:
    """Retourne None si facture non trouvée. Écrit directement dans InvoiceDocument."""
    from src.storage.documents.invoice import InvoiceDocument

    normalized = str(UUID(invoice_id))
    doc = await _get_by_str_id(InvoiceDocument, normalized)
    if doc is None:
        return None

    now = datetime.now(timezone.utc)
    resolved_flags = []
    for f in doc.flags:
        fd = _flag_to_dict(f)
        if not fd["resolved"]:
            fd["resolved"] = True
            fd["resolved_by"] = "human"
        resolved_flags.append(fd)

    coll = InvoiceDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": normalized},
        {"$set": {
            "flags": resolved_flags,
            "human_review_required": False,
            "human_review_notes": notes,
            "status": "VALIDATED",
            "updated_at": now,
        },
        "$push": {"history": {
            "id": str(uuid4()), "from_status": doc.status, "to_status": "VALIDATED",
            "changed_at": now, "changed_by": user.get("email", "agent"), "notes": None,
        }}},
    )
    await _create_audit_log_native(user, "APPROVE", "InvoiceRecord", invoice_id, notes or "")
    return await _get_by_str_id(InvoiceDocument, normalized)


async def reject_invoice_native(invoice_id: str, notes: str | None, user: dict) -> Any:
    from src.storage.documents.invoice import InvoiceDocument

    normalized = str(UUID(invoice_id))
    doc = await _get_by_str_id(InvoiceDocument, normalized)
    if doc is None:
        return None

    now = datetime.now(timezone.utc)
    coll = InvoiceDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": normalized},
        {"$set": {
            "status": "REJECTED",
            "human_review_required": False,
            "human_review_notes": notes,
            "updated_at": now,
        },
        "$push": {"history": {
            "id": str(uuid4()), "from_status": doc.status, "to_status": "REJECTED",
            "changed_at": now, "changed_by": user.get("email", "agent"), "notes": None,
        }}},
    )
    await _create_audit_log_native(user, "REJECT", "InvoiceRecord", invoice_id, notes or "")
    return await _get_by_str_id(InvoiceDocument, normalized)


# ── Lot 4 (Mongo primaire) : assets / budget lignes projet / budget plan ──────

async def create_asset_native(body, user: dict) -> Any:
    """Retourne un modèle Asset (pas un Document) pour préserver book_value_at()."""
    from src.models.asset import Asset
    from src.storage.documents.asset import AssetDocument

    asset = Asset(
        designation=body.designation,
        compte_immobilisation=body.compte_immobilisation,
        compte_amortissement=body.compte_amortissement,
        acquisition_date=body.acquisition_date,
        acquisition_cost_ht=body.acquisition_cost_ht,
        useful_life_years=body.useful_life_years,
        depreciation_method=body.depreciation_method,
    )
    doc = {
        "_id": str(asset.id),
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
        "fully_depreciated": False,
        "created_at": asset.created_at,
        "project_links": [],
    }
    coll = AssetDocument.get_pymongo_collection()
    await coll.insert_one(doc)
    await _create_audit_log_native(
        user, "CREATE", "Asset", str(asset.id),
        f"designation={asset.designation} compte={asset.compte_immobilisation} cost_ht={asset.acquisition_cost_ht}",
    )
    return asset


async def create_budget_line_native(projet_id: str, body) -> Any:
    from src.storage.documents.ligne_budget import LigneBudgetDocument

    doc = {
        "_id": str(uuid4()),
        "projet_id": projet_id,
        "categorie": body.categorie,
        "montant_prevu": body.montant_prevu,
        "montant_consomme": 0.0,
        "devise": body.devise,
        "created_at": datetime.now(timezone.utc),
    }
    coll = LigneBudgetDocument.get_pymongo_collection()
    await coll.insert_one(doc)
    return await _get_by_str_id(LigneBudgetDocument, doc["_id"])


async def update_budget_line_native(ligne_id: str, body) -> Any:
    from src.storage.documents.ligne_budget import LigneBudgetDocument

    normalized = str(UUID(ligne_id))
    lb = await _get_by_str_id(LigneBudgetDocument, normalized)
    if lb is None:
        return None

    updates: dict[str, Any] = {}
    if body.categorie is not None:     updates["categorie"] = body.categorie
    if body.montant_prevu is not None: updates["montant_prevu"] = body.montant_prevu
    if updates:
        coll = LigneBudgetDocument.get_pymongo_collection()
        await coll.update_one({"_id": normalized}, {"$set": updates})
    return await _get_by_str_id(LigneBudgetDocument, normalized)


async def delete_budget_line_native(ligne_id: str) -> bool:
    from src.storage.documents.ligne_budget import LigneBudgetDocument

    normalized = str(UUID(ligne_id))
    lb = await _get_by_str_id(LigneBudgetDocument, normalized)
    if lb is None:
        return False
    coll = LigneBudgetDocument.get_pymongo_collection()
    await coll.delete_one({"_id": normalized})
    return True


class BudgetPlanConflict(Exception):
    """Levée quand (catalog_id, year) existe déjà à la création."""


async def create_budget_plan_entry_native(body, year: int, user: dict) -> Any:
    from pymongo.errors import DuplicateKeyError

    from src.storage.documents.budget_plan import BudgetPlanDocument

    existing = await BudgetPlanDocument.find_one({"catalog_id": body.catalog_id, "year": year})
    if existing is not None:
        raise BudgetPlanConflict(body.catalog_id)

    doc = {
        "_id": str(uuid4()),
        "catalog_id": body.catalog_id,
        "year": year,
        "label": body.label,
        "monthly": [float(v) for v in body.monthly],
        "note": body.note,
        "updated_at": datetime.now(timezone.utc),
    }
    coll = BudgetPlanDocument.get_pymongo_collection()
    try:
        await coll.insert_one(doc)
    except DuplicateKeyError:
        # Two concurrent creates for the same (catalog_id, year) both pass the
        # find_one() check above — the compound unique index is the real
        # guarantee, so the loser of the race must map to the same conflict
        # the app-level check already reports, not an unhandled 500.
        raise BudgetPlanConflict(body.catalog_id)
    await _create_audit_log_native(user, "BUDGET_PLAN_CREATED", "BudgetPlan", f"{body.catalog_id}/{year}", "")
    return await BudgetPlanDocument.find_one({"catalog_id": body.catalog_id, "year": year})


async def update_budget_plan_entry_native(catalog_id: str, year: int, body, user: dict) -> Any:
    from src.storage.documents.budget_plan import BudgetPlanDocument

    row = await BudgetPlanDocument.find_one({"catalog_id": catalog_id, "year": year})
    if row is None:
        return None

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if body.label is not None:
        updates["label"] = body.label
    if body.monthly is not None:
        updates["monthly"] = [float(v) for v in body.monthly]
    if body.note is not None:
        updates["note"] = body.note

    coll = BudgetPlanDocument.get_pymongo_collection()
    await coll.update_one({"_id": str(row.id)}, {"$set": updates})
    await _create_audit_log_native(user, "BUDGET_PLAN_UPDATED", "BudgetPlan", f"{catalog_id}/{year}", "")
    return await BudgetPlanDocument.find_one({"catalog_id": catalog_id, "year": year})


async def delete_budget_plan_entry_native(catalog_id: str, year: int, user: dict) -> bool:
    from src.storage.documents.budget_plan import BudgetPlanDocument

    row = await BudgetPlanDocument.find_one({"catalog_id": catalog_id, "year": year})
    if row is None:
        return False

    coll = BudgetPlanDocument.get_pymongo_collection()
    await coll.delete_one({"_id": str(row.id)})
    await _create_audit_log_native(user, "BUDGET_PLAN_DELETED", "BudgetPlan", f"{catalog_id}/{year}", "")
    return True


async def seed_budget_plan_from_yaml_native(year: int, yaml_path) -> None:
    """Seed les lignes du plan budgétaire depuis le YAML si l'année n'est pas
    encore présente en base — Mongo exclusif, aucun secours SQLAlchemy."""
    import yaml as _yaml
    from src.storage.documents.budget_plan import BudgetPlanDocument

    existing = await BudgetPlanDocument.find_one({"year": year})
    if existing is not None:
        return

    data = _yaml.safe_load(yaml_path.read_text())
    now = datetime.now(timezone.utc)
    docs = [
        {
            "_id": str(uuid4()),
            "catalog_id": entry["catalog_id"], "year": year, "label": entry["label"],
            "monthly": [float(v) for v in entry["monthly"]], "note": entry.get("note"),
            "updated_at": now,
        }
        for entry in data.get("entries", [])
    ]
    if docs:
        coll = BudgetPlanDocument.get_pymongo_collection()
        await coll.insert_many(docs)


# ── Lot 5 (Mongo primaire) : invoices/status, billing, payments ──────────────
# Ces fonctions couvrent les routes simples (PATCH status, generate, mark-paid).
# Le pipeline IA complet (upload_invoice → InvoiceProcessingOrchestrator) utilise un dépôt
# Mongo SYNCHRONE (src/storage/sync_mongo_repository.py) car ce pipeline est
# délibérément synchrone — voir ce module pour le contexte complet.

async def update_invoice_status_native(invoice_id: str, new_status: str) -> Any:
    """Retourne None si facture non trouvée."""
    from src.storage.documents.invoice import InvoiceDocument

    normalized = str(UUID(invoice_id))
    doc = await _get_by_str_id(InvoiceDocument, normalized)
    if doc is None:
        return None

    now = datetime.now(timezone.utc)
    coll = InvoiceDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": normalized},
        {"$set": {"status": new_status, "updated_at": now},
         "$push": {"history": {
             "id": str(uuid4()), "from_status": doc.status, "to_status": new_status,
             "changed_at": now, "changed_by": "agent", "notes": None,
         }}},
    )
    return await _get_by_str_id(InvoiceDocument, normalized)


async def mark_installment_paid_native(installment_id: str, paid_amount: float, paid_date: str) -> Any:
    """Retourne None si non trouvée, _CONFLICT (chaîne) si déjà payée, sinon le document mis à jour."""
    from src.storage.documents.payment_installment import PaymentInstallmentDocument

    doc = await PaymentInstallmentDocument.find_one({"_id": installment_id})
    if doc is None:
        return None
    if doc.status == "PAID":
        return "ALREADY_PAID"

    coll = PaymentInstallmentDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": installment_id},
        {"$set": {
            "status": "PAID",
            "paid_amount": paid_amount,
            "paid_date": _to_midnight_utc(date.fromisoformat(paid_date)),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return await PaymentInstallmentDocument.find_one({"_id": installment_id})


# ── Lot 6 (Mongo primaire) : utilisateurs / sessions / OTP / reset ───────────
# ATTENTION : UserDocument.id et PasswordVerificationDocument.{id,user_id}
# déclarent le type UUID dans leur schéma Beanie, mais le script de migration
# les a TOUJOURS stockés comme chaînes avec tirets (voir _build_password_*
# et _migrate_users() dans migrate_sqlite_to_mongodb.py, qui écrivent via
# get_pymongo_collection() + replace_one(), sans passer par la validation
# Pydantic). On n'utilise donc ici QUE des filtres dict bruts ({"_id": "..."},
# {"user_id": "..."}) — jamais Document.get() ni les comparaisons typées
# (Document.field == value), qui coercent silencieusement vers UUID/BSON
# Binary et ne matchent alors plus rien. Voir _get_by_str_id() plus haut pour
# la même mise en garde appliquée aux autres collections.

_MAX_ACTIVE_SESSIONS = int(os.getenv("MAX_ACTIVE_SESSIONS", "5"))
_OTP_PURPOSE_LABELS = {
    "FIRST_LOGIN":      "première connexion",
    "VOLUNTARY_CHANGE": "changement volontaire",
    "FORGOT_PASSWORD":  "réinitialisation",
}


async def get_user_by_id_native(user_id: str) -> Any:
    from src.storage.documents.user import UserDocument
    return await _get_by_str_id(UserDocument, str(user_id))


async def get_user_by_email_native(email: str) -> Any:
    from src.storage.documents.user import UserDocument
    return await UserDocument.find_one({"email": email})


async def create_user_native(
    nom: str, prenom: str, email: str, hashed_password: str,
    role: str, departement: str = "", is_first_login: bool = True,
) -> Any:
    """Retourne None si l'email existe déjà (409 côté appelant).

    Le find_one() ci-dessous ne fait qu'un rejet précoce optimiste — la
    garantie d'unicité réelle vient de l'index unique Mongo sur `email`
    (voir user.py). Deux requêtes concurrentes peuvent toutes les deux
    passer ce check avant que l'une des deux n'insère ; l'insert_one()
    restant doit donc aussi absorber le DuplicateKeyError levé par Mongo
    pour la perdante de la course, sous peine de 500 au lieu d'un 409 propre.
    """
    from pymongo.errors import DuplicateKeyError

    from src.storage.documents.user import UserDocument

    existing = await UserDocument.find_one({"email": email})
    if existing is not None:
        return None

    now = datetime.now(timezone.utc)
    doc = {
        "_id": str(uuid4()),
        "nom": nom, "prenom": prenom, "email": email,
        "hashed_password": hashed_password, "role": role, "departement": departement,
        "is_first_login": is_first_login, "is_active": True, "created_at": now,
        "failed_login_attempts": 0, "locked_until": None, "last_failed_login": None,
        "last_login_at": None, "last_login_ip": None, "profile_picture": None,
    }
    coll = UserDocument.get_pymongo_collection()
    try:
        await coll.insert_one(doc)
    except DuplicateKeyError:
        return None
    return await UserDocument.find_one({"email": email})


async def record_login_success_native(user_id: str, ip: str | None) -> None:
    from src.storage.documents.user import UserDocument
    coll = UserDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": str(user_id)},
        {"$set": {
            "failed_login_attempts": 0, "locked_until": None, "last_failed_login": None,
            "last_login_at": datetime.now(timezone.utc), "last_login_ip": ip,
        }},
    )


async def record_login_failure_native(user_doc) -> int:
    """Incrémente le compteur d'échecs, verrouille si le seuil est atteint. Retourne le nombre de tentatives."""
    from src.storage.documents.user import UserDocument

    max_attempts = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
    lockout_minutes = int(os.getenv("ACCOUNT_LOCKOUT_MINUTES", "15"))

    attempts = (user_doc.failed_login_attempts or 0) + 1
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"failed_login_attempts": attempts, "last_failed_login": now}
    if attempts >= max_attempts:
        updates["locked_until"] = now + timedelta(minutes=lockout_minutes)

    coll = UserDocument.get_pymongo_collection()
    await coll.update_one({"_id": str(user_doc.id)}, {"$set": updates})
    return attempts


def check_locked_native(user_doc) -> tuple[bool, int]:
    """Synchrone — pure lecture sur l'objet déjà chargé, pas d'accès Mongo.
    Ne réinitialise pas automatiquement un verrou expiré (contrairement à la
    version SQLAlchemy) : le prochain login réussi le fera via
    record_login_success_native()."""
    locked_until = user_doc.locked_until
    if not locked_until:
        return False, 0
    now = datetime.now(timezone.utc)
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until > now:
        remaining = max(1, int((locked_until - now).total_seconds() // 60))
        return True, remaining
    return False, 0


async def update_user_role_native(user_id: str, role: str) -> None:
    """Utilisé par le provisioning LDAP quand le rôle annuaire change."""
    from src.storage.documents.user import UserDocument
    coll = UserDocument.get_pymongo_collection()
    await coll.update_one({"_id": str(user_id)}, {"$set": {"role": role}})


async def update_user_password_native(user_id: str, hashed_password: str, is_first_login: bool = False) -> None:
    from src.storage.documents.user import UserDocument
    coll = UserDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": str(user_id)},
        {"$set": {"hashed_password": hashed_password, "is_first_login": is_first_login}},
    )


async def register_active_token_native(jti: str, user_id: str, expires_at: datetime,
                                        ip: str | None, ua: str | None) -> None:
    from src.storage.documents.active_token import ActiveTokenDocument

    now = datetime.now(timezone.utc)
    active = await (
        ActiveTokenDocument.find({
            "user_id": str(user_id), "revoked": False, "expires_at": {"$gt": now},
        }).sort("+created_at").to_list()
    )

    coll = ActiveTokenDocument.get_pymongo_collection()
    if len(active) >= _MAX_ACTIVE_SESSIONS:
        to_evict = active[: len(active) - _MAX_ACTIVE_SESSIONS + 1]
        await coll.update_many(
            {"_id": {"$in": [a.id for a in to_evict]}}, {"$set": {"revoked": True}},
        )

    doc = {
        "_id": jti, "user_id": str(user_id), "created_at": now, "expires_at": expires_at,
        "ip_address": ip, "user_agent": (ua or "")[:100], "revoked": False,
    }
    await coll.replace_one({"_id": jti}, doc, upsert=True)


async def revoke_active_token_native(jti: str) -> None:
    from src.storage.documents.active_token import ActiveTokenDocument
    coll = ActiveTokenDocument.get_pymongo_collection()
    await coll.update_one({"_id": jti}, {"$set": {"revoked": True}})


async def revoke_active_tokens_by_prefix_native(jti_prefix: str, user_id: str | None, is_admin: bool) -> int:
    """Révoque les tokens actifs dont le JTI commence par jti_prefix.

    Si is_admin est False, seuls les tokens de user_id peuvent être révoqués.
    Retourne le nombre de tokens révoqués."""
    from src.storage.documents.active_token import ActiveTokenDocument

    query: dict[str, Any] = {"_id": {"$regex": f"^{re.escape(jti_prefix)}"}, "revoked": False}
    if not is_admin:
        query["user_id"] = str(user_id)

    rows = await ActiveTokenDocument.find(query).to_list()
    if not rows:
        return 0

    coll = ActiveTokenDocument.get_pymongo_collection()
    await coll.update_many({"_id": {"$in": [r.id for r in rows]}}, {"$set": {"revoked": True}})
    for r in rows:
        await revoke_token_native(r.id, "session_revoked", user_id)
    return len(rows)


async def revoke_token_native(jti: str, reason: str, user_id: str | None) -> None:
    from src.storage.documents.revoked_token import RevokedTokenDocument
    existing = await RevokedTokenDocument.get(jti)
    if existing is None:
        coll = RevokedTokenDocument.get_pymongo_collection()
        await coll.insert_one({
            "_id": jti,
            "reason": reason,
            "user_id": str(user_id) if user_id else None,
            "revoked_at": datetime.now(timezone.utc),
        })


async def generate_otp_native(user_doc, purpose: str) -> str:
    """Génère et envoie un OTP à 6 chiffres. Retourne le code généré."""
    import secrets
    import string
    from src.storage.documents.password_verification import PasswordVerificationDocument
    from src.services.email_service import send_otp_email

    coll = PasswordVerificationDocument.get_pymongo_collection()
    await coll.update_many(
        {"user_id": str(user_doc.id), "purpose": purpose, "used": False},
        {"$set": {"used": True}},
    )

    # secrets.choice (CSPRNG) — random.choices() is a non-cryptographic PRNG
    # and must never be used for OTP codes (predictable/brute-forceable seed).
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    now = datetime.now(timezone.utc)
    await coll.insert_one({
        "_id": str(uuid4()), "user_id": str(user_doc.id), "verification_type": "OTP",
        "code_or_token": code, "purpose": purpose,
        "expires_at": now + timedelta(minutes=10), "used": False, "created_at": now,
    })
    send_otp_email(user_doc.email, code, _OTP_PURPOSE_LABELS.get(purpose, purpose))
    return code


async def verify_otp_native(user_id: str, code: str) -> bool:
    """Retourne True et marque le code utilisé s'il est valide et non expiré."""
    from src.storage.documents.password_verification import PasswordVerificationDocument

    now = datetime.now(timezone.utc)
    coll = PasswordVerificationDocument.get_pymongo_collection()
    pv = await coll.find_one({
        "user_id": str(user_id), "verification_type": "OTP", "code_or_token": code,
        "used": False, "expires_at": {"$gt": now},
    })
    if pv is None:
        return False
    await coll.update_one({"_id": pv["_id"]}, {"$set": {"used": True}})
    return True


async def generate_reset_link_native(user_doc, purpose: str) -> str:
    import secrets
    from src.storage.documents.password_verification import PasswordVerificationDocument
    from src.services.email_service import send_reset_link_email

    coll = PasswordVerificationDocument.get_pymongo_collection()
    await coll.update_many(
        {"user_id": str(user_doc.id), "purpose": purpose, "used": False},
        {"$set": {"used": True}},
    )

    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    await coll.insert_one({
        "_id": str(uuid4()), "user_id": str(user_doc.id), "verification_type": "LINK",
        "code_or_token": token, "purpose": purpose,
        "expires_at": now + timedelta(hours=1), "used": False, "created_at": now,
    })
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
    link = f"{frontend_url}/reset-password?token={token}"
    send_reset_link_email(user_doc.email, link)
    return link


async def verify_reset_token_native(token: str) -> Any:
    """Retourne le UserDocument associé si le token est valide, sinon None."""
    from src.storage.documents.password_verification import PasswordVerificationDocument
    from src.storage.documents.user import UserDocument

    now = datetime.now(timezone.utc)
    coll = PasswordVerificationDocument.get_pymongo_collection()
    pv = await coll.find_one({
        "verification_type": "LINK", "code_or_token": token,
        "used": False, "expires_at": {"$gt": now},
    })
    if pv is None:
        return None
    await coll.update_one({"_id": pv["_id"]}, {"$set": {"used": True}})
    return await UserDocument.find_one({"_id": pv["user_id"]})


async def update_user_admin_native(user_id: str, role: str | None, is_active: bool | None,
                                    departement: str | None) -> Any:
    """Retourne None si non trouvé, _CONFLICT (chaîne) si dernier admin actif désactivé."""
    from src.storage.documents.user import UserDocument

    user = await _get_by_str_id(UserDocument, str(user_id))
    if user is None:
        return None

    updates: dict[str, Any] = {}
    if role is not None:
        updates["role"] = role
    if is_active is not None:
        if is_active is False and user.role == "Admin":
            active_admins = await UserDocument.find({"role": "Admin", "is_active": True}).count()
            if active_admins <= 1:
                return "LAST_ADMIN"
        updates["is_active"] = is_active
    if departement is not None:
        updates["departement"] = departement

    if updates:
        coll = UserDocument.get_pymongo_collection()
        await coll.update_one({"_id": str(user_id)}, {"$set": updates})
    return await _get_by_str_id(UserDocument, str(user_id))


async def update_user_profile_native(email: str, nom: str | None, prenom: str | None,
                                      departement: str | None) -> Any:
    from src.storage.documents.user import UserDocument

    user = await UserDocument.find_one({"email": email})
    if user is None:
        return None

    updates: dict[str, Any] = {}
    if nom is not None:
        updates["nom"] = nom
    if prenom is not None:
        updates["prenom"] = prenom
    if departement is not None:
        updates["departement"] = departement

    if updates:
        coll = UserDocument.get_pymongo_collection()
        await coll.update_one({"_id": str(user.id)}, {"$set": updates})
    return await UserDocument.find_one({"email": email})


async def update_user_avatar_native(email: str, avatar: str) -> Any:
    from src.storage.documents.user import UserDocument

    user = await UserDocument.find_one({"email": email})
    if user is None:
        return None
    coll = UserDocument.get_pymongo_collection()
    await coll.update_one({"_id": str(user.id)}, {"$set": {"profile_picture": avatar}})
    return await UserDocument.find_one({"email": email})


async def unlock_account_native(user_id: str) -> Any:
    from src.storage.documents.user import UserDocument

    user = await _get_by_str_id(UserDocument, str(user_id))
    if user is None:
        return None
    coll = UserDocument.get_pymongo_collection()
    await coll.update_one(
        {"_id": str(user_id)},
        {"$set": {"failed_login_attempts": 0, "locked_until": None, "last_failed_login": None}},
    )
    return await _get_by_str_id(UserDocument, str(user_id))
