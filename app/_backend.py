"""Shared backend utilities for the Streamlit app."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.accounting.journal_store import JournalRepository
from src.billing.billing_entry_generator import BillingEntryGenerator
from src.billing.client_invoice_store import ClientInvoiceRepository
from src.billing.invoice_builder import InvoiceBuilder
from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.pdf_generator import PDFGenerator
from src.billing.template_loader import TemplateLoader
from src.agent.config_loader import load_config, build_pipeline_components
from src.agent.pipeline import PipelineComponents
from src.extraction.llm_extractor import LLMBackendBase
from src.models.enums import FlagSeverity, InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.storage.db import build_engine, build_session_factory, init_db
from src.cost_catalog.catalog import CostCatalog
from src.storage.repository import InvoiceRepository
from src.suivi.aggregator import Aggregator
from src.suivi.lifecycle_tracker import LifecycleTracker
from src.suivi.reconciler import Reconciler
from src.budget.budget_tracker import BudgetPlan, BudgetTracker
from src.budget.cost_analyzer import CostAnalyzer
from src.capex.asset_repository import AssetRepository
from src.capex.depreciation_calculator import DepreciationCalculator
from src.capex.depreciation_entry_generator import DepreciationEntryGenerator


# ── Authentication ────────────────────────────────────────────────────────────

def require_auth() -> None:
    if st.session_state.get("authenticated"):
        return
    st.title("Invoice Agent — BIAT IT")
    pwd = st.text_input("Enter access password", type="password", key="_auth_pwd")
    if st.button("Login", type="primary"):
        expected = st.secrets.get("app_password", "biat2024")
        if pwd == expected:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


# ── Cached resources ──────────────────────────────────────────────────────────

@st.cache_resource
def _engine_and_config():
    cfg = load_config()
    engine = build_engine(cfg["storage"]["db_url"])
    init_db(engine)
    return engine, build_session_factory(engine), cfg


@st.cache_resource
def get_db_engine():
    """Return the shared SQLAlchemy engine (cached per Streamlit session)."""
    engine, _, _ = _engine_and_config()
    return engine


@st.cache_resource
def _cost_catalog():
    _, _, cfg = _engine_and_config()
    return CostCatalog.from_yaml(cfg["classification"]["cost_catalog_file"])


def get_repo() -> InvoiceRepository:
    engine, sf, _ = _engine_and_config()
    return InvoiceRepository(sf())


def get_journal_repo() -> JournalRepository:
    engine, sf, _ = _engine_and_config()
    return JournalRepository(sf())


def get_config() -> dict:
    _, _, cfg = _engine_and_config()
    return cfg


def get_tracker() -> LifecycleTracker:
    return LifecycleTracker(repository=get_repo())


def get_aggregator() -> Aggregator:
    return Aggregator(repository=get_repo())


def get_reconciler() -> Reconciler:
    return Reconciler(repository=get_repo())


def get_stuck_invoices() -> list:
    """Return invoices stuck in transition states beyond the configured timeout."""
    cfg = get_config()
    timeout = cfg["agent"].get("stuck_invoice_timeout_minutes", 30)
    return get_repo().get_stuck_invoices(timeout)


def get_ml_classifier():
    """Return a MLClassifier loaded from the configured model path."""
    from src.classification.ml_classifier import MLClassifier
    _, _, cfg = _engine_and_config()
    path = cfg["classification"].get("ml_model_path", "data/ml_model.joblib")
    return MLClassifier(model_path=path)


@st.cache_resource
def _budget_plan() -> BudgetPlan:
    return BudgetPlan.from_yaml("config/budget_plan.yaml")


def get_budget_tracker() -> BudgetTracker:
    _, sf, _ = _engine_and_config()
    return BudgetTracker(plan=_budget_plan(), session=sf())


def get_cost_analyzer() -> CostAnalyzer:
    _, sf, _ = _engine_and_config()
    return CostAnalyzer(session=sf())


def get_asset_repo() -> AssetRepository:
    _, sf, _ = _engine_and_config()
    return AssetRepository(sf())


def get_depreciation_calculator() -> DepreciationCalculator:
    return DepreciationCalculator()


def get_depreciation_entry_generator() -> DepreciationEntryGenerator:
    return DepreciationEntryGenerator()


# ── Billing resources ─────────────────────────────────────────────────────────

@st.cache_resource
def _template_loader() -> TemplateLoader:
    cfg = get_config()
    return TemplateLoader(cfg["billing"]["templates_file"])


def get_client_invoice_repo() -> ClientInvoiceRepository:
    _, sf, _ = _engine_and_config()
    return ClientInvoiceRepository(sf())


def get_invoice_builder() -> InvoiceBuilder:
    _, sf, _ = _engine_and_config()
    repo     = ClientInvoiceRepository(sf())
    numberer = InvoiceNumberer(repo)
    return InvoiceBuilder(loader=_template_loader(), numberer=numberer)


def get_pdf_generator() -> PDFGenerator:
    cfg = get_config()
    return PDFGenerator(output_dir=cfg["billing"]["pdf_output_dir"])


def get_billing_entry_generator() -> BillingEntryGenerator:
    return BillingEntryGenerator()


def get_project_repo():
    from src.billing.project_repository import ProjectRepository
    _, sf, _ = _engine_and_config()
    return ProjectRepository(sf())


def get_monthly_invoice_builder():
    from src.billing.monthly_invoice_builder import MonthlyInvoiceBuilder
    _, _, cfg = _engine_and_config()
    loader = TemplateLoader(cfg["billing"]["templates_file"])
    issuer = loader.issuer
    return MonthlyInvoiceBuilder(
        issuer_name=issuer.name,
        issuer_tax_id=issuer.tax_id,
        issuer_address=issuer.address,
        payment_terms_days=cfg["billing"].get("payment_terms_days", 30),
    )


# ── Pipeline components builder ───────────────────────────────────────────────

def get_pipeline_components(live: bool = True) -> tuple[PipelineComponents, InvoiceRepository]:
    """Build pipeline components for use in the Streamlit app.

    live=True  → real Ollama backend
    live=False → deterministic mock backend (no Ollama needed)
    """
    if live:
        backend = None  # build_pipeline_components will create OllamaBackend
    else:
        import json

        _MOCK = json.dumps({
            "issuer_name":      {"value": "TECHNOVA SOLUTIONS SARL",  "confidence": 0.95, "source": None},
            "issuer_tax_id":    {"value": "1472583D/A/M/000",          "confidence": 0.92, "source": None},
            "recipient_name":   {"value": "BIAT - Banque Internationale Arabe de Tunisie",
                                                                        "confidence": 0.95, "source": None},
            "recipient_tax_id": {"value": "0000217V/A/M/000",          "confidence": 0.90, "source": None},
            "invoice_number":   {"value": "FAC-2024-0147",             "confidence": 0.98, "source": None},
            "invoice_date":     {"value": "2024-05-20",                "confidence": 0.95, "source": None},
            "due_date":         {"value": "2024-06-19",                "confidence": 0.90, "source": None},
            "amount_ht":        {"value": 14500.0, "confidence": 0.95, "source": None},
            "tva_rate":         {"value": 19.0,    "confidence": 0.99, "source": None},
            "tva_amount":       {"value": 2755.0,  "confidence": 0.95, "source": None},
            "amount_ttc":       {"value": 17255.0, "confidence": 0.95, "source": None},
            "currency":         {"value": "TND",   "confidence": 1.0,  "source": None},
            "line_items": [
                {"description": "Maintenance informatique serveurs",   "quantity": 1.0, "unit_price": 8500.0,  "line_total": 8500.0,  "tva_rate": 19.0},
                {"description": "Support technique mensuel",           "quantity": 1.0, "unit_price": 3200.0,  "line_total": 3200.0,  "tva_rate": 19.0},
                {"description": "Formation equipe IT (3 jours)",       "quantity": 3.0, "unit_price": 650.0,   "line_total": 1950.0,  "tva_rate": 19.0},
                {"description": "Consommables informatiques",          "quantity": 1.0, "unit_price": 850.0,   "line_total": 850.0,   "tva_rate": 19.0},
            ],
        })

        class _MockBackend(LLMBackendBase):
            def complete(self, system, user): return _MOCK
        backend = _MockBackend()

    components, _engine = build_pipeline_components(llm_backend=backend)
    return components, components.repository


# ── Display helpers ───────────────────────────────────────────────────────────

def format_tnd(amount: float | None, decimals: int = 2) -> str:
    if amount is None:
        return "— TND"
    return f"{amount:,.{decimals}f} TND"


def conf_icon(conf: float) -> str:
    if conf >= 0.85: return "🟢"
    if conf >= 0.60: return "🟡"
    return "🔴"


def conf_pct(conf: float) -> str:
    return f"{conf:.0%}"


STATUS_COLORS = {
    InvoiceStatus.JOURNALED:  "🟢",
    InvoiceStatus.EXPORTED:   "🟡",
    InvoiceStatus.VALIDATED:  "🟢",
    InvoiceStatus.FLAGGED:    "🟠",
    InvoiceStatus.ESCALATED:  "🟠",
    InvoiceStatus.RECEIVED:   "🔵",
    InvoiceStatus.EXTRACTING: "🔵",
    InvoiceStatus.EXTRACTED:  "🔵",
    InvoiceStatus.CLASSIFYING:"🔵",
    InvoiceStatus.CLASSIFIED: "🔵",
    InvoiceStatus.VALIDATING:  "🔵",
    InvoiceStatus.EXPORTING:   "🔵",
    InvoiceStatus.JOURNALING:  "🔵",
    InvoiceStatus.ERROR:       "🔴",
    InvoiceStatus.REJECTED:   "🔴",
    InvoiceStatus.EXTRACTION_FAILED: "🔴",
    InvoiceStatus.PAID:       "✅",
    InvoiceStatus.COLLECTED:  "✅",
}


def status_badge(status: InvoiceStatus) -> str:
    icon = STATUS_COLORS.get(status, "⚪")
    return f"{icon} {status.value}"


def render_invoice_fields(inv: InvoiceRecord) -> None:
    fields = [
        ("Issuer",         inv.issuer_name),
        ("Issuer MF",      inv.issuer_tax_id),
        ("Recipient",      inv.recipient_name),
        ("Recipient MF",   inv.recipient_tax_id),
        ("Invoice #",      inv.invoice_number),
        ("Date",           inv.invoice_date),
        ("Due Date",       inv.due_date),
        ("Amount HT",      inv.amount_ht),
        ("TVA Rate",       inv.tva_rate),
        ("TVA Amount",     inv.tva_amount),
        ("Amount TTC",     inv.amount_ttc),
    ]
    rows = []
    for label, cf in fields:
        icon = conf_icon(cf.confidence)
        val = str(cf.value) if cf.value is not None else "—"
        rows.append({"Field": label, "Value": val, "Confidence": f"{icon} {conf_pct(cf.confidence)}"})

    import pandas as pd
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_flags(inv: InvoiceRecord) -> None:
    open_flags = [f for f in inv.flags if not f.resolved]
    if not open_flags:
        st.success("No open flags — clean extraction.")
        return
    for f in open_flags:
        if f.severity == FlagSeverity.ERROR:
            st.error(f"**{f.flag_type.value}** {('— ' + f.field_name) if f.field_name else ''}: {f.message}")
        else:
            st.warning(f"**{f.flag_type.value}** {('— ' + f.field_name) if f.field_name else ''}: {f.message}")
