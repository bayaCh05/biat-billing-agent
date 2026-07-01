# Diagram 5 — Database Schema (9 main tables)
# Paste into Eraser → New Diagram → Entity Relationship

```
// ── FACTURATION ───────────────────────────────────────
invoices [color: "#1A3A5C"] {
  id uuid pk
  status string "RECEIVED→JOURNALED→PAID"
  direction string "SUPPLIER | CLIENT | UNKNOWN"
  charge_type string "OPEX | CAPEX"
  file_hash string unique
  raw_file_path string
  issuer_name string
  issuer_tax_id string
  invoice_number string
  invoice_date date
  amount_ht float
  tva_rate float
  tva_amount float
  amount_ttc float
  accounting_compte string "PCE: 6xxx/2xxx"
  cost_catalog_id string
  classification_reason string
  classification_pass string "A/B/C"
  payment_term_days int
  human_review_required bool
  received_at timestamp
}

invoice_flags [color: "#C0391B"] {
  id uuid pk
  invoice_id uuid fk
  flag_type string "TOTAL_MISMATCH|DUPLICATE|..."
  severity string "ERROR | WARNING | INFO"
  message string
  resolved bool
  resolved_at timestamp
}

// ── COMPTABILITÉ ──────────────────────────────────────
journal_entries [color: "#2E86C1"] {
  id uuid pk
  reference string "OD-2026-NNNN"
  date_ecriture date
  description string
  source_invoice_id uuid fk
  accounting_explanation string "AI generated"
  created_at timestamp
}

journal_lines [color: "#2E86C1"] {
  id uuid pk
  entry_id uuid fk
  compte string "PCE account: 401/4366/6xxx/2xxx"
  libelle string
  debit float
  credit float
}

// ── IMMOBILISATIONS ───────────────────────────────────
assets [color: "#1D9E76"] {
  id uuid pk
  designation string
  compte_immobilisation string "2xxx"
  compte_amortissement string "28xx"
  acquisition_date date
  acquisition_cost_ht float
  useful_life_years int
  depreciation_method string "linear | degressive"
  amortization_source string "AI | DEFAULT"
  supplier_invoice_id uuid fk
}

// ── FACTURATION CLIENT ────────────────────────────────
client_invoices [color: "#804CD7"] {
  id uuid pk
  invoice_number string "FAC-IT-2026-NNNN"
  status string "DRAFT|SENT|PAID"
  client_name string
  amount_ht float
  tva_amount float
  amount_ttc float
  projet_id uuid fk
  generated_at timestamp
}

// ── PROJETS ───────────────────────────────────────────
chartes_projet [color: "#F0A500"] {
  id uuid pk
  project_name string
  chef_projet_id uuid fk
  budget_jh float
  taux_jh float
  jh_consommes float
  statut string
  date_debut date
  date_fin date
}

// ── SÉCURITÉ & AUDIT ──────────────────────────────────
audit_logs [color: "#5D6D7E"] {
  id uuid pk
  timestamp timestamp
  user_id string fk
  user_email string
  user_role string
  action string "INVOICE_UPLOADED|LOGIN|..."
  resource_type string
  resource_id string
  ip_address string
  status string "SUCCESS | FAILURE"
  row_hash string "HMAC-SHA256"
}

users [color: "#1A3A5C"] {
  id uuid pk
  email string unique
  nom string
  prenom string
  role string "Admin|Comptable|Chef de Projet|Direction"
  hashed_password string "bcrypt"
  is_active bool
  is_first_login bool
  failed_login_attempts int
  locked_until timestamp
  created_at timestamp
}

// ── RISQUES ───────────────────────────────────────────
risks [color: "#C0391B"] {
  id uuid pk
  titre string
  type_risque string "DELAI|BUDGET|TECHNIQUE|..."
  probabilite string "FAIBLE|MOYENNE|ELEVEE"
  impact string "FAIBLE|MOYEN|ELEVE|CRITIQUE"
  niveau_criticite string "FAIBLE|MOYENNE|ELEVEE|CRITIQUE"
  statut string "IDENTIFIE→CLOTURE"
  plan_mitigation text
  source string "MANUAL | AI_SUGGESTED"
  feuille_route_id uuid fk
  created_by string
  date_identification date
}

// ── RELATIONSHIPS ─────────────────────────────────────
invoice_flags.invoice_id > invoices.id
journal_entries.source_invoice_id > invoices.id
journal_lines.entry_id > journal_entries.id
assets.supplier_invoice_id > invoices.id
client_invoices.projet_id > chartes_projet.id
chartes_projet.chef_projet_id > users.id
audit_logs.user_id > users.id
```
