import { useState, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, Pencil, Plus, Trash2, X, Check, Info } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { BudgetSummary, BudgetLine, BudgetPlanEntry } from '../../types'
import {
  getBudgetSummary, listProjects,
  getBudgetPlan, updateBudgetPlanEntry, createBudgetPlanEntry, deleteBudgetPlanEntry,
} from '../../api/endpoints'
import { formatTND, formatVariance } from '../../utils/formatters'
import PageSpinner from '../../components/ui/PageSpinner'
import { useAuth } from '../../context/AuthContext'
import type { Project } from '../../types'

const MONTH_LABELS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

const EMPTY: BudgetSummary = {
  year: new Date().getFullYear(), through_month: new Date().getMonth() + 1,
  total_budget_ytd: 0, total_actual_ytd: 0,
  variance_pct: 0, lines_over_budget: 0, lines: [],
}

function periodLabel(month: number) {
  return `${MONTH_LABELS[0]} – ${MONTH_LABELS[month - 1]}`
}

// ── Edit modal for one budget line ───────────────────────────────────────────

interface EditModalProps {
  entry: BudgetPlanEntry
  onSave: (monthly: number[], label: string, note: string) => Promise<void>
  onClose: () => void
}

function EditModal({ entry, onSave, onClose }: EditModalProps) {
  const [monthly, setMonthly] = useState<number[]>([...entry.monthly])
  const [label, setLabel] = useState(entry.label)
  const [note, setNote] = useState(entry.note ?? '')
  const [saving, setSaving] = useState(false)
  const [uniform, setUniform] = useState(false)
  const [uniformVal, setUniformVal] = useState(entry.annual_total / 12)

  const applyUniform = () => setMonthly(Array(12).fill(Number(uniformVal)))

  const handleSave = async () => {
    setSaving(true)
    await onSave(monthly, label, note)
    setSaving(false)
  }

  const annual = monthly.reduce((s, v) => s + Number(v), 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#D5E8F5' }}>
          <div>
            <input
              className="text-base font-bold border-0 outline-none w-full"
              style={{ color: '#1A1A2E' }}
              value={label}
              onChange={e => setLabel(e.target.value)}
            />
            <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{entry.catalog_id}</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-full transition-colors">
            <X size={18} style={{ color: '#5D6D7E' }} />
          </button>
        </div>

        {/* Uniform shortcut */}
        <div className="px-6 pt-4 flex items-center gap-3">
          <button
            onClick={() => setUniform(v => !v)}
            className="text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors"
            style={{ borderColor: '#5BA3C9', color: '#1A3A5C', background: uniform ? '#EFF4FA' : 'white' }}
          >
            Montant uniforme / mois
          </button>
          {uniform && (
            <>
              <input
                type="number"
                className="border rounded-lg px-2 py-1 text-sm w-32 outline-none"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                value={uniformVal}
                onChange={e => setUniformVal(Number(e.target.value))}
              />
              <button
                onClick={applyUniform}
                className="text-xs font-medium px-3 py-1.5 rounded-lg text-white"
                style={{ background: '#1A3A5C' }}
              >
                Appliquer
              </button>
            </>
          )}
        </div>

        {/* Monthly grid */}
        <div className="px-6 pt-4 grid grid-cols-6 gap-2">
          {MONTH_LABELS.map((m, i) => (
            <div key={m}>
              <p className="text-[10px] font-medium mb-1 text-center" style={{ color: '#5D6D7E' }}>{m}</p>
              <input
                type="number"
                className="w-full border rounded-lg px-2 py-1.5 text-xs text-center outline-none"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                value={monthly[i]}
                onChange={e => {
                  const next = [...monthly]
                  next[i] = Number(e.target.value)
                  setMonthly(next)
                }}
              />
            </div>
          ))}
        </div>

        {/* Annual total */}
        <div className="px-6 pt-3 flex items-center gap-2">
          <span className="text-xs" style={{ color: '#5D6D7E' }}>Total annuel :</span>
          <span className="text-sm font-bold" style={{ color: '#1A3A5C' }}>{annual.toLocaleString('fr-TN')} TND</span>
        </div>

        {/* Note */}
        <div className="px-6 pt-3">
          <input
            className="w-full border rounded-lg px-3 py-2 text-xs outline-none"
            style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}
            placeholder="Note (facultatif)"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
        </div>

        {/* Footer */}
        <div className="px-6 py-4 flex justify-end gap-2 border-t mt-4" style={{ borderColor: '#D5E8F5' }}>
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border" style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}>
            Annuler
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm rounded-lg text-white font-medium flex items-center gap-2"
            style={{ background: saving ? '#9BAFBF' : '#1A3A5C' }}
          >
            <Check size={14} />
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Add line modal ────────────────────────────────────────────────────────────

interface AddModalProps {
  year: number
  onAdd: (entry: BudgetPlanEntry) => void
  onClose: () => void
}

function AddModal({ year, onAdd, onClose }: AddModalProps) {
  const [catalogId, setCatalogId] = useState('')
  const [label, setLabel] = useState('')
  const [uniformVal, setUniformVal] = useState(0)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const handleSave = async () => {
    if (!catalogId.trim() || !label.trim()) { setErr('ID et libellé requis'); return }
    setSaving(true)
    try {
      const entry = await createBudgetPlanEntry(year, {
        catalog_id: catalogId.trim().toLowerCase().replace(/\s+/g, '_'),
        label: label.trim(),
        monthly: Array(12).fill(Number(uniformVal)),
      })
      onAdd(entry)
    } catch {
      setErr('Erreur lors de la création')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#D5E8F5' }}>
          <p className="text-sm font-bold" style={{ color: '#1A1A2E' }}>Nouvelle ligne budgétaire</p>
          <button onClick={onClose}><X size={18} style={{ color: '#5D6D7E' }} /></button>
        </div>
        <div className="px-6 py-4 space-y-3">
          {err && <p className="text-xs text-red-600">{err}</p>}
          <div>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>Identifiant (catalog_id)</p>
            <input className="w-full border rounded-lg px-3 py-2 text-sm outline-none" style={{ borderColor: '#D5E8F5' }}
              placeholder="ex: nouveaux_frais" value={catalogId} onChange={e => setCatalogId(e.target.value)} />
          </div>
          <div>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>Libellé</p>
            <input className="w-full border rounded-lg px-3 py-2 text-sm outline-none" style={{ borderColor: '#D5E8F5' }}
              placeholder="ex: Nouveaux frais SI" value={label} onChange={e => setLabel(e.target.value)} />
          </div>
          <div>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>Montant mensuel (TND)</p>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm outline-none" style={{ borderColor: '#D5E8F5' }}
              value={uniformVal} onChange={e => setUniformVal(Number(e.target.value))} />
            <p className="text-[10px] mt-1" style={{ color: '#9BAFBF' }}>
              Appliqué uniformément sur les 12 mois — modifiable après création
            </p>
          </div>
        </div>
        <div className="px-6 pb-4 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border" style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}>Annuler</button>
          <button onClick={handleSave} disabled={saving}
            className="px-4 py-2 text-sm rounded-lg text-white font-medium"
            style={{ background: saving ? '#9BAFBF' : '#1A3A5C' }}>
            {saving ? 'Création…' : 'Créer'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Budget() {
  const { role } = useAuth()
  const navigate = useNavigate()
  const [year, setYear] = useState(2026)
  const [month, setMonth] = useState(6)
  const [budget, setBudget] = useState<BudgetSummary>(EMPTY)
  const [plan, setPlan] = useState<BudgetPlanEntry[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [editing, setEditing] = useState<BudgetPlanEntry | null>(null)
  const [showAdd, setShowAdd] = useState(false)

  const canEdit = role === 'Admin' || role === 'Comptable'
  const showProjectBanner = role === 'Chef de Projet' || role === 'Comptable'

  const load = useCallback(() => {
    setLoading(true)
    setError(false)
    const calls: Promise<unknown>[] = [
      getBudgetSummary(year, month).then(setBudget),
      getBudgetPlan(year).then(setPlan),
    ]
    if (showProjectBanner) calls.push(listProjects().then(setProjects).catch(() => {}))
    Promise.all(calls).catch(() => setError(true)).finally(() => setLoading(false))
  }, [year, month, showProjectBanner])

  useEffect(() => { load() }, [load])

  const handleSaveEntry = async (entry: BudgetPlanEntry, monthly: number[], label: string, note: string) => {
    await updateBudgetPlanEntry(entry.catalog_id, year, { monthly, label, note })
    setEditing(null)
    load()
  }

  const handleDelete = async (catalogId: string) => {
    if (!confirm('Supprimer cette ligne budgétaire ?')) return
    await deleteBudgetPlanEntry(catalogId, year)
    load()
  }

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const variance = budget.total_actual_ytd - budget.total_budget_ytd
  const varianceOver = variance > 0

  const sortedLines: BudgetLine[] = [...budget.lines].sort((a, b) => {
    if (a.is_over !== b.is_over) return a.is_over ? -1 : 1
    return b.variance_pct - a.variance_pct
  })

  return (
    <div style={{ background: '#F0F4F9', minHeight: '100vh' }}>
      {/* Modals */}
      {editing && (
        <EditModal
          entry={editing}
          onSave={(monthly, label, note) => handleSaveEntry(editing, monthly, label, note)}
          onClose={() => setEditing(null)}
        />
      )}
      {showAdd && (
        <AddModal
          year={year}
          onAdd={() => { setShowAdd(false); load() }}
          onClose={() => setShowAdd(false)}
        />
      )}

      {/* Header */}
      <div className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}>
        <h1 className="flex-1 text-lg font-bold" style={{ color: '#1A1A2E' }}>📊 Suivi Budgétaire</h1>

        {canEdit && (
          <button
            onClick={() => setEditMode(v => !v)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors"
            style={{
              borderColor: editMode ? '#1A3A5C' : '#D5E8F5',
              background: editMode ? '#1A3A5C' : 'white',
              color: editMode ? 'white' : '#1A3A5C',
            }}
          >
            <Pencil size={13} />
            {editMode ? 'Terminer' : 'Modifier le plan'}
          </button>
        )}

        <span className="px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
          ● Vue analytique
        </span>
        <div className="flex items-center gap-1">
          <button onClick={() => setYear(y => y - 1)} className="p-1.5 rounded hover:bg-gray-100 transition-colors">
            <ChevronLeft size={14} style={{ color: '#5D6D7E' }} />
          </button>
          <span className="text-sm font-semibold w-12 text-center" style={{ color: '#1A1A2E' }}>{year}</span>
          <button onClick={() => setYear(y => y + 1)} className="p-1.5 rounded hover:bg-gray-100 transition-colors">
            <ChevronRight size={14} style={{ color: '#5D6D7E' }} />
          </button>
        </div>
        <select
          value={month} onChange={e => setMonth(Number(e.target.value))}
          className="text-sm px-3 py-1.5 rounded-lg border outline-none"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
        >
          {MONTH_LABELS.map((_, i) => (
            <option key={i + 1} value={i + 1}>{periodLabel(i + 1)}</option>
          ))}
        </select>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4 mx-6 my-4">
        {[
          { label: 'Budget YTD', value: formatTND(budget.total_budget_ytd, 0), sub: `Jan–${MONTH_LABELS[month - 1]} ${year}`, subColor: '#5D6D7E' },
          { label: 'Réel YTD', value: formatTND(budget.total_actual_ytd, 0), sub: `${formatVariance(budget.variance_pct)} vs budget`, subColor: budget.variance_pct > 0 ? '#C0391B' : '#1D9E76' },
          { label: 'Variance', value: `${variance < 0 ? '' : '+'}${formatTND(variance, 0)}`, valueColor: varianceOver ? '#C0391B' : '#1D9E76', sub: varianceOver ? 'Dépassement' : 'Sous budget ✓', subColor: '#5D6D7E' },
          { label: 'Catégories hors budget', value: String(budget.lines_over_budget), sub: `sur ${budget.lines.length} lignes`, subColor: '#5D6D7E' },
        ].map(card => (
          <div key={card.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{card.label}</p>
            <p className="text-xl font-bold leading-tight" style={{ color: card.valueColor ?? '#1A1A2E' }}>{card.value}</p>
            <p className="text-xs mt-1" style={{ color: card.subColor }}>{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Edit mode: plan management table */}
      {editMode && (
        <div className="mx-6 mb-4 bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
          <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: '#F0F4F9' }}>
            <p className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>
              Plan budgétaire {year} — {plan.length} lignes
            </p>
            <button
              onClick={() => setShowAdd(true)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium text-white"
              style={{ background: '#1A3A5C' }}
            >
              <Plus size={12} /> Ajouter une ligne
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #E2EBF3' }}>
                  <th className="text-left px-4 py-2.5 font-semibold" style={{ color: '#5D6D7E' }}>Catégorie</th>
                  {MONTH_LABELS.map(m => (
                    <th key={m} className="text-right px-2 py-2.5 font-semibold" style={{ color: '#5D6D7E' }}>{m}</th>
                  ))}
                  <th className="text-right px-4 py-2.5 font-semibold" style={{ color: '#5D6D7E' }}>Annuel</th>
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {plan.map(entry => (
                  <tr key={entry.catalog_id} className="border-b hover:bg-gray-50 transition-colors" style={{ borderColor: '#F0F4F9' }}>
                    <td className="px-4 py-2.5">
                      <p className="font-medium" style={{ color: '#1A1A2E' }}>{entry.label}</p>
                      <p style={{ color: '#9BAFBF' }}>{entry.catalog_id}</p>
                    </td>
                    {entry.monthly.map((v, i) => (
                      <td key={i} className="text-right px-2 py-2.5" style={{ color: v === 0 ? '#D5E8F5' : '#1A1A2E' }}>
                        {v === 0 ? '—' : v.toLocaleString('fr-TN')}
                      </td>
                    ))}
                    <td className="text-right px-4 py-2.5 font-semibold" style={{ color: '#1A3A5C' }}>
                      {entry.annual_total.toLocaleString('fr-TN')}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <button onClick={() => setEditing(entry)} className="p-1 rounded hover:bg-blue-50 transition-colors" title="Modifier">
                          <Pencil size={13} style={{ color: '#1A3A5C' }} />
                        </button>
                        <button onClick={() => handleDelete(entry.catalog_id)} className="p-1 rounded hover:bg-red-50 transition-colors" title="Supprimer">
                          <Trash2 size={13} style={{ color: '#C0391B' }} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Project banner */}
      {showProjectBanner && !editMode && (
        <div className="mx-6 mb-2 rounded-xl border px-4 py-3 flex items-start gap-3" style={{ background: '#EFF4FA', borderColor: '#D5E8F5' }}>
          <Info size={15} className="mt-0.5 shrink-0" style={{ color: '#1A3A5C' }} />
          <div className="flex-1">
            <p className="text-xs font-semibold mb-0.5" style={{ color: '#1A3A5C' }}>Budget général — plan annuel modifiable</p>
            <p className="text-xs" style={{ color: '#5D6D7E' }}>
              Cliquez sur <strong>Modifier le plan</strong> pour ajuster les montants mensuels par catégorie.
              Pour les <strong>lignes budget par projet</strong>, accédez au détail d'un projet IT.
            </p>
            {projects.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {projects.slice(0, 5).map(p => (
                  <button key={p.id} onClick={() => navigate(`/projets-it/${p.id}`)}
                    className="text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-colors hover:bg-white"
                    style={{ borderColor: '#5BA3C9', color: '#1A3A5C' }}>
                    {p.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Two-column body */}
      <div className="grid gap-6 px-6 pb-6" style={{ gridTemplateColumns: '2fr 1fr' }}>
        {/* Left: bar chart */}
        <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
          <p className="text-sm font-semibold mb-5" style={{ color: '#1A1A2E' }}>
            Budget vs Réel par catégorie (Jan–{MONTH_LABELS[month - 1]} {year})
          </p>
          <div className="space-y-4">
            {budget.lines.map(line => {
              const pct = line.budget_ytd > 0 ? Math.min(100, (line.actual_ytd / line.budget_ytd) * 100) : 0
              const planEntry = plan.find(p => p.catalog_id === line.catalog_id)
              return (
                <div key={line.catalog_id}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs" style={{ color: '#5D6D7E' }}>{line.label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium" style={{ color: '#5D6D7E' }}>
                        {formatTND(line.actual_ytd, 0)} / {formatTND(line.budget_ytd, 0)}
                      </span>
                      {editMode && planEntry && (
                        <button onClick={() => setEditing(planEntry)} className="p-0.5 rounded hover:bg-blue-50 transition-colors">
                          <Pencil size={11} style={{ color: '#1A3A5C' }} />
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="h-2.5 rounded-full overflow-hidden" style={{ background: '#E8EFF7' }}>
                    <div className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: line.is_over ? '#C0391B' : '#1D9E76' }} />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-4 mt-5 text-xs" style={{ color: '#5D6D7E' }}>
            {[{ color: '#1D9E76', label: 'Réel' }, { color: '#F0A600', label: 'Budget' }, { color: '#C0391B', label: 'Dépassement' }].map(({ color, label }) => (
              <span key={label} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full inline-block shrink-0" style={{ background: color }} />
                {label}
              </span>
            ))}
          </div>
        </div>

        {/* Right: lines list */}
        <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
          <p className="text-sm font-semibold mb-4" style={{ color: '#1A1A2E' }}>Toutes les lignes budgétaires</p>
          <div className="space-y-1">
            {sortedLines.map(line => {
              const planEntry = plan.find(p => p.catalog_id === line.catalog_id)
              return (
                <div key={line.catalog_id} className="flex items-start justify-between gap-2 py-2.5 border-b" style={{ borderColor: '#F0F4F9' }}>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium" style={{ color: '#1A1A2E' }}>{line.label}</p>
                    <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                      Budget: {formatTND(line.budget_ytd, 0).replace(' TND', '')} &nbsp;Réel: {formatTND(line.actual_ytd, 0).replace(' TND', '')}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-sm font-bold" style={{ color: line.is_over ? '#C0391B' : '#1D9E76' }}>
                      {line.variance_pct > 0 ? '+' : ''}{line.variance_pct.toFixed(1)}%
                    </span>
                    {editMode && planEntry && (
                      <button onClick={() => setEditing(planEntry)} className="p-1 rounded hover:bg-blue-50 transition-colors">
                        <Pencil size={12} style={{ color: '#1A3A5C' }} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
