import { apiFetch, apiUpload } from './client'

import type {
  Invoice, InvoiceSummary, JournalEntry, BudgetSummary,
  Asset, KpiData, ClientTemplate, ClientInvoice, NLQueryResult, SuiviSnapshot,
  Project, ProjectPhase,
  UserMe, AdminUser,
  LigneBudget, BudgetSynthese,
  RoadmapItem,
  Livrable,
  NotificationItem,
  AuditLog,
  MonthlySpendItem,
  SupplierSpendItem,
  BudgetPlanEntry,
  AccountSpendItem,
  AnalyticsKPIs,
  Risk, RiskSummary,
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

// ── Risks ─────────────────────────────────────────────────────────────────────

export const listRisks = (params: {
  projet_id?: string
  feuille_route_id?: string
  statut?: string
  niveau_criticite?: string
} = {}) => {
  const q = new URLSearchParams()
  if (params.projet_id)        q.set('projet_id', params.projet_id)
  if (params.feuille_route_id) q.set('feuille_route_id', params.feuille_route_id)
  if (params.statut)           q.set('statut', params.statut)
  if (params.niveau_criticite) q.set('niveau_criticite', params.niveau_criticite)
  const qs = q.toString()
  return apiFetch<Risk[]>(`/risks${qs ? '?' + qs : ''}`)
}

export const getRiskSummary = () =>
  apiFetch<RiskSummary>('/risks/summary')

export const getRisksForRoadmap = (feuilleRouteId: string) =>
  apiFetch<Risk[]>(`/risks/roadmap/${feuilleRouteId}`)

export const getRisksForProject = (projetId: string) =>
  apiFetch<Risk[]>(`/risks/projet/${projetId}`)

export const createRisk = (body: {
  titre: string
  description?: string
  type_risque?: string
  probabilite: string
  impact: string
  statut?: string
  plan_mitigation?: string
  responsable_id?: string | null
  date_identification: string
  date_echeance_mitigation?: string | null
  feuille_route_id?: string | null
  projet_id?: string | null
}) =>
  apiFetch<Risk>('/risks', { method: 'POST', body: JSON.stringify(body) })

export const updateRisk = (id: string, body: {
  titre?: string
  description?: string
  type_risque?: string
  probabilite?: string
  impact?: string
  statut?: string
  plan_mitigation?: string
  responsable_id?: string | null
  date_echeance_mitigation?: string | null
}) =>
  apiFetch<Risk>(`/risks/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const closeRisk = (id: string) =>
  apiFetch<void>(`/risks/${id}`, { method: 'DELETE' })

// ── Password verification (OTP + reset link) ─────────────────────────────────

export const requestOtp = (newPassword: string, currentPassword?: string) =>
  apiFetch<{ message: string }>('/auth/change-password/request-otp', {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword, current_password: currentPassword ?? null }),
  })

export const confirmOtp = (otpCode: string, newPassword: string, currentPassword?: string) =>
  apiFetch<{ success: boolean; message: string }>('/auth/change-password/confirm', {
    method: 'POST',
    body: JSON.stringify({ otp_code: otpCode, new_password: newPassword, current_password: currentPassword ?? null }),
  })

export const forgotPassword = (email: string) =>
  apiFetch<{ message: string }>('/auth/forgot-password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })

export const resetPassword = (token: string, newPassword: string) =>
  apiFetch<{ success: boolean; message: string }>('/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  })

// ── Health ────────────────────────────────────────────────────────────────────

export const checkHealth = () =>
  apiFetch<{ status: string }>('/health')

// ── AI ────────────────────────────────────────────────────────────────────────

export interface HealthSummaryResult {
  summary: string
  status_label: 'Satisfaisant' | 'Vigilance requise' | 'Critique' | string
  kpis_snapshot: Record<string, number>
  generated_at: string
  ollama_available: boolean
}

export interface PipelineStatusStep {
  step: number
  name: string
  status: 'waiting' | 'running' | 'done' | 'failed' | 'skipped'
  summary?: string | null
  reason?: string | null
}

export interface JournalLine {
  compte: string
  libelle: string
  debit: number
  credit: number
}

export interface PipelineJournalEntry {
  id: string
  reference: string
  date_ecriture: string
  description: string
  accounting_explanation: string | null
  is_balanced: boolean
  lines: JournalLine[]
}

export interface PipelineStatus {
  invoice_id: string
  final_status: string
  steps: PipelineStatusStep[]
  degraded_mode: boolean
  human_review_required: boolean
  journal_entry: PipelineJournalEntry | null
}

export const getAIHealthSummary = () =>
  apiFetch<HealthSummaryResult>('/ai/health-summary')

export const getPipelineStatus = (invoiceId: string) =>
  apiFetch<PipelineStatus>(`/invoices/${invoiceId}/pipeline-status`)

export const suggestMitigation = (body: {
  titre: string; type_risque: string; probabilite: string; impact: string
}) =>
  apiFetch<{ suggestion: string; duration_ms: number }>('/ai/suggest-mitigation', {
    method: 'POST',
    body: JSON.stringify(body),
  })

export const getAIActivity = () =>
  apiFetch<{ ollama_stats: { total_calls: number; success_rate: number; avg_duration_ms: number }; ollama_available: boolean; model: string }>('/ai/activity')

export const scanRoadmapRisks = () =>
  apiFetch<{ items_scanned: number; risks_created: number; items_skipped: number }>('/ai/scan-roadmap-risks', { method: 'POST' })

export const correctClassification = (invoiceId: string, body: {
  cost_catalog_id: string; accounting_compte: string; invoice_text?: string
}) =>
  apiFetch<{ invoice_id: string; corrected_compte: string; feedback_count: number; retrain_triggered: boolean }>(
    `/ai/invoices/${invoiceId}/classification`,
    { method: 'PATCH', body: JSON.stringify(body) }
  )

// ── Security ──────────────────────────────────────────────────────────────────

export interface SecuritySummary {
  total_logins_today: number
  failed_logins_today: number
  locked_accounts_count: number
  uploads_today: number
  rejected_files_today: number
  last_integrity_check: string | null
  last_integrity_score: number | null
  tampered_entries_count: number
  active_sessions_count: number
  unauthorized_access_attempts_today: number
  accounts_with_recent_failures: { email: string; failed_attempts: number; last_attempt: string | null }[]
  locked_accounts: { id: string; email: string; locked_until: string | null; failed_attempts: number }[]
}

export interface IntegrityResult {
  total_checked: number
  valid: number
  tampered_count: number
  tampered_entries: { id: string; created_at: string; action: string }[]
  integrity_score: number
  checked_at: string
}

export interface ActiveSession {
  jti: string
  created_at: string
  expires_at: string
  ip_address: string | null
  is_current: boolean
}

export const getSecuritySummary = () =>
  apiFetch<SecuritySummary>('/security/summary')

export const verifyAuditIntegrity = () =>
  apiFetch<IntegrityResult>('/audit/verify-integrity')

export const unlockAccount = (userId: string) =>
  apiFetch<{ message: string }>(`/security/unlock-account/${userId}`, { method: 'POST' })

export const getSessions = () =>
  apiFetch<{ sessions: ActiveSession[] }>('/auth/sessions')

export const revokeSession = (jtiPrefix: string) =>
  apiFetch<{ revoked: number }>('/auth/revoke-session', {
    method: 'POST',
    body: JSON.stringify({ jti_prefix: jtiPrefix }),
  })

export const logoutApi = () =>
  apiFetch<{ message: string }>('/auth/logout', { method: 'POST' })
