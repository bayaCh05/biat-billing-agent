#!/usr/bin/env python3
"""BIAT IT — Comprehensive demo data seeder (Part 2 complement).

Adds what seed_demo.py does NOT cover:
  • 4 demo users (one per role: Admin, Comptable, Chef de Projet, Direction)
  • Livrables for all 9 existing phases
  • Budget lines (lignes_budget) for all 3 projects
  • Feuille de route 2026 (6 items)
  • Audit log entries (realistic history)

Safe to run multiple times — all operations are idempotent.

Usage (from project root):
    source .venv/bin/activate
    python scripts/seed_demo_data.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from sqlalchemy import select
    from src.storage.db import build_engine, build_session_factory, init_db
    from src.storage.orm_models_users import UserORM
    from src.storage.orm_models_extra import LigneBudgetORM, FeuilleDeRouteORM, LivrableORM
    from src.storage.orm_models_audit import AuditLogORM
    from api.auth import hash_password
except ImportError as exc:
    print(f"[seed_demo_data] Import error: {exc}")
    print("  Activate the venv first: source .venv/bin/activate")
    sys.exit(1)

DB_URL = "sqlite:///./data/invoices.db"

# ─── helpers ─────────────────────────────────────────────────────────────────

def _d(y: int, m: int, day: int) -> date:
    return date(y, m, day)

def _utc(y: int, m: int, day: int, h: int = 9, mn: int = 0) -> datetime:
    return datetime(y, m, day, h, mn, 0, tzinfo=timezone.utc)


# ─── 1. USERS ────────────────────────────────────────────────────────────────

DEMO_USERS = [
    dict(nom="Admin", prenom="Système",
         email="admin@biat-it.com.tn", password="biat2026!",
         role="Admin", departement="Département DSI"),
    dict(nom="Ben Ali", prenom="Sonia",
         email="comptable@biat-it.com.tn", password="biat2026!",
         role="Comptable", departement="Département Comptabilité"),
    dict(nom="Trabelsi", prenom="Karim",
         email="chef.projet@biat-it.com.tn", password="biat2026!",
         role="Chef de Projet", departement="Département IT"),
    dict(nom="Mansour", prenom="Leila",
         email="direction@biat-it.com.tn", password="biat2026!",
         role="Direction", departement="Direction Générale"),
]


def seed_users(session) -> list[str]:
    """Insert demo users. Returns list of created emails."""
    created = []
    for spec in DEMO_USERS:
        existing = session.execute(
            select(UserORM).where(UserORM.email == spec["email"])
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(UserORM(
            nom=spec["nom"], prenom=spec["prenom"],
            email=spec["email"],
            hashed_password=hash_password(spec["password"]),
            role=spec["role"],
            departement=spec["departement"],
            is_first_login=False,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        ))
        created.append(spec["email"])
    session.flush()
    return created


# ─── 2. LIVRABLES ────────────────────────────────────────────────────────────
#
# Each phase gets 2–3 livrables.  We use the phase_id as a unique prefix so
# re-runs are idempotent (we skip a phase if it already has livrables).

LIVRABLES_DATA = [
    # PRJ-CBK — Phase 1: Analyse (closed)
    dict(phase_id="PH-CBK-001",
         livrables=[
             dict(titre="Cahier des charges fonctionnel", description="Exigences fonctionnelles validées",
                  date_prevue=_d(2026,3,15), date_reelle=_d(2026,3,20), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Matrice des exigences", description="Traçabilité besoins / tests",
                  date_prevue=_d(2026,3,31), date_reelle=_d(2026,3,31), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-CBK — Phase 2: Architecture (closed)
    dict(phase_id="PH-CBK-002",
         livrables=[
             dict(titre="Dossier d'architecture technique", description="Architecture cible et ADR",
                  date_prevue=_d(2026,5,1), date_reelle=_d(2026,5,5), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="POC validé", description="Prototype fonctionnel validé",
                  date_prevue=_d(2026,5,15), date_reelle=_d(2026,5,15), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Plan de migration détaillé", description="Roadmap technique phase 3",
                  date_prevue=_d(2026,5,15), date_reelle=_d(2026,5,14), statut="LIVRE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-CBK — Phase 3: Développement (open)
    dict(phase_id="PH-CBK-003",
         livrables=[
             dict(titre="Modules backend développés", description="Services API REST — v1",
                  date_prevue=_d(2026,9,30), date_reelle=None, statut="EN_COURS",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Tests d'intégration", description="Suite de tests E2E",
                  date_prevue=_d(2026,11,30), date_reelle=None, statut="EN_ATTENTE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-IC — Phase 1: Audit (closed)
    dict(phase_id="PH-IC-001",
         livrables=[
             dict(titre="Rapport d'audit infrastructure", description="Inventaire complet et gaps identifiés",
                  date_prevue=_d(2026,3,1), date_reelle=_d(2026,3,5), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Cartographie SI", description="Schéma réseau et dépendances applicatives",
                  date_prevue=_d(2026,3,15), date_reelle=_d(2026,3,15), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-IC — Phase 2: POC (closed)
    dict(phase_id="PH-IC-002",
         livrables=[
             dict(titre="Environnement POC cloud hybride", description="3 serveurs migrés sur cloud privé",
                  date_prevue=_d(2026,5,15), date_reelle=_d(2026,5,20), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Rapport de validation POC", description="Tests de performance et sécurité",
                  date_prevue=_d(2026,5,30), date_reelle=_d(2026,5,30), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-IC — Phase 3: Déploiement (open)
    dict(phase_id="PH-IC-003",
         livrables=[
             dict(titre="Infrastructure cloud déployée", description="Migration complète 12 serveurs",
                  date_prevue=_d(2026,8,31), date_reelle=None, statut="EN_COURS",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Documentation opérationnelle", description="Runbooks et guides exploitation",
                  date_prevue=_d(2026,9,30), date_reelle=None, statut="EN_ATTENTE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-PCD — Phase 1: UX/UI (closed)
    dict(phase_id="PH-PCD-001",
         livrables=[
             dict(titre="Maquettes Figma validées", description="50 écrans, 3 itérations utilisateurs",
                  date_prevue=_d(2026,4,20), date_reelle=_d(2026,4,20), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-PCD — Phase 2: Développement (closed)
    dict(phase_id="PH-PCD-002",
         livrables=[
             dict(titre="Application web React", description="Frontend portail clients — prod ready",
                  date_prevue=_d(2026,6,10), date_reelle=_d(2026,6,16), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Tests E2E Playwright", description="120 scénarios, couverture 85 %",
                  date_prevue=_d(2026,6,16), date_reelle=_d(2026,6,16), statut="VALIDE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
    # PRJ-PCD — Phase 3: Recette (open)
    dict(phase_id="PH-PCD-003",
         livrables=[
             dict(titre="PV de recette client", description="Validation finale BIAT Retail",
                  date_prevue=_d(2026,10,31), date_reelle=None, statut="EN_ATTENTE",
                  created_by="chef.projet@biat-it.com.tn"),
             dict(titre="Mise en production", description="Déploiement infra prod + monitoring",
                  date_prevue=_d(2026,11,30), date_reelle=None, statut="EN_ATTENTE",
                  created_by="chef.projet@biat-it.com.tn"),
         ]),
]


def seed_livrables(session) -> int:
    """Insert livrables for phases that have none yet."""
    count = 0
    for phase_spec in LIVRABLES_DATA:
        phase_id = phase_spec["phase_id"]
        existing = session.execute(
            select(LivrableORM).where(LivrableORM.phase_id == phase_id)
        ).scalars().all()
        if existing:
            continue
        for lv in phase_spec["livrables"]:
            session.add(LivrableORM(
                phase_id=phase_id,
                titre=lv["titre"],
                description=lv["description"],
                date_livraison_prevue=lv["date_prevue"],
                date_livraison_reelle=lv["date_reelle"],
                statut=lv["statut"],
                created_by=lv["created_by"],
            ))
            count += 1
    session.flush()
    return count


# ─── 3. LIGNES BUDGET ────────────────────────────────────────────────────────

BUDGET_LINES = [
    # PRJ-CBK
    dict(projet_id="PRJ-CBK", categorie="Ressources Humaines",
         montant_prevu=60000.0, montant_consomme=45000.0),
    dict(projet_id="PRJ-CBK", categorie="Infrastructure",
         montant_prevu=30000.0, montant_consomme=28500.0),
    dict(projet_id="PRJ-CBK", categorie="Licences logicielles",
         montant_prevu=6000.0, montant_consomme=0.0),
    # PRJ-IC
    dict(projet_id="PRJ-IC", categorie="Ressources Humaines",
         montant_prevu=40000.0, montant_consomme=25000.0),
    dict(projet_id="PRJ-IC", categorie="Infrastructure Cloud",
         montant_prevu=20000.0, montant_consomme=15000.0),
    dict(projet_id="PRJ-IC", categorie="Formation et accompagnement",
         montant_prevu=5000.0, montant_consomme=0.0),
    # PRJ-PCD
    dict(projet_id="PRJ-PCD", categorie="Ressources Humaines",
         montant_prevu=50000.0, montant_consomme=35000.0),
    dict(projet_id="PRJ-PCD", categorie="UX/Design",
         montant_prevu=10000.0, montant_consomme=8000.0),
    dict(projet_id="PRJ-PCD", categorie="Tests et recette",
         montant_prevu=8000.0, montant_consomme=0.0),
]


def seed_lignes_budget(session) -> int:
    """Insert budget lines for projects that have none yet."""
    count = 0
    for spec in BUDGET_LINES:
        existing = session.execute(
            select(LigneBudgetORM).where(
                LigneBudgetORM.projet_id == spec["projet_id"],
                LigneBudgetORM.categorie == spec["categorie"],
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(LigneBudgetORM(
            projet_id=spec["projet_id"],
            categorie=spec["categorie"],
            montant_prevu=spec["montant_prevu"],
            montant_consomme=spec["montant_consomme"],
            devise="TND",
            created_at=datetime.now(timezone.utc),
        ))
        count += 1
    session.flush()
    return count


# ─── 4. FEUILLE DE ROUTE 2026 ────────────────────────────────────────────────

ROADMAP_ITEMS = [
    dict(titre="Audit infrastructure existante",
         description="Inventaire complet et cartographie des actifs IT du siège BIAT",
         date_debut=_d(2026,1,5), date_fin=_d(2026,3,15),
         projet_id="PRJ-IC", statut="TERMINE", priorite="HAUTE", annee=2026),
    dict(titre="Déploiement Alembic migrations",
         description="Mise en place du versioning de schéma de base de données avec Alembic",
         date_debut=_d(2026,1,10), date_fin=_d(2026,1,31),
         projet_id=None, statut="TERMINE", priorite="MOYENNE", annee=2026),
    dict(titre="Migration Cloud Privé Phase 1",
         description="POC cloud hybride : migration pilote 3 serveurs critiques",
         date_debut=_d(2026,4,1), date_fin=_d(2026,5,30),
         projet_id="PRJ-IC", statut="TERMINE", priorite="HAUTE", annee=2026),
    dict(titre="Portail Clients — Design UX",
         description="Wireframes, maquettes Figma et tests utilisateurs (5 sessions)",
         date_debut=_d(2026,3,1), date_fin=_d(2026,4,20),
         projet_id="PRJ-PCD", statut="TERMINE", priorite="MOYENNE", annee=2026),
    dict(titre="Migration Cloud Privé Phase 2",
         description="Déploiement production complet — migration des 12 serveurs restants",
         date_debut=_d(2026,7,1), date_fin=_d(2026,9,30),
         projet_id="PRJ-IC", statut="PLANIFIE", priorite="HAUTE", annee=2026),
    dict(titre="Bilan annuel et roadmap 2027",
         description="Rétrospective 2026 et planification stratégique IT 2027",
         date_debut=_d(2026,11,15), date_fin=_d(2026,12,31),
         projet_id=None, statut="PLANIFIE", priorite="BASSE", annee=2026),
]


def seed_roadmap(session) -> int:
    """Insert roadmap items (skip if titre already exists for the same year)."""
    count = 0
    for spec in ROADMAP_ITEMS:
        existing = session.execute(
            select(FeuilleDeRouteORM).where(
                FeuilleDeRouteORM.titre == spec["titre"],
                FeuilleDeRouteORM.annee == spec["annee"],
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(FeuilleDeRouteORM(
            titre=spec["titre"],
            description=spec["description"],
            date_debut=spec["date_debut"],
            date_fin=spec["date_fin"],
            projet_id=spec["projet_id"],
            responsable_id=None,
            statut=spec["statut"],
            priorite=spec["priorite"],
            annee=spec["annee"],
        ))
        count += 1
    session.flush()
    return count


# ─── 5. AUDIT LOGS ───────────────────────────────────────────────────────────

def seed_audit_logs(session) -> int:
    """Insert audit log entries if the table is empty."""
    existing_count = session.execute(
        select(AuditLogORM)
    ).scalars().first()
    if existing_count:
        return 0

    # Fetch a couple of invoice IDs for reference
    from src.storage.orm_models import InvoiceORM
    from src.accounting.journal_store import JournalEntryORM
    from src.capex.asset_repository import AssetORM

    invoice_ids = session.execute(
        select(InvoiceORM.id).limit(5)
    ).scalars().all()
    journal_ids = session.execute(
        select(JournalEntryORM.id).limit(2)
    ).scalars().all()
    asset_ids = session.execute(
        select(AssetORM.id).limit(1)
    ).scalars().all()

    inv_strs  = [str(i) for i in invoice_ids]
    jnl_strs  = [str(j) for j in journal_ids]
    asset_strs = [str(a) for a in asset_ids]

    logs = [
        # LOGIN events
        dict(action="LOGIN", actor="admin@biat-it.com.tn", entity_id=None,
             detail="Connexion réussie — IP 10.0.0.12",
             created_at=_utc(2026,1,15,8,32)),
        dict(action="LOGIN", actor="comptable@biat-it.com.tn", entity_id=None,
             detail="Connexion réussie — IP 10.0.0.25",
             created_at=_utc(2026,2,5,9,10)),
        dict(action="LOGIN", actor="chef.projet@biat-it.com.tn", entity_id=None,
             detail="Connexion réussie — IP 10.0.0.31",
             created_at=_utc(2026,3,1,8,45)),
        dict(action="LOGIN", actor="direction@biat-it.com.tn", entity_id=None,
             detail="Connexion réussie — IP 10.0.0.5",
             created_at=_utc(2026,4,10,14,20)),
        dict(action="LOGIN", actor="comptable@biat-it.com.tn", entity_id=None,
             detail="Connexion réussie — IP 10.0.0.25",
             created_at=_utc(2026,6,1,9,0)),

        # CREATE InvoiceRecord
        dict(action="CREATE_INVOICE", actor="agent", entity_id=inv_strs[0] if inv_strs else None,
             detail="Facture FAC-2026-01-OOREDOO reçue et créée",
             created_at=_utc(2026,1,14,10,5)),
        dict(action="CREATE_INVOICE", actor="agent", entity_id=inv_strs[1] if len(inv_strs)>1 else None,
             detail="Facture FAC-2026-02-STEG reçue et créée",
             created_at=_utc(2026,2,4,10,12)),
        dict(action="CREATE_INVOICE", actor="agent", entity_id=inv_strs[2] if len(inv_strs)>2 else None,
             detail="Facture FAC-2026-03-NEXIA reçue et créée",
             created_at=_utc(2026,2,19,10,8)),

        # APPROVE invoice
        dict(action="APPROVE_INVOICE", actor="comptable@biat-it.com.tn",
             entity_id=inv_strs[0] if inv_strs else None,
             detail="Facture FAC-2026-01-OOREDOO approuvée — validation manuelle",
             created_at=_utc(2026,1,16,11,30)),
        dict(action="APPROVE_INVOICE", actor="comptable@biat-it.com.tn",
             entity_id=inv_strs[1] if len(inv_strs)>1 else None,
             detail="Facture FAC-2026-02-STEG approuvée — validation manuelle",
             created_at=_utc(2026,2,6,14,15)),

        # REJECT invoice
        dict(action="REJECT_INVOICE", actor="comptable@biat-it.com.tn",
             entity_id=inv_strs[-1] if inv_strs else None,
             detail="Rejetée : document illisible, OCR confidence < 40 %",
             created_at=_utc(2026,5,30,16,0)),

        # CREATE JournalEntry
        dict(action="CREATE_JOURNAL_ENTRY", actor="agent",
             entity_id=jnl_strs[0] if jnl_strs else None,
             detail="Écriture FAC-2026-01-OOREDOO — compte 6261 / 401",
             created_at=_utc(2026,1,16,11,35)),
        dict(action="CREATE_JOURNAL_ENTRY", actor="agent",
             entity_id=jnl_strs[1] if len(jnl_strs)>1 else None,
             detail="Écriture FAC-2026-02-STEG — compte 6241 / 401",
             created_at=_utc(2026,2,6,14,20)),

        # CREATE Asset
        dict(action="CREATE_ASSET", actor="comptable@biat-it.com.tn",
             entity_id=asset_strs[0] if asset_strs else None,
             detail="Immobilisation créée : Serveurs Dell PowerEdge R750 (lot 3) — 85 000 TND",
             created_at=_utc(2026,1,20,10,0)),

        # CREATE User (by admin)
        dict(action="CREATE_USER", actor="admin@biat-it.com.tn",
             entity_id=None,
             detail="Compte créé : chef.projet@biat-it.com.tn / Chef de Projet",
             created_at=_utc(2026,1,5,9,0)),
    ]

    for spec in logs:
        session.add(AuditLogORM(
            action=spec["action"],
            actor=spec["actor"],
            entity_id=spec["entity_id"],
            detail=spec["detail"],
            created_at=spec["created_at"],
        ))
    session.flush()
    return len(logs)


# ─── VALIDATION ──────────────────────────────────────────────────────────────

def validate_after_seed(session) -> dict:
    """Run post-seed integrity checks. Returns a dict of results."""
    from sqlalchemy import text

    results = {}

    # Journal balance
    unbalanced = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT je.id
            FROM journal_entries je
            LEFT JOIN journal_lines jl ON jl.entry_id = je.id
            GROUP BY je.id
            HAVING ABS(COALESCE(SUM(jl.debit),0) - COALESCE(SUM(jl.credit),0)) > 0.005
        )
    """)).scalar_one()
    results["journal_all_balanced"] = (unbalanced == 0)

    # Asset useful_life > 0
    bad_assets = session.execute(text(
        "SELECT COUNT(*) FROM assets WHERE useful_life_years <= 0"
    )).scalar_one()
    results["assets_valid_life"] = (bad_assets == 0)

    # Invoice math
    bad_inv = session.execute(text("""
        SELECT COUNT(*) FROM invoices
        WHERE amount_ttc IS NOT NULL AND amount_ht IS NOT NULL AND tva_amount IS NOT NULL
        AND ABS(amount_ttc - (amount_ht + tva_amount)) > 0.001
    """)).scalar_one()
    results["invoices_math_valid"] = (bad_inv == 0)

    # LigneBudget non-negative
    neg_budget = session.execute(text(
        "SELECT COUNT(*) FROM lignes_budget WHERE montant_prevu < 0"
    )).scalar_one()
    results["budget_non_negative"] = (neg_budget == 0)

    # FK orphan checks
    orphan_journal = session.execute(text("""
        SELECT COUNT(*) FROM journal_entries
        WHERE source_invoice_id IS NOT NULL
        AND source_invoice_id NOT IN (SELECT id FROM invoices)
    """)).scalar_one()
    results["no_orphan_journal_entries"] = (orphan_journal == 0)

    orphan_livrables = session.execute(text("""
        SELECT COUNT(*) FROM livrables
        WHERE phase_id NOT IN (SELECT id FROM phases)
    """)).scalar_one()
    results["no_orphan_livrables"] = (orphan_livrables == 0)

    return results


# ─── SUMMARY ─────────────────────────────────────────────────────────────────

def print_summary(session) -> None:
    from sqlalchemy import text

    w = 56
    print("\n" + "═" * w)
    print("  DEMO DATA AUDIT — POST-SEED SUMMARY")
    print("═" * w)

    tables = [
        "users", "invoices", "journal_entries", "assets",
        "client_invoices", "chartes_projet", "phases",
        "livrables", "lignes_budget", "feuilles_de_route", "audit_logs",
    ]
    for tbl in tables:
        n = session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar_one()
        print(f"  {tbl:<25} {n:>4}")

    # Invoice statuses
    print("\n  Invoice statuses:")
    rows = session.execute(text(
        "SELECT status, COUNT(*) FROM invoices GROUP BY status ORDER BY status"
    )).fetchall()
    for status, cnt in rows:
        print(f"    {status:<22} {cnt:>3}")

    # Journal balance
    unbalanced = session.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT je.id FROM journal_entries je
            LEFT JOIN journal_lines jl ON jl.entry_id = je.id
            GROUP BY je.id
            HAVING ABS(COALESCE(SUM(jl.debit),0) - COALESCE(SUM(jl.credit),0)) > 0.005
        )
    """)).scalar_one()
    balanced = session.execute(text("SELECT COUNT(*) FROM journal_entries")).scalar_one()
    print(f"\n  Journal entries: {balanced} total, {balanced - unbalanced} balanced, {unbalanced} unbalanced")

    # Asset checks
    n_assets = session.execute(text("SELECT COUNT(*) FROM assets")).scalar_one()
    total_val = session.execute(text("SELECT SUM(acquisition_cost_ht) FROM assets")).scalar_one() or 0
    print(f"  Assets: {n_assets}, gross value: {total_val:,.3f} TND")

    print("\n" + "═" * w)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 56)
    print("  BIAT IT — Demo Data Seeder (Complement)")
    print("=" * 56)

    db_path = ROOT / "data" / "invoices.db"
    if not db_path.exists():
        print(f"\n  ERROR: {db_path} does not exist.")
        print("  Run seed_demo.py first: python scripts/seed_demo.py")
        sys.exit(1)

    engine  = build_engine(DB_URL)
    init_db(engine)
    sf      = build_session_factory(engine)
    session = sf()

    try:
        print("\n[1/5] Users…")
        created_users = seed_users(session)
        if created_users:
            print(f"  Created: {', '.join(created_users)}")
        else:
            print("  All users already exist — skipped")

        print("\n[2/5] Livrables…")
        n_liv = seed_livrables(session)
        print(f"  {n_liv} livrables created" if n_liv else "  Already seeded — skipped")

        print("\n[3/5] Lignes budget…")
        n_budget = seed_lignes_budget(session)
        print(f"  {n_budget} budget lines created" if n_budget else "  Already seeded — skipped")

        print("\n[4/5] Feuille de route 2026…")
        n_road = seed_roadmap(session)
        print(f"  {n_road} roadmap items created" if n_road else "  Already seeded — skipped")

        print("\n[5/5] Audit logs…")
        n_audit = seed_audit_logs(session)
        print(f"  {n_audit} audit log entries created" if n_audit else "  Already seeded — skipped")

        session.commit()
        print("\n  ✅ Commit successful")

        print("\n[Validation] Running integrity checks…")
        checks = validate_after_seed(session)
        all_ok = True
        for check, passed in checks.items():
            icon = "✅" if passed else "❌"
            print(f"  {icon} {check}")
            if not passed:
                all_ok = False
        if all_ok:
            print("\n  All integrity checks passed.")
        else:
            print("\n  ⚠ Some checks failed — review above.")

        print_summary(session)

    except Exception as exc:
        session.rollback()
        print(f"\n  ❌ Error: {exc}")
        raise
    finally:
        session.close()

    print(f"\n  Database: {db_path}")
    print("  API     : python scripts/run_api.py")
    print()


if __name__ == "__main__":
    main()
