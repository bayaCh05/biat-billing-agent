import json
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from src.models.invoice import InvoiceRecord
from src.storage.exporters.base import ExporterBase


def _default_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class JSONExporter(ExporterBase):
    """Exports each validated invoice as an individual JSON file."""

    def __init__(self, export_path: str) -> None:
        self.export_dir = Path(export_path)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export(self, invoice: InvoiceRecord) -> str:
        number_slug = (
            invoice.invoice_number.value.replace("/", "-").replace(" ", "_")
            if invoice.invoice_number.value
            else "unknown"
        )
        date_slug = (
            invoice.invoice_date.value.strftime("%Y%m%d")
            if invoice.invoice_date.value
            else "nodate"
        )
        filename = f"{invoice.id}_{number_slug}_{date_slug}.json"
        file_path = self.export_dir / filename

        payload = invoice.model_dump(mode="json")
        file_path.write_text(
            json.dumps(payload, indent=2, default=_default_serializer, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(file_path)
