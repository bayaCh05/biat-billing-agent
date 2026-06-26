// In dev: VITE_API_URL=http://localhost:8000 (cross-origin, frontend on :5173)
// In Docker: VITE_API_URL="" → relative /api (same-origin, everything on :8000)
const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

const TOKEN_KEY = 'biat_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function saveToken(t: string): void {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem('biat_role')
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handle401(): never {
  clearToken()
  window.location.replace('/login')
  throw new Error('Session expirée — veuillez vous reconnecter.')
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
    ...init,
  })
  if (res.status === 401) return handle401()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  })
  if (res.status === 401) return handle401()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function apiLogin(email: string, password: string): Promise<{ access_token: string; role: string; force_password_change: boolean }> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail ?? 'Identifiants incorrects.')
  }
  return res.json()
}
