"""Script de migration one-shot : SQLite → MongoDB.

Usage :
    # Dry-run (aucune écriture) :
    MONGODB_URI=mongodb://localhost:27017 python backend/scripts/migrate_sqlite_to_mongodb.py

    # Exécution réelle :
    MONGODB_URI=mongodb://localhost:27017 python backend/scripts/migrate_sqlite_to_mongodb.py --execute

Opérations :
    1. Connexion SQLAlchemy (SQLite source) + Beanie (MongoDB cible)
    2. Migration table par table, en batch de 100 documents
    3. Upsert par _id → idempotent (relanceable sans doublon)
    4. Recalcule les row_hash des AuditLog avec la formule ms-précision (Phase 4)
    5. Rapport final par collection

Sécurité :
    - Dry-run par défaut : n'écrit rien sans --execute
    - Non-destructif : les données SQLite ne sont jamais supprimées
    - DATA RESIDENCY : aucune donnée n'est envoyée hors du réseau local

Prérequis :
    - MONGODB_URI défini dans l'environnement
    - MONGODB_DB optionnel (défaut : biat_billing)
    - DATABASE_URL optionnel (défaut : sqlite:///./data/invoices.db)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

# --- Chemin Python -----------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import beanie
from motor.motor_asyncio import AsyncIOMotorClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from api.security.audit_integrity import compute_row_hash

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate")

# ── Config -------------------------------------------------------------------

SQLITE_URL  = os.getenv("DATABASE_URL", "sqlite:///./data/invoices.db")
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB  = os.getenv("MONGODB_DB", "biat_billing")
BATCH       = 100   # documents par insert_many


# ── Helpers ------------------------------------------------------------------

def _uuid(v: Any) -> UUID | None:
    if v is None:
        return None
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except (ValueError, AttributeError):
        return None


def _str_uuid(v: Any) -> str | None:
    u = _uuid(v)
    return str(u) if u else None


def _dt(v: Any) -> datetime | None:
    """Convertit une valeur DATETIME SQLite en datetime UTC.

    session.execute(text(...)) ne passe pas par les TypeDecorator SQLAlchemy :
    les colonnes DATETIME reviennent comme de simples chaînes
    ("2026-01-05 09:00:00.000000"), pas comme des objets datetime.
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            parsed = datetime.fromisoformat(v)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _date(v: Any) -> datetime | None:
    """Convertit une valeur DATE SQLite (chaîne "YYYY-MM-DD") en datetime minuit UTC.

    BSON n'a pas de type "date seule" — seul datetime est encodable. Beanie fait
    la même conversion en interne pour les champs Pydantic typés `date`
    (stockage en datetime minuit, décodage en date à la lecture). Voir _dt().
    """
    if v is None:
        d: date | None = None
    elif isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    elif isinstance(v, str):
        v = v.strip()
        if not v:
            d = None
        else:
            try:
                d = date.fromisoformat(v[:10])
            except ValueError:
                d = None
    else:
        d = None
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _json(v: Any) -> Any:
    """Décode une colonne JSON SQLite (texte brut via session.execute(text(...))).

    Même cause racine que _dt()/_date() : les colonnes JSON reviennent comme
    des chaînes ("null", "[85000.0, ...]", "{...}"), pas comme des objets
    Python déjà désérialisés. Sans ce parsing, Beanie stocke la chaîne brute
    et casse la validation Pydantic à la lecture (list[float]/dict attendus).
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return None
    return None


class _Stats:
    def __init__(self, name: str):
        self.name = name
        self.ok = self.skip = self.err = 0

    def report(self) -> str:
        return f"  {self.name:<36} ok={self.ok:>5}  skip={self.skip:>4}  err={self.err:>3}"


# ── Conversion des rows SQLite ------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convertit un Row SQLAlchemy en dict Python brut."""
    if hasattr(row, "_asdict"):
        return dict(row._asdict())
    if hasattr(row, "__dict__"):
        return {k: v for k, v in row.__dict__.items() if not k.startswith("_")}
    return dict(row)


# ── Connexions ----------------------------------------------------------------

async def _connect_mongo() -> AsyncIOMotorClient:
    client = AsyncIOMotorClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    await client.admin.command("ping")
    log.info("MongoDB connecté — base=%s", MONGODB_DB)
    return client


def _connect_sqlite() -> Session:
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    return Session(engine)


# ── Migrations par collection -------------------------------------------------

async def _migrate_users(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.user import UserDocument
    st = _Stats("users")
    rows = session.execute(text("SELECT * FROM users")).fetchall()
    batch: list[dict] = []

    for r in rows:
        d = _row_to_dict(r)
        doc = {
            "_id": str(_uuid(d["id"])),
            "nom": d.get("nom") or "",
            "prenom": d.get("prenom") or "",
            "email": d.get("email") or "",
            "hashed_password": d.get("hashed_password") or "",
            "role": d.get("role") or "",
            "departement": d.get("departement") or "",
            "is_first_login": bool(d.get("is_first_login", True)),
            "is_active": bool(d.get("is_active", True)),
            "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
            "failed_login_attempts": int(d.get("failed_login_attempts") or 0),
            "locked_until": _dt(d.get("locked_until")),
            "last_failed_login": _dt(d.get("last_failed_login")),
            "last_login_at": _dt(d.get("last_login_at")),
            "last_login_ip": d.get("last_login_ip"),
            "profile_picture": d.get("profile_picture"),
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(UserDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(UserDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_audit_logs(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.audit_log import AuditLogDocument
    st = _Stats("audit_logs")
    rows = session.execute(text("SELECT * FROM audit_logs ORDER BY created_at")).fetchall()
    batch: list[dict] = []

    for r in rows:
        d = _row_to_dict(r)

        # Recalcul du row_hash avec la formule ms-précision (Phase 4)
        class _Proxy:
            pass
        proxy = _Proxy()
        proxy.id = str(_uuid(d["id"]))
        raw_dt = _dt(d.get("created_at"))
        proxy.created_at = raw_dt
        proxy.user_id = d.get("user_id")
        proxy.action = d.get("action") or ""
        proxy.resource_type = d.get("resource_type")
        proxy.resource_id = d.get("resource_id")
        proxy.status = d.get("status") or "SUCCESS"
        proxy.ip_address = d.get("ip_address")

        new_hash = compute_row_hash(proxy)   # formule ms (Phase 4)

        doc = {
            "_id": str(_uuid(d["id"])),
            "created_at": raw_dt or datetime.now(timezone.utc),
            "user_id": d.get("user_id"),
            "user_email": d.get("user_email"),
            "user_role": d.get("user_role"),
            "actor": d.get("actor") or "",
            "action": d.get("action") or "",
            "resource_type": d.get("resource_type"),
            "resource_id": d.get("resource_id"),
            "entity_id": d.get("entity_id"),
            "before_value": _json(d.get("before_value")),
            "after_value": _json(d.get("after_value")),
            "ip_address": d.get("ip_address"),
            "user_agent": d.get("user_agent"),
            "status": d.get("status") or "SUCCESS",
            "detail": d.get("detail"),
            "row_hash": new_hash,
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(AuditLogDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(AuditLogDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_revoked_tokens(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.revoked_token import RevokedTokenDocument
    st = _Stats("revoked_tokens")
    rows = session.execute(text("SELECT * FROM revoked_tokens")).fetchall()
    batch: list[dict] = []

    for r in rows:
        d = _row_to_dict(r)
        doc = {
            "_id": d.get("jti") or "",
            "revoked_at": _dt(d.get("revoked_at")) or datetime.now(timezone.utc),
            "reason": d.get("reason") or "logout",
            "user_id": d.get("user_id"),
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(RevokedTokenDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(RevokedTokenDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_active_tokens(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.active_token import ActiveTokenDocument
    st = _Stats("active_tokens")
    rows = session.execute(text("SELECT * FROM active_tokens")).fetchall()
    batch: list[dict] = []

    for r in rows:
        d = _row_to_dict(r)
        expires_at = _dt(d.get("expires_at"))
        if expires_at and expires_at < datetime.now(timezone.utc):
            st.skip += 1   # déjà expiré, MongoDB TTL l'aurait supprimé
            continue
        doc = {
            "_id": d.get("jti") or "",
            "user_id": d.get("user_id") or "",
            "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
            "expires_at": expires_at or datetime.now(timezone.utc),
            "ip_address": d.get("ip_address"),
            "user_agent": d.get("user_agent"),
            "revoked": bool(d.get("revoked", False)),
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(ActiveTokenDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(ActiveTokenDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_invoices(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.invoice import (
        InvoiceDocument, LineItemEmbed, StatusHistoryEmbed, ValidationFlagEmbed,
    )
    st = _Stats("invoices  (+line_items+flags+history)")

    rows = session.execute(text("SELECT * FROM invoices")).fetchall()
    line_items_all = session.execute(text("SELECT * FROM line_items")).fetchall()
    flags_all = session.execute(text("SELECT * FROM validation_flags")).fetchall()
    history_all = session.execute(text("SELECT * FROM status_history")).fetchall()

    li_by_inv: dict[str, list] = {}
    for r in line_items_all:
        d = _row_to_dict(r)
        key = str(_uuid(d["invoice_id"]))
        li_by_inv.setdefault(key, []).append(d)

    fl_by_inv: dict[str, list] = {}
    for r in flags_all:
        d = _row_to_dict(r)
        key = str(_uuid(d["invoice_id"]))
        fl_by_inv.setdefault(key, []).append(d)

    hi_by_inv: dict[str, list] = {}
    for r in history_all:
        d = _row_to_dict(r)
        key = str(_uuid(d["invoice_id"]))
        hi_by_inv.setdefault(key, []).append(d)

    batch: list[dict] = []
    for r in rows:
        d = _row_to_dict(r)
        inv_id = str(_uuid(d["id"]))

        line_items = [
            {
                "id": str(_uuid(li["id"])),
                "line_number": li.get("line_number") or 0,
                "description": li.get("description"),
                "quantity": li.get("quantity"),
                "unit_price": li.get("unit_price"),
                "line_total": li.get("line_total"),
                "tva_rate": li.get("tva_rate"),
            }
            for li in li_by_inv.get(inv_id, [])
        ]
        flags = [
            {
                "id": str(_uuid(fl["id"])),
                "flag_type": fl.get("flag_type") or "",
                "severity": fl.get("severity") or "",
                "field_name": fl.get("field_name"),
                "message": fl.get("message") or "",
                "resolved": bool(fl.get("resolved", False)),
                "resolved_at": _dt(fl.get("resolved_at")),
                "resolved_by": fl.get("resolved_by"),
                "created_at": _dt(fl.get("created_at")) or datetime.now(timezone.utc),
            }
            for fl in fl_by_inv.get(inv_id, [])
        ]
        history = [
            {
                "id": str(_uuid(hi["id"])),
                "from_status": hi.get("from_status"),
                "to_status": hi.get("to_status") or "",
                "changed_at": _dt(hi.get("changed_at")) or datetime.now(timezone.utc),
                "changed_by": hi.get("changed_by") or "agent",
                "notes": hi.get("notes"),
            }
            for hi in hi_by_inv.get(inv_id, [])
        ]

        doc: dict[str, Any] = {"_id": inv_id}
        scalar_fields = [
            "file_hash", "raw_file_path", "file_mime_type", "direction", "status",
            "extraction_method", "retry_count", "last_error",
            "issuer_name", "issuer_name_conf", "issuer_tax_id", "issuer_tax_id_conf",
            "recipient_name", "recipient_name_conf", "recipient_tax_id", "recipient_tax_id_conf",
            "invoice_number", "invoice_number_conf", "invoice_date_conf",
            "due_date_conf",
            "amount_ht", "amount_ht_conf", "tva_rate", "tva_rate_conf",
            "tva_amount", "tva_amount_conf", "amount_ttc", "amount_ttc_conf",
            "currency",
            "cost_catalog_id", "accounting_compte", "accounting_label",
            "charge_nature", "charge_type", "matched_po_id", "matched_contract_id",
            "matched_client_id", "payment_term_days", "classification_reason",
            "classification_pass", "human_review_required", "human_review_notes",
            "reviewed_by", "export_reference",
        ]
        for f in scalar_fields:
            doc[f] = d.get(f)
        doc["raw_extracted_json"] = _json(d.get("raw_extracted_json"))
        doc["invoice_date"] = _date(d.get("invoice_date"))
        doc["due_date"] = _date(d.get("due_date"))
        for tf in ("received_at", "extracted_at", "classified_at", "validated_at",
                   "exported_at", "paid_at", "collected_at", "created_at",
                   "updated_at", "reviewed_at"):
            doc[tf] = _dt(d.get(tf))

        doc["line_items"] = line_items
        doc["flags"] = flags
        doc["history"] = history

        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(InvoiceDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(InvoiceDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_simple(
    session: Session, dry: bool,
    table: str,
    doc_class,
    build_fn,
    label: str | None = None,
) -> _Stats:
    """Migre une table simple (sans relations embarquées) via une fonction de transformation."""
    st = _Stats(label or table)
    rows = session.execute(text(f"SELECT * FROM {table}")).fetchall()  # noqa: S608
    batch: list[dict] = []

    for r in rows:
        d = _row_to_dict(r)
        try:
            doc = build_fn(d)
            batch.append(doc)
        except Exception as exc:
            log.warning("%s — ligne ignorée : %s", table, exc)
            st.err += 1
            continue
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(doc_class, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(doc_class, batch)
        st.ok += len(batch)

    return st


# ── Upsert générique ----------------------------------------------------------

async def _upsert_batch(doc_class, batch: list[dict]) -> None:
    """Insert ou remplace chaque document par _id (idempotent)."""
    coll = doc_class.get_pymongo_collection()
    for doc in batch:
        await coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)


# ── Fonctions de transformation des tables simples ---------------------------

def _build_payment(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "invoice_id": str(_uuid(d["invoice_id"])),
        "amount": float(d.get("amount") or 0),
        "payment_date": _date(d.get("payment_date")),
        "payment_reference": d.get("payment_reference"),
        "payment_method": d.get("payment_method"),
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
    }


def _build_budget_plan(d: dict) -> dict:
    return {
        "_id": str(_uuid(d.get("_id") or __import__("uuid").uuid4())),
        "catalog_id": d.get("catalog_id") or "",
        "year": int(d.get("year") or 2026),
        "label": d.get("label") or "",
        "monthly": _json(d.get("monthly")) or [0.0] * 12,
        "note": d.get("note"),
        "updated_at": _dt(d.get("updated_at")) or datetime.now(timezone.utc),
    }


def _build_payment_installment(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "invoice_id": _str_uuid(d.get("invoice_id")) or "",
        "installment_number": int(d.get("installment_number") or 1),
        "total_installments": int(d.get("total_installments") or 1),
        "base_amount": float(d.get("base_amount") or 0),
        "current_amount": float(d.get("current_amount") or 0),
        "due_date": _date(d.get("due_date")),
        "paid_date": _date(d.get("paid_date")),
        "paid_amount": d.get("paid_amount"),
        "status": d.get("status") or "PENDING",
        "late_periods": int(d.get("late_periods") or 0),
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
        "updated_at": _dt(d.get("updated_at")) or datetime.now(timezone.utc),
    }


def _build_feedback(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "invoice_id": _str_uuid(d.get("invoice_id")) or "",
        "original_compte": d.get("original_compte") or "",
        "corrected_compte": d.get("corrected_compte") or "",
        "original_catalog_id": d.get("original_catalog_id"),
        "corrected_catalog_id": d.get("corrected_catalog_id"),
        "invoice_text": d.get("invoice_text") or "",
        "corrected_by": d.get("corrected_by") or "",
        "corrected_at": _dt(d.get("corrected_at")) or datetime.now(timezone.utc),
    }


def _build_notification(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "type": d.get("type") or "",
        "title": d.get("title") or "",
        "body": d.get("body") or "",
        "is_read": bool(d.get("is_read", False)),
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
        "invoice_id": _str_uuid(d.get("invoice_id")),
    }


def _build_password_verification(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "user_id": str(_uuid(d["user_id"])),
        "verification_type": d.get("verification_type") or "OTP",
        "code_or_token": d.get("code_or_token") or "",
        "purpose": d.get("purpose") or "",
        "expires_at": _dt(d.get("expires_at")) or datetime.now(timezone.utc),
        "used": bool(d.get("used", False)),
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
    }


def _build_charte(d: dict) -> dict:
    return {
        "_id": d.get("id") or "",
        "project_id": d.get("project_id") or "",
        "project_name": d.get("project_name") or "",
        "client": d.get("client") or "BIAT",
        "valid_from": _date(d.get("valid_from")),
        "valid_until": _date(d.get("valid_until")),
        "budget_jh": float(d.get("budget_jh") or 0),
        "taux_jh": float(d.get("taux_jh") or 0),
        "is_active": bool(d.get("is_active", True)),
    }


def _build_phase(d: dict) -> dict:
    return {
        "_id": d.get("id") or "",
        "project_id": d.get("project_id") or "",
        "name": d.get("name") or "",
        "description": d.get("description") or "",
        "planned_jh": float(d.get("planned_jh") or 0),
        "consumed_jh": float(d.get("consumed_jh") or 0),
        "status": d.get("status") or "open",
        "closed_date": _date(d.get("closed_date")),
        "livrables": d.get("livrables") or "[]",
    }


def _build_livrable(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "phase_id": str(d.get("phase_id") or ""),
        "titre": d.get("titre") or "",
        "description": d.get("description") or "",
        "date_livraison_prevue": _date(d.get("date_livraison_prevue")),
        "date_livraison_reelle": _date(d.get("date_livraison_reelle")),
        "statut": d.get("statut") or "EN_ATTENTE",
        "fichier_path": d.get("fichier_path"),
        "created_by": d.get("created_by") or "",
    }


def _build_ligne_budget(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "projet_id": d.get("projet_id") or "",
        "categorie": d.get("categorie") or "",
        "montant_prevu": float(d.get("montant_prevu") or 0),
        "montant_consomme": float(d.get("montant_consomme") or 0),
        "devise": d.get("devise") or "TND",
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
    }


def _build_feuille_de_route(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "titre": d.get("titre") or "",
        "description": d.get("description") or "",
        "date_debut": _date(d.get("date_debut")),
        "date_fin": _date(d.get("date_fin")),
        "projet_id": d.get("projet_id"),
        "responsable_id": d.get("responsable_id"),
        "statut": d.get("statut") or "PLANIFIE",
        "priorite": d.get("priorite") or "MOYENNE",
        "annee": int(d.get("annee") or 2026),
    }


def _build_risque(d: dict) -> dict:
    return {
        "_id": str(_uuid(d["id"])),
        "titre": d.get("titre") or "",
        "description": d.get("description") or "",
        "type_risque": d.get("type_risque") or "AUTRE",
        "probabilite": d.get("probabilite") or "",
        "impact": d.get("impact") or "",
        "niveau_criticite": d.get("niveau_criticite") or "",
        "statut": d.get("statut") or "IDENTIFIE",
        "plan_mitigation": d.get("plan_mitigation") or "",
        "responsable_id": d.get("responsable_id"),
        "date_identification": _date(d.get("date_identification")),
        "date_echeance_mitigation": _date(d.get("date_echeance_mitigation")),
        "date_cloture": _date(d.get("date_cloture")),
        "feuille_route_id": _str_uuid(d.get("feuille_route_id")),
        "projet_id": d.get("projet_id"),
        "created_by": d.get("created_by") or "",
        "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
        "updated_at": _dt(d.get("updated_at")) or datetime.now(timezone.utc),
    }


async def _migrate_fiches_mensuelles(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.fiche_mensuelle import FicheMensuelleDocument
    st = _Stats("fiches_mensuelles (+phase_links+avances)")

    fiches = session.execute(text("SELECT * FROM fiches_mensuelles")).fetchall()
    phase_links = session.execute(text("SELECT * FROM fiche_phases")).fetchall()
    avances = session.execute(text("SELECT * FROM avances_programmees")).fetchall()

    pl_by_fiche: dict[str, list] = {}
    for r in phase_links:
        d = _row_to_dict(r)
        pl_by_fiche.setdefault(d["fiche_id"], []).append(d)

    av_by_fiche: dict[str, list] = {}
    for r in avances:
        d = _row_to_dict(r)
        av_by_fiche.setdefault(d["fiche_id"], []).append(d)

    batch: list[dict] = []
    for r in fiches:
        d = _row_to_dict(r)
        fiche_id = d["id"]

        pls = [{"fiche_id": pl["fiche_id"], "phase_id": pl["phase_id"]}
               for pl in pl_by_fiche.get(fiche_id, [])]
        avs = [
            {
                "id": str(_uuid(av["id"])),
                "project_id": av.get("project_id") or "",
                "charte_id": av.get("charte_id") or "",
                "description": av.get("description") or "",
                "montant_ht": float(av.get("montant_ht") or 0),
                "schedule_reference": av.get("schedule_reference") or "",
            }
            for av in av_by_fiche.get(fiche_id, [])
        ]

        doc = {
            "_id": fiche_id,
            "period_month": int(d.get("period_month") or 1),
            "period_year": int(d.get("period_year") or 2026),
            "prepared_by": d.get("prepared_by") or "",
            "prepared_at": _dt(d.get("prepared_at")) or datetime.now(timezone.utc),
            "status": d.get("status") or "draft",
            "invoice_number": d.get("invoice_number"),
            "phase_links": pls,
            "avances": avs,
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(FicheMensuelleDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(FicheMensuelleDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_assets(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.asset import AssetDocument
    st = _Stats("assets (+project_links)")

    try:
        assets = session.execute(text("SELECT * FROM assets")).fetchall()
    except Exception:
        log.warning("Table 'assets' absente — ignorée.")
        return st

    try:
        links = session.execute(text("SELECT * FROM asset_project_links")).fetchall()
    except Exception:
        links = []

    lk_by_asset: dict[str, list] = {}
    for r in links:
        d = _row_to_dict(r)
        key = str(_uuid(d["asset_id"]))
        lk_by_asset.setdefault(key, []).append(d)

    batch: list[dict] = []
    for r in assets:
        d = _row_to_dict(r)
        asset_id = str(_uuid(d["id"]))
        pls = [
            {"project_id": lk["project_id"], "allocation_pct": float(lk.get("allocation_pct") or 0)}
            for lk in lk_by_asset.get(asset_id, [])
        ]
        doc: dict[str, Any] = {"_id": asset_id, "project_links": pls}
        for f in ("designation", "compte_immobilisation", "compte_amortissement",
                  "depreciation_method", "supplier_invoice_id", "amortization_source",
                  "notes"):
            doc[f] = d.get(f) or ""
        for f in ("acquisition_cost_ht", "useful_life_years"):
            doc[f] = d.get(f)
        doc["acquisition_date"] = _date(d.get("acquisition_date"))
        doc["fully_depreciated"] = bool(d.get("fully_depreciated", False))
        doc["created_at"] = _dt(d.get("created_at")) or datetime.now(timezone.utc)

        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(AssetDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(AssetDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_journal_entries(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.journal_entry import JournalEntryDocument
    st = _Stats("journal_entries (+lines)")

    try:
        entries = session.execute(text("SELECT * FROM journal_entries")).fetchall()
        lines   = session.execute(text("SELECT * FROM journal_lines")).fetchall()
    except Exception as exc:
        log.warning("Tables journal absentes — ignorées : %s", exc)
        return st

    lines_by_entry: dict[str, list] = {}
    for r in lines:
        d = _row_to_dict(r)
        key = str(_uuid(d["entry_id"]))
        lines_by_entry.setdefault(key, []).append(d)

    batch: list[dict] = []
    for r in entries:
        d = _row_to_dict(r)
        entry_id = str(_uuid(d["id"]))
        jls = [
            {
                "id": str(_uuid(ln["id"])),
                "compte": ln.get("compte") or "",
                "libelle": ln.get("libelle") or "",
                "debit": ln.get("debit"),
                "credit": ln.get("credit"),
            }
            for ln in lines_by_entry.get(entry_id, [])
        ]
        doc = {
            "_id": entry_id,
            "reference": d.get("reference") or "",
            "date_ecriture": _date(d.get("date_ecriture")),
            "description": d.get("description") or "",
            "source_invoice_id": _str_uuid(d.get("source_invoice_id")),
            "source_asset_id": _str_uuid(d.get("source_asset_id")),
            "accounting_explanation": d.get("accounting_explanation"),
            "created_at": _dt(d.get("created_at")) or datetime.now(timezone.utc),
            "lines": jls,
        }
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(JournalEntryDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(JournalEntryDocument, batch)
        st.ok += len(batch)

    return st


async def _migrate_client_invoices(session: Session, dry: bool) -> _Stats:
    from src.storage.documents.client_invoice import ClientInvoiceDocument
    st = _Stats("client_invoices (+line_items)")

    try:
        invoices  = session.execute(text("SELECT * FROM client_invoices")).fetchall()
        line_rows = session.execute(text("SELECT * FROM client_line_items")).fetchall()
    except Exception as exc:
        log.warning("Tables client_invoices absentes — ignorées : %s", exc)
        return st

    li_by_inv: dict[str, list] = {}
    for r in line_rows:
        d = _row_to_dict(r)
        key = str(_uuid(d["invoice_id"]))
        li_by_inv.setdefault(key, []).append(d)

    batch: list[dict] = []
    for r in invoices:
        d = _row_to_dict(r)
        inv_id = str(_uuid(d["id"]))
        lis = [
            {
                "id": str(_uuid(li.get("id") or __import__("uuid").uuid4())),
                "description": li.get("description") or "",
                "quantity": float(li.get("quantity") or 0),
                "unit_price": float(li.get("unit_price") or 0),
                "line_total": float(li.get("line_total") or 0),
                "tva_rate": float(li.get("tva_rate") or 0),
                "tva_amount": float(li.get("tva_amount") or 0),
                "compte_produit": li.get("compte_produit") or "",
            }
            for li in li_by_inv.get(inv_id, [])
        ]
        doc: dict[str, Any] = {"_id": inv_id, "line_items": lis}
        for f in ("invoice_number", "issuer_name", "issuer_tax_id", "issuer_address",
                  "client_id", "client_name", "client_tax_id", "client_address",
                  "status", "source_template_id", "notes", "pdf_path"):
            doc[f] = d.get(f)
        for f in ("amount_ht", "tva_amount", "amount_ttc"):
            doc[f] = float(d.get(f) or 0)
        for tf in ("created_at", "sent_at", "paid_at"):
            doc[tf] = _dt(d.get(tf))
        doc["invoice_date"] = _date(d.get("invoice_date"))
        doc["due_date"] = _date(d.get("due_date"))
        batch.append(doc)
        if len(batch) >= BATCH:
            if not dry:
                await _upsert_batch(ClientInvoiceDocument, batch)
            st.ok += len(batch)
            batch = []

    if batch:
        if not dry:
            await _upsert_batch(ClientInvoiceDocument, batch)
        st.ok += len(batch)

    return st


# ── Main ---------------------------------------------------------------------

async def run(execute: bool) -> None:
    dry = not execute
    mode = "EXÉCUTION RÉELLE" if execute else "DRY-RUN (aucune écriture)"
    log.info("━━━ Migration SQLite → MongoDB  [%s] ━━━", mode)

    if not MONGODB_URI:
        log.error("MONGODB_URI non défini — abandon.")
        sys.exit(1)

    # Connexion MongoDB + Beanie
    client = await _connect_mongo()
    db = client[MONGODB_DB]
    from src.storage.mongodb import _all_document_models
    await beanie.init_beanie(database=db, document_models=_all_document_models())

    # Connexion SQLite
    session = _connect_sqlite()

    all_stats: list[_Stats] = []

    # ── Collections simples ---------------------------------------------------
    from src.storage.documents.payment                 import PaymentDocument
    from src.storage.documents.budget_plan             import BudgetPlanDocument
    from src.storage.documents.payment_installment     import PaymentInstallmentDocument
    from src.storage.documents.classification_feedback import ClassificationFeedbackDocument
    from src.storage.documents.notification            import NotificationDocument
    from src.storage.documents.password_verification   import PasswordVerificationDocument
    from src.storage.documents.charte_projet           import CharteProjetDocument
    from src.storage.documents.phase                   import PhaseDocument
    from src.storage.documents.livrable                import LivrableDocument
    from src.storage.documents.ligne_budget            import LigneBudgetDocument
    from src.storage.documents.feuille_de_route        import FeuilleDeRouteDocument
    from src.storage.documents.risque                  import RisqueDocument

    simple: list[tuple[str, Any, Any, str]] = [
        ("payments",                PaymentDocument,                _build_payment,               "payments"),
        ("budget_plan_entries",     BudgetPlanDocument,             _build_budget_plan,           "budget_plan_entries"),
        ("payment_installments",    PaymentInstallmentDocument,     _build_payment_installment,   "payment_installments"),
        ("classification_feedback", ClassificationFeedbackDocument, _build_feedback,              "classification_feedback"),
        ("notifications",           NotificationDocument,           _build_notification,          "notifications"),
        ("password_verifications",  PasswordVerificationDocument,   _build_password_verification, "password_verifications"),
        ("chartes_projet",          CharteProjetDocument,           _build_charte,                "chartes_projet"),
        ("phases",                  PhaseDocument,                  _build_phase,                 "phases"),
        ("livrables",               LivrableDocument,               _build_livrable,              "livrables"),
        ("lignes_budget",           LigneBudgetDocument,            _build_ligne_budget,          "lignes_budget"),
        ("feuilles_de_route",       FeuilleDeRouteDocument,         _build_feuille_de_route,      "feuilles_de_route"),
        ("risques",                 RisqueDocument,                 _build_risque,                "risques"),
    ]

    # ── Migrations complexes (avec sous-documents) ----------------------------
    for table, doc_class, build_fn, label in simple:
        try:
            st = await _migrate_simple(session, dry, table, doc_class, build_fn, label)
            all_stats.append(st)
        except Exception as exc:
            log.warning("Table '%s' ignorée : %s", table, exc)
            all_stats.append(_Stats(label))

    all_stats.append(await _migrate_users(session, dry))
    all_stats.append(await _migrate_audit_logs(session, dry))
    all_stats.append(await _migrate_revoked_tokens(session, dry))
    all_stats.append(await _migrate_active_tokens(session, dry))
    all_stats.append(await _migrate_invoices(session, dry))
    all_stats.append(await _migrate_fiches_mensuelles(session, dry))
    all_stats.append(await _migrate_assets(session, dry))
    all_stats.append(await _migrate_journal_entries(session, dry))
    all_stats.append(await _migrate_client_invoices(session, dry))

    # ── Rapport ---------------------------------------------------------------
    session.close()
    client.close()

    total_ok  = sum(s.ok  for s in all_stats)
    total_err = sum(s.err for s in all_stats)
    total_skip= sum(s.skip for s in all_stats)

    print()
    print("┌─ Rapport de migration ──────────────────────────────────────────────")
    for st in all_stats:
        print(st.report())
    print(f"├─ TOTAL  ok={total_ok}  skip={total_skip}  err={total_err}")
    print(f"└─ Mode : {mode}")
    if dry:
        print()
        print("  ⟹  Relancez avec --execute pour appliquer les changements.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migre SQLite → MongoDB")
    parser.add_argument(
        "--execute", action="store_true",
        help="Applique réellement les écritures (sans ce flag : dry-run).",
    )
    args = parser.parse_args()
    asyncio.run(run(args.execute))


if __name__ == "__main__":
    main()
