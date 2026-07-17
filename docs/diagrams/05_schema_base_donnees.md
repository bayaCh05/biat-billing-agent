# Diagram 5 — Data Schema (MongoDB-primary + remaining SQLite)

**Updated 2026-07-15** — the previous version ("9 SQLite tables") predated
the MongoDB migration and no longer reflected the system's real state.
MongoDB is now the primary database for nearly every domain (see
`CLAUDE.md` "MongoDB Migration Status"); SQLite remains load-bearing for
only 3 specific paths, listed in the note at the bottom of this file.

Rendered: [`05_schema_base_donnees.png`](05_schema_base_donnees.png) ·
Live editable source: https://app.eraser.io/workspace/NAh6JeIRqqIfV1Fef6wg?diagram=sWteENyCJ0LUzvCQUOHe

Paste into Eraser → New Diagram → Entity Relationship

```
title: "05 - Data Schema (MongoDB-primary + remaining SQLite)"

// ── MONGODB (PRIMARY) ─────────────────────────────────
invoices [color: "#1D9E76"] {
  _id string pk "uuid, string with dashes"
  status string "RECEIVED..JOURNALED/PAID"
  direction string "SUPPLIER | CLIENT | UNKNOWN"
  charge_type string "OPEX | CAPEX"
  file_hash string unique
  amount_ht float
  amount_ttc float
  cost_catalog_id string
  human_review_required bool
  flags array "ValidationFlagEmbed[]"
  received_at datetime
}

journal_entries [color: "#1D9E76"] {
  _id string pk
  reference string
  date_ecriture datetime
  source_invoice_id string fk
  lines array "embedded JournalLine[] (compte, debit, credit)"
}

users [color: "#1D9E76"] {
  _id string pk
  email string unique
  hashed_password string "argon2id"
  role string "Comptable|Chef de Projet|Direction|Admin"
  is_first_login bool
  failed_login_attempts int
}

audit_logs [color: "#1D9E76"] {
  _id string pk
  created_at datetime
  action string
  user_id string
  status string "SUCCESS|FAILURE"
  row_hash string "HMAC-SHA256, Mongo side has none tampered as of this snapshot"
}

audit_snapshots [color: "#1D9E76"] {
  _id string pk
  granularity string "DAILY|WEEKLY|MONTHLY"
  period_start datetime
  metrics object
  trend object
  alerts array
  reconciliation object
  similar_incidents array
  narrative_summary string
}

payment_installments [color: "#1D9E76"] {
  _id string pk
  invoice_id string fk
  due_date datetime
  status string "PENDING|LATE|PAID"
  current_amount float
}

assets [color: "#1D9E76"] {
  _id string pk
  designation string
  acquisition_cost_ht float
  depreciation_method string
  fully_depreciated bool
}

risques [color: "#1D9E76"] {
  _id string pk
  titre string
  niveau_criticite string
  statut string
}

feuilles_de_route [color: "#1D9E76"] {
  _id string pk
  statut string
  date_fin datetime
}

// ── SQLITE (SECONDARY, shrinking) ─────────────────────
audit_logs_sqlite [label: "audit_logs (SQLite)", color: "#5D6D7E"] {
  id uuid pk
  created_at datetime
  row_hash string "original HMAC, never overwritten"
  rebaseline_hash string "added after the 2026-07-10 secret rotation"
  rebaselined_at datetime
  rebaseline_reason string
}

invoices_sqlite [label: "invoices (SQLite, legacy)", color: "#5D6D7E"] {
  id uuid pk
  status string "frozen - no live writer anymore"
}

invoices._id < payment_installments.invoice_id
invoices._id < journal_entries.source_invoice_id
users._id < audit_logs.user_id
```

> **Note**: MongoDB now holds nearly everything (see `CLAUDE.md` "MongoDB
> Migration Status"). SQLite remains load-bearing only for: the `audit_logs`
> HMAC integrity chain, a review-queue fallback (invoice flagged before the
> daemon's removal in 2026-07), and a journal-entry completeness check in
> `get_pipeline_status`. `invoices_sqlite` is a frozen pre-migration
> snapshot — no new writer.
