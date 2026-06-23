import { useState, useEffect } from 'react'
import { ChevronDown, Download } from 'lucide-react'
import StatusChip from '../components/ui/StatusChip'
import { listInvoices, getInvoice } from '../api/endpoints'
import type { InvoiceSummary, Invoice, InvoiceDirection } from '../types'
import { formatTND, formatDate } from '../utils/formatters'
import { useAuth } from '../context/AuthContext'

const TERMINAL = new Set(['EXPORTED', 'JOURNALED', 'JOURNALING', 'PAID', 'COLLECTED'])
const PENDING  = new Set(['RECEIVED', 'EXTRACTING', 'EXTRACTED', 'CLASSIFYING', 'CLASSIFIED', 'VALIDATING', 'VALIDATED', 'FLAGGED', 'EXPORTING'])

function confColor(c: number): string {
  if (c >= 0.9) return '#1D9E76'
  if (c >= 0.6) return '#F0A600'
  return '#C0391B'
}

export default function InvoiceDetail() {
  const { role, initials } = useAuth()
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([])
  const [tab, setTab] = useState<'all' | 'supplier' | 'client'>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Invoice | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    listInvoices()
      .then(data => { if (data.length) setInvoices(data) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    setDetailLoading(true)
    getInvoice(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }, [selectedId])

  const byDir = (dir: InvoiceDirection) => invoices.filter(i => i.direction === dir)
  const displayed = tab === 'supplier' ? byDir('SUPPLIER') : tab === 'client' ? byDir('CLIENT') : invoices

  const totalTTC = invoices.reduce((s, i) => s + (i.amount_ttc ?? 0), 0)
  const pendingCount = invoices.filter(i => PENDING.has(i.status)).length
  const exportedCount = invoices.filter(i => TERMINAL.has(i.status)).length
  const selectedSummary = invoices.find(i => i.id === selectedId)

  function exportCSV() {
    const headers = ['ID', 'Statut', 'Fournisseur', 'N° Facture', 'Date', 'TTC', 'Catégorie']
    const rows = displayed.map(i => [
      i.id, i.status, i.issuer_name ?? '', i.invoice_number ?? '',
      i.invoice_date ?? '', String(i.amount_ttc ?? ''), i.accounting_label ?? '',
    ])
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a'); a.href = url; a.download = 'factures.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  const totalStr = totalTTC >= 1_000_000
    ? `${(totalTTC / 1_000_000).toFixed(3)}M TND`
    : `${totalTTC.toLocaleString('fr-TN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })} TND`

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <header className="flex items-center gap-3 px-6 h-14 border-b shrink-0 bg-white" style={{ borderColor: '#D5E8F5' }}>
        <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>📋 Toutes les factures</h1>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#5BA3C9' }} />
          {role}
        </span>
        <div className="flex-1" />
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0" style={{ background: '#1A3A5C' }}>{initials}</div>
      </header>

      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {/* KPI row */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Total factures',    value: String(invoices.length),    sub: '18 ce mois' },
            { label: 'Montant total TTC', value: totalStr,                   sub: '+8.2%' },
            { label: 'En attente',        value: String(pendingCount),       sub: '4 en retard' },
            { label: 'Exportées',         value: String(exportedCount),      sub: `Taux auto: ${invoices.length ? Math.round(exportedCount / invoices.length * 100) : 0}%` },
          ].map(card => (
            <div key={card.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-xs" style={{ color: '#5D6D7E' }}>{card.label}</p>
              <p className="text-2xl font-bold mt-0.5" style={{ color: '#1A1A2E' }}>{card.value}</p>
              <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{card.sub}</p>
            </div>
          ))}
        </div>

        {/* Tabs + actions */}
        <div className="flex items-center gap-2">
          {(['all', 'supplier', 'client'] as const).map(t => {
            const label = t === 'all'
              ? `Tous (${invoices.length})`
              : t === 'supplier'
              ? `Fournisseurs (${byDir('SUPPLIER').length})`
              : `Clients (${byDir('CLIENT').length})`
            const active = tab === t
            return (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="px-4 py-1.5 rounded-lg text-sm font-semibold border transition-colors"
                style={{
                  background: active ? '#1A3A5C' : '#fff',
                  color: active ? '#fff' : '#1A3A5C',
                  borderColor: active ? '#1A3A5C' : '#D5E8F5',
                }}
              >
                {label}
              </button>
            )
          })}
          <div className="ml-auto flex items-center gap-2">
            <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}>
              Direction <ChevronDown size={13} />
            </button>
            <button
              onClick={exportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
              style={{ background: '#1A3A5C' }}
            >
              <Download size={13} /> Exporter CSV
            </button>
          </div>
        </div>

        {/* Table + Detail panel */}
        <div className="flex gap-4 min-h-0">
          {/* Table */}
          <div className="flex-1 bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #D5E8F5' }}>
                  {['Statut', 'Fournisseur', 'N° Facture', 'Date', 'TTC (TND)', 'Catégorie', 'Conf.'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase whitespace-nowrap" style={{ color: '#5D6D7E' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayed.map(inv => {
                  const isSelected = inv.id === selectedId
                  const conf = 0.88
                  return (
                    <tr
                      key={inv.id}
                      onClick={() => setSelectedId(isSelected ? null : inv.id)}
                      className="cursor-pointer transition-colors"
                      style={{
                        borderBottom: '1px solid #F0F4F9',
                        background: isSelected ? '#EFF4FA' : undefined,
                        borderLeft: isSelected ? '3px solid #1A3A5C' : '3px solid transparent',
                      }}
                    >
                      <td className="px-4 py-3"><StatusChip status={inv.status} /></td>
                      <td className="px-4 py-3 font-semibold" style={{ color: '#1A1A2E' }}>{inv.issuer_name ?? '—'}</td>
                      <td className="px-4 py-3" style={{ color: '#1A1A2E' }}>{inv.invoice_number ?? '—'}</td>
                      <td className="px-4 py-3 whitespace-nowrap" style={{ color: '#5D6D7E' }}>
                        {inv.invoice_date ? inv.invoice_date.slice(5).replace('-', '/') : '—'}
                      </td>
                      <td className="px-4 py-3 font-semibold" style={{ color: '#1A1A2E' }}>
                        {inv.amount_ttc != null ? formatTND(inv.amount_ttc, 0) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{inv.accounting_label ?? '—'}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 text-xs font-medium">
                          <span className="w-2 h-2 rounded-full" style={{ background: confColor(conf) }} />
                          {Math.round(conf * 100)}%
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Detail panel */}
          {selectedId && (
            <div className="w-72 shrink-0 bg-white rounded-xl border" style={{ borderColor: '#D5E8F5' }}>
              <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: '#D5E8F5' }}>
                <p className="font-semibold text-sm" style={{ color: '#1A1A2E' }}>Détail facture</p>
                <button onClick={() => setSelectedId(null)} className="text-lg leading-none" style={{ color: '#5D6D7E' }}>✕</button>
              </div>

              <div className="p-4">
                {detailLoading ? (
                  <div className="text-center py-8 text-sm" style={{ color: '#5D6D7E' }}>Chargement…</div>
                ) : (
                  <div className="space-y-4 text-sm">
                    <div>
                      <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>Fournisseur</p>
                      <p className="font-semibold" style={{ color: '#1A1A2E' }}>
                        {detail ? String(detail.issuer_name.value ?? '—') : (selectedSummary?.issuer_name ?? '—')}
                      </p>
                      {detail?.issuer_tax_id.value && (
                        <p className="text-xs" style={{ color: '#5D6D7E' }}>MF: {String(detail.issuer_tax_id.value)}</p>
                      )}
                    </div>

                    <div>
                      <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>N° Facture</p>
                      <p className="font-semibold" style={{ color: '#1A1A2E' }}>
                        {detail ? String(detail.invoice_number.value ?? '—') : (selectedSummary?.invoice_number ?? '—')}
                      </p>
                      <p className="text-xs" style={{ color: '#5D6D7E' }}>
                        Émise le {formatDate(
                          detail ? String(detail.invoice_date.value ?? '') : (selectedSummary?.invoice_date ?? '')
                        )}
                      </p>
                    </div>

                    {detail ? (
                      <>
                        <div>
                          <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>Montant HT</p>
                          <p className="font-bold" style={{ color: '#1A1A2E' }}>{formatTND(Number(detail.amount_ht.value ?? 0))}</p>
                          <p className="text-xs" style={{ color: '#5D6D7E' }}>
                            TVA {detail.tva_rate.value ?? 19}%: {formatTND(Number(detail.tva_amount.value ?? 0))}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>Montant TTC</p>
                          <p className="font-bold text-base" style={{ color: '#1A3A5C' }}>{formatTND(Number(detail.amount_ttc.value ?? 0))}</p>
                          <p className="text-xs" style={{ color: confColor(detail.amount_ttc.confidence) }}>
                            Confiance: {Math.round(detail.amount_ttc.confidence * 100)}%
                          </p>
                        </div>
                      </>
                    ) : selectedSummary && (
                      <div>
                        <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>Montant TTC</p>
                        <p className="font-bold text-base" style={{ color: '#1A3A5C' }}>{formatTND(selectedSummary.amount_ttc ?? 0)}</p>
                      </div>
                    )}

                    <div>
                      <p className="text-xs mb-0.5 font-medium" style={{ color: '#5D6D7E' }}>Catégorie</p>
                      <p className="font-medium" style={{ color: '#1A1A2E' }}>
                        {detail?.accounting_label ?? selectedSummary?.accounting_label ?? '—'}
                      </p>
                      <p className="text-xs" style={{ color: '#5D6D7E' }}>
                        Compte {detail?.accounting_compte ?? selectedSummary?.accounting_compte ?? '—'}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs mb-1 font-medium" style={{ color: '#5D6D7E' }}>Statut</p>
                      <StatusChip status={selectedSummary?.status ?? 'RECEIVED'} />
                      {(detail?.extraction_method ?? selectedSummary?.extraction_method) && (
                        <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
                          Méthode: {detail?.extraction_method ?? selectedSummary?.extraction_method}
                        </p>
                      )}
                    </div>
                  </div>
                )}

                <div className="flex gap-2 mt-5">
                  <button className="flex-1 py-2 rounded-lg text-xs font-semibold text-white" style={{ background: '#1A3A5C' }}>
                    📄 Voir PDF
                  </button>
                  <button className="flex-1 py-2 rounded-lg text-xs font-semibold" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
                    📒 Voir écriture
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
