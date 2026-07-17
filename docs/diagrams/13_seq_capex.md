# Diagram 13 — Sequence: CAPEX Asset Creation

**Updated 2026-07-16** — translated to English, and fixed a stale detail:
`run({invoice, db})` — the `db: Session` parameter was confirmed dead code
(neither `AnomalyAgent` nor `AccountingAgent` ever read `context["db"]`)
and removed in the 2026-07-15 cleanup pass ("Lot 10"). The call is now
`run({invoice})`.

# Paste into Eraser → New Diagram → Sequence Diagram

```
title CAPEX — Asset Creation with AI Depreciation (Tunisian PCE)

Accountant [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
AccountingAgent [color: "#F0A500", icon: book-open]
Ollama [color: "#F0A500", icon: cpu]
Database [color: "#1A3A5C", icon: database]

note over Accountant: "The invoice has already been classified\ncharge_type = CAPEX\naccount = 2184 IT equipment"

FastAPI -> AccountingAgent: "run({invoice})\ncharge_type=CAPEX"

note over AccountingAgent: "Step 1 — Acquisition entry"
AccountingAgent -> AccountingAgent: "Generate PCE journal entry"
AccountingAgent -> Database: "save JournalEntry:\n  Debit 2184: 12 000.000 TND\n  Debit 4366 VAT: 2 280.000 TND\n  Credit 401 Supplier: 14 280.000 TND"

note over AccountingAgent: "Step 2 — Depreciation period (AI)"
AccountingAgent -> Ollama: "complete('PCE depreciation period\nfor: Dell PowerEdge server\ncategory: IT equipment')"
Ollama --> AccountingAgent: "'5' (integer between 1-20)"
AccountingAgent -> AccountingAgent: "Parse: 5 years\nsource = 'AI'"

alt "Ollama unavailable"
  AccountingAgent -> AccountingAgent: "fallback: 5 years\nsource = 'DEFAULT'"
end

note over AccountingAgent: "Step 3 — Asset creation"
AccountingAgent -> Database: "save Asset:\n  designation='Dell PowerEdge R740 server'\n  compte_immob='2184'\n  compte_amort='28184'\n  acquisition_cost_ht=12 000.000\n  useful_life_years=5\n  method='linear'\n  amortization_source='AI'"

note over AccountingAgent: "Step 4 — Accounting explanation (AI)"
AccountingAgent -> Ollama: "complete('Explain entry:\n2184 Debit 12000\n4366 Debit 2280\n401 Credit 14280')"
Ollama --> AccountingAgent: "'Asset acquisition per PCE art.23:\ndurable good > 1 year booked to 2184...'"
AccountingAgent -> Database: "save accounting_explanation in JournalEntry"

AccountingAgent --> FastAPI: "AgentResult:\n  asset_created=true\n  amortization_years=5\n  amortization_source=AI\n  is_balanced=true"

note over Accountant: "Viewed in /capex"
Accountant -> Frontend: "Opens /capex"
Frontend -> FastAPI: "GET /api/assets"
FastAPI -> Database: "SELECT assets"
Database --> FastAPI: "Asset + book_value_at(today)"
FastAPI --> Frontend: "Asset:\n  Book value at 2026-07-01 = 12 000.000 TND\n  Annual charge = 2 400.000 TND\n  Residual value 2031 = 0.000 TND"
Frontend --> Accountant: "📊 Asset shown with depreciation schedule"

note over FastAPI: "Every month-end (APScheduler)\nAutomatic depreciation charge:\n  Debit 6811: 200.000 TND/month\n  Credit 28184: 200.000 TND/month"
```
