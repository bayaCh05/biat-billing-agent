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
Mock backends are allowed in tests and the `live=false` demo-upload mode only
(`POST /api/invoices/upload` with `live=false` — see `api/routers/invoices.py`).
Violating this is a compliance failure for a banking subsidiary.

---

## Working Conventions

- **Reports and prompts in French.** Status updates, findings, and questions
  to the project owner should be written in French — this is an internship at
  a Tunisian bank and the owner works in French. Code, identifiers, commit
  messages, and this file stay in English/technical French mix as already
  established below.
- **Stage multi-step work explicitly, wait for validation before acting.** For
  any non-trivial cleanup/refactor pass (multiple files, deletions, dependency
  or doc changes), break the work into steps, give a detailed inventory of
  what was found at each step, and wait for explicit go-ahead before making
  changes — don't bundle "here's what I found" and "here's what I already did"
  into one message.
- **Never delete or rename a file without explicit confirmation for that
  specific file/action** — a prior approval for one file or one category does
  not extend to others found later in the same pass.
- **One atomic commit per lot, never automatic.** Each logically-distinct
  change (a dependency fix, a dead-code removal, a doc correction) gets its
  own commit with its own message — don't squash unrelated fixes together,
  and don't commit without being asked to for that lot.

---

## Runtime

| Item | Value |
|------|-------|
| Python | 3.14.2 (`.venv/bin/python3.14`) |
| Frontend | React 19 + Vite (`frontend/`) — calls the FastAPI backend over HTTP. There is no Streamlit app in this repo (removed before this doc was last synced — see "Project Structure") |
| SQLAlchemy | 2.0.50 |
| Pydantic | 2.13.4 |
| Pandas | 3.0.3 |
| pytest | 9.0.3 |
| DB (legacy/still-live) | SQLite at `data/invoices.db` (WAL mode) |
| DB (primary, in migration) | MongoDB via Beanie/Motor — `docker-compose` service `biat_mongo`, `MONGODB_URI`/`MONGODB_DB` in `.env`. **Auth required**: `mongod --auth`, credentials via `MONGO_ROOT_USER`/`MONGO_ROOT_PASSWORD` in `.env` (embedded in `MONGODB_URI` as `mongodb://user:pass@host/?authSource=admin`) |
| LLM | Ollama `qwen2.5:3b` on `http://localhost:11434` |
| OCR | Tesseract (not EasyOCR — not installed) |
| RAG (Classification Pass C) | ChromaDB (local vector store) + `sentence-transformers` for embeddings — `backend/src/ai_agents/rag/embedder.py` (`PCEEmbedder`), `pce_vectorstore.py` (`PCEVectorStore`). Both lazy-imported (heavy ML deps) and declared in `pyproject.toml` |

**Two persistence layers coexist.** See "MongoDB Migration Status" below before touching any storage code — reads/writes for most domains now go to MongoDB, not SQLite, and the rule for which one differs by file.

---

## Commands

```bash
# Activate virtual environment (always required first)
source .venv/bin/activate

# Run tests — MUST run from repo root, not backend/ (relative config paths break otherwise)
.venv/bin/pytest backend/                 # ~1020 tests, 0 skipped
.venv/bin/pytest backend/tests/unit/      # unit only
.venv/bin/pytest backend/tests/integration/  # integration only (needs Tesseract)
.venv/bin/pytest backend/ --tb=short -q   # compact output

# Run FastAPI backend (the production interface)
python scripts/run_api.py                 # port 8000, --reload for hot-reload

# Run the frontend (separate terminal)
cd frontend && npm run dev                # Vite dev server, or `npm run dev:full` to also start the API

# Human review queue (terminal UI) — reads SQLite; see "MongoDB Migration
# Status" below, this shows only invoices written via the (now-deleted)
# daemon path, so it will be empty/stale against a Mongo-only environment
python scripts/review_queue.py

# Generate demo invoice PDF
python scripts/make_realistic_invoice.py

# Lint
.venv/bin/ruff check backend/src backend/api backend/tests

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
> of these is `backend/` (i.e. `backend/src/ai_agents/orchestrator.py`, not
> `src/ai_agents/orchestrator.py`). There is also a full FastAPI REST API at
> `backend/api/` (routers under `backend/api/routers/`: `invoices.py`, `auth.py`,
> `admin.py`, `users.py`, `security.py`, `billing.py`, `payments.py`, `budget.py`,
> `capex.py`, `projet_budget.py`, `roadmap.py`, `risks.py`, `livrables.py`,
> `notifications.py`, `review.py`, `journal.py`, `suivi.py`, `ai.py`, `audit.py`,
> `kpi.py`, `nl_query.py`, `projects.py`, plus
> `backend/api/scheduler.py` for nightly jobs). `POST /api/invoices/upload` runs
> invoices through `backend/src/ai_agents/orchestrator.py::AIOrchestrator` (see
> below) — this is the **only** invoice-processing entry point left. The old
> headless daemon (`scripts/run_agent.py`, `agent/pipeline.py::process_invoice()`,
> `agent/agent.py::InvoiceAgent`) and the Streamlit app that used to call it
> directly were both deleted (2026-07, "Lot B" SQLAlchemy cleanup) — they were
> confirmed superseded by the API+AIOrchestrator path in practice before removal.
> Below this note, "Orchestrator... deleted in v3" refers to a different, older,
> unrelated class — `AIOrchestrator` is current and heavily used; do not read
> that note as discouraging it.

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
       → ai_agents/          ← AIOrchestrator + its 4 sync agents
       → api/                ← FastAPI routers
frontend/                    ← separate React/Vite app, calls api/ over HTTP
```

### Key design: `AIOrchestrator` coordinates synchronous agents

Invoice processing is **not** a set of free pipeline functions anymore (that
was `agent/pipeline.py::process_invoice()`, deleted along with the daemon —
see the path note above). `backend/src/ai_agents/orchestrator.py::AIOrchestrator`
is a class whose `process_invoice(invoice)` method runs an invoice through 4
agents in sequence, each doing one stage:

```python
from src.ai_agents.orchestrator import AIOrchestrator

orchestrator = AIOrchestrator(components, session)  # components: AIComponents, session: SQLAlchemy Session (see below)
result = orchestrator.process_invoice(invoice)       # extraction → classification → anomaly → accounting/journal
```

`AIOrchestrator` is deliberately **synchronous** ("Built as synchronous to
match the existing FastAPI + SQLAlchemy patterns" — see its docstring) even
though it reads/writes almost everything via Mongo — it uses the sync
`pymongo`-based repositories in `src/storage/sync_mongo_repository.py`
(`SyncMongoInvoiceRepository`, `SyncMongoJournalRepository`), never Beanie's
async API. The `session: Session` (SQLAlchemy) constructor arg is a real,
still-used parameter — passed through to some agents' `.run()` calls — not a
fallback pattern; do not try to remove it.

### Build the components

```python
from src.agent.config_loader import build_ai_components

components = build_ai_components()   # AIComponents — extractor, coder, classifier,
                                      # field_validator, coherence_checker,
                                      # duplicate_detector, anomaly_detector,
                                      # entry_generator, cost_catalog
try:
    orchestrator = AIOrchestrator(components, session)
    ...
finally:
    components.close()   # no-op today — kept so call sites don't need to change
                          # if a future component ever needs cleanup again
```

`AIComponents` (in `agent/config_loader.py`, replacing the old
`PipelineComponents`) holds only stateless business-logic objects — nothing
SQLAlchemy-bound. `api/deps.py::get_components()` is the real call site
(`POST /api/invoices/upload`, `ai.py`, `scheduler.py`'s two AI jobs all use it).

---

## Project Structure

```
src/
  agent/
    config_loader.py     # ← wires AIComponents from settings.yaml (build_ai_components())
  ai_agents/
    orchestrator.py      # ← AIOrchestrator — the real invoice-processing entry point
    extraction_agent.py, classification_agent.py, anomaly_agent.py, accounting_agent.py
    risk_agent.py, insight_agent.py  # secondary flows (roadmap risk scan, health-summary)
    rag/
      embedder.py         # PCEEmbedder (sentence-transformers)
      pce_vectorstore.py  # PCEVectorStore (ChromaDB) — used by Classification Pass C
      rag_classifier.py   # RAGClassifier — top-K similarity lookup
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
    classifier.py, matcher.py  # RAG-assisted Pass C helpers
  cost_catalog/
    catalog.py           # CostCatalog.from_yaml() — fuzzy keyword matching (NOT under classification/)
  validation/            # field_validator, coherence_checker, duplicate_detector, anomaly_detector
  accounting/            # entry_generator.py — journal entry patterns
  billing/               # client invoice generation + PDF (fpdf2)
  budget/                # BudgetTracker (planned vs actual), CostAnalyzer
  capex/                 # DepreciationCalculator (linear/degressive), AssetRepository
  suivi/                 # aggregator, lifecycle_tracker (orphaned since the daemon/Streamlit
                          # removal — zero live callers, kept only for its own tests), reconciler
  notifications/
    notification_service.py  # flagged-invoice notifications (GET /notifications/*)
  query/
    nl_query_engine.py   # NLQueryEngine — NL → MongoDB aggregation pipeline (POST /nl-query)
  services/              # risk_service.py (calculate_criticite), ldap_service.py, ldif_parser.py,
                          # email_service.py, audit_service.py (IP/UA helpers only — see
                          # "MongoDB Migration Status" re: log_action()), mock_ldap_auth.py,
                          # password_verification_service.py
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

frontend/                # separate top-level dir, NOT under backend/ — React 19 + Vite
  src/
    pages/, components/, api/, context/  # calls backend/api/ over HTTP, no direct Python coupling
  package.json            # npm run dev (Vite only) / npm run dev:full (Vite + uvicorn)

scripts/
  review_queue.py         # terminal review UI (reads SQLite — see "MongoDB Migration Status")
  make_realistic_invoice.py  # demo PDF generator
  seed_demo.py, seed_users.py, seed_budget_actuals.py, seed_projects.py,
  seed_risks.py, seed_roadmap.py  # Mongo-native, idempotent (see "MongoDB Migration Status")
  # run_agent.py (headless daemon) deleted 2026-07 — see Architecture path note above

tests/                    # ~1020 tests total, 0 skipped
  unit/                   # 42 files, mocked dependencies
  integration/            # test_api_e2e.py (real Mongo test DB + SQLite for get_session
                           # plumbing), test_orchestrator_audit_trail.py, test_avatar_rate_limit.py
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
  `seed_budget_actuals.py`, `seed_projects.py`, `seed_risks.py`,
  `seed_roadmap.py`) — write to MongoDB via `sync_mongo_repository.py`
  (`SyncMongo*Repository.save()` plus `create_user_sync`,
  `save_charte_projet_sync`, `save_phase_sync`, `save_livrable_sync`,
  `save_ligne_budget_sync`, `save_feuille_de_route_sync`, `save_risque_sync`).
  **Every write is idempotent (upsert-by-id / skip-if-exists) — these scripts
  no longer wipe the database by default.** That was safe when they targeted a
  disposable SQLite file; it is not safe now that they write to the same
  shared MongoDB the app reads from. `--append` is kept only for CLI
  compatibility and has no effect on this idempotency. `seed_projects.py`,
  `seed_risks.py`, and `seed_roadmap.py` were migrated off SQLAlchemy/SQLite
  onto this Mongo-native path in a 2026-07 cleanup pass — before that they
  silently wrote `CharteProjetORM`/`PhaseORM`/`RisqueORM`/`FeuilleDeRouteORM`
  rows into SQLite while the live roadmap/risk/project routers only read from
  Mongo, so running them had no visible effect on the real UI. The former
  `scripts/seed_risks_par_projet.py` (an undocumented, unmerged duplicate of
  `seed_risks.py` seeding the same 3 demo projects) was folded into
  `seed_risks.py` and deleted in the same pass.
- **`PATCH /ai/invoices/{id}/classification`** (classification-feedback endpoint)
  — reads/writes the invoice via `SyncMongoInvoiceRepository`, writes feedback via
  `save_classification_feedback_sync()`/`count_classification_feedback_sync()`
  into the `classification_feedback` Mongo collection
  (`ClassificationFeedbackDocument` existed since Phase 2 but was never actually
  written to before this — the endpoint previously only wrote to a SQLite-only
  table, dormant at 0 rows since real uploads through the API never landed there).

### What's still SQLite-only (do not assume these are in Mongo)

- **`main.py`'s demo-user reseeding** (`seed_demo_users`/`refresh_demo_passwords`,
  run on every startup) — writes SQLite `users`. Since login is Mongo-native now
  and the daemon/Streamlit are gone (deleted, see Architecture path note), this
  looks like dead weight rather than something to preserve — a deletion
  candidate, not a migration target, still not removed.
- **`api/routers/audit.py::compute_integrity_summary`**'s one-time HMAC backfill
  (`session.commit()` after backfilling `row_hash` on any pre-HMAC-era SQLite row
  still `NULL`) — as of 2026-07, 0 rows have `NULL` `row_hash` anymore (the
  backfill already ran, as a side effect of `/audit/verify-integrity` or
  `/security/summary` being hit normally) — this is done. **Separate, more
  serious finding from the same check, updated 2026-07-13**: verifying all 708
  rows' HMAC against the current `.env` `JWT_SECRET`/`AUDIT_HMAC_SECRET` now
  shows **708/708 rows fail** `verify_row_hash()` (re-verified live against
  `data/invoices.db` on 2026-07-13 — this is worse than the 569/708 figure
  first recorded here). Root cause, confirmed via commit history rather than
  guessed: commit `c1dfaf0` (2026-07-02) fixed a real HMAC bug where an inline
  `.env` comment on the `AUDIT_HMAC_SECRET` line was being parsed as part of
  the secret value itself; commit `2775772` (2026-07-10, "remove hardcoded
  JWT_SECRET fallback, enforce validation at startup") then replaced the
  previous default/fallback secret with a newly-validated one. Every row
  written before the 07-10 rotation was hashed under a secret that no longer
  exists anywhere, so **all** of them now fail against today's secret — this
  is a full one-time key rotation, not a mysterious partial-window anomaly,
  and not tampering. Full writeup: `docs/audit_hmac_incident.md`.
  `data/invoices.db` has deliberately **not** been touched to "fix" this. If
  asked to fix the audit integrity score, do not silently recompute
  `row_hash` over these rows — that defeats the point of an HMAC tamper
  check (see `docs/audit_hmac_incident.md` for why this is documented as a
  known limitation rather than resolved by re-signing). `/audit/verify-integrity`
  and `/security/summary` currently report 708 "tampered" entries (100%) on
  the real environment as a result; treat this as a known, documented,
  unresolved finding, not a bug to patch reflexively.
- **The audit-log HMAC hash chain** (`row_hash` column, `api/security/audit_integrity.py`,
  `AUDIT_INTEGRITY_CHECK` endpoint) — this is structurally SQLite-specific (tamper-evidence
  chain over that table's own rows). No Mongo equivalent exists yet; this is an open
  design question, not a pending mechanical migration. `verify_integrity_native()`
  computes an equivalent check over Mongo's `audit_logs` documents and
  `compute_integrity_summary()` merges both into one score — see that function's
  docstring ("one compliance trail split across two stores, not two independent ones").

**Consequence: SQLite cannot be removed yet, but the reason has narrowed further.**
Every live production gap that had **zero** Mongo equivalent (NL-query, AI
health-summary, notification sync, seed scripts, health checks,
classification-feedback, CI) was closed in Lot A. The daemon and its
SQLAlchemy-only dependents (`agent/pipeline.py`, `agent/agent.py`,
`ProjectRepository`, `MonthlyInvoiceBuilder`, `AutoCorrector`, `CostAllocator`,
`FlagEscalator`, the JSON/CSV exporters, `FolderWatcher`, the SQLAlchemy
`JournalRepository`) were deleted in Lot B (2026-07). What's left blocking a
full SQLite read-only/removal ("Lot 10") now: the HMAC-mismatch finding above
(needs a decision, not just code), and the SQLAlchemy fallback branches that
still exist in `api/deps.py`/`storage/db.py`/`storage/repository.py` and a
handful of routers with **deliberately-kept** SQL paths independent of the
daemon question — `audit.py` (this HMAC chain), `review.py::get_review_queue`
(a facture flagged before the daemon's deletion could still only exist in
SQLite), `invoices.py::get_pipeline_status`'s journal-entry completeness
guard, `budget.py`/`security.py`/others' `get_session` dependency. Do not set
SQLite read-only or delete these remaining SQLAlchemy code paths without a
deliberate, per-router removal pass and explicit confirmation each time.

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
inv.status                # InvoiceStatus enum (RECEIVED → ... → JOURNALED/PAID)
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

---

## Accounting (PCE Tunisien)

Plan Comptable des Entreprises tunisien (PCE), établi par la loi n° 96-112 du
30 décembre 1996 relative au système comptable des entreprises. Key accounts:
- `401` Fournisseurs, `411` Clients
- `4366` TVA déductible, `4367` TVA collectée
- `6xxx` Charges (OPEX), `2xxx` Immobilisations (CAPEX)
- `6811` Dotations amortissements, `28xx` Amortissements cumulés
- TVA rates allowed: 0%, 7%, 13%, 19% — validate against `tva_rates_allowed` in settings

**All TND amounts are rounded/stored to 3 decimal places** (the millime is
1/1000 of a dinar — Tunisia's smallest currency subunit), not 2. Enforced via
`round(x, 3)` throughout — `classification/accounting_coder.py` (confidence
scores excepted), `accounting/entry_generator.py` (ht/tva/ttc), `models/journal.py`
(`total_debit`/`total_credit`, and the `< 0.005 TND` double-entry tolerance is
half a millime). Don't round to 2 decimals anywhere in the money path.

---

## Enums Reference

### InvoiceStatus (state machine)
Enum definition (`models/enums.py`) still lists the full historical set:
`RECEIVED → EXTRACTING → EXTRACTED → CLASSIFYING → CLASSIFIED → VALIDATING → VALIDATED/FLAGGED → EXPORTING → EXPORTED → JOURNALING → JOURNALED → PAID/COLLECTED`.

**What `AIOrchestrator.process_invoice()` (the only live writer) actually
transitions through today** is a subset — it does NOT set the `-ING`
in-progress statuses at all (those were `agent/pipeline.py`'s stage-start
markers, deleted with the daemon), and it skips `EXPORTING`/`EXPORTED`
entirely (no JSON/CSV export step anymore — `pipeline.py::export_file()` and
the exporters that backed it were also deleted):
`RECEIVED → EXTRACTED → CLASSIFIED → VALIDATED (or FLAGGED) → JOURNALED`.
`JOURNALED` is the real happy-path terminal status for a successfully
processed invoice — set directly by `AIOrchestrator`'s accounting step, no
intermediate `JOURNALING`. `EXPORTED` still appears in code that reads
historical/legacy data (`ml_classifier.py`'s training-label set,
`suivi/reconciler.py`, `suivi/aggregator.py`, `scheduler.py`'s retrain job
all still treat it as "successfully processed" alongside `VALIDATED`/
`JOURNALED`/`PAID`) but nothing in the live path produces it anymore.

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
- Integration tests (`backend/tests/integration/`): `test_api_e2e.py` and
  `test_orchestrator_audit_trail.py` run against a real, disposable Mongo test
  database (`MONGODB_DB=biat_billing_test*`, dropped in a session-scoped
  fixture teardown) plus `sqlite:///:memory:` only for the `Depends(get_session)`
  plumbing still wired into a few routers (`audit.py`, `review.py`,
  `security.py`, ...) — not for the invoice-processing path itself, which is
  Mongo-only. Only the LLM backend is mocked.
- 5 PyMuPDF C-library `DeprecationWarning`s in test output are harmless — ignore
- The SQLAlchemy `InvoiceRepository` (`storage/repository.py`) is only
  imported by `api/routers/review.py` now (a deliberately-kept exception —
  see "MongoDB Migration Status") — its test mock must include
  `count_by_status` and `count_auto_approved`
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
- Obsolete test skip fixed in the old `test_pipeline_e2e.py` (`test_mark_paid_advances_supplier_invoice`
  was silently skipping every run once `pipeline.py` added the `post_journal()`
  stage — see JOURNALED in "InvoiceStatus" below). That whole file was later
  deleted (2026-07, Lot B) — it tested `agent/pipeline.py::process_invoice()`,
  confirmed to have zero live callers once the daemon was removed. The fix
  itself was real at the time; noted here only for history.
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
- Lot B (2026-07): SQL fallback branches removed from 14 routers; the daemon
  (`scripts/run_agent.py`, `agent/pipeline.py`, `agent/agent.py`) and its
  SQLAlchemy-only dependents (`ProjectRepository`, `MonthlyInvoiceBuilder`,
  `AutoCorrector`, `CostAllocator`, `FlagEscalator`, the JSON/CSV exporters,
  `FolderWatcher`, the SQLAlchemy `JournalRepository`) deleted outright —
  `AIOrchestrator` was first decoupled onto a new SQLAlchemy-free
  `AIComponents` (see Architecture above) so the real upload path kept
  working throughout. `ingestion/` (including `base.py`, its last
  remaining file with zero implementers) was deleted in this same commit
  alongside `FolderWatcher` — there is no `backend/src/ingestion/`
  directory left at all as of Lot B.

**Still open:**
- Refresh token rotation (jti reusable up to 7 days) — explicitly deprioritized
- "Lot 10" (SQLite → read-only → removal) — the functional gaps that used to
  block this are closed, and the daemon-specific SQLAlchemy code is gone
  (Lot B above), but SQLite/SQLAlchemy itself is still load-bearing for
  `audit.py`, `review.py`, `security.py` and a few other routers with
  deliberately-kept SQL paths unrelated to the daemon — see "MongoDB
  Migration Status" for the current, narrower list. Final removal step
  explicitly needs supervisor sign-off regardless.
- **Audit-log HMAC mismatch (2026-07, unresolved, documented as known
  limitation)**: 708 of 708 `audit_logs` rows (100%) fail HMAC verification
  against the current `JWT_SECRET`, as of a live re-check on 2026-07-13.
  Confirmed root cause via commit history: the `JWT_SECRET` hardening on
  2026-07-10 (`2775772`) rotated the effective secret away from the old
  default/fallback value, and every row written before that rotation was
  hashed under a secret that no longer exists — a genuine one-time key
  rotation, not tampering. Full incident note:
  `docs/audit_hmac_incident.md`. Do not silently "fix" this by recomputing
  `row_hash` — see that doc for why re-signing would defeat the purpose of
  the tamper check instead of resolving the incident.

---

## What NOT to Do

- Do not use the old `Orchestrator` class from pre-v3 (deleted) or reference
  `process_invoice()`/`PipelineComponents`/`agent/pipeline.py` — all deleted
  2026-07 along with the daemon (see Architecture above). Use `AIOrchestrator`
  (`ai_agents/orchestrator.py`) with `AIComponents`
  (`agent/config_loader.py::build_ai_components()`) instead — that's what
  `POST /api/invoices/upload` actually runs.
- Do not use `AccountingCoder(rules=...)` — v1 API, removed; use `AccountingCoder(catalog=CostCatalog)`
- Do not use `CostCatalog.load()` — the correct classmethod is `CostCatalog.from_yaml()`
- Do not call any cloud LLM with real invoice data — data residency violation
- Do not import `EasyOCREngine` from `ocr_engine` — it moved to `extras_ocr.py`
- Do not set SQLite to read-only or remove the *remaining* SQLAlchemy code paths
  (`storage/db.py`, `storage/repository.py`, `orm_models*.py`, `alembic/`, or
  the deliberately-kept SQL paths in `audit.py`/`review.py`/`security.py`/etc.)
  without a deliberate, per-router removal pass and explicit confirmation each
  time — the daemon-specific SQLAlchemy code is already gone (Lot B, 2026-07),
  but these remaining ones serve live, unrelated purposes (see "MongoDB
  Migration Status")
- Do not use `Document.get(x)` or `Document.field == value` typed queries against string-stored UUID/reference
  fields (`_id`, `user_id`, etc.) — Beanie coerces to the declared Pydantic type and silently matches nothing.
  Use dict-filtered `.find_one({"_id": id_str})` or `_get_by_str_id()` in `service_bridge.py`
- Do not `await` anything inside `AIOrchestrator`/its 4 agents or `InvoiceNumberer`/`InvoiceBuilder` — that
  call graph is synchronous by design; use `sync_mongo_repository.py`, not Beanie's async API, there
- Do not write a new Mongo document via `Document(...).insert()` for any field that should be a string
  UUID — Pydantic will coerce it to a native UUID/BSON Binary on write. Use
  `Document.get_pymongo_collection()` + raw `insert_one`/`update_one` instead
