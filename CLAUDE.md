# CLAUDE.md — BIAT IT Billing Agent v3

## Project Overview

Intelligent invoice automation system for BIAT IT (bank subsidiary in Tunisia).
Processes supplier and client invoices: OCR/LLM extraction → classification →
validation → accounting journal entries → budget tracking → CAPEX amortisation.

**Internship project.** Real bank data. All AI inference must be local (Ollama only).

---

## Critical Security Constraint

**DATA RESIDENCY: LOCAL ONLY.**
No invoice data may be sent to cloud APIs (OpenAI, Anthropic, Groq, etc.).
Ollama (local) is the only permitted LLM backend for production data.
Mock backends are allowed in tests and Streamlit demo mode only.
Violating this is a compliance failure for a banking subsidiary.

---

## Runtime

| Item | Value |
|------|-------|
| Python | 3.14.2 (`.venv/bin/python3.14`) |
| Streamlit | 1.58.0 |
| SQLAlchemy | 2.0.50 |
| Pydantic | 2.13.4 |
| Pandas | 3.0.3 |
| pytest | 9.0.3 |
| DB | SQLite at `data/invoices.db` (WAL mode) |
| LLM | Ollama `qwen2.5:3b` on `http://localhost:11434` |
| OCR | Tesseract (not EasyOCR — not installed) |

---

## Commands

```bash
# Activate virtual environment (always required first)
source .venv/bin/activate

# Run tests
.venv/bin/pytest                          # all 629 tests
.venv/bin/pytest tests/unit/             # unit only
.venv/bin/pytest tests/integration/     # integration only (needs Tesseract)
.venv/bin/pytest --tb=short -q           # compact output

# Run Streamlit app
streamlit run app/Home.py                 # starts on :8502

# Run headless daemon (watches ./inbox folder)
python scripts/run_agent.py

# Human review queue (terminal UI)
python scripts/review_queue.py

# Generate demo invoice PDF
python scripts/make_realistic_invoice.py

# Lint
.venv/bin/ruff check src/ app/ tests/

# Init / migrate DB
python -c "from src.storage.db import build_engine, init_db; init_db(build_engine('sqlite:///./data/invoices.db'))"
```

---

## Architecture (v3)

### Module dependency order (no cycles)
```
models → storage → cost_catalog
       → classification
       → extraction
       → validation
       → accounting
       → billing
       → budget
       → capex
       → suivi
       → agent/pipeline.py   ← pure functions
       → agent/agent.py      ← thin event loop
       → app/                ← Streamlit UI
```

### Key design: `pipeline.py` is pure functions

The core processing is **not a class**. It is a set of free functions:

```python
from src.agent.pipeline import (
    PipelineComponents,   # dataclass holding all deps
    process_invoice,      # runs all 4 stages
    extract,              # Stage 1: PDF/OCR/LLM
    classify,             # Stage 2: direction + accounting code
    validate,             # Stage 3: field checks, duplicates, math
    export_invoice,       # Stage 4: JSON export + journal entry
    recover_interrupted,  # call on startup to reset mid-flight invoices
    re_enqueue_received,  # call on startup to requeue RECEIVED invoices
)
```

`InvoiceAgent` (in `agent.py`) is just a thin `threading.Event` loop that calls
`process_invoice()`. The Streamlit app calls stage functions directly.

### Build the pipeline

```python
from src.agent.config_loader import build_pipeline_components, build_agent

# For Streamlit (no daemon loop)
components, engine = build_pipeline_components()

# For headless daemon
agent = build_agent()
agent.start()  # blocks; call agent.stop() from signal handler
```

`build_pipeline_components()` returns `(PipelineComponents, engine)` — the engine
is returned so callers can share it for FolderWatcher sessions without a second
connection pool.

---

## Project Structure

```
src/
  agent/
    pipeline.py          # ← core: pure functions + PipelineComponents dataclass
    agent.py             # ← thin daemon loop (InvoiceAgent)
    config_loader.py     # ← wires all components from settings.yaml
    auto_corrector.py    # ← math-only correction (no cloud)
  models/
    invoice.py           # InvoiceRecord with ConfidenceField[T] generics
    enums.py             # InvoiceStatus, FlagType, etc.
    asset.py             # CAPEX asset model
    client_invoice.py    # outgoing client invoices
    journal.py           # double-entry journal entries
  storage/
    db.py                # build_engine(), init_db() — SQLite WAL + FK
    orm_models.py        # InvoiceORM and related tables
    repository.py        # InvoiceRepository CRUD
  extraction/
    hybrid_extractor.py  # routes: native PDF → OCR → LLM
    llm_extractor.py     # Ollama backend (OllamaBackend)
    ocr_engine.py        # TesseractEngine (production)
    extras_ocr.py        # EasyOCREngine (optional, not installed)
  classification/
    accounting_coder.py  # Level A (rules) + Level B (ML) coding
    ml_classifier.py     # TF-IDF + LogisticRegression fallback
    catalog.py           # CostCatalog fuzzy keyword matching
  validation/            # field_validator, coherence_checker, duplicate_detector, anomaly_detector
  accounting/            # entry_generator.py — journal entry patterns
  billing/               # client invoice generation + PDF (fpdf2)
  budget/                # BudgetTracker (planned vs actual), CostAnalyzer
  capex/                 # DepreciationCalculator (linear/degressive), AssetRepository
  suivi/                 # aggregator, lifecycle_tracker, reconciler
  ingestion/
    folder_watcher.py    # watchdog-based file watcher
    null_ingestor.py     # no-op for Streamlit/script contexts
  utils/
    date_utils.py        # last_day_of_month(), last_day_int()
    logging.py           # structlog setup

config/
  settings.yaml          # all config (DB URL, OCR engine, thresholds, etc.)
  cost_catalog.yaml      # 33 entries: comptable taxonomy (nature/type/compte/TVA)
  budget_plan.yaml       # annual budget by catalog_id (12 monthly values each)
  client_templates.yaml  # intra-group billing templates
  rules/
    classification_rules.yaml   # direction rules (SUPPLIER/CLIENT/UNKNOWN)

app/
  Home.py                # invoice upload + pipeline execution
  _backend.py            # shared Streamlit helpers + get_pipeline_components()
  pages/
    1_📊_Dashboard.py    # invoice KPIs + ageing
    2_🔍_Review_Queue.py # human review of flagged invoices
    3_📋_Invoices.py     # full invoice list
    4_💳_Suivi.py        # lifecycle tracking + payment reconciliation
    5_📒_Journal.py      # accounting journal viewer
    6_📤_Facturation.py  # client invoice creation
    7_📊_Budget.py       # budget vs actual (4 tabs)
    8_🏗️_Immobilisations.py  # CAPEX asset register + depreciation
    9_🎯_Direction.py    # executive dashboard (all modules combined)

scripts/
  run_agent.py           # headless daemon entry point
  review_queue.py        # terminal review UI
  make_realistic_invoice.py  # demo PDF generator

tests/
  unit/                  # 15 files, mocked dependencies
  integration/           # test_pipeline_e2e.py — real DB, mocked LLM
  fixtures/make_invoice_pdf.py
```

---

## Key APIs to Know

### InvoiceRecord
```python
inv.issuer_name           # ConfidenceField[str] — always .value + .confidence
inv.amount_ttc.value      # float | None
inv.amount_ttc.confidence # float 0.0–1.0
inv.has_errors            # True if any unresolved ERROR-severity flag
inv.add_flag(flag)        # also sets human_review_required=True for ERRORs
inv.status                # InvoiceStatus enum (RECEIVED → ... → EXPORTED/PAID)
```

### CostCatalog
```python
catalog = CostCatalog.from_yaml("config/cost_catalog.yaml")  # correct classmethod
catalog.match(text, flux=ChargeFlux.FOURNISSEUR, min_score=70)  # returns CostCatalogEntry | None
catalog.get("salaires")   # lookup by id
```

### AccountingCoder
```python
coder = AccountingCoder(catalog=catalog, min_score=70, ml_classifier=ml_clf)
# NOT AccountingCoder(rules=...) — that was v1, now deleted
```

### Journal entries
```python
# Double-entry invariant: |sum(debits) − sum(credits)| < 0.005 TND
entry = EntryGenerator().generate(invoice, catalog_entry)
journal_repo.save(entry)
```

### Budget
```python
plan = BudgetPlan.from_yaml("config/budget_plan.yaml")
tracker = BudgetTracker(plan=plan, session=session)
summary = tracker.summary(year=2026, through_month=6)
# summary keys: total_budget_ytd, total_actual_ytd, variance_pct, lines_over_budget
```

### Streamlit conventions
- Use `width="stretch"` (NOT `use_container_width=True` — deprecated in 1.58)
- Use `df.style.map()` (NOT `df.style.applymap()` — removed in pandas 3.x)
- Only `app/Home.py` may call `st.set_page_config()`
- Cached resources: `@st.cache_resource` for engines, catalogs, budget plans
- After calling `get_pipeline_components()`, call `components.close()` in `finally`

---

## Accounting (PCE Tunisien)

Plan Comptable des Entreprises tunisien. Key accounts:
- `401` Fournisseurs, `411` Clients
- `4366` TVA déductible, `4367` TVA collectée
- `6xxx` Charges (OPEX), `2xxx` Immobilisations (CAPEX)
- `6811` Dotations amortissements, `28xx` Amortissements cumulés
- TVA rates allowed: 0%, 7%, 13%, 19% — validate against `tva_rates_allowed` in settings

---

## Enums Reference

### InvoiceStatus (state machine)
`RECEIVED → EXTRACTING → EXTRACTED → CLASSIFYING → CLASSIFIED → VALIDATING → VALIDATED/FLAGGED → EXPORTING → EXPORTED → PAID/COLLECTED`

Terminal statuses (pipeline stops): `FLAGGED, ESCALATED, ERROR, REJECTED, EXTRACTION_FAILED`

**Note:** `CORRECTED` was removed in v3 — no code ever set it.

### FlagType
- `TOTAL_MISMATCH`, `TVA_MISMATCH`, `LINEITEMS_SUM_MISMATCH` — math
- `MISSING_FIELD`, `INVALID_TAX_ID`, `LOW_CONFIDENCE` — field quality
- `DUPLICATE`, `SUSPECTED_DUPLICATE`, `NEAR_DUPLICATE` — deduplication
- `UNKNOWN_DIRECTION` — classifier could not determine SUPPLIER/CLIENT
- `CATALOG_NO_MATCH` — direction known but no catalog entry matched (not `UNKNOWN_DIRECTION`)
- `HIGH_VALUE`, `SUSPICIOUS_AMOUNT` — anomaly detection

---

## Configuration Reference (`config/settings.yaml`)

```yaml
extraction:
  ocr_engine: tesseract      # DO NOT change to easyocr — not installed
  llm_model: qwen2.5:3b      # Ollama model name
  llm_backend: ollama        # MUST stay ollama — data residency policy

classification:
  ml_model_path: data/ml_model.joblib   # trained on VALIDATED/EXPORTED invoices

storage:
  db_url: sqlite:///./data/invoices.db  # override with DATABASE_URL env var
```

---

## Test Conventions

- Unit tests: mock the repository and all external deps with `MagicMock`
- Integration tests: use `sqlite:///:memory:`, mock only the LLM backend
- `_build_components()` in `test_pipeline_e2e.py` is the integration test helper
- 5 PyMuPDF C-library `DeprecationWarning`s in test output are harmless — ignore
- `InvoiceRepository` mock must include `count_by_status` and `count_auto_approved`

---

## What NOT to Do

- Do not add `@st.cache_resource` to `get_pipeline_components()` — it creates per-mode sessions that must be closed
- Do not use `Orchestrator` — it was deleted in v3; use `process_invoice()` + `PipelineComponents`
- Do not use `AccountingCoder(rules=...)` — v1 API, removed; use `AccountingCoder(catalog=CostCatalog)`
- Do not use `CostCatalog.load()` — the correct classmethod is `CostCatalog.from_yaml()`
- Do not call `use_container_width=True` in Streamlit — use `width="stretch"`
- Do not call any cloud LLM with real invoice data — data residency violation
- Do not import `EasyOCREngine` from `ocr_engine` — it moved to `extras_ocr.py`
- Do not add `lifecycle_tracker` back to `PipelineComponents` — it belongs to `_backend.py` only
