#!/usr/bin/env python3
"""BIAT IT Billing Agent — Comprehensive Demo Dataset Generator.

Populates the SQLite database with 6 sections of demo data:
  1. 20 supplier invoices (all statuses, all cost categories)
  2.  5 CAPEX assets + monthly depreciation journal entries for 2026
  3.  3 projects with phases and a June 2026 fiche mensuelle
  4.  Asset-project allocations
  5.  3 client invoices (PAID / SENT / DRAFT)
  6.  Updated budget_plan.yaml

Run from project root: python scripts/make_full_demo_dataset.py
"""
from __future__ import annotations

import hashlib
import sys
import yaml
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.repository import InvoiceRepository
from src.accounting.journal_store import JournalRepository
from src.capex.asset_repository import AssetRepository
from src.billing.project_repository import ProjectRepository
from src.billing.client_invoice_store import ClientInvoiceRepository
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
from src.models.asset import Asset
from src.models.journal import JournalEntry, JournalLine
from src.models.client_invoice import ClientInvoice, ClientInvoiceStatus, ClientLineItem
from src.models.project import (
    AvanceProgrammee, CharteProjet, FicheMensuelle, FicheStatus,
    Phase, PhaseStatus,
)
from src.models.cost_allocation import AssetProjectLink
from src.models.enums import (
    ChargeNature, ChargeType, ExtractionMethod,
    FlagSeverity, FlagType, InvoiceDirection, InvoiceStatus,
)

DB_URL = "sqlite:///./data/invoices.db"
DEMO_SEED = "biat-it-demo-2026"


# ── Helpers ───────────────────────────────────────────────────────────────────

def fh(inv_num: str) -> str:
    """Deterministic unique file hash from invoice number."""
    return hashlib.sha256(f"{DEMO_SEED}:{inv_num}".encode()).hexdigest()


def cf(value, conf: float = 0.95) -> ConfidenceField:
    return ConfidenceField(value=value, confidence=conf)


def utc(d: date, hour: int = 10) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=timezone.utc)


def d(y: int, m: int, day: int) -> date:
    return date(y, m, day)


def round3(x: float) -> float:
    return round(x, 3)


def _make_supplier_invoice(
    *,
    inv_num: str,
    inv_date: date,
    due_date: date,
    issuer: str,
    issuer_mf: str,
    amount_ht: float,
    tva_rate: float,
    catalog_id: str,
    compte: str,
    label: str,
    charge_nature: ChargeNature,
    charge_type: ChargeType,
    status: InvoiceStatus,
    description: str,
    flags: list[ValidationFlag] | None = None,
    last_error: str | None = None,
) -> InvoiceRecord:
    tva = round3(amount_ht * tva_rate / 100)
    ttc = round3(amount_ht + tva)
    now = datetime.now(timezone.utc)

    # Spread lifecycle timestamps realistically
    rcvd = utc(inv_date - timedelta(days=1))
    extr = utc(inv_date)
    clsf = utc(inv_date, 11)
    vald = utc(inv_date, 12)
    expd = utc(inv_date + timedelta(days=1))

    inv = InvoiceRecord(
        file_hash=fh(inv_num),
        raw_file_path=f"/demo/{inv_num}.pdf",
        direction=InvoiceDirection.SUPPLIER,
        status=status,
        extraction_method=ExtractionMethod.NATIVE_PDF_LLM,
        issuer_name=cf(issuer),
        issuer_tax_id=cf(issuer_mf),
        recipient_name=cf("BIAT IT - Banque Internationale Arabe de Tunisie"),
        recipient_tax_id=cf("0000217V/A/M/000"),
        invoice_number=cf(inv_num),
        invoice_date=cf(inv_date),
        due_date=cf(due_date),
        amount_ht=cf(amount_ht),
        tva_rate=cf(tva_rate),
        tva_amount=cf(tva),
        amount_ttc=cf(ttc),
        currency="TND",
        cost_catalog_id=catalog_id,
        accounting_compte=compte,
        accounting_label=label,
        charge_nature=charge_nature,
        charge_type=charge_type,
        line_items=[LineItem(
            line_number=1,
            description=description,
            quantity=1.0,
            unit_price=amount_ht,
            line_total=amount_ht,
            tva_rate=tva_rate,
        )],
        last_error=last_error,
        received_at=rcvd,
    )

    if status in {InvoiceStatus.EXTRACTED, InvoiceStatus.CLASSIFIED,
                  InvoiceStatus.VALIDATED, InvoiceStatus.FLAGGED,
                  InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED}:
        inv.extracted_at = extr
    if status in {InvoiceStatus.CLASSIFIED, InvoiceStatus.VALIDATED,
                  InvoiceStatus.FLAGGED, InvoiceStatus.EXPORTED,
                  InvoiceStatus.JOURNALED}:
        inv.classified_at = clsf
    if status in {InvoiceStatus.VALIDATED, InvoiceStatus.FLAGGED,
                  InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED}:
        inv.validated_at = vald
    if status in {InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED}:
        inv.exported_at = expd
        inv.export_reference = f"EXP-{inv_num}"

    if flags:
        for flag in flags:
            inv.add_flag(flag)

    if status == InvoiceStatus.FLAGGED and not flags:
        inv.human_review_required = True

    return inv


def _make_journal_entry(
    inv: InvoiceRecord,
    compte_charge: str,
) -> JournalEntry:
    """Build a balanced PCE double-entry for a supplier invoice."""
    ht  = inv.amount_ht.value
    tva = inv.tva_amount.value
    ttc = inv.amount_ttc.value
    ref = inv.invoice_number.value
    dt  = inv.invoice_date.value
    lib = f"Facture {inv.issuer_name.value} - {ref}"

    lines: list[JournalLine] = []

    if tva and tva > 0:
        lines = [
            JournalLine(compte=compte_charge, libelle=lib, debit=ht),
            JournalLine(compte="4366", libelle=f"TVA déductible {ref}", debit=tva),
            JournalLine(compte="401",  libelle=f"Fournisseur {inv.issuer_name.value}", credit=ttc),
        ]
    else:
        lines = [
            JournalLine(compte=compte_charge, libelle=lib, debit=ht),
            JournalLine(compte="401",  libelle=f"Fournisseur {inv.issuer_name.value}", credit=ht),
        ]

    return JournalEntry(
        reference=ref,
        date_ecriture=dt,
        description=lib,
        source_invoice_id=inv.id,
        lines=lines,
    )


# ── Section 1: Supplier invoices ──────────────────────────────────────────────

def create_supplier_invoices(
    inv_repo: InvoiceRepository,
    jnl_repo: JournalRepository,
) -> None:

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

    # ── 5 JOURNALED (TVA 19%) ─────────────────────────────────────────────────
    journaled_19 = [
        dict(
            inv_num="FAC-2026-01-OOREDOO",  inv_date=d(2026,1,15), due_date=d(2026,2,14),
            issuer="OOREDOO TUNISIE SA",     issuer_mf="0038472K/A/M/000",
            amount_ht=3750.000, tva_rate=19,
            catalog_id="telecommunications", compte="6261",
            label="Frais de télécommunications",
            charge_nature=SEMI, charge_type=OPEX, status=JRN,
            description="Abonnement fibre optique 1 Gbps + lignes mobiles x20 - Janvier 2026",
        ),
        dict(
            inv_num="FAC-2026-02-STEG",      inv_date=d(2026,2,5),  due_date=d(2026,3,7),
            issuer="STEG",                   issuer_mf="0000045A/P/M/000",
            amount_ht=2400.000, tva_rate=19,
            catalog_id="electricite_steg",   compte="6241",
            label="Électricité (STEG)",
            charge_nature=SEMI, charge_type=OPEX, status=JRN,
            description="Consommation électrique Data Center + Bureaux Siège - Février 2026",
        ),
        dict(
            inv_num="FAC-2026-03-NEXIA",     inv_date=d(2026,2,20), due_date=d(2026,3,22),
            issuer="NEXIA INFORMATIQUE SARL", issuer_mf="1472583D/A/M/000",
            amount_ht=4500.000, tva_rate=19,
            catalog_id="maintenance_informatique", compte="6112",
            label="Maintenance et support informatique",
            charge_nature=FIXE, charge_type=OPEX, status=JRN,
            description="Contrat TMA serveurs et postes de travail - T1 2026",
        ),
        dict(
            inv_num="FAC-2026-04-SECURITAS",  inv_date=d(2026,3,1),  due_date=d(2026,3,31),
            issuer="SECURITAS TUNISIE",       issuer_mf="0887632B/A/M/000",
            amount_ht=5200.000, tva_rate=19,
            catalog_id="gardiennage_securite", compte="6281",
            label="Gardiennage et sécurité",
            charge_nature=FIXE, charge_type=OPEX, status=JRN,
            description="Gardiennage immeuble siège BIAT IT - Mars 2026",
        ),
        dict(
            inv_num="FAC-2026-05-TOPNET",     inv_date=d(2026,3,15), due_date=d(2026,4,14),
            issuer="TOPNET",                  issuer_mf="0934721C/A/M/000",
            amount_ht=1800.000, tva_rate=19,
            catalog_id="telecommunications",  compte="6261",
            label="Frais de télécommunications",
            charge_nature=SEMI, charge_type=OPEX, status=JRN,
            description="Abonnement internet ADSL Pro 100 Mbps + VPN - Mars 2026",
        ),
    ]

    # ── 4 JOURNALED (TVA 0% — formation exonérée) ────────────────────────────
    journaled_0 = [
        dict(
            inv_num="FAC-2026-06-GTT",       inv_date=d(2026,2,1),  due_date=d(2026,3,3),
            issuer="GLOBAL TECH TRAINING",   issuer_mf="1256398F/A/M/000",
            amount_ht=6500.000, tva_rate=0,
            catalog_id="formation_personnel", compte="6311",
            label="Formation du personnel",
            charge_nature=VAR, charge_type=OPEX, status=JRN,
            description="Formation AWS Practitioner + Cloud Architect (5 jours, 8 stagiaires)",
        ),
        dict(
            inv_num="FAC-2026-07-CIEL",      inv_date=d(2026,3,10), due_date=d(2026,4,9),
            issuer="CIEL FORMATION SARL",    issuer_mf="1398741G/A/M/000",
            amount_ht=4200.000, tva_rate=0,
            catalog_id="formation_personnel", compte="6311",
            label="Formation du personnel",
            charge_nature=VAR, charge_type=OPEX, status=JRN,
            description="Formation Cybersécurité ISO 27001 Lead Implementer (3 jours, 5 stagiaires)",
        ),
        dict(
            inv_num="FAC-2026-08-CIEL2",     inv_date=d(2026,4,5),  due_date=d(2026,5,5),
            issuer="CIEL FORMATION SARL",    issuer_mf="1398741G/A/M/000",
            amount_ht=3800.000, tva_rate=0,
            catalog_id="formation_personnel", compte="6311",
            label="Formation du personnel",
            charge_nature=VAR, charge_type=OPEX, status=JRN,
            description="Formation DevOps CI/CD Jenkins+Docker (2 jours, 6 stagiaires)",
        ),
        dict(
            inv_num="FAC-2026-09-GTT2",      inv_date=d(2026,5,12), due_date=d(2026,6,11),
            issuer="GLOBAL TECH TRAINING",   issuer_mf="1256398F/A/M/000",
            amount_ht=7500.000, tva_rate=0,
            catalog_id="formation_personnel", compte="6311",
            label="Formation du personnel",
            charge_nature=VAR, charge_type=OPEX, status=JRN,
            description="Formation Architecture Data & BI Tableau/PowerBI (5 jours, 10 stagiaires)",
        ),
    ]

    # ── 3 EXPORTED ────────────────────────────────────────────────────────────
    exported = [
        dict(
            inv_num="FAC-2026-10-SOTETEL",   inv_date=d(2026,4,1),  due_date=d(2026,5,1),
            issuer="SOTETEL",                issuer_mf="0345892H/A/M/000",
            amount_ht=8500.000, tva_rate=19,
            catalog_id="licences_saas",      compte="6133",
            label="Licences logiciels et abonnements SaaS",
            charge_nature=FIXE, charge_type=OPEX, status=EXP,
            description="Abonnement annuel Sophos XDR Endpoint Security (50 postes) 2026",
        ),
        dict(
            inv_num="FAC-2026-11-TT",        inv_date=d(2026,4,15), due_date=d(2026,5,15),
            issuer="TUNISIE TELECOM",         issuer_mf="0012456A/P/M/000",
            amount_ht=2200.000, tva_rate=19,
            catalog_id="telecommunications", compte="6261",
            label="Frais de télécommunications",
            charge_nature=SEMI, charge_type=OPEX, status=EXP,
            description="Lignes fixes + RNIS data centre - Avril 2026",
        ),
        dict(
            inv_num="FAC-2026-12-PDC",       inv_date=d(2026,5,3),  due_date=d(2026,6,2),
            issuer="PAPETERIE DU CENTRE",    issuer_mf="0876543J/A/M/000",
            amount_ht=650.000, tva_rate=19,
            catalog_id="fournitures_bureau", compte="6061",
            label="Fournitures de bureau",
            charge_nature=VAR, charge_type=OPEX, status=EXP,
            description="Ramettes A4 (50 cartons), classeurs, stylos - T2 2026",
        ),
    ]

    # ── 3 VALIDATED ───────────────────────────────────────────────────────────
    validated = [
        dict(
            inv_num="FAC-2026-13-MS",        inv_date=d(2026,5,15), due_date=d(2026,6,14),
            issuer="MICROSOFT TUNISIE SARL", issuer_mf="0764321K/A/M/000",
            amount_ht=18000.000, tva_rate=19,
            catalog_id="licences_saas",      compte="6133",
            label="Licences logiciels et abonnements SaaS",
            charge_nature=FIXE, charge_type=OPEX, status=VAL,
            description="Renouvellement Microsoft 365 Business Premium (60 utilisateurs) 2026-2027",
        ),
        dict(
            inv_num="FAC-2026-14-KPMG",      inv_date=d(2026,5,20), due_date=d(2026,6,19),
            issuer="KPMG TUNISIE",           issuer_mf="0098765J/A/M/000",
            amount_ht=12000.000, tva_rate=19,
            catalog_id="honoraires_conseil", compte="6222",
            label="Honoraires de conseil, audit et expertise",
            charge_nature=VAR, charge_type=OPEX, status=VAL,
            description="Mission audit processus DSI et recommandations COBIT - S1 2026",
        ),
        dict(
            inv_num="FAC-2026-15-IBM",       inv_date=d(2026,6,1),  due_date=d(2026,7,1),
            issuer="IBM TUNISIE",            issuer_mf="0345678L/A/M/000",
            amount_ht=8500.000, tva_rate=19,
            catalog_id="maintenance_informatique", compte="6112",
            label="Maintenance et support informatique",
            charge_nature=FIXE, charge_type=OPEX, status=VAL,
            description="Contrat support Premium IBM AIX servers - Juin 2026",
        ),
    ]

    # ── 2 FLAGGED — HIGH_VALUE ────────────────────────────────────────────────
    flagged_hv = [
        dict(
            inv_num="FAC-2026-16-DELL",      inv_date=d(2026,3,20), due_date=d(2026,4,19),
            issuer="DELL TECHNOLOGIES TN",   issuer_mf="0567891M/A/M/000",
            amount_ht=62000.000, tva_rate=19,
            catalog_id="materiel_informatique", compte="2183",
            label="Matériel informatique (serveurs, PC, écrans, équipements réseau)",
            charge_nature=FIXE, charge_type=CAPEX, status=FLG,
            description="Lot 4 serveurs Dell PowerEdge R760 + baies de stockage Dell PowerVault",
            flags=[ValidationFlag(
                flag_type=FlagType.HIGH_VALUE, severity=FlagSeverity.ERROR,
                message="Montant TTC 73,780 TND dépasse le seuil de revue manuelle (50,000 TND)",
            )],
        ),
        dict(
            inv_num="FAC-2026-17-CISCO",     inv_date=d(2026,4,10), due_date=d(2026,5,10),
            issuer="CISCO SYSTEMS TUNISIE",  issuer_mf="0678912N/A/M/000",
            amount_ht=78000.000, tva_rate=19,
            catalog_id="materiel_informatique", compte="2183",
            label="Matériel informatique (serveurs, PC, écrans, équipements réseau)",
            charge_nature=FIXE, charge_type=CAPEX, status=FLG,
            description="Infrastructure réseau Cisco Catalyst 9500 + Firewall Cisco FPR4100",
            flags=[ValidationFlag(
                flag_type=FlagType.HIGH_VALUE, severity=FlagSeverity.ERROR,
                message="Montant TTC 92,820 TND dépasse le seuil de revue manuelle (50,000 TND)",
            )],
        ),
    ]

    # ── 2 FLAGGED — CATALOG_NO_MATCH ─────────────────────────────────────────
    flagged_cat = [
        dict(
            inv_num="FAC-2026-18-PRINT",     inv_date=d(2026,4,25), due_date=d(2026,5,25),
            issuer="PRINTWAY TUNISIE SARL",  issuer_mf="0789123P/A/M/000",
            amount_ht=850.000, tva_rate=19,
            catalog_id=None,                 compte=None,
            label=None,
            charge_nature=None, charge_type=None, status=FLG,
            description="Impression roll-ups et brochures présentation DSI Q2 2026",
            flags=[ValidationFlag(
                flag_type=FlagType.CATALOG_NO_MATCH, severity=FlagSeverity.WARNING,
                message="Aucune entrée catalogue ne correspond (score max 48 < seuil 70). "
                        "Catégorie probable : publicite_communication",
            )],
        ),
        dict(
            inv_num="FAC-2026-19-SEL",       inv_date=d(2026,5,8),  due_date=d(2026,6,7),
            issuer="SOCIÉTÉ EXPRESS LOGISTIQUE", issuer_mf="0891234Q/A/M/000",
            amount_ht=1200.000, tva_rate=19,
            catalog_id=None,                 compte=None,
            label=None,
            charge_nature=None, charge_type=None, status=FLG,
            description="Transport et livraison équipements informatiques sur 3 sites",
            flags=[ValidationFlag(
                flag_type=FlagType.CATALOG_NO_MATCH, severity=FlagSeverity.WARNING,
                message="Aucune entrée catalogue ne correspond. "
                        "Catégorie probable : frais_deplacement",
            )],
        ),
    ]

    # ── 1 ERROR ───────────────────────────────────────────────────────────────
    error_inv = [
        dict(
            inv_num="FAC-2026-20-ERR",       inv_date=d(2026,5,30), due_date=d(2026,6,29),
            issuer=None,                     issuer_mf=None,
            amount_ht=None, tva_rate=None,
            catalog_id=None,                 compte=None,
            label=None,
            charge_nature=None, charge_type=None, status=ERR,
            description="Document illisible — tentatives OCR épuisées",
            last_error="Extraction échouée après 3 tentatives : OCR confidence < 40%",
        ),
    ]

    all_specs = (
        journaled_19 + journaled_0 + exported + validated
        + flagged_hv + flagged_cat + error_inv
    )

    journaled_journal_specs = []  # (invoice, compte_charge) pairs needing journal entries

    for i, spec in enumerate(all_specs, 1):
        # Build the invoice (handle None fields for error invoice)
        kwargs = dict(
            inv_num=spec["inv_num"],
            inv_date=spec["inv_date"] if spec.get("inv_date") else d(2026,5,30),
            due_date=spec["due_date"] if spec.get("due_date") else d(2026,6,29),
            issuer=spec["issuer"] or "INCONNU",
            issuer_mf=spec["issuer_mf"] or "0000000X",
            amount_ht=spec["amount_ht"] or 0.0,
            tva_rate=spec["tva_rate"] or 0.0,
            catalog_id=spec.get("catalog_id"),
            compte=spec.get("compte"),
            label=spec.get("label"),
            charge_nature=spec.get("charge_nature"),
            charge_type=spec.get("charge_type"),
            status=spec["status"],
            description=spec["description"],
            flags=spec.get("flags"),
            last_error=spec.get("last_error"),
        )
        inv = _make_supplier_invoice(**kwargs)

        # For the error invoice, clear extracted fields
        if spec["status"] == InvoiceStatus.ERROR:
            inv.issuer_name      = ConfidenceField()
            inv.issuer_tax_id    = ConfidenceField()
            inv.invoice_number   = cf(spec["inv_num"], 0.0)
            inv.amount_ht        = ConfidenceField()
            inv.tva_amount       = ConfidenceField()
            inv.amount_ttc       = ConfidenceField()

        inv_repo.save(inv)

        # Queue JOURNALED invoices for journal entry creation
        if spec["status"] == InvoiceStatus.JOURNALED and spec.get("compte"):
            journaled_journal_specs.append((inv, spec["compte"]))

        print(f"    [{i:02d}/20] {spec['inv_num']} → {spec['status'].value}")

    # Create journal entries for all JOURNALED invoices
    print(f"  Creating {len(journaled_journal_specs)} journal entries…")
    for inv, compte in journaled_journal_specs:
        entry = _make_journal_entry(inv, compte)
        jnl_repo.save(entry)


# ── Section 2: CAPEX assets + depreciation ────────────────────────────────────

def create_assets(
    asset_repo: AssetRepository,
    jnl_repo: JournalRepository,
) -> list[Asset]:

    asset_specs = [
        dict(
            designation="Serveurs Dell PowerEdge R750 (lot 3)",
            compte_immobilisation="2183", compte_amortissement="2893",
            acquisition_date=d(2024,1,15), acquisition_cost_ht=85000.00,
            useful_life_years=5, depreciation_method="linear",
            notes="Salle serveurs N-1, remplace lot PowerEdge R640",
        ),
        dict(
            designation="Licences Microsoft 365 Business (50 postes)",
            compte_immobilisation="2188", compte_amortissement="2898",
            acquisition_date=d(2024,6,1), acquisition_cost_ht=12000.00,
            useful_life_years=3, depreciation_method="degressive",
            notes="Contrat Microsoft EA — renouvellement juin 2027",
        ),
        dict(
            designation="Switch réseau Cisco Catalyst 9300",
            compte_immobilisation="2183", compte_amortissement="2893",
            acquisition_date=d(2023,9,1), acquisition_cost_ht=28500.00,
            useful_life_years=5, depreciation_method="linear",
            notes="Cœur réseau LAN siège BIAT IT, 48 ports 10G",
        ),
        dict(
            designation="Onduleurs APC Smart-UPS (lot 5)",
            compte_immobilisation="2183", compte_amortissement="2893",
            acquisition_date=d(2025,3,1), acquisition_cost_ht=15750.00,
            useful_life_years=5, depreciation_method="linear",
            notes="Protection alimentation salle serveurs et postes critiques",
        ),
        dict(
            designation="Logiciel ERP Sage 100 (licence perpétuelle)",
            compte_immobilisation="2183", compte_amortissement="2893",
            acquisition_date=d(2023,1,1), acquisition_cost_ht=45000.00,
            useful_life_years=5, depreciation_method="degressive",
            notes="ERP comptabilité, RH et gestion commerciale BIAT IT",
        ),
    ]

    assets: list[Asset] = []
    for i, spec in enumerate(asset_specs, 1):
        asset = Asset(**spec)
        asset_repo.save(asset)
        assets.append(asset)
        print(f"    [{i}/5] {asset.designation}")

    # Monthly depreciation entries Jan–Jun 2026
    MONTHS_2026 = [d(2026, m, 1) for m in range(1, 7)]
    entry_count = 0
    for asset in assets:
        monthly_amort = asset.monthly_depreciation
        for month_date in MONTHS_2026:
            last_day = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            entry = JournalEntry(
                reference=f"AMORT-{asset.designation[:15].replace(' ','-')}-{month_date.strftime('%Y%m')}",
                date_ecriture=last_day,
                description=(
                    f"Dotation amortissement {month_date.strftime('%B %Y')} — "
                    f"{asset.designation}"
                ),
                source_asset_id=asset.id,
                lines=[
                    JournalLine(
                        compte="6811",
                        libelle=f"Dotation amort. {asset.designation[:40]}",
                        debit=monthly_amort,
                    ),
                    JournalLine(
                        compte=asset.compte_amortissement,
                        libelle=f"Amort. cumulé {asset.designation[:40]}",
                        credit=monthly_amort,
                    ),
                ],
            )
            jnl_repo.save(entry)
            entry_count += 1

    print(f"  Created {entry_count} depreciation journal entries (Jan–Jun 2026)")
    return assets


# ── Section 3: Projects and phases ───────────────────────────────────────────

def create_projects(proj_repo: ProjectRepository) -> dict[str, list[Phase]]:
    """Returns {project_id: [phases]} for use in sections 4 and 5."""

    charte_specs = [
        dict(id="CHR-2026-001", project_id="PRJ-CBK",
             project_name="Migration Core Banking v4",
             budget_jh=180.0, taux_jh=850.0, valid_from=d(2026,1,1)),
        dict(id="CHR-2026-002", project_id="PRJ-PCD",
             project_name="Portail Client Digital",
             budget_jh=120.0, taux_jh=850.0, valid_from=d(2026,2,1)),
        dict(id="CHR-2026-003", project_id="PRJ-IC",
             project_name="Infrastructure Cloud Migration",
             budget_jh=90.0,  taux_jh=850.0, valid_from=d(2026,3,1)),
    ]

    phase_specs = {
        "PRJ-CBK": [
            dict(id="PRJ-CBK-P1", name="Analyse et spécifications fonctionnelles",
                 description="Recueil des besoins CBS v4, documentation AS-IS / TO-BE",
                 planned_jh=50.0, consumed_jh=48.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,3,31),
                 livrables=["Cahier des charges fonctionnel v1.0",
                            "Rapport AS-IS / TO-BE", "Matrice des écarts"]),
            dict(id="PRJ-CBK-P2", name="Architecture technique et maquettage",
                 description="Architecture cible CBS, infrastructure et intégrations",
                 planned_jh=40.0, consumed_jh=38.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,5,31),
                 livrables=["Dossier d'architecture technique",
                            "Maquette interface CBS v4", "Plan de migration"]),
            dict(id="PRJ-CBK-P3", name="Développement et intégration",
                 description="Implémentation des flux métier et interfaces CBS",
                 planned_jh=90.0, consumed_jh=0.0,
                 status=PhaseStatus.OPEN, closed_date=None, livrables=[]),
        ],
        "PRJ-PCD": [
            dict(id="PRJ-PCD-P1", name="UX/UI design et prototypage",
                 description="Maquettes interface portail, tests utilisateurs pilotes",
                 planned_jh=35.0, consumed_jh=33.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,4,30),
                 livrables=["Prototype Figma haute fidélité",
                            "Rapport tests UX", "Guide de style DSI"]),
            dict(id="PRJ-PCD-P2", name="Développement frontend React",
                 description="Implémentation portail client responsive (mobile first)",
                 planned_jh=45.0, consumed_jh=42.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,6,15),
                 livrables=["Application React v1.0 déployée en recette",
                            "Rapport tests fonctionnels"]),
            dict(id="PRJ-PCD-P3", name="Backend API et intégrations SI",
                 description="API REST + intégrations CBS, notification push",
                 planned_jh=40.0, consumed_jh=0.0,
                 status=PhaseStatus.OPEN, closed_date=None, livrables=[]),
        ],
        "PRJ-IC": [
            dict(id="PRJ-IC-P1", name="Audit infrastructure existante",
                 description="Inventaire et évaluation migration-readiness",
                 planned_jh=20.0, consumed_jh=18.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,4,15),
                 livrables=["Rapport audit infrastructure",
                            "Matrice de migration priorités", "RFI cloud providers"]),
            dict(id="PRJ-IC-P2", name="POC Cloud hybride (AWS + on-premise)",
                 description="Proof of concept déploiement conteneurs et réseau hybride",
                 planned_jh=30.0, consumed_jh=28.0,
                 status=PhaseStatus.CLOSED, closed_date=d(2026,6,10),
                 livrables=["Rapport POC cloud hybride",
                            "Architecture cible validée", "Bilan coûts cloud"]),
            dict(id="PRJ-IC-P3", name="Migration pilote (20% du parc)",
                 description="Migration lot pilote : 5 applications non-critiques",
                 planned_jh=40.0, consumed_jh=0.0,
                 status=PhaseStatus.OPEN, closed_date=None, livrables=[]),
        ],
    }

    phases_by_project: dict[str, list[Phase]] = {}

    for spec in charte_specs:
        charte = CharteProjet(**spec, valid_until=None, client="BIAT", is_active=True)
        proj_repo.save_charte(charte)
        print(f"    Charte {charte.id} — {charte.project_name}")

        phases: list[Phase] = []
        for ps in phase_specs[spec["project_id"]]:
            phase = Phase(**ps, project_id=spec["project_id"])
            proj_repo.save_phase(phase)
            phases.append(phase)
            status_label = "CLOSED" if ps["status"] == PhaseStatus.CLOSED else "OPEN"
            print(f"      Phase {phase.id} [{status_label}]")
        phases_by_project[spec["project_id"]] = phases

    # FicheMensuelle — Juin 2026
    # Closed phases eligible for billing in June:
    #   PRJ-CBK-P2 (closed May 31), PRJ-PCD-P2 (closed Jun 15), PRJ-IC-P2 (closed Jun 10)
    june_closed = ["PRJ-CBK-P2", "PRJ-PCD-P2", "PRJ-IC-P2"]

    avances = [
        AvanceProgrammee(
            project_id="PRJ-IC",
            charte_id="CHR-2026-003",
            description="Avance sur phase 3 migration pilote (achat licences cloud)",
            montant_ht=10000.0,
            schedule_reference="SCHED-PRJ-IC-2026-Q3",
        ),
    ]

    fiche = FicheMensuelle(
        id="FICHE-2026-06",
        period_month=6,
        period_year=2026,
        prepared_by="Baya Chaabene",
        prepared_at=datetime(2026, 6, 16, 9, 0, 0, tzinfo=timezone.utc),
        phases_cloturees=june_closed,
        avances=avances,
        status=FicheStatus.SUBMITTED,
        invoice_number=None,
    )
    proj_repo.save_fiche(fiche)
    print(f"    FicheMensuelle {fiche.id} — {len(june_closed)} phases, SUBMITTED")

    return phases_by_project


# ── Section 4: Asset-project allocations ─────────────────────────────────────

def create_allocations(
    asset_repo: AssetRepository,
    assets: list[Asset],
) -> None:
    allocations_map = [
        # asset_idx, {project_id: pct}
        (0, {"PRJ-CBK": 50.0, "PRJ-PCD": 30.0, "PRJ-IC": 20.0}),  # Dell servers
        (1, {"PRJ-CBK": 40.0, "PRJ-PCD": 40.0, "PRJ-IC": 20.0}),  # MS licences
        (2, {"PRJ-CBK": 33.0, "PRJ-PCD": 33.0, "PRJ-IC": 34.0}),  # Cisco switch
        (3, {"PRJ-CBK": 60.0, "PRJ-PCD": 25.0, "PRJ-IC": 15.0}),  # APC UPS
        (4, {"PRJ-CBK": 70.0, "PRJ-PCD": 20.0, "PRJ-IC": 10.0}),  # ERP Sage
    ]
    for asset_idx, proj_map in allocations_map:
        asset = assets[asset_idx]
        for proj_id, pct in proj_map.items():
            link = AssetProjectLink(
                asset_id=str(asset.id), project_id=proj_id, allocation_pct=pct
            )
            asset_repo.save_link(link)
        print(f"    {asset.designation[:40]} → {proj_map}")


# ── Section 5: Client invoices ────────────────────────────────────────────────

def create_client_invoices(ci_repo: ClientInvoiceRepository) -> None:

    ISSUER_NAME    = "BIAT IT - Banque Internationale Arabe de Tunisie"
    ISSUER_TAX_ID  = "0000217V/A/M/000"
    ISSUER_ADDR    = "70-72 Avenue Habib Bourguiba, 1000 Tunis, Tunisie"
    CLIENT_ID      = "BIAT-GROUP"
    CLIENT_NAME    = "BIAT - Banque Internationale Arabe de Tunisie"
    CLIENT_TAX_ID  = "0000218W/A/M/000"
    CLIENT_ADDR    = "70-72 Avenue Habib Bourguiba, 1000 Tunis, Tunisie"

    def li(desc: str, qty: float, price: float, tva: float = 19.0,
           charte: str | None = None, phase: str | None = None) -> ClientLineItem:
        total = round3(qty * price)
        tva_a = round3(total * tva / 100)
        return ClientLineItem(
            description=desc, quantity=qty, unit_price=price,
            line_total=total, tva_rate=tva, tva_amount=tva_a,
            compte_produit="7061",
            charte_reference=charte, phase_id=phase,
        )

    # Invoice 1 — April 2026 — PAID
    inv1_lines = [
        li("PRJ-CBK Phase 1 : Analyse et spécifications fonctionnelles — 20 JH × 850 TND",
           20.0, 850.0, charte="CHR-2026-001", phase="PRJ-CBK-P1"),
        li("PRJ-IC Avance phase 3 — Achat licences cloud",
           1.0, 10000.0, charte="CHR-2026-003"),
    ]
    inv1 = ClientInvoice(
        invoice_number="FAC-IT-2026-001",
        invoice_date=d(2026, 4, 5),
        due_date=d(2026, 5, 5),
        issuer_name=ISSUER_NAME, issuer_tax_id=ISSUER_TAX_ID, issuer_address=ISSUER_ADDR,
        client_id=CLIENT_ID, client_name=CLIENT_NAME,
        client_tax_id=CLIENT_TAX_ID, client_address=CLIENT_ADDR,
        line_items=inv1_lines,
        status=ClientInvoiceStatus.PAID,
        notes="Facturation phases clôturées T1 2026",
        sent_at=datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc),
        paid_at=datetime(2026, 4, 25, 14, 30, tzinfo=timezone.utc),
    )
    ci_repo.save(inv1)
    print(f"    FAC-IT-2026-001  HT={inv1.amount_ht:,.3f} TND  [PAID]")

    # Invoice 2 — May 2026 — SENT
    inv2_lines = [
        li("PRJ-PCD Phase 1 : UX/UI design et prototypage — 15 JH × 850 TND",
           15.0, 850.0, charte="CHR-2026-002", phase="PRJ-PCD-P1"),
        li("PRJ-CBK Phase 2 : Architecture technique et maquettage — 18 JH × 850 TND",
           18.0, 850.0, charte="CHR-2026-001", phase="PRJ-CBK-P2"),
    ]
    inv2 = ClientInvoice(
        invoice_number="FAC-IT-2026-002",
        invoice_date=d(2026, 5, 10),
        due_date=d(2026, 6, 9),
        issuer_name=ISSUER_NAME, issuer_tax_id=ISSUER_TAX_ID, issuer_address=ISSUER_ADDR,
        client_id=CLIENT_ID, client_name=CLIENT_NAME,
        client_tax_id=CLIENT_TAX_ID, client_address=CLIENT_ADDR,
        line_items=inv2_lines,
        status=ClientInvoiceStatus.SENT,
        notes="Facturation phases clôturées Avril-Mai 2026",
        sent_at=datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc),
    )
    ci_repo.save(inv2)
    print(f"    FAC-IT-2026-002  HT={inv2.amount_ht:,.3f} TND  [SENT]")

    # Invoice 3 — June 2026 — DRAFT
    inv3_lines = [
        li("PRJ-PCD Phase 2 : Développement frontend React — 42 JH × 850 TND",
           42.0, 850.0, charte="CHR-2026-002", phase="PRJ-PCD-P2"),
        li("PRJ-IC Phase 2 : POC Cloud hybride — 28 JH × 850 TND",
           28.0, 850.0, charte="CHR-2026-003", phase="PRJ-IC-P2"),
    ]
    inv3 = ClientInvoice(
        invoice_number="FAC-IT-2026-003",
        invoice_date=d(2026, 6, 16),
        due_date=d(2026, 7, 16),
        issuer_name=ISSUER_NAME, issuer_tax_id=ISSUER_TAX_ID, issuer_address=ISSUER_ADDR,
        client_id=CLIENT_ID, client_name=CLIENT_NAME,
        client_tax_id=CLIENT_TAX_ID, client_address=CLIENT_ADDR,
        line_items=inv3_lines,
        status=ClientInvoiceStatus.DRAFT,
        notes="Phases clôturées Juin 2026 — Fiche FICHE-2026-06",
    )
    ci_repo.save(inv3)
    print(f"    FAC-IT-2026-003  HT={inv3.amount_ht:,.3f} TND  [DRAFT]")


# ── Section 6: Budget plan ────────────────────────────────────────────────────

def update_budget_plan() -> None:
    plan_path = Path("config/budget_plan.yaml")
    with open(plan_path) as f:
        plan = yaml.safe_load(f)

    updates = {
        "telecommunications": {
            "monthly": [5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000],
            "note": "60,000 TND annuel — fibre optique + téléphonie fixe/mobile",
        },
        "formation_personnel": {
            # 0+10+0+15+12.5+7.5+0+15+0+20+20+20 = 120,000
            "monthly": [0, 10000, 0, 15000, 12500, 7500, 0, 15000, 0, 20000, 20000, 20000],
            "note": "120,000 TND annuel — 4 vagues de formation (T1/T2/T3/T4)",
        },
        "licences_saas": {
            # 8*9 + 25*2 + 61 = 72+50+61 = 183? → 8,8,25,8,8,25,8,8,25,8,8,61 = 192? Let me be explicit:
            # 8+8+25+8+8+25+8+8+25+8+8+61 = (8×9)+(25×2)+61 no: 25 appears at idx 2,5,8 = 3 times
            # 8×9 = 72 ; 25×3 = 75 ; 61 at last = 72+75-8+61? No: 8,8,25,8,8,25,8,8,25,8,8,61
            # count of 8s: positions 0,1,3,4,6,7,9,10 = 8 items → 64,000
            # count of 25s: positions 2,5,8 = 3 items → 75,000
            # last: 61,000  → total = 64+75+61 = 200,000 ✓
            "monthly": [8000, 8000, 25000, 8000, 8000, 25000, 8000, 8000, 25000, 8000, 8000, 61000],
            "note": "200,000 TND annuel — renouvellements T1/T2/T3 + big renouvellement T4",
        },
        "materiel_informatique": {
            "monthly": [0, 0, 50000, 0, 0, 0, 0, 0, 50000, 0, 50000, 0],
            "note": "150,000 TND annuel — renouvellement matériel (CAPEX) en 3 lots",
        },
        "honoraires_conseil": {
            "monthly": [5000, 5000, 8000, 5000, 5000, 8000, 5000, 5000, 8000, 5000, 5000, 16000],
            "note": "80,000 TND annuel — audits trimestriels + mission annuelle KPMG",
        },
        "fournitures_bureau": {
            "monthly": [1250, 1250, 1250, 1250, 1250, 1250, 1250, 1250, 1250, 1250, 1250, 1250],
            "note": "15,000 TND annuel",
        },
        "gardiennage_securite": {
            "monthly": [6000, 6000, 6000, 6000, 6000, 6000, 6000, 6000, 6000, 6000, 6000, 6000],
            "note": "72,000 TND annuel — contrat mensuel fixe Securitas",
        },
        "maintenance_informatique": {
            "monthly": [7500, 7500, 7500, 7500, 7500, 7500, 7500, 7500, 7500, 7500, 7500, 7500],
            "note": "90,000 TND annuel — TMA serveurs + support IBM + contrats maintenance",
        },
        "electricite_steg": {
            # 2500+2500+2200+2000+2000+2800+3000+3000+2600+2200+2000+3200 = 30,000
            "monthly": [2500, 2500, 2200, 2000, 2000, 2800, 3000, 3000, 2600, 2200, 2000, 3200],
            "note": "30,000 TND annuel — variation saisonnière climatisation",
        },
    }

    for entry in plan["entries"]:
        cid = entry.get("catalog_id")
        if cid in updates:
            entry["monthly"] = updates[cid]["monthly"]
            entry["note"]    = updates[cid]["note"]
            assert sum(entry["monthly"]) == sum(updates[cid]["monthly"])

    with open(plan_path, "w") as f:
        yaml.dump(plan, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"  Updated {len(updates)} catalog entries in {plan_path}")


# ── Summary ───────────────────────────────────────────────────────────────────

def print_summary(
    inv_repo: InvoiceRepository,
    jnl_repo: JournalRepository,
    asset_repo: AssetRepository,
    ci_repo: ClientInvoiceRepository,
) -> None:
    from collections import Counter

    invs = inv_repo.list_all()
    status_counts = Counter(inv.status.value for inv in invs)
    total_ttc = sum(
        inv.amount_ttc.value for inv in invs
        if inv.amount_ttc.value and inv.direction == InvoiceDirection.SUPPLIER
    )

    journal_entries = jnl_repo.list_entries()
    assets = asset_repo.list_all()
    client_invs = ci_repo.list_all()

    print("\n" + "=" * 60)
    print("  DEMO DATASET SUMMARY")
    print("=" * 60)
    print(f"\n  Supplier invoices : {len(invs)}")
    for status, count in sorted(status_counts.items()):
        print(f"    {status:<20} {count}")
    print(f"  Total TTC (all suppliers): {total_ttc:>12,.3f} TND")

    print(f"\n  Journal entries   : {len(journal_entries)}")
    inv_entries = [e for e in journal_entries if e.source_invoice_id]
    dep_entries = [e for e in journal_entries if e.source_asset_id]
    print(f"    Invoice entries : {len(inv_entries)}")
    print(f"    Depreciation    : {len(dep_entries)}")

    print(f"\n  CAPEX assets      : {len(assets)}")
    total_gross = asset_repo.total_gross_value()
    print(f"  Total gross value : {total_gross:>12,.3f} TND")

    print(f"\n  Client invoices   : {len(client_invs)}")
    total_billed = sum(ci.amount_ht for ci in client_invs)
    print(f"  Total billed HT   : {total_billed:>12,.3f} TND")

    print("\n" + "=" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  BIAT IT Demo Dataset Generator")
    print("=" * 60)

    # Clear the existing DB so the script is re-runnable
    db_path = Path("data/invoices.db")
    if db_path.exists():
        print(f"\n  Removing existing database: {db_path}")
        db_path.unlink()

    engine = build_engine(DB_URL)
    init_db(engine)
    sf = build_session_factory(engine)
    session = sf()

    inv_repo   = InvoiceRepository(session)
    jnl_repo   = JournalRepository(session)
    asset_repo = AssetRepository(session)
    proj_repo  = ProjectRepository(session)
    ci_repo    = ClientInvoiceRepository(session)

    print("\n[1/6] Creating supplier invoices…")
    create_supplier_invoices(inv_repo, jnl_repo)

    print("\n[2/6] Creating CAPEX assets and depreciation entries…")
    assets = create_assets(asset_repo, jnl_repo)

    print("\n[3/6] Creating projects, phases and fiche mensuelle…")
    create_projects(proj_repo)

    print("\n[4/6] Creating asset-project allocations…")
    create_allocations(asset_repo, assets)

    print("\n[5/6] Creating client invoices to BIAT…")
    create_client_invoices(ci_repo)

    print("\n[6/6] Updating budget plan…")
    update_budget_plan()

    print_summary(inv_repo, jnl_repo, asset_repo, ci_repo)
    session.close()
    print("\n  Demo dataset ready.")
    print("  Run:  streamlit run app/Home.py")
    print()


if __name__ == "__main__":
    main()
