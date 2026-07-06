from abc import ABC, abstractmethod

from src.models.invoice import InvoiceRecord


class IngestorBase(ABC):
    @abstractmethod
    def start(self) -> None:
        """Start watching/polling the source for new files."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the ingestor cleanly."""

    @abstractmethod
    def pop_next(self) -> InvoiceRecord | None:
        """Return the next ingested invoice (or None if queue is empty)."""

    def enqueue(self, invoice: InvoiceRecord) -> None:
        """Re-queue an invoice recovered from the database on agent startup.

        Default is a no-op. Ingestors that maintain an internal queue should
        override this; re_enqueue_received() in pipeline.py calls it on startup.
        """
