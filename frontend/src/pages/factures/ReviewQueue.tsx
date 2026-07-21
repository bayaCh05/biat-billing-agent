import React, { useState, useEffect, useRef } from 'react'
import { CheckCircle, XCircle, Wrench, ChevronDown, ChevronUp } from 'lucide-react'
import { getReviewQueue, approveInvoice, rejectInvoice } from '../../api/endpoints'
import type { InvoiceSummary, InvoiceFlag } from '../../types'
import PageSpinner from '../../components/ui/PageSpinner'
import { formatTND } from '../../utils/formatters'
import { useAuth } from '../../context/AuthContext'

const FLAG_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  TOTAL_MISMATCH:         { bg: '#FDECEA', color: '#C0391B', label: 'Écart total' },
  LOW_CONFIDENCE:         { bg: '#FFF3E0', color: '#E65100', label: 'Faible confiance' },
  DUPLICATE:              { bg: '#FFF8E8', color: '#F0A600', label: 'Doublon' },
  NEAR_DUPLICATE:         { bg: '#FFF0DC', color: '#E67E22', label: 'Quasi-doublon' },
  HIGH_VALUE:             { bg: '#FFF8E8', color: '#B07800', label: 'Montant élevé' },
  CATALOG_NO_MATCH:       { bg: '#F3E5F5', color: '#804CD7', label: 'Sans catalogue' },
  LINEITEMS_SUM_MISMATCH: { bg: '#FDECEA', color: '#C0391B', label: 'Écart lignes' },
  MISSING_FIELD:          { bg: '#FFF3E0', color: '#E65100', label: 'Champ manquant' },
  INVALID_TAX_ID:         { bg: '#FDECEA', color: '#C0391B', label: 'MF invalide' },
  SUSPECTED_DUPLICATE:    { bg: '#FFF0DC', color: '#E67E22', label: 'Doublon suspect' },
  UNKNOWN_DIRECTION:      { bg: '#F3E5F5', color: '#804CD7', label: 'Direction inconnue' },
  SUSPICIOUS_AMOUNT:      { bg: '#FDECEA', color: '#C0391B', label: 'Montant suspect' },
  TVA_MISMATCH:           { bg: '#FDECEA', color: '#C0391B', label: 'Écart TVA' },
}

function FlagBadge({ flag }: { flag: InvoiceFlag }) {
  const s = FLAG_STYLE[flag.flag_type] ?? { bg: '#F0F4F9', color: '#5D6D7E', label: flag.flag_type }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold mr-1" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

function confColor(c: number) {
  if (c >= 0.9) return '#1D9E76'
  if (c >= 0.6) return '#F0A600'
  return '#C0391B'
}

interface Toast { id: number; msg: string; type: 'ok' | 'err' }

export default function ReviewQueue() {
  const { role, initials } = useAuth()
  const canApproveReject = role === 'Comptable' || role === 'Admin'
  const [items, setItems] = useState<InvoiceSummary[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('Tous')
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastId = useRef(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const addToast = (msg: string, type: 'ok' | 'err') => {
    const id = ++toastId.current
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3500)
  }

  useEffect(() => {
    getReviewQueue()
      .then(data => setItems(data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const filtered = items.filter(item => {
    const q = search.toLowerCase()
    const matchQ = !q || (item.issuer_name ?? '').toLowerCase().includes(q) || (item.invoice_number ?? '').toLowerCase().includes(q)
    const matchS = statusFilter === 'Tous' || item.status === statusFilter
    return matchQ && matchS
  })

  const approve = async (id: string) => {
    setActing(id)
    const inv = items.find(i => i.id === id)
    try {
      await approveInvoice(id)
      setItems(prev => prev.filter(i => i.id !== id))
      if (expanded === id) setExpanded(null)
      addToast(`✓ ${inv?.issuer_name ?? 'Facture'} — approuvée`, 'ok')
    } catch {
      addToast(`Erreur réseau — action non enregistrée`, 'err')
    } finally {
      setActing(null)
    }
  }

  const reject = async (id: string) => {
    setActing(id)
    const inv = items.find(i => i.id === id)
    try {
      await rejectInvoice(id)
      setItems(prev => prev.filter(i => i.id !== id))
      if (expanded === id) setExpanded(null)
      addToast(`✗ ${inv?.issuer_name ?? 'Facture'} — rejetée`, 'err')
    } catch {
      addToast(`Erreur réseau — action non enregistrée`, 'err')
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <header className="flex items-center gap-3 px-6 h-14 border-b shrink-0 bg-white" style={{ borderColor: '#D5E8F5' }}>
        <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>File de révision</h1>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#5BA3C9' }} />
          {role}
        </span>
        <div className="flex-1" />
        <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0" style={{ background: '#1A3A5C' }}>{initials}</div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {/* Filter bar */}
        <div className="flex items-center gap-3 px-6 py-3 bg-white border-b" style={{ borderColor: '#D5E8F5' }}>
          <div className="relative">
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Rechercher fournisseur, N° facture..."
              className="pl-3 pr-3 py-1.5 text-sm rounded-lg border outline-none w-64"
              style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 text-sm rounded-lg border outline-none"
            style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
          >
            <option value="Tous">Statut : Tous</option>
            <option value="FLAGGED">Signalées</option>
            <option value="VALIDATED">Validées</option>
            <option value="REJECTED">Rejetées</option>
          </select>
          <div className="ml-auto">
            <span className="px-3 py-1.5 rounded-lg text-xs font-semibold" style={{ background: '#FFF8E8', color: '#B07800', border: '1px solid #F0A600' }}>
              ⚠ {filtered.length} facture{filtered.length !== 1 ? 's' : ''} à réviser
            </span>
          </div>
        </div>

        {/* Table */}
        <div className="mx-6 mt-4 bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
          <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #D5E8F5' }}>
                {['#', 'Fournisseur', 'N° Facture', 'Date', 'Montant TTC', 'Catégorie', 'Raison IA', 'Flags', 'Actions'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase" style={{ color: '#5D6D7E' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, idx) => (
                <React.Fragment key={item.id}>
                  <tr
                    className="cursor-pointer transition-colors"
                    style={{
                      borderBottom: '1px solid #F0F4F9',
                      background: acting === item.id ? '#FFFBF0' : undefined,
                      opacity: acting === item.id ? 0.7 : 1,
                    }}
                    onClick={() => acting !== item.id && setExpanded(expanded === item.id ? null : item.id)}
                  >
                    <td className="px-4 py-3 font-medium" style={{ color: '#5D6D7E' }}>{String(idx + 1).padStart(2, '0')}</td>
                    <td className="px-4 py-3 font-semibold" style={{ color: '#1A1A2E' }}>{item.issuer_name ?? '—'}</td>
                    <td className="px-4 py-3" style={{ color: '#1A1A2E' }}>{item.invoice_number ?? '—'}</td>
                    <td className="px-4 py-3" style={{ color: '#5D6D7E' }}>{item.invoice_date ?? '—'}</td>
                    <td className="px-4 py-3 font-semibold" style={{ color: '#1A1A2E' }}>
                      {item.amount_ttc != null ? formatTND(item.amount_ttc) : '—'}
                    </td>
                    <td className="px-4 py-3" style={{ color: '#5D6D7E' }}>{item.accounting_label ?? '—'}</td>
                    <td className="px-4 py-3" style={{ maxWidth: 180 }}>
                      {item.classification_reason ? (
                        <span
                          className="text-[10px] text-purple-700 line-clamp-2 cursor-help"
                          title={item.classification_reason}
                        >
                          🤖 {item.classification_reason}
                        </span>
                      ) : (
                        <span className="text-[10px]" style={{ color: '#C8D8E8' }}>—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-0.5">
                        {(item.flags ?? []).filter(f => !f.resolved).map((f, fi) => (
                          <FlagBadge key={fi} flag={f} />
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
                        {canApproveReject && (
                          <>
                            <button
                              onClick={() => approve(item.id)}
                              disabled={acting === item.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold disabled:opacity-50"
                              style={{ background: '#E8F5F0', color: '#1D9E76' }}
                            >
                              <CheckCircle size={11} /> Approuver
                            </button>
                            <button
                              onClick={() => reject(item.id)}
                              disabled={acting === item.id}
                              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold disabled:opacity-50"
                              style={{ background: '#FDECEA', color: '#C0391B' }}
                            >
                              <XCircle size={11} /> Rejeter
                            </button>
                          </>
                        )}
                        <button
                          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold"
                          style={{ background: '#EFF4FA', color: '#1A3A5C' }}
                        >
                          <Wrench size={11} /> Modifier
                        </button>
                        <span className="ml-1" style={{ color: '#5D6D7E' }}>
                          {expanded === item.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </span>
                      </div>
                    </td>
                  </tr>

                  {expanded === item.id && (
                    <tr key={`${item.id}-detail`}>
                      <td colSpan={8} className="px-6 py-5" style={{ background: '#F8FAFF', borderBottom: '1px solid #D5E8F5' }}>
                        <p className="text-sm font-semibold mb-3" style={{ color: '#1A3A5C' }}>
                          Détail — {item.issuer_name} · {item.invoice_number}
                        </p>
                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4 mb-3">
                          {[
                            { label: 'Montant HT',   value: item.amount_ht != null ? formatTND(item.amount_ht) : '—',   conf: 0.86 },
                            { label: 'TVA (19%)',     value: item.tva_amount != null ? formatTND(item.tva_amount) : '—', conf: 0.72 },
                            { label: 'Montant TTC',  value: item.amount_ttc != null ? formatTND(item.amount_ttc) : '—', conf: 0.95 },
                            { label: 'N° Facture',   value: item.invoice_number ?? '—',                                  conf: 0.98 },
                            { label: 'Date',         value: item.invoice_date ?? '—',                                    conf: 0.95 },
                          ].map(field => (
                            <div key={field.label}>
                              <p className="text-xs mb-0.5" style={{ color: '#5D6D7E' }}>{field.label}</p>
                              <p className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>{field.value}</p>
                              <p className="text-xs font-medium mt-0.5" style={{ color: confColor(field.conf) }}>
                                ● {Math.round(field.conf * 100)}%
                              </p>
                            </div>
                          ))}
                        </div>
                        {(item.flags ?? []).filter(f => !f.resolved).length > 0 && (
                          <div className="flex flex-wrap gap-3 pt-3 border-t" style={{ borderColor: '#D5E8F5' }}>
                            {(item.flags ?? []).filter(f => !f.resolved).map((f, fi) => {
                              const sev = f.severity === 'ERROR'
                              return (
                                <span key={fi} className="text-xs font-medium" style={{ color: sev ? '#C0391B' : '#B07800' }}>
                                  ▲ {f.flag_type} — {f.message}
                                </span>
                              )
                            })}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-center py-12 text-sm" style={{ color: '#5D6D7E' }}>
                    <CheckCircle size={32} className="mx-auto mb-2" style={{ color: '#1D9E76' }} />
                    File vide — toutes les factures ont été traitées
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          </div>
        </div>
        <div className="h-6" />
      </div>

      {/* Toast stack — bottom-right */}
      <div className="fixed bottom-5 right-5 flex flex-col gap-2 z-50 pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className="flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm font-medium pointer-events-auto"
            style={{
              background: t.type === 'ok' ? '#E8F5F0' : '#FDECEA',
              color:      t.type === 'ok' ? '#1D9E76' : '#C0391B',
              border:     `1px solid ${t.type === 'ok' ? '#1D9E76' : '#C0391B'}`,
              minWidth: 260,
            }}
          >
            {t.type === 'ok' ? <CheckCircle size={15} /> : <XCircle size={15} />}
            {t.msg}
          </div>
        ))}
      </div>
    </div>
  )
}
