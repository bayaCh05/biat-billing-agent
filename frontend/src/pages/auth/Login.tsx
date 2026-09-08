import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, type UserRole } from '../../context/AuthContext'
import { roleHome } from '../../config/navigation'
import { apiLogin } from '../../api/client'

export default function Login() {
  const { loginWithToken } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail]     = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password) return setError('Veuillez remplir tous les champs.')
    setLoading(true)
    try {
      const { access_token, role, force_password_change } = await apiLogin(email.trim(), password)
      loginWithToken(access_token, role as UserRole, force_password_change)
      if (force_password_change) {
        navigate('/changer-mot-de-passe')
      } else {
        navigate(roleHome(role as UserRole))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Identifiants incorrects.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* ── Left branding panel ── */}
      <div
        className="relative flex flex-col justify-center px-12 overflow-hidden"
        style={{ width: '40%', background: '#1A3A5C', flexShrink: 0 }}
      >
        <div className="absolute rounded-full"
          style={{ width: 320, height: 320, bottom: -96, left: -96, border: '1px solid rgba(255,255,255,0.08)' }} />
        <div className="absolute rounded-full"
          style={{ width: 220, height: 220, top: -64, right: -64, border: '1px solid rgba(255,255,255,0.08)' }} />
        <div className="absolute rounded-full"
          style={{ width: 120, height: 120, bottom: 96, right: 32, border: '1px solid rgba(255,255,255,0.06)' }} />

        <div className="relative z-10 flex flex-col gap-5">
          <div className="flex flex-col items-center justify-center gap-1.5 rounded-xl"
            style={{ width: 56, height: 56, background: '#14293F' }}>
            <div className="rounded-full" style={{ width: 20, height: 3, background: '#5BA3C9' }} />
            <div className="rounded-full" style={{ width: 14, height: 3, background: '#F0A600' }} />
          </div>

          <h1 className="text-5xl font-bold text-white tracking-tight">BIAT</h1>

          <div className="flex flex-col gap-2">
            <p className="text-xs font-semibold tracking-widest" style={{ color: '#F0A600' }}>
              INNOVATION &amp; TECHNOLOGY
            </p>
            <div className="rounded-full" style={{ width: 32, height: 2, background: '#F0A600' }} />
          </div>

          <p className="text-xl font-medium text-white leading-snug">
            Système Intelligent de<br />Gestion de Facturation
          </p>

          <p className="text-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.55)', maxWidth: 280 }}>
            Traitement automatisé des factures fournisseurs et facturation client pour BIAT IT, Tunisie.
          </p>
        </div>
      </div>

      {/* ── Right login panel ── */}
      <div className="flex flex-1 items-center justify-center p-8" style={{ background: '#F0F4F9' }}>
        <div className="w-full rounded-2xl bg-white p-10" style={{ maxWidth: 400, boxShadow: '0 4px 24px rgba(26,58,92,0.10)' }}>
          <h2 className="text-2xl font-bold mb-1" style={{ color: '#1A1A2E' }}>Connexion</h2>
          <p className="text-sm mb-8" style={{ color: '#5D6D7E' }}>Accédez à votre espace de gestion</p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Adresse email</label>
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-all w-full"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                placeholder="vous@biat-it.tn"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-medium" style={{ color: '#374151' }}>Mot de passe</label>
                <Link
                  to="/forgot-password"
                  className="text-xs hover:underline"
                  style={{ color: '#5BA3C9' }}
                >
                  Mot de passe oublié ?
                </Link>
              </div>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-all w-full"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="rounded-lg px-3 py-2.5 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 mt-1 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Connexion…' : 'Se connecter'}
            </button>
          </form>

          <p className="text-xs text-center mt-6" style={{ color: '#9BAFBF' }}>
            © 2026 BIAT Innovation &amp; Technology — Système sécurisé
          </p>
        </div>
      </div>
    </div>
  )
}
