# Diagram 12 — Sequence: Client Invoice Flow

**Updated 2026-07-16** — translated to English.

# Paste into Eraser → New Diagram → Sequence Diagram

```
title Client Billing — Generation & Collection (FAC-IT-2026-NNNN)

ProjectManager [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
InvoiceBuilder [color: "#F0A500", icon: file-text]
Database [color: "#1A3A5C", icon: database]
EmailService [color: "#1D9E76", icon: mail]

ProjectManager -> Frontend: "Opens /billing → picks template\n'biat_maintenance' + June 2026"
Frontend -> FastAPI: "POST /api/billing/generate\n{template_id, year, month}"
FastAPI -> Database: "SELECT template WHERE id=biat_maintenance"
Database --> FastAPI: "Template: BIAT Bank, IT maintenance\n5 lines, VAT 19%"

FastAPI -> InvoiceBuilder: "build(template, project_data)"
InvoiceBuilder -> InvoiceBuilder: "Generates number: FAC-IT-2026-0023\nComputes HT/VAT/TTC amounts"
InvoiceBuilder -> InvoiceBuilder: "Generates PDF (fpdf2)"
InvoiceBuilder -> Database: "save ClientInvoice(status=DRAFT)"
InvoiceBuilder --> FastAPI: "ClientInvoice(id, invoice_number, amount_ttc)"
FastAPI --> Frontend: "201 ClientInvoice"
Frontend --> ProjectManager: "📄 FAC-IT-2026-0023 generated (DRAFT)\nTTC amount: 85 000.000 TND"

ProjectManager -> Frontend: "Clicks 'Send'"
Frontend -> FastAPI: "POST /api/billing/invoices/{id}/send"
FastAPI -> Database: "UPDATE status=SENT\nrecorded_at=now()"
FastAPI -> EmailService: "send invoice PDF to BIAT Bank"
FastAPI --> Frontend: "200 {status: SENT}"
Frontend --> ProjectManager: "📤 Sent to BIAT Bank"

note over ProjectManager: "Later — BIAT Bank settles the invoice"
ProjectManager -> Frontend: "Clicks 'Mark as paid'"
Frontend -> FastAPI: "PATCH /api/billing/invoices/{id}/collect\n{payment_date, reference}"
FastAPI -> Database: "UPDATE status=PAID\npaid_at=now()"

note over FastAPI: "Generates the revenue journal entry"
FastAPI -> Database: "save JournalEntry:\n  Debit 532 Bank: 85 000.000\n  Credit 706 Services rendered: 71 428.571\n  Credit 4367 VAT collected: 13 571.429"
FastAPI --> Frontend: "200 {status: PAID, journal_id}"
Frontend --> ProjectManager: "✅ Collected — 7xxx entry generated"
```
