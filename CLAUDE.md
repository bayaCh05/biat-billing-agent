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
| DB (legacy/still-live) | SQLite at `data/invoices.db` (WAL mode) |
| DB (primary, in migration) | MongoDB via Beanie/Motor — `docker-compose` service `biat_mongo`, `MONGODB_URI`/`MONGODB_DB` in `.env`. **Auth required**: `mongod --auth`, credentials via `MONGO_ROOT_USER`/`MONGO_ROOT_PASSWORD` in `.env` (embedded in `MONGODB_URI` as `mongodb://user:pass@host/?authSource=admin`) |
| LLM | Ollama `qwen2.5:3b` on `http://localhost:11434` |
| OCR | Tesseract (not EasyOCR — not installed) |

**Two persistence layers coexist.** See "MongoDB Migration Status" below before touching any storage code — reads/writes for most domains now go to MongoDB, not SQLite, and the rule for which one differs by file.

---

## Commands

```bash
# Activate virtual environment (always required first)
source .venv/bin/activate

# Run tests — MUST run from repo root, not backend/ (relative config paths break otherwise)
.venv/bin/pytest backend/                 # all 1177 tests, 1 skipped (real-PDF fixture, env-dependent)
.venv/bin/pytest backend/tests/unit/      # unit only
.venv/bin/pytest backend/tests/integration/  # integration only (needs Tesseract)
.venv/bin/pytest backend/ --tb=short -q   # compact output

# Run Streamlit app
streamlit run app/Home.py                 # starts on :8502

# Run FastAPI backend (the real production interface)
python scripts/run_api.py                 # port 8000, --reload for hot-reload

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

# MongoDB (docker-compose service "biat_mongo") — runs with --auth; see .env for
# MONGO_ROOT_USER/MONGO_ROOT_PASSWORD. On an EXISTING populated volume, changing
# these env vars alone does nothing (Mongo's init scripts only bootstrap a root
# user on a brand-new empty data dir) — create the user manually first:
#   docker exec biat_mongo mongosh admin --eval 'db.createUser({user:"...",pwd:"...",roles:[{role:"root",db:"admin"}]})'
docker compose up -d mongo                              # start local Mongo
python backend/scripts/db_inspect.py list <collection>   # read-only inspection CLI
python backend/scripts/verify_migration_integrity.py     # SQLite vs Mongo row-count/UUID-identity check
```

CI (`.github/workflows/ci.yml`) runs its own `mongo:7` service container for the `test` job —
deliberately **without** `--auth` (ephemeral, empty, torn down every run — no real data ever
touches it, unlike the dev/prod volume above which requires auth by design).

---

## Architecture (v3)

> **Path note:** the module paths below (`src/...`) predate the FastAPI backend and
> predate this doc being kept in sync with it. The actual current repo root for all
> of these is `backend/` (i.e. `backend/src/agent/pipeline.py`, not `src/agent/pipeline.py`).
> There is also a full FastAPI REST API at `backend/api/` (routers under
> `backend/api/routers/`: `invoices.py`, `auth.py`, `admin.py`, `users.py`, `security.py`,
> `billing.py`, `payments.py`, `budget.py`, `capex.py`, `projet_budget.py`, `roadmap.py`,
> `risks.py`, `livrables.py`, `notifications.py`, `review.py`, `journal.py`, `suivi.py`,
> `ai.py`, plus `backend/api/scheduler.py` for nightly jobs) — this is the actual
> production interface, not just Streamlit. `POST /api/invoices/upload` runs invoices
> through `backend/src/ai_agents/orchestrator.py::AIOrchestrator` (see below), **not**
> `pipeline.py::process_invoice()`. The daemon (`scripts/run_agent.py`) and Streamlit's
> direct pipeline calls are the only things still using `pipeline.py::process_invoice()`.
> Below this note, "Orchestrator... deleted in v3" refers to a different, older class —
> `AIOrchestrator` is current and heavily used; do not read that note as discouraging it.

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

## MongoDB Migration Status (Phase 7 — in progress, SQLite NOT yet removed)

The app is mid-migration from SQLAlchemy/SQLite to MongoDB/Beanie. **Do not assume
SQLite is authoritative for anything** — check this section first. All paths below
are relative to `backend/`.

### What's Mongo-primary (SQLite frozen/stale for these)

- **Invoices, journal entries, CAPEX assets, payment installments** — written by
  `src/ai_agents/orchestrator.py::AIOrchestrator` (the real upload pipeline) via a
  **synchronous** pymongo repository layer, `src/storage/sync_mongo_repository.py`
  (`SyncMongoInvoiceRepository`, `SyncMongoJournalRepository`, `SyncMongoAssetRepository`,
  `SyncMongoClientInvoiceRepository`, plus free functions `save_payment_installments_sync`,
  `historical_amounts_for_catalog_sync`, `historical_payment_terms_sync`,
  `journal_consistency_check_sync`, `recalculate_late_installments_sync`).
- **Roadmap, livrables, risks, phases, budget lines/plan entries, notifications,
  review approve/reject** — written via async Beanie functions in
  `src/storage/documents/service_bridge.py` (`*_native` functions), called directly
  from `api/routers/*.py`.
- **Users, sessions (active/revoked tokens), OTP codes, password-reset links,
  account lockout state** — same pattern, `*_native` functions in `service_bridge.py`,
  called from `api/auth.py` (`get_current_user`) and `api/routers/auth.py`,
  `admin.py`, `users.py`, `security.py`.
- **Audit log entries — all of them now**, not just auth/admin/security. As of
  Lots 7–9, `invoices.py` upload-time events (`FILE_REJECTED`, `INVOICE_UPLOADED`),
  `ai_agents/orchestrator.py::_audit_ai()` (`AI_EXTRACT`, `AI_CLASSIFY`,
  `AI_ANOMALY`, `AI_JOURNAL`), and `api/routers/audit.py`'s `AUDIT_INTEGRITY_CHECK`
  entries all write Mongo-native too (`log_audit_event_native()` /
  `log_ai_audit_event_sync()` — the latter in `sync_mongo_repository.py`, sync
  by design since `AIOrchestrator` is sync). **`src/services/audit_service.py::log_action()`
  (the old SQLAlchemy audit writer) now has zero real callers anywhere in the
  codebase** — grep confirms only its own definition and stale docstring
  references remain. `audit_logs` in SQLite receives no new writes through any
  currently-active code path.
- **Journal consistency check** — `AccountingAgent.check_consistency()` delegates
  directly to `sync_mongo_repository.py::journal_consistency_check_sync()`
  (queries the `journal_entries` Mongo collection), used by both
  `scheduler.py::_job_accounting_consistency` (weekly) and
  `POST /ai/accounting-check`. The injected SQLAlchemy `journal_repository` is
  no longer read by either caller.
- **ML classifier retraining** — `scheduler.py::_job_retrain_classifier` (weekly)
  and `POST /ai/retrain` both use `SyncMongoInvoiceRepository.count_by_status()`/
  `.get_by_status()` (added specifically for this) instead of the SQLAlchemy
  `InvoiceRepository` — see "Scheduled Jobs Status" below.
- **Roadmap risk scan** — `RiskAgent._scan_roadmap()` (used by
  `scheduler.py::_job_scan_roadmap_risks`, `POST /ai/scan-roadmap-risks`,
  `POST /ai/scan-item-risk/{id}`) queries `FeuilleDeRouteDocument`/`RisqueDocument`
  directly and creates risks via `create_risk_native()`. Bridged from its sync
  callers (all plain `def`/APScheduler jobs, no event loop of their own) via
  `asyncio.run()` in `_scan_roadmap()` — see that method's docstring before
  reusing this bridge pattern elsewhere.
- **AI health-summary** (`GET /ai/health-summary`, `InsightAgent._gather_kpis()`)
  — reads via 4 sync helpers in `sync_mongo_repository.py`
  (`invoice_pending_rejected_30d_sync`, `roadmap_kpis_sync`, `risks_kpis_sync`,
  `budget_variance_kpis_sync`), added specifically for this (2026-07). `InsightAgent`
  no longer takes an `engine` constructor arg — it's `InsightAgent()`.
- **NL-query** (`POST /nl-query`, `src/query/nl_query_engine.py`) — the LLM now
  generates a MongoDB aggregation pipeline (`{"collection": ..., "pipeline": [...]}`)
  instead of raw SQL, executed via `sync_mongo_repository.py::_get_db()` (sync route,
  no `await`). Collection allowlist + forbidden-stage list (`$out`, `$merge`,
  `$lookup`, `$where`, ...) enforced in `NLQueryEngine._is_safe()`. Cross-collection
  joins are NOT supported (`$lookup` is blocked) — journal lines are embedded in
  `journal_entries.lines`, not a separate collection, precisely so most questions
  don't need one. `NLQueryEngine()` no longer takes an `engine` constructor arg either.
- **Notification sync** (`sync_flagged_invoices_mirrored()` in `service_bridge.py`,
  called by `GET /notifications/count` and `/list`) — as of 2026-07 this reads
  flagged invoices from `InvoiceDocument` directly and dedups against
  `NotificationDocument`, no SQLite involved at all anymore. Before this fix it
  silently scanned SQLite only, meaning invoices flagged through the real
  Mongo-only upload path never generated a notification — a real bug, not just a
  migration-status inaccuracy.
- **Seed/demo scripts** (`scripts/seed_demo.py`, `seed_users.py`,
  `seed_budget_actuals.py`) — write to MongoDB via `sync_mongo_repository.py`
  (`SyncMongo*Repository.save()` plus new `create_user_sync`,
  `save_charte_projet_sync`, `save_phase_sync`, `save_livrable_sync`,
  `save_ligne_budget_sync`, `save_feuille_de_route_sync`). **Every write is
  idempotent (upsert-by-id / skip-if-exists) — these scripts no longer wipe the
  database by default.** That was safe when they targeted a disposable SQLite
  file; it is not safe now that they write to the same shared MongoDB the app
  reads from. `--append` is kept only for CLI compatibility and has no effect
  on this idempotency.
- **`PATCH /ai/invoices/{id}/classification`** (classification-feedback endpoint)
  — reads/writes the invoice via `SyncMongoInvoiceRepository`, writes feedback via
  `save_classification_feedback_sync()`/`count_classification_feedback_sync()`
  into the `classification_feedback` Mongo collection
  (`ClassificationFeedbackDocument` existed since Phase 2 but was never actually
  written to before this — the endpoint previously only wrote to a SQLite-only
  table, dormant at 0 rows since real uploads through the API never landed there).

### What's still SQLite-only (do not assume these are in Mongo)

- **The daemon** (`scripts/run_agent.py` → `InvoiceAgent` → `agent/pipeline.py::process_invoice()`)
  and **Streamlit's direct pipeline calls** — both still use the shared SQLAlchemy
  `PipelineComponents` from `agent/config_loader.py`, untouched by the migration.
  Do not assume invoices created this way land in Mongo. **Confirmed (2026-07)
  by the project owner: both are superseded by the API+AIOrchestrator path in
  practice** — safe to disregard as a blocker for SQLite read-only/removal work,
  but the code itself hasn't been deleted.
- **`main.py`'s demo-user reseeding** (`seed_demo_users`/`refresh_demo_passwords`,
  run on every startup) — writes SQLite `users`. Since login is Mongo-native now
  and daemon/Streamlit are confirmed superseded, this looks like dead weight
  rather than something to preserve — a deletion candidate, not a migration target.
- **`api/routers/audit.py::compute_integrity_summary`**'s one-time HMAC backfill
  (`session.commit()` after backfilling `row_hash` on any pre-HMAC-era SQLite row
  still `NULL`) — as of 2026-07, 5 rows out of 708 in `audit_logs` still need
  this. One-time; becomes permanently dormant once those 5 are backfilled (no
  code path creates new `NULL`-hash rows anymore, per `log_action()` above).
- **The audit-log HMAC hash chain** (`row_hash` column, `api/security/audit_integrity.py`,
  `AUDIT_INTEGRITY_CHECK` endpoint) — this is structurally SQLite-specific (tamper-evidence
  chain over that table's own rows). No Mongo equivalent exists yet; this is an open
  design question, not a pending mechanical migration. `verify_integrity_native()`
  computes an equivalent check over Mongo's `audit_logs` documents and
  `compute_integrity_summary()` merges both into one score — see that function's
  docstring ("one compliance trail split across two stores, not two independent ones").

**Consequence: SQLite cannot be removed yet, but the reason has changed again.**
As of 2026-07, every live production gap that had **zero** Mongo equivalent
(NL-query, AI health-summary, notification sync, seed scripts, health checks,
classification-feedback, CI) has been closed — see the Mongo-primary bullets
above. What's left blocking a full SQLite read-only/removal ("Lot 10") is now
much narrower: the one-time HMAC backfill on `audit_logs`, plus the general
fact that the SQLAlchemy fallback branches in most `api/routers/*.py` GET
routes (the `if mongo_x is not None: ... else: <SQL>` pattern) haven't been
removed yet — they're currently unreachable in practice (Mongo is always
primary) but still live code. Do not set SQLite read-only or delete
SQLAlchemy code paths without a deliberate, lot-by-lot removal pass — and
note the daemon/Streamlit code paths above still exist even though they're
confirmed unused in practice.

### Scheduled Jobs Status (`api/scheduler.py`)

All 4 jobs are Mongo-native as of 2026-07.

| Job | Cadence | Data source |
|-----|---------|--------------|
| `_job_accounting_consistency` | weekly (Mon 6am) | Mongo (`journal_consistency_check_sync`) |
| `_job_retrain_classifier` | weekly | Mongo (`SyncMongoInvoiceRepository`) |
| `_job_recalculate_installments` | nightly | Mongo (`recalculate_late_installments_sync`) |
| `_job_scan_roadmap_risks` | nightly (8am) | Mongo (`RiskAgent._scan_roadmap_async`, bridged via `asyncio.run()`) |

### Conventions — read before writing any Mongo code

- **`_id` (and any soft-reference field) is ALWAYS a string with dashes**
  (`str(uuid4())`), **NEVER** a native BSON UUID Binary — even when a Beanie
  `Document` class declares the field as `UUID` in its Pydantic schema (several
  do, e.g. `UserDocument.id`, `PasswordVerificationDocument.user_id` — this is a
  known inconsistency between the Beanie schema's type hint and what's actually
  on disk, not a bug to "fix"). All the migration + native write code inserts via
  raw `Document.get_pymongo_collection()` + `insert_one`/`update_one`/`replace_one`,
  never `Document(...).insert()`, specifically to avoid Pydantic coercing the
  string into a UUID object on write.
- **Never call `Document.get(x)` or a typed query (`Document.field == value`) against
  a string-stored id/reference field.** Beanie coerces the argument to the field's
  *declared* type before querying, silently producing a BSON UUID query that never
  matches string-stored data — this bug has recurred repeatedly across the migration.
  Use dict-filtered queries instead: `Document.find_one({"_id": id_str})` or the
  `_get_by_str_id(doc_class, id_str)` helper in `service_bridge.py`.
- **Sync vs async is not a style choice — it's forced by the caller.** FastAPI routes
  are `async def` → use the async Beanie functions in `service_bridge.py`. The invoice
  pipeline (`AIOrchestrator` and its 4 agents in `ai_agents/`) and anything called
  from `InvoiceNumberer`/`InvoiceBuilder` (billing) are genuinely synchronous by
  design — use `sync_mongo_repository.py` (plain `pymongo.MongoClient`) there instead,
  never `await` inside them.
- Dates with no time component (e.g. `invoice_date`, `acquisition_date`) are stored
  as `datetime` at UTC midnight (`_to_midnight_utc()` helper) — BSON has no pure date type.
- `MONGODB_URI` / `MONGODB_DB` env vars gate Mongo entirely — if unset, `init_beanie()`
  returns `False` and the app runs SQLite-only (no crash). Don't assume Mongo is reachable
  in every environment; native `*_native` functions do NOT have SQL fallbacks by design
  (they're meant to be authoritative) — only the older `*_mongo()` read-bridge functions
  from the earlier migration phase have a `None`-means-fall-back-to-SQL contract.

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
`RECEIVED → EXTRACTING → EXTRACTED → CLASSIFYING → CLASSIFIED → VALIDATING → VALIDATED/FLAGGED → EXPORTING → EXPORTED → JOURNALING → JOURNALED → PAID/COLLECTED`

`JOURNALING`/`JOURNALED` is `pipeline.py`'s `post_journal()` stage (5th stage,
after export) — on success `EXPORTED → JOURNALING → JOURNALED`; on failure
reverts to `EXPORTED` + a `JOURNAL_FAILED` ERROR flag. This is the real
happy-path terminal status for a successfully processed invoice, not `EXPORTED`
— a test (`test_mark_paid_advances_supplier_invoice`) used to assume `EXPORTED`
was terminal and silently skipped on every run once this stage started firing;
fixed 2026-07 (see "Security Hardening Status" above).

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
- No `pytest-asyncio`/`pytest-anyio` plugin actually installed despite being a
  listed dependency — drive async code via `asyncio.run(coro)` in plain sync
  test functions, not `async def test_...`.
- **Rate-limit testing gotcha**: `api/limiter.py`'s `RATE_LIMIT_ENABLED` is read
  once at import time and baked into every `@limiter.limit(...)` decorator.
  `test_api_e2e.py` sets it to `false` before importing the real app, and since
  pytest runs the whole suite in one process, whichever test module imports
  `api.limiter` first fixes that constant for every test that follows. **Do
  not** try to work around this with `importlib.reload()` — `slowapi`'s
  `Limiter` registers each decorated route under a plain
  `f"{module}.{qualname}"` string key that *accumulates* across repeated
  reloads of the same function name, so reloading a router module N times
  makes that endpoint's hit-count increase by N+1 per request (a pure test
  artifact, verified experimentally — see `test_avatar_rate_limit.py`).
  Instead, drive the real behavior through a clean `subprocess` with
  `RATE_LIMIT_ENABLED=true` set before any import.

---

## Security Hardening Status (2026-07 audit)

An internal audit produced two batches of findings, all now fixed and pushed
except one. Don't re-scope or re-flag these — check here first.

**Fixed:**
- JWT_SECRET hardcoded fallback removed; validated at startup
- Unique-index collisions now return clean 409s instead of unhandled 500s
- Role guards added to journal/capex/nl-query/billing routes
- `/security/summary` no longer hardcodes `tampered_entries_count: 0`
- OTP generation uses `secrets`, not `random.choices()`
- Silent SQL fallback removed on 6 Mongo-only read domains (roadmap/risks/livrables)
- Session revocation on password change/reset/admin-reset (touches both
  `RevokedTokenDocument` and `ActiveTokenDocument` — see "Conventions" above)
- `LDAP_BIND_PASSWORD` hardcoded fallback removed; fail-fast check in
  `api/main.py::_startup()` (not `ldap_service.py` — that module is only
  imported lazily, on first LDAP login attempt, not at app boot)
- MongoDB authentication enabled (`mongod --auth`; see Runtime table above)
- Rate limit added to `PATCH /users/me/avatar` (10/minute, matches invoice upload)
- Obsolete test skip fixed in `test_pipeline_e2e.py` (`test_mark_paid_advances_supplier_invoice`
  was silently skipping every run once `pipeline.py` added the `post_journal()`
  stage — see JOURNALED in "InvoiceStatus" below)
- `service_bridge.py` test coverage: 127 functions audited, 30 confirmed dead
  and removed, all 97 remaining now have direct unit tests
- Debug-log leak fixed (raw invoice text no longer dumped at DEBUG level)
- Unused `demo_base64` endpoint removed
- All 4 `scheduler.py` jobs (`accounting_consistency`, `retrain_classifier`,
  `recalculate_installments`, `scan_roadmap_risks`) moved off the stale
  SQLAlchemy repository onto Mongo — see "Scheduled Jobs Status" above.
  `scan_roadmap_risks` was the largest item: it used to silently write
  AI-suggested risks into SQLite only, invisible to the real Mongo-backed UI
- NL-query, AI health-summary, notification sync, seed/demo scripts, health
  checks (`/api/health`, `/api/health/ready`), CI (Mongo service container
  added), and the classification-feedback endpoint all migrated to Mongo —
  these had **zero** Mongo equivalent before (not a fallback, an outright gap),
  found during a fresh inventory that also flagged this doc as stale on
  exactly these points. See "MongoDB Migration Status" above.

**Still open:**
- Refresh token rotation (jti reusable up to 7 days) — explicitly deprioritized
- "Lot 10" (SQLite → read-only → removal) — the functional gaps that used to
  block this are closed now (see above); what remains is the one-time HMAC
  backfill on `audit_logs` and a deliberate lot-by-lot removal of the
  now-unreachable-in-practice SQLAlchemy fallback branches; final removal step
  explicitly needs supervisor sign-off regardless

---

## What NOT to Do

- Do not add `@st.cache_resource` to `get_pipeline_components()` — it creates per-mode sessions that must be closed
- Do not use the old `Orchestrator` class from pre-v3 (deleted) — use `process_invoice()` + `PipelineComponents`
  for the daemon/Streamlit path. This is unrelated to `AIOrchestrator` (`ai_agents/orchestrator.py`), which is
  current and is what `POST /api/invoices/upload` actually runs — do not delete or avoid that one.
- Do not use `AccountingCoder(rules=...)` — v1 API, removed; use `AccountingCoder(catalog=CostCatalog)`
- Do not use `CostCatalog.load()` — the correct classmethod is `CostCatalog.from_yaml()`
- Do not call `use_container_width=True` in Streamlit — use `width="stretch"`
- Do not call any cloud LLM with real invoice data — data residency violation
- Do not import `EasyOCREngine` from `ocr_engine` — it moved to `extras_ocr.py`
- Do not add `lifecycle_tracker` back to `PipelineComponents` — it belongs to `_backend.py` only
- Do not set SQLite to read-only or remove SQLAlchemy code paths yet — the functional gaps that used to
  block this (`audit_logs`, `scheduler.py::_job_scan_roadmap_risks`, NL-query, AI health-summary,
  notification sync, seed scripts, classification-feedback) are all resolved now, but the one-time
  `audit_logs` HMAC backfill and a deliberate removal pass over the SQLAlchemy fallback branches still
  need to happen first (see "MongoDB Migration Status" / "Security Hardening Status")
- Do not use `Document.get(x)` or `Document.field == value` typed queries against string-stored UUID/reference
  fields (`_id`, `user_id`, etc.) — Beanie coerces to the declared Pydantic type and silently matches nothing.
  Use dict-filtered `.find_one({"_id": id_str})` or `_get_by_str_id()` in `service_bridge.py`
- Do not `await` anything inside `AIOrchestrator`/its 4 agents or `InvoiceNumberer`/`InvoiceBuilder` — that
  call graph is synchronous by design; use `sync_mongo_repository.py`, not Beanie's async API, there
- Do not write a new Mongo document via `Document(...).insert()` for any field that should be a string
  UUID — Pydantic will coerce it to a native UUID/BSON Binary on write. Use
  `Document.get_pymongo_collection()` + raw `insert_one`/`update_one` instead
