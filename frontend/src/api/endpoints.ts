import { apiFetch, apiBlobFetch, apiUpload } from './client'

import type {
  Invoice, InvoiceSummary, JournalEntry, BudgetSummary,
  Asset, KpiData, ClientTemplate, ClientInvoice, NLQueryResult, SuiviSnapshot,
  Project, ProjectPhase,
  UserMe, AdminUser,
  LigneBudget, BudgetSynthese,
  RoadmapItem,
  Livrable,
  NotificationItem,
  BCTAgingItem,
  AuditLog,
  MonthlySpendItem,
  SupplierSpendItem,
  BudgetPlanEntry,
  AccountSpendItem,
  AnalyticsKPIs,
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

export const getBudgetPlan = (year: number) =>
  apiFetch<BudgetPlanEntry[]>(`/budget/plan?year=${year}`)

export const updateBudgetPlanEntry = (catalogId: string, year: number, body: { label?: string; monthly?: number[]; note?: string }) =>
  apiFetch<BudgetPlanEntry>(`/budget/plan/${catalogId}?year=${year}`, { method: 'PUT', body: JSON.stringify(body) })

export const createBudgetPlanEntry = (year: number, body: { catalog_id: string; label: string; monthly: number[]; note?: string }) =>
  apiFetch<BudgetPlanEntry>(`/budget/plan?year=${year}`, { method: 'POST', body: JSON.stringify(body) })

export const deleteBudgetPlanEntry = (catalogId: string, year: number) =>
  apiFetch<void>(`/budget/plan/${catalogId}?year=${year}`, { method: 'DELETE' })

// ── CAPEX ─────────────────────────────────────────────────────────────────────

export const listAssets = () =>
  apiFetch<Asset[]>('/assets')

export const createAsset = (body: {
  designation: string
  compte_immobilisation: string
  compte_amortissement: string
  acquisition_date: string
  acquisition_cost_ht: number
  useful_life_years: number
  depreciation_method: string
}) =>
  apiFetch<Asset>('/assets', { method: 'POST', body: JSON.stringify(body) })

// ── KPI ───────────────────────────────────────────────────────────────────────

export const getKpi = () =>
  apiFetch<KpiData>('/kpi')

// ── Billing ───────────────────────────────────────────────────────────────────

export const listTemplates = () =>
  apiFetch<ClientTemplate[]>('/billing/templates')

export const listClientInvoices = () =>
  apiFetch<ClientInvoice[]>('/billing/invoices')

export const generateInvoice = (
  template_id: string,
  year: number,
  month: number,
  bct?: {
    is_export: boolean
    currency: string
    foreign_currency_amount?: number | null
    exchange_rate?: number | null
    shipment_date?: string | null
    domiciliation_bank?: string | null
    domiciliation_number?: string | null
  },
) =>
  apiFetch<{ invoice_number: string; amount_ttc: number }>('/billing/generate', {
    method: 'POST',
    body: JSON.stringify({ template_id, year, month, ...(bct ?? {}) }),
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

export const getNotificationList = () =>
  apiFetch<NotificationItem[]>('/notifications/list')

export const markNotificationRead = (id: string) =>
  apiFetch<NotificationItem>(`/notifications/${id}/read`, { method: 'PATCH' })

export const markAllNotificationsRead = () =>
  apiFetch<{ count: number }>('/notifications/read-all', { method: 'POST' })

// ── Projects ──────────────────────────────────────────────────────────────────

export const listProjects = () =>
  apiFetch<Project[]>('/projects')

export const listProjectPhases = (project_id: string) =>
  apiFetch<ProjectPhase[]>(`/projects/${project_id}/phases`)

// ── Users / Me ───────────────────────────────────────────────────────────────

export const getMe = () =>
  apiFetch<UserMe>('/users/me')

export const updateMe = (body: { nom?: string; prenom?: string; departement?: string }) =>
  apiFetch<UserMe>('/users/me', { method: 'PATCH', body: JSON.stringify(body) })

export const changePassword = (current_password: string, new_password: string) =>
  apiFetch<{ message: string }>('/auth/change-password', {
    method: 'PATCH',
    body: JSON.stringify({ current_password, new_password }),
  })

// ── Admin ─────────────────────────────────────────────────────────────────────

export const listAdminUsers = () =>
  apiFetch<AdminUser[]>('/admin/users')

export const createAdminUser = (body: { nom: string; prenom: string; email: string; role: string; departement: string }) =>
  apiFetch<{ user_id: string; email: string; temp_password: string }>('/admin/users', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const updateAdminUser = (id: string, body: { role?: string; is_active?: boolean; departement?: string }) =>
  apiFetch<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const resetAdminUserPassword = (id: string) =>
  apiFetch<{ temp_password: string }>(`/admin/users/${id}/reset-password`, { method: 'POST' })

// ── BCT Export Compliance ─────────────────────────────────────────────────────

export const getBctAging = () =>
  apiFetch<BCTAgingItem[]>('/export/bct-aging')

export const markRepatriated = (invoiceId: string, repat_date?: string) =>
  apiFetch<{ invoice_id: string; repatriation_date: string; message: string }>(
    `/export/client-invoices/${invoiceId}/mark-repatriated`,
    { method: 'PATCH', body: JSON.stringify({ repatriation_date: repat_date ?? null }) },
  )

export const downloadBctReport = (from: string, to: string): Promise<void> =>
  apiBlobFetch(
    `/export/bct-report?from_=${from}&to=${to}`,
    `bct_report_${from}_${to}.zip`,
  )

export const verifyBctReport = (csvFile: File, sigFile: File): Promise<{ valid: boolean; message: string }> => {
  const fd = new FormData()
  fd.append('report_file', csvFile)
  fd.append('signature_file', sigFile)
  return apiUpload<{ valid: boolean; message: string }>('/export/bct-report/verify', fd)
}

// ── Project (single) ──────────────────────────────────────────────────────────

export const getProject = (id: string) =>
  apiFetch<Project>(`/projects/${id}`)

// ── Budget projet ─────────────────────────────────────────────────────────────

export const listProjetBudget = (projetId: string) =>
  apiFetch<LigneBudget[]>(`/projets/${projetId}/budget`)

export const createLigneBudget = (projetId: string, body: { categorie: string; montant_prevu: number; devise?: string }) =>
  apiFetch<LigneBudget>(`/projets/${projetId}/budget`, { method: 'POST', body: JSON.stringify(body) })

export const updateLigneBudget = (ligneId: string, body: { categorie?: string; montant_prevu?: number }) =>
  apiFetch<LigneBudget>(`/projet-budget/${ligneId}`, { method: 'PATCH', body: JSON.stringify(body) })

export const deleteLigneBudget = (ligneId: string) =>
  apiFetch<void>(`/projet-budget/${ligneId}`, { method: 'DELETE' })

export const getBudgetSynthese = (projetId: string) =>
  apiFetch<BudgetSynthese>(`/projets/${projetId}/budget/synthese`)

// ── Roadmap ───────────────────────────────────────────────────────────────────

export const listRoadmap = (annee = 2026) =>
  apiFetch<RoadmapItem[]>(`/roadmap?annee=${annee}`)

export const createRoadmapItem = (body: Partial<RoadmapItem>) =>
  apiFetch<RoadmapItem>('/roadmap', { method: 'POST', body: JSON.stringify(body) })

export const updateRoadmapItem = (id: string, body: Partial<RoadmapItem>) =>
  apiFetch<RoadmapItem>(`/roadmap/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const deleteRoadmapItem = (id: string) =>
  apiFetch<void>(`/roadmap/${id}`, { method: 'DELETE' })

// ── Livrables ─────────────────────────────────────────────────────────────────

export const listLivrables = (phaseId: string) =>
  apiFetch<Livrable[]>(`/phases/${phaseId}/livrables`)

export const createLivrable = (phaseId: string, body: { titre: string; description?: string; date_livraison_prevue: string; statut?: string }) =>
  apiFetch<Livrable>(`/phases/${phaseId}/livrables`, { method: 'POST', body: JSON.stringify(body) })

export const updateLivrable = (id: string, body: { statut?: string; date_livraison_reelle?: string; titre?: string }) =>
  apiFetch<Livrable>(`/livrables/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const validerPhase = (phaseId: string) =>
  apiFetch<{ message: string; status: string }>(`/phases/${phaseId}/valider`, { method: 'POST' })

// ── Analytics Direction ───────────────────────────────────────────────────────

export const getMonthlySpend = (year = 2026) =>
  apiFetch<MonthlySpendItem[]>(`/analytics/monthly-spend?year=${year}`)

export const getBySupplier = (year?: number) =>
  apiFetch<SupplierSpendItem[]>(`/analytics/by-supplier${year ? `?year=${year}` : ''}`)

export const getByAccount = (year?: number) =>
  apiFetch<AccountSpendItem[]>(`/analytics/by-account${year ? `?year=${year}` : ''}`)

export const getAnalyticsKPIs = (year = 2026) =>
  apiFetch<AnalyticsKPIs>(`/analytics/kpis?year=${year}`)

// ── Audit Trail ───────────────────────────────────────────────────────────────

export const listAuditLogs = (params: {
  action?: string
  resource_type?: string
  user_email?: string
  status?: string
  from_date?: string
  to_date?: string
  limit?: number
  offset?: number
} = {}) => {
  const q = new URLSearchParams()
  if (params.action)        q.set('action', params.action)
  if (params.resource_type) q.set('resource_type', params.resource_type)
  if (params.user_email)    q.set('user_email', params.user_email)
  if (params.status)        q.set('status', params.status)
  if (params.from_date)     q.set('from_date', params.from_date)
  if (params.to_date)       q.set('to_date', params.to_date)
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  const qs = q.toString()
  return apiFetch<AuditLog[]>(`/audit/logs${qs ? '?' + qs : ''}`)
}

export const getResourceHistory = (resourceType: string, resourceId: string) =>
  apiFetch<AuditLog[]>(`/audit/logs/${resourceType}/${resourceId}`)

// ── Health ────────────────────────────────────────────────────────────────────

export const checkHealth = () =>
  apiFetch<{ status: string }>('/health')
