import { useState, useEffect, useCallback } from 'react'
import { Plus, X, AlertTriangle, CheckCircle, Clock, ChevronRight } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { useAuth } from '../context/AuthContext'
import type { RoadmapItemWithRisks, Risk, NiveauCriticite } from '../types'
import type { RoadmapItem } from '../types'
import {
  listRoadmapWithRisks,
  createRoadmapItem,
  updateRoadmapItem,
  deleteRoadmapItem,
  listProjects,
  getRisksForRoadmap,
  scanItemRisk,
} from '../api/endpoints'
import type { Project } from '../types'

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUT_MAP: Record<string, { label: string; bg: string; color: string }> = {
  PLANIFIE: { label: 'Planifié',  bg: '#EFF4FA', color: '#1A3A5C' },
  EN_COURS: { label: 'En cours',  bg: '#FFF8E8', color: '#B07800' },
  TERMINE:  { label: 'Terminé',   bg: '#E8F5F0', color: '#0D6E52' },
  ANNULE:   { label: 'Annulé',    bg: '#FEF0EE', color: '#C0391B' },
}

const PRIORITE_COLOR: Record<string, string> = {
  HAUTE:   '#E74C3C',
  MOYENNE: '#F0A500',
  BASSE:   '#1D9E76',
}

const CRITICITE_COLOR: Record<NiveauCriticite, string> = {
  FAIBLE:   '#2E86C1',
  MOYENNE:  '#F0A500',
  ELEVEE:   '#E67E22',
  CRITIQUE: '#E74C3C',
}

const CRITICITE_ORDER: NiveauCriticite[] = ['FAIBLE', 'MOYENNE', 'ELEVEE', 'CRITIQUE']

const QUARTERS = [
  { label: 'T1 2026', start: 0,   end: 90  },
  { label: 'T2 2026', start: 91,  end: 181 },
  { label: 'T3 2026', start: 182, end: 273 },
  { label: 'T4 2026', start: 274, end: 365 },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function dayOfYear(dateStr: string): number {
  const d = new Date(dateStr)
  const start = new Date(d.getFullYear(), 0, 0)
  return Math.floor((d.getTime() - start.getTime()) / 86400000)
}

function barPos(debut: string, fin: string) {
  const total = 365
  const s = Math.max(1, dayOfYear(debut))
  const e = Math.min(365, dayOfYear(fin))
  return { left: ((s - 1) / total) * 100, width: Math.max(1, ((e - s + 1) / total) * 100) }
}

function getBarColor(item: RoadmapItemWithRisks): string {
  if (item.statut === 'ANNULE') return '#95A5A6'
  if (item.statut === 'TERMINE') return '#1D9E76'
  if (item.is_late) {
    if (item.days_overdue > 30) return '#E74C3C'
    if (item.days_overdue > 7)  return '#E67E22'
    return '#F0A500'
  }
  if (item.days_until_due >= 0 && item.days_until_due <= 7) return '#F0A500'
  return PRIORITE_COLOR[item.priorite] ?? '#1A3A5C'
}

type DelayCategory = 'on_time' | 'at_risk' | 'late' | null

function classifyItem(item: RoadmapItemWithRisks): DelayCategory {
  if (item.statut === 'TERMINE' || item.statut === 'ANNULE') return 'on_time'
  if (item.is_late) return 'late'
  if (item.days_until_due >= 0 && item.days_until_due <= 7) return 'at_risk'
  return 'on_time'
}

const canEdit = (role: string) => ['Chef de Projet', 'Admin'].includes(role)

const EMPTY = {
  titre: '', description: '',
  date_debut: '2026-01-01', date_fin: '2026-03-31',
  statut: 'PLANIFIE' as RoadmapItem['statut'],
  priorite: 'MOYENNE' as RoadmapItem['priorite'],
  annee: 2026,
  projet_id: null as string | null,
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function RoadmapPage() {
  const { role } = useAuth()
  const editable = canEdit(role)

  const [items, setItems]           = useState<RoadmapItemWithRisks[]>([])
  const [projects, setProjects]     = useState<Project[]>([])
  const [loading, setLoading]       = useState(true)
  const [filterStatut, setFilterStatut] = useState('')
  const [filterProjet, setFilterProjet] = useState('')
  const [delayFilter, setDelayFilter]   = useState<DelayCategory>(null)
  const [showModal, setShowModal]   = useState(false)
  const [form, setForm]             = useState({ ...EMPTY })
  const [saving, setSaving]         = useState(false)

  // Risk side panel
  const [panelItemId, setPanelItemId]   = useState<string | null>(null)
  const [panelRisks, setPanelRisks]     = useState<Risk[]>([])
  const [panelLoading, setPanelLoading] = useState(false)

  // Per-item AI scan state
  const [creatingRisk, setCreatingRisk] = useState<string | null>(null)
  const [riskCreated, setRiskCreated]   = useState<string | null>(null)

  useEffect(() => {
    Promise.all([listRoadmapWithRisks(2026), listProjects()])
      .then(([r, p]) => { setItems(r); setProjects(p) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const openPanel = useCallback(async (itemId: string) => {
    setPanelItemId(itemId)
    setPanelRisks([])
    setPanelLoading(true)
    try {
      const risks = await getRisksForRoadmap(itemId)
      setPanelRisks(risks)
    } catch { /* ignore */ }
    setPanelLoading(false)
  }, [])

  const closePanel = () => { setPanelItemId(null); setPanelRisks([]) }

  async function handleCreateItemRisk(itemId: string) {
    setCreatingRisk(itemId)
    setRiskCreated(null)
    try {
      await scanItemRisk(itemId)
      setRiskCreated(itemId)
      // Refresh items and panel risks
      const [r] = await Promise.all([listRoadmapWithRisks(2026)])
      setItems(r)
      if (panelItemId === itemId) {
        const risks = await getRisksForRoadmap(itemId)
        setPanelRisks(risks)
      }
    } catch { /* ignore */ }
    setCreatingRisk(null)
  }

  const filtered = items.filter(i => {
    if (filterStatut && i.statut !== filterStatut) return false
    if (filterProjet && i.projet_id !== filterProjet) return false
    if (delayFilter) {
      const cat = classifyItem(i)
      if (delayFilter === 'on_time' && cat !== 'on_time') return false
      if (delayFilter === 'at_risk' && cat !== 'at_risk') return false
      if (delayFilter === 'late' && cat !== 'late') return false
    }
    return true
  })

  // Summary counts
  const counts = items.reduce(
    (acc, i) => {
      const cat = classifyItem(i)
      acc[cat]++
      if (i.risk_summary.highest_criticite === 'CRITIQUE') acc.critical++
      return acc
    },
    { on_time: 0, at_risk: 0, late: 0, critical: 0 } as Record<string, number>
  )

  async function handleSave() {
    setSaving(true)
    try {
      const created = await createRoadmapItem(form)
      // listRoadmapWithRisks to get enriched item
      const all = await listRoadmapWithRisks(2026)
      setItems(all)
      setShowModal(false)
      setForm({ ...EMPTY })
    } catch { /* ignore */ }
    setSaving(false)
  }

  async function handleUpdateStatut(item: RoadmapItemWithRisks, statut: RoadmapItem['statut']) {
    try {
      await updateRoadmapItem(item.id, { statut })
      const all = await listRoadmapWithRisks(2026)
      setItems(all)
    } catch { /* ignore */ }
  }

  async function handleDelete(id: string) {
    try {
      await deleteRoadmapItem(id)
      setItems(prev => prev.filter(i => i.id !== id))
      if (panelItemId === id) closePanel()
    } catch { /* ignore */ }
  }

  const inp = 'w-full border rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-400 transition-all'

  return (
    <div>
      <PageHeader title="Feuille de Route 2026" badge={`${items.length} items`}>
        {editable && (
          <Button icon={<Plus size={14} />} onClick={() => setShowModal(true)}>
            Ajouter item
          </Button>
        )}
      </PageHeader>

      <div className="p-6 space-y-5">

        {/* Summary bar */}
        {!loading && (
          <div
            className="flex items-center gap-4 px-5 py-3 rounded-xl border text-sm font-medium"
            style={{ background: '#F5F7FA', borderColor: '#D5E8F5' }}
          >
            <button
              className={`flex items-center gap-2 px-3 py-1 rounded-lg transition-all ${delayFilter === 'on_time' ? 'ring-2 ring-green-400' : 'hover:bg-white'}`}
              onClick={() => setDelayFilter(f => f === 'on_time' ? null : 'on_time')}
            >
              <span className="w-2.5 h-2.5 rounded-full bg-green-500" />
              <span style={{ color: '#1A3A5C' }}>À l'heure&nbsp;: <strong>{counts.on_time}</strong></span>
            </button>
            <button
              className={`flex items-center gap-2 px-3 py-1 rounded-lg transition-all ${delayFilter === 'at_risk' ? 'ring-2 ring-yellow-400' : 'hover:bg-white'}`}
              onClick={() => setDelayFilter(f => f === 'at_risk' ? null : 'at_risk')}
            >
              <span className="w-2.5 h-2.5 rounded-full bg-yellow-400" />
              <span style={{ color: '#1A3A5C' }}>Échéance proche&nbsp;: <strong>{counts.at_risk}</strong></span>
            </button>
            <button
              className={`flex items-center gap-2 px-3 py-1 rounded-lg transition-all ${delayFilter === 'late' ? 'ring-2 ring-red-400' : 'hover:bg-white'}`}
              onClick={() => setDelayFilter(f => f === 'late' ? null : 'late')}
            >
              <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
              <span style={{ color: '#1A3A5C' }}>En retard&nbsp;: <strong>{counts.late}</strong></span>
            </button>
            {counts.critical > 0 && (
              <div className="ml-auto flex items-center gap-1.5 text-xs font-semibold" style={{ color: '#E74C3C' }}>
                <AlertTriangle size={13} />
                Risques critiques liés&nbsp;: {counts.critical}
              </div>
            )}
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3">
          <select
            className="border rounded-lg px-3 py-2 text-xs"
            style={{ borderColor: '#D5E8F5' }}
            value={filterStatut}
            onChange={e => setFilterStatut(e.target.value)}
          >
            <option value="">Tous les statuts</option>
            {Object.entries(STATUT_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <select
            className="border rounded-lg px-3 py-2 text-xs"
            style={{ borderColor: '#D5E8F5' }}
            value={filterProjet}
            onChange={e => setFilterProjet(e.target.value)}
          >
            <option value="">Tous les projets</option>
            {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {delayFilter && (
            <button
              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border"
              style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}
              onClick={() => setDelayFilter(null)}
            >
              <X size={11} /> Effacer filtre
            </button>
          )}
          <div className="flex items-center gap-3 ml-auto">
            {Object.entries(PRIORITE_COLOR).map(([k, c]) => (
              <span key={k} className="flex items-center gap-1.5 text-xs font-medium" style={{ color: '#5D6D7E' }}>
                <span className="w-3 h-3 rounded-sm" style={{ background: c }} />
                {k.charAt(0) + k.slice(1).toLowerCase()}
              </span>
            ))}
          </div>
        </div>

        {/* Gantt + side panel wrapper */}
        <div className="flex gap-4">
          <div className={panelItemId ? 'flex-1 min-w-0' : 'w-full'}>
            <Card>
              {loading ? (
                <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>Chargement…</p>
              ) : filtered.length === 0 ? (
                <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>
                  Aucun item roadmap. {editable && 'Cliquez sur "Ajouter item" pour commencer.'}
                </p>
              ) : (
                <div>
                  {/* Quarter header */}
                  <div className="flex mb-3 ml-44">
                    {QUARTERS.map(q => (
                      <div key={q.label} className="flex-1 text-center text-xs font-semibold" style={{ color: '#1A3A5C' }}>
                        {q.label}
                      </div>
                    ))}
                  </div>

                  {/* Quarter grid lines */}
                  <div className="relative">
                    <div className="absolute inset-y-0 left-44 right-0 flex pointer-events-none">
                      {QUARTERS.map((_q, i) => (
                        <div key={i} className="flex-1" style={{ borderLeft: '1px dashed #E2EBF3' }} />
                      ))}
                      <div style={{ borderRight: '1px dashed #E2EBF3', width: 0 }} />
                    </div>

                    {/* Rows */}
                    <div className="space-y-2">
                      {filtered.map(item => {
                        const bar     = barPos(item.date_debut, item.date_fin)
                        const color   = getBarColor(item)
                        const st      = STATUT_MAP[item.statut]
                        const isLate  = item.is_late
                        const soon    = !isLate && item.days_until_due >= 0 && item.days_until_due <= 7
                        const done    = item.statut === 'TERMINE'
                        const rs      = item.risk_summary
                        const isSelectedPanel = panelItemId === item.id

                        return (
                          <div
                            key={item.id}
                            className={`flex items-center gap-3 group rounded-lg ${isSelectedPanel ? 'ring-1' : ''}`}
                            style={isSelectedPanel ? { ringColor: '#2E86C1' } : {}}
                          >
                            {/* Label */}
                            <div className="shrink-0 w-44 pr-3">
                              <div className="flex items-center gap-1">
                                {done && <CheckCircle size={11} style={{ color: '#1D9E76' }} />}
                                {isLate && <AlertTriangle size={11} style={{ color: '#E74C3C' }} />}
                                {soon && !isLate && (
                                  <span className="inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
                                )}
                                <p className="text-xs font-semibold truncate" style={{ color: '#1A1A2E' }} title={item.titre}>
                                  {item.titre}
                                </p>
                              </div>
                              <span
                                className="inline-block text-[10px] px-1.5 py-0.5 rounded-full font-semibold mt-0.5"
                                style={{ background: st?.bg, color: st?.color }}
                              >
                                {st?.label}
                              </span>
                              {isLate && (
                                <div className="text-[10px] font-semibold mt-0.5" style={{ color: '#E74C3C' }}>
                                  {item.days_overdue}j de retard
                                </div>
                              )}
                              {soon && !isLate && (
                                <div className="text-[10px] font-semibold mt-0.5" style={{ color: '#F0A500' }}>
                                  Échéance dans {item.days_until_due}j
                                </div>
                              )}
                            </div>

                            {/* Bar track */}
                            <div className="relative flex-1 h-9 rounded" style={{ background: '#F0F4F9' }}>
                              <div
                                className="absolute top-1 bottom-1 rounded-md flex items-center px-2"
                                style={{
                                  left: `${bar.left}%`,
                                  width: `${bar.width}%`,
                                  background: color,
                                  opacity: item.statut === 'ANNULE' ? 0.4 : 0.9,
                                  boxShadow: isLate ? `0 0 0 1.5px ${color}` : undefined,
                                }}
                                title={
                                  isLate
                                    ? `En retard de ${item.days_overdue} jours\n${item.date_debut} → ${item.date_fin}${rs.count > 0 ? `\n${rs.count} risque(s) lié(s)` : ''}`
                                    : `${item.date_debut} → ${item.date_fin}`
                                }
                              >
                                {bar.width > 8 && (
                                  <span className="text-[10px] text-white font-semibold truncate flex-1">{item.titre}</span>
                                )}

                                {/* Risk badge */}
                                {rs.count > 0 && rs.highest_criticite && (
                                  <button
                                    className="shrink-0 flex items-center gap-0.5 text-[9px] font-bold px-1 py-0.5 rounded-full ml-1"
                                    style={{
                                      background: 'rgba(255,255,255,0.9)',
                                      color: CRITICITE_COLOR[rs.highest_criticite],
                                    }}
                                    onClick={e => { e.stopPropagation(); openPanel(item.id) }}
                                    title={`${rs.count} risque(s) — criticité max : ${rs.highest_criticite}`}
                                  >
                                    ⚠ {rs.count}
                                  </button>
                                )}
                              </div>
                            </div>

                            {/* Actions */}
                            <div className="shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              {/* Panel open button */}
                              <button
                                className="text-xs px-1.5 py-0.5 rounded border hover:bg-blue-50 transition-colors"
                                style={{ borderColor: '#D5E8F5', color: '#2E86C1' }}
                                onClick={() => isSelectedPanel ? closePanel() : openPanel(item.id)}
                                title="Voir risques liés"
                              >
                                <ChevronRight size={12} />
                              </button>

                              {/* AI risk creation button — only on late items */}
                              {isLate && editable && (
                                <button
                                  className="text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors"
                                  style={{
                                    borderColor: creatingRisk === item.id ? '#D5E8F5' : '#F0A500',
                                    color: riskCreated === item.id ? '#1D9E76' : '#B07800',
                                    background: riskCreated === item.id ? '#E8F5F0' : undefined,
                                  }}
                                  disabled={creatingRisk === item.id}
                                  onClick={() => handleCreateItemRisk(item.id)}
                                  title="Demander à l'IA de créer un risque de retard"
                                >
                                  {creatingRisk === item.id
                                    ? '⏳ IA…'
                                    : riskCreated === item.id
                                      ? '✅ Créé'
                                      : '🤖 Risque'}
                                </button>
                              )}

                              {editable && (
                                <>
                                  <select
                                    className="border rounded text-xs px-1 py-0.5"
                                    style={{ borderColor: '#D5E8F5' }}
                                    value={item.statut}
                                    onChange={e => handleUpdateStatut(item, e.target.value as RoadmapItem['statut'])}
                                  >
                                    {Object.keys(STATUT_MAP).map(k => <option key={k} value={k}>{k}</option>)}
                                  </select>
                                  <button onClick={() => handleDelete(item.id)} className="text-red-400 hover:text-red-600 transition-colors">
                                    <X size={13} />
                                  </button>
                                </>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}
            </Card>
          </div>

          {/* Risk side panel */}
          {panelItemId && (
            <div
              className="shrink-0 w-72 rounded-xl border flex flex-col"
              style={{ background: '#FFFFFF', borderColor: '#D5E8F5', maxHeight: '70vh' }}
            >
              <div
                className="flex items-center justify-between px-4 py-3 border-b rounded-t-xl"
                style={{ borderColor: '#D5E8F5', background: '#F5F7FA' }}
              >
                <span className="text-sm font-bold" style={{ color: '#1A3A5C' }}>Risques liés</span>
                <button onClick={closePanel} className="hover:opacity-60 transition-opacity">
                  <X size={14} style={{ color: '#5D6D7E' }} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {panelLoading ? (
                  <p className="text-xs text-center py-6" style={{ color: '#5D6D7E' }}>Chargement…</p>
                ) : panelRisks.length === 0 ? (
                  <p className="text-xs text-center py-6" style={{ color: '#5D6D7E' }}>Aucun risque lié à ce jalon.</p>
                ) : (
                  panelRisks.map(r => (
                    <div
                      key={r.id}
                      className="rounded-lg border p-2.5 text-xs"
                      style={{ borderColor: '#E2EBF3', background: '#FAFBFC' }}
                    >
                      <div className="flex items-start justify-between gap-2 mb-1">
                        <span className="font-semibold leading-tight" style={{ color: '#1A1A2E' }}>{r.titre}</span>
                        <span
                          className="shrink-0 px-1.5 py-0.5 rounded-full font-bold text-[10px]"
                          style={{
                            background: `${CRITICITE_COLOR[r.niveau_criticite]}20`,
                            color: CRITICITE_COLOR[r.niveau_criticite],
                          }}
                        >
                          {r.niveau_criticite}
                        </span>
                      </div>
                      <div className="flex items-center gap-2" style={{ color: '#5D6D7E' }}>
                        <span>{r.statut}</span>
                        {r.created_by === 'system:ai' && (
                          <span className="px-1 py-0.5 rounded text-[9px] font-semibold" style={{ background: '#FFF8E8', color: '#B07800' }}>
                            🤖 IA
                          </span>
                        )}
                      </div>
                      <a
                        href="/risques"
                        className="mt-1 inline-flex items-center gap-0.5 text-[10px] font-medium hover:underline"
                        style={{ color: '#2E86C1' }}
                      >
                        Voir détails <ChevronRight size={9} />
                      </a>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Create modal */}
        {showModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
            <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
              <div className="flex items-center justify-between mb-5">
                <h3 className="font-bold text-base" style={{ color: '#1A1A2E' }}>Nouvel item roadmap</h3>
                <button onClick={() => setShowModal(false)}><X size={18} style={{ color: '#5D6D7E' }} /></button>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Titre</label>
                  <input className={inp} value={form.titre} onChange={e => setForm(f => ({ ...f, titre: e.target.value }))} placeholder="Ex : Migration infrastructure cloud" style={{ borderColor: '#D5E8F5' }} />
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Description</label>
                  <textarea className={inp} rows={2} value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} style={{ borderColor: '#D5E8F5', resize: 'none' }} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Date début</label>
                    <input type="date" className={inp} value={form.date_debut} onChange={e => setForm(f => ({ ...f, date_debut: e.target.value }))} style={{ borderColor: '#D5E8F5' }} />
                  </div>
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Date fin</label>
                    <input type="date" className={inp} value={form.date_fin} onChange={e => setForm(f => ({ ...f, date_fin: e.target.value }))} style={{ borderColor: '#D5E8F5' }} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Priorité</label>
                    <select className={inp} value={form.priorite} onChange={e => setForm(f => ({ ...f, priorite: e.target.value as RoadmapItem['priorite'] }))} style={{ borderColor: '#D5E8F5' }}>
                      <option value="HAUTE">Haute</option>
                      <option value="MOYENNE">Moyenne</option>
                      <option value="BASSE">Basse</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Statut</label>
                    <select className={inp} value={form.statut} onChange={e => setForm(f => ({ ...f, statut: e.target.value as RoadmapItem['statut'] }))} style={{ borderColor: '#D5E8F5' }}>
                      {Object.entries(STATUT_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Projet associé (optionnel)</label>
                  <select className={inp} value={form.projet_id ?? ''} onChange={e => setForm(f => ({ ...f, projet_id: e.target.value || null }))} style={{ borderColor: '#D5E8F5' }}>
                    <option value="">Aucun projet</option>
                    {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex gap-2 mt-5">
                <Button onClick={handleSave} disabled={saving || !form.titre}>
                  {saving ? 'Enregistrement…' : 'Ajouter'}
                </Button>
                <Button variant="secondary" onClick={() => setShowModal(false)}>Annuler</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
