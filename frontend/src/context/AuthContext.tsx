import { createContext, useContext } from 'react'

export type UserRole = 'Comptable' | 'Chef de Projet' | 'Direction' | 'Admin'

export interface AuthState {
  role: UserRole
  name: string
  initials: string
  avatar: string | null
  setAvatar: (url: string | null) => void
  notifCount: number
  setNotifCount: (count: number | ((prev: number) => number)) => void
  isAuthenticated: boolean
  isBootstrapping: boolean
  forcePasswordChange: boolean
  isDemoUser: boolean
  setRole: (r: UserRole) => void
  loginWithToken: (token: string, role: UserRole, forcePasswordChange?: boolean) => void
  logout: () => void
  clearForcePasswordChange: () => void
}

export const AuthContext = createContext<AuthState>({} as AuthState)

export const useAuth = () => useContext(AuthContext)
