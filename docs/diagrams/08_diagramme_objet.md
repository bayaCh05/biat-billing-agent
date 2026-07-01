# Diagram 8 — Object Diagram (CAPEX invoice snapshot)
# Paste into Eraser → New Diagram → Entity Relationship (use as Object Diagram)

```
// Object Diagram — CAPEX Invoice Processing Snapshot
// Moment in time: Facture CAPEX serveur, statut JOURNALED

invoice_001 [label: "invoice_001 : InvoiceRecord", color: "#1A3A5C"] {
  status: "JOURNALED"
  direction: "SUPPLIER"
  charge_type: "CAPEX"
  amount_ht: "12 000.000 TND"
  tva_amount: "2 280.000 TND"
  amount_ttc: "14 280.000 TND"
  payment_term_days: "90 jours"
  cost_catalog_id: "CAPEX-INFRA-01"
  classification_reason: "Classifié matériel informatique\n(Pass A: fuzzy match 'serveur')"
  classification_pass: "A"
  human_review_required: "false"
}

field_montant [label: "field_montant : ConfidenceField[float]", color: "#2E86C1"] {
  value: "12 000.000"
  confidence: "0.97"
  source: "NATIVE_PDF_LLM"
}

catalog_entry [label: "catalog_entry : CostCatalogEntry", color: "#2E86C1"] {
  id: "CAPEX-INFRA-01"
  compte: "2184"
  label: "Matériel informatique"
  charge_type: "CAPEX"
  tva_rate: "19.0"
}

journal_001 [label: "journal_001 : JournalEntry", color: "#1D9E76"] {
  reference: "OD-2026-0142"
  date_ecriture: "2026-07-01"
  description: "Acquisition matériel informatique — TECHNOVA SOLUTIONS"
  accounting_explanation: "Selon PCE art.23: immobilisation corporelle\ncomptabilisée en 2184 (acquisition) et 401\n(dette fournisseur TTC)"
}

line_debit [label: "line_debit : JournalLine", color: "#1D9E76"] {
  compte: "2184"
  libelle: "Matériel informatique — Serveur Dell"
  debit: "12 000.000"
  credit: "0.000"
}

line_tva [label: "line_tva : JournalLine", color: "#1D9E76"] {
  compte: "4366"
  libelle: "TVA déductible 19%"
  debit: "2 280.000"
  credit: "0.000"
}

line_credit [label: "line_credit : JournalLine", color: "#1D9E76"] {
  compte: "401"
  libelle: "Fournisseur TECHNOVA SOLUTIONS"
  debit: "0.000"
  credit: "14 280.000"
}

asset_001 [label: "asset_001 : Asset", color: "#F0A500"] {
  designation: "Serveur Dell PowerEdge R740"
  compte_immobilisation: "2184"
  compte_amortissement: "28184"
  acquisition_date: "2026-07-01"
  acquisition_cost_ht: "12 000.000 TND"
  useful_life_years: "5 ans"
  depreciation_method: "linear"
  amortization_source: "AI (Ollama qwen2.5:3b)"
}

installment_1 [label: "installment_1 : PaymentInstallment", color: "#804CD7"] {
  installment_number: "1/3"
  due_date: "2026-07-31"
  base_amount: "4 760.000 TND"
  current_amount: "4 760.000 TND"
  status: "PENDING"
  late_periods: "0"
}

installment_2 [label: "installment_2 : PaymentInstallment", color: "#804CD7"] {
  installment_number: "2/3"
  due_date: "2026-08-30"
  base_amount: "4 760.000 TND"
  status: "PENDING"
}

installment_3 [label: "installment_3 : PaymentInstallment", color: "#804CD7"] {
  installment_number: "3/3"
  due_date: "2026-09-29"
  base_amount: "4 760.000 TND"
  status: "PENDING"
}

user_comptable [label: "user_comptable : User", color: "#1A3A5C"] {
  email: "comptable@biat-it.tn"
  role: "COMPTABLE"
  is_active: "true"
  is_first_login: "false"
}

// Links
invoice_001.amount_ht -- field_montant
invoice_001.cost_catalog_id -- catalog_entry
journal_001 -- invoice_001
line_debit -- journal_001
line_tva -- journal_001
line_credit -- journal_001
asset_001 -- invoice_001
installment_1 -- invoice_001
installment_2 -- invoice_001
installment_3 -- invoice_001
```

> **Balance check**: Σ débits = 12 000 + 2 280 = **14 280 TND** = Σ crédits ✓
