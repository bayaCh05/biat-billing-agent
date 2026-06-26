import { useState, useEffect } from 'react'
import { Plus, X, ChevronDown } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { useAuth } from '../context/AuthContext'
import type { RoadmapItem } from '../types'
import { listRoadmap, createRoadmapItem, updateRoadmapItem, deleteRoadmapItem, listProjects } from '../api/endpoints'
import type { Project } from '../types'

const STATUT_MAP: Record<string, { label: string; bg: string; color: string }> = {
  PLANIFIE: { label: 'Planifié',   bg: '#EFF4FA', color: '#1A3A5C' },
  EN_COURS: { label: 'En cours',   bg: '#FFF8E8', color: '#B07800' },
  TERMINE:  { label: 'Terminé',    bg: '#E8F5F0', color: '#0D6E52' },
  ANNULE:   { label: 'Annulé',     bg: '#FEF0EE', color: '#C0391B' },
}

const PRIORITE_COLOR: Record<string, string> = {
  HAUTE:   '#E74C3C',
  MOYENNE: '#F0A500',
  BASSE:   '#1D9E76',
}

const QUARTERS = [
  { label: 'T1 2026', start: 0,   end: 90  },
  { label: 'T2 2026', start: 91,  end: 181 },
  { label: 'T3 2026', start: 182, end: 273 },
  { label: 'T4 2026', start: 274, end: 365 },
]

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

const canEdit = (role: string) => ['Chef de Projet', 'Admin'].includes(role)

const EMPTY = { titre: '', description: '', date_debut: '2026-01-01', date_fin: '2026-03-31', statut: 'PLANIFIE', priorite: 'MOYENNE', annee: 2026, projet_id: null as string | null }

export default function RoadmapPage() {
  const { role } = useAuth()
  const editable = canEdit(role)

  const [items, setItems] = useState<RoadmapItem[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [filterStatut, setFilterStatut] = useState('')
  const [filterProjet, setFilterProjet] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState({ ...EMPTY })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.all([listRoadmap(2026), listProjects()])
      .then(([r, p]) => { setItems(r); setProjects(p) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = items.filter(i =>
    (!filterStatut || i.statut === filterStatut) &&
    (!filterProjet || i.projet_id === filterProjet)
  )

  async function handleSave() {
    setSaving(true)
    try {
      const created = await createRoadmapItem(form)
      setItems(prev => [...prev, created])
      setShowModal(false)
      setForm({ ...EMPTY })
    } catch { /* ignore */ }
    setSaving(false)
  }

  async function handleUpdateStatut(item: RoadmapItem, statut: string) {
    try {
      const updated = await updateRoadmapItem(item.id, { statut })
      setItems(prev => prev.map(i => i.id === item.id ? updated : i))
    } catch { /* ignore */ }
  }

  async function handleDelete(id: string) {
    try {
      await deleteRoadmapItem(id)
      setItems(prev => prev.filter(i => i.id !== id))
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
          <div className="flex items-center gap-3 ml-auto">
            {Object.entries(PRIORITE_COLOR).map(([k, c]) => (
              <span key={k} className="flex items-center gap-1.5 text-xs font-medium" style={{ color: '#5D6D7E' }}>
                <span className="w-3 h-3 rounded-sm" style={{ background: c }} />
                {k.charAt(0) + k.slice(1).toLowerCase()}
              </span>
            ))}
          </div>
        </div>

        {/* Gantt */}
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
                  {QUARTERS.map((q, i) => (
                    <div key={i} className="flex-1" style={{ borderLeft: '1px dashed #E2EBF3' }} />
                  ))}
                  <div style={{ borderRight: '1px dashed #E2EBF3', width: 0 }} />
                </div>

                {/* Rows */}
                <div className="space-y-2">
                  {filtered.map(item => {
                    const bar = barPos(item.date_debut, item.date_fin)
                    const color = PRIORITE_COLOR[item.priorite] ?? '#1A3A5C'
                    const st = STATUT_MAP[item.statut]
                    return (
                      <div key={item.id} className="flex items-center gap-3 group">
                        {/* Label */}
                        <div className="shrink-0 w-44 pr-3">
                          <p className="text-xs font-semibold truncate" style={{ color: '#1A1A2E' }} title={item.titre}>{item.titre}</p>
                          <span className="inline-block text-[10px] px-1.5 py-0.5 rounded-full font-semibold mt-0.5" style={{ background: st?.bg, color: st?.color }}>
                            {st?.label}
                          </span>
                        </div>

                        {/* Bar track */}
                        <div className="relative flex-1 h-8 rounded" style={{ background: '#F0F4F9' }}>
                          <div
                            className="absolute top-1 bottom-1 rounded-md flex items-center px-2 cursor-default"
                            style={{ left: `${bar.left}%`, width: `${bar.width}%`, background: color, opacity: item.statut === 'ANNULE' ? 0.4 : 0.85 }}
                            title={`${item.date_debut} → ${item.date_fin}`}
                          >
                            {bar.width > 8 && (
                              <span className="text-[10px] text-white font-semibold truncate">{item.titre}</span>
                            )}
                          </div>
                        </div>

                        {/* Actions */}
                        {editable && (
                          <div className="shrink-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <select
                              className="border rounded text-xs px-1 py-0.5"
                              style={{ borderColor: '#D5E8F5' }}
                              value={item.statut}
                              onChange={e => handleUpdateStatut(item, e.target.value)}
                            >
                              {Object.keys(STATUT_MAP).map(k => <option key={k} value={k}>{k}</option>)}
                            </select>
                            <button onClick={() => handleDelete(item.id)} className="text-red-400 hover:text-red-600 transition-colors">
                              <X size={13} />
                            </button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          )}
        </Card>

        {/* Modal */}
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
                    <select className={inp} value={form.priorite} onChange={e => setForm(f => ({ ...f, priorite: e.target.value }))} style={{ borderColor: '#D5E8F5' }}>
                      <option value="HAUTE">Haute</option>
                      <option value="MOYENNE">Moyenne</option>
                      <option value="BASSE">Basse</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Statut</label>
                    <select className={inp} value={form.statut} onChange={e => setForm(f => ({ ...f, statut: e.target.value }))} style={{ borderColor: '#D5E8F5' }}>
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
