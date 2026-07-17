# Diagram 2 — Functional Architecture
# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TB
  classDef module fill:#1A3A5C,color:#fff,stroke:#1A3A5C,rx:8
  classDef flow fill:#2E86C1,color:#fff,stroke:#2E86C1
  classDef ai fill:#F0A500,color:#fff,stroke:#F0A500,rx:8
  classDef report fill:#1D9E76,color:#fff,stroke:#1D9E76,rx:8

  M1["📄 Module 1\nSupplier Invoice\nManagement\n(OCR + LLM + PCE)"]:::module
  M2["🧾 Module 2\nClient Billing\n(Templates + PDF)"]:::module
  M3["📒 Module 3\nAccounting & PCE Journal\n(Double entry, TND)"]:::module
  M4["🏗️ Module 4\nCAPEX Assets\n(PCE depreciation)"]:::module
  M5["💳 Module 5\nPayment Schedule\n(Automatic penalties)"]:::module
  M6["📂 Module 6\nIT Project Management\n(Charter → Phases → Deliverables)"]:::module
  M7["⚠️ Module 7\nRisks & Roadmap\n(Criticality matrix)"]:::module
  M8["📊 Module 8\nReporting & Dashboards\n(KPIs + AI + NL Query)"]:::report

  AI1["🤖 Invoice Processing Orchestrator\n4 local Ollama agents"]:::ai
  AI2["🤖 RiskAgent\n(nightly scan)"]:::ai
  AI3["🤖 InsightAgent\n(executive summary)"]:::ai
  AI4["🤖 AuditAgent\n(DAILY/WEEKLY/MONTHLY report)"]:::ai

  M1 -->|"OPEX entry"| M3
  M1 -->|"If CAPEX"| M4
  M1 -->|"If payment term"| M5
  M2 -->|"Revenue entry 7xxx"| M3
  M2 -->|"Linked to project"| M6
  M4 -->|"Depreciation charge 6811"| M3
  M5 -->|"Settlement 401"| M3
  M6 -->|"JH budget"| M8
  M7 -->|"Critical risks"| M8
  M3 -->|"Journal + General Ledger"| M8
  M1 -->|"pipeline"| AI1
  M7 -->|"overdue milestones"| AI2
  M8 -->|"KPI snapshot"| AI3
  M3 & M5 & M7 -->|"cross-entity reconciliation"| AI4

  style M1 fill:#1A3A5C,color:#fff
  style M2 fill:#1A3A5C,color:#fff
  style M3 fill:#2E86C1,color:#fff
  style M4 fill:#2E86C1,color:#fff
  style M5 fill:#2E86C1,color:#fff
  style M6 fill:#1A3A5C,color:#fff
  style M7 fill:#1A3A5C,color:#fff
  style M8 fill:#1D9E76,color:#fff
```
