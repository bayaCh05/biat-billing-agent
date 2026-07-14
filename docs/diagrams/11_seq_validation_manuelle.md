# Diagram 11 — Sequence: Manual Validation (FLAGGED invoice)
# Paste into Eraser → New Diagram → Sequence Diagram

```
title Révision Manuelle — File de Révision (FLAGGED → JOURNALED)

Comptable [color: "#1A3A5C", icon: user]
ReviewQueue [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
Database [color: "#1A3A5C", icon: database]
Orchestrator [label: "Invoice Processing Orchestrator", color: "#F0A500", icon: layers]
Ollama [color: "#F0A500", icon: cpu]

Comptable -> ReviewQueue: "Ouvre /review"
ReviewQueue -> FastAPI: "GET /api/review"
FastAPI -> Database: "SELECT invoices WHERE status=FLAGGED\nAND human_review_required=true"
Database --> FastAPI: "Liste factures signalées"
FastAPI --> ReviewQueue: "Liste avec flags + raison classification"
ReviewQueue --> Comptable: "📋 Facture FAC-2026-0147\n⚠️ TOTAL_MISMATCH: TTC calculé ≠ TTC extrait\n⚠️ LOW_CONFIDENCE: issuer_tax_id 0.45"

Comptable -> ReviewQueue: "Clique 'Voir détails'"
ReviewQueue -> FastAPI: "GET /api/invoices/{id}/pipeline-status"
FastAPI --> ReviewQueue: "steps[], flags[], journal_entry, AI reason"
ReviewQueue --> Comptable: "Détails complets:\n- Raison IA: 'Pass A: fuzzy 73% maintenance'\n- TVA attendue: 2 755 | extraite: 2 700\n- Confiance tax_id: 0.45"

Comptable -> ReviewQueue: "Corrige amount_ttc = 17 255\nCorrige issuer_tax_id manuellement"
ReviewQueue -> FastAPI: "PATCH /api/review/{id}/approve\n{corrected_fields, resolution}"

FastAPI -> Database: "UPDATE invoice:\n- amount_ttc corrected\n- flags resolved\n- human_review_required=false"
FastAPI -> Database: "save AuditLog(REVIEW_ACTION=APPROVED)"

FastAPI -> Orchestrator: "resume from VALIDATED step"
Orchestrator -> FastAPI: "AccountingAgent.run(invoice)"

note over Orchestrator: "Regénère l'écriture PCE avec valeurs corrigées"
Orchestrator -> Ollama: "complete(accounting_explanation)"
Ollama --> Orchestrator: "Explication 2 phrases PCE"
Orchestrator -> Database: "save JournalEntry (balanced)\ninvoice.status = JOURNALED"

FastAPI --> ReviewQueue: "ActionResult(new_status=JOURNALED)"
ReviewQueue --> Comptable: "✅ Facture approuvée\nÉcriture OD-2026-0147 générée\nMontant TTC: 17 255.000 TND"

note over Comptable: "Alternative: REJETER"
Comptable -> ReviewQueue: "Clique 'Rejeter'"
ReviewQueue -> FastAPI: "PATCH /api/review/{id}/reject\n{reason}"
FastAPI -> Database: "invoice.status = REJECTED\nsave AuditLog(REVIEW_ACTION=REJECTED)"
FastAPI --> ReviewQueue: "ActionResult(new_status=REJECTED)"
```
