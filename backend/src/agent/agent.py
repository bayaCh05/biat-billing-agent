"""Standalone invoice processing daemon.

InvoiceAgent wraps the folder watcher and the pipeline into a single
event-driven loop. It is only needed for the headless daemon mode
(scripts/run_agent.py). The Streamlit app calls process_invoice() directly.

Design:
  - threading.Event for clean shutdown (no busy-sleep)
  - Single-threaded processing — Ollama is sequential, concurrency adds bugs
  - Crash recovery on startup via pipeline.recover_interrupted()
"""
from __future__ import annotations

import threading

from src.agent.pipeline import (
    PipelineComponents,
    process_invoice,
    re_enqueue_received,
    recover_interrupted,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class InvoiceAgent:
    """Watches the inbox and processes invoices one at a time."""

    def __init__(
        self,
        components: PipelineComponents,
        ingestor,
        poll_interval: float = 10.0,
        stuck_timeout_minutes: int = 30,
    ) -> None:
        self.components = components
        self.ingestor = ingestor
        self.poll_interval = poll_interval
        self.stuck_timeout_minutes = stuck_timeout_minutes
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the agent loop (blocks until stop() is called)."""
        recover_interrupted(self.components.repository)
        re_enqueue_received(self.components.repository, self.ingestor)
        self.ingestor.start()
        logger.info("agent_started", poll_interval=self.poll_interval)

        try:
            while not self._stop_event.is_set():
                invoice = self.ingestor.pop_next()
                if invoice:
                    process_invoice(invoice, self.components)
                else:
                    self._check_stuck_invoices()
                    self._stop_event.wait(timeout=self.poll_interval)
        finally:
            self.ingestor.stop()
            self.components.close()
            logger.info("agent_stopped")

    def _check_stuck_invoices(self) -> None:
        """Warn about invoices in transition states that have not moved in too long."""
        stuck = self.components.repository.get_stuck_invoices(self.stuck_timeout_minutes)
        for inv in stuck:
            logger.warning(
                "invoice_stuck",
                invoice_id=str(inv.id),
                status=inv.status.value,
                stuck_minutes=self.stuck_timeout_minutes,
                last_updated=inv.updated_at.isoformat() if inv.updated_at else None,
            )

    def stop(self) -> None:
        """Signal the agent to stop after the current invoice finishes."""
        self._stop_event.set()
