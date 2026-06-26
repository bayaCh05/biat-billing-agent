import { useState, useEffect } from 'react'
import { UserPlus, RefreshCw, Ban, Copy, CheckCircle } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import Card from '../../components/ui/Card'
import Button from '../../components/ui/Button'
import type { AdminUser } from '../../types'
import { listAdminUsers, createAdminUser, updateAdminUser, resetAdminUserPassword } from '../../api/endpoints'

const ROLES = ['Comptable', 'Chef de Projet', 'Direction']
const DEPARTEMENTS = ['DSI', 'Comptabilité', 'Direction Générale', 'MOA', 'Infrastructure', 'Développement']

const ROLE_BADGE: Record<string, { bg: string; color: string }> = {
  'Comptable':      { bg: '#EFF4FA', color: '#1A3A5C' },
  'Chef de Projet': { bg: '#FFF8E8', color: '#B07800' },
  'Direction':      { bg: '#F0EBF9', color: '#5A30A0' },
  'Admin':          { bg: '#FEF0EE', color: '#C0391B' },
}

function fmtDate(iso: string) {
  const d = new Date(iso)
  return d.toLocaleDateString('fr-TN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export default function InscriptionPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [createdResult, setCreatedResult] = useState<{ email: string; temp_password: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')

  const [form, setForm] = useState({ nom: '', prenom: '', email: '', role: 'Comptable', departement: 'DSI' })

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try { setUsers(await listAdminUsers()) } catch { /* ignore */ }
    setLoading(false)
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await createAdminUser(form)
      setCreatedResult({ email: res.email, temp_password: res.temp_password })
      setForm({ nom: '', prenom: '', email: '', role: 'Comptable', departement: 'DSI' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur lors de la création.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleToggleActive(user: AdminUser) {
    try {
      await updateAdminUser(user.id, { is_active: !user.is_active })
      await load()
    } catch { /* ignore */ }
  }

  async function handleReset(user: AdminUser) {
    try {
      const res = await resetAdminUserPassword(user.id)
      alert(`Nouveau mot de passe temporaire pour ${user.email} :\n\n${res.temp_password}\n\nCommuniquez ce mot de passe à l'utilisateur.`)
      await load()
    } catch { /* ignore */ }
  }

  function copyPassword() {
    if (createdResult) {
      navigator.clipboard.writeText(createdResult.temp_password)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const label = 'block text-xs font-medium mb-1'
  const input = 'w-full border rounded-lg px-3 py-2 text-sm outline-none transition-all focus:border-blue-400'

  return (
    <div>
      <PageHeader title="Gestion des utilisateurs" badge={`${users.length} comptes`}>
        <Button icon={<UserPlus size={14} />} onClick={() => { setShowForm(v => !v); setCreatedResult(null) }}>
          {showForm ? 'Annuler' : 'Créer un utilisateur'}
        </Button>
      </PageHeader>

      <div className="p-6 space-y-5">

        {/* Creation form */}
        {showForm && (
          <Card>
            <h3 className="text-sm font-semibold mb-4" style={{ color: '#1A3A5C' }}>Nouveau compte utilisateur</h3>

            {createdResult ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium" style={{ color: '#1D9E76' }}>
                  <CheckCircle size={16} /> Compte créé avec succès
                </div>
                <div className="rounded-xl p-4 border" style={{ background: '#EFF4FA', borderColor: '#D5E8F5' }}>
                  <p className="text-xs text-gray-500 mb-1">Email</p>
                  <p className="font-mono text-sm font-semibold">{createdResult.email}</p>
                  <p className="text-xs text-gray-500 mt-3 mb-1">Mot de passe temporaire</p>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-base font-bold tracking-widest" style={{ color: '#1A3A5C' }}>
                      {createdResult.temp_password}
                    </span>
                    <button onClick={copyPassword} className="text-gray-400 hover:text-gray-600 transition-colors">
                      {copied ? <CheckCircle size={14} style={{ color: '#1D9E76' }} /> : <Copy size={14} />}
                    </button>
                  </div>
                </div>
                <p className="text-xs" style={{ color: '#F0A500' }}>
                  Communiquez ce mot de passe à l'utilisateur. Il devra le changer à sa première connexion.
                </p>
                <Button variant="secondary" onClick={() => setCreatedResult(null)}>Créer un autre</Button>
              </div>
            ) : (
              <form onSubmit={handleCreate} className="grid grid-cols-2 gap-4">
                {error && (
                  <div className="col-span-2 rounded-lg px-3 py-2 text-sm" style={{ background: '#FEF0EE', color: '#C0391B' }}>{error}</div>
                )}
                <div>
                  <label className={label} style={{ color: '#374151' }}>Prénom</label>
                  <input className={input} value={form.prenom} onChange={e => setForm(f => ({ ...f, prenom: e.target.value }))} required placeholder="Karim" />
                </div>
                <div>
                  <label className={label} style={{ color: '#374151' }}>Nom</label>
                  <input className={input} value={form.nom} onChange={e => setForm(f => ({ ...f, nom: e.target.value }))} required placeholder="Bennaceur" />
                </div>
                <div className="col-span-2">
                  <label className={label} style={{ color: '#374151' }}>Adresse email</label>
                  <input type="email" className={input} value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} required placeholder="k.bennaceur@biat.com.tn" />
                </div>
                <div>
                  <label className={label} style={{ color: '#374151' }}>Rôle</label>
                  <select className={input} value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                    {ROLES.map(r => <option key={r}>{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className={label} style={{ color: '#374151' }}>Département</label>
                  <select className={input} value={form.departement} onChange={e => setForm(f => ({ ...f, departement: e.target.value }))}>
                    {DEPARTEMENTS.map(d => <option key={d}>{d}</option>)}
                  </select>
                </div>
                <div className="col-span-2 flex gap-2">
                  <Button type="submit" disabled={submitting} icon={<UserPlus size={14} />}>
                    {submitting ? 'Création…' : 'Créer le compte'}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setShowForm(false)}>Annuler</Button>
                </div>
              </form>
            )}
          </Card>
        )}

        {/* Users table */}
        <Card>
          <h3 className="text-sm font-semibold mb-4" style={{ color: '#1A3A5C' }}>Tous les utilisateurs</h3>
          {loading ? (
            <p className="text-sm text-center py-8" style={{ color: '#5D6D7E' }}>Chargement…</p>
          ) : users.length === 0 ? (
            <p className="text-sm text-center py-8" style={{ color: '#5D6D7E' }}>
              Aucun utilisateur créé. Utilisez le formulaire ci-dessus pour ajouter des comptes.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ borderBottom: '1px solid #E2EBF3' }}>
                    {['Nom', 'Email', 'Rôle', 'Département', 'Statut', 'Créé le', 'Actions'].map(h => (
                      <th key={h} className="text-left pb-3 pr-4 text-xs font-semibold" style={{ color: '#5D6D7E' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => {
                    const badge = ROLE_BADGE[u.role] ?? { bg: '#F0F4F9', color: '#5D6D7E' }
                    return (
                      <tr key={u.id} style={{ borderBottom: '1px solid #F0F4F9' }}>
                        <td className="py-3 pr-4 font-medium" style={{ color: '#1A1A2E' }}>
                          {u.prenom} {u.nom}
                          {u.is_first_login && (
                            <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full font-semibold" style={{ background: '#FFF8E8', color: '#B07800' }}>
                              1ère connexion
                            </span>
                          )}
                        </td>
                        <td className="py-3 pr-4 font-mono text-xs" style={{ color: '#5D6D7E' }}>{u.email}</td>
                        <td className="py-3 pr-4">
                          <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={badge}>{u.role}</span>
                        </td>
                        <td className="py-3 pr-4 text-xs" style={{ color: '#5D6D7E' }}>{u.departement || '—'}</td>
                        <td className="py-3 pr-4">
                          <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={{
                            background: u.is_active ? '#E8F5F0' : '#FEF0EE',
                            color: u.is_active ? '#0D6E52' : '#C0391B',
                          }}>
                            {u.is_active ? 'Actif' : 'Désactivé'}
                          </span>
                        </td>
                        <td className="py-3 pr-4 text-xs" style={{ color: '#5D6D7E' }}>{fmtDate(u.created_at)}</td>
                        <td className="py-3">
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => handleReset(u)}
                              className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors hover:bg-gray-100"
                              style={{ color: '#1A3A5C' }}
                              title="Réinitialiser le mot de passe"
                            >
                              <RefreshCw size={12} /> Réinitialiser
                            </button>
                            <button
                              onClick={() => handleToggleActive(u)}
                              className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors hover:bg-gray-100"
                              style={{ color: u.is_active ? '#C0391B' : '#1D9E76' }}
                              title={u.is_active ? 'Désactiver' : 'Réactiver'}
                            >
                              <Ban size={12} /> {u.is_active ? 'Désactiver' : 'Réactiver'}
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
