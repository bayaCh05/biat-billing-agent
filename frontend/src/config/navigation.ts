import type { UserRole } from '../context/AuthContext'

export function roleHome(role: UserRole): string {
  if (role === 'Direction') return '/direction'
  if (role === 'Chef de Projet') return '/projects'
  if (role === 'Admin') return '/admin/inscription'
  return '/kpi'
}
