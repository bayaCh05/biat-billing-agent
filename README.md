# BIAT IT — Billing Agent v3

Intelligent invoice automation system for BIAT IT (bank subsidiary in Tunisia).

Processes supplier and client invoices: OCR/LLM extraction → classification → validation → accounting journal entries → budget tracking → CAPEX amortisation.

> **Data residency constraint:** All LLM inference is local-only via Ollama. No invoice data is ever sent to a cloud API (OpenAI, Anthropic, Groq, etc.). This is a compliance requirement for a banking subsidiary.

---

## Two UIs — which one to use

| UI | When to use | How to start |
|----|-------------|--------------|
| **React + FastAPI** (primary) | Full-featured demo, supervisor review, production deployment | `uvicorn api.main:app --reload` + `npm run dev` in `frontend/` |
| **Streamlit** (local demo) | Quick local test of the OCR/LLM pipeline without the React app | `streamlit run app/Home.py` |

The React app is served from the Docker container at port 8000. The Streamlit app is a standalone tool for testing the core pipeline.

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

# Required for uvicorn --reload to resolve project modules in child processes
echo "/path/to/internship_biat" > .venv/lib/python3.14/site-packages/biat_project.pth
```

### 2. Ollama model

```bash
ollama pull qwen2.5:3b
# ollama serve must be running on http://localhost:11434
```

### 3. Database — init + seed

```bash
# Initialise schema
python -c "from src.storage.db import build_engine, init_db; init_db(build_engine('sqlite:///./data/invoices.db'))"

# Seed with realistic demo data
python scripts/seed_demo.py
```

Seed options:
```bash
python scripts/seed_demo.py            # wipe + reseed (default)
python scripts/seed_demo.py --append   # keep existing rows, add new ones
python scripts/seed_demo.py --dry-run  # validate config only, no writes
```

Seeds: 25 supplier invoices (various statuses), 12 journal entries, 5 CAPEX assets, 30 depreciation entries, 3 client invoices.

### 4. FastAPI backend

```bash
uvicorn api.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

### 5. React frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

---

## Roles and access

Log in with any of these demo accounts on the login screen:

| Role | Pages accessible |
|------|-----------------|
| **Comptable** | All pages except Direction dashboard |
| **Chef de Projet** | Accueil, Dashboard, Factures, Suivi, Facturation, Projets, Budget |
| **Direction** | Accueil, Direction, KPI, Budget, Immobilisations, Requêtes |

---

## Running tests

**Python (629 tests):**
```bash
source .venv/bin/activate
.venv/bin/pytest                      # all tests
.venv/bin/pytest tests/unit/         # unit only (mocked deps)
.venv/bin/pytest tests/integration/  # integration (needs Tesseract)
.venv/bin/pytest --tb=short -q       # compact output
```

**Frontend (35 tests — Vitest + Testing Library):**
```bash
cd frontend
npm test           # run once
npm run test:watch # watch mode
```

Tests cover: `formatTND` / `formatDate` / `formatVariance` utilities, `AuthContext` localStorage persistence and role-to-name mapping, `ReviewQueue` approve/reject toasts and error recovery.

---

## Lint

```bash
.venv/bin/ruff check src/ app/ tests/ api/
```

---

## Streamlit app (legacy UI)

```bash
streamlit run app/Home.py   # :8502
```

---

## Headless daemon

```bash
python scripts/run_agent.py     # watches ./inbox/ for new PDFs
python scripts/review_queue.py  # terminal review UI
```

---

## Architecture

```
PDF / invoice file
       │
       ▼
 Extraction ──────── native PDF text
       │              OCR (Tesseract)
       │              LLM (Ollama qwen2.5:3b, local)
       ▼
 Classification ───── direction rules + CostCatalog (33 entries)
       │              ML fallback (TF-IDF + LogisticRegression)
       ▼
 Validation ─────────  math checks, duplicate detection, anomaly flags
       │               human review queue for flagged invoices
       ▼
 Accounting ──────────  double-entry journal (PCE Tunisien)
       │                401/411 · 4366/4367 · 6xxx OPEX · 2xxx CAPEX
       ▼
 Budget tracking + CAPEX depreciation (linear / degressive)
```

Core: `src/agent/pipeline.py` — pure functions, no class hierarchy.  
API layer: `api/` — FastAPI + uvicorn, all endpoints under `/api/`.  
UI: `frontend/` — React 18 + TypeScript + Vite + Tailwind v4.

---

## Key configuration

`config/settings.yaml` — DB URL, OCR engine, LLM model, thresholds.  
`config/cost_catalog.yaml` — 33 accounting taxonomy entries.  
`config/budget_plan.yaml` — annual budget by catalog ID (12 monthly values).

Override DB with env var: `DATABASE_URL=sqlite:///./data/other.db uvicorn api.main:app`

---

## Generate a demo invoice PDF

```bash
python scripts/make_realistic_invoice.py
# outputs a supplier PDF to ./inbox/ ready for upload
```
