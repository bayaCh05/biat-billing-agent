"""
Tests for the ingestion module (FolderWatcher).

Strategy: call _process_file() and _scan_existing() directly without starting
the watchdog observer, so tests are fast and don't need real filesystem events.
Each test gets a fresh in-memory SQLite DB and real temp directories.
"""

from pathlib import Path

import pytest

from src.ingestion.folder_watcher import FolderWatcher
from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.repository import InvoiceRepository


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    factory = build_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def config(tmp_path):
    return {
        "ingestion": {
            "watch_path": str(tmp_path / "inbox"),
            "processed_path": str(tmp_path / "processed"),
            "supported_formats": ["pdf", "png", "jpg", "jpeg", "tiff"],
            "poll_interval_seconds": 10,
        }
    }


@pytest.fixture()
def watcher(config, session_factory):
    return FolderWatcher(config=config, session_factory=session_factory)


@pytest.fixture()
def inbox(config):
    p = Path(config["ingestion"]["watch_path"])
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture()
def processed(config):
    p = Path(config["ingestion"]["processed_path"])
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_file(folder: Path, name: str, content: bytes = b"fake invoice pdf content") -> Path:
    p = folder / name
    p.write_bytes(content)
    return p


# ── Core processing tests ──────────────────────────────────────────────────────

class TestProcessFile:

    def test_queues_invoice_for_supported_file(self, watcher, inbox, processed):
        pdf = write_file(inbox, "invoice.pdf")
        watcher._process_file(pdf)
        result = watcher.pop_next()
        assert result is not None
        assert result.status == InvoiceStatus.RECEIVED

    def test_file_hash_is_populated(self, watcher, inbox, processed):
        pdf = write_file(inbox, "invoice.pdf")
        watcher._process_file(pdf)
        inv = watcher.pop_next()
        assert len(inv.file_hash) == 64  # SHA-256 hex

    def test_raw_file_path_points_to_processed_folder(self, watcher, inbox, processed):
        pdf = write_file(inbox, "invoice.pdf")
        watcher._process_file(pdf)
        inv = watcher.pop_next()
        assert str(processed) in inv.raw_file_path
        assert Path(inv.raw_file_path).exists()

    def test_file_is_moved_out_of_inbox(self, watcher, inbox, processed):
        pdf = write_file(inbox, "invoice.pdf")
        watcher._process_file(pdf)
        assert not pdf.exists()
        assert (processed / "invoice.pdf").exists()

    def test_invoice_saved_to_db(self, watcher, inbox, processed, session_factory):
        pdf = write_file(inbox, "invoice.pdf")
        watcher._process_file(pdf)
        inv = watcher.pop_next()

        # Verify via a fresh session
        session = session_factory()
        repo = InvoiceRepository(session)
        loaded = repo.get_by_id(inv.id)
        session.close()

        assert loaded is not None
        assert loaded.file_hash == inv.file_hash

    def test_unsupported_format_is_skipped(self, watcher, inbox, processed):
        txt = write_file(inbox, "notes.txt")
        watcher._process_file(txt)
        assert watcher.pop_next() is None

    def test_unsupported_file_stays_in_inbox(self, watcher, inbox, processed):
        txt = write_file(inbox, "notes.txt")
        watcher._process_file(txt)
        assert txt.exists()  # not touched

    def test_pop_next_returns_none_when_empty(self, watcher):
        assert watcher.pop_next() is None

    def test_different_content_produces_different_hashes(self, watcher, inbox, processed):
        pdf_a = write_file(inbox, "a.pdf", content=b"invoice A content")
        pdf_b = write_file(inbox, "b.pdf", content=b"invoice B content")
        watcher._process_file(pdf_a)
        watcher._process_file(pdf_b)
        inv_a = watcher.pop_next()
        inv_b = watcher.pop_next()
        assert inv_a.file_hash != inv_b.file_hash


# ── Duplicate detection tests ──────────────────────────────────────────────────

class TestDuplicateDetection:

    def test_exact_duplicate_by_hash_is_skipped(self, watcher, inbox, processed):
        content = b"same content for both files"
        pdf1 = write_file(inbox, "original.pdf", content=content)
        watcher._process_file(pdf1)
        assert watcher.pop_next() is not None  # first goes through

        pdf2 = write_file(inbox, "copy.pdf", content=content)
        watcher._process_file(pdf2)
        assert watcher.pop_next() is None  # duplicate blocked

    def test_duplicate_copy_is_not_moved(self, watcher, inbox, processed):
        content = b"same content"
        pdf1 = write_file(inbox, "original.pdf", content=content)
        watcher._process_file(pdf1)
        watcher.pop_next()

        pdf2 = write_file(inbox, "copy.pdf", content=content)
        watcher._process_file(pdf2)
        # Duplicate file should still be in inbox (not moved)
        assert pdf2.exists()

    def test_different_content_same_name_both_ingested(self, watcher, inbox, processed):
        pdf1 = write_file(inbox, "invoice.pdf", content=b"version one")
        watcher._process_file(pdf1)
        watcher.pop_next()

        # Second file with same name but different content
        pdf2 = write_file(inbox, "invoice.pdf", content=b"version two")
        watcher._process_file(pdf2)
        inv2 = watcher.pop_next()

        assert inv2 is not None
        # Filename collision resolved with a unique suffix
        assert Path(inv2.raw_file_path).name != "invoice.pdf"
        assert Path(inv2.raw_file_path).exists()


# ── Filename collision in processed/ ──────────────────────────────────────────

class TestFilenameCollision:

    def test_existing_file_in_processed_gets_unique_suffix(self, watcher, inbox, processed):
        # Pre-populate processed with a file of the same name
        existing = processed / "facture.pdf"
        existing.write_bytes(b"already there")

        pdf = write_file(inbox, "facture.pdf", content=b"new invoice")
        watcher._process_file(pdf)
        inv = watcher.pop_next()

        assert inv is not None
        stored = Path(inv.raw_file_path)
        assert stored.exists()
        assert stored.name != "facture.pdf"  # suffix added
        assert existing.read_bytes() == b"already there"  # original untouched


# ── Scan-on-startup tests ─────────────────────────────────────────────────────

class TestScanExisting:

    def test_processes_files_already_in_inbox(self, watcher, inbox, processed):
        write_file(inbox, "old_invoice.pdf", content=b"arrived while agent was down")
        write_file(inbox, "old_invoice2.pdf", content=b"also arrived while agent was down")
        watcher._scan_existing()

        results = []
        while (inv := watcher.pop_next()) is not None:
            results.append(inv)
        assert len(results) == 2

    def test_empty_inbox_produces_no_invoices(self, watcher, inbox, processed):
        watcher._scan_existing()
        assert watcher.pop_next() is None

    def test_skips_unsupported_files_in_inbox(self, watcher, inbox, processed):
        write_file(inbox, "readme.txt")
        write_file(inbox, "data.xlsx")
        write_file(inbox, "invoice.pdf", content=b"this one counts")
        watcher._scan_existing()

        results = []
        while (inv := watcher.pop_next()) is not None:
            results.append(inv)
        assert len(results) == 1


# ── Recovery re-enqueue ───────────────────────────────────────────────────────

class TestEnqueue:

    def test_enqueue_puts_invoice_in_queue(self, watcher):
        inv = InvoiceRecord(
            file_hash="a" * 64,
            raw_file_path="/processed/test.pdf",
            status=InvoiceStatus.RECEIVED,
        )
        watcher.enqueue(inv)
        assert watcher.pop_next() is inv

    def test_multiple_enqueues_preserve_order(self, watcher):
        invoices = [
            InvoiceRecord(file_hash=c * 64, raw_file_path=f"/f{i}.pdf", status=InvoiceStatus.RECEIVED)
            for i, c in enumerate("abc")
        ]
        for inv in invoices:
            watcher.enqueue(inv)

        popped = [watcher.pop_next() for _ in range(3)]
        assert popped == invoices


# ── Observer start/stop ───────────────────────────────────────────────────────

class TestObserverLifecycle:

    def test_start_creates_directories(self, watcher, config):
        inbox = Path(config["ingestion"]["watch_path"])
        processed_dir = Path(config["ingestion"]["processed_path"])
        # Remove them first to verify start() creates them
        inbox.rmdir() if inbox.exists() else None
        processed_dir.rmdir() if processed_dir.exists() else None

        watcher.start()
        watcher.stop()

        assert inbox.exists()
        assert processed_dir.exists()

    def test_stop_without_start_does_not_raise(self, watcher):
        watcher.stop()  # should be a no-op

    def test_start_and_stop_cleanly(self, watcher):
        watcher.start()
        watcher.stop()
