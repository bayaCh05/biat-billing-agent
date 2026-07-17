# Diagram 9 — Invoice Processing Pipeline

**Updated 2026-07-15** — the previous version still included an
EXPORTING/EXPORTED step and implied a headless daemon could trigger
processing. The daemon (`scripts/run_agent.py`, `agent/pipeline.py`) was
removed in 2026-07 — `POST /api/invoices/upload` is now the sole entry
point for invoice processing, and the real path never goes through
EXPORTING/EXPORTED anymore.

Rendered: [`09_seq_traitement_facture.png`](09_seq_traitement_facture.png) ·
Live editable source: https://app.eraser.io/workspace/NAh6JeIRqqIfV1Fef6wg?diagram=otOSSUcUe9iKR6Te7LSp

Paste into Eraser → New Diagram → Sequence

```
title: "09 - Invoice Processing Pipeline"

Accountant [color: "#1A3A5C"]
API [label: "POST /api/invoices/upload", color: "#2E86C1"]
Orchestrator [label: "InvoiceProcessingOrchestrator", color: "#F0A500"]
Extraction [label: "ExtractionAgent", color: "#F0A500"]
Classification [label: "ClassificationAgent", color: "#F0A500"]
Anomaly [label: "AnomalyAgent", color: "#F0A500"]
Accounting [label: "AccountingAgent", color: "#F0A500"]
Ollama [label: "Ollama (host)", color: "#804CD7"]
Mongo [label: "MongoDB", color: "#1D9E76"]

Accountant > API: "upload PDF"
API > Orchestrator: "process_invoice(invoice)"
Orchestrator > Extraction: "run()"
Extraction > Ollama: "native PDF / OCR Tesseract / LLM fallback"
Ollama --> Extraction
Extraction --> Orchestrator: "status = EXTRACTED"
Orchestrator > Mongo: "AI_EXTRACT audit event"

Orchestrator > Classification: "run()"
Classification > Ollama: "RAG (ChromaDB) + Ollama, Pass A/B/C"
Ollama --> Classification
Classification --> Orchestrator: "status = CLASSIFIED"
Orchestrator > Mongo: "AI_CLASSIFY audit event"

Orchestrator > Anomaly: "run()"
Anomaly > Mongo: "duplicate + semantic checks"
Mongo --> Anomaly
Anomaly --> Orchestrator: "flags[], requires_human_review?"
Orchestrator > Mongo: "AI_ANOMALY audit event"

alt "requires_human_review = true"
  Orchestrator > Mongo: "status = FLAGGED, human_review_required = true"
  Orchestrator --> API: "return FLAGGED"
  API --> Accountant: "needs manual review"
else "no anomaly"
  Orchestrator > Mongo: "status = VALIDATED"
  Orchestrator > Accounting: "run()"
  Accounting > Ollama: "explanation text (rules compute the numbers, not the LLM)"
  Ollama --> Accounting
  Accounting > Mongo: "journal entry (401/411, 4366/4367, 6xxx/2xxx), CAPEX asset if applicable, payment installments"
  Accounting --> Orchestrator: "status = JOURNALED"
  Orchestrator > Mongo: "AI_JOURNAL audit event"
  Orchestrator --> API: "return JOURNALED"
  API --> Accountant: "processed end-to-end"
end
```

> **Note**: `RECEIVED → EXTRACTED → CLASSIFIED → VALIDATED` (or `FLAGGED`)
> `→ JOURNALED`. No `EXPORTING`/`EXPORTED` step in the real path (removed
> along with the old daemon). This is the **only** entry point for invoice
> processing — no more headless daemon.
