// In dev: VITE_API_URL=http://localhost:8000 (cross-origin, frontend on :5173)
// In Docker: VITE_API_URL="" → relative /api (same-origin, everything on :8000)
const BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api'

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST', body: formData })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}
