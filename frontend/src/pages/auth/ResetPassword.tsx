import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { KeyRound, Eye, EyeOff, CheckCircle, AlertTriangle } from 'lucide-react'
import { resetPassword } from '../../api/endpoints'

export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [newPw, setNewPw]       = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [showNew, setShowNew]   = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState(false)

  useEffect(() => {
    if (!token) queueMicrotask(() => setError('Lien invalide — aucun token trouvé dans l\'URL.'))
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!token) return setError('Lien invalide.')
    if (newPw.length < 8)     return setError('Le mot de passe doit contenir au moins 8 caractères.')
    if (newPw !== confirmPw)  return setError('Les mots de passe ne correspondent pas.')

    setLoading(true)
    try {
      await resetPassword(token, newPw)
      setSuccess(true)
      setTimeout(() => navigate('/login?reset=1'), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lien invalide ou expiré.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center" style={{ background: '#F0F4F9' }}>
      <div className="w-full rounded-2xl bg-white p-10 shadow-lg" style={{ maxWidth: 420 }}>

        {/* Logo mark */}
        <div className="flex items-center gap-2 mb-6">
          <div className="flex flex-col gap-1 items-center justify-center rounded-lg"
            style={{ width: 36, height: 36, background: '#1A3A5C' }}>
            <div className="rounded-full" style={{ width: 14, height: 2, background: '#5BA3C9' }} />
            <div className="rounded-full" style={{ width: 10, height: 2, background: '#F0A600' }} />
          </div>
          <span className="text-sm font-bold" style={{ color: '#1A3A5C' }}>BIAT IT</span>
        </div>

        {success ? (
          <div className="flex flex-col items-center gap-4 py-4 text-center">
            <div className="flex items-center justify-center rounded-full"
              style={{ width: 56, height: 56, background: '#E8F5F0' }}>
              <CheckCircle size={28} style={{ color: '#1D9E76' }} />
            </div>
            <h2 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Mot de passe réinitialisé</h2>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>
              Votre mot de passe a été modifié avec succès.<br />
              Redirection vers la connexion…
            </p>
          </div>
        ) : !token ? (
          <div className="flex flex-col items-center gap-4 py-4 text-center">
            <div className="flex items-center justify-center rounded-full"
              style={{ width: 56, height: 56, background: '#FEF0EE' }}>
              <AlertTriangle size={28} style={{ color: '#C0391B' }} />
            </div>
            <h2 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Lien invalide</h2>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>
              Ce lien de réinitialisation est invalide ou a expiré.
            </p>
            <Link to="/forgot-password" className="text-sm font-semibold hover:underline" style={{ color: '#1A3A5C' }}>
              Demander un nouveau lien
            </Link>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="flex items-center justify-center rounded-xl"
                style={{ width: 44, height: 44, background: '#EFF4FA' }}>
                <KeyRound size={20} style={{ color: '#1A3A5C' }} />
              </div>
              <div>
                <h2 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Nouveau mot de passe</h2>
                <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>Définissez un nouveau mot de passe sécurisé</p>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="rounded-lg px-3 py-2.5 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>
                  {error}
                </div>
              )}

              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#374151' }}>
                  Nouveau mot de passe
                </label>
                <div className="relative">
                  <input
                    type={showNew ? 'text' : 'password'}
                    value={newPw}
                    onChange={e => setNewPw(e.target.value)}
                    autoComplete="new-password"
                    className="w-full border rounded-lg px-3 py-2.5 text-sm pr-9 outline-none transition-all"
                    style={{ borderColor: '#D5E8F5' }}
                    onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                    onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                    placeholder="••••••••"
                  />
                  <button type="button" onClick={() => setShowNew(v => !v)}
                    className="absolute right-2.5 top-3 text-gray-400 hover:text-gray-600">
                    {showNew ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium mb-1.5" style={{ color: '#374151' }}>
                  Confirmer le mot de passe
                </label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={e => setConfirmPw(e.target.value)}
                  autoComplete="new-password"
                  className="w-full border rounded-lg px-3 py-2.5 text-sm outline-none transition-all"
                  style={{ borderColor: '#D5E8F5' }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                  placeholder="••••••••"
                />
              </div>

              <div className="rounded-lg px-3 py-2 text-xs" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
                Minimum 8 caractères.
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
                style={{ background: '#1A3A5C' }}
              >
                {loading ? 'Enregistrement…' : 'Définir le nouveau mot de passe'}
              </button>
            </form>

            <div className="mt-5 text-center">
              <Link to="/login" className="text-xs hover:underline" style={{ color: '#5BA3C9' }}>
                Retour à la connexion
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
