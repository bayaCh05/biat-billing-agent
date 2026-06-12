"""Génération de factures PDF (format A4, langue française).

Utilise fpdf2. La mise en page reproduit une facture commerciale tunisienne
standard avec : en-tête émetteur/client, tableau des lignes, total TVA/TTC,
conditions de règlement, et mentions légales.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from fpdf import FPDF

from src.models.client_invoice import ClientInvoice


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_amount(value: float) -> str:
    return f"{value:,.3f} TND".replace(",", " ")


def _fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _safe(text: str) -> str:
    """Encode to latin-1, replacing unsupported chars with ASCII equivalents."""
    replacements = {
        "’": "'",  # right single quotation mark
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "é": "\xe9",  # é  — already latin-1, no-op
        "è": "\xe8",
        "ê": "\xea",
        "ë": "\xeb",
        "à": "\xe0",
        "â": "\xe2",
        "ù": "\xf9",
        "û": "\xfb",
        "î": "\xee",
        "ô": "\xf4",
        "ç": "\xe7",
        "É": "\xc9",
        "À": "\xc0",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


# ── PDF layout ────────────────────────────────────────────────────────────────

class _InvoicePDF(FPDF):
    """Thin FPDF subclass for invoice styling."""

    BLUE   = (0,  51, 102)   # BIAT-style dark blue
    GRAY   = (80, 80, 80)
    LGRAY  = (200, 200, 200)
    WHITE  = (255, 255, 255)
    BLACK  = (0, 0, 0)

    def _h_line(self) -> None:
        self.set_draw_color(*self.LGRAY)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def _blue_rect(self, x: float, y: float, w: float, h: float) -> None:
        self.set_fill_color(*self.BLUE)
        self.rect(x, y, w, h, style="F")

    def _label(self, text: str, w: float = 50) -> None:
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.GRAY)
        self.cell(w, 5, _safe(text))

    def _value(self, text: str, w: float = 90, newline: bool = False) -> None:
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.BLACK)
        nx = "LMARGIN" if newline else "RIGHT"
        ny = "NEXT"    if newline else "TOP"
        self.cell(w, 5, _safe(text), new_x=nx, new_y=ny)


class PDFGenerator:
    """Génère un fichier PDF pour une ClientInvoice."""

    def __init__(self, output_dir: str | Path = "exports/invoices") -> None:
        self._output_dir = Path(output_dir)

    def generate(self, invoice: ClientInvoice) -> Path:
        """Générer le PDF et renvoyer son chemin absolu."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{invoice.invoice_number}.pdf"
        pdf  = self._build_pdf(invoice)
        pdf.output(str(path))
        return path

    def generate_to_bytes(self, invoice: ClientInvoice) -> bytes:
        """Générer le PDF en mémoire et renvoyer les bytes."""
        return bytes(self._build_pdf(invoice).output())

    # ── Internal build ────────────────────────────────────────────────────────

    def _build_pdf(self, invoice: ClientInvoice) -> _InvoicePDF:
        pdf = _InvoicePDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_margins(left=15, top=15, right=15)

        self._header_block(pdf, invoice)
        self._parties_block(pdf, invoice)
        self._line_items_table(pdf, invoice)
        self._totals_block(pdf, invoice)
        self._footer_block(pdf, invoice)

        return pdf

    # ── Section builders ──────────────────────────────────────────────────────

    def _header_block(self, pdf: _InvoicePDF, inv: ClientInvoice) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin

        # Left: issuer info
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*_InvoicePDF.BLUE)
        pdf.cell(page_w / 2, 8, _safe(inv.issuer_name))

        # Right: "FACTURE" title
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_InvoicePDF.BLUE)
        pdf.cell(page_w / 2, 8, "FACTURE", align="R", new_x="LMARGIN", new_y="NEXT")

        # Issuer address left, number/dates right
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_InvoicePDF.GRAY)
        pdf.multi_cell(page_w / 2, 4.5, _safe(inv.issuer_address), new_x="RIGHT", new_y="TOP")

        x_right = pdf.l_margin + page_w / 2
        y_meta  = pdf.l_margin - 5 + 14

        pdf.set_xy(x_right, y_meta)
        for label, value in [
            ("N°",       inv.invoice_number),
            ("Date",     _fmt_date(inv.invoice_date)),
            ("Échéance", _fmt_date(inv.due_date)),
        ]:
            pdf._label(label, 30)
            pdf._value(value, page_w / 2 - 30)
            pdf.ln(5)

        pdf.set_y(max(pdf.get_y(), y_meta + 18))
        pdf.ln(3)

        # MF issuer
        pdf.set_x(pdf.l_margin)
        pdf._label("MF :")
        pdf._value(inv.issuer_tax_id)
        pdf.ln(6)

        pdf._h_line()

    def _parties_block(self, pdf: _InvoicePDF, inv: ClientInvoice) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        y0     = pdf.get_y()

        # "Facturé à" label
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_InvoicePDF.GRAY)
        pdf.cell(page_w / 2, 5, "FACTUR\xc9 \xc0 :", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_InvoicePDF.BLACK)
        pdf.cell(page_w / 2, 6, _safe(inv.client_name), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_InvoicePDF.GRAY)
        if inv.client_address:
            pdf.multi_cell(page_w / 2, 4.5, _safe(inv.client_address),
                           new_x="LMARGIN", new_y="NEXT")
        pdf._label("MF : ")
        pdf._value(inv.client_tax_id, newline=True)
        pdf.ln(5)
        pdf._h_line()

    def _line_items_table(self, pdf: _InvoicePDF, inv: ClientInvoice) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin

        # Column widths
        col_desc = page_w * 0.48
        col_qty  = page_w * 0.10
        col_pu   = page_w * 0.18
        col_tva  = page_w * 0.10
        col_tot  = page_w * 0.14

        # Header row
        pdf.set_fill_color(*_InvoicePDF.BLUE)
        pdf.set_text_color(*_InvoicePDF.WHITE)
        pdf.set_font("Helvetica", "B", 8)
        row_h = 7

        for text, w, align in [
            ("Description",       col_desc, "L"),
            ("Qt\xe9",            col_qty,  "C"),
            ("P.U. HT (TND)",     col_pu,   "R"),
            ("TVA %",             col_tva,  "C"),
            ("Total HT (TND)",    col_tot,  "R"),
        ]:
            pdf.cell(w, row_h, text, border=0, fill=True, align=align)
        pdf.ln()

        # Data rows
        pdf.set_text_color(*_InvoicePDF.BLACK)
        for i, line in enumerate(inv.line_items):
            fill = (i % 2 == 0)
            pdf.set_fill_color(245, 247, 250) if fill else pdf.set_fill_color(*_InvoicePDF.WHITE)
            pdf.set_font("Helvetica", "", 8)

            # Description may be multiline — use multi_cell only for that column
            x_before = pdf.get_x()
            y_before = pdf.get_y()

            # Estimate height needed for description
            pdf.set_font("Helvetica", "", 8)
            n_lines  = max(1, len(pdf.multi_cell(
                col_desc, row_h, _safe(line.description),
                border=0, fill=fill, dry_run=True, output="LINES",
            )))
            cell_h   = row_h * n_lines

            pdf.set_xy(x_before, y_before)
            pdf.multi_cell(col_desc, row_h, _safe(line.description),
                           border=0, fill=fill, align="L", new_x="RIGHT", new_y="TOP")

            pdf.set_xy(x_before + col_desc, y_before)
            for val, w, align in [
                (f"{line.quantity:g}",                  col_qty,  "C"),
                (_fmt_amount(line.unit_price),           col_pu,   "R"),
                (f"{line.tva_rate:g}%",                 col_tva,  "C"),
                (_fmt_amount(line.line_total),           col_tot,  "R"),
            ]:
                pdf.cell(w, cell_h, val, border=0, fill=fill, align=align)
            pdf.ln(cell_h)

        pdf.ln(3)

    def _totals_block(self, pdf: _InvoicePDF, inv: ClientInvoice) -> None:
        page_w  = pdf.w - pdf.l_margin - pdf.r_margin
        label_w = 50
        val_w   = 40
        x_start = pdf.l_margin + page_w - label_w - val_w

        rows = [
            ("Montant HT",    _fmt_amount(inv.amount_ht)),
            (f"TVA ({inv.line_items[0].tva_rate:g}% sur HT)" if inv.line_items else "TVA",
             _fmt_amount(inv.tva_amount)),
        ]

        for label, value in rows:
            pdf.set_x(x_start)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_InvoicePDF.GRAY)
            pdf.cell(label_w, 6, label, align="R")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_InvoicePDF.BLACK)
            pdf.cell(val_w, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")

        # TTC highlighted
        pdf.set_x(x_start)
        pdf.set_fill_color(*_InvoicePDF.BLUE)
        pdf.set_text_color(*_InvoicePDF.WHITE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(label_w, 8, "Montant TTC", fill=True, align="R")
        pdf.cell(val_w,   8, _fmt_amount(inv.amount_ttc), fill=True, align="R",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(8)

    def _footer_block(self, pdf: _InvoicePDF, inv: ClientInvoice) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf._h_line()

        if inv.notes:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*_InvoicePDF.GRAY)
            pdf.multi_cell(page_w, 4.5, _safe(f"Notes : {inv.notes}"),
                           new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_InvoicePDF.GRAY)
        pdf.multi_cell(
            page_w, 4.5,
            _safe(
                f"Conditions de paiement : r\xe8glement par virement bancaire sous "
                f"{(inv.due_date - inv.invoice_date).days} jours. "
                f"Tout retard de paiement entrainera l'application de p\xe9nalit\xe9s "
                "de retard conform\xe9ment aux dispositions l\xe9gales en vigueur."
            ),
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.ln(2)
        pdf.set_font("Helvetica", "I", 7)
        pdf.cell(
            page_w, 4,
            _safe(f"Document g\xe9n\xe9r\xe9 le {_fmt_date(date.today())} — BIAT IT"),
            align="C",
        )
