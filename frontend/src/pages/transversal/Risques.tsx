import { Fragment, useEffect, useState } from 'react'
import {
  ShieldAlert, Plus, CheckCircle2, Clock, X,
  Sparkles, Loader2, ChevronDown, ChevronRight, FolderKanban,
} from 'lucide-react'
import {
  createRisk, updateRisk, closeRisk,
  suggestMitigation,
  getRisksParProjet,
} from '../../api/endpoints'
import type {
  Risk, NiveauCriticite, StatutRisque,
  RisquesProjetGroupe,
} from '../../types'

// ── Shared constants ──────────────────────────────────────────────────────────

const CRITICITE_COLOR: Record<NiveauCriticite, string> = {
  FAIBLE:   '#1D9E76',
  MOYENNE:  '#F0A500',
  ELEVEE:   '#E67E22',
  CRITIQUE: '#C0391B',
}

const CRITICITE_BG: Record<NiveauCriticite, string> = {
  FAIBLE:   '#E6F9F3',
  MOYENNE:  '#FEF9E7',
  ELEVEE:   '#FDF2E9',
  CRITIQUE: '#FDEDEC',
}

const STATUT_LABEL: Record<StatutRisque, string> = {
  IDENTIFIE:       'Identifié',
  EN_SURVEILLANCE: 'En surveillance',
  EN_TRAITEMENT:   'En traitement',
  MAITRISE:        'Maîtrisé',
  SURVENU:         'Survenu',
  CLOTURE:         'Clôturé',
}

const TYPE_LABEL: Record<string, string> = {
  DELAI:         'Délai',
  BUDGET:        'Budget',
  TECHNIQUE:     'Technique',
  RESSOURCE:     'Ressource',
  FOURNISSEUR:   'Fournisseur',
  REGLEMENTAIRE: 'Réglementaire',
  AUTRE:         'Autre',
}

const EMPTY_FORM = {
  titre: '', description: '', type_risque: 'AUTRE',
  probabilite: 'MOYENNE', impact: 'MOYEN', plan_mitigation: '',
  responsable_id: '', date_identification: new Date().toISOString().slice(0, 10),
  date_echeance_mitigation: '', feuille_route_id: '', projet_id: '',
}

const TODAY = new Date().toISOString().slice(0, 10)

/** YYYY-MM-DD → DD/MM/YYYY */
const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function CriticBadge({ c }: { c: string }) {
  const col = CRITICITE_COLOR[c as NiveauCriticite] ?? '#5D6D7E'
  const bg  = CRITICITE_BG[c as NiveauCriticite]   ?? '#F5F8FC'
  return (
    <span className="text-xs font-bold px-2 py-0.5 rounded-full" style={{ color: col, background: bg }}>
      {c}
    </span>
  )
}

function CriticCount({ label, count, c }: { label: string; count: number; c: NiveauCriticite }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full border"
      style={{
        color:       CRITICITE_COLOR[c],
        background:  CRITICITE_BG[c],
        borderColor: CRITICITE_COLOR[c] + '55',
      }}
    >
      <span className="font-bold">{count}</span>
      <span className="opacity-80">{label}</span>
    </span>
  )
}

// ── Risk row ──────────────────────────────────────────────────────────────────

function RiskRow({
  r, openEdit, handleClose,
}: {
  r: Risk
  openEdit: (r: Risk) => void
  handleClose: (id: string) => void
}) {
  const overdue = !!r.date_echeance_mitigation && r.date_echeance_mitigation < TODAY
  return (
    <tr style={{ borderTop: '1px solid #E2EBF3' }}>
      <td className="px-4 py-3 font-medium" style={{ color: '#1A3A5C', maxWidth: 200 }}>
        <div className="flex items-start gap-1.5">
          <span className="line-clamp-2">{r.titre}</span>
          {r.created_by === 'system:ai' && (
            <span className="shrink-0 inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded-full bg-orange-50 text-orange-600 border border-orange-200">
              🤖 IA
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{TYPE_LABEL[r.type_risque] ?? r.type_risque}</td>
      <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{r.probabilite}</td>
      <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{r.impact}</td>
      <td className="px-4 py-3"><CriticBadge c={r.niveau_criticite} /></td>
      <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{STATUT_LABEL[r.statut as StatutRisque] ?? r.statut}</td>
      <td className="px-4 py-3 text-xs" style={{ color: overdue ? '#C0391B' : '#5D6D7E' }}>
        {fmtDate(r.date_echeance_mitigation)}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <button onClick={() => openEdit(r)} className="p-1 rounded hover:bg-gray-100" title="Modifier">
            <Clock size={14} style={{ color: '#1A3A5C' }} />
          </button>
          {r.statut !== 'CLOTURE' && (
            <button onClick={() => handleClose(r.id)} className="p-1 rounded hover:bg-red-50" title="Clôturer">
              <X size={14} style={{ color: '#C0391B' }} />
            </button>
          )}
          {r.statut === 'CLOTURE' && <CheckCircle2 size={14} style={{ color: '#1D9E76' }} />}
        </div>
      </td>
    </tr>
  )
}

const TABLE_COLS = ['Titre', 'Type', 'Probabilité', 'Impact', 'Criticité', 'Statut', 'Échéance', 'Actions']

// ── "Par projet" view ─────────────────────────────────────────────────────────

function VueParProjet({
  filterCriticite,
  filterStatut,
  openEdit,
  handleClose,
  reloadKey,
}: {
  filterCriticite: string
  filterStatut: string
  openEdit: (r: Risk) => void
  handleClose: (id: string) => void
  reloadKey: number
}) {
  const [groupes, setGroupes] = useState<RisquesProjetGroupe[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const load = async () => {
    setLoading(true)
    try {
      const g = await getRisksParProjet()
      setGroupes(g)
      setExpanded(new Set(g.map(x => x.projet_id)))
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { queueMicrotask(load) }, [reloadKey])

  const toggle = (id: string) =>
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })

  // Client-side filtering: apply criticite + statut inside each group
  const filteredGroupes = groupes
    .map(g => ({
      ...g,
      risks: g.risks.filter(r => {
        if (filterCriticite && r.niveau_criticite !== filterCriticite) return false
        if (filterStatut    && r.statut           !== filterStatut)    return false
        return true
      }),
    }))
    .filter(g => g.risks.length > 0)

  if (loading) {
    return <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>Chargement…</p>
  }

  if (filteredGroupes.length === 0) {
    return (
      <div className="text-center py-16">
        <FolderKanban size={40} style={{ color: '#C8D8E8', margin: '0 auto 12px' }} />
        <p className="text-sm font-medium" style={{ color: '#1A3A5C' }}>Aucun risque par projet</p>
        <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
          {filterCriticite || filterStatut
            ? 'Aucun risque ne correspond aux filtres sélectionnés.'
            : 'Les risques doivent être liés à un projet pour apparaître ici.'}
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border overflow-hidden" style={{ borderColor: '#E2EBF3' }}>
      <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead style={{ background: '#F5F8FC' }}>
          <tr>
            {TABLE_COLS.map(h => (
              <th key={h} className="text-left px-4 py-3 text-xs font-semibold" style={{ color: '#5D6D7E' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filteredGroupes.map((groupe, gIdx) => {
            const isOpen = expanded.has(groupe.projet_id)

            return (
              <Fragment key={groupe.projet_id}>
                {/* ── Group header row ── */}
                <tr
                  className="cursor-pointer select-none hover:brightness-95 transition-all"
                  style={{
                    background: '#EEF3FA',
                    borderTop: gIdx > 0 ? '2px solid #C8D8E8' : undefined,
                  }}
                  onClick={() => toggle(groupe.projet_id)}
                >
                  <td colSpan={8} className="px-4 py-2.5">
                    <div className="flex items-center gap-3 flex-wrap">
                      {isOpen
                        ? <ChevronDown  size={14} style={{ color: '#1A3A5C', flexShrink: 0 }} />
                        : <ChevronRight size={14} style={{ color: '#5D6D7E', flexShrink: 0 }} />}
                      <FolderKanban size={14} style={{ color: '#1A3A5C', flexShrink: 0 }} />
                      <span className="font-bold text-sm" style={{ color: '#1A3A5C' }}>
                        {groupe.project_name}
                      </span>
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-medium"
                        style={{ background: '#D5E4F5', color: '#1A3A5C' }}
                      >
                        {groupe.risks.length} risque{groupe.risks.length > 1 ? 's' : ''}
                      </span>
                      <div className="flex items-center gap-1.5 ml-1">
                        {(['CRITIQUE', 'ELEVEE', 'MOYENNE', 'FAIBLE'] as NiveauCriticite[]).map(c => {
                          const n = groupe.risks.filter(r => r.niveau_criticite === c).length
                          return n > 0 ? (
                            <CriticCount
                              key={c}
                              label={c.charAt(0) + c.slice(1).toLowerCase()}
                              count={n}
                              c={c}
                            />
                          ) : null
                        })}
                      </div>
                    </div>
                  </td>
                </tr>

                {/* ── Risk rows ── */}
                {isOpen && groupe.risks.map(r => (
                  <RiskRow key={r.id} r={r} openEdit={openEdit} handleClose={handleClose} />
                ))}
              </Fragment>
            )
          })}
        </tbody>
      </table>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function RisksPage() {
  const [showModal, setShowModal] = useState(false)
  const [editRisk, setEditRisk]   = useState<Risk | null>(null)
  const [form, setForm]           = useState({ ...EMPTY_FORM })
  const [saving, setSaving]       = useState(false)
  const [saveError, setSaveError] = useState(false)
  const [filterStatut, setFilterStatut]       = useState('')
  const [filterCriticite, setFilterCriticite] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const [suggestingMitigation, setSuggestingMitigation] = useState(false)

  const openCreate = () => { setEditRisk(null); setForm({ ...EMPTY_FORM }); setSaveError(false); setShowModal(true) }

  const openEdit = (r: Risk) => {
    setEditRisk(r)
    setForm({
      titre: r.titre, description: r.description, type_risque: r.type_risque,
      probabilite: r.probabilite, impact: r.impact, plan_mitigation: r.plan_mitigation,
      responsable_id: r.responsable_id ?? '', date_identification: r.date_identification,
      date_echeance_mitigation: r.date_echeance_mitigation ?? '',
      feuille_route_id: r.feuille_route_id ?? '', projet_id: r.projet_id ?? '',
    })
    setSaveError(false)
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.titre || !form.probabilite || !form.impact) return
    if (!form.feuille_route_id && !form.projet_id) {
      alert('Veuillez renseigner un ID de projet ou de feuille de route.')
      return
    }
    setSaving(true)
    setSaveError(false)
    try {
      const payload = {
        titre: form.titre, description: form.description, type_risque: form.type_risque,
        probabilite: form.probabilite, impact: form.impact, plan_mitigation: form.plan_mitigation,
        responsable_id: form.responsable_id || null,
        date_identification: form.date_identification,
        date_echeance_mitigation: form.date_echeance_mitigation || null,
        feuille_route_id: form.feuille_route_id || null,
        projet_id: form.projet_id || null,
      }
      if (editRisk) {
        await updateRisk(editRisk.id, payload)
      } else {
        await createRisk(payload)
      }
      setShowModal(false)
      setReloadKey(k => k + 1)
    } catch {
      setSaveError(true)
    } finally {
      setSaving(false)
    }
  }

  const handleClose = async (id: string) => {
    if (!confirm('Clôturer ce risque ?')) return
    await closeRisk(id)
    setReloadKey(k => k + 1)
  }

  return (
    <div className="p-6 space-y-5">
      {/* En-tête */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg" style={{ background: '#E8F0FA' }}>
            <ShieldAlert size={20} style={{ color: '#1A3A5C' }} />
          </div>
          <div>
            <h1 className="text-xl font-bold" style={{ color: '#1A3A5C' }}>Gestion des Risques</h1>
            <p className="text-xs" style={{ color: '#5D6D7E' }}>Matrice probabilité × impact — suivi et mitigation</p>
          </div>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white"
          style={{ background: '#1A3A5C' }}
        >
          <Plus size={14} /> Nouveau risque
        </button>
      </div>

      {/* Filtres */}
      <div className="flex items-center gap-3">
        <select
          value={filterCriticite}
          onChange={e => setFilterCriticite(e.target.value)}
          className="text-sm border rounded-lg px-3 py-2"
          style={{ borderColor: '#C8D8E8', color: '#1A3A5C' }}
        >
          <option value="">Toutes les criticités</option>
          {(['FAIBLE', 'MOYENNE', 'ELEVEE', 'CRITIQUE'] as NiveauCriticite[]).map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select
          value={filterStatut}
          onChange={e => setFilterStatut(e.target.value)}
          className="text-sm border rounded-lg px-3 py-2"
          style={{ borderColor: '#C8D8E8', color: '#1A3A5C' }}
        >
          <option value="">Tous les statuts</option>
          {Object.entries(STATUT_LABEL).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        {(filterCriticite || filterStatut) && (
          <button
            onClick={() => { setFilterCriticite(''); setFilterStatut('') }}
            className="text-xs px-2.5 py-1.5 rounded-lg border hover:bg-gray-50 transition-colors"
            style={{ borderColor: '#C8D8E8', color: '#5D6D7E' }}
          >
            Réinitialiser
          </button>
        )}
      </div>

      <VueParProjet
        filterCriticite={filterCriticite}
        filterStatut={filterStatut}
        openEdit={openEdit}
        handleClose={handleClose}
        reloadKey={reloadKey}
      />

      {/* Modal création / édition */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold" style={{ color: '#1A3A5C' }}>
                {editRisk ? 'Modifier le risque' : 'Nouveau risque'}
              </h2>
              <button onClick={() => setShowModal(false)}><X size={18} /></button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Titre *</label>
                <input
                  className="w-full border rounded-lg px-3 py-2 text-sm"
                  style={{ borderColor: '#C8D8E8' }}
                  value={form.titre}
                  onChange={e => setForm(f => ({ ...f, titre: e.target.value }))}
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Description</label>
                <textarea
                  className="w-full border rounded-lg px-3 py-2 text-sm"
                  style={{ borderColor: '#C8D8E8' }}
                  rows={2}
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Type</label>
                  <select
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    value={form.type_risque}
                    onChange={e => setForm(f => ({ ...f, type_risque: e.target.value }))}
                  >
                    {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Probabilité *</label>
                  <select
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    value={form.probabilite}
                    onChange={e => setForm(f => ({ ...f, probabilite: e.target.value }))}
                  >
                    {['FAIBLE', 'MOYENNE', 'ELEVEE'].map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Impact *</label>
                  <select
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    value={form.impact}
                    onChange={e => setForm(f => ({ ...f, impact: e.target.value }))}
                  >
                    {['FAIBLE', 'MOYEN', 'ELEVE', 'CRITIQUE'].map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Date identification *</label>
                  <input
                    type="date"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    value={form.date_identification}
                    onChange={e => setForm(f => ({ ...f, date_identification: e.target.value }))}
                  />
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-semibold" style={{ color: '#5D6D7E' }}>Plan de mitigation</label>
                  <button
                    type="button"
                    disabled={suggestingMitigation || !form.titre}
                    onClick={async () => {
                      setSuggestingMitigation(true)
                      try {
                        const res = await suggestMitigation({
                          titre: form.titre, type_risque: form.type_risque,
                          probabilite: form.probabilite, impact: form.impact,
                        })
                        setForm(f => ({ ...f, plan_mitigation: res.suggestion }))
                      } catch { /* silent */ } finally {
                        setSuggestingMitigation(false)
                      }
                    }}
                    className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border hover:bg-purple-50 disabled:opacity-40 transition-colors"
                    style={{ borderColor: '#804CD7', color: '#804CD7' }}
                  >
                    {suggestingMitigation ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                    Suggérer un plan IA
                  </button>
                </div>
                <textarea
                  className="w-full border rounded-lg px-3 py-2 text-sm"
                  style={{ borderColor: '#C8D8E8' }}
                  rows={3}
                  value={form.plan_mitigation}
                  onChange={e => setForm(f => ({ ...f, plan_mitigation: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Échéance mitigation</label>
                  <input
                    type="date"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    value={form.date_echeance_mitigation}
                    onChange={e => setForm(f => ({ ...f, date_echeance_mitigation: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Responsable (ID)</label>
                  <input
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    placeholder="user@biat-it.tn"
                    value={form.responsable_id}
                    onChange={e => setForm(f => ({ ...f, responsable_id: e.target.value }))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Projet ID</label>
                  <input
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    placeholder="proj-..."
                    value={form.projet_id}
                    onChange={e => setForm(f => ({ ...f, projet_id: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold mb-1" style={{ color: '#5D6D7E' }}>Feuille de route ID</label>
                  <input
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    style={{ borderColor: '#C8D8E8' }}
                    placeholder="UUID"
                    value={form.feuille_route_id}
                    onChange={e => setForm(f => ({ ...f, feuille_route_id: e.target.value }))}
                  />
                </div>
              </div>
            </div>

            {saveError && (
              <p className="text-sm" style={{ color: '#C0391B' }}>
                ⚠ Échec de l'enregistrement — vérifiez votre connexion et réessayez.
              </p>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 border rounded-lg py-2 text-sm font-semibold"
                style={{ borderColor: '#C8D8E8', color: '#5D6D7E' }}
              >
                Annuler
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 rounded-lg py-2 text-sm font-semibold text-white"
                style={{ background: saving ? '#C8D8E8' : '#1A3A5C' }}
              >
                {saving ? 'Enregistrement…' : (editRisk ? 'Modifier' : 'Créer')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
