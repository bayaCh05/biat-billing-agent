"""Export PDF d'un rapport d'audit périodique (AuditSnapshotDocument).

Consomme directement le dict retourné par
`sync_mongo_repository.get_audit_snapshot_by_id_sync()` (même forme que la
réponse JSON de `GET /audit-reports/{id}`) — pas de modèle Pydantic dédié,
cohérent avec `api/routers/audit_reports.py::get_audit_report()` qui renvoie
ce dict tel quel. Utilise fpdf2, même bibliothèque et conventions que
`billing/pdf_generator.py` (police Helvetica, encodage latin-1 via `_safe()`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fpdf import FPDF

_BLUE = (0, 51, 102)
_GRAY = (80, 80, 80)
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_RED = (192, 57, 27)
_AMBER = (176, 120, 0)
_GREEN = (29, 158, 118)

_SEVERITY_COLOR = {"CRITICAL": _RED, "WARNING": _AMBER, "INFO": _GRAY}

_DOMAIN_LABELS = {
    "invoices": "Factures",
    "journal": "Comptabilit\xe9",
    "budget": "Budget",
    "echeancier": "\xc9ch\xe9ancier",
    "risks": "Risques",
    "roadmap": "Roadmap",
}


def _safe(text: str) -> str:
    """Encode to latin-1, replacing unsupported chars with ASCII equivalents."""
    replacements = {
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-",
        "é": "\xe9", "è": "\xe8", "ê": "\xea", "ë": "\xeb",
        "à": "\xe0", "â": "\xe2", "ù": "\xf9", "û": "\xfb",
        "î": "\xee", "ô": "\xf4", "ç": "\xe7", "É": "\xc9", "À": "\xc0",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _fmt_dt(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return str(value)


def _fmt_date(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value)


class _ReportPDF(FPDF):
    def _h_line(self) -> None:
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)


class AuditReportPDFGenerator:
    """Génère un PDF récapitulatif pour un AuditSnapshotDocument."""

    def generate_to_bytes(self, snapshot: dict) -> bytes:
        pdf = self._build_pdf(snapshot)
        return bytes(pdf.output())

    def _build_pdf(self, snapshot: dict) -> _ReportPDF:
        pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_margins(left=15, top=15, right=15)

        self._header(pdf, snapshot)
        self._alerts(pdf, snapshot.get("alerts") or [])
        self._metrics(pdf, snapshot.get("metrics") or {})
        self._narrative(pdf, snapshot.get("narrative_summary"))
        self._footer(pdf)

        return pdf

    def _header(self, pdf: _ReportPDF, s: dict) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        granularity_label = {
            "DAILY": "QUOTIDIEN", "WEEKLY": "HEBDOMADAIRE", "MONTHLY": "MENSUEL",
        }.get(s.get("granularity", ""), s.get("granularity", ""))

        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(*_BLUE)
        pdf.cell(page_w, 8, _safe("RAPPORT D'AUDIT"), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_GRAY)
        pdf.cell(page_w, 6, _safe(
            f"P\xe9riode {granularity_label} : {_fmt_date(s.get('period_start'))} "
            f"au {_fmt_date(s.get('period_end'))}"
        ), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(page_w, 6, _safe(
            f"G\xe9n\xe9r\xe9 le {_fmt_dt(s.get('generated_at'))} — "
            f"statut : {s.get('status', '?')}"
        ), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        pdf._h_line()
        pdf.ln(2)

    def _alerts(self, pdf: _ReportPDF, alerts: list[dict]) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_BLACK)
        pdf.cell(page_w, 7, _safe(f"Alertes ({len(alerts)})"), new_x="LMARGIN", new_y="NEXT")

        if not alerts:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_GREEN)
            pdf.cell(page_w, 6, _safe("Aucune anomalie d\xe9tect\xe9e sur cette p\xe9riode."),
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
            return

        order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        for alert in sorted(alerts, key=lambda a: order.get(a.get("severity", "INFO"), 3)):
            color = _SEVERITY_COLOR.get(alert.get("severity", "INFO"), _GRAY)
            domain_label = _DOMAIN_LABELS.get(alert.get("domain", ""), alert.get("domain", ""))
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(*color)
            pdf.cell(6, 5, _safe("-"))
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(page_w - 6, 5, _safe(
                f"[{alert.get('severity', '?')}] [{domain_label}] {alert.get('message', '')}"
            ), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    def _metrics(self, pdf: _ReportPDF, metrics: dict) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_BLACK)
        pdf.cell(page_w, 7, _safe("D\xe9tail par domaine"), new_x="LMARGIN", new_y="NEXT")

        for domain, label in _DOMAIN_LABELS.items():
            values = metrics.get(domain)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(240, 244, 250)
            pdf.cell(page_w, 6, _safe(label), fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*_GRAY)
            if not values:
                pdf.cell(page_w, 5, _safe("Donn\xe9es indisponibles."), new_x="LMARGIN", new_y="NEXT")
            else:
                line = "  ".join(f"{k} : {v}" for k, v in values.items())
                pdf.multi_cell(page_w, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*_BLACK)
            pdf.ln(1)
        pdf.ln(2)

    def _narrative(self, pdf: _ReportPDF, narrative: str | None) -> None:
        if not narrative:
            return
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf._h_line()
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*_BLUE)
        pdf.cell(page_w, 7, _safe("Synth\xe8se"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_BLACK)
        pdf.multi_cell(page_w, 5, _safe(narrative), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    def _footer(self, pdf: _ReportPDF) -> None:
        page_w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf._h_line()
        pdf.set_font("Helvetica", "I", 7)
        pdf.set_text_color(*_GRAY)
        pdf.cell(page_w, 4, _safe(
            f"Document g\xe9n\xe9r\xe9 automatiquement le {_fmt_dt(datetime.now())} — BIAT IT"
        ), align="C")
