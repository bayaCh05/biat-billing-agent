"""Generate a set of diverse mock invoices covering different cost catalog categories.

Usage:
    python scripts/make_mock_invoices.py          # writes to ./inbox/
    python scripts/make_mock_invoices.py ./mydir  # custom output dir
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fpdf import FPDF, XPos, YPos


# ── Invoice templates ─────────────────────────────────────────────────────────

INVOICES = [
    {
        "filename": "facture_steg_mai2026.pdf",
        "supplier": {
            "name": "STEG - Société Tunisienne de l'Electricité et du Gaz",
            "address": "38 Rue Kemal Ataturk - 1080 Tunis, Tunisie",
            "mf": "0000001A/A/M/000",
        },
        "number": "STEG-2026-05-00847",
        "date": "31/05/2026",
        "due": "30/06/2026",
        "items": [
            ("Consommation électricité Mai 2026 - Compteur 047821", 1, 1840.500, 19.0),
            ("Taxe de distribution énergie", 1, 95.000, 0.0),
        ],
        "ht": 1935.500,
        "tva": 349.695,
        "ttc": 2285.195,
    },
    {
        "filename": "facture_loyer_juin2026.pdf",
        "supplier": {
            "name": "IMMOBILIERE DU LAC SARL",
            "address": "Les Berges du Lac II - 1053 Tunis, Tunisie",
            "mf": "1234567B/A/M/000",
        },
        "number": "IL-2026-06-0124",
        "date": "01/06/2026",
        "due": "05/06/2026",
        "items": [
            ("Loyer mensuel bureaux - Juin 2026 - Plateau 3ème étage 450m²", 1, 8500.000, 0.0),
            ("Charges communes immeuble Juin 2026", 1, 620.000, 0.0),
        ],
        "ht": 9120.000,
        "tva": 0.000,
        "ttc": 9120.000,
    },
    {
        "filename": "facture_maintenance_informatique.pdf",
        "supplier": {
            "name": "NEXIA INFORMATIQUE SARL",
            "address": "Zone Industrielle Charguia II - 2035 Tunis, Tunisie",
            "mf": "9876543C/A/M/000",
        },
        "number": "NX-2026-0589",
        "date": "28/05/2026",
        "due": "27/06/2026",
        "items": [
            ("Contrat TMA - Tierce Maintenance Applicative - Mai 2026", 1, 4200.000, 19.0),
            ("Support technique infrastructure réseau - 12h intervention", 12, 180.000, 19.0),
            ("Maintenance préventive serveurs datacenter", 1, 850.000, 19.0),
        ],
        "ht": 7210.000,
        "tva": 1369.900,
        "ttc": 8579.900,
    },
    {
        "filename": "facture_telecom_ooredoo.pdf",
        "supplier": {
            "name": "OOREDOO TUNISIE SA",
            "address": "Centre Urbain Nord - 1080 Tunis, Tunisie",
            "mf": "0002847F/A/M/000",
        },
        "number": "OOR-B2B-2026-05-10293",
        "date": "31/05/2026",
        "due": "30/06/2026",
        "items": [
            ("Abonnement fibre optique 1 Gbps symétrique - Mai 2026", 1, 1200.000, 19.0),
            ("Forfait téléphonie mobile entreprise 20 lignes - Mai 2026", 20, 45.000, 19.0),
            ("Bande passante supplémentaire - pic charge datacenter", 1, 320.000, 19.0),
        ],
        "ht": 2420.000,
        "tva": 459.800,
        "ttc": 2879.800,
    },
    {
        "filename": "facture_formation_aws.pdf",
        "supplier": {
            "name": "GLOBAL TECH TRAINING SARL",
            "address": "Avenue Mohamed V - 1002 Tunis, Tunisie",
            "mf": "4561237D/A/M/000",
        },
        "number": "GTT-2026-0341",
        "date": "15/05/2026",
        "due": "14/06/2026",
        "items": [
            ("Formation AWS Solutions Architect - 5 jours - 3 participants", 3, 1850.000, 19.0),
            ("Support pédagogique et certification AWS (vouchers)", 3, 420.000, 19.0),
        ],
        "ht": 6810.000,
        "tva": 1293.900,
        "ttc": 8103.900,
    },
    {
        "filename": "facture_licences_microsoft.pdf",
        "supplier": {
            "name": "SOTETEL - Partenaire Microsoft Tunisie",
            "address": "Centre Urbain Nord - Immeuble Sotetel - 1082 Tunis",
            "mf": "0034512G/A/M/000",
        },
        "number": "SOT-2026-LIC-0089",
        "date": "01/06/2026",
        "due": "01/07/2026",
        "items": [
            ("Microsoft 365 Business Premium - 120 licences - renouvellement annuel", 120, 185.000, 19.0),
            ("Azure Active Directory P2 - 120 licences", 120, 62.000, 19.0),
            ("Microsoft Defender for Endpoint Plan 2 - 120 licences", 120, 48.000, 19.0),
        ],
        "ht": 35400.000,
        "tva": 6726.000,
        "ttc": 42126.000,
    },
    {
        "filename": "facture_gardiennage_mai.pdf",
        "supplier": {
            "name": "SECURITAS TUNISIE SA",
            "address": "Zone d'Activité Économique La Soukra - 2036 Ariana",
            "mf": "0123456H/A/M/000",
        },
        "number": "SEC-2026-05-2847",
        "date": "31/05/2026",
        "due": "30/06/2026",
        "items": [
            ("Prestation gardiennage et surveillance - Mai 2026 - 2 agents 24h/24", 2, 1650.000, 19.0),
            ("Ronde nocturne supplémentaire weekend (8 rondes)", 8, 120.000, 19.0),
        ],
        "ht": 4260.000,
        "tva": 809.400,
        "ttc": 5069.400,
    },
    {
        "filename": "facture_fournitures_bureau.pdf",
        "supplier": {
            "name": "PAPETERIE DU CENTRE SARL",
            "address": "Avenue de Carthage - 1000 Tunis, Tunisie",
            "mf": "7891234I/A/M/000",
        },
        "number": "PDC-2026-04-0672",
        "date": "20/04/2026",
        "due": "20/05/2026",
        "items": [
            ("Ramettes papier A4 80g - 5 cartons (50 ramettes)", 50, 8.500, 19.0),
            ("Stylos bille BIC bleu - 10 boîtes", 10, 12.000, 19.0),
            ("Classeurs A4 dos 8cm - 2 cartons (40 classeurs)", 40, 4.200, 19.0),
            ("Chemises plastiques transparentes A4 - 500 unités", 500, 0.350, 19.0),
        ],
        "ht": 818.000,
        "tva": 155.420,
        "ttc": 973.420,
    },
    {
        "filename": "facture_honoraires_audit.pdf",
        "supplier": {
            "name": "KPMG TUNISIE",
            "address": "Immeuble Le Dôme - Avenue du Japon - 1073 Tunis",
            "mf": "0098765J/A/M/000",
        },
        "number": "KPMG-2026-IT-0047",
        "date": "10/05/2026",
        "due": "09/06/2026",
        "items": [
            ("Audit sécurité système d'information - Phase 1 diagnostic", 1, 12000.000, 19.0),
            ("Rapport de conformité RGPD et recommandations", 1, 4500.000, 19.0),
        ],
        "ht": 16500.000,
        "tva": 3135.000,
        "ttc": 19635.000,
    },
    {
        "filename": "facture_assurance_multirisques.pdf",
        "supplier": {
            "name": "STAR ASSURANCES SA",
            "address": "53 Avenue Habib Bourguiba - 1000 Tunis, Tunisie",
            "mf": "0001234K/A/M/000",
        },
        "number": "STAR-2026-MR-00341",
        "date": "01/01/2026",
        "due": "31/01/2026",
        "items": [
            ("Prime assurance multirisques bureaux et matériels IT - 2026", 1, 7200.000, 0.0),
            ("Garantie dommages électriques matériel informatique", 1, 1800.000, 0.0),
        ],
        "ht": 9000.000,
        "tva": 0.000,
        "ttc": 9000.000,
    },
]

CLIENT = {
    "name": "BIAT IT - Banque Internationale Arabe de Tunisie",
    "address": "70-72 Avenue Habib Bourguiba - 1000 Tunis, Tunisie",
    "mf": "0000217V/A/M/000",
}


# ── PDF builder ───────────────────────────────────────────────────────────────

def make_invoice(inv: dict, output_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    sup = inv["supplier"]

    # Supplier header
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, sup["name"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, sup["address"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, f"Matricule Fiscal: {sup['mf']}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Invoice title
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 11, "FACTURE", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, f"N° {inv['number']}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Two columns: supplier / client
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(235, 235, 235)
    pdf.cell(90, 6, "FOURNISSEUR", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(10, 6, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(90, 6, "CLIENT", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=9)
    left_lines = [sup["name"], sup["address"], f"MF: {sup['mf']}"]
    right_lines = [CLIENT["name"], CLIENT["address"], f"MF: {CLIENT['mf']}"]
    for l, r in zip(left_lines, right_lines):
        pdf.cell(90, 5, l, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(10, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(90, 5, r, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Dates
    pdf.ln(4)
    pdf.cell(65, 6, f"Date de facture: {inv['date']}")
    pdf.cell(65, 6, f"Date d'échéance: {inv['due']}")
    pdf.cell(60, 6, "Devise: Dinar Tunisien (TND)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Table header
    pdf.set_fill_color(25, 90, 160)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(85, 7, "Description", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(18, 7, "Qté", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(28, 7, "P.U. HT", align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(14, 7, "TVA%", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(35, 7, "Total HT", align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Table rows
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=9)
    alt = False
    for desc, qty, unit, tva in inv["items"]:
        pdf.set_fill_color(248, 248, 248) if alt else pdf.set_fill_color(255, 255, 255)
        total = qty * unit
        pdf.cell(85, 6, desc[:60], fill=alt, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(18, 6, str(qty), align="C", fill=alt, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(28, 6, f"{unit:,.3f}", align="R", fill=alt, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(14, 6, f"{tva:.0f}%", align="C", fill=alt, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 6, f"{total:,.3f}", align="R", fill=alt, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        alt = not alt

    # Totals
    pdf.ln(4)
    for label, value in [
        ("Total HT:", f"{inv['ht']:,.3f} TND"),
        (f"TVA ({int(inv['tva'] / inv['ht'] * 100) if inv['ht'] else 0}%):", f"{inv['tva']:,.3f} TND"),
        ("TOTAL TTC:", f"{inv['ttc']:,.3f} TND"),
    ]:
        bold = "TTC" in label
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.cell(145, 7, label, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 7, value, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Footer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"{sup['name']} - MF: {sup['mf']} - Paiement a 30 jours", align="C",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./inbox")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating {len(INVOICES)} mock invoices → {out_dir}/\n")
    for inv in INVOICES:
        path = out_dir / inv["filename"]
        make_invoice(inv, path)
        print(f"  ✓  {inv['filename']:<45}  {inv['ttc']:>10,.3f} TND  ({inv['supplier']['name'][:35]})")

    print(f"\nDone. Drop {out_dir}/ files through the pipeline:")
    print(f"  python scripts/run_agent.py")
