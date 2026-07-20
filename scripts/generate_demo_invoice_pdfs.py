#!/usr/bin/env python3
"""Generate real PDF files for the supplier invoices seeded by seed_demo.py /
seed_budget_actuals.py.

Those two scripts create invoice records with a fake `raw_file_path`
(`/demo/{n}.pdf`, `seeds/budget/{catalog}_{month}.pdf`) that never pointed to
an actual file — "Voir PDF" in the frontend always 404'd for demo data. This
script renders one realistic-looking fpdf2 PDF per invoice (matching that
invoice's real issuer/amounts/line items) under `data/uploads/seed/{id}.pdf`
and updates `raw_file_path` in MongoDB to point at it.

Idempotent — skips any invoice whose raw_file_path already points to an
existing file (so it never touches real, uploaded invoices).

Usage (from project root, MONGODB_URI/MONGODB_DB set in .env):
    python scripts/generate_demo_invoice_pdfs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

# api.auth must be imported first — it loads .env (MONGODB_URI included).
import api.auth  # noqa: F401,E402
from fpdf import FPDF, XPos, YPos  # noqa: E402
from pymongo import MongoClient  # noqa: E402

OUT_DIR = ROOT / "data" / "uploads" / "seed"


def _money(v: float) -> str:
    s = f"{v:,.3f}".replace(",", " ").replace(".", ",")
    return f"{s} TND"


def _latin1(text: str) -> str:
    """Core Helvetica only supports latin-1 — swap common typographic chars."""
    return (
        text.replace("—", "-").replace("–", "-")
        .replace("’", "'").replace("‘", "'")
        .replace("“", '"').replace("”", '"')
        .encode("latin-1", errors="replace").decode("latin-1")
    )


def render_invoice_pdf(inv: dict, output_path: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    issuer = _latin1(inv.get("issuer_name") or "Fournisseur")
    issuer_tax_id = _latin1(inv.get("issuer_tax_id") or "N/A")
    recipient = _latin1(inv.get("recipient_name") or "BIAT IT")
    recipient_tax_id = _latin1(inv.get("recipient_tax_id") or "0000217V/A/M/000")

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, issuer, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, f"Matricule Fiscal: {issuer_tax_id}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "FACTURE", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, _latin1(f"Numero de facture: {inv.get('invoice_number') or '-'}"),
              align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(90, 6, "FOURNISSEUR", fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(10, 6, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(90, 6, "CLIENT", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", size=9)
    left = [issuer, f"MF: {issuer_tax_id}"]
    right = [recipient, f"MF: {recipient_tax_id}"]
    for l, r in zip(left, right):
        pdf.cell(90, 5, l, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(10, 5, "", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(90, 5, r, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(5)
    pdf.set_font("Helvetica", size=9)
    inv_date = inv.get("invoice_date")
    due_date = inv.get("due_date")
    pdf.cell(60, 6, f"Date de facture: {inv_date.strftime('%d/%m/%Y') if inv_date else '-'}",
              new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(60, 6, f"Date d'echeance: {due_date.strftime('%d/%m/%Y') if due_date else '-'}",
              new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(70, 6, "Devise: Dinar Tunisien (TND)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

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
    items = inv.get("line_items") or [{
        "description": inv.get("accounting_label") or "Prestation",
        "quantity": 1.0,
        "unit_price": inv.get("amount_ht") or 0.0,
        "tva_rate": inv.get("tva_rate") or 19.0,
        "line_total": inv.get("amount_ht") or 0.0,
    }]
    fill = False
    for it in items:
        desc = _latin1(str(it.get("description") or ""))[:55]
        qty = it.get("quantity") or 1.0
        unit = it.get("unit_price") or 0.0
        tva = it.get("tva_rate") or 19.0
        total = it.get("line_total") or (qty * unit)
        pdf.set_fill_color(248, 248, 248) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.cell(80, 6, desc, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(20, 6, f"{qty:g}", align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(30, 6, f"{unit:,.3f}", align="R", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(15, 6, f"{tva:.0f}%", align="C", fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 6, f"{total:,.3f}", align="R", fill=fill, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        fill = not fill

    pdf.ln(4)
    pdf.set_font("Helvetica", size=10)
    totals = [
        ("Montant HT:", _money(inv.get("amount_ht") or 0.0)),
        (f"TVA ({inv.get('tva_rate') or 19:.0f}%):", _money(inv.get("tva_amount") or 0.0)),
        ("Montant TTC:", _money(inv.get("amount_ttc") or 0.0)),
    ]
    for label, value in totals:
        pdf.set_font("Helvetica", "B" if "TTC" in label else "", 10)
        pdf.cell(140, 7, label, align="R", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(40, 7, value, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Modalites de paiement:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 5, "Virement bancaire - Paiement a 30 jours date de facture.",
              new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(8)
    pdf.set_text_color(150, 150, 150)
    pdf.set_font("Helvetica", "I", 7)
    pdf.cell(0, 5, "Document genere pour la demonstration - donnees synthetiques.",
              align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def main() -> None:
    client = MongoClient(os.environ["MONGODB_URI"])
    db = client[os.environ["MONGODB_DB"]]

    generated, skipped = 0, 0
    for inv in db["invoices"].find({}):
        existing = inv.get("raw_file_path")
        if existing and Path(existing).exists():
            skipped += 1
            continue
        out_path = OUT_DIR / f"{inv['_id']}.pdf"
        render_invoice_pdf(inv, out_path)
        db["invoices"].update_one(
            {"_id": inv["_id"]},
            {"$set": {"raw_file_path": str(out_path), "file_mime_type": "application/pdf"}},
        )
        generated += 1

    print(f"✓ {generated} PDF générés, {skipped} factures ignorées (fichier déjà présent).")


if __name__ == "__main__":
    main()
