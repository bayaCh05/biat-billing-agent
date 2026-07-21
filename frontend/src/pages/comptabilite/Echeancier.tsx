import { useState, useEffect } from 'react'
import { CalendarClock, AlertTriangle, TrendingUp, CheckCircle, RefreshCw, X } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import Card from '../../components/ui/Card'
import { apiFetch } from '../../api/client'

// ── Types ──────────────────────────────────────────────────────────────────

interface Installment {
  id: string
  invoice_id: string
  issuer_name: string | null
  invoice_number: string | null
  installment_number: number
  total_installments: number
  base_amount: number
  current_amount: number
  penalty_amount: number
  penalty_pct: number
  due_date: string
  paid_date: string | null
  paid_amount: number | null
  status: 'PENDING' | 'LATE' | 'PAID'
  late_periods: number
  days_overdue: number
}

interface Summary {
  total: number
  late_count: number
  pending_count: number
  paid_count: number
  total_penalties: number
  next_due_date: string | null
  next_due_amount: number | null
}

// ── Helpers ────────────────────────────────────────────────────────────────

const TND = (n: number) =>
  n.toLocaleString('fr-TN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' TND'

function formatDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function rowBg(inst: Installment): string {
  if (inst.status === 'PAID') return '#F8FAFC'
  if (inst.status === 'LATE') {
    if (inst.days_overdue > 60) return '#FEE2E2'
    if (inst.days_overdue > 30) return '#FFEDD5'
    return '#FEF9C3'
  }
  return '#FFFFFF'
}

function StatusBadge({ inst }: { inst: Installment }) {
  if (inst.status === 'PAID')
    return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#E8F5F0', color: '#1D9E76' }}>✅ Payée</span>
  if (inst.status === 'PENDING')
    return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#EFF4FA', color: '#2E86C1' }}>⏳ En attente</span>
  if (inst.days_overdue > 60)
    return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#FEE2E2', color: '#C0391B' }}>🔴 {inst.days_overdue}j retard</span>
  if (inst.days_overdue > 30)
    return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#FFEDD5', color: '#C2400B' }}>🟠 {inst.days_overdue}j retard</span>
  return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#FEF9C3', color: '#A16207' }}>🟡 {inst.days_overdue}j retard</span>
}

// ── Mark-paid modal ────────────────────────────────────────────────────────

function MarkPaidModal({ inst, onClose, onDone }: {
  inst: Installment
  onClose: () => void
  onDone: () => void
}) {
  const [amount, setAmount] = useState(inst.current_amount.toFixed(3))
  const [paidDate, setPaidDate] = useState(new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      await apiFetch(`/payments/installments/${inst.id}/mark-paid`, {
        method: 'PATCH',
        body: JSON.stringify({ paid_amount: parseFloat(amount), paid_date: paidDate }),
      })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold" style={{ color: '#1A3A5C' }}>
            Marquer comme payée
          </h3>
          <button onClick={onClose}><X size={18} className="text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="rounded-lg p-3 mb-4 text-sm" style={{ background: '#F0F4F9' }}>
          <p className="font-semibold" style={{ color: '#1A1A2E' }}>{inst.issuer_name ?? '—'}</p>
          <p className="text-xs" style={{ color: '#5D6D7E' }}>
            {inst.invoice_number} — Échéance {inst.installment_number}/{inst.total_installments}
          </p>
          <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
            Base: {TND(inst.base_amount)}
            {inst.penalty_amount > 0 && (
              <span style={{ color: '#C0391B' }}> + pénalité {TND(inst.penalty_amount)}</span>
            )}
          </p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>
              Montant payé (TND)
            </label>
            <input
              type="number"
              step="0.001"
              value={amount}
              onChange={e => setAmount(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm"
              style={{ borderColor: '#D5E8F5' }}
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>
              Date de paiement
            </label>
            <input
              type="date"
              value={paidDate}
              onChange={e => setPaidDate(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm"
              style={{ borderColor: '#D5E8F5' }}
            />
          </div>
        </div>

        {error && (
          <p className="text-xs text-red-600 mt-2">{error}</p>
        )}

        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-xl border text-sm font-medium"
            style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}
          >
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="flex-1 py-2 rounded-xl text-sm font-semibold text-white disabled:opacity-50"
            style={{ background: '#1D9E76' }}
          >
            {saving ? 'Enregistrement...' : 'Confirmer le paiement'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function EcheancierPage() {
  const [installments, setInstallments] = useState<Installment[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [payingInst, setPayingInst] = useState<Installment | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [items, sum] = await Promise.all([
        apiFetch<Installment[]>('/payments/installments'),
        apiFetch<Summary>('/payments/installments/summary'),
      ])
      setInstallments(items)
      setSummary(sum)
    } catch {
      // keep whatever we had
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { queueMicrotask(load) }, [])

  const filtered = statusFilter === 'ALL'
    ? installments
    : installments.filter(i => i.status === statusFilter)

  return (
    <div>
      {payingInst && (
        <MarkPaidModal
          inst={payingInst}
          onClose={() => setPayingInst(null)}
          onDone={() => { setPayingInst(null); load() }}
        />
      )}

      <PageHeader title="📅 Échéancier de Paiements">
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 hover:bg-gray-50 text-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Actualiser
        </button>
      </PageHeader>

      <div className="p-6 flex flex-col gap-5">

        {/* Summary cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <p className="text-xs text-gray-500 mb-1">Total échéances</p>
            <p className="text-2xl font-bold" style={{ color: '#1A3A5C' }}>{summary?.total ?? 0}</p>
          </Card>
          <Card>
            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1">
              <AlertTriangle size={11} className="text-red-500" /> En retard
            </p>
            <p className="text-2xl font-bold" style={{ color: summary?.late_count ? '#C0391B' : '#1A1A2E' }}>
              {summary?.late_count ?? 0}
            </p>
          </Card>
          <Card>
            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1">
              <TrendingUp size={11} className="text-red-500" /> Pénalités accumulées
            </p>
            <p className="text-xl font-bold" style={{ color: summary?.total_penalties ? '#C0391B' : '#1A1A2E' }}>
              {summary ? TND(summary.total_penalties) : '—'}
            </p>
          </Card>
          <Card>
            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1">
              <CalendarClock size={11} className="text-blue-500" /> Prochaine échéance
            </p>
            {summary?.next_due_date ? (
              <>
                <p className="text-sm font-bold" style={{ color: '#2E86C1' }}>{formatDate(summary.next_due_date)}</p>
                <p className="text-xs" style={{ color: '#5D6D7E' }}>{TND(summary.next_due_amount ?? 0)}</p>
              </>
            ) : (
              <p className="text-sm font-medium text-gray-400">Aucune</p>
            )}
          </Card>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-2">
          {[
            { key: 'ALL',     label: `Toutes (${installments.length})` },
            { key: 'LATE',    label: `En retard (${installments.filter(i => i.status === 'LATE').length})` },
            { key: 'PENDING', label: `En attente (${installments.filter(i => i.status === 'PENDING').length})` },
            { key: 'PAID',    label: `Payées (${installments.filter(i => i.status === 'PAID').length})` },
          ].map(f => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors"
              style={{
                background: statusFilter === f.key ? '#1A3A5C' : '#F0F4F9',
                color: statusFilter === f.key ? '#FFFFFF' : '#5D6D7E',
                borderColor: statusFilter === f.key ? '#1A3A5C' : '#D5E8F5',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Main table */}
        <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: '#F0F4F9', borderBottom: '1px solid #D5E8F5' }}>
                {['Fournisseur', 'Facture', 'Échéance', 'Date due', 'Base', 'Pénalité', 'À payer', 'Statut', 'Action'].map(h => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold uppercase" style={{ color: '#5D6D7E' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">
                    {loading ? 'Chargement...' : 'Aucune échéance'}
                  </td>
                </tr>
              ) : filtered.map(inst => (
                <tr
                  key={inst.id}
                  style={{
                    background: rowBg(inst),
                    borderBottom: '1px solid #F0F4F9',
                    opacity: inst.status === 'PAID' ? 0.6 : 1,
                  }}
                >
                  {/* Fournisseur */}
                  <td className="px-4 py-3">
                    <p className="font-medium text-xs" style={{ color: '#1A1A2E', textDecoration: inst.status === 'PAID' ? 'line-through' : 'none' }}>
                      {inst.issuer_name ?? '—'}
                    </p>
                  </td>

                  {/* Facture */}
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: '#5D6D7E' }}>
                    {inst.invoice_number ?? '—'}
                  </td>

                  {/* Échéance N° */}
                  <td className="px-4 py-3 text-xs text-center" style={{ color: '#5D6D7E' }}>
                    {inst.installment_number}/{inst.total_installments}
                  </td>

                  {/* Date due */}
                  <td className="px-4 py-3 text-xs" style={{ color: '#1A1A2E' }}>
                    {formatDate(inst.due_date)}
                    {inst.paid_date && (
                      <p className="text-xs mt-0.5" style={{ color: '#1D9E76' }}>
                        Payé {formatDate(inst.paid_date)}
                      </p>
                    )}
                  </td>

                  {/* Base */}
                  <td className="px-4 py-3 text-xs font-mono text-right" style={{ color: '#1A1A2E' }}>
                    {TND(inst.base_amount)}
                  </td>

                  {/* Pénalité */}
                  <td className="px-4 py-3 text-xs" style={{ color: inst.penalty_amount > 0 ? '#C0391B' : '#5D6D7E' }}>
                    {inst.penalty_amount > 0 ? (
                      <div>
                        <p className="font-mono font-semibold">+{TND(inst.penalty_amount)}</p>
                        <p className="text-xs mt-0.5">
                          🔴 {inst.days_overdue}j × {inst.late_periods} période{inst.late_periods > 1 ? 's' : ''} = +{inst.penalty_pct}%
                        </p>
                      </div>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>

                  {/* À payer */}
                  <td className="px-4 py-3 text-xs font-mono font-semibold text-right" style={{ color: inst.penalty_amount > 0 ? '#C0391B' : '#1A1A2E' }}>
                    {TND(inst.current_amount)}
                  </td>

                  {/* Statut */}
                  <td className="px-4 py-3">
                    <StatusBadge inst={inst} />
                  </td>

                  {/* Action */}
                  <td className="px-4 py-3">
                    {inst.status !== 'PAID' && (
                      <button
                        onClick={() => setPayingInst(inst)}
                        className="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-lg text-white transition-colors"
                        style={{ background: '#1D9E76' }}
                      >
                        <CheckCircle size={11} />
                        Payée
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          {/* Penalty legend */}
          {filtered.some(i => i.status === 'LATE') && (
            <div className="px-4 py-3 border-t text-xs flex items-center gap-4" style={{ borderColor: '#F0F4F9', background: '#FFFBF0' }}>
              <span className="font-semibold" style={{ color: '#A16207' }}>Calcul des pénalités:</span>
              <span style={{ color: '#5D6D7E' }}>Montant actuel = Base × (1 + 10%) ^ nombre de tranches de 30j écoulées</span>
              <span className="ml-auto flex items-center gap-3">
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#FEF9C3' }}></span> 1–30j</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#FFEDD5' }}></span> 31–60j</span>
                <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: '#FEE2E2' }}></span> &gt;60j</span>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
