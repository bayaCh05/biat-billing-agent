# Diagram 12 — Sequence: Client Invoice Flow
# Paste into Eraser → New Diagram → Sequence Diagram

```
title Facturation Client — Génération & Encaissement (FAC-IT-2026-NNNN)

ChefProjet [color: "#1A3A5C", icon: user]
Frontend [color: "#2E86C1", icon: monitor]
FastAPI [color: "#2E86C1", icon: server]
InvoiceBuilder [color: "#F0A500", icon: file-text]
Database [color: "#1A3A5C", icon: database]
EmailService [color: "#1D9E76", icon: mail]

ChefProjet -> Frontend: "Ouvre /billing → choisit template\n'biat_maintenance' + mois Juin 2026"
Frontend -> FastAPI: "POST /api/billing/generate\n{template_id, year, month}"
FastAPI -> Database: "SELECT template WHERE id=biat_maintenance"
Database --> FastAPI: "Template: BIAT Bank, Maintenance SI\n5 lignes, TVA 19%"

FastAPI -> InvoiceBuilder: "build(template, project_data)"
InvoiceBuilder -> InvoiceBuilder: "Génère numéro: FAC-IT-2026-0023\nCalcule montants HT/TVA/TTC"
InvoiceBuilder -> InvoiceBuilder: "Génère PDF (fpdf2)"
InvoiceBuilder -> Database: "save ClientInvoice(status=DRAFT)"
InvoiceBuilder --> FastAPI: "ClientInvoice(id, invoice_number, amount_ttc)"
FastAPI --> Frontend: "201 ClientInvoice"
Frontend --> ChefProjet: "📄 FAC-IT-2026-0023 générée (DRAFT)\nMontant TTC: 85 000.000 TND"

ChefProjet -> Frontend: "Clique 'Envoyer'"
Frontend -> FastAPI: "POST /api/billing/invoices/{id}/send"
FastAPI -> Database: "UPDATE status=SENT\nrecorded_at=now()"
FastAPI -> EmailService: "send invoice PDF to BIAT Bank"
FastAPI --> Frontend: "200 {status: SENT}"
Frontend --> ChefProjet: "📤 Envoyée à BIAT Bank"

note over ChefProjet: "Plus tard — BIAT Bank règle la facture"
ChefProjet -> Frontend: "Clique 'Marquer comme payée'"
Frontend -> FastAPI: "PATCH /api/billing/invoices/{id}/collect\n{payment_date, reference}"
FastAPI -> Database: "UPDATE status=PAID\npaid_at=now()"

note over FastAPI: "Génère écriture comptable produit"
FastAPI -> Database: "save JournalEntry:\n  Débit 532 Banque: 85 000.000\n  Crédit 706 Prestations de services: 71 428.571\n  Crédit 4367 TVA collectée: 13 571.429"
FastAPI --> Frontend: "200 {status: PAID, journal_id}"
Frontend --> ChefProjet: "✅ Encaissée — écriture 7xxx générée"
```
