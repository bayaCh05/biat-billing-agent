# Diagram 15 — Workflow: Payment Schedule and Late Penalties (with risk column)

**Updated 2026-07-16** — translated to English.

# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TB

  INV["📥 Invoice received — Day 0\nTTC amount: 14 280 TND\nTerm: 90 days (3 × 30d)"]

  subgraph GEN["Payment schedule generation (AI)"]
    E1["Installment 1 — Day 30\n4 760 TND\n🟢 PENDING — On time"]
    E2["Installment 2 — Day 60\n4 760 TND\n🟢 PENDING — On time"]
    E3["Installment 3 — Day 90\n4 760 TND\n🟢 PENDING — On time"]
  end

  INV --> E1
  INV --> E2
  INV --> E3

  subgraph LATE1["Scenario: Installment 1 unpaid"]
    D31["Day 31 — Late payment detected\n🔴 LATE\n⚠️ Risk: penalty imminent"]
    D31 -->|"+10% after 30d late"| P1["Day 60: 4 760 × 1.10\n= 5 236 TND\n🔴 Penalty +10%"]
    P1 -->|"+10% after 60d late"| P2["Day 90: 4 760 × 1.21\n= 5 760 TND\n🔴 Penalty +21%"]
  end

  subgraph PAID1["Late payment of installment 1"]
    PAY["Day 65: Payment 5 760 TND\n✅ PAID"]
    JE["Journal entry:\nDebit 401 (Supplier) 4 760\nDebit 668 (Penalties) 1 000\nCredit 532 (Bank) 5 760"]
  end

  E1 -->|"Unpaid"| D31
  P1 --> PAY
  PAY --> JE

  subgraph FORMULA["Penalty formula"]
    F["amount × (1 + rate)^late_periods\nRate = 10% per 30-day period\n\nEx: 4 760 × (1.10)² = 5 759.6 TND"]
  end

  subgraph RISK_COL["Risk levels per installment"]
    R1["🟢 PENDING — Risk: None"]
    R2["🟡 Due in 7 days — Risk: Low\nYellow pulse in the UI"]
    R3["🔴 1–30 days late — Risk: HIGH\n+10% applied"]
    R4["🔴🔴 > 30 days late — Risk: CRITICAL\n+21% or more applied"]
  end

  style INV fill:#1A3A5C,color:#FFFFFF
  style D31 fill:#E74C3C,color:#FFFFFF
  style P1 fill:#E67E22,color:#FFFFFF
  style P2 fill:#E74C3C,color:#FFFFFF
  style PAY fill:#1D9E76,color:#FFFFFF
  style JE fill:#2E86C1,color:#FFFFFF
  style F fill:#F5F7FA,color:#1A3A5C,stroke:#2E86C1
  style R1 fill:#E8F5F0,color:#0D6E52
  style R2 fill:#FFF8E8,color:#B07800
  style R3 fill:#FEE8E0,color:#C0391B
  style R4 fill:#FEE2E2,color:#7F1D1D
```

## Risk summary table per period

| Day | Installment | Amount | Status | Risk level | System action |
|------|----------|---------|--------|-----------------|----------------|
| D+30 | 1 | 4 760 TND | PENDING | 🟢 None | — |
| D+37 | 1 | 4 760 TND | LATE | 🔴 HIGH | Accountant alert |
| D+60 | 1 | 5 236 TND | LATE +10% | 🔴 CRITICAL | Penalty applied |
| D+90 | 1 | 5 760 TND | LATE +21% | 🔴 CRITICAL | Compounded penalty |
| D+65 | 1 | 5 760 TND | PAID | ✅ Settled | Entry 401/668/532 |
| D+60 | 2 | 4 760 TND | PENDING | 🟢 None | — |
| D+90 | 3 | 4 760 TND | PENDING | 🟢 None | — |

> **Rule**: Each 30-day period of delay = +10% cumulative on the affected installment.
> Recalculated automatically every night by the APScheduler scheduler.
