import type { UserRole } from '../context/AuthContext'

export const ROLE_PATHS: Record<UserRole, string[]> = {
  'Admin':          ['/admin', '/kpi', '/audit', '/notifications'],
  'Comptable':      ['/upload', '/kpi', '/review', '/invoices', '/suivi', '/journal', '/grand-livre', '/billing', '/projects', '/projets-it', '/budget', '/capex', '/requetes', '/roadmap', '/bct-export', '/notifications'],
  'Chef de Projet': ['/upload', '/kpi', '/invoices', '/suivi', '/billing', '/projects', '/projets-it', '/budget', '/roadmap', '/notifications'],
  'Direction':      ['/direction', '/kpi', '/budget', '/capex', '/requetes', '/roadmap', '/bct-export', '/audit', '/notifications'],
}
