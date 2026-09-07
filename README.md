# BIAT IT — Billing Agent v3

Intelligent invoice automation system for BIAT IT (bank subsidiary in Tunisia).

Processes supplier and client invoices: OCR/LLM extraction → classification → validation → accounting journal entries → budget tracking → CAPEX amortisation.

> **Data residency constraint:** All LLM inference is local-only via Ollama. No invoice data is ever sent to a cloud API (OpenAI, Anthropic, Groq, etc.). This is a compliance requirement for a banking subsidiary.

---

## UI

React + FastAPI is the only UI — `PYTHONPATH=backend uvicorn api.main:app --reload`
(backend) + `npm run dev` in `frontend/` (frontend). There used to also be a
Streamlit app (`app/Home.py`); it was removed from this repo before this doc
was last synced — do not look for it.

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.14 |
| Node.js | 20+ |
| Tesseract OCR | 5.x |
| Ollama | latest |
| MongoDB | via `docker compose up -d mongo` (primary DB — see step 3) |

**Two databases are required, not one.** MongoDB is primary for almost
everything (invoices, journal entries, users, roadmap, budget, audit log,
...). SQLite (via SQLAlchemy/Alembic) is still required too — several
routers (`audit.py`, `review.py`, `security.py`, others) have live,
deliberately-kept SQL-backed code paths that haven't been migrated yet. Skip
either one and parts of the app will fail or silently show stale/empty data.

---

## Quick start

### 1. Python environment

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Ollama model

```bash
ollama pull qwen2.5:3b
# ollama serve must be running on http://localhost:11434
```

### 3. Databases — Mongo + SQLite migrations + seed

Start MongoDB (primary DB for almost everything — see Prerequisites):
```bash
docker compose up -d mongo   # runs with --auth; see .env for MONGO_ROOT_USER/PASSWORD
```

SQLite schema is managed by **Alembic** (still required — several routers
have live SQL-backed code paths). Run migrations before starting the server.

```bash
# Apply all pending migrations (creates full schema on a fresh DB)
alembic upgrade head

# Seed with realistic demo data — writes to MongoDB, idempotent (safe to
# re-run; does NOT wipe the database, unlike older versions of this script)
python scripts/seed_demo.py
```

#### Migration commands reference

```bash
alembic current                              # check current DB revision
alembic history                              # full migration history
alembic downgrade -1                         # roll back one migration
alembic revision --autogenerate -m "desc"    # new migration after ORM change
alembic stamp head                           # stamp existing DB without running
```

> **Important:** Never run `alembic upgrade head` automatically on startup in
> production. Schema changes in a banking system require a deliberate, reviewed
> deployment step.

Seed options:
```bash
python scripts/seed_demo.py            # idempotent upsert (default — safe to re-run, does not wipe)
python scripts/seed_demo.py --append   # kept only for CLI compatibility; no effect (writes are always idempotent now)
python scripts/seed_demo.py --dry-run  # validate imports only, no writes
```

To reset back to a clean demo state (e.g. before a rehearsal/demo, if the
data has drifted from manual testing) rather than just adding to it:
```bash
python scripts/reset_demo.py --dry-run  # preview what would be cleared
python scripts/reset_demo.py --yes      # clear demo collections + local upload/email
                                         # artifacts, then re-run all seeders
```
Only clears what the seeders themselves own (invoices, journal entries,
projects, risks, roadmap, budget lines, CAPEX assets, derived audit
snapshots/notifications) plus `data/uploads/` and `data/email_outbox/` —
never `users`, `audit_logs`, sessions, or anything else you weren't asked
to reset.

### 4. FastAPI backend

```bash
PYTHONPATH=backend uvicorn api.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

### 5. React frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

---

## Two terminals — quick reference

```
Terminal 1 (backend)                   Terminal 2 (frontend)
─────────────────────────────────────  ──────────────────────
source .venv/bin/activate              cd frontend
PYTHONPATH=backend uvicorn \           npm run dev
  api.main:app --reload --port 8000
→ API on :8000                         → UI on :5173
```

---

## Docker deployment

The steps above are for local development (separate Python venv + Vite dev
server). For a single-command deployment, `docker-compose.yml` builds one
combined image (`app`) serving both the compiled React SPA and the FastAPI
API on the same origin, plus a `mongo` service:

```bash
cp .env.example .env   # then fill in real secrets — see "Key configuration" below
docker compose up -d --build
docker compose exec app alembic upgrade head   # first boot only — see below
```

**The `alembic upgrade head` step is required on first boot and is not run
automatically.** The container's entrypoint only calls `init_db()`, which is
a deliberate no-op for a file-based SQLite DB (see the "Important" note under
"Quick start" above — no auto-migrations on startup in a banking system).
`/api/health` will still report healthy on a completely empty SQLite file
(it only checks the connection, not that tables exist) — the gap only
surfaces as a "no such table" error the first time a SQLite-backed route
(`audit.py`, `review.py`, `security.py`, `invoices.py::get_pipeline_status`)
is actually hit. Run the migration once after the first `up -d --build` on
any new volume; it's a no-op (already at `head`) on subsequent restarts.

`app` waits on Mongo's healthcheck before starting. Ollama is **not**
containerized (data residency — see "Prerequisites") and must already be
running on the host; the container reaches it via `host.docker.internal`
(works natively on Docker Desktop for Mac/Windows, and via the
`extra_hosts: host-gateway` entry already in `docker-compose.yml` on Linux).
See Diagram 19 (`docs/diagrams/19_deploiement_docker_compose.md`) for the
full topology.

**Installing Ollama on a fresh Linux server** (no Docker Desktop, so no GUI
installer): install it once on the host, then pull the model, before running
`docker compose up`:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &              # or: systemctl enable --now ollama, if the installer set up a service
ollama pull qwen2.5:3b
```

```bash
docker compose logs -f app        # tail the API/SPA container
docker compose down               # stop (add -v to also drop named volumes)
```

**`mailhog` (dev-only fake SMTP server) does not start by default.** It's
gated behind the `dev` Compose profile — `docker compose up -d --build`
above only starts `mongo` + `app`. Its web UI has no authentication and
displays every email sent through it, including OTP codes and password
reset links, so it must never run on anything reachable beyond your own dev
machine:
```bash
docker compose --profile dev up -d mailhog   # local dev only
```
For a real deployment, don't use this profile — set `SMTP_HOST`/`SMTP_PORT`
(and `SMTP_USERNAME`/`SMTP_PASSWORD` if needed) in `.env` to a real mail
relay instead.

---

## Accounts and roles

There is no demo-account login path anymore — `login()` checks only real
Mongo `users` documents. To get a local account to log in with, either:
create one directly in Mongo (see `_seed_test_users()` in
`backend/tests/integration/test_api_e2e.py` for the exact document shape),
or via `POST /api/admin/users` once you already have an Admin session.

**Known gap**: nothing currently creates the *first* Admin account on a
brand-new database without one already existing — `POST /api/admin/users`
requires an Admin session to call. Until this is solved, bootstrap the
first account by writing directly to Mongo's `users` collection (same
shape as `_seed_test_users()` above).

| Role | Pages accessible |
|------|-----------------|
| **Admin** | All pages + admin panel |
| **Comptable** | All pages except Direction dashboard |
| **Chef de Projet** | Accueil, Dashboard, Factures, Suivi, Facturation, Projets, Budget |
| **Direction** | Accueil, Direction, KPI, Budget, Immobilisations, Requêtes |

---

## Running tests

**Python (1203 tests: 1131 unit + 72 integration):**
```bash
source .venv/bin/activate
.venv/bin/pytest backend/                 # all tests — MUST run from repo root
.venv/bin/pytest backend/tests/unit/      # unit only (mocked deps)
.venv/bin/pytest backend/tests/integration/  # integration only (real Mongo test DB, needs Tesseract)
.venv/bin/pytest backend/ --tb=short -q   # compact output
```

**Frontend (Vitest + Testing Library):**
```bash
cd frontend
npm test            # run once
npm run test:watch  # watch mode
```

---

## Lint

```bash
.venv/bin/ruff check backend/src/ backend/api/ backend/tests/
```

---

## Project structure

```
internship_biat/
├── backend/
│   ├── api/                  # FastAPI routers + auth + scheduler
│   ├── src/
│   │   ├── agent/            # config_loader.py — wires AIComponents (build_ai_components())
│   │   ├── ai_agents/
│   │   │   ├── invoice_processing_orchestrator.py  # InvoiceProcessingOrchestrator — the real invoice-processing entry point
│   │   │   ├── extraction_agent.py, classification_agent.py,
│   │   │   │   anomaly_agent.py, accounting_agent.py   # the 4 sequential agents
│   │   │   ├── risk_agent.py, insight_agent.py  # roadmap risk scan, health-summary
│   │   │   ├── rag/          # PCE vector store for duplicate detection
│   │   │   ├── base_agent.py # BaseAgent abstract class
│   │   │   ├── ollama_client.py  # OllamaClient singleton
│   │   │   └── agent_schemas.py  # AgentResult, OrchestratorResult, PipelineStep
│   │   ├── models/           # InvoiceRecord, Asset, JournalEntry, enums
│   │   ├── storage/          # ORM models (SQLite/legacy) + sync_mongo_repository.py (primary)
│   │   ├── extraction/       # PDF/OCR/LLM hybrid extractor
│   │   ├── classification/   # AccountingCoder, CostCatalog, ML classifier
│   │   ├── validation/       # field, coherence, duplicate, anomaly checks
│   │   ├── accounting/       # double-entry journal entry generator
│   │   ├── billing/          # client invoice generation
│   │   ├── budget/           # BudgetTracker (planned vs actual)
│   │   └── capex/            # depreciation (linear/degressive), AssetRepository
│   └── tests/
│       ├── unit/             # 52 files, mocked deps
│       └── integration/      # 3 files, real disposable Mongo test DB, mocked LLM
├── scripts/
│   ├── seed_demo.py, seed_budget_actuals.py, seed_projects.py,
│   │   seed_risks.py, seed_roadmap.py  # Mongo-native, idempotent seeders
│   │   # (does NOT create user accounts — no demo accounts anymore, see below)
│   ├── review_queue.py       # terminal review UI (reads SQLite — see Prerequisites)
│   └── run_api.py            # FastAPI entry point
│   # run_agent.py (headless daemon) removed 2026-07 — superseded by the API+InvoiceProcessingOrchestrator path
│   # seed_users.py removed — created hardcoded-password demo Mongo accounts
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── admin/        # HabilitationsPage, InscriptionPage
│       │   ├── auth/         # Login, ForgotPassword, ResetPassword, ChangerMotDePasse, Profile
│       │   ├── comptabilite/ # Echeancier, Facturation, GrandLivre, Journaux, Suivi
│       │   ├── factures/     # InvoiceDetail, InvoicePipeline, ReviewQueue
│       │   ├── pilotage/     # Budget, Capex, Direction, KPIDashboard
│       │   ├── projets/      # FacturationClientDetail, ProjetDetail, Projets
│       │   └── transversal/  # AIActivity, Audit, Requetes, Risques, Roadmap, Security
│       ├── api/              # typed API client (endpoints.ts)
│       ├── components/       # Layout, Sidebar, NotificationBell, shared UI
│       └── context/          # AuthContext (JWT + role management)
├── config/
│   ├── settings.yaml         # DB URL, OCR engine, LLM model, thresholds
│   ├── cost_catalog.yaml     # 33 accounting taxonomy entries
│   └── budget_plan.yaml      # annual budget by catalog ID (12 monthly values)
├── data/
│   └── invoices.db           # SQLite (WAL mode) — still required, see Prerequisites
└── backend/alembic/          # SQLite migration scripts
```

---

## Invoice processing pipeline

```
PDF / invoice file
       │
       ▼
 ExtractionAgent ────── native PDF text / OCR (Tesseract) / LLM (Ollama qwen2.5:3b)
       │
       ▼
 ClassificationAgent ── direction rules + CostCatalog (33 entries) + ML fallback
       │
       ▼
 AnomalyAgent ────────  math checks, duplicate detection, anomaly flags
       │                → FLAGGED (human review) or VALIDATED
       ▼
 AccountingAgent ──────  double-entry journal (PCE Tunisien)
                         401/411 · 4366/4367 · 6xxx OPEX · 2xxx CAPEX
                         → JOURNALED
```

Orchestration: `backend/src/ai_agents/invoice_processing_orchestrator.py` — `InvoiceProcessingOrchestrator.process_invoice()`,
invoked from `POST /api/invoices/upload` — this is the only invoice-processing
entry point (an older headless daemon existed until 2026-07; removed as
superseded once confirmed unused in practice).  
API layer: `backend/api/` — FastAPI + uvicorn, all endpoints under `/api/`.  
UI: `frontend/` — React 19 + TypeScript + Vite + Tailwind v4.

---

## Key configuration

`config/settings.yaml` — DB URL, OCR engine, LLM model, thresholds.  
`config/cost_catalog.yaml` — 33 accounting taxonomy entries.  
`config/budget_plan.yaml` — annual budget by catalog ID (12 monthly values).

Override DB with env var:
```bash
DATABASE_URL=sqlite:///./data/other.db PYTHONPATH=backend uvicorn api.main:app
```

---

## Terminal review UI

```bash
python scripts/review_queue.py   # reads SQLite — stale/empty on a Mongo-only environment, see Prerequisites
```

---

## Generate a demo invoice PDF

```bash
python scripts/make_realistic_invoice.py
# writes ./data/demo_invoice.pdf — upload it via POST /api/invoices/upload
# (or the frontend's upload page); there is no folder-watcher anymore
```
