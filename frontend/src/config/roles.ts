import type { UserRole } from '../context/AuthContext'

export const ROLE_PATHS: Record<UserRole, string[]> = {
  'Admin':          ['/admin', '/kpi', '/audit', '/audit-reports', '/ai-activity', '/security'],
  'Comptable':      ['/upload', '/kpi', '/review', '/invoices', '/suivi', '/echeancier', '/journal', '/grand-livre', '/billing', '/projects', '/projets-it', '/budget', '/capex', '/requetes', '/roadmap', '/risques', '/audit-reports'],
  'Chef de Projet': ['/upload', '/kpi', '/invoices', '/suivi', '/billing', '/projects', '/projets-it', '/budget', '/roadmap', '/risques', '/audit-reports'],
  'Direction':      ['/direction', '/kpi', '/budget', '/capex', '/echeancier', '/requetes', '/roadmap', '/risques', '/audit', '/audit-reports'],
}
