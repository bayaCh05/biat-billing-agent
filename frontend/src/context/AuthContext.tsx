import { createContext, useContext, useState, type ReactNode } from 'react'

export type UserRole = 'Comptable' | 'Chef de Projet' | 'Direction'

interface AuthState {
  role: UserRole
  name: string
  initials: string
  notifCount: number
  setRole: (r: UserRole) => void
}

const AuthContext = createContext<AuthState>({} as AuthState)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<UserRole>('Comptable')
  return (
    <AuthContext.Provider value={{ role, setRole, name: 'Baya C.', initials: 'BC', notifCount: 3 }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
