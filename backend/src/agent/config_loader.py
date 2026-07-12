"""Pipeline assembly — loads config and wires all components together."""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv

from src.accounting.entry_generator import EntryGenerator
from src.accounting.journal_store import JournalRepository
from src.agent.auto_corrector import AutoCorrector
from src.agent.pipeline import PipelineComponents
from src.billing.cost_allocator import CostAllocator
from src.billing.monthly_invoice_builder import MonthlyInvoiceBuilder
from src.billing.project_repository import ProjectRepository
from src.billing.template_loader import TemplateLoader
from src.classification.accounting_coder import AccountingCoder
from src.classification.classifier import Classifier
from src.classification.ml_classifier import MLClassifier
from src.cost_catalog.catalog import CostCatalog
from src.extraction.hybrid_extractor import HybridExtractor
from src.extraction.llm_extractor import LLMExtractor, OllamaBackend
from src.extraction.ocr_engine import TesseractEngine
from src.extraction.ocr_preprocessor import OCRPreprocessor
from src.extraction.pdf_reader import PDFReader
from src.ingestion.folder_watcher import FolderWatcher
from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.exporters.csv_exporter import CSVExporter
from src.storage.exporters.json_exporter import JSONExporter
from src.storage.repository import InvoiceRepository
from src.validation.anomaly_detector import AnomalyDetector
from src.validation.coherence_checker import CoherenceChecker
from src.validation.duplicate_detector import DuplicateDetector
from src.validation.escalator import FlagEscalator
from src.validation.field_validator import FieldValidator


_EXPORTERS = {
    "json": lambda cfg: JSONExporter(export_path=cfg["storage"]["export_path"]),
    "csv":  lambda cfg: CSVExporter(export_path=cfg["storage"]["export_path"]),
}


def load_config(settings_path: str = "config/settings.yaml") -> dict:
    load_dotenv()
    with open(settings_path) as f:
        cfg = yaml.safe_load(f)
    if db_url := os.getenv("DATABASE_URL"):
        cfg["storage"]["db_url"] = db_url
    return cfg


def load_rules(path: str) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)


@dataclass
class AIComponents:
    """Stateless business-logic components shared by AIOrchestrator's agents.

    Unlike PipelineComponents (agent/pipeline.py), nothing here is bound to a
    SQLAlchemy session — AIOrchestrator reads/writes invoices via the sync
    Mongo repositories directly (see orchestrator.py), so duplicate_detector/
    anomaly_detector below are pre-bound to SyncMongoInvoiceRepository at
    construction time, not left to be rebound later.
    """
    extractor:          "HybridExtractor"
    classifier:         "Classifier"
    coder:              "AccountingCoder"
    field_validator:    "FieldValidator"
    coherence_checker:  "CoherenceChecker"
    duplicate_detector: "DuplicateDetector"
    anomaly_detector:   "AnomalyDetector"
    entry_generator:    "EntryGenerator"
    cost_catalog:       "CostCatalog"

    def close(self) -> None:
        """No-op — kept so call sites can keep calling components.close()
        unconditionally; nothing here holds a DB session to release."""


def build_ai_components(
    config_path: str = "config/settings.yaml",
    llm_backend=None,
) -> "AIComponents":
    """Assemble the stage objects AIOrchestrator needs — no SQLAlchemy involved."""
    from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository

    cfg = load_config(config_path)
    mongo_repo = SyncMongoInvoiceRepository()

    if llm_backend is None:
        llm_backend = OllamaBackend(
            model=cfg["extraction"].get("llm_model", "qwen2.5:3b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    extractor = HybridExtractor(
        pdf_reader=PDFReader(
            min_chars=cfg["extraction"]["min_native_pdf_chars"],
            min_quality_ratio=cfg["extraction"]["min_text_quality_ratio"],
        ),
        preprocessor=OCRPreprocessor(),
        ocr_engine=TesseractEngine(languages=cfg["extraction"]["languages"]),
        llm_extractor=LLMExtractor(
            backend=llm_backend,
            languages=cfg["extraction"]["languages"],
            mode=cfg["extraction"].get("llm_extraction_mode", "amounts_only"),
        ),
        config=cfg,
    )

    classification_rules = load_rules(cfg["classification"]["rules_file"])
    cost_catalog = CostCatalog.from_yaml(cfg["classification"]["cost_catalog_file"])
    ml_classifier = MLClassifier(
        model_path=cfg["classification"].get("ml_model_path", "data/ml_model.joblib")
    )

    return AIComponents(
        extractor=extractor,
        classifier=Classifier(rules=classification_rules["direction_rules"]),
        coder=AccountingCoder(
            catalog=cost_catalog,
            min_score=cfg["classification"].get("catalog_min_score", 70),
            ml_classifier=ml_classifier,
        ),
        field_validator=FieldValidator(
            confidence_thresholds=cfg["extraction"]["confidence_thresholds"]
        ),
        coherence_checker=CoherenceChecker(config=cfg),
        duplicate_detector=DuplicateDetector(config=cfg, repository=mongo_repo),
        anomaly_detector=AnomalyDetector(config=cfg, repository=mongo_repo, catalog=cost_catalog),
        entry_generator=EntryGenerator(),
        cost_catalog=cost_catalog,
    )


def build_pipeline_components(
    config_path: str = "config/settings.yaml",
    llm_backend=None,
) -> tuple["PipelineComponents", object]:
    """Assemble all pipeline dependencies from config.

    Returns:
        (components, engine) — engine is returned so build_agent() can reuse
        the same connection pool for the FolderWatcher session factory.

    Args:
        config_path:  path to settings.yaml
        llm_backend:  optional override for the LLM backend (tests / Streamlit mock mode)
    """
    cfg = load_config(config_path)

    engine = build_engine(cfg["storage"]["db_url"])
    init_db(engine)
    session_factory  = build_session_factory(engine)
    inv_session      = session_factory()
    journal_session  = session_factory()
    project_session  = session_factory()

    repository         = InvoiceRepository(inv_session)
    journal_repository = JournalRepository(journal_session)
    project_repo       = ProjectRepository(project_session)

    template_loader = TemplateLoader(cfg["billing"]["templates_file"])
    issuer          = template_loader.issuer
    monthly_invoice_builder = MonthlyInvoiceBuilder(
        issuer_name=issuer.name,
        issuer_tax_id=issuer.tax_id,
        issuer_address=issuer.address,
        payment_terms_days=cfg["billing"].get("payment_terms_days", 30),
    )
    cost_allocator = CostAllocator()

    if llm_backend is None:
        llm_backend = OllamaBackend(
            model=cfg["extraction"].get("llm_model", "qwen2.5:3b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    extractor = HybridExtractor(
        pdf_reader=PDFReader(
            min_chars=cfg["extraction"]["min_native_pdf_chars"],
            min_quality_ratio=cfg["extraction"]["min_text_quality_ratio"],
        ),
        preprocessor=OCRPreprocessor(),
        ocr_engine=TesseractEngine(languages=cfg["extraction"]["languages"]),
        llm_extractor=LLMExtractor(
            backend=llm_backend,
            languages=cfg["extraction"]["languages"],
            mode=cfg["extraction"].get("llm_extraction_mode", "amounts_only"),
        ),
        config=cfg,
    )

    classification_rules = load_rules(cfg["classification"]["rules_file"])
    cost_catalog = CostCatalog.from_yaml(cfg["classification"]["cost_catalog_file"])
    ml_classifier = MLClassifier(
        model_path=cfg["classification"].get("ml_model_path", "data/ml_model.joblib")
    )

    escalator = FlagEscalator(
        threshold=cfg["validation"].get("warning_escalation_threshold", 2)
    )

    components = PipelineComponents(
        extractor=extractor,
        classifier=Classifier(rules=classification_rules["direction_rules"]),
        coder=AccountingCoder(
            catalog=cost_catalog,
            min_score=cfg["classification"].get("catalog_min_score", 70),
            ml_classifier=ml_classifier,
        ),
        field_validator=FieldValidator(
            confidence_thresholds=cfg["extraction"]["confidence_thresholds"]
        ),
        coherence_checker=CoherenceChecker(config=cfg),
        duplicate_detector=DuplicateDetector(config=cfg, repository=repository),
        anomaly_detector=AnomalyDetector(config=cfg, repository=repository, catalog=cost_catalog),
        escalator=escalator,
        auto_corrector=AutoCorrector(config=cfg, repository=repository),
        exporter=_EXPORTERS[cfg["storage"]["export_format"]](cfg),
        entry_generator=EntryGenerator(),
        cost_catalog=cost_catalog,
        repository=repository,
        journal_repository=journal_repository,
        project_repo=project_repo,
        cost_allocator=cost_allocator,
        monthly_invoice_builder=monthly_invoice_builder,
        max_retries=cfg["agent"]["max_retry_attempts"],
        _sessions=[inv_session, journal_session, project_session],
    )
    return components, engine  # engine returned so build_agent() reuses it


def build_agent(config_path: str = "config/settings.yaml"):
    """Build a ready-to-start InvoiceAgent for headless daemon mode."""
    from src.agent.agent import InvoiceAgent

    cfg = load_config(config_path)
    components, engine = build_pipeline_components(config_path)

    # FolderWatcher gets its own session factory from the shared engine —
    # no second connection pool, no second build_engine() call.
    session_factory = build_session_factory(engine)
    ingestor = FolderWatcher(config=cfg, session_factory=session_factory)

    return InvoiceAgent(
        components=components,
        ingestor=ingestor,
        poll_interval=cfg["ingestion"]["poll_interval_seconds"],
        stuck_timeout_minutes=cfg["agent"].get("stuck_invoice_timeout_minutes", 30),
    )
