"""No-op ingestor for contexts where the agent is driven externally (Streamlit, scripts)."""
from __future__ import annotations

from src.ingestion.base import IngestorBase
from src.models.invoice import InvoiceRecord


class NullIngestor(IngestorBase):
    def start(self) -> None: pass
    def stop(self) -> None: pass
    def pop_next(self) -> InvoiceRecord | None: return None
    def enqueue(self, inv: InvoiceRecord) -> None: pass
