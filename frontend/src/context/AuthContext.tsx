import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { getNotificationCount } from '../api/endpoints'
import { getToken, saveToken, clearToken } from '../api/client'

export type UserRole = 'Comptable' | 'Chef de Projet' | 'Direction' | 'Admin'

export const ROLE_PATHS: Record<UserRole, string[]> = {
  'Admin':          ['/admin', '/kpi'],
  'Comptable':      ['/upload', '/kpi', '/review', '/invoices', '/suivi', '/journal', '/grand-livre', '/billing', '/projects', '/projets-it', '/budget', '/capex', '/requetes', '/roadmap'],
  'Chef de Projet': ['/upload', '/kpi', '/invoices', '/suivi', '/billing', '/projects', '/projets-it', '/budget', '/roadmap'],
  'Direction':      ['/direction', '/kpi', '/budget', '/capex', '/requetes', '/roadmap'],
}

export function roleHome(role: UserRole): string {
  if (role === 'Direction')      return '/direction'
  if (role === 'Chef de Projet') return '/projects'
  if (role === 'Admin')          return '/admin/inscription'
  return '/kpi'
}

const ROLE_NAMES: Record<UserRole, string> = {
  'Comptable':      'Baya C.',
  'Chef de Projet': 'Karim B.',
  'Direction':      'Directeur',
  'Admin':          'Admin',
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
  isAuthenticated: boolean
  forcePasswordChange: boolean
  setRole: (r: UserRole) => void
  loginWithToken: (token: string, role: UserRole, forcePasswordChange?: boolean) => void
  logout: () => void
  clearForcePasswordChange: () => void
}

const AuthContext = createContext<AuthState>({} as AuthState)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<UserRole>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return (stored as UserRole) ?? 'Comptable'
  })
  const [isAuthenticated, setIsAuthenticated] = useState(() => !!getToken())
  const [notifCount, setNotifCount] = useState(0)
  const [forcePasswordChange, setForcePasswordChange] = useState(false)

  const setRole = (r: UserRole) => {
    localStorage.setItem(STORAGE_KEY, r)
    setRoleState(r)
  }

  const loginWithToken = (token: string, r: UserRole, fpc = false) => {
    saveToken(token)
    setRole(r)
    setIsAuthenticated(true)
    setForcePasswordChange(fpc)
  }

  const logout = () => {
    clearToken()
    setIsAuthenticated(false)
    setForcePasswordChange(false)
  }

  const clearForcePasswordChange = () => setForcePasswordChange(false)

  useEffect(() => {
    if (!isAuthenticated) return
    getNotificationCount()
      .then(d => setNotifCount(d.count))
      .catch(() => {})
    const id = setInterval(() => {
      getNotificationCount()
        .then(d => setNotifCount(d.count))
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(id)
  }, [isAuthenticated])

  const name = ROLE_NAMES[role]

  return (
    <AuthContext.Provider value={{
      role, setRole, name, initials: initials(name), notifCount,
      isAuthenticated, forcePasswordChange,
      loginWithToken, logout, clearForcePasswordChange,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
