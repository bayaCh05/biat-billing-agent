# Diagram 11 — Sequence: Manual Validation (FLAGGED invoice)

**Updated 2026-07-16** — translated to English.

# Paste into Eraser → New Diagram → Sequence Diagram

```
title Manual Review — Review Queue (FLAGGED → JOURNALED)

Accountant [color: "#1A3A5C", icon: user]
ReviewQueue [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
Database [color: "#1A3A5C", icon: database]
Orchestrator [label: "Invoice Processing Orchestrator", color: "#F0A500", icon: layers]
Ollama [color: "#F0A500", icon: cpu]

Accountant -> ReviewQueue: "Opens /review"
ReviewQueue -> FastAPI: "GET /api/review"
FastAPI -> Database: "SELECT invoices WHERE status=FLAGGED\nAND human_review_required=true"
Database --> FastAPI: "List of flagged invoices"
FastAPI --> ReviewQueue: "List with flags + classification reason"
ReviewQueue --> Accountant: "📋 Invoice FAC-2026-0147\n⚠️ TOTAL_MISMATCH: computed TTC ≠ extracted TTC\n⚠️ LOW_CONFIDENCE: issuer_tax_id 0.45"

Accountant -> ReviewQueue: "Clicks 'View details'"
ReviewQueue -> FastAPI: "GET /api/invoices/{id}/pipeline-status"
FastAPI --> ReviewQueue: "steps[], flags[], journal_entry, AI reason"
ReviewQueue --> Accountant: "Full details:\n- AI reason: 'Pass A: fuzzy 73% maintenance'\n- Expected VAT: 2 755 | extracted: 2 700\n- tax_id confidence: 0.45"

Accountant -> ReviewQueue: "Corrects amount_ttc = 17 255\nCorrects issuer_tax_id manually"
ReviewQueue -> FastAPI: "PATCH /api/review/{id}/approve\n{corrected_fields, resolution}"

FastAPI -> Database: "UPDATE invoice:\n- amount_ttc corrected\n- flags resolved\n- human_review_required=false"
FastAPI -> Database: "save AuditLog(REVIEW_ACTION=APPROVED)"

FastAPI -> Orchestrator: "resume from VALIDATED step"
Orchestrator -> FastAPI: "AccountingAgent.run(invoice)"

note over Orchestrator: "Regenerates the PCE entry with corrected values"
Orchestrator -> Ollama: "complete(accounting_explanation)"
Ollama --> Orchestrator: "2-sentence PCE explanation"
Orchestrator -> Database: "save JournalEntry (balanced)\ninvoice.status = JOURNALED"

FastAPI --> ReviewQueue: "ActionResult(new_status=JOURNALED)"
ReviewQueue --> Accountant: "✅ Invoice approved\nEntry OD-2026-0147 generated\nTTC amount: 17 255.000 TND"

note over Accountant: "Alternative: REJECT"
Accountant -> ReviewQueue: "Clicks 'Reject'"
ReviewQueue -> FastAPI: "PATCH /api/review/{id}/reject\n{reason}"
FastAPI -> Database: "invoice.status = REJECTED\nsave AuditLog(REVIEW_ACTION=REJECTED)"
FastAPI --> ReviewQueue: "ActionResult(new_status=REJECTED)"
```
