from abc import ABC, abstractmethod

from src.models.invoice import InvoiceRecord


class ExtractorBase(ABC):
    @abstractmethod
    def extract(self, invoice: InvoiceRecord) -> InvoiceRecord:
        """Populate invoice extracted fields. Returns the mutated invoice."""
