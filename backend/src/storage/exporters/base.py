from abc import ABC, abstractmethod

from src.models.invoice import InvoiceRecord


class ExporterBase(ABC):
    @abstractmethod
    def export(self, invoice: InvoiceRecord) -> str:
        """Export the invoice. Returns a reference string (file path, record ID, etc.)."""
