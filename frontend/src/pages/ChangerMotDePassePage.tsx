import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { KeyRound, Eye, EyeOff, CheckCircle, Mail } from 'lucide-react'
import { useAuth, roleHome } from '../context/AuthContext'
import { requestOtp, confirmOtp } from '../api/endpoints'

type Step = 'form' | 'otp' | 'success'

export default function ChangerMotDePassePage() {
  const navigate = useNavigate()
  const { role, forcePasswordChange, clearForcePasswordChange } = useAuth()

  const [step, setStep] = useState<Step>('form')

  // Form values (step 1)
  const [currentPw, setCurrentPw]     = useState('')
  const [newPw, setNewPw]             = useState('')
  const [confirmPw, setConfirmPw]     = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew]         = useState(false)

  // OTP values (step 2)
  const [otp, setOtp] = useState(['', '', '', '', '', ''])
  const otpRefs = [
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null),
  ]

  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  // Step 1: validate + request OTP
  async function handleRequestOtp(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (newPw.length < 8)     return setError('Le nouveau mot de passe doit contenir au moins 8 caractères.')
    if (newPw !== confirmPw)  return setError('Les mots de passe ne correspondent pas.')

    setLoading(true)
    try {
      await requestOtp(newPw, currentPw || undefined)
      setStep('otp')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors de la demande.')
    } finally {
      setLoading(false)
    }
  }

  // OTP digit input handler
  function handleOtpChange(i: number, val: string) {
    const digit = val.replace(/\D/g, '').slice(-1)
    const next = [...otp]
    next[i] = digit
    setOtp(next)
    if (digit && i < 5) otpRefs[i + 1].current?.focus()
  }

  function handleOtpKeyDown(i: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !otp[i] && i > 0) {
      otpRefs[i - 1].current?.focus()
    }
  }

  function handleOtpPaste(e: React.ClipboardEvent) {
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (text.length === 6) {
      setOtp(text.split(''))
      otpRefs[5].current?.focus()
    }
  }

  // Step 2: submit OTP
  async function handleConfirmOtp(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const code = otp.join('')
    if (code.length < 6) return setError('Veuillez entrer le code complet à 6 chiffres.')

    setLoading(true)
    try {
      await confirmOtp(code, newPw, currentPw || undefined)
      clearForcePasswordChange()
      setStep('success')
      setTimeout(() => navigate(roleHome(role)), 1800)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Code incorrect ou expiré.')
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    setError('')
    setOtp(['', '', '', '', '', ''])
    try {
      await requestOtp(newPw, currentPw || undefined)
      otpRefs[0].current?.focus()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors du renvoi.')
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center" style={{ background: '#F0F4F9' }}>
      <div className="w-full rounded-2xl bg-white p-10 shadow-lg" style={{ maxWidth: 440 }}>

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center justify-center rounded-xl"
            style={{ width: 44, height: 44, background: '#EFF4FA' }}>
            <KeyRound size={20} style={{ color: '#1A3A5C' }} />
          </div>
          <div>
            <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Changer le mot de passe</h1>
            <p className="text-xs mt-0.5" style={{ color: '#F0A500' }}>
              {forcePasswordChange ? 'Première connexion — changement obligatoire' : 'Sécurisation du compte'}
            </p>
          </div>
        </div>

        {/* Step indicators */}
        <div className="flex items-center gap-2 mb-6">
          {(['form', 'otp', 'success'] as Step[]).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div className="flex items-center justify-center rounded-full text-xs font-bold"
                style={{
                  width: 24, height: 24,
                  background: step === s ? '#1A3A5C' : (
                    ['form', 'otp', 'success'].indexOf(step) > i ? '#1D9E76' : '#E2EBF3'
                  ),
                  color: step === s || ['form', 'otp', 'success'].indexOf(step) > i ? '#fff' : '#9BAFBF',
                }}>
                {['form', 'otp', 'success'].indexOf(step) > i ? '✓' : i + 1}
              </div>
              {i < 2 && <div className="flex-1 h-0.5 w-8"
                style={{ background: ['form', 'otp', 'success'].indexOf(step) > i ? '#1D9E76' : '#E2EBF3' }} />}
            </div>
          ))}
        </div>

        {/* ── STEP 1: Password form ── */}
        {step === 'form' && (
          <form onSubmit={handleRequestOtp} className="space-y-4">
            {error && (
              <div className="rounded-lg px-3 py-2.5 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>
                {error}
              </div>
            )}

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>
                Mot de passe temporaire
              </label>
              <div className="relative">
                <input
                  type={showCurrent ? 'text' : 'password'}
                  value={currentPw}
                  onChange={e => setCurrentPw(e.target.value)}
                  autoComplete="current-password"
                  className="w-full border rounded-lg px-3 py-2.5 text-sm pr-9 outline-none transition-all"
                  style={{ borderColor: '#D5E8F5' }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                  placeholder="••••••••"
                />
                <button type="button" onClick={() => setShowCurrent(v => !v)}
                  className="absolute right-2.5 top-3 text-gray-400 hover:text-gray-600">
                  {showCurrent ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>
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
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>
                Confirmer le nouveau mot de passe
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
              Minimum 8 caractères. Un code de vérification sera envoyé à votre email.
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Envoi du code…' : 'Envoyer le code de vérification'}
            </button>
          </form>
        )}

        {/* ── STEP 2: OTP input ── */}
        {step === 'otp' && (
          <form onSubmit={handleConfirmOtp} className="space-y-5">
            <div className="flex flex-col items-center gap-2 py-2">
              <div className="flex items-center justify-center rounded-full"
                style={{ width: 48, height: 48, background: '#EFF4FA' }}>
                <Mail size={22} style={{ color: '#1A3A5C' }} />
              </div>
              <p className="text-sm font-semibold text-center" style={{ color: '#1A1A2E' }}>
                Code envoyé par email
              </p>
              <p className="text-xs text-center" style={{ color: '#5D6D7E' }}>
                Saisissez le code à 6 chiffres envoyé à votre adresse email.
                <br />Valable 10 minutes.
              </p>
            </div>

            {error && (
              <div className="rounded-lg px-3 py-2.5 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>
                {error}
              </div>
            )}

            {/* 6-digit OTP input */}
            <div className="flex justify-center gap-3" onPaste={handleOtpPaste}>
              {otp.map((digit, i) => (
                <input
                  key={i}
                  ref={otpRefs[i]}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={e => handleOtpChange(i, e.target.value)}
                  onKeyDown={e => handleOtpKeyDown(i, e)}
                  className="w-12 h-14 text-center text-2xl font-bold rounded-xl border-2 outline-none transition-all"
                  style={{
                    borderColor: digit ? '#1A3A5C' : '#D5E8F5',
                    color: '#1A3A5C',
                  }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = digit ? '#1A3A5C' : '#D5E8F5')}
                />
              ))}
            </div>

            <button
              type="submit"
              disabled={loading || otp.join('').length < 6}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Vérification…' : 'Valider le code'}
            </button>

            <div className="flex items-center justify-between text-xs" style={{ color: '#5D6D7E' }}>
              <button type="button" onClick={() => setStep('form')} className="hover:underline">
                ← Modifier le mot de passe
              </button>
              <button type="button" onClick={handleResend} className="hover:underline" style={{ color: '#5BA3C9' }}>
                Renvoyer le code
              </button>
            </div>
          </form>
        )}

        {/* ── STEP 3: Success ── */}
        {step === 'success' && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle size={44} style={{ color: '#1D9E76' }} />
            <p className="font-semibold" style={{ color: '#1D9E76' }}>Mot de passe modifié avec succès</p>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>Redirection vers votre tableau de bord…</p>
          </div>
        )}
      </div>
    </div>
  )
}
