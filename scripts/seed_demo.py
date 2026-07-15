#!/usr/bin/env python3
"""BIAT IT — Demo database seeder (unified, MongoDB).

Usage (from project root, MONGODB_URI/MONGODB_DB set in .env):
    python scripts/seed_demo.py            # idempotent — safe to re-run
    python scripts/seed_demo.py --append   # same effect (see --help)
    python scripts/seed_demo.py --dry-run  # validate imports without writing

Every write is upsert-by-id or skip-if-exists — this seeds the SAME MongoDB
the app reads from (not a disposable demo-only file, unlike the old SQLite
version), so re-running never wipes existing data.

Populates (in order — matches the numbered [n/9] steps printed at runtime):
  1. 24 supplier invoices spanning all statuses + all cost catalogue entries
  2.  9 double-entry journal entries (matched to JOURNALED invoices)
  3. 30 monthly depreciation entries (5 assets × Jan–Jun 2026) + 5 CAPEX assets
  4.  3 projects + 9 phases
  5.  3 outgoing client invoices (PAID / SENT / DRAFT)
  6. Budget plan updated to match seeded amounts
  7. Livrables for all 9 phases
  8. Budget lines for all 3 projects
  9. Feuille de route 2026 (6 items)

Does NOT create user accounts — this script used to also seed 4 demo
accounts (@biat-it.com.tn, hardcoded password), removed along with the
rest of the demo-account mechanism. Provisioning the first real Admin
account is a separate, currently unsolved problem (no script or endpoint
exists for it yet).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# ── Early import check ────────────────────────────────────────────────────────
try:
    # api.auth must be imported first — it's what loads .env (MONGODB_URI
    # included) before src.storage.mongodb reads it as a module-level
    # constant. Importing mongodb.py first would freeze MONGODB_URI at "".
    import api.auth  # noqa: F401
    from src.storage.mongodb import close_mongodb, init_beanie
    from src.storage.sync_mongo_repository import (
        SyncMongoAssetRepository, SyncMongoClientInvoiceRepository,
        SyncMongoInvoiceRepository, SyncMongoJournalRepository,
        phase_has_livrables_sync, save_charte_projet_sync,
        save_feuille_de_route_sync, save_ligne_budget_sync, save_livrable_sync,
        save_phase_sync,
    )
    from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
    from src.models.asset import Asset
    from src.models.journal import JournalEntry, JournalLine
    from src.models.client_invoice import ClientInvoice, ClientInvoiceStatus, ClientLineItem
    from src.models.enums import (
        ChargeNature, ChargeType, ExtractionMethod,
        FlagSeverity, FlagType, InvoiceDirection, InvoiceStatus,
    )
except ImportError as exc:
    print(f"[seed] Import error: {exc}")
    print("  Make sure you activated the venv: source .venv/bin/activate")
    sys.exit(1)

SEED_KEY = "biat-demo-2026-v2"


# ── Helpers ───────────────────────────────────────────────────────────────────

def fh(inv_num: str) -> str:
    return hashlib.sha256(f"{SEED_KEY}:{inv_num}".encode()).hexdigest()

def cf(value, conf: float = 0.95) -> ConfidenceField:
    return ConfidenceField(value=value, confidence=conf)

def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)

def utc(dt: date | None = None, hour: int = 10, *, y: int = 0, m: int = 0, day: int = 0, mn: int = 0) -> datetime:
    if dt is not None:
        return datetime(dt.year, dt.month, dt.day, hour, 0, 0, tzinfo=timezone.utc)
    return datetime(y, m, day, hour, mn, 0, tzinfo=timezone.utc)

def r3(x: float) -> float:
    return round(x, 3)

def last_day(y: int, m: int) -> date:
    nxt = date(y, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)
    return nxt - timedelta(days=1)


# ── Invoice factory ───────────────────────────────────────────────────────────

def make_supplier(
    *,
    num: str, inv_date: date, due: date,
    issuer: str, mf: str,
    ht: float, tva: float,
    catalog_id: str | None, compte: str | None, label: str | None,
    nature: ChargeNature | None, typ: ChargeType | None,
    status: InvoiceStatus, desc: str,
    flags: list[ValidationFlag] | None = None,
    paid_at_: datetime | None = None,
    error: str | None = None,
) -> InvoiceRecord:
    tva_amt = r3(ht * tva / 100)
    ttc     = r3(ht + tva_amt)
    rcvd    = utc(inv_date - timedelta(days=1))

    inv = InvoiceRecord(
        file_hash=fh(num),
        raw_file_path=f"/demo/{num}.pdf",
        direction=InvoiceDirection.SUPPLIER,
        status=status,
        extraction_method=ExtractionMethod.NATIVE_PDF_LLM,
        issuer_name=cf(issuer), issuer_tax_id=cf(mf),
        recipient_name=cf("BIAT IT"), recipient_tax_id=cf("0000217V/A/M/000"),
        invoice_number=cf(num),
        invoice_date=cf(inv_date), due_date=cf(due),
        amount_ht=cf(ht), tva_rate=cf(tva),
        tva_amount=cf(tva_amt), amount_ttc=cf(ttc),
        currency="TND",
        cost_catalog_id=catalog_id, accounting_compte=compte,
        accounting_label=label, charge_nature=nature, charge_type=typ,
        line_items=[LineItem(
            line_number=1, description=desc,
            quantity=1.0, unit_price=ht, line_total=ht, tva_rate=tva,
        )],
        last_error=error,
        received_at=rcvd,
    )

    TERMINAL = {
        InvoiceStatus.EXTRACTED, InvoiceStatus.CLASSIFIED,
        InvoiceStatus.VALIDATED, InvoiceStatus.FLAGGED,
        InvoiceStatus.EXPORTED,  InvoiceStatus.JOURNALED,
        InvoiceStatus.PAID,
    }
    if status in TERMINAL:
        inv.extracted_at  = utc(inv_date)
    if status in (TERMINAL - {InvoiceStatus.EXTRACTED}):
        inv.classified_at = utc(inv_date, 11)
    if status in {InvoiceStatus.VALIDATED, InvoiceStatus.FLAGGED,
                  InvoiceStatus.EXPORTED,  InvoiceStatus.JOURNALED, InvoiceStatus.PAID}:
        inv.validated_at  = utc(inv_date, 12)
    if status in {InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED, InvoiceStatus.PAID}:
        inv.exported_at   = utc(inv_date + timedelta(days=1))
        inv.export_reference = f"EXP-{num}"
    if status == InvoiceStatus.PAID and paid_at_:
        inv.paid_at = paid_at_

    if flags:
        for f_ in flags:
            inv.add_flag(f_)
    elif status == InvoiceStatus.FLAGGED:
        inv.human_review_required = True

    return inv


def make_journal(inv: InvoiceRecord, compte_charge: str) -> JournalEntry:
    ht  = inv.amount_ht.value
    tva = inv.tva_amount.value
    ttc = inv.amount_ttc.value
    num = inv.invoice_number.value
    lib = f"Facture {inv.issuer_name.value} — {num}"
    lines = [
        JournalLine(compte=compte_charge, libelle=lib, debit=ht),
    ]
    if tva and tva > 0:
        lines.append(JournalLine(compte="4366", libelle=f"TVA déductible {num}", debit=tva))
    lines.append(JournalLine(compte="401", libelle=f"Fournisseur {inv.issuer_name.value}", credit=ttc or ht))
    return JournalEntry(
        reference=num,
        date_ecriture=inv.invoice_date.value,
        description=lib,
        source_invoice_id=inv.id,
        lines=lines,
    )


# ── Section 1 — Supplier invoices ─────────────────────────────────────────────

OPEX  = ChargeType.OPEX
CAPEX_T = ChargeType.CAPEX
FIXE  = ChargeNature.FIXE
VAR   = ChargeNature.VARIABLE
SEMI  = ChargeNature.SEMI_VARIABLE
JRN   = InvoiceStatus.JOURNALED
EXP   = InvoiceStatus.EXPORTED
VAL   = InvoiceStatus.VALIDATED
FLG   = InvoiceStatus.FLAGGED
ERR   = InvoiceStatus.ERROR
PAI   = InvoiceStatus.PAID
RCV   = InvoiceStatus.RECEIVED


SUPPLIER_SPECS = [
    # ── 9 JOURNALED — core OPEX ───────────────────────────────────────────────
    dict(num="FAC-2026-01-OOREDOO",  inv_date=d(2026,1,15), due=d(2026,2,14),
         issuer="OOREDOO TUNISIE SA",     mf="0038472K/A/M/000",
         ht=3750, tva=19, catalog_id="telecommunications", compte="6261",
         label="Frais de télécommunications", nature=SEMI, typ=OPEX, status=JRN,
         desc="Abonnement fibre 1 Gbps + lignes mobiles x20 — Janvier 2026"),
    dict(num="FAC-2026-02-STEG",     inv_date=d(2026,2,5),  due=d(2026,3,7),
         issuer="STEG",                   mf="0000045A/P/M/000",
         ht=2400, tva=19, catalog_id="electricite_steg", compte="6241",
         label="Électricité (STEG)", nature=SEMI, typ=OPEX, status=JRN,
         desc="Consommation Data Center + Bureaux Siège — Février 2026"),
    dict(num="FAC-2026-03-NEXIA",    inv_date=d(2026,2,20), due=d(2026,3,22),
         issuer="NEXIA INFORMATIQUE SARL", mf="1472583D/A/M/000",
         ht=4500, tva=19, catalog_id="maintenance_informatique", compte="6112",
         label="Maintenance et support informatique", nature=FIXE, typ=OPEX, status=JRN,
         desc="Contrat TMA serveurs et postes de travail — T1 2026"),
    dict(num="FAC-2026-04-SECURITAS", inv_date=d(2026,3,1), due=d(2026,3,31),
         issuer="SECURITAS TUNISIE",      mf="0887632B/A/M/000",
         ht=5200, tva=19, catalog_id="gardiennage_securite", compte="6281",
         label="Gardiennage et sécurité", nature=FIXE, typ=OPEX, status=JRN,
         desc="Gardiennage immeuble siège BIAT IT — Mars 2026"),
    dict(num="FAC-2026-05-TOPNET",   inv_date=d(2026,3,15), due=d(2026,4,14),
         issuer="TOPNET",                 mf="0934721C/A/M/000",
         ht=1800, tva=19, catalog_id="telecommunications", compte="6261",
         label="Frais de télécommunications", nature=SEMI, typ=OPEX, status=JRN,
         desc="Abonnement ADSL Pro 100 Mbps + VPN — Mars 2026"),
    dict(num="FAC-2026-06-GTT",      inv_date=d(2026,2,1),  due=d(2026,3,3),
         issuer="GLOBAL TECH TRAINING",   mf="1256398F/A/M/000",
         ht=6500, tva=0, catalog_id="formation_personnel", compte="6311",
         label="Formation du personnel", nature=VAR, typ=OPEX, status=JRN,
         desc="Formation AWS Practitioner + Cloud Architect (5 j, 8 stagiaires)"),
    dict(num="FAC-2026-07-CIEL",     inv_date=d(2026,3,10), due=d(2026,4,9),
         issuer="CIEL FORMATION SARL",    mf="1398741G/A/M/000",
         ht=4200, tva=0, catalog_id="formation_personnel", compte="6311",
         label="Formation du personnel", nature=VAR, typ=OPEX, status=JRN,
         desc="Formation Cybersécurité ISO 27001 Lead Implementer (3 j, 5 stagiaires)"),
    dict(num="FAC-2026-08-CIEL2",    inv_date=d(2026,4,5),  due=d(2026,5,5),
         issuer="CIEL FORMATION SARL",    mf="1398741G/A/M/000",
         ht=3800, tva=0, catalog_id="formation_personnel", compte="6311",
         label="Formation du personnel", nature=VAR, typ=OPEX, status=JRN,
         desc="Formation DevOps CI/CD Jenkins+Docker (2 j, 6 stagiaires)"),
    dict(num="FAC-2026-09-GTT2",     inv_date=d(2026,5,12), due=d(2026,6,11),
         issuer="GLOBAL TECH TRAINING",   mf="1256398F/A/M/000",
         ht=7500, tva=0, catalog_id="formation_personnel", compte="6311",
         label="Formation du personnel", nature=VAR, typ=OPEX, status=JRN,
         desc="Formation Architecture Data & BI Tableau/PowerBI (5 j, 10 stagiaires)"),

    # ── 3 PAID — full lifecycle complete ──────────────────────────────────────
    dict(num="FAC-2026-P1-SOTETEL",  inv_date=d(2026,1,10), due=d(2026,2,9),
         issuer="SOTETEL",               mf="0345892H/A/M/000",
         ht=8500, tva=19, catalog_id="licences_saas", compte="6133",
         label="Licences logiciels et abonnements SaaS", nature=FIXE, typ=OPEX, status=PAI,
         desc="Sophos XDR Endpoint Security — 50 postes — T1 2026",
         paid_at_=utc(d(2026,2,7))),
    dict(num="FAC-2026-P2-TT",       inv_date=d(2026,2,15), due=d(2026,3,17),
         issuer="TUNISIE TELECOM",        mf="0012456A/P/M/000",
         ht=2200, tva=19, catalog_id="telecommunications", compte="6261",
         label="Frais de télécommunications", nature=SEMI, typ=OPEX, status=PAI,
         desc="Lignes fixes + RNIS data centre — Février 2026",
         paid_at_=utc(d(2026,3,15))),
    dict(num="FAC-2026-P3-PDC",      inv_date=d(2026,3,5),  due=d(2026,4,4),
         issuer="PAPETERIE DU CENTRE",    mf="0876543J/A/M/000",
         ht=650, tva=19, catalog_id="fournitures_bureau", compte="6061",
         label="Fournitures de bureau", nature=VAR, typ=OPEX, status=PAI,
         desc="Ramettes A4 + fournitures T1 2026",
         paid_at_=utc(d(2026,4,2))),

    # ── 3 EXPORTED — pending payment (some overdue) ───────────────────────────
    dict(num="FAC-2026-10-SOTETEL",  inv_date=d(2026,4,1),  due=d(2026,5,1),
         issuer="SOTETEL",               mf="0345892H/A/M/000",
         ht=8500, tva=19, catalog_id="licences_saas", compte="6133",
         label="Licences logiciels et abonnements SaaS", nature=FIXE, typ=OPEX, status=EXP,
         desc="Sophos XDR Endpoint Security renouvellement T2 2026"),
    dict(num="FAC-2026-11-TT",       inv_date=d(2026,4,15), due=d(2026,5,15),
         issuer="TUNISIE TELECOM",        mf="0012456A/P/M/000",
         ht=2200, tva=19, catalog_id="telecommunications", compte="6261",
         label="Frais de télécommunications", nature=SEMI, typ=OPEX, status=EXP,
         desc="Lignes fixes + RNIS data centre — Avril 2026"),
    dict(num="FAC-2026-12-PDC",      inv_date=d(2026,5,3),  due=d(2026,6,2),
         issuer="PAPETERIE DU CENTRE",    mf="0876543J/A/M/000",
         ht=650, tva=19, catalog_id="fournitures_bureau", compte="6061",
         label="Fournitures de bureau", nature=VAR, typ=OPEX, status=EXP,
         desc="Ramettes A4 (50 cartons), classeurs, stylos — T2 2026"),

    # ── 3 VALIDATED — awaiting export ─────────────────────────────────────────
    dict(num="FAC-2026-13-MS",       inv_date=d(2026,5,15), due=d(2026,6,14),
         issuer="MICROSOFT TUNISIE SARL", mf="0764321K/A/M/000",
         ht=18000, tva=19, catalog_id="licences_saas", compte="6133",
         label="Licences logiciels et abonnements SaaS", nature=FIXE, typ=OPEX, status=VAL,
         desc="Microsoft 365 Business Premium 60 utilisateurs 2026-2027"),
    dict(num="FAC-2026-14-KPMG",     inv_date=d(2026,5,20), due=d(2026,6,19),
         issuer="KPMG TUNISIE",           mf="0098765J/A/M/000",
         ht=12000, tva=19, catalog_id="honoraires_conseil", compte="6222",
         label="Honoraires de conseil, audit et expertise", nature=VAR, typ=OPEX, status=VAL,
         desc="Mission audit processus DSI et recommandations COBIT — S1 2026"),
    dict(num="FAC-2026-15-IBM",      inv_date=d(2026,6,1),  due=d(2026,7,1),
         issuer="IBM TUNISIE",            mf="0345678L/A/M/000",
         ht=8500, tva=19, catalog_id="maintenance_informatique", compte="6112",
         label="Maintenance et support informatique", nature=FIXE, typ=OPEX, status=VAL,
         desc="Contrat support Premium IBM AIX servers — Juin 2026"),

    # ── 2 FLAGGED — HIGH_VALUE (CAPEX) ────────────────────────────────────────
    dict(num="FAC-2026-16-DELL",     inv_date=d(2026,3,20), due=d(2026,4,19),
         issuer="DELL TECHNOLOGIES TN",   mf="0567891M/A/M/000",
         ht=62000, tva=19, catalog_id="materiel_informatique", compte="2183",
         label="Matériel informatique", nature=FIXE, typ=CAPEX_T, status=FLG,
         desc="Lot 4 serveurs Dell PowerEdge R760 + baies de stockage PowerVault",
         flags=[ValidationFlag(
             flag_type=FlagType.HIGH_VALUE, severity=FlagSeverity.ERROR,
             message="Montant TTC 73 780 TND dépasse le seuil de revue (50 000 TND)",
         )]),
    dict(num="FAC-2026-17-CISCO",    inv_date=d(2026,4,10), due=d(2026,5,10),
         issuer="CISCO SYSTEMS TUNISIE",  mf="0678912N/A/M/000",
         ht=78000, tva=19, catalog_id="materiel_informatique", compte="2183",
         label="Matériel informatique", nature=FIXE, typ=CAPEX_T, status=FLG,
         desc="Infrastructure réseau Cisco Catalyst 9500 + Firewall Cisco FPR4100",
         flags=[ValidationFlag(
             flag_type=FlagType.HIGH_VALUE, severity=FlagSeverity.ERROR,
             message="Montant TTC 92 820 TND dépasse le seuil de revue (50 000 TND)",
         )]),

    # ── 2 FLAGGED — CATALOG_NO_MATCH ──────────────────────────────────────────
    dict(num="FAC-2026-18-PRINT",    inv_date=d(2026,4,25), due=d(2026,5,25),
         issuer="PRINTWAY TUNISIE SARL",  mf="0789123P/A/M/000",
         ht=850, tva=19, catalog_id=None, compte=None, label=None,
         nature=None, typ=None, status=FLG,
         desc="Impression roll-ups et brochures présentation DSI Q2 2026",
         flags=[ValidationFlag(
             flag_type=FlagType.CATALOG_NO_MATCH, severity=FlagSeverity.WARNING,
             message="Aucune entrée catalogue (score max 48 < seuil 70). "
                     "Catégorie probable : publicite_communication",
         )]),
    dict(num="FAC-2026-19-SEL",      inv_date=d(2026,5,8),  due=d(2026,6,7),
         issuer="SOCIÉTÉ EXPRESS LOGISTIQUE", mf="0891234Q/A/M/000",
         ht=1200, tva=19, catalog_id=None, compte=None, label=None,
         nature=None, typ=None, status=FLG,
         desc="Transport et livraison équipements informatiques sur 3 sites",
         flags=[ValidationFlag(
             flag_type=FlagType.CATALOG_NO_MATCH, severity=FlagSeverity.WARNING,
             message="Aucune entrée catalogue. Catégorie probable : frais_deplacement",
         )]),

    # ── 1 ERROR ───────────────────────────────────────────────────────────────
    dict(num="FAC-2026-20-ERR",      inv_date=d(2026,5,30), due=d(2026,6,29),
         issuer="INCONNU",               mf="0000000X",
         ht=0, tva=0, catalog_id=None, compte=None, label=None,
         nature=None, typ=None, status=ERR,
         desc="Document illisible — tentatives OCR épuisées",
         error="Extraction échouée après 3 tentatives : OCR confidence < 40%"),

    # ── 2 RECEIVED — live pipeline simulation ─────────────────────────────────
    dict(num="FAC-2026-21-OOREDOO",  inv_date=d(2026,6,20), due=d(2026,7,20),
         issuer="OOREDOO TUNISIE SA",     mf="0038472K/A/M/000",
         ht=3750, tva=19, catalog_id=None, compte=None, label=None,
         nature=None, typ=None, status=RCV,
         desc="Abonnement fibre + mobiles Juin 2026 — en attente traitement"),
    dict(num="FAC-2026-22-STEG",     inv_date=d(2026,6,20), due=d(2026,7,20),
         issuer="STEG",                   mf="0000045A/P/M/000",
         ht=2800, tva=19, catalog_id=None, compte=None, label=None,
         nature=None, typ=None, status=RCV,
         desc="Electricité Data Center + Bureaux Juin 2026 — reçue ce jour"),
]

_JOURNAL_STATUSES = {InvoiceStatus.JOURNALED, InvoiceStatus.PAID}


# ── Section 2 — CAPEX assets ──────────────────────────────────────────────────

ASSET_SPECS = [
    dict(designation="Serveurs Dell PowerEdge R750 (lot 3)",
         compte_immobilisation="2183", compte_amortissement="2893",
         acquisition_date=d(2024,1,15), acquisition_cost_ht=85000.0,
         useful_life_years=5, depreciation_method="linear",
         notes="Salle serveurs N-1, remplace lot PowerEdge R640"),
    dict(designation="Licences Microsoft 365 Business (50 postes)",
         compte_immobilisation="2188", compte_amortissement="2898",
         acquisition_date=d(2024,6,1), acquisition_cost_ht=12000.0,
         useful_life_years=3, depreciation_method="degressive",
         notes="Contrat Microsoft EA — renouvellement juin 2027"),
    dict(designation="Switch réseau Cisco Catalyst 9300",
         compte_immobilisation="2183", compte_amortissement="2893",
         acquisition_date=d(2023,9,1), acquisition_cost_ht=28500.0,
         useful_life_years=5, depreciation_method="linear",
         notes="Cœur réseau LAN siège, 48 ports 10G"),
    dict(designation="Onduleurs APC Smart-UPS (lot 5)",
         compte_immobilisation="2183", compte_amortissement="2893",
         acquisition_date=d(2025,3,1), acquisition_cost_ht=15750.0,
         useful_life_years=5, depreciation_method="linear",
         notes="Protection alimentation salle serveurs et postes critiques"),
    dict(designation="Logiciel ERP Sage 100 (licence perpétuelle)",
         compte_immobilisation="2183", compte_amortissement="2893",
         acquisition_date=d(2023,1,1), acquisition_cost_ht=45000.0,
         useful_life_years=5, depreciation_method="degressive",
         notes="ERP comptabilité, RH et gestion commerciale BIAT IT"),
]


# ── Section 3 — Client invoices ───────────────────────────────────────────────

def _make_client_invoices() -> list[ClientInvoice]:
    ISSUER = "BIAT IT"
    ISSUER_MF = "0000217V/A/M/000"
    ISSUER_ADDR = "Zone Urbaine Nord, Les Berges du Lac I, 1053 Tunis"
    CLIENT_ID = "BIAT-GROUP"
    CLIENT_NAME = "BIAT — Banque Internationale Arabe de Tunisie"
    CLIENT_MF = "0000218W/A/M/000"
    CLIENT_ADDR = "70-72 Avenue Habib Bourguiba, 1000 Tunis"

    def li(desc: str, qty: float, price: float, tva: float = 19.0) -> ClientLineItem:
        total = r3(qty * price)
        return ClientLineItem(
            description=desc, quantity=qty, unit_price=price,
            line_total=total, tva_rate=tva, tva_amount=r3(total * tva / 100),
            compte_produit="7061",
        )

    base = dict(
        issuer_name=ISSUER, issuer_tax_id=ISSUER_MF, issuer_address=ISSUER_ADDR,
        client_id=CLIENT_ID, client_name=CLIENT_NAME,
        client_tax_id=CLIENT_MF, client_address=CLIENT_ADDR,
    )

    return [
        ClientInvoice(
            **base,
            invoice_number="FAC-IT-2026-001", invoice_date=d(2026,4,5), due_date=d(2026,5,5),
            line_items=[
                li("PRJ-CBK Phase 1 : Analyse & spécifications — 20 JH × 850 TND", 20, 850),
                li("PRJ-IC Avance Phase 3 — Achat licences cloud", 1, 10000),
            ],
            status=ClientInvoiceStatus.PAID,
            notes="Facturation phases clôturées T1 2026",
            sent_at=utc(d(2026,4,5)), paid_at=utc(d(2026,4,25)),
        ),
        ClientInvoice(
            **base,
            invoice_number="FAC-IT-2026-002", invoice_date=d(2026,5,10), due_date=d(2026,6,9),
            line_items=[
                li("PRJ-PCD Phase 1 : UX/UI design — 15 JH × 850 TND", 15, 850),
                li("PRJ-CBK Phase 2 : Architecture technique — 18 JH × 850 TND", 18, 850),
            ],
            status=ClientInvoiceStatus.SENT,
            notes="Facturation phases clôturées Avril–Mai 2026",
            sent_at=utc(d(2026,5,10)),
        ),
        ClientInvoice(
            **base,
            invoice_number="FAC-IT-2026-003", invoice_date=d(2026,6,16), due_date=d(2026,7,16),
            line_items=[
                li("PRJ-PCD Phase 2 : Développement frontend React — 42 JH × 850 TND", 42, 850),
                li("PRJ-IC Phase 2 : POC Cloud hybride — 28 JH × 850 TND", 28, 850),
            ],
            status=ClientInvoiceStatus.DRAFT,
            notes="Phases clôturées Juin 2026 — Fiche FICHE-2026-06",
        ),
    ]




# ── Section 5 — Livrables ─────────────────────────────────────────────────────

LIVRABLES_DATA = [
    dict(phase_id="PH-CBK-001", livrables=[
        dict(titre="Cahier des charges fonctionnel", description="Exigences fonctionnelles validées",
             date_prevue=d(2026,3,15), date_reelle=d(2026,3,20), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Matrice des exigences", description="Traçabilité besoins / tests",
             date_prevue=d(2026,3,31), date_reelle=d(2026,3,31), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-CBK-002", livrables=[
        dict(titre="Dossier d'architecture technique", description="Architecture cible et ADR",
             date_prevue=d(2026,5,1), date_reelle=d(2026,5,5), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="POC validé", description="Prototype fonctionnel validé",
             date_prevue=d(2026,5,15), date_reelle=d(2026,5,15), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Plan de migration détaillé", description="Roadmap technique phase 3",
             date_prevue=d(2026,5,15), date_reelle=d(2026,5,14), statut="LIVRE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-CBK-003", livrables=[
        dict(titre="Modules backend développés", description="Services API REST — v1",
             date_prevue=d(2026,9,30), date_reelle=None, statut="EN_COURS",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Tests d'intégration", description="Suite de tests E2E",
             date_prevue=d(2026,11,30), date_reelle=None, statut="EN_ATTENTE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-IC-001", livrables=[
        dict(titre="Rapport d'audit infrastructure", description="Inventaire complet et gaps identifiés",
             date_prevue=d(2026,3,1), date_reelle=d(2026,3,5), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Cartographie SI", description="Schéma réseau et dépendances applicatives",
             date_prevue=d(2026,3,15), date_reelle=d(2026,3,15), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-IC-002", livrables=[
        dict(titre="Environnement POC cloud hybride", description="3 serveurs migrés sur cloud privé",
             date_prevue=d(2026,5,15), date_reelle=d(2026,5,20), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Rapport de validation POC", description="Tests de performance et sécurité",
             date_prevue=d(2026,5,30), date_reelle=d(2026,5,30), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-IC-003", livrables=[
        dict(titre="Infrastructure cloud déployée", description="Migration complète 12 serveurs",
             date_prevue=d(2026,8,31), date_reelle=None, statut="EN_COURS",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Documentation opérationnelle", description="Runbooks et guides exploitation",
             date_prevue=d(2026,9,30), date_reelle=None, statut="EN_ATTENTE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-PCD-001", livrables=[
        dict(titre="Maquettes Figma validées", description="50 écrans, 3 itérations utilisateurs",
             date_prevue=d(2026,4,20), date_reelle=d(2026,4,20), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-PCD-002", livrables=[
        dict(titre="Application web React", description="Frontend portail clients — prod ready",
             date_prevue=d(2026,6,10), date_reelle=d(2026,6,16), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Tests E2E Playwright", description="120 scénarios, couverture 85 %",
             date_prevue=d(2026,6,16), date_reelle=d(2026,6,16), statut="VALIDE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
    dict(phase_id="PH-PCD-003", livrables=[
        dict(titre="PV de recette client", description="Validation finale BIAT Retail",
             date_prevue=d(2026,10,31), date_reelle=None, statut="EN_ATTENTE",
             created_by="chef.projet@biat-it.com.tn"),
        dict(titre="Mise en production", description="Déploiement infra prod + monitoring",
             date_prevue=d(2026,11,30), date_reelle=None, statut="EN_ATTENTE",
             created_by="chef.projet@biat-it.com.tn"),
    ]),
]


# ── Section 6 — Budget lines ──────────────────────────────────────────────────

BUDGET_LINES = [
    dict(projet_id="PRJ-CBK", categorie="Ressources Humaines",      montant_prevu=60000.0, montant_consomme=45000.0),
    dict(projet_id="PRJ-CBK", categorie="Infrastructure",           montant_prevu=30000.0, montant_consomme=28500.0),
    dict(projet_id="PRJ-CBK", categorie="Licences logicielles",     montant_prevu=6000.0,  montant_consomme=0.0),
    dict(projet_id="PRJ-IC",  categorie="Ressources Humaines",      montant_prevu=40000.0, montant_consomme=25000.0),
    dict(projet_id="PRJ-IC",  categorie="Infrastructure Cloud",     montant_prevu=20000.0, montant_consomme=15000.0),
    dict(projet_id="PRJ-IC",  categorie="Formation et accompagnement", montant_prevu=5000.0, montant_consomme=0.0),
    dict(projet_id="PRJ-PCD", categorie="Ressources Humaines",      montant_prevu=50000.0, montant_consomme=35000.0),
    dict(projet_id="PRJ-PCD", categorie="UX/Design",                montant_prevu=10000.0, montant_consomme=8000.0),
    dict(projet_id="PRJ-PCD", categorie="Tests et recette",         montant_prevu=8000.0,  montant_consomme=0.0),
]


# ── Section 7 — Roadmap 2026 ──────────────────────────────────────────────────

ROADMAP_ITEMS = [
    dict(titre="Audit infrastructure existante",
         description="Inventaire complet et cartographie des actifs IT du siège BIAT",
         date_debut=d(2026,1,5), date_fin=d(2026,3,15),
         projet_id="PRJ-IC", statut="TERMINE", priorite="HAUTE", annee=2026),
    dict(titre="Déploiement Alembic migrations",
         description="Mise en place du versioning de schéma de base de données avec Alembic",
         date_debut=d(2026,1,10), date_fin=d(2026,1,31),
         projet_id=None, statut="TERMINE", priorite="MOYENNE", annee=2026),
    dict(titre="Migration Cloud Privé Phase 1",
         description="POC cloud hybride : migration pilote 3 serveurs critiques",
         date_debut=d(2026,4,1), date_fin=d(2026,5,30),
         projet_id="PRJ-IC", statut="TERMINE", priorite="HAUTE", annee=2026),
    dict(titre="Portail Clients — Design UX",
         description="Wireframes, maquettes Figma et tests utilisateurs (5 sessions)",
         date_debut=d(2026,3,1), date_fin=d(2026,4,20),
         projet_id="PRJ-PCD", statut="TERMINE", priorite="MOYENNE", annee=2026),
    dict(titre="Migration Cloud Privé Phase 2",
         description="Déploiement production complet — migration des 12 serveurs restants",
         date_debut=d(2026,7,1), date_fin=d(2026,9,30),
         projet_id="PRJ-IC", statut="PLANIFIE", priorite="HAUTE", annee=2026),
    dict(titre="Bilan annuel et roadmap 2027",
         description="Rétrospective 2026 et planification stratégique IT 2027",
         date_debut=d(2026,11,15), date_fin=d(2026,12,31),
         projet_id=None, statut="PLANIFIE", priorite="BASSE", annee=2026),
]


# ── Seeder ────────────────────────────────────────────────────────────────────

def seed() -> None:
    from src.storage.sync_mongo_repository import _get_db

    db = _get_db()
    inv_repo   = SyncMongoInvoiceRepository()
    jnl_repo   = SyncMongoJournalRepository()
    asset_repo = SyncMongoAssetRepository()
    ci_repo    = SyncMongoClientInvoiceRepository()

    def _journal_exists(reference: str) -> bool:
        return db["journal_entries"].find_one({"reference": reference}) is not None

    # ── 1. Supplier invoices + journal entries ────────────────────────────────
    print("\n[1/9] Supplier invoices…")
    journal_queue: list[tuple[InvoiceRecord, str]] = []
    created = skipped = 0

    for spec in SUPPLIER_SPECS:
        num = spec["num"]
        if inv_repo.get_by_hash(fh(num)) is not None:
            skipped += 1
            continue

        inv = make_supplier(**spec)

        if spec["status"] == InvoiceStatus.ERROR:
            inv.issuer_name   = ConfidenceField()
            inv.issuer_tax_id = ConfidenceField()
            inv.amount_ht     = ConfidenceField()
            inv.tva_amount    = ConfidenceField()
            inv.amount_ttc    = ConfidenceField()

        inv_repo.save(inv)
        created += 1

        if spec["status"] in _JOURNAL_STATUSES and spec.get("compte"):
            journal_queue.append((inv, spec["compte"]))

        status_str = spec["status"].value if isinstance(spec["status"], InvoiceStatus) else spec["status"]
        print(f"  {num}  →  {status_str}")

    print(f"  {created} created, {skipped} skipped (already exist)")

    print(f"\n[2/9] Journal entries ({len(journal_queue)})…")
    jnl_created = 0
    for inv, compte in journal_queue:
        entry = make_journal(inv, compte)
        if not _journal_exists(entry.reference):
            jnl_repo.save(entry)
            jnl_created += 1
    print(f"  {jnl_created} created, {len(journal_queue) - jnl_created} skipped (already exist)")

    # ── 3. CAPEX assets + depreciation ───────────────────────────────────────
    print("\n[3/9] CAPEX assets + depreciation (Jan–Jun 2026)…")
    assets: list[Asset] = []
    assets_created = 0
    for spec in ASSET_SPECS:
        asset = Asset(**spec)
        existing = db["assets"].find_one({"designation": asset.designation})
        if existing is None:
            asset_repo.save(asset)
            assets_created += 1
        else:
            asset.id = UUID(existing["_id"])
        assets.append(asset)
        print(f"  {asset.designation}")
    print(f"  {assets_created} created, {len(assets) - assets_created} skipped (already exist)")

    dep_count = dep_skipped = 0
    for asset in assets:
        amort = asset.monthly_depreciation
        for m in range(1, 7):
            ld = last_day(2026, m)
            reference = f"AMORT-{asset.designation[:15].replace(' ','-')}-2026{m:02d}"
            if _journal_exists(reference):
                dep_skipped += 1
                continue
            jnl_repo.save(JournalEntry(
                reference=reference,
                date_ecriture=ld,
                description=f"Dotation amortissement {ld.strftime('%B %Y')} — {asset.designation}",
                source_asset_id=asset.id,
                lines=[
                    JournalLine(compte="6811",
                                libelle=f"Dotation amort. {asset.designation[:40]}",
                                debit=amort),
                    JournalLine(compte=asset.compte_amortissement,
                                libelle=f"Amort. cumulé {asset.designation[:40]}",
                                credit=amort),
                ],
            ))
            dep_count += 1
    print(f"  {dep_count} created, {dep_skipped} skipped (already exist)")

    # ── 4. Projects + phases ──────────────────────────────────────────────────
    print("\n[4/9] Projects + phases…")
    proj_data = [
        dict(id="CHR-2026-0001", project_id="PRJ-CBK", project_name="Migration Core Banking System",
             client="BIAT", valid_from=d(2026,1,5), valid_until=d(2026,12,31),
             budget_jh=120.0, taux_jh=850.0, is_active=True),
        dict(id="CHR-2026-0002", project_id="PRJ-IC", project_name="Infrastructure Cloud Hybride",
             client="BIAT", valid_from=d(2026,2,1), valid_until=d(2026,9,30),
             budget_jh=80.0, taux_jh=850.0, is_active=True),
        dict(id="CHR-2026-0003", project_id="PRJ-PCD", project_name="Portail Client Digital",
             client="BIAT", valid_from=d(2026,3,1), valid_until=d(2026,11,30),
             budget_jh=100.0, taux_jh=850.0, is_active=True),
    ]
    phase_data = [
        dict(id="PH-CBK-001", project_id="PRJ-CBK", name="Analyse & spécifications",
             description="Cadrage fonctionnel, recueil besoins",
             planned_jh=20.0, consumed_jh=20.0, status="closed",
             closed_date=d(2026,3,31), livrables='["Cahier des charges"]'),
        dict(id="PH-CBK-002", project_id="PRJ-CBK", name="Architecture technique",
             description="Conception architecture cible, prototypage",
             planned_jh=18.0, consumed_jh=18.0, status="closed",
             closed_date=d(2026,5,15), livrables='["Dossier d\'architecture"]'),
        dict(id="PH-CBK-003", project_id="PRJ-CBK", name="Développement & tests",
             description="Développement modules, tests unitaires",
             planned_jh=82.0, consumed_jh=24.0, status="open",
             closed_date=None, livrables='[]'),
        dict(id="PH-IC-001", project_id="PRJ-IC", name="Audit infrastructure existante",
             description="Inventaire, audit sécurité",
             planned_jh=15.0, consumed_jh=15.0, status="closed",
             closed_date=d(2026,3,15), livrables='["Rapport d\'audit"]'),
        dict(id="PH-IC-002", project_id="PRJ-IC", name="POC Cloud hybride",
             description="Migration pilote, validation",
             planned_jh=28.0, consumed_jh=28.0, status="closed",
             closed_date=d(2026,5,30), livrables='["Environnement POC"]'),
        dict(id="PH-IC-003", project_id="PRJ-IC", name="Déploiement production",
             description="Migration complète, formation équipes",
             planned_jh=37.0, consumed_jh=8.0, status="open",
             closed_date=None, livrables='[]'),
        dict(id="PH-PCD-001", project_id="PRJ-PCD", name="UX/UI Design",
             description="Wireframes, maquettes Figma",
             planned_jh=15.0, consumed_jh=15.0, status="closed",
             closed_date=d(2026,4,20), livrables='["Maquettes validées"]'),
        dict(id="PH-PCD-002", project_id="PRJ-PCD", name="Développement frontend React",
             description="Implémentation composants, intégration API",
             planned_jh=42.0, consumed_jh=42.0, status="closed",
             closed_date=d(2026,6,16), livrables='["Application web"]'),
        dict(id="PH-PCD-003", project_id="PRJ-PCD", name="Recette & mise en production",
             description="Tests de recette, déploiement production",
             planned_jh=43.0, consumed_jh=0.0, status="open",
             closed_date=None, livrables='[]'),
    ]
    for pd in proj_data:
        save_charte_projet_sync(
            id=pd["id"], project_id=pd["project_id"], project_name=pd["project_name"],
            client=pd["client"], valid_from=pd["valid_from"], valid_until=pd["valid_until"],
            budget_jh=pd["budget_jh"], taux_jh=pd["taux_jh"], is_active=pd["is_active"],
        )
    for phd in phase_data:
        save_phase_sync(
            id=phd["id"], project_id=phd["project_id"], name=phd["name"],
            description=phd["description"], planned_jh=phd["planned_jh"],
            consumed_jh=phd["consumed_jh"], status=phd["status"],
            closed_date=phd["closed_date"], livrables=phd["livrables"],
        )
    print(f"  {len(proj_data)} projects, {len(phase_data)} phases")

    # ── 5. Client invoices ────────────────────────────────────────────────────
    print("\n[5/9] Client invoices…")
    ci_created = ci_skipped = 0
    for ci in _make_client_invoices():
        if db["client_invoices"].find_one({"invoice_number": ci.invoice_number}):
            ci_skipped += 1
            continue
        ci_repo.save(ci)
        ci_created += 1
        print(f"  {ci.invoice_number}  HT={ci.amount_ht:,.3f} TND  [{ci.status.value}]")
    print(f"  {ci_created} created, {ci_skipped} skipped (already exist)")

    # ── 6. Budget plan YAML ───────────────────────────────────────────────────
    print("\n[6/9] Updating budget_plan.yaml…")
    _update_budget_plan()

    # ── 7. Livrables ──────────────────────────────────────────────────────────
    print("\n[7/9] Livrables…")
    n_liv = 0
    for phase_spec in LIVRABLES_DATA:
        phase_id = phase_spec["phase_id"]
        if phase_has_livrables_sync(phase_id):
            continue
        for lv in phase_spec["livrables"]:
            save_livrable_sync(
                phase_id=phase_id, titre=lv["titre"], description=lv["description"],
                date_prevue=lv["date_prevue"], date_reelle=lv["date_reelle"],
                statut=lv["statut"], created_by=lv["created_by"],
            )
            n_liv += 1
    print(f"  {n_liv} livrables created" if n_liv else "  Already seeded — skipped")

    # ── 9. Budget lines ───────────────────────────────────────────────────────
    print("\n[8/9] Budget lines…")
    n_budget = 0
    for spec in BUDGET_LINES:
        created = save_ligne_budget_sync(
            projet_id=spec["projet_id"], categorie=spec["categorie"],
            montant_prevu=spec["montant_prevu"], montant_consomme=spec["montant_consomme"],
        )
        if created:
            n_budget += 1
    print(f"  {n_budget} budget lines created" if n_budget else "  Already seeded — skipped")

    # ── 10. Roadmap 2026 ──────────────────────────────────────────────────────
    print("\n[9/9] Feuille de route 2026…")
    n_road = 0
    for spec in ROADMAP_ITEMS:
        created = save_feuille_de_route_sync(
            titre=spec["titre"], description=spec["description"],
            date_debut=spec["date_debut"], date_fin=spec["date_fin"],
            projet_id=spec["projet_id"], statut=spec["statut"],
            priorite=spec["priorite"], annee=spec["annee"],
        )
        if created:
            n_road += 1
    print(f"  {n_road} roadmap items created" if n_road else "  Already seeded — skipped")


def _update_budget_plan() -> None:
    import yaml
    plan_path = ROOT / "config" / "budget_plan.yaml"
    with open(plan_path) as f:
        plan = yaml.safe_load(f)

    updates = {
        "telecommunications":    {"monthly": [5000]*12},
        "electricite_steg":      {"monthly": [2500,2500,2200,2000,2000,2800,3000,3000,2600,2200,2000,3200]},
        "maintenance_informatique": {"monthly": [7500]*12},
        "gardiennage_securite":  {"monthly": [6000]*12},
        "formation_personnel":   {"monthly": [0,10000,0,15000,12500,7500,0,15000,0,20000,20000,20000]},
        "licences_saas":         {"monthly": [8000,8000,25000,8000,8000,25000,8000,8000,25000,8000,8000,61000]},
        "materiel_informatique": {"monthly": [0,0,50000,0,0,0,0,0,50000,0,50000,0]},
        "honoraires_conseil":    {"monthly": [5000,5000,8000,5000,5000,8000,5000,5000,8000,5000,5000,16000]},
        "fournitures_bureau":    {"monthly": [1250]*12},
    }

    updated = 0
    for entry in plan.get("entries", []):
        cid = entry.get("catalog_id")
        if cid in updates:
            entry["monthly"] = updates[cid]["monthly"]
            updated += 1

    with open(plan_path, "w") as f:
        yaml.dump(plan, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  {updated} catalogue entries updated in {plan_path.name}")


def print_summary() -> None:
    from collections import Counter

    from src.storage.sync_mongo_repository import _get_db

    db = _get_db()
    invoice_docs = list(db["invoices"].find({}))
    journal_docs = list(db["journal_entries"].find({}))
    asset_docs   = list(db["assets"].find({}))
    ci_docs      = list(db["client_invoices"].find({}))

    counts = Counter(i["status"] for i in invoice_docs)
    total  = sum(
        i.get("amount_ttc") or 0 for i in invoice_docs
        if i.get("direction") == InvoiceDirection.SUPPLIER.value
    )

    tables = [
        "users", "invoices", "journal_entries", "assets",
        "client_invoices", "chartes_projet", "phases",
        "livrables", "lignes_budget", "feuilles_de_route", "audit_logs",
    ]

    w = 56
    print("\n" + "═" * w)
    print("  DEMO DATASET — SUMMARY")
    print("═" * w)

    for tbl in tables:
        n = db[tbl].count_documents({})
        print(f"  {tbl:<25} {n:>4}")

    print(f"\n  Invoice statuses:")
    for status, n in sorted(counts.items()):
        print(f"    {status:<22} {n:>3}")
    print(f"  Total TTC fournisseurs : {total:>12,.3f} TND")

    inv_jnl = sum(1 for e in journal_docs if e.get("source_invoice_id"))
    dep_jnl = sum(1 for e in journal_docs if e.get("source_asset_id"))
    print(f"\n  Journal entries   : {len(journal_docs)}")
    print(f"    Invoice         : {inv_jnl}")
    print(f"    Depreciation    : {dep_jnl}")

    gross = sum(a.get("acquisition_cost_ht") or 0 for a in asset_docs)
    billed = sum(c.get("amount_ht") or 0 for c in ci_docs)
    print(f"\n  CAPEX assets      : {len(asset_docs)}")
    print(f"  Gross value       : {gross:>12,.3f} TND")
    print(f"\n  Client invoices   : {len(ci_docs)}")
    print(f"  Total billed HT   : {billed:>12,.3f} TND")

    today = _to_midnight_utc_local(date.today())
    overdue_count = sum(
        1 for i in invoice_docs
        if i.get("status") == InvoiceStatus.EXPORTED.value
        and i.get("due_date") and i["due_date"] < today
        and not i.get("paid_at")
    )
    print(f"\n  Overdue invoices  : {overdue_count}")
    print("\n" + "═" * w)


def _to_midnight_utc_local(d: date) -> datetime:
    # pymongo decodes BSON dates as naive UTC by default (no tz_aware=True on
    # the client) — must compare against a naive datetime too, not an aware one.
    return datetime(d.year, d.month, d.day)


# ── Entry point ───────────────────────────────────────────────────────────────

async def _async_main() -> None:
    if not await init_beanie():
        print("\n  ❌ MONGODB_URI non défini ou connexion MongoDB impossible.")
        sys.exit(1)

    try:
        seed()
        print("\n  ✅ Seed terminé")
        print_summary()
    except Exception as exc:
        print(f"\n  ❌ Error: {exc}")
        raise
    finally:
        await close_mongodb()


def main() -> None:
    parser = argparse.ArgumentParser(description="BIAT IT demo database seeder")
    parser.add_argument("--append",  action="store_true",
                        help=(
                            "Kept for CLI compatibility — every write here is "
                            "idempotent (upsert-by-id or skip-if-exists), so "
                            "re-running is always safe. This flag only affects "
                            "whether re-seeding an existing supplier invoice "
                            "(same file hash) is silently skipped."
                        ))
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate imports and config; do not write to DB")
    args = parser.parse_args()

    print("=" * 56)
    print("  BIAT IT — Demo Database Seeder")
    print("=" * 56)

    if args.dry_run:
        print("\n  [dry-run] Imports OK. Config files:")
        print(f"    {ROOT / 'config' / 'budget_plan.yaml'}")
        print("    DB: MongoDB (MONGODB_URI / MONGODB_DB)")
        print("  Pass without --dry-run to seed.")
        return

    asyncio.run(_async_main())

    print("\n  API      : python scripts/run_api.py")
    print("  Frontend : cd frontend && npm run dev")
    print()


if __name__ == "__main__":
    main()
