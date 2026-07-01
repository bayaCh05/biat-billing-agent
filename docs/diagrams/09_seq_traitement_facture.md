# Diagram 9 — Sequence: Invoice Processing Pipeline
# Paste into Eraser → New Diagram → Sequence Diagram

```
title Traitement Pipeline IA — Facture Fournisseur (PDF → JOURNALED)

Comptable [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
Orchestrator [color: "#F0A500", icon: layers]
ExtractionAgent [color: "#F0A500", icon: scan]
ClassificationAgent [color: "#F0A500", icon: tag]
AnomalyAgent [color: "#F0A500", icon: alert-triangle]
AccountingAgent [color: "#F0A500", icon: book-open]
Ollama [color: "#F0A500", icon: cpu]
Database [color: "#1A3A5C", icon: database]

Comptable -> Frontend: "1. Upload PDF (drag & drop)"
Frontend -> FastAPI: "POST /api/invoices/upload\nBearer token + multipart"

FastAPI -> FastAPI: "2. JWT auth check\n+ MIME validation\n+ rate limit check"
FastAPI -> Database: "save AuditLog(INVOICE_UPLOADED)"

FastAPI -> Orchestrator: "process_invoice(invoice)"
Orchestrator -> Ollama: "is_available()?"
Ollama --> Orchestrator: "true / false (degraded mode)"

note over Orchestrator: "Step 1 — Extraction"
Orchestrator -> ExtractionAgent: "run({invoice})"
ExtractionAgent -> ExtractionAgent: "try native PDF text"
ExtractionAgent -> ExtractionAgent: "fallback: Tesseract OCR"
ExtractionAgent -> Ollama: "complete(extraction_prompt)"
Ollama --> ExtractionAgent: "JSON ConfidenceField[]"
ExtractionAgent --> Orchestrator: "AgentResult(success, confidence_fields)"
Orchestrator -> Database: "invoice.status = EXTRACTED"

note over Orchestrator: "Step 2 — Classification"
Orchestrator -> ClassificationAgent: "run({invoice, degraded_mode})"
ClassificationAgent -> ClassificationAgent: "Pass A: CostCatalog fuzzy match"

alt "Pass A score >= 70"
  ClassificationAgent --> Orchestrator: "Pass A matched"
else "Pass A fails"
  ClassificationAgent -> ClassificationAgent: "Pass B: TF-IDF/LogReg ML"
  alt "Pass B confidence >= 0.7"
    ClassificationAgent --> Orchestrator: "Pass B matched"
  else "Pass B fails"
    ClassificationAgent -> Ollama: "complete(RAG classification prompt)"
    Ollama --> ClassificationAgent: "PCE compte + reason"
    ClassificationAgent --> Orchestrator: "Pass C matched"
  end
end

Orchestrator -> Database: "invoice.status = CLASSIFIED\naccounting_compte, reason saved"

note over Orchestrator: "Step 3 — Anomaly Detection"
Orchestrator -> AnomalyAgent: "run({invoice, db})"
AnomalyAgent -> AnomalyAgent: "Math: |HT + TVA - TTC| < 0.005 TND"
AnomalyAgent -> AnomalyAgent: "Duplicate: hash + semantic check"
AnomalyAgent -> AnomalyAgent: "High value: > 50 000 TND?"

alt "Errors detected (severity=ERROR)"
  AnomalyAgent --> Orchestrator: "requires_human_review=true"
  Orchestrator -> Database: "invoice.status = FLAGGED"
  FastAPI --> Frontend: "InvoiceOut(status=FLAGGED)"
  Frontend --> Comptable: "⚠️ Facture signalée — révision requise"
else "No blocking errors"
  AnomalyAgent --> Orchestrator: "no critical flags"
  Orchestrator -> Database: "invoice.status = VALIDATED"

  note over Orchestrator: "Step 4 — Accounting"
  Orchestrator -> AccountingAgent: "run({invoice, db})"
  AccountingAgent -> AccountingAgent: "Generate PCE journal entry"
  AccountingAgent -> Ollama: "complete(accounting explanation)"
  Ollama --> AccountingAgent: "2-sentence PCE explanation"

  alt "CAPEX invoice"
    AccountingAgent -> Ollama: "complete(amortization duration)"
    Ollama --> AccountingAgent: "N years (1-20)"
    AccountingAgent -> Database: "save Asset"
  end

  alt "payment_term_days set"
    AccountingAgent -> Database: "save PaymentInstallment × N"
  end

  AccountingAgent -> Database: "save JournalEntry + JournalLines"
  AccountingAgent --> Orchestrator: "AgentResult(is_balanced=true)"
  Orchestrator -> Database: "invoice.status = JOURNALED"
  FastAPI --> Frontend: "InvoiceOut(status=JOURNALED)"
  Frontend --> Comptable: "✅ Facture traitée — écriture PCE générée"
end
```
