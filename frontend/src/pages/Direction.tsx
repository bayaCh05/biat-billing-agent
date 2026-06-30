import { useEffect, useState, useCallback } from 'react'
import {
  AreaChart, Area, BarChart, Bar,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type {
  KpiData, BudgetSummary, Asset,
  MonthlySpendItem, SupplierSpendItem, AccountSpendItem, AnalyticsKPIs,
} from '../types'
import { formatTND } from '../utils/formatters'
import {
  getKpi, getBudgetSummary, listAssets,
  getMonthlySpend, getBySupplier, getByAccount, getAnalyticsKPIs,
} from '../api/endpoints'
import { RefreshCw } from 'lucide-react'

const MONTH_SHORT = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']

const PIE_COLORS = ['#2E86C1', '#1D9E76', '#F0A500', '#804CD7', '#C0391B', '#5D6D7E', '#1ABC9C', '#E67E22']

// ── Skeleton ──────────────────────────────────────────────────────────────────

function Skeleton({ h = 'h-4', w = 'w-full', cls = '' }: { h?: string; w?: string; cls?: string }) {
  return <div className={`animate-pulse bg-gray-200 rounded ${h} ${w} ${cls}`} />
}

function ChartSkeleton() {
  return (
    <div className="flex flex-col gap-2 p-4">
      <Skeleton h="h-3" w="w-1/3" />
      <div className="flex items-end gap-2 h-40 mt-2">
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} className="flex-1 bg-gray-200 animate-pulse rounded-t" style={{ height: `${30 + Math.random() * 70}%` }} />
        ))}
      </div>
    </div>
  )
}

// ── Tooltip formatters ────────────────────────────────────────────────────────

function TndTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; fill: string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-xs">
      <p className="font-semibold text-gray-700 mb-1">{label}</p>
      {payload.map(p => (
        <p key={p.name} style={{ color: p.fill }}>
          {p.name}: {formatTND(p.value)}
        </p>
      ))}
    </div>
  )
}

// ── KPI card ─────────────────────────────────────────────────────────────────

function KpiCard({ label, value, suffix, delta, color, loading }: {
  label: string; value: string | number; suffix?: string
  delta?: string; color: string; loading?: boolean
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-5 py-4 relative overflow-hidden shadow-sm">
      <div className="absolute left-0 top-0 bottom-0 w-1 rounded-l-xl" style={{ background: color }} />
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      {loading ? (
        <Skeleton h="h-7" w="w-24" cls="mt-1" />
      ) : (
        <p className="text-2xl font-bold" style={{ color: '#1A3A5C' }}>
          {value}{suffix}
        </p>
      )}
      {delta && !loading && <p className="text-xs mt-1.5" style={{ color }}>{delta}</p>}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Direction() {
  const now = new Date()
  const year = now.getFullYear()

  // Analytics data
  const [monthly, setMonthly]     = useState<MonthlySpendItem[]>([])
  const [suppliers, setSuppliers] = useState<SupplierSpendItem[]>([])
  const [accounts, setAccounts]   = useState<AccountSpendItem[]>([])
  const [kpis, setKpis]           = useState<AnalyticsKPIs | null>(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(true)

  // Existing overview data
  const [kpi, setKpi]         = useState<KpiData | null>(null)
  const [budget, setBudget]   = useState<BudgetSummary | null>(null)
  const [assets, setAssets]   = useState<Asset[]>([])
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(now)

  const loadAnalytics = useCallback(async () => {
    setAnalyticsLoading(true)
    try {
      const [m, s, a, k] = await Promise.all([
        getMonthlySpend(year),
        getBySupplier(year),
        getByAccount(year),
        getAnalyticsKPIs(year),
      ])
      setMonthly(m)
      setSuppliers(s)
      setAccounts(a)
      setKpis(k)
    } finally {
      setAnalyticsLoading(false)
    }
  }, [year])

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true)
    try {
      const [k, b, a] = await Promise.all([
        getKpi(),
        getBudgetSummary(),
        listAssets(),
      ])
      setKpi(k)
      setBudget(b)
      setAssets(a)
    } finally {
      setOverviewLoading(false)
    }
  }, [])

  const refresh = useCallback(() => {
    setLastRefresh(new Date())
    loadAnalytics()
    loadOverview()
  }, [loadAnalytics, loadOverview])

  useEffect(() => {
    loadAnalytics()
    loadOverview()
  }, [loadAnalytics, loadOverview])

  // Derived
  const consumedPct = (budget?.total_budget_ytd ?? 0) > 0
    ? (budget!.total_actual_ytd / budget!.total_budget_ytd) * 100
    : 0
  const activeAssets = assets.filter(a => !a.fully_depreciated)

  // Chart data: monthly spend with short labels
  const monthlyChart = monthly.map((m, i) => ({
    name: MONTH_SHORT[i],
    OPEX: m.opex,
    CAPEX: m.capex,
    Total: m.total_ht,
  }))

  // Supplier chart: truncate long names
  const supplierChart = suppliers.map(s => ({
    name: s.supplier.length > 22 ? s.supplier.slice(0, 20) + '…' : s.supplier,
    'Montant TTC': s.total_ttc,
  }))

  // Pie chart: top 6 accounts + other
  const pieData = accounts.slice(0, 7).map(a => ({
    name: `${a.compte} ${a.label.slice(0, 18)}`,
    value: a.total_ht,
    pct: a.pct,
  }))

  // SVG donut params
  const r = 54, circ = 2 * Math.PI * r
  const dashOffset = circ * (1 - Math.min(consumedPct, 100) / 100)

  return (
    <div className="p-6 max-w-[1400px] mx-auto flex flex-col gap-5">

      {/* Header */}
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-lg font-bold text-gray-900">Vue Direction — Tableau Exécutif {year}</h1>
          <p className="text-xs text-gray-400">Actualisé à {lastRefresh.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</p>
        </div>
        <span className="ml-auto text-[11px] font-semibold bg-purple-50 text-purple-700 rounded-full px-3 py-1">● Direction</span>
        <button
          onClick={refresh}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 hover:bg-gray-50 text-gray-600"
        >
          <RefreshCw className={`w-3 h-3 ${analyticsLoading || overviewLoading ? 'animate-spin' : ''}`} />
          Actualiser
        </button>
      </div>

      {/* ── Analytics KPI cards ────────────────────────────────────────────── */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard
          label="Délai moyen de traitement"
          value={analyticsLoading ? '—' : (kpis?.avg_processing_days.toFixed(1) ?? '—')}
          suffix=" j"
          delta={kpis ? (kpis.avg_processing_days < 3 ? '✓ Dans les normes' : '⚠ Au-dessus de 3j') : undefined}
          color="#2E86C1"
          loading={analyticsLoading}
        />
        <KpiCard
          label="Taux de rejet"
          value={analyticsLoading ? '—' : (kpis?.rejection_rate.toFixed(1) ?? '—')}
          suffix="%"
          delta={kpis ? (kpis.rejection_rate < 10 ? '✓ Taux acceptable' : '⚠ Revoir le flux') : undefined}
          color="#C0391B"
          loading={analyticsLoading}
        />
        <KpiCard
          label="Révision humaine"
          value={analyticsLoading ? '—' : (kpis?.human_review_rate.toFixed(1) ?? '—')}
          suffix="%"
          delta={kpis ? `${kpis.pending_count} facture(s) en attente` : undefined}
          color="#F0A500"
          loading={analyticsLoading}
        />
        <KpiCard
          label="CAPEX YTD"
          value={analyticsLoading ? '—' : formatTND(kpis?.total_capex_ytd ?? 0, 0)}
          delta={kpis ? `OPEX: ${formatTND(kpis.total_opex_ytd, 0)}` : undefined}
          color="#1D9E76"
          loading={analyticsLoading}
        />
      </div>

      {/* ── Monthly spend area chart ──────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-800">Dépenses mensuelles {year}</h2>
            <p className="text-xs text-gray-400">Factures fournisseurs traitées — ventilation OPEX / CAPEX</p>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#2E86C1] inline-block" />OPEX</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-[#F0A500] inline-block" />CAPEX</span>
          </div>
        </div>
        {analyticsLoading ? <ChartSkeleton /> : (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={monthlyChart} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradOpex" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2E86C1" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#2E86C1" stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gradCapex" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#F0A500" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#F0A500" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#F0F4F9" />
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#8898A9' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#8898A9' }} axisLine={false} tickLine={false}
                tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
              <Tooltip content={<TndTooltip />} />
              <Area type="monotone" dataKey="OPEX" stroke="#2E86C1" strokeWidth={2}
                fill="url(#gradOpex)" dot={false} activeDot={{ r: 4 }} />
              <Area type="monotone" dataKey="CAPEX" stroke="#F0A500" strokeWidth={2}
                fill="url(#gradCapex)" dot={false} activeDot={{ r: 4 }} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Suppliers bar + PCE pie ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-5">

        {/* Top 10 suppliers — horizontal bar */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-1">Top fournisseurs {year}</h2>
          <p className="text-xs text-gray-400 mb-4">Par montant TTC total traité</p>
          {analyticsLoading ? <ChartSkeleton /> : supplierChart.length === 0 ? (
            <p className="text-xs text-gray-400 py-8 text-center">Aucune donnée</p>
          ) : (
            <ResponsiveContainer width="100%" height={supplierChart.length * 36 + 20}>
              <BarChart layout="vertical" data={supplierChart} margin={{ top: 0, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#F0F4F9" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#8898A9' }} axisLine={false} tickLine={false}
                  tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
                <YAxis type="category" dataKey="name" width={148}
                  tick={{ fontSize: 10, fill: '#374151' }} axisLine={false} tickLine={false} />
                <Tooltip
                  formatter={(v) => [formatTND(v as number), 'Total TTC']}
                  contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #E5E7EB' }}
                />
                <Bar dataKey="Montant TTC" fill="#2E86C1" radius={[0, 4, 4, 0]} maxBarSize={20} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* PCE account distribution — pie */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-1">Répartition par compte PCE</h2>
          <p className="text-xs text-gray-400 mb-4">Distribution des charges par plan comptable</p>
          {analyticsLoading ? <ChartSkeleton /> : pieData.length === 0 ? (
            <p className="text-xs text-gray-400 py-8 text-center">Aucune donnée</p>
          ) : (
            <div className="flex items-center gap-4">
              <ResponsiveContainer width="55%" height={200}>
                <PieChart>
                  <Pie
                    data={pieData} cx="50%" cy="50%"
                    innerRadius={52} outerRadius={80}
                    dataKey="value" paddingAngle={2}
                  >
                    {pieData.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v, _name, props) => [
                      `${formatTND(v as number)} (${(props as { payload?: { pct?: number } }).payload?.pct ?? 0}%)`,
                      'HT',
                    ]}
                    contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid #E5E7EB' }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex-1 flex flex-col gap-1.5">
                {pieData.map((d, i) => (
                  <div key={d.name} className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                    <span className="text-[11px] text-gray-600 truncate flex-1">{d.name}</span>
                    <span className="text-[11px] font-semibold text-gray-700">{d.pct}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Overview row: ageing · budget · alerts ────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">

        {/* Budget donut */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">Budget YTD — Consommation</h2>
          {overviewLoading ? <Skeleton h="h-36" /> : (
            <div className="flex flex-col items-center gap-3">
              <div className="relative w-32 h-32">
                <svg width="128" height="128" viewBox="0 0 140 140" style={{ transform: 'rotate(-90deg)' }}>
                  <circle cx="70" cy="70" r={r} fill="none" stroke="#E8F4EC" strokeWidth="18" />
                  <circle cx="70" cy="70" r={r} fill="none" stroke="#1D9E76" strokeWidth="18"
                    strokeDasharray={circ} strokeDashoffset={dashOffset} strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-xl font-bold text-gray-900">{consumedPct.toFixed(1)}%</span>
                  <span className="text-[10px] text-gray-400">consommé</span>
                </div>
              </div>
              <div className="w-full text-xs flex flex-col gap-1.5">
                {[
                  { color: '#1D9E76', text: `Réel YTD : ${formatTND(budget?.total_actual_ytd ?? 0, 0)}` },
                  { color: '#D5E8F5', text: `Restant : ${formatTND((budget?.total_budget_ytd ?? 0) - (budget?.total_actual_ytd ?? 0), 0)}` },
                  { color: '#C0391B', text: `${budget?.lines_over_budget ?? 0} ligne(s) hors budget` },
                ].map(item => (
                  <div key={item.text} className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: item.color }} />
                    <span className="text-gray-600">{item.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Existing KPI summary */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">Métriques pipeline</h2>
          {overviewLoading ? <div className="flex flex-col gap-3"><Skeleton h="h-5" /><Skeleton h="h-5" /><Skeleton h="h-5" /><Skeleton h="h-5" /></div> : (
            <div className="flex flex-col gap-3">
              {[
                { label: 'Factures traitées', value: String(kpi?.total_invoices ?? 0), color: '#2E86C1' },
                { label: 'Taux auto-approbation', value: `${kpi?.auto_approval_rate ?? 0}%`, color: '#1D9E76' },
                { label: 'Signalées (FLAGGED)', value: String(kpi?.flagged ?? 0), color: '#F0A500' },
                { label: 'Actifs CAPEX actifs', value: String(activeAssets.length), color: '#804CD7' },
              ].map(row => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs text-gray-500">{row.label}</span>
                  <span className="text-sm font-bold" style={{ color: row.color }}>{row.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Asset summary */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-800 mb-4">Immobilisations CAPEX</h2>
          {overviewLoading ? <div className="flex flex-col gap-3"><Skeleton h="h-16" /><Skeleton h="h-16" /></div> : (
            <div className="flex flex-col gap-2">
              {[
                { label: 'Actifs en service', count: assets.filter(a => !a.fully_depreciated).length, bg: '#E8F5F0', color: '#1D9E76' },
                { label: 'Entièrement amortis', count: assets.filter(a => a.fully_depreciated).length, bg: '#EFF4FA', color: '#5BA3C9' },
                { label: 'Total actifs', count: assets.length, bg: '#F0F4F9', color: '#1A3A5C' },
              ].map(s => (
                <div key={s.label} className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: s.bg }}>
                  <span className="text-xs font-medium" style={{ color: s.color }}>{s.label}</span>
                  <span className="text-lg font-bold" style={{ color: s.color }}>{s.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
