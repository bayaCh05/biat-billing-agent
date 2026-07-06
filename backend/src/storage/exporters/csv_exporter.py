import csv
from datetime import datetime, timezone
from pathlib import Path

from src.models.invoice import InvoiceRecord
from src.storage.exporters.base import ExporterBase

# Flat columns written to CSV (one row per invoice, no nested objects).
# Line items and flags are excluded — they go to the JSON export.
CSV_COLUMNS = [
    "id", "direction", "status",
    "invoice_number", "invoice_number_conf",
    "invoice_date", "invoice_date_conf",
    "due_date", "due_date_conf",
    "issuer_name", "issuer_name_conf",
    "issuer_tax_id", "issuer_tax_id_conf",
    "recipient_name", "recipient_name_conf",
    "recipient_tax_id", "recipient_tax_id_conf",
    "amount_ht", "amount_ht_conf",
    "tva_rate", "tva_rate_conf",
    "tva_amount", "tva_amount_conf",
    "amount_ttc", "amount_ttc_conf",
    "currency",
    "cost_catalog_id", "accounting_compte", "accounting_label",
    "charge_nature", "charge_type",
    "matched_po_id",
    "human_review_required",
    "received_at", "extracted_at", "validated_at", "exported_at",
    "paid_at", "collected_at",
    "export_reference",
]


class CSVExporter(ExporterBase):
    """Appends validated invoices to a monthly rolling CSV file."""

    def __init__(self, export_path: str) -> None:
        self.export_dir = Path(export_path)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export(self, invoice: InvoiceRecord) -> str:
        month_slug = datetime.now(tz=timezone.utc).strftime("%Y_%m")
        file_path = self.export_dir / f"invoices_{month_slug}.csv"
        write_header = not file_path.exists()

        row = self._flatten(invoice)
        with file_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        return str(file_path)

    def _flatten(self, invoice: InvoiceRecord) -> dict:
        row: dict = {
            "id": str(invoice.id),
            "direction": invoice.direction.value,
            "status": invoice.status.value,
            "currency": invoice.currency,
            "cost_catalog_id": invoice.cost_catalog_id,
            "accounting_compte": invoice.accounting_compte,
            "accounting_label": invoice.accounting_label,
            "charge_nature": invoice.charge_nature.value if invoice.charge_nature else None,
            "charge_type": invoice.charge_type.value if invoice.charge_type else None,
            "matched_po_id": invoice.matched_po_id,
            "human_review_required": invoice.human_review_required,
            "received_at": invoice.received_at.isoformat() if invoice.received_at else None,
            "extracted_at": invoice.extracted_at.isoformat() if invoice.extracted_at else None,
            "validated_at": invoice.validated_at.isoformat() if invoice.validated_at else None,
            "exported_at": invoice.exported_at.isoformat() if invoice.exported_at else None,
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "collected_at": invoice.collected_at.isoformat() if invoice.collected_at else None,
            "export_reference": invoice.export_reference,
        }
        # Unpack ConfidenceField objects
        for field_name in [
            "invoice_number", "invoice_date", "due_date",
            "issuer_name", "issuer_tax_id",
            "recipient_name", "recipient_tax_id",
            "amount_ht", "tva_rate", "tva_amount", "amount_ttc",
        ]:
            cf = getattr(invoice, field_name)
            value = cf.value
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            row[field_name] = value
            row[f"{field_name}_conf"] = round(cf.confidence, 4) if cf.value is not None else None
        return row
