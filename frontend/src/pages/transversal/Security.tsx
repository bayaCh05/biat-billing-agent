import { useState, useEffect } from 'react'
import { ShieldCheck, RefreshCw, Lock, Unlock, AlertTriangle, CheckCircle } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import Card from '../../components/ui/Card'
import {
  getSecuritySummary, verifyAuditIntegrity, unlockAccount,
  type SecuritySummary, type IntegrityResult
} from '../../api/endpoints'

function StatCard({ label, value, color, icon }: { label: string; value: string | number; color?: string; icon?: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs text-gray-500">{label}</p>
        {icon}
      </div>
      <p className="text-2xl font-bold" style={{ color: color ?? '#1A1A2E' }}>
        {value}
      </p>
    </div>
  )
}

export default function SecurityPage() {
  const [summary, setSummary] = useState<SecuritySummary | null>(null)
  const [integrity, setIntegrity] = useState<IntegrityResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [checkingIntegrity, setCheckingIntegrity] = useState(false)
  const [unlocking, setUnlocking] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const s = await getSecuritySummary()
      setSummary(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }

  const runIntegrityCheck = async () => {
    setCheckingIntegrity(true)
    try {
      const result = await verifyAuditIntegrity()
      setIntegrity(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur lors de la vérification')
    } finally {
      setCheckingIntegrity(false)
    }
  }

  const handleUnlock = async (userId: string) => {
    setUnlocking(userId)
    try {
      await unlockAccount(userId)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur lors du déverrouillage')
    } finally {
      setUnlocking(null)
    }
  }

  useEffect(() => { queueMicrotask(load) }, [])

  const integrityScore = integrity?.integrity_score ?? summary?.last_integrity_score
  const scoreColor = integrityScore == null ? '#5D6D7E'
    : integrityScore >= 99 ? '#1D9E76'
    : integrityScore >= 90 ? '#F0A500'
    : '#C0391B'

  return (
    <div>
      <PageHeader title="🔒 Sécurité" badge="Admin">
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 hover:bg-gray-50 text-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Actualiser
        </button>
      </PageHeader>

      <div className="p-6 flex flex-col gap-5">
        {error && !summary && (
          <div className="px-4 py-3 rounded-xl text-sm text-amber-700 bg-amber-50 flex items-center gap-2">
            <AlertTriangle size={14} />
            Données en cours de chargement — réessayez dans un instant
          </div>
        )}

        {/* KPI overview */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard label="Connexions aujourd'hui" value={summary?.total_logins_today ?? 0} color="#2E86C1" />
          <StatCard
            label="Échecs de connexion"
            value={summary?.failed_logins_today ?? 0}
            color={summary && summary.failed_logins_today > 10 ? '#C0391B' : '#1A1A2E'}
            icon={summary && summary.failed_logins_today > 10 ? <AlertTriangle size={14} className="text-red-500" /> : undefined}
          />
          <StatCard label="Comptes verrouillés" value={summary?.locked_accounts_count ?? 0} color="#F0A500" />
          <StatCard label="Sessions actives" value={summary?.active_sessions_count ?? 0} color="#804CD7" />
        </div>

        <div className="grid grid-cols-2 gap-5">
          {/* Audit integrity */}
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
              <ShieldCheck size={16} className="text-green-500" />
              Intégrité des journaux d'audit
            </h3>

            {integrityScore != null && (
              <div className="flex items-center gap-3 mb-3 p-3 rounded-lg" style={{ background: '#F0F4F9' }}>
                <span className="text-3xl font-bold" style={{ color: scoreColor }}>
                  {integrityScore.toFixed(1)}%
                </span>
                <div>
                  {integrityScore >= 99
                    ? <p className="text-xs text-green-700 font-medium">✅ Aucune altération détectée</p>
                    : <p className="text-xs text-red-700 font-medium">⚠️ {integrity?.tampered_count ?? '?'} entrée(s) potentiellement altérée(s)</p>
                  }
                  {(integrity?.checked_at ?? summary?.last_integrity_check) && (
                    <p className="text-[10px] text-gray-500">
                      Dernière vérification: {new Date(integrity?.checked_at ?? summary?.last_integrity_check ?? '').toLocaleString('fr-TN')}
                    </p>
                  )}
                </div>
              </div>
            )}

            {/* Pre-HMAC entries — not suspicious */}
            {integrity != null && integrity.null_hash_count > 0 && (
              <div className="mb-2 p-2 rounded-lg bg-yellow-50 border border-yellow-200">
                <p className="text-xs font-semibold text-yellow-700 flex items-center gap-1">
                  🟡 Entrées pré-HMAC (non suspectes) : {integrity.null_hash_count}
                </p>
                <p className="text-[10px] text-yellow-600 mt-0.5">
                  Créées avant l'activation de la vérification — hashes recalculés automatiquement.
                </p>
              </div>
            )}

            {/* Rebaselined entries — known secret-rotation exception, not suspicious */}
            {integrity != null && integrity.rebaselined_count > 0 && (
              <div className="mb-2 p-2 rounded-lg bg-blue-50 border border-blue-200">
                <p className="text-xs font-semibold text-blue-700 flex items-center gap-1">
                  🔵 Entrées rebaselined (rotation de secret, non suspectes) : {integrity.rebaselined_count}
                </p>
                <p className="text-[10px] text-blue-600 mt-0.5">
                  row_hash d'origine devenu non-vérifiable suite à la rotation du 2026-07-10 —
                  voir docs/audit_hmac_incident.md. Hash d'origine conservé, jamais écrasé.
                </p>
              </div>
            )}

            {/* Genuinely tampered entries */}
            {integrity?.tampered_entries && integrity.tampered_entries.length > 0 && (
              <div className="mb-2 p-2 rounded-lg bg-red-50 border border-red-200">
                <p className="text-xs font-semibold text-red-700 flex items-center gap-1 mb-1">
                  🔴 Entrées potentiellement altérées : {integrity.tampered_count}
                </p>
                {integrity.tampered_entries.map(e => (
                  <p key={e.id} className="text-[10px] text-red-600">
                    {e.action} — {new Date(e.created_at).toLocaleDateString('fr-TN')}
                  </p>
                ))}
              </div>
            )}

            {/* All clear after check */}
            {integrity != null && integrity.null_hash_count === 0 && integrity.rebaselined_count === 0 && integrity.tampered_count === 0 && (
              <div className="mb-2 p-2 rounded-lg bg-green-50 border border-green-200">
                <p className="text-xs text-green-700 font-medium">
                  ✅ {integrity.total_checked} entrées vérifiées — aucune anomalie.
                </p>
              </div>
            )}

            <button
              onClick={runIntegrityCheck}
              disabled={checkingIntegrity}
              className="flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-lg text-white disabled:opacity-50 w-full justify-center"
              style={{ background: '#1A3A5C' }}
            >
              {checkingIntegrity ? <RefreshCw size={12} className="animate-spin" /> : <ShieldCheck size={12} />}
              {checkingIntegrity ? 'Vérification en cours…' : 'Vérifier l\'intégrité maintenant'}
            </button>
          </Card>

          {/* File & access stats */}
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
              <AlertTriangle size={16} className="text-orange-500" />
              Activité suspecte aujourd'hui
            </h3>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Fichiers rejetés</span>
                <span className="font-semibold" style={{ color: summary && summary.rejected_files_today > 0 ? '#C0391B' : '#1D9E76' }}>
                  {summary?.rejected_files_today ?? '—'}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Fichiers uploadés</span>
                <span className="font-semibold">{summary?.uploads_today ?? '—'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Accès non autorisés (403)</span>
                <span className="font-semibold" style={{ color: summary && summary.unauthorized_access_attempts_today > 0 ? '#C0391B' : '#1D9E76' }}>
                  {summary?.unauthorized_access_attempts_today ?? '—'}
                </span>
              </div>
            </div>

            {summary && summary.accounts_with_recent_failures.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-semibold text-gray-700 mb-2">Comptes avec échecs récents:</p>
                {summary.accounts_with_recent_failures.map(a => (
                  <div key={a.email} className="flex items-center justify-between py-1 text-xs">
                    <span className="text-gray-700 truncate">{a.email}</span>
                    <span className="shrink-0 font-semibold text-orange-600">{a.failed_attempts} tentatives</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Locked accounts */}
        {summary && summary.locked_accounts.length > 0 && (
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
              <Lock size={16} className="text-red-500" />
              Comptes verrouillés ({summary.locked_accounts.length})
            </h3>
            <div className="space-y-2">
              {summary.locked_accounts.map(acc => (
                <div key={acc.id} className="flex items-center justify-between p-3 rounded-lg" style={{ background: '#FDECEA' }}>
                  <div>
                    <p className="text-sm font-semibold text-gray-800">{acc.email}</p>
                    <p className="text-xs text-gray-500">
                      {acc.failed_attempts} tentatives · jusqu'au {acc.locked_until ? new Date(acc.locked_until).toLocaleString('fr-TN') : '—'}
                    </p>
                  </div>
                  <button
                    onClick={() => handleUnlock(acc.id)}
                    disabled={unlocking === acc.id}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg disabled:opacity-50"
                    style={{ background: '#E8F5F0', color: '#1D9E76' }}
                  >
                    {unlocking === acc.id ? <RefreshCw size={11} className="animate-spin" /> : <Unlock size={11} />}
                    Déverrouiller
                  </button>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Security info */}
        <div className="p-3 rounded-lg text-xs grid grid-cols-1 sm:grid-cols-3 gap-3" style={{ background: '#F0F4F9' }}>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>Mots de passe hachés bcrypt</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>JWT HS256 + refresh tokens</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>Audit HMAC-SHA256</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>Verrouillage après 5 échecs</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>Validation MIME fichiers</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle size={13} className="text-green-500 shrink-0" />
            <span>Tokens en mémoire (pas localStorage)</span>
          </div>
        </div>
      </div>
    </div>
  )
}
