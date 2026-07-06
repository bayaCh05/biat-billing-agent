import type { UserRole } from '../context/AuthContext'

export const ROLE_PATHS: Record<UserRole, string[]> = {
  'Admin':          ['/admin', '/kpi', '/audit', '/ai-activity', '/security'],
  'Comptable':      ['/upload', '/kpi', '/review', '/invoices', '/suivi', '/echeancier', '/journal', '/grand-livre', '/billing', '/projects', '/projets-it', '/budget', '/capex', '/requetes', '/roadmap', '/risques'],
  'Chef de Projet': ['/upload', '/kpi', '/invoices', '/suivi', '/billing', '/projects', '/projets-it', '/budget', '/roadmap', '/risques'],
  'Direction':      ['/direction', '/kpi', '/budget', '/capex', '/echeancier', '/requetes', '/roadmap', '/risques', '/audit'],
}
