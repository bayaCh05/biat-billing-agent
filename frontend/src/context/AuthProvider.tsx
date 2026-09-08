import { useEffect, useState, type ReactNode } from 'react'
import { getNotificationCount, getMe } from '../api/endpoints'
import { getToken, saveToken, clearToken } from '../api/client'
import { AuthContext, type UserRole } from './AuthContext'

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

export function AuthProvider({ children }: { children: ReactNode }) {
  const storedRole = (localStorage.getItem(STORAGE_KEY) as UserRole) ?? 'Comptable'
  const [role, setRoleState] = useState<UserRole>(storedRole)
  const [name, setName] = useState<string>(ROLE_FALLBACK_NAMES[storedRole])
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(getToken()))
  // True while we still have a session to try restoring via the refresh
  // cookie (stored role, no in-memory token yet — e.g. right after a hard
  // reload). AuthGuard must wait for this before deciding to redirect to
  // /login, otherwise it redirects on the very first render, before the
  // refresh call below even gets a chance to run.
  const [isBootstrapping, setIsBootstrapping] = useState(
    () => !getToken() && Boolean(localStorage.getItem(STORAGE_KEY)),
  )
  const [notifCount, setNotifCount] = useState(0)
  const [forcePasswordChange, setForcePasswordChange] = useState(false)
  const [avatar, setAvatar] = useState<string | null>(null)

  // On mount: try to restore session via refresh cookie only if the user had a previous session.
  // We skip this on fresh visits (no stored role) to avoid a noisy CORS call on the login page.
  useEffect(() => {
    if (getToken()) return
    if (!localStorage.getItem(STORAGE_KEY)) return
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
          setIsAuthenticated(true)
        }
      })
      .catch(() => {
        localStorage.removeItem(STORAGE_KEY)
        window.location.replace('/login')
      })
      .finally(() => setIsBootstrapping(false))
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
    setIsAuthenticated(true)
    setForcePasswordChange(fpc)
  }

  const logout = () => {
    clearToken()
    setIsAuthenticated(false)
    setForcePasswordChange(false)
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
      isAuthenticated, isBootstrapping, forcePasswordChange,
      loginWithToken, logout, clearForcePasswordChange,
    }}>
      {children}
    </AuthContext.Provider>
  )
}
