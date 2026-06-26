import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KeyRound, Eye, EyeOff, CheckCircle } from 'lucide-react'
import { useAuth, roleHome } from '../context/AuthContext'
import { changePassword } from '../api/endpoints'

export default function ChangerMotDePassePage() {
  const navigate = useNavigate()
  const { role, clearForcePasswordChange } = useAuth()

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw]         = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew]         = useState(false)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!currentPw)          return setError('Veuillez saisir votre mot de passe actuel.')
    if (newPw.length < 8)    return setError('Le nouveau mot de passe doit contenir au moins 8 caractères.')
    if (newPw !== confirmPw) return setError('Les mots de passe ne correspondent pas.')

    setLoading(true)
    try {
      await changePassword(currentPw, newPw)
      clearForcePasswordChange()
      setSuccess(true)
      setTimeout(() => navigate(roleHome(role)), 1800)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors du changement de mot de passe.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center" style={{ background: '#F0F4F9' }}>
      <div className="w-full rounded-2xl bg-white p-10 shadow-lg" style={{ maxWidth: 440 }}>
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center justify-center rounded-xl" style={{ width: 44, height: 44, background: '#EFF4FA' }}>
            <KeyRound size={20} style={{ color: '#1A3A5C' }} />
          </div>
          <div>
            <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Changer le mot de passe</h1>
            <p className="text-xs mt-0.5" style={{ color: '#F0A500' }}>Première connexion — changement obligatoire</p>
          </div>
        </div>

        {success ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle size={40} style={{ color: '#1D9E76' }} />
            <p className="font-semibold" style={{ color: '#1D9E76' }}>Mot de passe modifié avec succès</p>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>Redirection vers votre tableau de bord…</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-lg px-3 py-2.5 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>
                {error}
              </div>
            )}

            {[
              { label: 'Mot de passe temporaire', value: currentPw, set: setCurrentPw, show: showCurrent, toggle: () => setShowCurrent(v => !v) },
              { label: 'Nouveau mot de passe', value: newPw, set: setNewPw, show: showNew, toggle: () => setShowNew(v => !v) },
            ].map(({ label, value, set, show, toggle }) => (
              <div key={label}>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>{label}</label>
                <div className="relative">
                  <input
                    type={show ? 'text' : 'password'}
                    value={value}
                    onChange={e => set(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2.5 text-sm pr-9 outline-none transition-all"
                    style={{ borderColor: '#D5E8F5' }}
                    onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                    onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                    placeholder="••••••••"
                  />
                  <button type="button" onClick={toggle} className="absolute right-2.5 top-3 text-gray-400 hover:text-gray-600">
                    {show ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            ))}

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Confirmer le nouveau mot de passe</label>
              <input
                type="password"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                className="w-full border rounded-lg px-3 py-2.5 text-sm outline-none transition-all"
                style={{ borderColor: '#D5E8F5' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                placeholder="••••••••"
              />
            </div>

            <div className="rounded-lg px-3 py-2 text-xs" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
              Le mot de passe doit contenir au moins 8 caractères.
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60 mt-1"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Enregistrement…' : 'Enregistrer le mot de passe'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
