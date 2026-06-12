from __future__ import annotations

import queue
import shutil
import time
from pathlib import Path
from uuid import uuid4

from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.ingestion.base import IngestorBase
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.utils.file_utils import is_supported, mime_type, sha256
from src.utils.logging import get_logger


class _FileHandler(FileSystemEventHandler):
    """Watchdog handler that forwards new files to FolderWatcher._process_file."""

    def __init__(self, watcher: FolderWatcher) -> None:
        self._watcher = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self._watcher._process_file(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        # Catches files drag-dropped or mv'd into the watched folder
        if not event.is_directory:
            self._watcher._process_file(Path(event.dest_path))


class FolderWatcher(IngestorBase):
    """
    Watches a local folder for new invoice files.

    Thread safety: _process_file is called from the watchdog background thread.
    It uses its own DB session (via session_factory) so it never shares a session
    with the InvoiceAgent's pipeline sessions.
    """

    def __init__(self, config: dict, session_factory) -> None:
        cfg = config["ingestion"]
        self.watch_path = Path(cfg["watch_path"])
        self.processed_path = Path(cfg["processed_path"])
        self.supported_formats: set[str] = set(cfg["supported_formats"])
        self._session_factory = session_factory
        self._queue: queue.Queue[InvoiceRecord] = queue.Queue()
        self._observer: Observer | None = None
        self._log = get_logger(__name__)

    # ── IngestorBase interface ─────────────────────────────────────────────────

    def start(self) -> None:
        self.watch_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)

        # Pick up any files that landed while the agent was offline
        self._scan_existing()

        handler = _FileHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_path), recursive=False)
        self._observer.start()
        self._log.info("folder_watcher_started", watch_path=str(self.watch_path))

    def stop(self) -> None:
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join()
        self._log.info("folder_watcher_stopped")

    def pop_next(self) -> InvoiceRecord | None:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def enqueue(self, invoice: InvoiceRecord) -> None:
        """Called by the orchestrator to re-queue DB-recovered invoices."""
        self._queue.put(invoice)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _scan_existing(self) -> None:
        """Process any files already sitting in the inbox on startup."""
        for path in sorted(self.watch_path.iterdir()):
            if path.is_file():
                self._process_file(path)

    def _process_file(self, file_path: Path) -> None:
        """Full ingestion pipeline for one file. Safe to call from any thread."""
        if not self._wait_stable(file_path):
            self._log.warning("file_unstable_or_gone", path=str(file_path))
            return

        if not is_supported(str(file_path), list(self.supported_formats)):
            self._log.debug(
                "skipped_unsupported_format",
                path=str(file_path),
                ext=file_path.suffix,
            )
            return

        try:
            file_hash = sha256(str(file_path))
        except OSError as exc:
            self._log.error("hash_failed", path=str(file_path), error=str(exc))
            return

        # Each call gets its own session so watchdog's thread never shares
        # the main thread's session.
        session = self._session_factory()
        try:
            from src.storage.repository import InvoiceRepository
            repo = InvoiceRepository(session)

            if repo.get_by_hash(file_hash) is not None:
                self._log.warning(
                    "duplicate_skipped",
                    path=str(file_path),
                    hash_prefix=file_hash[:16],
                )
                return

            detected_mime = self._detect_mime(str(file_path))
            processed_path = self._move_to_processed(file_path)

            invoice = InvoiceRecord(
                file_hash=file_hash,
                raw_file_path=str(processed_path),
                file_mime_type=detected_mime,
                status=InvoiceStatus.RECEIVED,
            )
            repo.save(invoice)
            self._queue.put(invoice)
            self._log.info(
                "invoice_ingested",
                invoice_id=str(invoice.id),
                path=str(processed_path),
                mime=detected_mime,
            )
        except Exception as exc:
            session.rollback()
            self._log.error("ingestion_failed", path=str(file_path), error=str(exc))
        finally:
            session.close()

    def _move_to_processed(self, file_path: Path) -> Path:
        dest = self.processed_path / file_path.name
        if dest.exists():
            dest = self.processed_path / f"{file_path.stem}_{uuid4().hex[:8]}{file_path.suffix}"
        shutil.move(str(file_path), str(dest))
        return dest

    @staticmethod
    def _detect_mime(file_path: str) -> str | None:
        try:
            return mime_type(file_path)
        except Exception:
            return None

    @staticmethod
    def _wait_stable(file_path: Path, timeout: float = 5.0) -> bool:
        """Block until file size stops changing (fully written) or timeout."""
        deadline = time.monotonic() + timeout
        last_size = -1
        while time.monotonic() < deadline:
            if not file_path.exists():
                return False
            try:
                current_size = file_path.stat().st_size
                if current_size > 0 and current_size == last_size:
                    return True
                last_size = current_size
                time.sleep(0.2)
            except OSError:
                return False
        return file_path.exists()
