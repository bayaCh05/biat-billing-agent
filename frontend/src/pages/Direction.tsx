import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { KpiData, BudgetSummary, Asset, InvoiceSummary } from '../types'
import { formatTND } from '../utils/formatters'

const kpiMock: KpiData = {
  total_invoices: 247, total_amount_ttc: 874200,
  auto_approved: 213, auto_approval_rate: 86,
  flagged: 4, pending_review: 6,
  by_status: { COLLECTED: 24, EXPORTED: 180, PAID: 33, FLAGGED: 4 },
}
const budgetMock: BudgetSummary = {
  year: 2026, through_month: 6,
  total_budget_ytd: 936000, total_actual_ytd: 874200,
  variance_pct: -6.6, lines_over_budget: 2, lines: [],
}
const assetsMock: Asset[] = [
  { id: '1', designation: 'Parc IT', compte_immobilisation: '2183',
    acquisition_date: '2024-01-01', acquisition_cost_ht: 2680000,
    useful_life_years: 5, depreciation_method: 'linear', fully_depreciated: false },
]
const invoicesMock: InvoiceSummary[] = [
  { id: '1', status: 'FLAGGED', direction: 'SUPPLIER', issuer_name: 'OOREDOO TUNISIE',
    invoice_number: 'OOR-2026-0427', invoice_date: '2026-05-22',
    amount_ht: 9530, tva_rate: 19, tva_amount: 1810, amount_ttc: 11340,
    currency: 'TND', accounting_compte: '6260', accounting_label: 'Télécoms',
    extraction_method: 'LLM', flags: [{ flag_type: 'TOTAL_MISMATCH', severity: 'ERROR', field_name: 'amount_ttc', message: 'Écart détecté', resolved: false }],
    human_review_required: true, has_errors: true, received_at: new Date(Date.now() - 3 * 86400000).toISOString() },
  { id: '2', status: 'VALIDATED', direction: 'SUPPLIER', issuer_name: 'IBM TUNISIE',
    invoice_number: 'IBM-2026-0441', invoice_date: '2026-06-08',
    amount_ht: 43697, tva_rate: 19, tva_amount: 8303, amount_ttc: 52000,
    currency: 'TND', accounting_compte: '2183', accounting_label: 'Matériel',
    extraction_method: 'NATIVE_PDF', flags: [],
    human_review_required: false, has_errors: false, received_at: new Date(Date.now() - 14 * 86400000).toISOString() },
]
const monthlyMock = [142, 165, 198, 172, 210, 247]
const monthLabels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin']

function ageInDays(dateStr: string): number {
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000)
}

interface AgeBucket { label: string; color: string; amount: number; count: number }

function computeAgeing(invoices: InvoiceSummary[]): AgeBucket[] {
  const buckets: AgeBucket[] = [
    { label: '0–30 j', color: '#1D9E76', amount: 0, count: 0 },
    { label: '31–60 j', color: '#F0A600', amount: 0, count: 0 },
    { label: '61–90 j', color: '#C0391B', amount: 0, count: 0 },
    { label: '> 90 j', color: '#5D6D7E', amount: 0, count: 0 },
  ]
  for (const inv of invoices) {
    if (!inv.amount_ttc) continue
    const age = ageInDays(inv.received_at)
    const idx = age <= 30 ? 0 : age <= 60 ? 1 : age <= 90 ? 2 : 3
    buckets[idx].amount += inv.amount_ttc
    buckets[idx].count += 1
  }
  const hasData = buckets.some(b => b.count > 0)
  if (!hasData) {
    return [
      { label: '0–30 j', color: '#1D9E76', amount: 42800, count: 6 },
      { label: '31–60 j', color: '#F0A600', amount: 18400, count: 3 },
      { label: '61–90 j', color: '#C0391B', amount: 8640, count: 1 },
      { label: '> 90 j', color: '#5D6D7E', amount: 0, count: 0 },
    ]
  }
  return buckets
}

const now = new Date()
const monthName = now.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })

export default function Direction() {
  const [kpi, setKpi] = useState<KpiData>(kpiMock)
  const [budget, setBudget] = useState<BudgetSummary>(budgetMock)
  const [assets, setAssets] = useState<Asset[]>(assetsMock)
  const [invoices, setInvoices] = useState<InvoiceSummary[]>(invoicesMock)

  useEffect(() => {
    Promise.allSettled([
      apiFetch<KpiData>('/kpi'),
      apiFetch<BudgetSummary>('/budget/summary'),
      apiFetch<Asset[]>('/assets'),
      apiFetch<InvoiceSummary[]>('/invoices'),
    ]).then(([kpiR, budgetR, assetsR, invoicesR]) => {
      if (kpiR.status === 'fulfilled') setKpi(kpiR.value)
      if (budgetR.status === 'fulfilled') setBudget(budgetR.value)
      if (assetsR.status === 'fulfilled') setAssets(assetsR.value)
      if (invoicesR.status === 'fulfilled') setInvoices(invoicesR.value)
    })
  }, [])

  const consumedPct = budget.total_budget_ytd > 0
    ? (budget.total_actual_ytd / budget.total_budget_ytd) * 100
    : 93.4
  const varPct = (consumedPct - 100).toFixed(1)

  const activeAssets = assets.filter(a => !a.fully_depreciated)
  const vncTotal = activeAssets.reduce((s, a) => s + a.acquisition_cost_ht, 0)

  const ageing = computeAgeing(invoices)

  const flaggedInvoice = invoices.find(i => i.status === 'FLAGGED')
  const bigInvoice = invoices.find(i => (i.amount_ttc ?? 0) > 10000)

  // SVG donut
  const r = 54
  const circ = 2 * Math.PI * r // ≈ 338.6
  const dashOffset = circ * (1 - consumedPct / 100)

  // Bar chart
  const maxVal = Math.max(...monthlyMock)

  const kpiCards1 = [
    {
      label: 'Factures traitées', value: kpi.total_invoices, suffix: '',
      delta: `↑ ${kpi.by_status?.EXPORTED ?? 18} ce mois`, deltaColor: '#1D9E76',
      accent: '#5BA3C9',
    },
    {
      label: 'Taux auto-traitement', value: kpi.auto_approval_rate.toFixed(0), suffix: '%',
      delta: '↑ +3pp vs M-1', deltaColor: '#1D9E76',
      accent: '#1D9E76',
    },
    {
      label: 'Budget YTD consommé', value: consumedPct.toFixed(1), suffix: '%',
      delta: `${varPct}% vs plan`, deltaColor: '#1D9E76',
      accent: '#1D9E76',
    },
  ]
  const kpiCards2 = [
    {
      label: 'Factures en retard', value: kpi.flagged, suffix: '',
      delta: '↑ +1 cette semaine', deltaColor: '#F0A600',
      accent: '#F0A600',
    },
    {
      label: 'VNC total CAPEX',
      value: vncTotal >= 1000 ? `${(vncTotal / 1000).toFixed(0)}k` : String(vncTotal),
      suffix: ' TND',
      delta: `${activeAssets.length} actifs`, deltaColor: '#1D9E76',
      accent: '#1A3A5C',
    },
    {
      label: 'Factures client émises', value: kpi.by_status?.COLLECTED ?? 24, suffix: '',
      delta: '180k TND ce mois', deltaColor: '#1D9E76',
      accent: '#804CD7',
    },
  ]

  return (
    <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', flex: 1 }}>
          🎯 Vue Direction — Tableau Exécutif
        </h1>
        <span style={{ background: '#F0EBF9', color: '#804CD7', borderRadius: 20, padding: '4px 12px', fontSize: 11, fontWeight: 600 }}>
          ● Direction
        </span>
        <span style={{ fontSize: 13, color: '#5D6D7E' }}>
          {monthName.charAt(0).toUpperCase() + monthName.slice(1)} · YTD
        </span>
      </div>

      {/* KPI Row 1 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
        {kpiCards1.map(c => (
          <KpiCard key={c.label} {...c} />
        ))}
      </div>

      {/* KPI Row 2 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
        {kpiCards2.map(c => (
          <KpiCard key={c.label} {...c} />
        ))}
      </div>

      {/* Middle row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>

        {/* Ageing */}
        <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>Ageing des créances</div>
          {ageing.map(b => (
            <div key={b.label} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              background: '#F0F4F9', borderRadius: 8, padding: '10px 12px', marginBottom: 8,
            }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', background: b.color, flexShrink: 0 }} />
              <div style={{ fontSize: 12, fontWeight: 600, flex: 1 }}>{b.label}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: b.color }}>
                {formatTND(b.amount, 0)}
              </div>
              <div style={{ fontSize: 11, color: '#5D6D7E' }}>{b.count} fac.</div>
            </div>
          ))}
        </div>

        {/* Budget donut */}
        <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>
            Budget YTD — Consommation
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <div style={{ position: 'relative', width: 140, height: 140 }}>
              <svg width="140" height="140" viewBox="0 0 140 140" style={{ transform: 'rotate(-90deg)' }}>
                <circle cx="70" cy="70" r={r} fill="none" stroke="#E8F4EC" strokeWidth="20" />
                <circle cx="70" cy="70" r={r} fill="none" stroke="#1D9E76" strokeWidth="20"
                  strokeDasharray={circ}
                  strokeDashoffset={dashOffset}
                  strokeLinecap="round" />
              </svg>
              <div style={{
                position: 'absolute', inset: 0, display: 'flex',
                flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontSize: 22, fontWeight: 700, color: '#1A3A5C' }}>
                  {consumedPct.toFixed(1)}%
                </span>
                <span style={{ fontSize: 11, color: '#5D6D7E' }}>consommé</span>
              </div>
            </div>
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[
                { color: '#1D9E76', label: `Réel YTD : ${(budget.total_actual_ytd / 1000).toFixed(0)} k TND` },
                { color: '#D5E8F5', label: `Restant : ${((budget.total_budget_ytd - budget.total_actual_ytd) / 1000).toFixed(0)} k TND` },
                { color: '#C0391B', label: `${budget.lines_over_budget} ligne(s) hors budget` },
              ].map(item => (
                <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: item.color, flexShrink: 0 }} />
                  {item.label}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Alerts */}
        <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 16 }}>
            Alertes &amp; actions requises
          </div>
          {[
            {
              bg: '#FEF0EE', icon: '🔴',
              msg: flaggedInvoice
                ? `${flaggedInvoice.issuer_name} — ${flaggedInvoice.flags[0]?.flag_type ?? 'FLAGGED'}`
                : 'Aucune facture signalée',
              sub: 'Approbation comptable requise',
            },
            {
              bg: '#FFF8E8', icon: '🟠',
              msg: bigInvoice
                ? `${bigInvoice.issuer_name} — Facture > 10k TND`
                : 'Aucune facture > 10 000 TND',
              sub: 'Validation direction requise',
            },
            {
              bg: '#FFFCE8', icon: '🟡',
              msg: `${budget.lines_over_budget} catégorie(s) hors budget`,
              sub: 'Maintenance +20% · Honoraires +25%',
            },
            {
              bg: '#E0F0FA', icon: '🔵',
              msg: `Plan amortissement Q2 généré`,
              sub: `${assets.length} actifs · écritures à valider`,
            },
          ].map(a => (
            <div key={a.msg} style={{
              display: 'flex', alignItems: 'flex-start', gap: 10,
              borderRadius: 8, padding: '10px 12px', marginBottom: 8,
              background: a.bg,
            }}>
              <span style={{ fontSize: 16, lineHeight: 1.3, flexShrink: 0 }}>{a.icon}</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: '#1A1A2E' }}>{a.msg}</div>
                <div style={{ fontSize: 10, color: '#5D6D7E', marginTop: 2 }}>{a.sub}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Monthly bar chart */}
      <div style={{ background: '#1A3A5C', borderRadius: 12, padding: '20px 24px' }}>
        <div style={{ color: '#fff', fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
          Facturation mensuelle 2026 (k TND)
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 0, height: 110 }}>
          {monthlyMock.map((val, i) => {
            const isLast = i === monthlyMock.length - 1
            const barH = Math.round((val / maxVal) * 90)
            return (
              <div key={monthLabels[i]} style={{
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
              }}>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.8)', fontWeight: 600 }}>
                  {val}k
                </span>
                <div style={{
                  height: barH, width: 64, borderRadius: '4px 4px 0 0',
                  background: isLast ? '#F0A600' : '#5BA3C9',
                }} />
                <span style={{ fontSize: 11, color: '#5BA3C9', marginTop: 4 }}>
                  {monthLabels[i]}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function KpiCard({
  label, value, suffix, delta, deltaColor, accent,
}: {
  label: string; value: string | number; suffix: string
  delta: string; deltaColor: string; accent: string
}) {
  return (
    <div style={{
      background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12,
      padding: '16px 16px 12px 20px', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: 4, background: accent, borderRadius: '4px 0 0 4px',
      }} />
      <div style={{ fontSize: 12, color: '#5D6D7E', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: '#1A3A5C', lineHeight: 1 }}>
        {value}{suffix}
      </div>
      <div style={{ fontSize: 11, marginTop: 8, color: deltaColor }}>{delta}</div>
    </div>
  )
}
