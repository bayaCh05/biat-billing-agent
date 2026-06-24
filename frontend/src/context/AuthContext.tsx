import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { getNotificationCount } from '../api/endpoints'

export type UserRole = 'Comptable' | 'Chef de Projet' | 'Direction'

export const ROLE_PATHS: Record<UserRole, string[]> = {
  'Comptable':      ['/upload', '/kpi', '/review', '/invoices', '/suivi', '/journal', '/grand-livre', '/billing', '/projects', '/budget', '/capex', '/requetes'],
  'Chef de Projet': ['/upload', '/kpi', '/invoices', '/suivi', '/billing', '/projects', '/budget'],
  'Direction':      ['/direction', '/kpi', '/budget', '/capex', '/requetes'],
}

export function roleHome(role: UserRole): string {
  if (role === 'Direction')      return '/direction'
  if (role === 'Chef de Projet') return '/projects'
  return '/kpi'
}

const ROLE_NAMES: Record<UserRole, string> = {
  'Comptable':      'Baya C.',
  'Chef de Projet': 'Karim B.',
  'Direction':      'Directeur',
}

function initials(name: string) {
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
}

const STORAGE_KEY = 'biat_role'

interface AuthState {
  role: UserRole
  name: string
  initials: string
  notifCount: number
  setRole: (r: UserRole) => void
}

const AuthContext = createContext<AuthState>({} as AuthState)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<UserRole>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return (stored as UserRole) ?? 'Comptable'
  })
  const [notifCount, setNotifCount] = useState(0)

  const setRole = (r: UserRole) => {
    localStorage.setItem(STORAGE_KEY, r)
    setRoleState(r)
  }

  useEffect(() => {
    getNotificationCount()
      .then(d => setNotifCount(d.count))
      .catch(() => {})
    const id = setInterval(() => {
      getNotificationCount()
        .then(d => setNotifCount(d.count))
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  const name = ROLE_NAMES[role]

  return (
    <AuthContext.Provider value={{ role, setRole, name, initials: initials(name), notifCount }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
