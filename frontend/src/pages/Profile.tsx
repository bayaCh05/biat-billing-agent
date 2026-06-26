import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { LogOut, KeyRound, CheckCircle, Eye, EyeOff } from 'lucide-react'

const ROLE_EMAILS: Record<string, string> = {
  'Comptable':      'baya.chaabene@biat.com.tn',
  'Chef de Projet': 'karim.bennaceur@biat.com.tn',
  'Direction':      'direction.it@biat.com.tn',
}

const ROLE_COLOR: Record<string, string> = {
  'Direction':      '#804CD7',
  'Chef de Projet': '#F0A600',
  'Comptable':      '#1A3A5C',
}

const ROLE_BADGE_CLASS: Record<string, string> = {
  'Direction':      'bg-purple-100 text-purple-700',
  'Chef de Projet': 'bg-amber-100 text-amber-700',
  'Comptable':      'bg-blue-100 text-blue-700',
}

export default function Profile() {
  const navigate = useNavigate()
  const { name, initials, role, logout } = useAuth()

  const [currentPw, setCurrentPw]   = useState('')
  const [newPw, setNewPw]           = useState('')
  const [confirmPw, setConfirmPw]   = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew]         = useState(false)
  const [pwSuccess, setPwSuccess]     = useState(false)
  const [pwError, setPwError]         = useState('')

  const avatarBg = ROLE_COLOR[role]     ?? '#1A3A5C'
  const email    = ROLE_EMAILS[role]    ?? 'user@biat.com.tn'
  const badgeCls = ROLE_BADGE_CLASS[role] ?? 'bg-blue-100 text-blue-700'

  function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    setPwError('')
    if (!currentPw)          return setPwError('Veuillez saisir votre mot de passe actuel.')
    if (newPw.length < 8)    return setPwError('Le nouveau mot de passe doit contenir au moins 8 caractères.')
    if (newPw !== confirmPw) return setPwError('Les mots de passe ne correspondent pas.')
    // Client-side only — demo auth has no backend password storage
    setPwSuccess(true)
    setCurrentPw(''); setNewPw(''); setConfirmPw('')
    setTimeout(() => setPwSuccess(false), 4000)
  }

  return (
    <div className="p-6 max-w-xl mx-auto">
      {/* Page heading */}
      <div className="mb-6">
        <h1 className="text-xl font-bold" style={{ color: '#1A3A5C' }}>Mon profil</h1>
        <p className="text-sm text-gray-500 mt-0.5">Informations du compte et paramètres de sécurité</p>
      </div>

      {/* Identity card */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4 flex items-center gap-5">
        <div
          className="flex items-center justify-center rounded-full text-white font-bold text-2xl shrink-0"
          style={{ width: 72, height: 72, background: avatarBg }}
        >
          {initials}
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{name}</h2>
          <span className={`inline-block mt-1 text-xs font-medium px-2.5 py-1 rounded-full ${badgeCls}`}>
            {role}
          </span>
          <p className="text-sm text-gray-500 mt-1.5">{email}</p>
        </div>
      </div>

      {/* Account details */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: '#1A3A5C' }}>Détails du compte</h3>
        <dl className="space-y-2 text-sm">
          {[
            { label: 'Nom complet',   value: name },
            { label: 'Rôle',          value: role },
            { label: 'Email',         value: email },
            { label: 'Organisation',  value: 'BIAT Innovation & Technology' },
          ].map(({ label, value }) => (
            <div key={label} className="flex gap-3">
              <dt className="w-32 shrink-0 text-gray-500">{label}</dt>
              <dd className="text-gray-900 font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Change password */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4">
        <div className="flex items-center gap-2 mb-4">
          <KeyRound size={15} style={{ color: '#1A3A5C' }} />
          <h3 className="text-sm font-semibold" style={{ color: '#1A3A5C' }}>Changer le mot de passe</h3>
        </div>

        {pwSuccess && (
          <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 mb-4">
            <CheckCircle size={14} />
            Mot de passe modifié avec succès.
          </div>
        )}
        {pwError && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-4">
            {pwError}
          </div>
        )}

        <form onSubmit={handleChangePassword} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Mot de passe actuel</label>
            <div className="relative">
              <input
                type={showCurrent ? 'text' : 'password'}
                value={currentPw}
                onChange={e => setCurrentPw(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm pr-9 focus:outline-none focus:ring-2 focus:ring-blue-200"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowCurrent(v => !v)}
                className="absolute right-2.5 top-2.5 text-gray-400 hover:text-gray-600"
              >
                {showCurrent ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Nouveau mot de passe</label>
            <div className="relative">
              <input
                type={showNew ? 'text' : 'password'}
                value={newPw}
                onChange={e => setNewPw(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm pr-9 focus:outline-none focus:ring-2 focus:ring-blue-200"
                placeholder="8 caractères minimum"
              />
              <button
                type="button"
                onClick={() => setShowNew(v => !v)}
                className="absolute right-2.5 top-2.5 text-gray-400 hover:text-gray-600"
              >
                {showNew ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Confirmer le mot de passe</label>
            <input
              type="password"
              value={confirmPw}
              onChange={e => setConfirmPw(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-200"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            className="w-full py-2 rounded-lg text-sm font-semibold text-white mt-1 hover:opacity-90 transition-opacity"
            style={{ background: '#1A3A5C' }}
          >
            Enregistrer
          </button>
        </form>
      </div>

      {/* Logout */}
      <button
        onClick={() => { logout(); navigate('/login') }}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red-200 text-red-600 text-sm font-medium hover:bg-red-50 transition-colors"
      >
        <LogOut size={14} />
        Se déconnecter
      </button>
    </div>
  )
}
