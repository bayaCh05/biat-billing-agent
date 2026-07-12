"""Pipeline assembly — loads config and wires AI components together."""
from __future__ import annotations

import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv

from src.classification.accounting_coder import AccountingCoder
from src.classification.classifier import Classifier
from src.classification.ml_classifier import MLClassifier
from src.cost_catalog.catalog import CostCatalog
from src.accounting.entry_generator import EntryGenerator
from src.extraction.hybrid_extractor import HybridExtractor
from src.extraction.llm_extractor import LLMExtractor, OllamaBackend
from src.extraction.ocr_engine import TesseractEngine
from src.extraction.ocr_preprocessor import OCRPreprocessor
from src.extraction.pdf_reader import PDFReader
from src.validation.anomaly_detector import AnomalyDetector
from src.validation.coherence_checker import CoherenceChecker
from src.validation.duplicate_detector import DuplicateDetector
from src.validation.field_validator import FieldValidator


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

    Nothing here is bound to a SQLAlchemy session — AIOrchestrator reads/writes
    invoices via the sync Mongo repositories directly (see orchestrator.py), so
    duplicate_detector/anomaly_detector below are pre-bound to
    SyncMongoInvoiceRepository at construction time, not left to be rebound later.
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
