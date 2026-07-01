// In dev: VITE_API_URL=http://localhost:8000 (cross-origin, frontend on :5173)
// In Docker: VITE_API_URL="" → relative /api (same-origin, everything on :8000)
const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

// Token stored in memory only — never written to localStorage for security.
// Role + name are still persisted to localStorage for UX (surviving hard refresh).
let _accessToken: string | null = null
let _refreshing: Promise<string | null> | null = null

export function getToken(): string | null { return _accessToken }

export function saveToken(t: string): void { _accessToken = t }

export function clearToken(): void {
  _accessToken = null
  localStorage.removeItem('biat_role')
}

function decodeExp(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' ? payload.exp : 0
  } catch { return 0 }
}

async function tryRefresh(): Promise<string | null> {
  if (_refreshing) return _refreshing
  _refreshing = (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
      if (!res.ok) return null
      const data = await res.json()
      if (data.access_token) { _accessToken = data.access_token; return data.access_token }
      return null
    } catch { return null }
    finally { _refreshing = null }
  })()
  return _refreshing
}

async function getValidToken(): Promise<string | null> {
  if (!_accessToken) return null
  // Refresh proactively if token expires in < 5 min
  const exp = decodeExp(_accessToken)
  if (exp && exp - Date.now() / 1000 < 300) {
    const fresh = await tryRefresh()
    return fresh ?? _accessToken
  }
  return _accessToken
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function handle401(): never {
  clearToken()
  window.location.replace('/login')
  throw new Error('Session expirée — veuillez vous reconnecter.')
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getValidToken()
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders(token), ...init?.headers },
    ...init,
  })
  if (res.status === 401) return handle401()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

/** Fetch a binary response (e.g. ZIP download) and trigger a browser download. */
export async function apiBlobFetch(path: string, filename: string, init?: RequestInit): Promise<void> {
  const token = await getValidToken()
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(token),
    ...init,
  })
  if (res.status === 401) return handle401()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** POST a FormData and return JSON — used for file upload endpoints. */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const token = await getValidToken()
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders(token),
    body: formData,
  })
  if (res.status === 401) return handle401()
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function apiLogin(email: string, password: string): Promise<{ access_token: string; role: string; force_password_change: boolean; user_id?: string; expires_in?: number }> {
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
