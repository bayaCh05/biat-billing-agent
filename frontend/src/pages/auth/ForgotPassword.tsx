import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Mail, ArrowLeft, CheckCircle } from 'lucide-react'
import { forgotPassword } from '../../api/endpoints'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!email.trim()) return setError('Veuillez saisir votre adresse email.')
    setLoading(true)
    try {
      await forgotPassword(email.trim())
      setSent(true)
    } catch {
      // Show the generic message regardless — security: don't reveal email existence
      setSent(true)
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

        {sent ? (
          <div className="flex flex-col items-center gap-4 py-4 text-center">
            <div className="flex items-center justify-center rounded-full"
              style={{ width: 56, height: 56, background: '#E8F5F0' }}>
              <CheckCircle size={28} style={{ color: '#1D9E76' }} />
            </div>
            <h2 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Email envoyé</h2>
            <p className="text-sm leading-relaxed" style={{ color: '#5D6D7E' }}>
              Si l'adresse <strong>{email}</strong> est associée à un compte actif,
              un lien de réinitialisation a été envoyé.<br /><br />
              Vérifiez votre boîte de réception (et vos spams).
              Le lien expire dans <strong>1 heure</strong>.
            </p>
            <Link
              to="/login"
              className="mt-2 text-sm font-semibold hover:underline flex items-center gap-1.5"
              style={{ color: '#1A3A5C' }}
            >
              <ArrowLeft size={14} /> Retour à la connexion
            </Link>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="flex items-center justify-center rounded-xl"
                style={{ width: 44, height: 44, background: '#EFF4FA' }}>
                <Mail size={20} style={{ color: '#1A3A5C' }} />
              </div>
              <div>
                <h2 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Mot de passe oublié</h2>
                <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                  Recevez un lien de réinitialisation par email
                </p>
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
                  Adresse email
                </label>
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2.5 text-sm outline-none transition-all"
                  style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                  placeholder="vous@biat-it.tn"
                />
              </div>

              <div className="rounded-lg px-3 py-2 text-xs" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
                Un lien sécurisé valable 1 heure sera envoyé à cette adresse.
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
                style={{ background: '#1A3A5C' }}
              >
                {loading ? 'Envoi…' : 'Envoyer le lien'}
              </button>
            </form>

            <div className="mt-5 text-center">
              <Link
                to="/login"
                className="text-xs hover:underline flex items-center justify-center gap-1"
                style={{ color: '#5BA3C9' }}
              >
                <ArrowLeft size={12} /> Retour à la connexion
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
