import { apiFetch, apiUpload } from './client'
import type {
  Invoice, InvoiceSummary, JournalEntry, BudgetSummary,
  Asset, KpiData, ClientTemplate, ClientInvoice, NLQueryResult, SuiviSnapshot,
  Project, ProjectPhase,
} from '../types'

// ── Invoices ──────────────────────────────────────────────────────────────────

export const uploadInvoice = (file: File, live = false) => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('live', String(live))
  return apiUpload<Invoice>('/invoices/upload', fd)
}

export const listInvoices = (status?: string) =>
  apiFetch<InvoiceSummary[]>(`/invoices${status ? `?status=${status}` : ''}`)

export const getInvoice = (id: string) =>
  apiFetch<Invoice>(`/invoices/${id}`)

// ── Review ────────────────────────────────────────────────────────────────────

export const getReviewQueue = () =>
  apiFetch<InvoiceSummary[]>('/review')

export const approveInvoice = (id: string, notes = '') =>
  apiFetch<{ action: string }>(`/review/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })

export const rejectInvoice = (id: string, notes = '') =>
  apiFetch<{ action: string }>(`/review/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  })

// ── Journal ───────────────────────────────────────────────────────────────────

export const listJournal = (start?: string, end?: string) => {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  const q = params.toString()
  return apiFetch<JournalEntry[]>(`/journal${q ? `?${q}` : ''}`)
}

// ── Budget ────────────────────────────────────────────────────────────────────

export const getBudgetSummary = (year?: number, month?: number) => {
  const params = new URLSearchParams()
  if (year) params.set('year', String(year))
  if (month) params.set('month', String(month))
  const q = params.toString()
  return apiFetch<BudgetSummary>(`/budget/summary${q ? `?${q}` : ''}`)
}

// ── CAPEX ─────────────────────────────────────────────────────────────────────

export const listAssets = () =>
  apiFetch<Asset[]>('/assets')

// ── KPI ───────────────────────────────────────────────────────────────────────

export const getKpi = () =>
  apiFetch<KpiData>('/kpi')

// ── Billing ───────────────────────────────────────────────────────────────────

export const listTemplates = () =>
  apiFetch<ClientTemplate[]>('/billing/templates')

export const listClientInvoices = () =>
  apiFetch<ClientInvoice[]>('/billing/invoices')

export const generateInvoice = (template_id: string, year: number, month: number) =>
  apiFetch<{ invoice_number: string; amount_ttc: number }>('/billing/generate', {
    method: 'POST',
    body: JSON.stringify({ template_id, year, month }),
  })

// ── NL Query ─────────────────────────────────────────────────────────────────

export const nlQuery = (question: string) =>
  apiFetch<NLQueryResult>('/nl-query', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })

// ── Suivi ────────────────────────────────────────────────────────────────────

export const getSuiviSnapshot = () =>
  apiFetch<SuiviSnapshot>('/suivi/snapshot')

// ── Notifications ─────────────────────────────────────────────────────────────

export const getNotificationCount = () =>
  apiFetch<{ count: number }>('/notifications/count')

// ── Projects ──────────────────────────────────────────────────────────────────

export const listProjects = () =>
  apiFetch<Project[]>('/projects')

export const listProjectPhases = (project_id: string) =>
  apiFetch<ProjectPhase[]>(`/projects/${project_id}/phases`)

// ── Health ────────────────────────────────────────────────────────────────────

export const checkHealth = () =>
  apiFetch<{ status: string }>('/health')
