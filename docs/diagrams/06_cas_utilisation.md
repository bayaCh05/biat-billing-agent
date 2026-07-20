# Diagram 6 — Use Case Diagram

**Updated 2026-07-16/20** — translated to English, added the "View audit
reports" use case (Admin/Direction, AuditAgent), and fixed two role-mapping
gaps: "Executive AI summary" (`/ai/health-summary`) is reachable by all 4
roles, not just Direction; "Suggest mitigation" (`/ai/suggest-mitigation`)
is reachable by Chef de Projet/Admin directly, not only as an AI-internal
step. Both routes already required a valid login (via the router-level
`dependencies=_PROTECTED` in `api/main.py`) but were missing their own
`require_role(...)` — any authenticated user of any role could call them,
not the specific roles this diagram now shows — fixed 2026-07-20 (see
`backend/api/routers/ai.py`).

# Paste into Eraser → New Diagram → Flowchart (use as UML Use Case)

```mermaid
flowchart LR
  classDef actor fill:#1A3A5C,color:#fff,stroke:none,shape:circle
  classDef uc fill:#E3F0F9,color:#1A3A5C,stroke:#2E86C1
  classDef ai fill:#FEF9E7,color:#8B6914,stroke:#F0A500
  classDef sys fill:#F5F7FA,stroke:#1A3A5C

  ADMIN(["👤 Admin"])
  COMPTABLE(["👤 Accountant"])
  CHEF(["👤 Project Manager"])
  DIR(["👤 Direction"])
  IA(["🤖 AI System"])

  subgraph SYS["BIAT IT Intelligent Billing System"]
    subgraph GU["User Management"]
      UC_CU["Create user"]
      UC_AR["Assign role"]
      UC_DC["Deactivate account"]
      UC_MP["Edit profile"]
      UC_CPW["Change password"]
    end

    subgraph FF["Supplier Invoices"]
      UC_SF["Submit invoice"]
      UC_EX["Extract OCR+LLM\n<<include>>"]:::ai
      UC_CL["Classify PCE account\n<<include>>"]:::ai
      UC_VD["Validate data"]
      UC_AR2["Approve / Reject\n<<extend>>"]
    end

    subgraph COMPTA["Accounting"]
      UC_GE["Generate PCE entry\n<<include>>"]:::ai
      UC_CJ["View journal"]
      UC_GL["View general ledger"]
      UC_EX2["Export entries"]
      UC_VI["Verify audit integrity"]
    end

    subgraph CAPEX["CAPEX Assets"]
      UC_CI["Create asset\n<<extend>>"]:::ai
      UC_CA["View depreciation"]
    end

    subgraph PAY["Payments"]
      UC_GES["Generate payment schedule\n<<include>>"]:::ai
      UC_PEN["Calculate penalties\n(automatic)"]:::ai
      UC_PAY["Mark installment paid"]
    end

    subgraph FACTCLI["Client Billing"]
      UC_FC["Create client invoice"]
      UC_PDF["Generate PDF\n<<include>>"]:::ai
      UC_PAY2["Mark paid"]
    end

    subgraph PROJ["Project Management"]
      UC_CP["Create project charter"]
      UC_PH["Manage phases"]
      UC_LIV["Manage deliverables"]
      UC_JH["Log person-days"]
    end

    subgraph RISK["Risks & Roadmap"]
      UC_CR["Create risk"]
      UC_MIT["Suggest mitigation\n<<include>>"]:::ai
      UC_SCAN["Scan roadmap\n(automatic, nightly)"]:::ai
      UC_RD["View roadmap"]
    end

    subgraph REP["Reporting"]
      UC_DB["View dashboard"]
      UC_AI["Executive AI summary\n<<include>>"]:::ai
      UC_NL["Natural-language question"]
      UC_KPI["Track KPIs"]
      UC_AUDIT["View audit reports\n(DAILY/WEEKLY/MONTHLY)\n<<include>>"]:::ai
    end
  end

  ADMIN --> UC_CU & UC_AR & UC_DC & UC_VI & UC_AUDIT & UC_AI & UC_MIT
  COMPTABLE --> UC_SF & UC_VD & UC_AR2 & UC_CJ & UC_GL & UC_EX2 & UC_PAY & UC_DB & UC_NL & UC_AI
  CHEF --> UC_FC & UC_CP & UC_PH & UC_LIV & UC_JH & UC_CR & UC_RD & UC_AI & UC_MIT
  DIR --> UC_DB & UC_KPI & UC_NL & UC_AI & UC_RD & UC_CJ & UC_AUDIT
  IA --> UC_EX & UC_CL & UC_GE & UC_CI & UC_GES & UC_PEN & UC_PDF & UC_MIT & UC_SCAN & UC_AI & UC_AUDIT
  ADMIN & COMPTABLE & CHEF & DIR --> UC_MP & UC_CPW

  UC_SF --> UC_EX --> UC_CL --> UC_GE
  UC_GE --> UC_CI
  UC_GE --> UC_GES
```
