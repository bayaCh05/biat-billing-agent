# BIAT IT — Billing Agent v3

Intelligent invoice automation system for BIAT IT (bank subsidiary in Tunisia).

Processes supplier and client invoices: OCR/LLM extraction → classification → validation → accounting journal entries → budget tracking → CAPEX amortisation.

> **Data residency constraint:** All LLM inference is local-only via Ollama. No invoice data is ever sent to a cloud API (OpenAI, Anthropic, Groq, etc.). This is a compliance requirement for a banking subsidiary.

---

## Two UIs — which one to use

| UI | When to use | How to start |
|----|-------------|--------------|
| **React + FastAPI** (primary) | Full-featured demo, supervisor review, production deployment | `PYTHONPATH=backend uvicorn api.main:app --reload` + `npm run dev` in `frontend/` |
| **Streamlit** (local demo) | Quick local test of the OCR/LLM pipeline without the React app | `streamlit run app/Home.py` |

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.14 |
| Node.js | 20+ |
| Tesseract OCR | 5.x |
| Ollama | latest |

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

### 3. Database — migrations + seed

Schema is managed by **Alembic**. Run migrations before starting the server.

```bash
# Apply all pending migrations (creates full schema on a fresh DB)
alembic upgrade head

# Seed with realistic demo data (4 users, 22 invoices, 5 CAPEX assets,
# 3 projects, 19 livrables, 3 client invoices, roadmap, audit logs)
python backend/scripts/seed_demo.py
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
python backend/scripts/seed_demo.py            # wipe + reseed (default)
python backend/scripts/seed_demo.py --append   # keep existing rows, add new ones
python backend/scripts/seed_demo.py --dry-run  # validate imports only, no writes
```

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

## Demo accounts

| Email | Password | Role |
|-------|----------|------|
| admin@biat-it.com.tn | biat2026! | Admin |
| comptable@biat-it.com.tn | biat2026! | Comptable |
| chef.projet@biat-it.com.tn | biat2026! | Chef de Projet |
| direction@biat-it.com.tn | biat2026! | Direction |

| Role | Pages accessible |
|------|-----------------|
| **Admin** | All pages + admin panel |
| **Comptable** | All pages except Direction dashboard |
| **Chef de Projet** | Accueil, Dashboard, Factures, Suivi, Facturation, Projets, Budget |
| **Direction** | Accueil, Direction, KPI, Budget, Immobilisations, Requêtes |

---

## Running tests

**Python (703 tests):**
```bash
source .venv/bin/activate
.venv/bin/pytest                          # all tests
.venv/bin/pytest backend/tests/unit/     # unit only (mocked deps)
.venv/bin/pytest backend/tests/          # all backend tests
.venv/bin/pytest --tb=short -q           # compact output
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
│   │   ├── agent/            # pipeline.py (pure functions), agent.py (daemon loop)
│   │   ├── ai/
│   │   │   ├── agents/       # 4 pipeline agents: extraction, classification, anomaly, accounting
│   │   │   ├── services/     # RiskAgent (roadmap), InsightAgent (direction dashboard)
│   │   │   ├── rag/          # PCE vector store for duplicate detection
│   │   │   ├── base.py       # BaseAgent abstract class
│   │   │   ├── client.py     # OllamaClient singleton
│   │   │   ├── invoice_pipeline.py  # InvoicePipeline: sequential 4-step runner
│   │   │   └── schemas.py    # AgentResult, OrchestratorResult, PipelineStep
│   │   ├── models/           # InvoiceRecord, Asset, JournalEntry, enums
│   │   ├── storage/          # ORM models, repositories, DB init
│   │   ├── extraction/       # PDF/OCR/LLM hybrid extractor
│   │   ├── classification/   # AccountingCoder, CostCatalog, ML classifier
│   │   ├── validation/       # field, coherence, duplicate, anomaly checks
│   │   ├── accounting/       # double-entry journal entry generator
│   │   ├── billing/          # client invoice generation
│   │   ├── budget/           # BudgetTracker (planned vs actual)
│   │   └── capex/            # depreciation (linear/degressive), AssetRepository
│   ├── scripts/
│   │   ├── seed_demo.py      # full demo data seeder (11 sections)
│   │   ├── run_agent.py      # headless daemon (watches inbox/)
│   │   └── review_queue.py   # terminal review UI
│   └── tests/
│       └── unit/             # 703 tests, all mocked
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
│   └── invoices.db           # SQLite (WAL mode)
└── alembic/                  # DB migration scripts
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

Core runner: `backend/src/ai/invoice_pipeline.py` — `InvoicePipeline.process_invoice()`.  
Pure functions: `backend/src/agent/pipeline.py` — used by the Streamlit UI and the headless daemon.  
API layer: `backend/api/` — FastAPI + uvicorn, all endpoints under `/api/`.  
UI: `frontend/` — React 18 + TypeScript + Vite + Tailwind v4.

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

## Streamlit app (legacy UI)

```bash
streamlit run app/Home.py   # :8502
```

---

## Headless daemon

```bash
python backend/scripts/run_agent.py     # watches ./inbox/ for new PDFs
python backend/scripts/review_queue.py  # terminal review UI
```

---

## Generate a demo invoice PDF

```bash
python backend/scripts/make_realistic_invoice.py
# outputs a supplier PDF to ./inbox/ ready for upload
```
