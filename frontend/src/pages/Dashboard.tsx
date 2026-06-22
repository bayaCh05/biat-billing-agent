import { useState, useEffect } from 'react'
import { Bell, Search, FileText, Zap, TrendingUp, Clock, AlertTriangle } from 'lucide-react'
import StatusChip from '../components/ui/StatusChip'
import { getKpi, listInvoices, getBudgetSummary } from '../api/endpoints'
import type { KpiData, InvoiceSummary, BudgetLine } from '../types'
import { formatTND, formatTNDCompact } from '../utils/formatters'
import { budgetLinesMock, mockInvoices } from '../data/mockInvoices'
import { useAuth } from '../context/AuthContext'

const MOCK_KPI: KpiData = {
  total_invoices: 20,
  total_amount_ttc: 271364,
  auto_approved: 17,
  auto_approval_rate: 85,
  flagged: 4,
  pending_review: 4,
  by_status: {
    RECEIVED: 24, EXTRACTED: 22, CLASSIFIED: 21,
    VALIDATED: 20, EXPORTED: 18, JOURNALED: 16, PAID: 12,
  },
}

const PIPELINE_STAGES = [
  { keys: ['RECEIVED'],                   label: 'Reçues',      bg: '#3B4F6B' },
  { keys: ['EXTRACTING', 'EXTRACTED'],    label: 'Extraites',   bg: '#2E6B8A' },
  { keys: ['CLASSIFYING', 'CLASSIFIED'],  label: 'Classifiées', bg: '#2A7A8A' },
  { keys: ['VALIDATING', 'VALIDATED'],    label: 'Validées',    bg: '#1D8A6B' },
  { keys: ['EXPORTING', 'EXPORTED'],      label: 'Exportées',   bg: '#1A9060' },
  { keys: ['JOURNALING', 'JOURNALED'],    label: 'Journalisées',bg: '#178050' },
  { keys: ['PAID', 'COLLECTED'],          label: 'Payées',      bg: '#147040' },
]

const BAR_COLORS = ['#1A3A5C', '#2E6B8A', '#C0391B', '#1D9E76', '#804CD7', '#F0A600']

const ALERTS = [
  { text: '4 factures en attente de révision',       border: '#F0A600', bg: '#FFF8E8' },
  { text: '3 factures en retard de paiement',        border: '#C0391B', bg: '#FFF0EE' },
  { text: "1 immobilisation en fin d'amortissement", border: '#E67E22', bg: '#FFF4E8' },
  { text: 'Budget Télécoms dépassé de 12%',          border: '#C0391B', bg: '#FFF0EE' },
]

const KPI_META = [
  { icon: FileText,   bg: '#EFF4FA', color: '#1A3A5C', delta: '+4 vs mois dernier',  pos: true  },
  { icon: Zap,        bg: '#FFF8E8', color: '#F0A600', delta: 'Objectif: 80%',        pos: true  },
  { icon: TrendingUp, bg: '#E8F5F0', color: '#1D9E76', delta: '+12% vs 2025',         pos: true  },
  { icon: Clock,      bg: '#FDECEA', color: '#C0391B', delta: '⚠ Action requise',     pos: false },
]

function timeAgo(iso: string): string {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000)
  if (h < 1) return "À l'instant"
  if (h < 24) return `Il y a ${h}h`
  return `Il y a ${Math.floor(h / 24)}j`
}

export default function Dashboard() {
  const { role, initials, notifCount } = useAuth()
  const [kpi, setKpi] = useState<KpiData>(MOCK_KPI)
  const [recent, setRecent] = useState<InvoiceSummary[]>(mockInvoices.slice(0, 5))
  const [budgetLines, setBudgetLines] = useState<BudgetLine[]>(budgetLinesMock)

  useEffect(() => {
    Promise.all([
      getKpi().catch(() => null),
      listInvoices().catch(() => null),
      getBudgetSummary().catch(() => null),
    ]).then(([kpiData, invData, budgetData]) => {
      if (kpiData) setKpi(kpiData)
      if (invData) setRecent(invData.slice(0, 5))
      if (budgetData) setBudgetLines(budgetData.lines)
    })
  }, [])

  const kpiCards = [
    { label: 'Factures traitées',        value: String(kpi.total_invoices) },
    { label: "Taux d'auto-approbation",  value: `${kpi.auto_approval_rate}%` },
    { label: 'Dépenses Y TD',            value: formatTNDCompact(kpi.total_amount_ttc) },
    { label: 'En attente de révision',   value: String(kpi.pending_review) },
  ]

  const maxBudget = Math.max(...budgetLines.map(l => l.budget_ytd), 1)

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <header className="flex items-center gap-3 px-6 h-14 border-b shrink-0 bg-white" style={{ borderColor: '#D5E8F5' }}>
        <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>Tableau de bord</h1>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#5BA3C9' }} />
          {role}
        </span>
        <div className="flex-1" />
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#5D6D7E' }} />
          <input
            placeholder="Rechercher..."
            className="pl-8 pr-3 py-1.5 text-sm rounded-lg border outline-none w-52"
            style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
          />
        </div>
        <button className="relative p-1.5 rounded-lg hover:bg-gray-50">
          <Bell size={18} style={{ color: '#5D6D7E' }} />
          {notifCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full text-white text-[9px] font-bold flex items-center justify-center" style={{ background: '#C0391B' }}>
              {notifCount}
            </span>
          )}
        </button>
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0" style={{ background: '#1A3A5C' }}>
          {initials}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {/* KPI Row */}
        <div className="grid grid-cols-4 gap-4">
          {kpiCards.map((card, i) => {
            const Meta = KPI_META[i]
            const Icon = Meta.icon
            return (
              <div key={card.label} className="bg-white rounded-xl border p-4 flex items-start gap-3" style={{ borderColor: '#D5E8F5' }}>
                <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: Meta.bg }}>
                  <Icon size={18} style={{ color: Meta.color }} />
                </div>
                <div className="min-w-0">
                  <p className="text-xs leading-snug" style={{ color: '#5D6D7E' }}>{card.label}</p>
                  <p className="text-2xl font-bold leading-tight mt-0.5" style={{ color: '#1A1A2E' }}>{card.value}</p>
                  <p className="text-xs font-medium mt-1" style={{ color: Meta.pos ? '#1D9E76' : '#E67E22' }}>{Meta.delta}</p>
                </div>
              </div>
            )
          })}
        </div>

        {/* Pipeline + Alertes */}
        <div className="grid grid-cols-[1fr_300px] gap-4">
          <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5' }}>
            <p className="font-semibold text-sm mb-3" style={{ color: '#1A3A5C' }}>Pipeline des factures</p>
            <div className="flex gap-2">
              {PIPELINE_STAGES.map(stage => {
                const count = stage.keys.reduce((s, k) => s + (kpi.by_status[k] ?? 0), 0)
                return (
                  <div key={stage.label} className="flex-1 rounded-lg px-2 py-3 text-center" style={{ background: stage.bg }}>
                    <p className="text-xl font-bold text-white">{count}</p>
                    <p className="text-[10px] text-white/80 mt-0.5 leading-tight">{stage.label}</p>
                  </div>
                )
              })}
            </div>
            <p className="text-xs mt-2.5" style={{ color: '#5D6D7E' }}>
              {kpi.by_status['RECEIVED'] ?? 24} → {kpi.by_status['PAID'] ?? 12} factures payées ce mois
            </p>
          </div>

          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
            <div className="flex items-center gap-2 mb-3">
              <p className="font-semibold text-sm" style={{ color: '#1A1A2E' }}>Alertes actives</p>
              <span className="w-5 h-5 rounded-full text-white text-[10px] font-bold flex items-center justify-center shrink-0" style={{ background: '#F0A600' }}>
                {ALERTS.length + kpi.pending_review}
              </span>
            </div>
            <div className="space-y-1.5">
              {ALERTS.map(a => (
                <div key={a.text} className="flex items-start gap-1.5 px-2.5 py-2 rounded-md border-l-4 text-xs" style={{ background: a.bg, borderColor: a.border, color: '#1A1A2E' }}>
                  <AlertTriangle size={11} className="shrink-0 mt-0.5" style={{ color: a.border }} />
                  {a.text}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Expenses + Recent */}
        <div className="grid grid-cols-[1fr_300px] gap-4">
          <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5' }}>
            <p className="font-semibold text-sm mb-4" style={{ color: '#1A1A2E' }}>Dépenses par catégorie — 2026</p>
            <div className="space-y-3">
              {budgetLines.map((line, i) => (
                <div key={line.catalog_id}>
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs" style={{ color: '#5D6D7E' }}>{line.label}</span>
                    <span className="text-xs font-medium" style={{ color: '#1A1A2E' }}>{formatTND(line.actual_ytd, 0)}</span>
                  </div>
                  <div className="h-2 rounded-full overflow-hidden" style={{ background: '#E8EFF7' }}>
                    <div
                      className="h-2 rounded-full"
                      style={{
                        width: `${Math.min(100, (line.actual_ytd / maxBudget) * 100)}%`,
                        background: line.is_over ? '#C0391B' : BAR_COLORS[i % BAR_COLORS.length],
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
            <p className="font-semibold text-sm mb-3" style={{ color: '#1A1A2E' }}>Activité récente</p>
            <div className="space-y-3">
              {recent.map(inv => (
                <div key={inv.id} className="flex items-start gap-2.5">
                  <span className="w-2 h-2 rounded-full mt-1 shrink-0" style={{ background: inv.has_errors ? '#C0391B' : inv.human_review_required ? '#F0A600' : '#1D9E76' }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold truncate" style={{ color: '#1A1A2E' }}>{inv.issuer_name ?? '—'}</p>
                    <p className="text-[10px]" style={{ color: '#5D6D7E' }}>
                      {inv.amount_ttc != null ? formatTND(inv.amount_ttc, 0) : '—'}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <StatusChip status={inv.status} />
                    <p className="text-[10px] mt-0.5" style={{ color: '#5D6D7E' }}>{timeAgo(inv.received_at)}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
