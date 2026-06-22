import { useState, useEffect } from 'react'
import { apiFetch } from '../../api/client'

export default function ApiToast() {
  const [apiDown, setApiDown] = useState(false)

  useEffect(() => {
    const check = () =>
      apiFetch<{ status: string }>('/health')
        .then(() => setApiDown(false))
        .catch(() => setApiDown(true))

    check()
    const id = setInterval(check, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!apiDown) return null

  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20, zIndex: 9999,
      background: '#FEF0EE', border: '1px solid #C0391B',
      borderRadius: 10, padding: '10px 16px',
      display: 'flex', alignItems: 'center', gap: 10,
      boxShadow: '0 4px 12px rgba(0,0,0,0.12)', fontSize: 13,
    }}>
      <span style={{ color: '#C0391B', fontWeight: 700 }}>⚠</span>
      <div>
        <p style={{ color: '#C0391B', fontWeight: 600, margin: 0 }}>API indisponible</p>
        <p style={{ color: '#5D6D7E', fontSize: 11, margin: 0 }}>Mode démo — données simulées</p>
      </div>
    </div>
  )
}
