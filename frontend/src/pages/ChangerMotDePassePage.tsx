import { useRef, useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { KeyRound, Eye, EyeOff, CheckCircle, Mail } from 'lucide-react'
import { useAuth, roleHome } from '../context/AuthContext'
import { requestOtp, confirmOtp } from '../api/endpoints'
import { getToken } from '../api/client'

type Step = 'request' | 'otp' | 'password' | 'success'

const STEPS: Step[] = ['request', 'otp', 'password', 'success']

// ── helpers ───────────────────────────────────────────────────────────────────

function getEmailFromToken(): string {
  const token = getToken()
  if (!token) return ''
  try {
    const b64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(b64))
    return typeof payload.email === 'string' ? payload.email : ''
  } catch { return '' }
}

function maskEmail(email: string): string {
  if (!email) return ''
  try {
    const [local, domain] = email.split('@')
    if (local.length <= 2) return `${local[0]}***@${domain}`
    return `${local[0]}***${local[local.length - 1]}@${domain}`
  } catch { return email }
}

function pwStrength(pw: string): { score: number; label: string; color: string } {
  let score = 0
  if (pw.length >= 8)            score++
  if (/[A-Z]/.test(pw))         score++
  if (/[0-9]/.test(pw))         score++
  if (/[^A-Za-z0-9]/.test(pw))  score++
  const labels = ['', 'Faible', 'Moyen', 'Fort', 'Très fort']
  const colors = ['', '#C0391B', '#F0A500', '#1D9E76', '#1D9E76']
  return { score, label: labels[score] ?? '', color: colors[score] ?? '' }
}

function fmt(sec: number) {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`
}

// ── component ─────────────────────────────────────────────────────────────────

export default function ChangerMotDePassePage() {
  const navigate  = useNavigate()
  const { role, forcePasswordChange, clearForcePasswordChange, isDemoUser } = useAuth()

  const [step, setStep]             = useState<Step>('request')
  const [maskedEmail, setMaskedEmail] = useState(() => maskEmail(getEmailFromToken()))
  const [skipOtp, setSkipOtp]       = useState(false)

  // OTP step
  const [otp, setOtp]               = useState(['', '', '', '', '', ''])
  const otpRefs = [
    useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null),
    useRef<HTMLInputElement>(null), useRef<HTMLInputElement>(null),
  ]
  const [otpCode, setOtpCode]       = useState('')   // locked-in after step 2
  const sentAt                      = useRef(0)
  const [countdown, setCountdown]   = useState(600)
  const [resendIn, setResendIn]     = useState(60)

  // Password step
  const [newPw, setNewPw]           = useState('')
  const [confirmPw, setConfirmPw]   = useState('')
  const [showPw, setShowPw]         = useState(false)

  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')

  useEffect(() => {
    if (isDemoUser) {
      navigate(roleHome(role), { replace: true })
    }
  }, [isDemoUser, navigate, role])

  // Tick down the OTP countdown while on that step
  useEffect(() => {
    if (step !== 'otp') return
    const id = setInterval(() => {
      const elapsed = Math.floor((Date.now() - sentAt.current) / 1000)
      setCountdown(Math.max(0, 600 - elapsed))
      setResendIn(Math.max(0, 60 - elapsed))
    }, 1000)
    return () => clearInterval(id)
  }, [step])

  // ── Step 1: request OTP ───────────────────────────────────────────────────

  async function handleRequestOtp() {
    setError('')
    setLoading(true)
    try {
      const res = await requestOtp()
      if (res.masked_email) setMaskedEmail(res.masked_email)
      if (res.skip_otp) {
        setSkipOtp(true)
        setStep('password')
      } else {
        setSkipOtp(false)
        sentAt.current = Date.now()
        setCountdown(600)
        setResendIn(60)
        setOtp(['', '', '', '', '', ''])
        setStep('otp')
        setTimeout(() => otpRefs[0].current?.focus(), 80)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors de la demande.')
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    if (resendIn > 0 || loading) return
    setError('')
    setLoading(true)
    try {
      const res = await requestOtp()
      if (res.masked_email) setMaskedEmail(res.masked_email)
      sentAt.current = Date.now()
      setCountdown(600)
      setResendIn(60)
      setOtp(['', '', '', '', '', ''])
      setTimeout(() => otpRefs[0].current?.focus(), 80)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors du renvoi.')
    } finally {
      setLoading(false)
    }
  }

  // ── Step 2: OTP digit handlers ────────────────────────────────────────────

  function handleOtpChange(i: number, val: string) {
    const digit = val.replace(/\D/g, '').slice(-1)
    const next = [...otp]; next[i] = digit; setOtp(next)
    if (digit && i < 5) otpRefs[i + 1].current?.focus()
  }

  function handleOtpKeyDown(i: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !otp[i] && i > 0) otpRefs[i - 1].current?.focus()
  }

  function handleOtpPaste(e: React.ClipboardEvent) {
    e.preventDefault()
    const text = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (text.length === 6) { setOtp(text.split('')); otpRefs[5].current?.focus() }
  }

  function handleOtpNext(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const code = otp.join('')
    if (code.length < 6) return setError('Veuillez entrer le code complet à 6 chiffres.')
    if (countdown <= 0)  return setError('Code expiré. Renvoyez un nouveau code.')
    setOtpCode(code)
    setStep('password')
  }

  // ── Step 3: new password ──────────────────────────────────────────────────

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (newPw.length < 8)    return setError('Le mot de passe doit contenir au moins 8 caractères.')
    if (newPw !== confirmPw) return setError('Les mots de passe ne correspondent pas.')

    setLoading(true)
    try {
      await confirmOtp(skipOtp ? null : otpCode, newPw)
      const wasFirst = forcePasswordChange
      clearForcePasswordChange()
      setStep('success')
      setTimeout(() => navigate(wasFirst ? roleHome(role) : roleHome(role)), 2000)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Code incorrect ou expiré.'
      setError(msg)
      // Send real users back to re-enter OTP; demo users stay on password step
      if (!skipOtp && (msg.toLowerCase().includes('code') || msg.includes('expiré'))) {
        setOtp(['', '', '', '', '', ''])
        setStep('otp')
      }
    } finally {
      setLoading(false)
    }
  }

  // ── render ────────────────────────────────────────────────────────────────

  const stepIdx  = STEPS.indexOf(step)
  const strength = pwStrength(newPw)

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
            <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>
              Changer le mot de passe
            </h1>
            <p className="text-xs mt-0.5" style={{ color: '#F0A500' }}>
              {forcePasswordChange
                ? 'Première connexion — changement obligatoire'
                : 'Sécurisation du compte'}
            </p>
          </div>
        </div>

        {/* Step progress dots (hidden on success) */}
        {step !== 'success' && (
          <div className="flex items-center gap-2 mb-6">
            {(['request', 'otp', 'password'] as Step[]).map((s, i) => (
              <div key={s} className="flex items-center gap-2">
                <div
                  className="flex items-center justify-center rounded-full text-xs font-bold"
                  style={{
                    width: 24, height: 24,
                    background: stepIdx > i ? '#1D9E76' : step === s ? '#1A3A5C' : '#E2EBF3',
                    color: stepIdx > i || step === s ? '#fff' : '#9BAFBF',
                  }}
                >
                  {stepIdx > i ? '✓' : i + 1}
                </div>
                {i < 2 && (
                  <div className="h-0.5 w-8"
                    style={{ background: stepIdx > i ? '#1D9E76' : '#E2EBF3' }} />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Global error banner */}
        {error && (
          <div className="rounded-lg px-3 py-2.5 text-sm mb-4"
            style={{ background: '#FEF0EE', color: '#C0391B' }}>
            {error}
          </div>
        )}

        {/* ── STEP 1: Request OTP ─────────────────────────────────────── */}
        {step === 'request' && (
          <div className="space-y-5">
            <div className="rounded-xl p-5 text-center" style={{ background: '#EFF4FA' }}>
              <div className="flex items-center justify-center rounded-full mx-auto mb-3"
                style={{ width: 48, height: 48, background: '#D5E8F5' }}>
                <Mail size={22} style={{ color: '#1A3A5C' }} />
              </div>
              <p className="text-sm font-semibold mb-1" style={{ color: '#1A1A2E' }}>
                Vérification par email
              </p>
              <p className="text-xs leading-relaxed" style={{ color: '#5D6D7E' }}>
                Un code de vérification à 6 chiffres sera envoyé à{' '}
                {maskedEmail
                  ? <><strong style={{ color: '#1A3A5C' }}>{maskedEmail}</strong></>
                  : 'votre adresse email professionnelle'
                }
              </p>
            </div>

            <button
              onClick={handleRequestOtp}
              disabled={loading}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Envoi du code…' : 'Envoyer le code'}
            </button>
          </div>
        )}

        {/* ── STEP 2: OTP entry ───────────────────────────────────────── */}
        {step === 'otp' && (
          <form onSubmit={handleOtpNext} className="space-y-5">
            <div className="flex flex-col items-center gap-1.5 py-1">
              <p className="text-sm font-semibold text-center" style={{ color: '#1A1A2E' }}>
                Code envoyé par email
              </p>
              {maskedEmail && (
                <p className="text-xs text-center" style={{ color: '#5D6D7E' }}>
                  Envoyé à <strong>{maskedEmail}</strong>
                </p>
              )}
              {countdown > 0 ? (
                <p className="text-xs font-medium tabular-nums"
                  style={{ color: countdown < 60 ? '#C0391B' : '#5D6D7E' }}>
                  Code valide encore {fmt(countdown)}
                </p>
              ) : (
                <p className="text-xs font-medium" style={{ color: '#C0391B' }}>
                  Code expiré — renvoyez un nouveau code
                </p>
              )}
            </div>

            {/* 6-digit OTP boxes */}
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
                  style={{ borderColor: digit ? '#1A3A5C' : '#D5E8F5', color: '#1A3A5C' }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = digit ? '#1A3A5C' : '#D5E8F5')}
                />
              ))}
            </div>

            <button
              type="submit"
              disabled={otp.join('').length < 6 || countdown === 0}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              Suivant →
            </button>

            <div className="flex items-center justify-between text-xs" style={{ color: '#5D6D7E' }}>
              <button type="button" onClick={() => setStep('request')} className="hover:underline">
                ← Retour
              </button>
              <button
                type="button"
                onClick={handleResend}
                disabled={resendIn > 0 || loading}
                className="hover:underline disabled:opacity-40"
                style={{ color: resendIn > 0 ? '#9BAFBF' : '#5BA3C9' }}
              >
                {resendIn > 0 ? `Renvoyer (${resendIn}s)` : 'Renvoyer le code'}
              </button>
            </div>
          </form>
        )}

        {/* ── STEP 3: New password ────────────────────────────────────── */}
        {step === 'password' && (
          <form onSubmit={handleConfirm} className="space-y-4">
            {skipOtp ? (
              <div className="rounded-lg px-3 py-2.5 text-xs flex items-center gap-2"
                style={{ background: '#FFF8E7', color: '#92610A', border: '1px solid #F0A500', borderRadius: 8 }}>
                <span style={{ fontSize: 14 }}>ℹ️</span>
                Compte de démonstration — la vérification par email est désactivée.
              </div>
            ) : (
              <div className="rounded-lg px-3 py-2 text-xs flex items-center gap-2"
                style={{ background: '#E8F5F0', color: '#1D9E76' }}>
                <CheckCircle size={13} />
                Code vérifié — choisissez votre nouveau mot de passe
              </div>
            )}

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>
                Nouveau mot de passe
              </label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  value={newPw}
                  onChange={e => setNewPw(e.target.value)}
                  autoComplete="new-password"
                  autoFocus
                  className="w-full border rounded-lg px-3 py-2.5 text-sm pr-9 outline-none transition-all"
                  style={{ borderColor: '#D5E8F5' }}
                  onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                  onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
                  placeholder="••••••••"
                />
                <button type="button" onClick={() => setShowPw(v => !v)}
                  className="absolute right-2.5 top-3 text-gray-400 hover:text-gray-600">
                  {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>

              {/* Strength bar */}
              {newPw && (
                <div className="mt-2">
                  <div className="flex gap-1 h-1.5 mb-1">
                    {[1, 2, 3, 4].map(n => (
                      <div key={n} className="flex-1 rounded-full transition-colors"
                        style={{ background: n <= strength.score ? strength.color : '#E2EBF3' }} />
                    ))}
                  </div>
                  <p className="text-[10px] font-semibold" style={{ color: strength.color }}>
                    {strength.label}
                  </p>
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>
                Confirmer le mot de passe
              </label>
              <input
                type="password"
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                autoComplete="new-password"
                className="w-full border rounded-lg px-3 py-2.5 text-sm outline-none transition-all"
                style={{ borderColor: confirmPw && confirmPw !== newPw ? '#C0391B' : '#D5E8F5' }}
                onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
                onBlur={e => (e.target.style.borderColor = confirmPw && confirmPw !== newPw ? '#C0391B' : '#D5E8F5')}
                placeholder="••••••••"
              />
              {confirmPw && confirmPw !== newPw && (
                <p className="text-[10px] mt-1" style={{ color: '#C0391B' }}>
                  Les mots de passe ne correspondent pas
                </p>
              )}
            </div>

            {/* Requirements checklist */}
            <div className="rounded-lg px-3 py-2.5 space-y-1" style={{ background: '#EFF4FA' }}>
              {[
                { label: 'Minimum 8 caractères',    ok: newPw.length >= 8 },
                { label: 'Au moins une majuscule',  ok: /[A-Z]/.test(newPw) },
                { label: 'Au moins un chiffre',     ok: /[0-9]/.test(newPw) },
              ].map(r => (
                <div key={r.label}
                  className="flex items-center gap-1.5 text-xs"
                  style={{ color: r.ok ? '#1D9E76' : '#5D6D7E' }}>
                  <span className="text-sm">{r.ok ? '✓' : '·'}</span>
                  {r.label}
                </div>
              ))}
            </div>

            <button
              type="submit"
              disabled={loading || newPw.length < 8 || newPw !== confirmPw}
              className="w-full py-3 rounded-xl text-white text-sm font-semibold transition-all hover:opacity-90 disabled:opacity-60"
              style={{ background: '#1A3A5C' }}
            >
              {loading ? 'Enregistrement…' : 'Confirmer'}
            </button>

            {!skipOtp && (
              <button type="button" onClick={() => { setError(''); setOtp(['', '', '', '', '', '']); setStep('otp') }}
                className="w-full text-xs hover:underline" style={{ color: '#5BA3C9' }}>
                ← Modifier le code OTP
              </button>
            )}
          </form>
        )}

        {/* ── STEP 4: Success ─────────────────────────────────────────── */}
        {step === 'success' && (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <div className="flex items-center justify-center rounded-full"
              style={{ width: 56, height: 56, background: '#E8F5F0' }}>
              <CheckCircle size={28} style={{ color: '#1D9E76' }} />
            </div>
            <p className="font-semibold text-base" style={{ color: '#1D9E76' }}>
              Mot de passe modifié avec succès
            </p>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>
              Redirection vers votre tableau de bord…
            </p>
          </div>
        )}

      </div>
    </div>
  )
}
