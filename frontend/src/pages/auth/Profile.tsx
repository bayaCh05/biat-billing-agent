import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { LogOut, CheckCircle, Monitor, RefreshCw, Camera, AlertCircle } from 'lucide-react'
import { getSessions, revokeSession, logoutApi, updateAvatar, type ActiveSession } from '../../api/endpoints'

const ROLE_COLOR: Record<string, string> = {
  'Direction':      '#804CD7',
  'Chef de Projet': '#F0A600',
  'Comptable':      '#1A3A5C',
  'Admin':          '#C0391B',
}

const ROLE_BADGE: Record<string, string> = {
  'Direction':      'bg-purple-100 text-purple-700',
  'Chef de Projet': 'bg-amber-100 text-amber-700',
  'Comptable':      'bg-blue-100 text-blue-700',
  'Admin':          'bg-red-100 text-red-700',
}

const ROLE_EMAILS: Record<string, string> = {
  'Comptable':      'baya.chaabene@biat.com.tn',
  'Chef de Projet': 'karim.bennaceur@biat.com.tn',
  'Direction':      'direction.it@biat.com.tn',
}

const MAX_FILE_MB = 5

/** Redimensionne une image via canvas (max 300×300, JPEG 0.82). */
function resizeImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      const MAX = 300
      let { width: w, height: h } = img
      if (w > MAX || h > MAX) {
        if (w > h) { h = Math.round(h * MAX / w); w = MAX }
        else        { w = Math.round(w * MAX / h); h = MAX }
      }
      const canvas = document.createElement('canvas')
      canvas.width = w
      canvas.height = h
      canvas.getContext('2d')!.drawImage(img, 0, 0, w, h)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', 0.82))
    }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Impossible de lire l\'image.')) }
    img.src = url
  })
}

export default function Profile() {
  const navigate = useNavigate()
  const { name, initials, role, avatar, setAvatar, logout, isDemoUser } = useAuth()

  const avatarBg  = ROLE_COLOR[role] ?? '#1A3A5C'
  const badgeCls  = ROLE_BADGE[role]  ?? 'bg-blue-100 text-blue-700'
  const email     = ROLE_EMAILS[role] ?? 'user@biat.com.tn'

  /* ── Avatar upload ──────────────────────────────────────────────────────── */
  const fileRef       = useRef<HTMLInputElement>(null)
  const [hoverAvatar, setHoverAvatar]     = useState(false)
  const [uploading, setUploading]         = useState(false)
  const [avatarMsg, setAvatarMsg]         = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  function flashMsg(type: 'ok' | 'err', text: string) {
    setAvatarMsg({ type, text })
    setTimeout(() => setAvatarMsg(null), 4000)
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!e.target) return
    // Reset so the same file can be re-selected
    e.target.value = ''

    if (!file) return
    if (!file.type.startsWith('image/')) {
      return flashMsg('err', 'Fichier non reconnu. Veuillez sélectionner une image.')
    }
    if (file.size > MAX_FILE_MB * 1024 * 1024) {
      return flashMsg('err', `Fichier trop grand (max ${MAX_FILE_MB} Mo).`)
    }

    if (isDemoUser) {
      return flashMsg('err', 'Photo non disponible pour les comptes de démonstration.')
    }

    setUploading(true)
    try {
      const b64 = await resizeImage(file)
      // Optimistic update
      setAvatar(b64)
      await updateAvatar(b64)
      flashMsg('ok', 'Photo de profil mise à jour.')
    } catch {
      // Roll back optimistic update on error
      setAvatar(avatar)
      flashMsg('err', 'Erreur lors de l\'envoi. Réessayez.')
    } finally {
      setUploading(false)
    }
  }

  /* ── Sessions ───────────────────────────────────────────────────────────── */
  const [sessions, setSessions]               = useState<ActiveSession[]>([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [revokingJti, setRevokingJti]         = useState<string | null>(null)

  useEffect(() => {
    setLoadingSessions(true)
    getSessions()
      .then(d => setSessions(d.sessions))
      .catch(() => {})
      .finally(() => setLoadingSessions(false))
  }, [])

  const handleRevokeSession = async (jti: string) => {
    setRevokingJti(jti)
    try {
      await revokeSession(jti)
      setSessions(prev => prev.filter(s => s.jti !== jti))
    } catch { /* ignore */ }
    finally { setRevokingJti(null) }
  }

  const handleLogout = async () => {
    try { await logoutApi() } catch { /* ignore */ }
    logout()
    navigate('/login')
  }

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <div className="p-6 max-w-xl mx-auto">

      {/* En-tête */}
      <div className="mb-6">
        <h1 className="text-xl font-bold" style={{ color: '#1A3A5C' }}>Mon profil</h1>
        <p className="text-sm text-gray-500 mt-0.5">Informations du compte et paramètres de sécurité</p>
      </div>

      {/* Carte identité */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4 flex items-center gap-5">

        {/* Avatar cliquable */}
        <div className="relative shrink-0 group">
          <button
            type="button"
            className="relative block rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
            style={{ '--tw-ring-color': '#5BA3C9' } as React.CSSProperties}
            onClick={() => !uploading && fileRef.current?.click()}
            onMouseEnter={() => setHoverAvatar(true)}
            onMouseLeave={() => setHoverAvatar(false)}
            title="Changer la photo de profil"
            disabled={uploading}
          >
            {/* Image ou initiales */}
            {avatar ? (
              <img
                src={avatar}
                alt="Photo de profil"
                className="rounded-full object-cover"
                style={{ width: 72, height: 72 }}
              />
            ) : (
              <div
                className="flex items-center justify-center rounded-full text-white font-bold text-2xl"
                style={{ width: 72, height: 72, background: avatarBg }}
              >
                {uploading ? (
                  <span className="inline-block w-5 h-5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                ) : initials}
              </div>
            )}

            {/* Overlay "Changer" au survol */}
            <div
              className="absolute inset-0 rounded-full flex flex-col items-center justify-center transition-opacity duration-200"
              style={{
                background: 'rgba(0,0,0,0.45)',
                opacity: hoverAvatar && !uploading ? 1 : 0,
              }}
            >
              <Camera size={18} color="white" />
              <span style={{ color: 'white', fontSize: 9, fontWeight: 700, marginTop: 2, letterSpacing: '0.03em' }}>
                CHANGER
              </span>
            </div>

            {/* Spinner overlay quand upload en cours */}
            {uploading && avatar && (
              <div
                className="absolute inset-0 rounded-full flex items-center justify-center"
                style={{ background: 'rgba(0,0,0,0.35)' }}
              >
                <span className="inline-block w-5 h-5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              </div>
            )}
          </button>

          {/* Input file caché */}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        <div className="flex-1 min-w-0">
          <h2 className="text-lg font-semibold text-gray-900">{name}</h2>
          <span className={`inline-block mt-1 text-xs font-medium px-2.5 py-1 rounded-full ${badgeCls}`}>
            {role}
          </span>
          <p className="text-sm text-gray-500 mt-1.5">{email}</p>

          {/* Feedback upload */}
          {avatarMsg && (
            <div
              className="flex items-center gap-1.5 mt-2 text-xs px-2.5 py-1.5 rounded-lg"
              style={{
                background: avatarMsg.type === 'ok' ? '#ECFDF5' : '#FEF2F2',
                color:      avatarMsg.type === 'ok' ? '#065F46' : '#991B1B',
                border:     `1px solid ${avatarMsg.type === 'ok' ? '#A7F3D0' : '#FECACA'}`,
              }}
            >
              {avatarMsg.type === 'ok'
                ? <CheckCircle size={12} />
                : <AlertCircle size={12} />}
              {avatarMsg.text}
            </div>
          )}
          <p className="text-[11px] text-gray-400 mt-1">
            {isDemoUser
              ? 'Photo de profil non disponible pour les comptes de démonstration.'
              : `Cliquez sur la photo pour la modifier · max ${MAX_FILE_MB} Mo · redimensionné à 300×300`}
          </p>
        </div>
      </div>

      {/* Détails du compte */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: '#1A3A5C' }}>Détails du compte</h3>
        <dl className="space-y-2 text-sm">
          {[
            { label: 'Nom complet',  value: name },
            { label: 'Rôle',         value: role },
            { label: 'Email',        value: email },
            { label: 'Organisation', value: 'BIAT Innovation & Technology' },
          ].map(({ label, value }) => (
            <div key={label} className="flex gap-3">
              <dt className="w-32 shrink-0 text-gray-500">{label}</dt>
              <dd className="text-gray-900 font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {/* Sessions actives */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Monitor size={16} className="text-blue-500" />
            <span className="text-sm font-semibold text-gray-800">Sessions actives</span>
          </div>
          <button
            onClick={() => {
              setLoadingSessions(true)
              getSessions().then(d => setSessions(d.sessions)).catch(() => {}).finally(() => setLoadingSessions(false))
            }}
            disabled={loadingSessions}
            className="text-xs text-blue-600 hover:underline flex items-center gap-1"
          >
            <RefreshCw size={10} className={loadingSessions ? 'animate-spin' : ''} />
            Actualiser
          </button>
        </div>
        {sessions.length === 0 && !loadingSessions && (
          <p className="text-xs text-gray-500">
            Aucune session active trouvée (fonctionnalité disponible avec comptes DB uniquement).
          </p>
        )}
        <div className="space-y-2">
          {sessions.map(s => (
            <div
              key={s.jti}
              className="flex items-center justify-between p-2.5 rounded-lg text-xs"
              style={{ background: s.is_current ? '#E8F5F0' : '#F8FAFC' }}
            >
              <div>
                <span className="font-mono text-gray-700">{s.jti}…</span>
                {s.is_current && <span className="ml-2 text-green-700 font-semibold">● Session actuelle</span>}
                <p className="text-gray-400 mt-0.5">
                  {s.ip_address ?? 'IP inconnue'} · expire {new Date(s.expires_at).toLocaleString('fr-TN')}
                </p>
              </div>
              {!s.is_current && (
                <button
                  onClick={() => handleRevokeSession(s.jti)}
                  disabled={revokingJti === s.jti}
                  className="px-2 py-1 rounded-lg text-red-600 border border-red-200 hover:bg-red-50 disabled:opacity-50"
                >
                  {revokingJti === s.jti ? '…' : 'Déconnecter'}
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Déconnexion */}
      <button
        onClick={handleLogout}
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red-200 text-red-600 text-sm font-medium hover:bg-red-50 transition-colors"
      >
        <LogOut size={14} />
        Se déconnecter
      </button>
    </div>
  )
}
