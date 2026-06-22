// ── Invoice ───────────────────────────────────────────────────────────────────

export interface ConfidenceField {
  value: string | number | null
  confidence: number
}

export interface LineItem {
  line_number: number
  description: string | null
  quantity: number | null
  unit_price: number | null
  line_total: number | null
  tva_rate: number | null
}

export interface InvoiceFlag {
  flag_type: string
  severity: 'ERROR' | 'WARNING' | 'INFO'
  field_name: string | null
  message: string
  resolved: boolean
}

export interface Invoice {
  id: string
  status: InvoiceStatus
  direction: InvoiceDirection
  issuer_name: ConfidenceField
  issuer_tax_id: ConfidenceField
  recipient_name: ConfidenceField
  invoice_number: ConfidenceField
  invoice_date: ConfidenceField
  amount_ht: ConfidenceField
  tva_rate: ConfidenceField
  tva_amount: ConfidenceField
  amount_ttc: ConfidenceField
  currency: string
  accounting_compte: string | null
  accounting_label: string | null
  extraction_method: string | null
  flags: InvoiceFlag[]
  human_review_required: boolean
  received_at: string
  line_items: LineItem[]
}

export interface InvoiceSummary {
  id: string
  status: InvoiceStatus
  direction: InvoiceDirection
  issuer_name: string | null
  invoice_number: string | null
  invoice_date: string | null
  amount_ht: number | null
  tva_rate: number | null
  tva_amount: number | null
  amount_ttc: number | null
  currency: string
  accounting_compte: string | null
  accounting_label: string | null
  extraction_method: string | null
  flags: InvoiceFlag[]
  human_review_required: boolean
  has_errors: boolean
  received_at: string
}

export type InvoiceStatus =
  | 'RECEIVED' | 'EXTRACTING' | 'EXTRACTED'
  | 'CLASSIFYING' | 'CLASSIFIED'
  | 'VALIDATING' | 'VALIDATED' | 'FLAGGED'
  | 'EXPORTING' | 'EXPORTED'
  | 'JOURNALING' | 'JOURNALED'
  | 'PAID' | 'COLLECTED'
  | 'ERROR' | 'REJECTED' | 'EXTRACTION_FAILED' | 'ESCALATED'

export type InvoiceDirection = 'SUPPLIER' | 'CLIENT' | 'UNKNOWN'

// ── Journal ───────────────────────────────────────────────────────────────────

export interface JournalLine {
  compte: string
  libelle: string
  debit: number
  credit: number
}

export interface JournalEntry {
  id: string
  reference: string
  date_ecriture: string
  description: string
  lines: JournalLine[]
  source_invoice_id: string | null
}

// ── Budget ────────────────────────────────────────────────────────────────────

export interface BudgetLine {
  catalog_id: string
  label: string
  budget_ytd: number
  actual_ytd: number
  variance: number
  variance_pct: number
  is_over: boolean
}

export interface BudgetSummary {
  year: number
  through_month: number
  total_budget_ytd: number
  total_actual_ytd: number
  variance_pct: number
  lines_over_budget: number
  lines: BudgetLine[]
}

// ── CAPEX ─────────────────────────────────────────────────────────────────────

export interface Asset {
  id: string
  designation: string
  compte_immobilisation: string
  acquisition_date: string
  acquisition_cost_ht: number
  useful_life_years: number
  depreciation_method: string
  fully_depreciated: boolean
}

// ── KPI ───────────────────────────────────────────────────────────────────────

export interface KpiData {
  total_invoices: number
  total_amount_ttc: number
  auto_approved: number
  auto_approval_rate: number
  flagged: number
  pending_review: number
  by_status: Record<string, number>
}

// ── Billing ───────────────────────────────────────────────────────────────────

export interface ClientTemplate {
  id: string
  client_code: string
  client_name: string
  service_description: string
  unit_price_ht: number
  tva_rate: number
}

// ── Projects ─────────────────────────────────────────────────────────────────

export type ProjectStatus = 'ACTIVE' | 'COMPLETED' | 'ON_HOLD' | 'CANCELLED'

export interface Project {
  id: string
  name: string
  client: string
  budget_jh: number
  consumed_jh: number
  taux_jh: number
  status: ProjectStatus
  start_date: string
  end_date: string | null
  budget_tnd: number
  spent_tnd: number
}

export interface ProjectPhase {
  id: string
  project_id: string
  name: string
  planned_jh: number
  consumed_jh: number
  status: 'OPEN' | 'IN_PROGRESS' | 'CLOSED'
}

// ── Suivi ─────────────────────────────────────────────────────────────────────

export interface AgeingBucket {
  current: number; count_current: number
  days_1_30: number; count_1_30: number
  days_31_60: number; count_31_60: number
  days_61_90: number; count_61_90: number
  over_90: number; count_over_90: number
}

export interface SuiviSnapshot {
  total_payables: number
  total_receivables: number
  overdue_count: number
  pending_payment_count: number
  pending_collection_count: number
  payables_ageing: AgeingBucket
  receivables_ageing: AgeingBucket
  pending_payment: InvoiceSummary[]
  pending_collection: InvoiceSummary[]
  overdue: InvoiceSummary[]
}

// ── NL Query ─────────────────────────────────────────────────────────────────

export interface NLQueryResult {
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  row_count: number
  error: string | null
}
