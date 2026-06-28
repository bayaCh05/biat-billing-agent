import { useState, useEffect, useCallback } from 'react'
import { listAuditLogs } from '../api/endpoints'
import type { AuditLog } from '../types'
import { Shield, ChevronDown, ChevronRight, Download, RefreshCw, Filter } from 'lucide-react'

const ACTIONS = ['', 'LOGIN', 'LOGOUT', 'CREATE', 'UPDATE', 'DELETE', 'APPROVE', 'REJECT', 'EXPORT']
const RESOURCE_TYPES = ['', 'InvoiceRecord', 'Asset', 'JournalEntry', 'ClientInvoice', 'User']

const ACTION_COLORS: Record<string, string> = {
  LOGIN:   'bg-blue-100 text-blue-800',
  LOGOUT:  'bg-gray-100 text-gray-700',
  CREATE:  'bg-green-100 text-green-800',
  UPDATE:  'bg-yellow-100 text-yellow-800',
  DELETE:  'bg-red-100 text-red-800',
  APPROVE: 'bg-emerald-100 text-emerald-800',
  REJECT:  'bg-orange-100 text-orange-800',
  EXPORT:  'bg-purple-100 text-purple-800',
}

function StatusBadge({ status }: { status: string }) {
  const ok = status === 'SUCCESS'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
      {ok ? '✓' : '✗'} {status}
    </span>
  )
}

function ActionBadge({ action }: { action: string }) {
  const cls = ACTION_COLORS[action] ?? 'bg-gray-100 text-gray-700'
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-mono font-semibold ${cls}`}>{action}</span>
}

function JsonDiff({ before, after }: { before: unknown; after: unknown }) {
  const fmt = (v: unknown) => JSON.stringify(v, null, 2)
  return (
    <div className="grid grid-cols-2 gap-3 mt-2 text-xs">
      {before !== null && before !== undefined && (
        <div>
          <p className="font-semibold text-red-700 mb-1">Avant</p>
          <pre className="bg-red-50 border border-red-200 rounded p-2 overflow-auto max-h-48 text-red-900">{fmt(before)}</pre>
        </div>
      )}
      {after !== null && after !== undefined && (
        <div>
          <p className="font-semibold text-green-700 mb-1">Après</p>
          <pre className="bg-green-50 border border-green-200 rounded p-2 overflow-auto max-h-48 text-green-900">{fmt(after)}</pre>
        </div>
      )}
    </div>
  )
}

function AuditRow({ log }: { log: AuditLog }) {
  const [open, setOpen] = useState(false)
  const hasDetail = log.before_value || log.after_value || log.detail || log.user_agent

  return (
    <>
      <tr
        className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${hasDetail ? 'cursor-pointer' : ''}`}
        onClick={() => hasDetail && setOpen(o => !o)}
      >
        <td className="py-2 px-3 text-xs text-gray-500 whitespace-nowrap">
          {hasDetail && (
            open ? <ChevronDown className="inline w-3 h-3 mr-1" /> : <ChevronRight className="inline w-3 h-3 mr-1" />
          )}
          {new Date(log.created_at).toLocaleString('fr-TN', { hour12: false })}
        </td>
        <td className="py-2 px-3 text-xs">
          <div className="font-medium text-gray-800">{log.user_email ?? '—'}</div>
          {log.user_role && <div className="text-gray-400 text-[11px]">{log.user_role}</div>}
        </td>
        <td className="py-2 px-3"><ActionBadge action={log.action} /></td>
        <td className="py-2 px-3 text-xs text-gray-600">{log.resource_type ?? '—'}</td>
        <td className="py-2 px-3 text-xs font-mono text-gray-500 max-w-[140px] truncate" title={log.resource_id ?? ''}>
          {log.resource_id ?? '—'}
        </td>
        <td className="py-2 px-3"><StatusBadge status={log.status} /></td>
        <td className="py-2 px-3 text-xs text-gray-400">{log.ip_address ?? '—'}</td>
      </tr>
      {open && hasDetail && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={7} className="px-6 py-3">
            {log.detail && <p className="text-xs text-gray-600 mb-2 italic">{log.detail}</p>}
            {(log.before_value || log.after_value) && (
              <JsonDiff before={log.before_value} after={log.after_value} />
            )}
            {log.user_agent && (
              <p className="text-[11px] text-gray-400 mt-2 break-all">UA: {log.user_agent}</p>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showFilters, setShowFilters] = useState(false)

  const [filters, setFilters] = useState({
    action: '',
    resource_type: '',
    user_email: '',
    status: '',
    from_date: '',
    to_date: '',
    limit: 100,
    offset: 0,
  })

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, string | number> = {}
      if (filters.action)        params.action = filters.action
      if (filters.resource_type) params.resource_type = filters.resource_type
      if (filters.user_email)    params.user_email = filters.user_email
      if (filters.status)        params.status = filters.status
      if (filters.from_date)     params.from_date = filters.from_date
      if (filters.to_date)       params.to_date = filters.to_date
      params.limit = filters.limit
      params.offset = filters.offset
      const data = await listAuditLogs(params as Parameters<typeof listAuditLogs>[0])
      setLogs(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => { load() }, [load])

  const exportCsv = () => {
    const headers = ['Date', 'Email', 'Rôle', 'Action', 'Ressource', 'ID', 'Statut', 'IP', 'Détail']
    const rows = logs.map(l => [
      l.created_at,
      l.user_email ?? '',
      l.user_role ?? '',
      l.action,
      l.resource_type ?? '',
      l.resource_id ?? '',
      l.status,
      l.ip_address ?? '',
      l.detail ?? '',
    ])
    const csv = [headers, ...rows].map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-biat-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const setFilter = (key: string, value: string | number) =>
    setFilters(f => ({ ...f, [key]: value, offset: key !== 'offset' ? 0 : f.offset }))

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-900 rounded-xl flex items-center justify-center">
            <Shield className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Piste d'Audit</h1>
            <p className="text-xs text-gray-500">Journal de conformité BCT — inaltérable et infalsifiable</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowFilters(f => !f)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50"
          >
            <Filter className="w-3.5 h-3.5" /> Filtres
          </button>
          <button
            onClick={exportCsv}
            disabled={logs.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40"
          >
            <Download className="w-3.5 h-3.5" /> CSV
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-blue-900 text-white hover:bg-blue-800 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Actualiser
          </button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 mb-5 grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Action</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.action}
              onChange={e => setFilter('action', e.target.value)}
            >
              {ACTIONS.map(a => <option key={a} value={a}>{a || 'Toutes'}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type de ressource</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.resource_type}
              onChange={e => setFilter('resource_type', e.target.value)}
            >
              {RESOURCE_TYPES.map(r => <option key={r} value={r}>{r || 'Toutes'}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Statut</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.status}
              onChange={e => setFilter('status', e.target.value)}
            >
              <option value="">Tous</option>
              <option value="SUCCESS">SUCCESS</option>
              <option value="FAILURE">FAILURE</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Email utilisateur</label>
            <input
              type="text"
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              placeholder="Recherche partielle…"
              value={filters.user_email}
              onChange={e => setFilter('user_email', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Depuis</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.from_date}
              onChange={e => setFilter('from_date', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Jusqu'à</label>
            <input
              type="date"
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.to_date}
              onChange={e => setFilter('to_date', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Lignes par page</label>
            <select
              className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
              value={filters.limit}
              onChange={e => setFilter('limit', Number(e.target.value))}
            >
              {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>
      )}

      {/* Stats bar */}
      <div className="flex items-center gap-4 mb-4 text-xs text-gray-500">
        <span>{logs.length} entrée{logs.length !== 1 ? 's' : ''}</span>
        {logs.filter(l => l.status === 'FAILURE').length > 0 && (
          <span className="text-red-600 font-semibold">
            ⚠ {logs.filter(l => l.status === 'FAILURE').length} échec{logs.filter(l => l.status === 'FAILURE').length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Table */}
      {error ? (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600 whitespace-nowrap">Date / Heure</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">Utilisateur</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">Action</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">Ressource</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">ID</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">Statut</th>
                  <th className="py-2.5 px-3 text-left text-xs font-semibold text-gray-600">IP</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={7} className="text-center py-12 text-gray-400 text-sm">Chargement…</td></tr>
                ) : logs.length === 0 ? (
                  <tr><td colSpan={7} className="text-center py-12 text-gray-400 text-sm">Aucune entrée d'audit trouvée</td></tr>
                ) : (
                  logs.map(l => <AuditRow key={l.id} log={l} />)
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {logs.length === filters.limit && (
            <div className="flex justify-end items-center gap-3 px-4 py-3 border-t border-gray-100 bg-gray-50">
              <button
                disabled={filters.offset === 0}
                onClick={() => setFilter('offset', Math.max(0, filters.offset - filters.limit))}
                className="px-3 py-1 text-sm rounded border border-gray-300 hover:bg-white disabled:opacity-40"
              >
                ← Précédent
              </button>
              <span className="text-xs text-gray-500">Page {Math.floor(filters.offset / filters.limit) + 1}</span>
              <button
                onClick={() => setFilter('offset', filters.offset + filters.limit)}
                className="px-3 py-1 text-sm rounded border border-gray-300 hover:bg-white"
              >
                Suivant →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
