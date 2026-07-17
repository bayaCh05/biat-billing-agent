# Diagram 14 — Workflow: Invoice Status (with risk indicators)

**Updated 2026-07-16** — translated to English, and fixed a real
staleness: this diagram showed `EXTRACTING/CLASSIFYING/VALIDATING/
JOURNALING/EXPORTED` as states the live pipeline actually transitions
through. Per `CLAUDE.md` ("InvoiceStatus" state machine), the enum still
*defines* all of these (kept for historical/legacy-data reasons — see
Diagram 7), but `InvoiceProcessingOrchestrator.process_invoice()` — the only
live writer — never sets any `-ING` in-progress status and skips
`EXPORTING`/`EXPORTED` entirely (that was the deleted daemon's export
step). The real live path is `RECEIVED → EXTRACTED → CLASSIFIED →
VALIDATED (or FLAGGED) → JOURNALED`. This version marks the removed
states explicitly as legacy/historical rather than showing them as live
transitions — same fix already applied to Diagram 9.

# Paste into Eraser → New Diagram → Flowchart

```mermaid
flowchart TD

  RECEIVED["📥 RECEIVED"]
  EXTRACTED["📄 EXTRACTED"]
  CLASSIFIED["🗂️ CLASSIFIED"]
  VALIDATED["✔️ VALIDATED"]
  FLAGGED["🚩 FLAGGED\nHuman review required"]
  JOURNALED["📗 JOURNALED"]
  PAID["💳 PAID"]
  REJECTED["❌ REJECTED"]
  ERROR["💥 ERROR"]
  EXTRACTION_FAILED["💥 EXTRACTION_FAILED"]

  LEGACY["🗄️ Legacy/historical only —\nEXTRACTING, CLASSIFYING, VALIDATING,\nJOURNALING, EXPORTED\nStill defined in the enum (old data,\nml_classifier training labels) but never\nset by the live pipeline anymore"]

  RISK_EXTRACT["⚠️ Extraction risk\nUnreadable PDF / missing fields\nFallback: Tesseract OCR\nTotal failure → EXTRACTION_FAILED"]
  RISK_CLASS["⚠️ Classification risk\nPCE account potentially wrong\nConfidence < 85% → FLAGGED"]
  RISK_VALID["⚠️ Validation risks\n• HT + VAT ≠ TTC\n• Duplicate detected\n• Suspicious amount\nAnomalyAgent → FLAGGED"]
  RISK_JOURNAL["⚠️ Journal entry risk\nDebit ≠ Credit\nAuto-blocked before save"]
  RISK_PAYMENT["⚠️ Payment risk\nLate → +10% per 30-day period\nAutomatic nightly tracking"]

  RECEIVED --> EXTRACTED
  EXTRACTED --- RISK_EXTRACT
  RISK_EXTRACT -->|"Total failure"| EXTRACTION_FAILED

  EXTRACTED --> CLASSIFIED
  CLASSIFIED --- RISK_CLASS
  RISK_CLASS -->|"Confidence ≥ 85%"| VALIDATED
  RISK_CLASS -->|"Confidence < 85%"| FLAGGED

  VALIDATED --- RISK_VALID
  RISK_VALID -->|"No ERROR flag"| JOURNALED
  RISK_VALID -->|"ERROR flag"| FLAGGED

  JOURNALED --- RISK_JOURNAL

  FLAGGED -->|"Accountant: Correct"| VALIDATED
  FLAGGED -->|"Accountant: Reject"| REJECTED

  JOURNALED --> PAID
  JOURNALED --- RISK_PAYMENT

  style RECEIVED fill:#1A3A5C,color:#FFFFFF
  style JOURNALED fill:#1D9E76,color:#FFFFFF
  style PAID fill:#1D9E76,color:#FFFFFF
  style FLAGGED fill:#F0A500,color:#FFFFFF
  style ERROR fill:#E74C3C,color:#FFFFFF
  style EXTRACTION_FAILED fill:#E74C3C,color:#FFFFFF
  style REJECTED fill:#E74C3C,color:#FFFFFF
  style LEGACY fill:#F5F7FA,color:#5D6D7E,stroke:#9BAFBF,stroke-width:1px,stroke-dasharray: 4 2
  style RISK_EXTRACT fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_CLASS fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_VALID fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
  style RISK_JOURNAL fill:#FEE2E2,color:#7F1D1D,stroke:#E74C3C,stroke-width:2px
  style RISK_PAYMENT fill:#FFF8E8,color:#7D4E00,stroke:#F0A500,stroke-width:2px
```

## Transitions and risks

| Transition | Trigger | Risk | Mitigation |
|-----------|-------------|--------|------------|
| RECEIVED → EXTRACTED | Automatic AI pipeline | Unreadable PDF | Tesseract OCR fallback |
| EXTRACTED → EXTRACTION_FAILED | OCR + LLM both fail | Critical — blocked | Rejected with notification |
| CLASSIFIED → FLAGGED | Confidence < 85% | Wrong PCE account | Mandatory human review |
| VALIDATED → FLAGGED | AnomalyAgent ERROR flag | Math / duplicate / anomaly | Accounting review queue |
| VALIDATED → JOURNALED | AccountingAgent, no ERROR flag | PCE non-compliance if unbalanced | Auto-blocked before DB save |
| JOURNALED → PAID | Accountant marks paid | Late payment | +10%/30-day penalty, nightly alerts |
