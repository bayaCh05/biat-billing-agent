import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { getNotificationCount, getMe } from '../api/endpoints'
import { getToken, saveToken, clearToken } from '../api/client'

export type UserRole = 'Comptable' | 'Chef de Projet' | 'Direction' | 'Admin'

export function roleHome(role: UserRole): string {
  if (role === 'Direction')      return '/direction'
  if (role === 'Chef de Projet') return '/projects'
  if (role === 'Admin')          return '/admin/inscription'
  return '/kpi'
}

const ROLE_FALLBACK_NAMES: Record<UserRole, string> = {
  'Comptable':      'Comptable',
  'Chef de Projet': 'Chef de Projet',
  'Direction':      'Directeur',
  'Admin':          'Admin',
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(b64))
  } catch {
    return {}
  }
}

function isDemoToken(token: string): boolean {
  const payload = decodeJwtPayload(token)
  return typeof payload.sub === 'string' && payload.sub.startsWith('demo:')
}

function nameFromToken(token: string, role: UserRole): string {
  const payload = decodeJwtPayload(token)
  const prenom = typeof payload.prenom === 'string' ? payload.prenom : ''
  const nom    = typeof payload.nom    === 'string' ? payload.nom    : ''
  if (prenom || nom) return `${prenom} ${nom}`.trim()
  return ROLE_FALLBACK_NAMES[role]
}

function initials(name: string) {
  return name.split(' ').map(w => w[0]).filter(Boolean).join('').toUpperCase().slice(0, 2)
}

const STORAGE_KEY = 'biat_role'

interface AuthState {
  role: UserRole
  name: string
  initials: string
  avatar: string | null
  setAvatar: (url: string | null) => void
  notifCount: number
  setNotifCount: (count: number | ((prev: number) => number)) => void
  isAuthenticated: boolean
  forcePasswordChange: boolean
  isDemoUser: boolean
  setRole: (r: UserRole) => void
  loginWithToken: (token: string, role: UserRole, forcePasswordChange?: boolean) => void
  logout: () => void
  clearForcePasswordChange: () => void
}

const AuthContext = createContext<AuthState>({} as AuthState)

export function AuthProvider({ children }: { children: ReactNode }) {
  const storedRole = (localStorage.getItem(STORAGE_KEY) as UserRole) ?? 'Comptable'
  const [role, setRoleState] = useState<UserRole>(storedRole)
  const [name, setName] = useState<string>(ROLE_FALLBACK_NAMES[storedRole])
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [notifCount, setNotifCount] = useState(0)
  const [forcePasswordChange, setForcePasswordChange] = useState(false)
  const [isDemoUser, setIsDemoUser] = useState(false)
  const [avatar, setAvatar] = useState<string | null>(null)

  // On mount: try to restore session via refresh cookie only if the user had a previous session.
  // We skip this on fresh visits (no stored role) to avoid a noisy CORS call on the login page.
  useEffect(() => {
    if (getToken()) { setIsAuthenticated(true); return }
    if (!localStorage.getItem(STORAGE_KEY)) return  // no prior session
    const base = import.meta.env.VITE_API_URL
      ? `${import.meta.env.VITE_API_URL}/api`
      : '/api'
    fetch(`${base}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(r => {
        if (r.status === 401) {
          localStorage.removeItem(STORAGE_KEY)
          window.location.replace('/login')
          return null
        }
        return r.ok ? r.json() : null
      })
      .then((data: { access_token: string; role: string } | null) => {
        if (data?.access_token) {
          saveToken(data.access_token)
          const r = (data.role as UserRole) ?? storedRole
          localStorage.setItem(STORAGE_KEY, r)
          setRoleState(r)
          setName(nameFromToken(data.access_token, r))
          setIsDemoUser(isDemoToken(data.access_token))
          setIsAuthenticated(true)
        }
      })
      .catch(() => {
        localStorage.removeItem(STORAGE_KEY)
        window.location.replace('/login')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setRole = (r: UserRole) => {
    localStorage.setItem(STORAGE_KEY, r)
    setRoleState(r)
  }

  const loginWithToken = (token: string, r: UserRole, fpc = false) => {
    saveToken(token)
    setRole(r)
    setName(nameFromToken(token, r))
    setIsDemoUser(isDemoToken(token))
    setIsAuthenticated(true)
    setForcePasswordChange(fpc)
  }

  const logout = () => {
    clearToken()
    setIsAuthenticated(false)
    setForcePasswordChange(false)
    setIsDemoUser(false)
    setAvatar(null)
  }

  const clearForcePasswordChange = () => setForcePasswordChange(false)

  // Charge le compteur de notifications et la photo de profil après connexion
  useEffect(() => {
    if (!isAuthenticated) return
    getNotificationCount()
      .then(d => setNotifCount(d.count))
      .catch(() => {})
    getMe()
      .then(u => setAvatar(u.profile_picture ?? null))
      .catch(() => {})
    const id = setInterval(() => {
      getNotificationCount()
        .then(d => setNotifCount(d.count))
        .catch(() => {})
    }, 60_000)
    return () => clearInterval(id)
  }, [isAuthenticated])

  return (
    <AuthContext.Provider value={{
      role, setRole, name, initials: initials(name), avatar, setAvatar,
      notifCount, setNotifCount,
      isAuthenticated, forcePasswordChange, isDemoUser,
      loginWithToken, logout, clearForcePasswordChange,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
