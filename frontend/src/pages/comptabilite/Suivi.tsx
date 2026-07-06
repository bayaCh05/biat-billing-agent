import { useState, useEffect } from 'react'
import { apiFetch } from '../../api/client'
import { formatTND, formatDate } from '../../utils/formatters'
import type { SuiviSnapshot, AgeingBucket, InvoiceSummary } from '../../types'
import PageSpinner from '../../components/ui/PageSpinner'

const SNAPSHOT_EMPTY: SuiviSnapshot = {
  total_payables: 0, total_receivables: 0,
  overdue_count: 0, pending_payment_count: 0, pending_collection_count: 0,
  payables_ageing:    { current: 0, count_current: 0, days_1_30: 0, count_1_30: 0, days_31_60: 0, count_31_60: 0, days_61_90: 0, count_61_90: 0, over_90: 0, count_over_90: 0 },
  receivables_ageing: { current: 0, count_current: 0, days_1_30: 0, count_1_30: 0, days_31_60: 0, count_31_60: 0, days_61_90: 0, count_61_90: 0, over_90: 0, count_over_90: 0 },
  pending_payment: [], pending_collection: [], overdue: [],
}

const AGEING_ROWS = [
  { key: 'current',  label: 'Courant',  amtKey: 'current'   as const, cntKey: 'count_current' as const, color: '#1D9E76' },
  { key: '1_30',     label: '1–30 j',   amtKey: 'days_1_30' as const, cntKey: 'count_1_30'    as const, color: '#5BA3C9' },
  { key: '31_60',    label: '31–60 j',  amtKey: 'days_31_60'as const, cntKey: 'count_31_60'   as const, color: '#F0A600' },
  { key: '61_90',    label: '61–90 j',  amtKey: 'days_61_90'as const, cntKey: 'count_61_90'   as const, color: '#C0391B' },
  { key: 'over_90',  label: '> 90 j',   amtKey: 'over_90'   as const, cntKey: 'count_over_90' as const, color: '#5D6D7E' },
]

function AgeingCard({ title, bucket }: { title: string; bucket: AgeingBucket }) {
  return (
    <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: 20, flex: 1 }}>
      <p style={{ fontSize: 14, fontWeight: 600, color: '#1A3A5C', marginBottom: 14 }}>{title}</p>
      {AGEING_ROWS.map(row => (
        <div key={row.key} style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#F0F4F9', borderRadius: 8, padding: '10px 12px', marginBottom: 8 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: row.color, flexShrink: 0 }} />
          <span style={{ fontSize: 12, fontWeight: 600, flex: 1, color: '#1A1A2E' }}>{row.label}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: row.color }}>{formatTND(bucket[row.amtKey])}</span>
          <span style={{ fontSize: 11, color: '#5D6D7E', marginLeft: 8 }}>{bucket[row.cntKey]} fac.</span>
        </div>
      ))}
    </div>
  )
}

function daysSince(dateStr: string): number {
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000)
}

const STATUS_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  EXPORTED:    { bg: '#E3F0F9', color: '#1A3A5C', label: 'Exportée' },
  JOURNALED:   { bg: '#E8F5F0', color: '#0D6E52', label: 'Journalisée' },
  PAID:        { bg: '#E8F5F0', color: '#1D9E76', label: 'Payée' },
  COLLECTED:   { bg: '#E8F5F0', color: '#1D9E76', label: 'Encaissée' },
  FLAGGED:     { bg: '#FEF0EE', color: '#C0391B', label: 'Signalée' },
  VALIDATED:   { bg: '#FFF8E8', color: '#F0A600', label: 'Validée' },
  REJECTED:    { bg: '#FDECEA', color: '#C0391B', label: 'Rejetée' },
  RECEIVED:    { bg: '#E3F0F9', color: '#1A3A5C', label: 'Reçue' },
  EXTRACTED:   { bg: '#E3F0F9', color: '#1A3A5C', label: 'Extraite' },
  CLASSIFIED:  { bg: '#E3F0F9', color: '#1A3A5C', label: 'Classifiée' },
}

function InvoiceTable({ rows }: { rows: InvoiceSummary[] }) {
  if (rows.length === 0) {
    return (
      <tr>
        <td colSpan={6} style={{ padding: '24px 16px', textAlign: 'center', color: '#5D6D7E', fontSize: 13 }}>
          Aucune facture
        </td>
      </tr>
    )
  }
  return (
    <>
      {rows.map(inv => {
        const st = STATUS_STYLE[inv.status] ?? { bg: '#F0F4F9', color: '#5D6D7E', label: inv.status }
        const days = daysSince(inv.received_at)
        return (
          <tr key={inv.id} style={{ borderBottom: '1px solid #F0F4F9' }}>
            <td style={{ padding: '10px 14px', fontFamily: 'monospace', fontSize: 12, color: '#1A3A5C' }}>{inv.invoice_number ?? '—'}</td>
            <td style={{ padding: '10px 14px', fontSize: 13, fontWeight: 500 }}>{inv.issuer_name ?? '—'}</td>
            <td style={{ padding: '10px 14px', fontSize: 12, color: '#5D6D7E' }}>{formatDate(inv.invoice_date)}</td>
            <td style={{ padding: '10px 14px', fontSize: 13, fontWeight: 600, textAlign: 'right' }}>{formatTND(inv.amount_ttc)}</td>
            <td style={{ padding: '10px 14px' }}>
              <span style={{ padding: '3px 8px', borderRadius: 8, fontSize: 11, fontWeight: 600, background: st.bg, color: st.color }}>{st.label}</span>
            </td>
            <td style={{ padding: '10px 14px', fontSize: 12, color: days > 60 ? '#C0391B' : days > 30 ? '#F0A600' : '#5D6D7E', fontWeight: days > 30 ? 600 : 400 }}>
              {days}j
            </td>
          </tr>
        )
      })}
    </>
  )
}

const TABS = [
  { key: 'payment',    label: 'Paiements fournisseurs', col: 'Fournisseur' },
  { key: 'collection', label: 'Collectes clients',      col: 'Client'      },
  { key: 'overdue',    label: 'En retard',              col: 'Tiers'       },
] as const

export default function Suivi() {
  const [snapshot, setSnapshot] = useState<SuiviSnapshot>(SNAPSHOT_EMPTY)
  const [tab, setTab] = useState<'payment' | 'collection' | 'overdue'>('payment')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const today = new Date()
  const monthLabel = today.toLocaleDateString('fr-TN', { month: 'long', year: 'numeric' })

  useEffect(() => {
    apiFetch<SuiviSnapshot>('/suivi/snapshot')
      .then(data => setSnapshot(data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  const kpis = [
    { label: 'Total à payer',       value: formatTND(snapshot.total_payables),       sub: 'Fournisseurs EXPORTED', color: '#C0391B' },
    { label: 'Total à encaisser',   value: formatTND(snapshot.total_receivables),     sub: 'Clients EXPORTED',      color: '#1D9E76' },
    { label: 'Factures en retard',  value: String(snapshot.overdue_count),            sub: 'Échéance dépassée',     color: '#F0A600' },
    { label: 'En attente paiement', value: String(snapshot.pending_payment_count),    sub: 'À régler',              color: '#1A3A5C' },
  ]

  const activeRows =
    tab === 'payment'    ? snapshot.pending_payment    :
    tab === 'collection' ? snapshot.pending_collection :
    snapshot.overdue

  const activeTab = TABS.find(t => t.key === tab)!

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  return (
    <div style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A3A5C', flex: 1 }}>💳 Suivi des Paiements &amp; Créances</h1>
        <span style={{ padding: '4px 12px', borderRadius: 20, fontSize: 11, fontWeight: 600, background: '#E3F0F9', color: '#5BA3C9', textTransform: 'capitalize' }}>{monthLabel}</span>
      </div>

      {/* KPI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
        {kpis.map(k => (
          <div key={k.label} style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, padding: '16px 20px', position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 4, background: k.color, borderRadius: '4px 0 0 4px' }} />
            <p style={{ fontSize: 12, color: '#5D6D7E', marginBottom: 6 }}>{k.label}</p>
            <p style={{ fontSize: 22, fontWeight: 700, color: k.color, lineHeight: 1 }}>{k.value}</p>
            <p style={{ fontSize: 11, color: '#5D6D7E', marginTop: 6 }}>{k.sub}</p>
          </div>
        ))}
      </div>

      {/* Ageing */}
      <div style={{ display: 'flex', gap: 16 }}>
        <AgeingCard title="Ageing Fournisseurs (à payer)"   bucket={snapshot.payables_ageing}    />
        <AgeingCard title="Ageing Clients (à encaisser)"    bucket={snapshot.receivables_ageing} />
      </div>

      {/* Tabs + Table */}
      <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 12, overflow: 'hidden' }}>
        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid #D5E8F5' }}>
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: '12px 20px', fontSize: 13, fontWeight: tab === t.key ? 600 : 400,
                color: tab === t.key ? '#1A3A5C' : '#5D6D7E',
                background: 'none', border: 'none', cursor: 'pointer',
                borderBottom: tab === t.key ? '2px solid #F0A600' : '2px solid transparent',
                transition: 'all .15s',
              }}
            >
              {t.label}
              <span style={{ marginLeft: 8, fontSize: 11, padding: '2px 7px', borderRadius: 10, background: tab === t.key ? '#E3F0F9' : '#F0F4F9', color: tab === t.key ? '#1A3A5C' : '#5D6D7E', fontWeight: 600 }}>
                {t.key === 'payment' ? snapshot.pending_payment_count : t.key === 'collection' ? snapshot.pending_collection_count : snapshot.overdue_count}
              </span>
            </button>
          ))}
        </div>

        {/* Table */}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#F0F4F9' }}>
              {['N° Facture', activeTab.col, 'Date', 'Montant TTC', 'Statut', 'Jours'].map(h => (
                <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, color: '#5D6D7E', textTransform: 'uppercase', letterSpacing: '.4px', fontWeight: 600 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <InvoiceTable rows={activeRows} />
          </tbody>
        </table>
      </div>
    </div>
  )
}
