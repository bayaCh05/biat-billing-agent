import { useState, useEffect } from 'react'
import { ChevronLeft, ChevronRight, Info } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { BudgetSummary, BudgetLine } from '../types'
import { getBudgetSummary, listProjects } from '../api/endpoints'
import { formatTND, formatVariance } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'
import { useAuth } from '../context/AuthContext'
import type { Project } from '../types'

const MONTH_LABELS = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc']

const EMPTY: BudgetSummary = {
  year: new Date().getFullYear(), through_month: new Date().getMonth() + 1,
  total_budget_ytd: 0, total_actual_ytd: 0,
  variance_pct: 0, lines_over_budget: 0, lines: [],
}

function periodLabel(month: number) {
  return `${MONTH_LABELS[0]} – ${MONTH_LABELS[month - 1]}`
}

export default function Budget() {
  const { role } = useAuth()
  const navigate = useNavigate()
  const [year, setYear] = useState(2026)
  const [month, setMonth] = useState(6)
  const [budget, setBudget] = useState<BudgetSummary>(EMPTY)
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const showProjectBanner = role === 'Chef de Projet' || role === 'Comptable'

  useEffect(() => {
    setLoading(true)
    setError(false)
    const calls: Promise<unknown>[] = [getBudgetSummary(year, month)]
    if (showProjectBanner) calls.push(listProjects().then(setProjects).catch(() => {}))
    calls[0]
      .then(data => setBudget(data as BudgetSummary))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [year, month])

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const variance = budget.total_actual_ytd - budget.total_budget_ytd
  const varianceOver = variance > 0

  const sortedLines: BudgetLine[] = [...budget.lines].sort((a, b) => {
    if (a.is_over !== b.is_over) return a.is_over ? -1 : 1
    return b.variance_pct - a.variance_pct
  })

  return (
    <div style={{ background: '#F0F4F9', minHeight: '100vh' }}>
      {/* Page header */}
      <div
        className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}
      >
        <h1 className="flex-1 text-lg font-bold" style={{ color: '#1A1A2E' }}>📊 Suivi Budgétaire</h1>
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
          {
            label: 'Budget YTD',
            value: formatTND(budget.total_budget_ytd, 0),
            sub: `Jan–${MONTH_LABELS[month - 1]} ${year}`,
            subColor: '#5D6D7E',
          },
          {
            label: 'Réel YTD',
            value: formatTND(budget.total_actual_ytd, 0),
            sub: `${formatVariance(budget.variance_pct)} vs budget`,
            subColor: budget.variance_pct > 0 ? '#C0391B' : '#1D9E76',
          },
          {
            label: 'Variance',
            value: `${variance < 0 ? '' : '+'}${formatTND(variance, 0)}`,
            valueColor: varianceOver ? '#C0391B' : '#1D9E76',
            sub: varianceOver ? 'Dépassement' : 'Sous budget ✓',
            subColor: '#5D6D7E',
          },
          {
            label: 'Catégories hors budget',
            value: String(budget.lines_over_budget),
            sub: `sur ${budget.lines.length} lignes`,
            subColor: '#5D6D7E',
          },
        ].map(card => (
          <div key={card.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{card.label}</p>
            <p className="text-xl font-bold leading-tight" style={{ color: card.valueColor ?? '#1A1A2E' }}>{card.value}</p>
            <p className="text-xs mt-1" style={{ color: card.subColor }}>{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Banner for Chef de Projet / Comptable: link to project budget lines */}
      {showProjectBanner && (
        <div
          className="mx-6 mb-2 rounded-xl border px-4 py-3 flex items-start gap-3"
          style={{ background: '#EFF4FA', borderColor: '#D5E8F5' }}
        >
          <Info size={15} className="mt-0.5 shrink-0" style={{ color: '#1A3A5C' }} />
          <div className="flex-1">
            <p className="text-xs font-semibold mb-0.5" style={{ color: '#1A3A5C' }}>
              Vue analytique globale — lecture seule
            </p>
            <p className="text-xs" style={{ color: '#5D6D7E' }}>
              Cette page affiche le budget opérationnel défini dans le plan annuel.
              Pour ajouter ou modifier des <strong>lignes budget par projet</strong>, accédez au détail d'un projet IT.
            </p>
            {projects.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {projects.slice(0, 5).map(p => (
                  <button
                    key={p.id}
                    onClick={() => navigate(`/projets-it/${p.id}`)}
                    className="text-[11px] font-medium px-2.5 py-1 rounded-lg border transition-colors hover:bg-white"
                    style={{ borderColor: '#5BA3C9', color: '#1A3A5C' }}
                  >
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
        {/* Left: horizontal bar chart */}
        <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
          <p className="text-sm font-semibold mb-5" style={{ color: '#1A1A2E' }}>
            Budget vs Réel par catégorie (Jan–{MONTH_LABELS[month - 1]} {year})
          </p>
          <div className="space-y-4">
            {budget.lines.map(line => {
              const pct = line.budget_ytd > 0 ? Math.min(100, (line.actual_ytd / line.budget_ytd) * 100) : 0
              const barColor = line.is_over ? '#C0391B' : '#1D9E76'
              return (
                <div key={line.catalog_id}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs" style={{ color: '#5D6D7E' }}>{line.label}</span>
                    <span className="text-xs font-medium" style={{ color: '#5D6D7E' }}>
                      {formatTND(line.actual_ytd, 0)}
                    </span>
                  </div>
                  <div className="h-2.5 rounded-full overflow-hidden" style={{ background: '#E8EFF7' }}>
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: barColor }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-4 mt-5 text-xs" style={{ color: '#5D6D7E' }}>
            {[
              { color: '#1D9E76', label: 'Réel' },
              { color: '#F0A600', label: 'Budget' },
              { color: '#C0391B', label: 'Dépassement' },
            ].map(({ color, label }) => (
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
            {sortedLines.map(line => (
              <div key={line.catalog_id} className="flex items-start justify-between gap-2 py-2.5 border-b" style={{ borderColor: '#F0F4F9' }}>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium" style={{ color: '#1A1A2E' }}>{line.label}</p>
                  <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                    Budget: {formatTND(line.budget_ytd, 0).replace(' TND', '')} &nbsp;Réel: {formatTND(line.actual_ytd, 0).replace(' TND', '')}
                  </p>
                </div>
                <span className="text-sm font-bold shrink-0" style={{ color: line.is_over ? '#C0391B' : '#1D9E76' }}>
                  {line.variance_pct > 0 ? '+' : ''}{line.variance_pct.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
