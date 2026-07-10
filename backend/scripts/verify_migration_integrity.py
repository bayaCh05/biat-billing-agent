"""Vérification d'intégrité post-migration SQLite → MongoDB (Phase 7, Étape 4).

Lecture seule des deux bases — ne modifie rien. Compare, table par table :
    1. Le nombre de documents Mongo vs le nombre de lignes SQLite (en tenant
       compte des sous-documents embarqués : line_items, flags, history, etc.)
    2. Que chaque InvoiceDocument._id est l'UUID exact de invoices.id (SQLite)
    3. Que le contenu métier (pas seulement l'id) correspond bien à la même ligne

Usage :
    python backend/scripts/verify_migration_integrity.py

Variables d'environnement :
    DATABASE_URL — SQLite source (défaut : sqlite:///./data/invoices.db)
    MONGODB_URI  — MongoDB cible (défaut : mongodb://localhost:27017)
    MONGODB_DB   — Nom de la base (défaut : biat_billing)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from uuid import UUID

from pymongo import MongoClient

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/invoices.db")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "biat_billing")

SQLITE_PATH = DATABASE_URL.replace("sqlite:///", "").replace("sqlite:////", "/")


def _norm_id(v) -> str:
    return str(UUID(str(v)))


def _connect():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5_000)
    client.admin.command("ping")
    return conn, client[MONGODB_DB]


PASS, FAIL, INFO = "✅", "❌", "ℹ️ "

results: list[tuple[str, str]] = []  # (status, message)


def check(label: str, expected: int, actual: int, note: str = "") -> None:
    status = PASS if expected == actual else FAIL
    msg = f"{label}: SQLite={expected}  Mongo={actual}"
    if note:
        msg += f"  ({note})"
    results.append((status, msg))


def info(msg: str) -> None:
    results.append((INFO, msg))


def main() -> None:
    conn, db = _connect()

    def sql_count(table: str, where: str = "") -> int:
        q = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
        if where:
            q += f" WHERE {where}"
        return conn.execute(q).fetchone()[0]

    def mongo_count(coll: str) -> int:
        return db[coll].count_documents({})

    def mongo_embedded_sum(coll: str, field: str) -> int:
        pipeline = [
            {"$project": {"n": {"$size": {"$ifNull": [f"${field}", []]}}}},
            {"$group": {"_id": None, "total": {"$sum": "$n"}}},
        ]
        r = list(db[coll].aggregate(pipeline))
        return r[0]["total"] if r else 0

    # ── 1. Tables simples 1:1 ─────────────────────────────────────────────────
    simple = [
        ("users", "users"),
        ("audit_logs", "audit_logs"),
        ("revoked_tokens", "revoked_tokens"),
        ("payments", "payments"),
        ("classification_feedback", "classification_feedback"),
        ("notifications", "notifications"),
        ("chartes_projet", "chartes_projet"),
        ("phases", "phases"),
        ("livrables", "livrables"),
        ("lignes_budget", "lignes_budget"),
        ("feuilles_de_route", "feuilles_de_route"),
        ("risques", "risques"),
    ]
    for table, coll in simple:
        check(f"{table} -> {coll}", sql_count(table), mongo_count(coll))

    # budget_plan_entries : clé composite (catalog_id, year), pas de colonne "id"
    check("budget_plan_entries -> budget_plan_entries",
          sql_count("budget_plan_entries"), mongo_count("budget_plan_entries"))

    # ── 2. active_tokens : les sessions déjà expirées sont volontairement exclues ──
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    sql_active = sql_count("active_tokens", f"expires_at >= '{now_iso}'")
    sql_expired = sql_count("active_tokens", f"expires_at < '{now_iso}'")
    mongo_active = mongo_count("active_tokens")
    check("active_tokens -> active_tokens (non expirés seulement)", sql_active, mongo_active,
          note=f"{sql_expired} session(s) expirée(s) exclue(s) volontairement")

    # ── 3. password_verifications : TTL Mongo purge les codes déjà expirés ────
    pv_mongo = mongo_count("password_verifications")
    pv_sql = sql_count("password_verifications")
    info(f"password_verifications : SQLite={pv_sql}  Mongo={pv_mongo}  "
         "(TTL index expireAfterSeconds=0 sur expires_at — les codes déjà "
         "expirés sont automatiquement purgés par MongoDB peu après l'insertion, "
         "ce n'est pas une perte de données)")

    # payment_installments (pas de sous-documents)
    check("payment_installments -> payment_installments",
          sql_count("payment_installments"), mongo_count("payment_installments"))

    # ── 4. Tables avec sous-documents embarqués ────────────────────────────────
    check("invoices -> InvoiceDocument (parent)", sql_count("invoices"), mongo_count("invoices"))
    check("  ↳ line_items embarqués", sql_count("line_items"),
          mongo_embedded_sum("invoices", "line_items"))
    check("  ↳ validation_flags embarqués", sql_count("validation_flags"),
          mongo_embedded_sum("invoices", "flags"))
    check("  ↳ status_history embarqué", sql_count("status_history"),
          mongo_embedded_sum("invoices", "history"))

    check("journal_entries -> JournalEntryDocument (parent)",
          sql_count("journal_entries"), mongo_count("journal_entries"))
    check("  ↳ journal_lines embarquées", sql_count("journal_lines"),
          mongo_embedded_sum("journal_entries", "lines"))

    check("assets -> AssetDocument (parent)", sql_count("assets"), mongo_count("assets"))
    check("  ↳ asset_project_links embarqués", sql_count("asset_project_links"),
          mongo_embedded_sum("assets", "project_links"))

    check("client_invoices -> ClientInvoiceDocument (parent)",
          sql_count("client_invoices"), mongo_count("client_invoices"))
    check("  ↳ client_line_items embarqués", sql_count("client_line_items"),
          mongo_embedded_sum("client_invoices", "line_items"))

    check("fiches_mensuelles -> FicheMensuelleDocument (parent)",
          sql_count("fiches_mensuelles"), mongo_count("fiches_mensuelles"))
    check("  ↳ fiche_phases embarqués", sql_count("fiche_phases"),
          mongo_embedded_sum("fiches_mensuelles", "phase_links"))
    check("  ↳ avances_programmees embarquées", sql_count("avances_programmees"),
          mongo_embedded_sum("fiches_mensuelles", "avances"))

    # ── 5. Identité des UUID + cohérence du contenu métier (Phase 0.5 / ChromaDB) ──
    invoice_rows = conn.execute(
        "SELECT id, invoice_number, amount_ttc, direction, status FROM invoices"
    ).fetchall()
    uuid_ok = 0
    uuid_mismatch: list[str] = []
    content_mismatch: list[str] = []
    for row in invoice_rows:
        expected_id = _norm_id(row["id"])
        doc = db["invoices"].find_one({"_id": expected_id})
        if doc is None:
            uuid_mismatch.append(row["id"])
            continue
        if doc["_id"] != expected_id:
            uuid_mismatch.append(row["id"])
            continue
        uuid_ok += 1
        if (doc.get("invoice_number") != row["invoice_number"]
                or doc.get("direction") != row["direction"]
                or doc.get("status") != row["status"]):
            content_mismatch.append(row["id"])

    status = PASS if not uuid_mismatch and not content_mismatch else FAIL
    results.append((status,
        f"InvoiceDocument._id == UUID(invoices.id) pour {uuid_ok}/{len(invoice_rows)} factures"
        + (f" — {len(uuid_mismatch)} id manquant(s)/divergent(s): {uuid_mismatch[:5]}"
           if uuid_mismatch else "")
        + (f" — {len(content_mismatch)} contenu divergent: {content_mismatch[:5]}"
           if content_mismatch else "")))

    # ── Rapport ────────────────────────────────────────────────────────────────
    print("┌─ Vérification d'intégrité post-migration ─────────────────────────────")
    n_fail = 0
    for status, msg in results:
        print(f"  {status}  {msg}")
        if status == FAIL:
            n_fail += 1
    print(f"└─ {len(results) - n_fail}/{len(results)} vérifications OK")

    conn.close()
    client_close = db.client
    client_close.close()

    if n_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
