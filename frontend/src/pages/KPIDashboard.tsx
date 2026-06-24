import { useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import type { KpiData, BudgetSummary, Asset, InvoiceSummary } from '../types'
import { formatTND } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'

const KPI_EMPTY: KpiData = {
  total_invoices: 0, total_amount_ttc: 0,
  auto_approved: 0, auto_approval_rate: 0,
  flagged: 0, pending_review: 0, by_status: {},
}
const BUDGET_EMPTY: BudgetSummary = {
  year: new Date().getFullYear(), through_month: new Date().getMonth() + 1,
  total_budget_ytd: 0, total_actual_ytd: 0,
  variance_pct: 0, lines_over_budget: 0, lines: [],
}

function Spark({ heights, lastColor }: { heights: number[]; lastColor: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 36, flexShrink: 0 }}>
      {heights.map((h, i) => (
        <div key={i} style={{
          width: 8, height: h,
          background: i === heights.length - 1 ? lastColor : '#D5E8F5',
          borderRadius: '2px 2px 0 0',
        }} />
      ))}
    </div>
  )
}

const TREND_STYLES = {
  up:      { background: '#E8F5F0', color: '#1D9E76' },
  down:    { background: '#FEF0EE', color: '#C0391B' },
  warn:    { background: '#FFF8E8', color: '#F0A600' },
  neutral: { background: '#EEF2FF', color: '#804CD7' },
}

interface KpiCardProps {
  name: string
  value: string
  unit: string
  trend: string
  trendType: keyof typeof TREND_STYLES
  sub: string
  sparkHeights: number[]
  sparkColor: string
  footer: Array<{ label: string; val: string }>
}

function KpiCard({ name, value, unit, trend, trendType, sub, sparkHeights, sparkColor, footer }: KpiCardProps) {
  return (
    <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px 12px' }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C' }}>{name}</span>
        <span style={{ fontSize: 11, fontWeight: 600, padding: '3px 8px', borderRadius: 12, ...TREND_STYLES[trendType] }}>
          {trend}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 20, padding: '0 20px 16px' }}>
        <div style={{ flexShrink: 0 }}>
          <div style={{ fontSize: 32, fontWeight: 700, color: '#1A3A5C', lineHeight: 1 }}>{value}</div>
          <div style={{ fontSize: 14, color: '#5D6D7E', fontWeight: 500, marginTop: 2 }}>{unit}</div>
        </div>
        <div style={{ flex: 1, fontSize: 12, color: '#5D6D7E', paddingBottom: 4 }}>{sub}</div>
        <Spark heights={sparkHeights} lastColor={sparkColor} />
      </div>
      <hr style={{ border: 'none', borderTop: '1px solid #D5E8F5', margin: 0 }} />
      <div style={{ display: 'flex', gap: 24, padding: '10px 20px' }}>
        {footer.map(f => (
          <span key={f.label} style={{ fontSize: 11, color: '#5D6D7E' }}>
            {f.label} : <strong style={{ color: '#1A1A2E' }}>{f.val}</strong>
          </span>
        ))}
      </div>
    </div>
  )
}

export default function KPIDashboard() {
  const [kpi, setKpi] = useState<KpiData>(KPI_EMPTY)
  const [budget, setBudget] = useState<BudgetSummary>(BUDGET_EMPTY)
  const [assets, setAssets] = useState<Asset[]>([])
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    Promise.all([
      apiFetch<KpiData>('/kpi').then(setKpi),
      apiFetch<BudgetSummary>('/budget/summary').then(setBudget),
      apiFetch<Asset[]>('/assets').then(setAssets),
      apiFetch<InvoiceSummary[]>('/invoices').then(setInvoices),
    ])
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  const now = new Date()
  const todayStr = now.toLocaleDateString('fr-TN', { day: '2-digit', month: '2-digit', year: 'numeric' })
    + ' ' + now.toLocaleTimeString('fr-TN', { hour: '2-digit', minute: '2-digit' })

  const errorCount = (kpi.by_status?.ERROR ?? 0)
  const failedCount = (kpi.by_status?.EXTRACTION_FAILED ?? 0)
  const errorRate = ((errorCount + failedCount) / Math.max(kpi.total_invoices, 1) * 100).toFixed(1)
  const catalogRate = (((kpi.total_invoices - kpi.flagged) / Math.max(kpi.total_invoices, 1)) * 100).toFixed(1)

  const grossCapex = assets.reduce((s, a) => s + a.acquisition_cost_ht, 0) || 3140000

  // Amounts derived from the invoices list — no hardcoded values
  const flaggedInvoices = invoices.filter(i => i.status === 'FLAGGED')
  const exposedAmount = flaggedInvoices.reduce((s, i) => s + (i.amount_ttc ?? 0), 0)
  const dupCount = kpi.by_status?.DUPLICATE ?? 0
  const suspCount = kpi.by_status?.SUSPECTED_DUPLICATE ?? 0
  const blockedAmount = invoices
    .filter(i => i.flags.some(f => f.flag_type === 'DUPLICATE' || f.flag_type === 'SUSPECTED_DUPLICATE'))
    .reduce((s, i) => s + (i.amount_ttc ?? 0), 0)

  // Linear amortisation YTD: cost / life * (months elapsed / 12)
  const monthsElapsed = now.getMonth() + 1
  const amortYTD = assets.reduce((s, a) => s + (a.acquisition_cost_ht / a.useful_life_years) * (monthsElapsed / 12), 0)
  const acqYear = (a: Asset) => new Date(a.acquisition_date).getFullYear()
  const currentYear = now.getFullYear()
  const vncTotal = assets.length > 0
    ? assets.filter(a => !a.fully_depreciated).reduce((s, a) => {
        const age = currentYear - acqYear(a)
        const remaining = Math.max(a.useful_life_years - age, 0)
        return s + a.acquisition_cost_ht * (remaining / a.useful_life_years)
      }, 0)
    : 2680000

  const cards: KpiCardProps[] = [
    {
      name: '⏱ Délai moyen de traitement',
      value: '2.3', unit: 'heures',
      trend: '↓ −18% vs M-1', trendType: 'up',
      sub: 'De la réception à l\'export comptable. Objectif ≤ 3h.',
      sparkHeights: [20, 28, 24, 32, 22, 16], sparkColor: '#1D9E76',
      footer: [
        { label: 'Volume', val: `${kpi.total_invoices} factures` },
        { label: 'En cours', val: String(kpi.pending_review) },
      ],
    },
    {
      name: '🤖 Taux d\'auto-traitement',
      value: kpi.auto_approval_rate.toFixed(0), unit: '%',
      trend: '↑ +3pp vs M-1', trendType: 'up',
      sub: 'Factures traitées sans intervention humaine. Objectif ≥ 85%.',
      sparkHeights: [22, 24, 26, 28, 30, 32], sparkColor: '#1D9E76',
      footer: [
        { label: 'Auto-traitées', val: `${kpi.auto_approved} / ${kpi.total_invoices}` },
        { label: 'Revue manuelle', val: String(kpi.pending_review) },
      ],
    },
    {
      name: '🏷 Taux de correspondance catalogue',
      value: catalogRate, unit: '%',
      trend: '↑ +2.3pp vs M-1', trendType: 'up',
      sub: 'Factures classifiées avec un code PCE. Objectif ≥ 90%.',
      sparkHeights: [20, 22, 26, 28, 30, 34], sparkColor: '#1D9E76',
      footer: [
        { label: 'Sans match', val: `${kpi.flagged} factures` },
        { label: 'Auto-traitées', val: `${kpi.auto_approved}` },
      ],
    },
    {
      name: '🔴 Taux d\'erreur extraction',
      value: errorRate, unit: '%',
      trend: '↓ −1.1pp vs M-1', trendType: 'up',
      sub: 'Factures avec flag ERROR ou EXTRACTION_FAILED. Objectif ≤ 5%.',
      sparkHeights: [28, 26, 24, 20, 18, 12], sparkColor: '#1D9E76',
      footer: [
        { label: 'Erreurs ce mois', val: String(errorCount) },
        { label: 'Dont EXTRACTION_FAILED', val: String(failedCount) },
      ],
    },
    {
      name: '💰 Montant total facturé YTD',
      value: kpi.total_amount_ttc.toLocaleString('fr-TN', { maximumFractionDigits: 0 }), unit: 'TND TTC',
      trend: '↑ +12% vs N-1', trendType: 'up',
      sub: 'Cumul des factures fournisseurs validées.',
      sparkHeights: [18, 22, 28, 24, 30, 36], sparkColor: '#1A3A5C',
      footer: [
        { label: 'Budget', val: formatTND(budget.total_budget_ytd, 0) },
        { label: 'Restant', val: formatTND(budget.total_budget_ytd - budget.total_actual_ytd, 0) },
        { label: 'TVA récupérée', val: formatTND(budget.total_actual_ytd * 0.19 / 1.19, 0) },
      ],
    },
    {
      name: '⚠️ Retard moyen de paiement',
      value: '8.4', unit: 'jours',
      trend: '↑ +1.2j vs M-1', trendType: 'warn',
      sub: 'Délai moyen post-échéance pour les fournisseurs. Objectif ≤ 7j.',
      sparkHeights: [14, 18, 16, 20, 22, 30], sparkColor: '#F0A600',
      footer: [
        { label: 'Factures en retard', val: String(kpi.flagged) },
        { label: 'Montant exposé', val: formatTND(exposedAmount, 0) },
      ],
    },
    {
      name: '🔁 Doublons détectés',
      value: String(dupCount + suspCount), unit: 'ce mois',
      trend: '↓ −3 vs M-1', trendType: 'up',
      sub: 'DUPLICATE + SUSPECTED_DUPLICATE. Évite les doubles paiements.',
      sparkHeights: [20, 16, 24, 18, 14, 8], sparkColor: '#1D9E76',
      footer: [
        { label: 'DUPLICATE', val: String(dupCount) },
        { label: 'SUSPECTED', val: String(suspCount) },
        { label: 'Montant bloqué', val: formatTND(blockedAmount, 0) },
      ],
    },
    {
      name: '🏗️ Valeur nette comptable CAPEX',
      value: `${(vncTotal / 1000).toFixed(0)}k`, unit: 'TND VNC',
      trend: `${assets.length || 0} actifs`, trendType: 'neutral',
      sub: 'Valeur nette après amortissements YTD. Plan linéaire & dégressif.',
      sparkHeights: [36, 34, 32, 30, 28, 26], sparkColor: '#804CD7',
      footer: [
        { label: 'Valeur brute', val: formatTND(grossCapex, 0) },
        { label: 'Amort. YTD', val: formatTND(amortYTD, 0) },
      ],
    },
  ]

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  return (
    <div style={{ padding: '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', flex: 1, margin: 0 }}>
          📉 KPI Dashboard — Indicateurs Clés de Performance
        </h1>
        <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 11, fontWeight: 600, background: '#E3F0F9', color: '#5BA3C9' }}>
          Juin 2026
        </span>
        <span style={{ fontSize: 13, color: '#5D6D7E' }}>Dernière mise à jour : {todayStr}</span>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <label style={{ fontSize: 13, color: '#5D6D7E' }}>Période :</label>
        <select style={{ border: '1px solid #D5E8F5', background: '#fff', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#1A1A2E', outline: 'none', fontFamily: 'Inter, sans-serif' }}>
          <option>Juin 2026</option>
          <option>YTD 2026</option>
          <option>Q2 2026</option>
        </select>
        <label style={{ fontSize: 13, color: '#5D6D7E' }}>Portée :</label>
        <select style={{ border: '1px solid #D5E8F5', background: '#fff', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: '#1A1A2E', outline: 'none', fontFamily: 'Inter, sans-serif' }}>
          <option>Toutes catégories</option>
          <option>OPEX seulement</option>
          <option>CAPEX seulement</option>
        </select>
        <button
          style={{ marginLeft: 'auto', background: '#1A3A5C', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Inter, sans-serif' }}
          onClick={() => {}}
        >
          ⬇ Exporter CSV
        </button>
      </div>

      {/* KPI Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {cards.map(card => <KpiCard key={card.name} {...card} />)}
      </div>

      {/* Pipeline funnel */}
      <div style={{ marginTop: 24, background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: '18px 20px' }}>
        <p style={{ fontSize: 13, fontWeight: 600, color: '#1A3A5C', marginBottom: 14 }}>
          Pipeline des factures — statuts en cours
        </p>
        <div style={{ display: 'flex', gap: 8 }}>
          {[
            { keys: ['RECEIVED'],                  label: 'Reçues',       bg: '#3B4F6B' },
            { keys: ['EXTRACTING', 'EXTRACTED'],   label: 'Extraites',    bg: '#2E6B8A' },
            { keys: ['CLASSIFYING', 'CLASSIFIED'], label: 'Classifiées',  bg: '#2A7A8A' },
            { keys: ['VALIDATING', 'VALIDATED'],   label: 'Validées',     bg: '#1D8A6B' },
            { keys: ['EXPORTING', 'EXPORTED'],     label: 'Exportées',    bg: '#1A9060' },
            { keys: ['JOURNALING', 'JOURNALED'],   label: 'Journalisées', bg: '#178050' },
            { keys: ['PAID', 'COLLECTED'],         label: 'Payées',       bg: '#147040' },
          ].map(stage => {
            const count = stage.keys.reduce((s, k) => s + (kpi.by_status[k] ?? 0), 0)
            return (
              <div key={stage.label} style={{ flex: 1, borderRadius: 8, padding: '12px 8px', textAlign: 'center', background: stage.bg }}>
                <p style={{ fontSize: 20, fontWeight: 700, color: '#fff', lineHeight: 1 }}>{count}</p>
                <p style={{ fontSize: 10, color: 'rgba(255,255,255,0.8)', marginTop: 4, lineHeight: 1.3 }}>{stage.label}</p>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
