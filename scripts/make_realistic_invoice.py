"""Generate a realistic-looking Tunisian supplier invoice PDF for demo purposes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fpdf import FPDF, XPos, YPos


def make_invoice(output_path: str = "./data/demo_invoice.pdf") -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ── Header: supplier info ─────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "TECHNOVA SOLUTIONS SARL", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(80, 80, 80)
    for line in [
        "Zone Industrielle El Agba - 1000 Tunis, Tunisie",
        "Tel: +216 71 000 000   |   Email: contact@technova.tn",
        "Matricule Fiscal: 1472583D/A/M/000",
        "RC: B 123456789   |   IBAN: TN59 1000 6035 1835 9840 1652",
    ]:
        pdf.cell(0, 5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Invoice title + number ────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "FACTURE", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, "Numero de facture: FAC-2024-0147", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # ── Two-column: supplier left, client right ───────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 6, "FOURNISSEUR", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(10, 6, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(90, 6, "CLIENT", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=9)
    left = [
        "TECHNOVA SOLUTIONS SARL",
        "Zone Industrielle El Agba",
        "1000 Tunis, Tunisie",
        "MF: 1472583D/A/M/000",
    ]
    right = [
        "BIAT - Banque Internationale Arabe de Tunisie",
        "70-72 Avenue Habib Bourguiba",
        "1000 Tunis, Tunisie",
        "MF: 0000217V/A/M/000",
    ]
    for l, r in zip(left, right):
        pdf.cell(90, 5, l, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(10, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(90, 5, r, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Dates ─────────────────────────────────────────────────────────────────
    pdf.ln(5)
    pdf.set_font("Helvetica", size=9)
    pdf.cell(60, 6, "Date de facture: 20/05/2024", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(60, 6, "Date d'echeance: 19/06/2024", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(70, 6, "Devise: Dinar Tunisien (TND)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    # ── Line items table ──────────────────────────────────────────────────────
    pdf.set_fill_color(30, 100, 180)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(80, 7, "Description", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(20, 7, "Qte", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(30, 7, "Prix Unit. HT", align="R", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(15, 7, "TVA%", align="C", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(35, 7, "Montant HT", align="R", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=9)
    items = [
        ("Developpement application mobile (iOS/Android)", 1, 8500.000, 19.0, 8500.000),
        ("Integration API bancaire BIAT",                  1, 3200.000, 19.0, 3200.000),
        ("Formation equipe IT (3 jours)",                  3,  650.000, 19.0, 1950.000),
        ("Support technique mensuel (Mai 2024)",           1,  850.000, 19.0,  850.000),
    ]
    fill = False
    for desc, qty, unit, tva, total in items:
        pdf.set_fill_color(248, 248, 248) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(80, 6, desc, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(20, 6, str(qty), align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 6, f"{unit:,.3f}", align="R", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(15, 6, f"{tva:.0f}%", align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 6, f"{total:,.3f}", align="R", fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill

    # ── Totals ────────────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("Helvetica", size=10)
    totals = [
        ("Montant HT:",        "14 500,000 TND"),
        ("TVA (19%):",          "2 755,000 TND"),
        ("Montant TTC:",       "17 255,000 TND"),
    ]
    for label, value in totals:
        pdf.set_font("Helvetica", "B" if "TTC" in label else "", 10)
        pdf.cell(140, 7, label, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 7, value, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Payment info ──────────────────────────────────────────────────────────
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Modalites de paiement:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(60, 60, 60)
    for line in [
        "Virement bancaire - IBAN: TN59 1000 6035 1835 9840 1652",
        "Paiement a 30 jours date de facture.",
        "Tout retard de paiement entrainera des penalites de 1,5% par mois.",
    ]:
        pdf.cell(0, 5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.ln(8)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5,
             "TECHNOVA SOLUTIONS SARL - Capital: 50 000 TND - RNE: 1472583D - TVA: 1472583D/A/M/000",
             align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    print(f"Invoice written to: {output_path}")
    return output_path


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "./data/demo_invoice.pdf"
    make_invoice(path)
