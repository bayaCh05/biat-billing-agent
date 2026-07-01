import { useState, useEffect } from 'react'
import type { KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { NLQueryResult } from '../types'

interface HistoryItem { query: string; resultCount: number; timestamp: string }

const STORAGE_KEY = 'biat_nl_history'

const CHIPS = [
  '📋 Factures Ooredoo du mois',
  '💰 Factures > 10 000 TND',
  '📈 Budget restant par catégorie',
  '🔴 Factures en retard',
  '🏷 Catégorie Maintenance ce trimestre',
  '📉 Taux auto-traitement YTD',
  '🔁 Doublons détectés',
  '🏗️ Actifs CAPEX acquis en 2026',
]

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "à l'instant"
  if (mins < 60) return `il y a ${mins} min`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `il y a ${hrs}h`
  return new Date(iso).toLocaleDateString('fr-TN')
}

function exportCSV(columns: string[], rows: (string | number | null)[][]) {
  const header = columns.join(';')
  const body = rows.map(r => r.map(v => v ?? '').join(';')).join('\n')
  const blob = new Blob([`${header}\n${body}`], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `requete_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function highlightSQL(sql: string): string {
  const escaped = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const keywords = ['ORDER BY', 'GROUP BY', 'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'HAVING', 'LIMIT', 'ILIKE', 'LIKE', 'NOT', 'NULL', 'AS', 'JOIN', 'LEFT', 'INNER', 'ON', 'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'IN', 'strftime']
  let out = escaped
  keywords.forEach(kw => {
    out = out.replace(new RegExp(`\\b(${kw})\\b`, 'gi'), `<span style="color:#7DC4F0">$1</span>`)
  })
  out = out.replace(/'([^']*)'/g, `<span style="color:#A8E0B4">'$1'</span>`)
  return out
}

const STATUS_BADGE: Record<string, { bg: string; color: string; label: string }> = {
  EXPORTED:          { bg: '#E8F5F0', color: '#1D9E76', label: 'Exportée' },
  JOURNALED:         { bg: '#E8F5F0', color: '#0D6E52', label: 'Journalisée' },
  PAID:              { bg: '#E8F0FA', color: '#1A3A5C', label: 'Payée' },
  COLLECTED:         { bg: '#E8F0FA', color: '#1A3A5C', label: 'Encaissée' },
  FLAGGED:           { bg: '#FEF0EE', color: '#C0391B', label: 'Signalée' },
  VALIDATED:         { bg: '#E3F0F9', color: '#5BA3C9', label: 'Validée' },
  REJECTED:          { bg: '#FDECEA', color: '#C0391B', label: 'Rejetée' },
  ERROR:             { bg: '#FEF0EE', color: '#C0391B', label: 'Erreur' },
  RECEIVED:          { bg: '#E3F0F9', color: '#1A3A5C', label: 'Reçue' },
  EXTRACTED:         { bg: '#E3F0F9', color: '#1A3A5C', label: 'Extraite' },
  CLASSIFIED:        { bg: '#E3F0F9', color: '#1A3A5C', label: 'Classifiée' },
  EXTRACTION_FAILED: { bg: '#FDECEA', color: '#C0391B', label: 'OCR échoué' },
}

export default function Requetes() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<NLQueryResult | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [sqlOpen, setSqlOpen] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [inputFocused, setInputFocused] = useState(false)

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) setHistory(JSON.parse(stored))
    } catch { /* ignore */ }
  }, [])

  async function submit() {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setResult(null)
    setSqlOpen(false)
    const t0 = Date.now()
    try {
      const res = await apiFetch<NLQueryResult>('/nl-query', {
        method: 'POST',
        body: JSON.stringify({ question: q }),
      })
      setElapsed(Math.round((Date.now() - t0) / 100) / 10)
      setResult(res)
      const newItem: HistoryItem = { query: q, resultCount: res.row_count, timestamp: new Date().toISOString() }
      const updated = [newItem, ...history].slice(0, 10)
      setHistory(updated)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
    } catch (e) {
      setElapsed(Math.round((Date.now() - t0) / 100) / 10)
      setResult({ sql: '', columns: [], rows: [], row_count: 0, error: String(e) })
    } finally {
      setLoading(false)
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') submit()
  }

  function cellDisplay(val: string | number | null, colIdx: number, col: string) {
    if (val === null || val === undefined) return <span style={{ color: '#5D6D7E' }}>—</span>
    const s = String(val)
    const badge = STATUS_BADGE[s.toUpperCase()]
    if ((col.toLowerCase().includes('status') || col.toLowerCase() === 'statut') && badge) {
      return (
        <span style={{ background: badge.bg, color: badge.color, padding: '3px 8px', borderRadius: 8, fontSize: 11, fontWeight: 600 }}>
          {badge.label}
        </span>
      )
    }
    return <span style={colIdx === 0 ? { fontWeight: 600 } : {}}>{s}</span>
  }

  return (
    <div style={{ flex: 1, display: 'flex', gap: 24, padding: '32px 40px', minHeight: 0 }}>
      {/* Main column */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 20 }}>

        {/* Search section */}
        <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 16, padding: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#5D6D7E', letterSpacing: '.4px', textTransform: 'uppercase', marginBottom: 10 }}>
            Requête
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={onKey}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              placeholder="Ex : Quelles factures dépassent 10 000 TND ce mois ?"
              style={{
                flex: 1,
                border: `2px solid ${inputFocused ? '#5BA3C9' : '#D5E8F5'}`,
                borderRadius: 12,
                padding: '14px 18px',
                fontSize: 16,
                color: '#1A1A2E',
                fontFamily: 'Inter, sans-serif',
                outline: 'none',
                transition: 'border .15s',
              }}
            />
            <button
              onClick={submit}
              disabled={loading}
              style={{
                background: '#1A3A5C',
                color: '#fff',
                border: 'none',
                borderRadius: 12,
                padding: '14px 24px',
                fontSize: 15,
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                fontFamily: 'Inter, sans-serif',
                whiteSpace: 'nowrap',
                opacity: loading ? 0.7 : 1,
              }}
            >
              🔍 Interroger
            </button>
          </div>
          <div style={{ marginTop: 10, fontSize: 12, color: '#5D6D7E' }}>
            Traitement <strong style={{ color: '#1A3A5C' }}>100% local</strong> — aucune donnée ne quitte la machine.{' '}
            Modèle : <strong style={{ color: '#1A3A5C' }}>qwen2.5:3b</strong> via Ollama.
          </div>
        </div>

        {/* Chips */}
        <div>
          <div style={{ fontSize: 12, color: '#5D6D7E', marginBottom: 8, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.4px' }}>
            Exemples de requêtes
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {CHIPS.map(chip => {
              const active = query === chip
              return (
                <span
                  key={chip}
                  onClick={() => setQuery(chip)}
                  style={{
                    background: active ? '#E3F0F9' : '#F0F4F9',
                    border: `1px solid ${active ? '#5BA3C9' : '#D5E8F5'}`,
                    borderRadius: 20,
                    padding: '6px 14px',
                    fontSize: 12,
                    color: active ? '#1A3A5C' : '#1A1A2E',
                    fontWeight: active ? 600 : 400,
                    cursor: 'pointer',
                  }}
                >
                  {chip}
                </span>
              )
            })}
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ textAlign: 'center', padding: 40, color: '#5D6D7E', fontSize: 15 }}>
            ⏳ Interrogation en cours…
          </div>
        )}

        {/* Result card */}
        {!loading && result && (
          <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 16, overflow: 'hidden' }}>
            {/* Header */}
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #D5E8F5', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 18 }}>📋</span>
              <span style={{ fontSize: 15, fontWeight: 600, flex: 1 }}>
                Résultats — {query.length > 40 ? query.slice(0, 40) + '…' : query}
              </span>
              <span style={{ fontSize: 12, color: '#5D6D7E' }}>
                Requête exécutée en {elapsed}s · {result.row_count} résultat{result.row_count !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Body */}
            <div style={{ padding: 20 }}>
              {result.error ? (
                <div style={{ background: '#FEF0EE', border: '1px solid #C0391B', borderRadius: 10, padding: 16, fontSize: 13, color: '#C0391B' }}>
                  ⚠️ {result.error}
                </div>
              ) : result.columns.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#5D6D7E', fontSize: 13, padding: 24 }}>
                  Aucun résultat pour cette requête.
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#F0F4F9' }}>
                      {result.columns.map(col => (
                        <th key={col} style={{ padding: '10px 14px', textAlign: 'left', fontSize: 11, color: '#5D6D7E', textTransform: 'uppercase', letterSpacing: '.4px', fontWeight: 600 }}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        style={{ borderTop: '1px solid #D5E8F5' }}
                        onMouseEnter={e => (e.currentTarget.style.background = '#F8FBFE')}
                        onMouseLeave={e => (e.currentTarget.style.background = '')}
                      >
                        {row.map((cell, ci) => (
                          <td key={ci} style={{ padding: '10px 14px' }}>
                            {cellDisplay(cell, ci, result.columns[ci])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* SQL expander */}
            {result.sql && (
              <div style={{ margin: '0 20px 16px', border: '1px solid #D5E8F5', borderRadius: 10, overflow: 'hidden' }}>
                <div
                  onClick={() => setSqlOpen(v => !v)}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', background: '#F0F4F9', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#5D6D7E' }}
                >
                  🔎 Voir la requête SQL générée {sqlOpen ? '▴' : '▾'}
                </div>
                {sqlOpen && (
                  <div style={{ background: '#1E2A3A', fontFamily: "'Courier New', monospace", fontSize: 12, color: '#A8C4E0', lineHeight: 1.6, padding: '14px 16px' }}>
                    <code dangerouslySetInnerHTML={{ __html: highlightSQL(result.sql) }} />
                  </div>
                )}
              </div>
            )}

            {/* Footer */}
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '12px 20px', borderTop: '1px solid #D5E8F5' }}>
              <button
                onClick={() => result && exportCSV(result.columns, result.rows)}
                style={{ border: '1px solid #D5E8F5', background: '#fff', borderRadius: 8, padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'Inter, sans-serif' }}
              >
                ⬇ Exporter CSV
              </button>
              <button
                onClick={() => navigate('/journal')}
                style={{ border: '1px solid #D5E8F5', background: '#fff', borderRadius: 8, padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'Inter, sans-serif' }}
              >
                📒 Voir journal
              </button>
              <button
                onClick={() => navigate('/invoices')}
                style={{ border: '1px solid #D5E8F5', background: '#fff', borderRadius: 8, padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'Inter, sans-serif' }}
              >
                📋 Filtrer dans Factures
              </button>
              <span style={{ fontSize: 12, color: '#5D6D7E', marginLeft: 'auto' }}>
                Total : {result.row_count} résultat{result.row_count !== 1 ? 's' : ''}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* History column */}
      <div style={{ width: 280, flexShrink: 0 }}>
        <div style={{ background: '#fff', border: '1px solid #D5E8F5', borderRadius: 16, overflow: 'hidden' }}>
          <div style={{ padding: '16px 18px', borderBottom: '1px solid #D5E8F5', fontSize: 13, fontWeight: 600, color: '#1A3A5C' }}>
            🕒 Historique des requêtes
          </div>
          {history.length === 0 ? (
            <div style={{ padding: 16, fontSize: 12, color: '#5D6D7E' }}>Aucune requête</div>
          ) : (
            history.map((item, i) => (
              <div
                key={i}
                onClick={() => setQuery(item.query)}
                style={{ padding: '12px 18px', borderBottom: i < history.length - 1 ? '1px solid #D5E8F5' : 'none', cursor: 'pointer' }}
                onMouseEnter={e => (e.currentTarget.style.background = '#F0F4F9')}
                onMouseLeave={e => (e.currentTarget.style.background = '')}
              >
                <div style={{ fontSize: 12, fontWeight: 600, color: '#1A1A2E', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item.query}
                </div>
                <div style={{ fontSize: 11, color: '#5D6D7E', marginTop: 3 }}>
                  {relativeTime(item.timestamp)} ·{' '}
                  <span style={{ color: '#1D9E76', fontWeight: 600 }}>{item.resultCount} résultats</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
