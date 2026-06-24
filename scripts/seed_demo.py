#!/usr/bin/env python3
"""BIAT IT — Demo database seeder.

Usage (from project root):
    python scripts/seed_demo.py            # wipe DB and seed fresh
    python scripts/seed_demo.py --append   # keep existing rows, add only new ones
    python scripts/seed_demo.py --dry-run  # validate imports without writing

Populates:
  1. 24 supplier invoices spanning all statuses + all cost catalogue entries
  2. 9  double-entry journal entries (matched to JOURNALED invoices)
  3. 30 monthly depreciation entries (5 assets × Jan–Jun 2026)
  4.  5 CAPEX assets (linear + dégressive)
  5.  3 projects + 9 phases + June 2026 fiche mensuelle
  6.  5 asset-project allocations
  7.  3 outgoing client invoices (PAID / SENT / DRAFT)
  8.  Budget plan updated to match seeded amounts
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Early import check ────────────────────────────────────────────────────────
try:
    from src.storage.db import build_engine, build_session_factory, init_db
    from src.storage.repository import InvoiceRepository
    from src.accounting.journal_store import JournalRepository
    from src.capex.asset_repository import AssetRepository
    from src.billing.client_invoice_store import ClientInvoiceRepository
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

DB_URL   = "sqlite:///./data/invoices.db"
SEED_KEY = "biat-demo-2026-v2"


# ── Helpers ───────────────────────────────────────────────────────────────────

def fh(inv_num: str) -> str:
    return hashlib.sha256(f"{SEED_KEY}:{inv_num}".encode()).hexdigest()

def cf(value, conf: float = 0.95) -> ConfidenceField:
    return ConfidenceField(value=value, confidence=conf)

def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)

def utc(dt: date, hour: int = 10) -> datetime:
    return datetime(dt.year, dt.month, dt.day, hour, 0, 0, tzinfo=timezone.utc)

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
CAPEX = ChargeType.CAPEX
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
         label="Matériel informatique", nature=FIXE, typ=CAPEX, status=FLG,
         desc="Lot 4 serveurs Dell PowerEdge R760 + baies de stockage PowerVault",
         flags=[ValidationFlag(
             flag_type=FlagType.HIGH_VALUE, severity=FlagSeverity.ERROR,
             message="Montant TTC 73 780 TND dépasse le seuil de revue (50 000 TND)",
         )]),
    dict(num="FAC-2026-17-CISCO",    inv_date=d(2026,4,10), due=d(2026,5,10),
         issuer="CISCO SYSTEMS TUNISIE",  mf="0678912N/A/M/000",
         ht=78000, tva=19, catalog_id="materiel_informatique", compte="2183",
         label="Matériel informatique", nature=FIXE, typ=CAPEX, status=FLG,
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

# Which specs need journal entries (JOURNALED or PAID)
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


# ── Seeder ────────────────────────────────────────────────────────────────────

def seed(session, *, append: bool = False) -> None:
    inv_repo   = InvoiceRepository(session)
    jnl_repo   = JournalRepository(session)
    asset_repo = AssetRepository(session)
    ci_repo    = ClientInvoiceRepository(session)

    existing_hashes = {inv.file_hash.value for inv in inv_repo.list_all()}

    # ── 1. Supplier invoices ──────────────────────────────────────────────────
    print("\n[1/5] Supplier invoices…")
    journal_queue: list[tuple[InvoiceRecord, str]] = []
    created = skipped = 0

    for spec in SUPPLIER_SPECS:
        num = spec["num"]
        if fh(num) in existing_hashes and append:
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
        print(f"  {'  ' if spec['status'] == RCV else ''}{num}  →  {status_str}")

    print(f"  {created} created, {skipped} skipped (--append)")

    print(f"\n  Creating {len(journal_queue)} journal entries…")
    for inv, compte in journal_queue:
        jnl_repo.save(make_journal(inv, compte))

    # ── 2. CAPEX assets + depreciation ───────────────────────────────────────
    print("\n[2/5] CAPEX assets + depreciation (Jan–Jun 2026)…")
    assets: list[Asset] = []
    for spec in ASSET_SPECS:
        asset = Asset(**spec)
        asset_repo.save(asset)
        assets.append(asset)
        print(f"  {asset.designation}")

    dep_count = 0
    for asset in assets:
        amort = asset.monthly_depreciation
        for m in range(1, 7):
            ld = last_day(2026, m)
            jnl_repo.save(JournalEntry(
                reference=f"AMORT-{asset.designation[:15].replace(' ','-')}-2026{m:02d}",
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
    print(f"  {dep_count} depreciation entries (5 assets × 6 months)")

    # ── 3. Projects + phases ──────────────────────────────────────────────────
    from src.storage.orm_models_projects import CharteProjetORM, PhaseORM  # noqa: PLC0415
    print("\n[3/5] Projects + phases…")
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
        if not session.get(CharteProjetORM, pd["id"]):
            session.add(CharteProjetORM(**pd))
    for phd in phase_data:
        if not session.get(PhaseORM, phd["id"]):
            session.add(PhaseORM(**phd))
    session.flush()
    print(f"  {len(proj_data)} projects, {len(phase_data)} phases")

    # ── 4. Client invoices ────────────────────────────────────────────────────
    print("\n[4/5] Client invoices…")
    for ci in _make_client_invoices():
        ci_repo.save(ci)
        print(f"  {ci.invoice_number}  HT={ci.amount_ht:,.3f} TND  [{ci.status.value}]")

    # ── 5. Budget plan ────────────────────────────────────────────────────────
    print("\n[5/5] Updating budget_plan.yaml…")
    _update_budget_plan()


def _update_budget_plan() -> None:
    import yaml
    plan_path = ROOT / "config" / "budget_plan.yaml"
    with open(plan_path) as f:
        plan = yaml.safe_load(f)

    updates = {
        "telecommunications":    {"monthly": [5000]*12, "annual": 60000},
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


def print_summary(session) -> None:
    from collections import Counter
    inv_repo   = InvoiceRepository(session)
    jnl_repo   = JournalRepository(session)
    asset_repo = AssetRepository(session)
    ci_repo    = ClientInvoiceRepository(session)

    invs    = inv_repo.list_all()
    entries = jnl_repo.list_entries()
    assets  = asset_repo.list_all()
    cis     = ci_repo.list_all()

    counts  = Counter(i.status.value for i in invs)
    total   = sum(i.amount_ttc.value or 0 for i in invs
                  if i.direction == InvoiceDirection.SUPPLIER and i.amount_ttc.value)

    w = 54
    print("\n" + "═" * w)
    print("  DEMO DATASET — SUMMARY")
    print("═" * w)
    print(f"\n  Supplier invoices : {len(invs)}")
    for status, n in sorted(counts.items()):
        bar = "█" * n
        print(f"    {status:<20} {n:>2}  {bar}")
    print(f"  Total TTC fournisseurs : {total:>12,.3f} TND")

    inv_jnl = sum(1 for e in entries if e.source_invoice_id)
    dep_jnl = sum(1 for e in entries if e.source_asset_id)
    print(f"\n  Journal entries   : {len(entries)}")
    print(f"    Invoice         : {inv_jnl}")
    print(f"    Depreciation    : {dep_jnl}")

    gross = asset_repo.total_gross_value()
    print(f"\n  CAPEX assets      : {len(assets)}")
    print(f"  Gross value       : {gross:>12,.3f} TND")

    billed = sum(ci.amount_ht for ci in cis)
    print(f"\n  Client invoices   : {len(cis)}")
    print(f"  Total billed HT   : {billed:>12,.3f} TND")

    overdue_count = sum(
        1 for i in invs
        if i.status == InvoiceStatus.EXPORTED
        and i.due_date.value
        and i.due_date.value < date.today()
        and not i.paid_at
    )
    print(f"\n  Overdue invoices  : {overdue_count}")
    print("\n" + "═" * w)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="BIAT IT demo database seeder")
    parser.add_argument("--append",  action="store_true",
                        help="Keep existing rows; skip duplicates (by file hash)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate imports and config; do not write to DB")
    args = parser.parse_args()

    print("=" * 54)
    print("  BIAT IT — Demo Database Seeder")
    print("=" * 54)

    if args.dry_run:
        print("\n  [dry-run] Imports OK. Config files:")
        print(f"    {ROOT / 'config' / 'budget_plan.yaml'}")
        print(f"    DB: {DB_URL}")
        print("  Pass without --dry-run to seed.")
        return

    db_path = ROOT / "data" / "invoices.db"

    if not args.append:
        if db_path.exists():
            db_path.unlink()
            print(f"\n  Removed existing database.")
        (ROOT / "data").mkdir(exist_ok=True)

    engine  = build_engine(DB_URL)
    init_db(engine)
    sf      = build_session_factory(engine)
    session = sf()

    try:
        seed(session, append=args.append)
        print_summary(session)
    finally:
        session.close()

    print(f"\n  Database : {db_path}")
    print("  API      : python scripts/run_api.py")
    print("  Frontend : cd frontend && npm run dev")
    print()


if __name__ == "__main__":
    main()
