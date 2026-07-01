import { useEffect, useState } from 'react'
import { ShieldAlert, Plus, AlertTriangle, CheckCircle2, Clock, X, Sparkles, Loader2 } from 'lucide-react'
import { listRisks, createRisk, updateRisk, closeRisk, getRiskSummary, suggestMitigation } from '../api/endpoints'
import type { Risk, RiskSummary, NiveauCriticite, StatutRisque } from '../types'

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
  DELAI:        'Délai',
  BUDGET:       'Budget',
  TECHNIQUE:    'Technique',
  RESSOURCE:    'Ressource',
  FOURNISSEUR:  'Fournisseur',
  REGLEMENTAIRE:'Réglementaire',
  AUTRE:        'Autre',
}

const EMPTY_FORM = {
  titre: '',
  description: '',
  type_risque: 'AUTRE',
  probabilite: 'MOYENNE',
  impact: 'MOYEN',
  plan_mitigation: '',
  responsable_id: '',
  date_identification: new Date().toISOString().slice(0, 10),
  date_echeance_mitigation: '',
  feuille_route_id: '',
  projet_id: '',
}

export default function RisksPage() {
  const [risks, setRisks] = useState<Risk[]>([])
  const [summary, setSummary] = useState<RiskSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editRisk, setEditRisk] = useState<Risk | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [saving, setSaving] = useState(false)
  const [filterStatut, setFilterStatut] = useState('')
  const [filterCriticite, setFilterCriticite] = useState('')
  const [suggestingMitigation, setSuggestingMitigation] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [r, s] = await Promise.all([
        listRisks({ statut: filterStatut || undefined, niveau_criticite: filterCriticite || undefined }),
        getRiskSummary(),
      ])
      setRisks(r)
      setSummary(s)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filterStatut, filterCriticite])

  const openCreate = () => {
    setEditRisk(null)
    setForm({ ...EMPTY_FORM })
    setShowModal(true)
  }

  const openEdit = (r: Risk) => {
    setEditRisk(r)
    setForm({
      titre: r.titre,
      description: r.description,
      type_risque: r.type_risque,
      probabilite: r.probabilite,
      impact: r.impact,
      plan_mitigation: r.plan_mitigation,
      responsable_id: r.responsable_id ?? '',
      date_identification: r.date_identification,
      date_echeance_mitigation: r.date_echeance_mitigation ?? '',
      feuille_route_id: r.feuille_route_id ?? '',
      projet_id: r.projet_id ?? '',
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.titre || !form.probabilite || !form.impact) return
    if (!form.feuille_route_id && !form.projet_id) {
      alert('Veuillez renseigner un ID de projet ou de feuille de route.')
      return
    }
    setSaving(true)
    try {
      const payload = {
        titre: form.titre,
        description: form.description,
        type_risque: form.type_risque,
        probabilite: form.probabilite,
        impact: form.impact,
        plan_mitigation: form.plan_mitigation,
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
      load()
    } finally {
      setSaving(false)
    }
  }

  const handleClose = async (id: string) => {
    if (!confirm('Clôturer ce risque ?')) return
    await closeRisk(id)
    load()
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
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

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-4">
          {(['FAIBLE', 'MOYENNE', 'ELEVEE', 'CRITIQUE'] as NiveauCriticite[]).map(c => (
            <div key={c} className="rounded-xl border p-4" style={{ borderColor: CRITICITE_COLOR[c], background: CRITICITE_BG[c] }}>
              <p className="text-xs font-semibold mb-1" style={{ color: CRITICITE_COLOR[c] }}>{c}</p>
              <p className="text-3xl font-bold" style={{ color: CRITICITE_COLOR[c] }}>{summary.by_criticite[c] ?? 0}</p>
              <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>risques actifs</p>
            </div>
          ))}
        </div>
      )}

      {/* Overdue alert */}
      {summary && summary.overdue.length > 0 && (
        <div className="flex items-start gap-3 p-4 rounded-xl border" style={{ background: '#FDEDEC', borderColor: '#C0391B' }}>
          <AlertTriangle size={18} style={{ color: '#C0391B', flexShrink: 0, marginTop: 2 }} />
          <div>
            <p className="text-sm font-semibold" style={{ color: '#C0391B' }}>
              {summary.overdue.length} risque(s) avec échéance dépassée
            </p>
            <ul className="text-xs mt-1 space-y-0.5" style={{ color: '#922B21' }}>
              {summary.overdue.map(o => (
                <li key={o.id}>• {o.titre} — prévu le {o.date_echeance_mitigation}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
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
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>Chargement…</p>
      ) : risks.length === 0 ? (
        <div className="text-center py-16">
          <ShieldAlert size={40} style={{ color: '#C8D8E8', margin: '0 auto 12px' }} />
          <p className="text-sm" style={{ color: '#5D6D7E' }}>Aucun risque enregistré.</p>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: '#E2EBF3' }}>
          <table className="w-full text-sm">
            <thead style={{ background: '#F5F8FC' }}>
              <tr>
                {['Titre', 'Type', 'Probabilité', 'Impact', 'Criticité', 'Statut', 'Échéance', 'Actions'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold" style={{ color: '#5D6D7E' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {risks.map((r, i) => (
                <tr key={r.id} style={{ borderTop: i > 0 ? '1px solid #E2EBF3' : undefined }}>
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
                  <td className="px-4 py-3 text-xs">{r.probabilite}</td>
                  <td className="px-4 py-3 text-xs">{r.impact}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs font-bold px-2 py-1 rounded-full" style={{
                      color: CRITICITE_COLOR[r.niveau_criticite as NiveauCriticite],
                      background: CRITICITE_BG[r.niveau_criticite as NiveauCriticite],
                    }}>
                      {r.niveau_criticite}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{STATUT_LABEL[r.statut as StatutRisque] ?? r.statut}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: r.date_echeance_mitigation && r.date_echeance_mitigation < new Date().toISOString().slice(0,10) ? '#C0391B' : '#5D6D7E' }}>
                    {r.date_echeance_mitigation ?? '—'}
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
                      {r.statut === 'CLOTURE' && (
                        <CheckCircle2 size={14} style={{ color: '#1D9E76' }} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal */}
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
                          titre: form.titre,
                          type_risque: form.type_risque,
                          probabilite: form.probabilite,
                          impact: form.impact,
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
