"""Generate 10 varied supplier invoice PDFs covering 5 cost categories."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fpdf import FPDF, XPos, YPos


VENDORS = [
    # (vendor_name, mf, address, service_desc, qty, unit_price, tva_rate, catalog_hint)
    (
        "OOREDOO TUNISIE SA",
        "0038472K/A/M/000",
        "Rue du Lac Biwa, Les Berges du Lac 1053 Tunis",
        [
            ("Abonnement fibre optique entreprise 1 Gbps - Juin 2026", 1, 2800.0, 19.0),
            ("Lignes mobiles professionnelles x20 - Juin 2026",        1,  950.0, 19.0),
        ],
        "telecommunications",
    ),
    (
        "OOREDOO TUNISIE SA",
        "0038472K/A/M/000",
        "Rue du Lac Biwa, Les Berges du Lac 1053 Tunis",
        [
            ("Abonnement internet haut debit ADSL - Mai 2026",         1, 1850.0, 19.0),
            ("Telephonie fixe et mobile entreprise - Mai 2026",        1,  720.0, 19.0),
        ],
        "telecommunications",
    ),
    (
        "STEG - Societe Tunisienne de l'Electricite et du Gaz",
        "0000045A/P/M/000",
        "38 Rue Kemal Ataturk 1000 Tunis",
        [
            ("Consommation electrique Data Center - Juin 2026",        1, 8400.0, 19.0),
            ("Consommation electrique Bureaux Siege - Juin 2026",      1, 3200.0, 19.0),
        ],
        "electricite_steg",
    ),
    (
        "STEG - Societe Tunisienne de l'Electricite et du Gaz",
        "0000045A/P/M/000",
        "38 Rue Kemal Ataturk 1000 Tunis",
        [
            ("Electricite Agence Sfax - Mai 2026",                     1, 1950.0, 19.0),
            ("Electricite Agence Sousse - Mai 2026",                   1, 1650.0, 19.0),
        ],
        "electricite_steg",
    ),
    (
        "CIEL FORMATION SARL",
        "1234567C/A/M/000",
        "Centre Urbain Nord 1082 Tunis",
        [
            ("Formation Cybersecurite SI bancaire (5 jours x 8 agents)", 40, 420.0, 19.0),
        ],
        "formation_personnel",
    ),
    (
        "CIEL FORMATION SARL",
        "1234567C/A/M/000",
        "Centre Urbain Nord 1082 Tunis",
        [
            ("Certification ISO 27001 Lead Implementer x3 agents",    3, 2800.0, 19.0),
            ("Formation Cloud Computing AWS (3 jours)",               6,  650.0, 19.0),
        ],
        "formation_personnel",
    ),
    (
        "TECHNOVA SOLUTIONS SARL",
        "1472583D/A/M/000",
        "Zone Industrielle El Agba 1000 Tunis",
        [
            ("Maintenance preventive serveurs Dell PowerEdge - Juin 2026", 1, 6500.0, 19.0),
            ("Support technique niveau 2 (forfait mensuel)",              1, 3800.0, 19.0),
            ("Remplacement disques SSD baie NAS",                         4,  420.0, 19.0),
        ],
        "maintenance_informatique",
    ),
    (
        "TECHNOVA SOLUTIONS SARL",
        "1472583D/A/M/000",
        "Zone Industrielle El Agba 1000 Tunis",
        [
            ("Maintenance reseau LAN/WAN et switches - T2 2026",      1, 4200.0, 19.0),
            ("Mise a jour firewall et configuration VPN",              1, 2900.0, 19.0),
        ],
        "maintenance_informatique",
    ),
    (
        "MICROSOFT TUNISIE SARL",
        "9876543B/A/M/000",
        "Immeuble Iris, Lac 2 Berges du Lac 1053 Tunis",
        [
            ("Licences Microsoft 365 Business Premium x150 (annuel)", 150, 320.0, 19.0),
        ],
        "licences_saas",
    ),
    (
        "MICROSOFT TUNISIE SARL",
        "9876543B/A/M/000",
        "Immeuble Iris, Lac 2 Berges du Lac 1053 Tunis",
        [
            ("Abonnement Azure DevOps Enterprise x10 developpeurs",   10, 480.0, 19.0),
            ("Licences Windows Server 2025 Datacenter x4",             4, 8500.0, 19.0),
        ],
        "licences_saas",
    ),
]


def _make_invoice(
    output_path: str,
    vendor: str, mf: str, address: str,
    items: list[tuple[str, int, float, float]],
    inv_number: str, inv_date: str, due_date: str,
) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, vendor, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, address, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, f"Matricule Fiscal: {mf}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Title
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "FACTURE", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, f"Numero: {inv_number}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Supplier / client columns
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 6, "FOURNISSEUR", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(10, 6, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(90, 6, "CLIENT", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    left = [vendor, address, f"MF: {mf}"]
    right = [
        "BIAT IT - Banque Internationale Arabe de Tunisie",
        "70-72 Avenue Habib Bourguiba 1000 Tunis",
        "MF: 0000217V/A/M/000",
    ]
    for l, r in zip(left, right):
        pdf.cell(90, 5, l, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(10, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(90, 5, r, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Dates
    pdf.ln(4)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(70, 6, f"Date de facture: {inv_date}", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(70, 6, f"Date d'echeance: {due_date}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Line items header
    pdf.set_fill_color(30, 100, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(80, 7, "Description", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(20, 7, "Qte", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(30, 7, "PU HT", align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(15, 7, "TVA%", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(35, 7, "Montant HT", align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=9)
    total_ht = 0.0
    tva_rate_first = 19.0
    fill = False
    for desc, qty, unit, tva in items:
        line_ht = round(qty * unit, 3)
        total_ht += line_ht
        tva_rate_first = tva
        bg = (248, 248, 248) if fill else (255, 255, 255)
        pdf.set_fill_color(*bg)
        pdf.cell(80, 6, desc[:55], fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(20, 6, str(qty), align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 6, f"{unit:,.3f}", align="R", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(15, 6, f"{tva:.0f}%", align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 6, f"{line_ht:,.3f}", align="R", fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill

    # Totals
    tva_amount = round(total_ht * tva_rate_first / 100, 3)
    ttc = round(total_ht + tva_amount, 3)
    pdf.ln(4)
    for label, value in [
        ("Montant HT:",   f"{total_ht:,.3f} TND"),
        (f"TVA ({tva_rate_first:.0f}%):", f"{tva_amount:,.3f} TND"),
        ("Montant TTC:",  f"{ttc:,.3f} TND"),
    ]:
        pdf.set_font("Helvetica", "B" if "TTC" in label else "", 10)
        pdf.cell(140, 7, label, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 7, value, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Footer
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"{vendor} - MF: {mf} - Devise: Dinar Tunisien (TND)",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, "Paiement a 30 jours. Virement bancaire uniquement.",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    return output_path


DATES = [
    ("15/01/2026", "14/02/2026", "FAC-2026-01"),
    ("10/02/2026", "12/03/2026", "FAC-2026-02"),
    ("05/03/2026", "04/04/2026", "FAC-2026-03"),
    ("18/03/2026", "17/04/2026", "FAC-2026-04"),
    ("02/04/2026", "02/05/2026", "FAC-2026-05"),
    ("14/04/2026", "14/05/2026", "FAC-2026-06"),
    ("03/05/2026", "02/06/2026", "FAC-2026-07"),
    ("20/05/2026", "19/06/2026", "FAC-2026-08"),
    ("01/06/2026", "01/07/2026", "FAC-2026-09"),
    ("10/06/2026", "10/07/2026", "FAC-2026-10"),
]

if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./inbox")
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, (vendor, mf, address, items, _) in enumerate(VENDORS):
        inv_date, due_date, inv_num = DATES[i]
        slug = vendor.split()[0].lower()
        out = out_dir / f"invoice_{i+1:02d}_{slug}.pdf"
        path = _make_invoice(
            str(out), vendor, mf, address, items,
            inv_number=f"{inv_num}-{slug.upper()}",
            inv_date=inv_date,
            due_date=due_date,
        )
        print(f"[{i+1:2d}/10] {path}")

    print("\nDone. Drop these PDFs into the Streamlit upload or watch folder.")
