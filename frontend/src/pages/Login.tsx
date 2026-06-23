import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BarChart2, FolderOpen, TrendingUp } from 'lucide-react'
import { useAuth, type UserRole } from '../context/AuthContext'

const roles: { id: UserRole; label: string; sub: string; icon: React.ReactNode }[] = [
  { id: 'Comptable',      label: 'Comptable',      sub: 'Factures & Journal', icon: <BarChart2 size={16} /> },
  { id: 'Chef de Projet', label: 'Chef de Projet', sub: 'Billing & Budget',   icon: <FolderOpen size={16} /> },
  { id: 'Direction',      label: 'Direction',      sub: 'KPIs & Tableaux',    icon: <TrendingUp size={16} /> },
]

export default function Login() {
  const { setRole } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [selectedRole, setSelectedRole] = useState<UserRole>('Comptable')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setRole(selectedRole)
    navigate('/kpi')
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden">
      {/* ── Left branding panel ── */}
      <div
        className="relative flex flex-col justify-center px-12 overflow-hidden"
        style={{ width: '40%', background: '#1A3A5C', flexShrink: 0 }}
      >
        {/* Decorative circles */}
        <div
          className="absolute rounded-full"
          style={{ width: 320, height: 320, bottom: -96, left: -96, border: '1px solid rgba(255,255,255,0.08)' }}
        />
        <div
          className="absolute rounded-full"
          style={{ width: 220, height: 220, top: -64, right: -64, border: '1px solid rgba(255,255,255,0.08)' }}
        />
        <div
          className="absolute rounded-full"
          style={{ width: 120, height: 120, bottom: 96, right: 32, border: '1px solid rgba(255,255,255,0.06)' }}
        />

        <div className="relative z-10 flex flex-col gap-5">
          {/* Logo box */}
          <div
            className="flex flex-col items-center justify-center gap-1.5 rounded-xl"
            style={{ width: 56, height: 56, background: '#14293F' }}
          >
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
      <div
        className="flex flex-1 items-center justify-center p-8"
        style={{ background: '#F0F4F9' }}
      >
        <div
          className="w-full rounded-2xl bg-white p-10"
          style={{ maxWidth: 420, boxShadow: '0 4px 24px rgba(26,58,92,0.10)' }}
        >
          <h2 className="text-2xl font-bold mb-1" style={{ color: '#1A1A2E' }}>Connexion</h2>
          <p className="text-sm mb-7" style={{ color: '#5D6D7E' }}>Accédez à votre espace de gestion</p>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* Email */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Adresse email</label>
              <input
                type="email"
                placeholder="vous@biat-it.tn"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-all w-full"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
              />
            </div>

            {/* Password */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Mot de passe</label>
              <input
                type="password"
                placeholder="············"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-all w-full"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
              />
            </div>

            {/* Role selector */}
            <div className="flex flex-col gap-2">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Votre rôle</label>
              <div className="grid grid-cols-3 gap-2">
                {roles.map(r => {
                  const active = selectedRole === r.id
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setSelectedRole(r.id)}
                      className="flex flex-col items-center gap-1.5 rounded-xl p-3 text-center transition-all"
                      style={{
                        border: active ? '2px solid #1A3A5C' : '1px solid #D5E8F5',
                        background: active ? '#F5F8FC' : '#fff',
                      }}
                    >
                      <div
                        className="flex items-center justify-center rounded-lg"
                        style={{
                          width: 32, height: 32,
                          background: active ? '#EFF4FA' : '#F8FAFC',
                          color: active ? '#1A3A5C' : '#5D6D7E',
                        }}
                      >
                        {r.icon}
                      </div>
                      <span className="text-xs font-semibold leading-tight" style={{ color: active ? '#1A3A5C' : '#1A1A2E' }}>
                        {r.label}
                      </span>
                      <span className="text-[10px] leading-tight" style={{ color: '#9BAFBF' }}>
                        {r.sub}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 mt-2"
              style={{ background: '#1A3A5C' }}
            >
              Se connecter
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
