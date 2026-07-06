"""Helper to generate test invoice PDFs using fpdf2."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF, XPos, YPos


def make_supplier_invoice_pdf(path: str | Path) -> Path:
    """Write a realistic French supplier invoice PDF and return the path."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    lines = [
        "FACTURE",
        "",
        "Fournisseur: Acme Solutions SARL",
        "Matricule Fiscal: 1234567A/M/P/000",
        "Adresse: 10 Rue de la Liberte, Tunis 1001",
        "",
        "Client: BIAT IT",
        "Matricule Fiscal: 9876543B/N/Q/001",
        "Adresse: Avenue Habib Bourguiba, Tunis",
        "",
        "Numero de facture: INV-2024-TEST-001",
        "Date de facture: 15/03/2024",
        "Date d'echeance: 15/04/2024",
        "",
        "Description                        Qte   Prix U.   Total HT",
        "Licence logiciel ERP annuelle       1    1000.00   1000.00",
        "Support et maintenance              1     500.00    500.00",
        "",
        "Montant HT:              1500.00 TND",
        "TVA (19%):                285.00 TND",
        "Montant TTC:             1785.00 TND",
        "",
        "Mode de paiement: Virement bancaire",
        "RIB: 08 006 0123456789 75",
    ]

    for line in lines:
        pdf.cell(0, 8, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    path = Path(path)
    pdf.output(str(path))
    return path


def make_client_invoice_pdf(path: str | Path) -> Path:
    """Write a client invoice (BIAT IT as issuer) and return the path."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    lines = [
        "FACTURE CLIENT",
        "",
        "Emetteur: BIAT IT",
        "Matricule Fiscal: 9876543B/N/Q/001",
        "",
        "Client: Tech Corp Tunisia",
        "Matricule Fiscal: 5556667C/M/P/002",
        "",
        "Numero de facture: CLI-2024-001",
        "Date de facture: 20/03/2024",
        "",
        "Prestation de service informatique: 3000.00 TND",
        "TVA (19%):                           570.00 TND",
        "Montant TTC:                        3570.00 TND",
    ]

    for line in lines:
        pdf.cell(0, 8, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    path = Path(path)
    pdf.output(str(path))
    return path
