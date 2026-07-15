import { useState, useEffect } from 'react'
import { Download, Bot } from 'lucide-react'
import type { JournalEntry } from '../../types'
import { listJournal } from '../../api/endpoints'
import { formatTND } from '../../utils/formatters'
import PageSpinner from '../../components/ui/PageSpinner'

function formatDateFr(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function groupByDate(entries: JournalEntry[]): [string, JournalEntry[]][] {
  const map = new Map<string, JournalEntry[]>()
  for (const e of entries) {
    const k = e.date_ecriture
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(e)
  }
  return Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]))
}

function today() { return new Date().toISOString().slice(0, 10) }
function yearStart() { return `${new Date().getFullYear()}-01-01` }

export default function Journaux() {
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [startDate, setStartDate] = useState(yearStart)
  const [endDate, setEndDate] = useState(today)
  const [compteFilter, setCompteFilter] = useState('Tous')
  const [typeFilter, setTypeFilter] = useState('Tous')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    queueMicrotask(() => {
      setLoading(true)
      setError(false)
      listJournal(startDate, endDate)
        .then(data => setEntries(data))
        .catch(() => setError(true))
        .finally(() => setLoading(false))
    })
  }, [startDate, endDate])

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const allLines = entries.flatMap(e => e.lines)
  const totalDebit = allLines.reduce((s, l) => s + l.debit, 0)
  const totalCredit = allLines.reduce((s, l) => s + l.credit, 0)
  const balanced = Math.abs(totalDebit - totalCredit) < 0.005

  const comptes = Array.from(new Set(allLines.map(l => l.compte))).sort()
  const grouped = groupByDate(entries)

  const kpiCards = [
    { label: 'Total écritures', value: allLines.length.toString() },
    { label: 'Total débit', value: formatTND(totalDebit) },
    { label: 'Total crédit', value: formatTND(totalCredit) },
    {
      label: 'Solde (Δ)',
      value: formatTND(Math.abs(totalDebit - totalCredit)),
      check: balanced,
    },
  ]

  return (
    <div style={{ background: '#F0F4F9', minHeight: '100vh' }}>
      {/* Page header */}
      <div
        className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}
      >
        <h1 className="flex-1 text-lg font-bold" style={{ color: '#1A1A2E' }}>📒 Journal Comptable</h1>
        <span className="px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#E3F0F9', color: '#5BA3C9' }}>
          ● Comptable
        </span>
      </div>

      {/* Filter bar */}
      <div
        className="flex items-center gap-3 px-6 py-3 border-b"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}
      >
        <input
          type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
          className="text-sm px-3 py-1.5 rounded-lg border outline-none"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
        />
        <span className="text-sm" style={{ color: '#5D6D7E' }}>—</span>
        <input
          type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
          className="text-sm px-3 py-1.5 rounded-lg border outline-none"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
        />
        <select
          value={compteFilter} onChange={e => setCompteFilter(e.target.value)}
          className="text-sm px-3 py-1.5 rounded-lg border outline-none"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
        >
          <option value="Tous">Compte: Tous</option>
          {comptes.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
          className="text-sm px-3 py-1.5 rounded-lg border outline-none"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
        >
          <option value="Tous">Type: Tous</option>
          <option value="DEBIT">Débit</option>
          <option value="CREDIT">Crédit</option>
        </select>
        <div className="flex-1" />
        <button
          onClick={() => {
            const header = 'Date;Référence;Description;Compte;Libellé;Débit (TND);Crédit (TND)'
            const rows = entries.flatMap(e => e.lines.map(l => {
              const [y, m, d] = e.date_ecriture.split('-')
              return [`${d}/${m}/${y}`, e.reference, `"${e.description}"`, l.compte, l.libelle, l.debit.toFixed(3), l.credit.toFixed(3)].join(';')
            }))
            const csv = [header, ...rows].join('\n')
            const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a'); a.href = url
            a.download = `journal_${new Date().toISOString().slice(0, 10)}.csv`
            a.click(); URL.revokeObjectURL(url)
          }}
          className="flex items-center gap-1.5 text-xs font-semibold text-white px-4 py-2 rounded-lg"
          style={{ background: '#1A3A5C' }}
        >
          <Download size={13} />
          Exporter Journal (.csv)
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4 mx-6 my-4">
        {kpiCards.map(card => (
          <div
            key={card.label}
            className="bg-white rounded-xl border p-4"
            style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}
          >
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{card.label}</p>
            <div className="flex items-center gap-1.5">
              <p className="text-xl font-bold leading-tight" style={{ color: '#1A1A2E' }}>{card.value}</p>
              {'check' in card && (
                <span className="text-base font-bold" style={{ color: card.check ? '#1D9E76' : '#C0391B' }}>
                  {card.check ? '✓' : '✗'}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Grouped entries */}
      <div className="px-6 pb-6 space-y-4">
        {grouped.map(([date, dayEntries]) => {
          const dayLines = dayEntries.flatMap(e => e.lines)
          const dayDebit = dayLines.reduce((s, l) => s + l.debit, 0)
          const dayCredit = dayLines.reduce((s, l) => s + l.credit, 0)
          const dayBalanced = Math.abs(dayDebit - dayCredit) < 0.005

          const displayLines = dayLines.filter(l => {
            if (compteFilter !== 'Tous' && l.compte !== compteFilter) return false
            if (typeFilter === 'DEBIT' && l.debit === 0) return false
            if (typeFilter === 'CREDIT' && l.credit === 0) return false
            return true
          })

          const lineToRef = new Map(
            dayEntries.flatMap(e => e.lines.map(l => [l, e.reference]))
          )
          const lineToExplanation = new Map(
            dayEntries.flatMap(e => e.lines.map(l => [l, e.accounting_explanation ?? null]))
          )

          return (
            <div key={date} className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
              <div className="px-4 py-2.5 text-sm font-semibold" style={{ background: '#F0F4F9', color: '#1A1A2E' }}>
                📅 {formatDateFr(date)} — {dayEntries.length} écriture{dayEntries.length > 1 ? 's' : ''}
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b" style={{ borderColor: '#D5E8F5' }}>
                    {['Compte', 'Libellé', 'Référence', 'Débit (TND)', 'Crédit (TND)'].map(h => (
                      <th
                        key={h}
                        className={`px-4 py-2.5 text-xs font-semibold uppercase ${h.startsWith('Déb') || h.startsWith('Cré') ? 'text-right' : 'text-left'}`}
                        style={{ color: '#5D6D7E' }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displayLines.map((line, i) => (
                    <tr key={i} className="border-b" style={{ borderColor: '#F0F4F9' }}>
                      <td className="px-4 py-2.5">
                        <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: '#EFF4FA', color: '#1A3A5C' }}>
                          {line.compte}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-sm" style={{ color: '#1A1A2E' }}>{line.libelle}</td>
                      <td className="px-4 py-2.5 text-xs font-mono" style={{ color: '#5D6D7E' }}>
                        <span className="flex items-center gap-1.5">
                          {lineToRef.get(line) ?? ''}
                          {lineToExplanation.get(line) && (
                            <span
                              title={lineToExplanation.get(line) ?? ''}
                              className="cursor-help shrink-0"
                              style={{ color: '#804CD7' }}
                            >
                              <Bot size={11} />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-sm font-medium text-right" style={{ color: '#1A1A2E' }}>
                        {line.debit > 0 ? line.debit.toLocaleString('fr-TN', { minimumFractionDigits: 3 }) : ''}
                      </td>
                      <td className="px-4 py-2.5 text-sm font-medium text-right" style={{ color: '#C0391B' }}>
                        {line.credit > 0 ? line.credit.toLocaleString('fr-TN', { minimumFractionDigits: 3 }) : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center px-4 py-2.5" style={{ background: '#E8F5F0' }}>
                <span className="flex-1 text-sm font-medium" style={{ color: '#1D9E76' }}>
                  Total journée {dayBalanced ? '✓ Équilibre respecté' : '✗ Déséquilibre'}
                </span>
                <span className="text-sm font-semibold w-44 text-right" style={{ color: '#1A1A2E' }}>
                  {dayDebit.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                </span>
                <span className="text-sm font-semibold w-44 text-right" style={{ color: '#C0391B' }}>
                  {dayCredit.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
