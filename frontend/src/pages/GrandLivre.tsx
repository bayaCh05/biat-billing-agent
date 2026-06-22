import { useState, useEffect } from 'react'
import PageHeader from '../components/ui/PageHeader'
import { listJournal } from '../api/endpoints'
import { grandLivreMock } from '../data/mockJournaux'
import { formatTND } from '../utils/formatters'
import type { JournalEntry } from '../types'

type GrandLivreData = Record<string, {
  libelle: string
  lines: { date: string; ref: string; desc: string; debit: number; credit: number }[]
}>

function buildGrandLivre(entries: JournalEntry[]): GrandLivreData {
  const result: GrandLivreData = {}
  for (const entry of entries) {
    for (const line of entry.lines) {
      if (!result[line.compte]) {
        result[line.compte] = { libelle: line.libelle, lines: [] }
      }
      result[line.compte].lines.push({
        date: entry.date_ecriture,
        ref: entry.reference,
        desc: entry.description,
        debit: line.debit,
        credit: line.credit,
      })
    }
  }
  return result
}

function exportFEC(gl: GrandLivreData) {
  const header = 'JournalCode;JournalLib;EcritureNum;EcritureDate;CompteNum;CompteLib;Debit;Credit'
  const rows: string[] = []
  for (const [compte, data] of Object.entries(gl)) {
    for (const line of data.lines) {
      rows.push([
        'ACH', data.libelle, line.ref,
        line.date.replace(/-/g, ''), compte, data.libelle,
        line.debit.toFixed(3), line.credit.toFixed(3),
      ].join(';'))
    }
  }
  const csv = [header, ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const ym = new Date().toISOString().slice(0, 7).replace('-', '')
  a.download = `grand_livre_${ym}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function GrandLivre() {
  const [gl, setGl] = useState<GrandLivreData>(grandLivreMock)
  const [search, setSearch] = useState('')

  useEffect(() => {
    listJournal()
      .then(entries => {
        const built = buildGrandLivre(entries)
        if (Object.keys(built).length > 0) setGl(built)
      })
      .catch(() => { /* keep mock */ })
  }, [])

  const allComptes = Object.keys(gl)
  const comptes = allComptes.filter(c =>
    c.includes(search) || gl[c].libelle.toLowerCase().includes(search.toLowerCase())
  )
  const [selected, setSelected] = useState<string>('')
  const activeCompte = selected && gl[selected] ? selected : (comptes[0] ?? '')
  const compte = gl[activeCompte]

  const totalDebit  = compte ? compte.lines.reduce((s, l) => s + l.debit,  0) : 0
  const totalCredit = compte ? compte.lines.reduce((s, l) => s + l.credit, 0) : 0
  const solde = totalDebit - totalCredit

  return (
    <div>
      <PageHeader title="📚 Grand Livre" badge="Par compte PCE">
        <button
          onClick={() => exportFEC(gl)}
          style={{
            background: '#1A3A5C', color: '#fff', border: 'none',
            borderRadius: 8, padding: '7px 14px', fontSize: 12,
            fontWeight: 600, cursor: 'pointer', fontFamily: 'Inter, sans-serif',
          }}
        >
          ⬇ Exporter FEC
        </button>
      </PageHeader>

      <div className="p-6 grid gap-6" style={{ gridTemplateColumns: '220px 1fr' }}>
        {/* Account list */}
        <div className="bg-white rounded-xl border overflow-hidden h-fit" style={{ borderColor: '#D5E8F5' }}>
          <div
            className="px-3 py-2"
            style={{ background: '#F0F4F9', borderBottom: '1px solid #D5E8F5' }}
          >
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filtrer comptes…"
              style={{
                width: '100%', border: '1px solid #D5E8F5', borderRadius: 6,
                padding: '5px 8px', fontSize: 12, outline: 'none',
                fontFamily: 'Inter, sans-serif', color: '#1A1A2E',
              }}
            />
          </div>
          {comptes.length === 0 && (
            <p className="px-3 py-3 text-xs" style={{ color: '#5D6D7E' }}>Aucun compte</p>
          )}
          {comptes.map(c => (
            <button
              key={c}
              onClick={() => setSelected(c)}
              className="w-full text-left px-3 py-2.5 text-sm transition-all"
              style={{
                background: activeCompte === c ? '#E3F0F9' : 'transparent',
                color: activeCompte === c ? '#1A3A5C' : '#1A1A2E',
                fontWeight: activeCompte === c ? 600 : 400,
                borderBottom: '1px solid #F0F4F9',
              }}
            >
              <span
                className="font-mono text-xs mr-2 px-1.5 py-0.5 rounded"
                style={{
                  background: activeCompte === c ? '#1A3A5C' : '#F0F4F9',
                  color: activeCompte === c ? '#fff' : '#5D6D7E',
                }}
              >
                {c}
              </span>
              {gl[c].libelle}
            </button>
          ))}
        </div>

        {/* Lines */}
        <div className="space-y-4">
          {!compte ? (
            <p className="text-sm" style={{ color: '#5D6D7E' }}>Sélectionnez un compte.</p>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-4">
                {[
                  { label: 'Total Débit',  value: formatTND(totalDebit),  color: '#1D9E76' },
                  { label: 'Total Crédit', value: formatTND(totalCredit), color: '#F0A600' },
                  { label: 'Solde',        value: `${solde >= 0 ? '+' : ''}${formatTND(Math.abs(solde))}`, color: solde >= 0 ? '#1A3A5C' : '#C0391B' },
                ].map(s => (
                  <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
                    <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
                    <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
                  </div>
                ))}
              </div>

              <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
                <div className="px-4 py-3" style={{ background: '#F0F4F9', borderBottom: '1px solid #D5E8F5' }}>
                  <p className="text-sm font-semibold" style={{ color: '#1A3A5C' }}>
                    Compte {activeCompte} — {compte.libelle}
                  </p>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr style={{ borderBottom: '1px solid #F0F4F9' }}>
                      {['Date', 'Référence', 'Description', 'Débit', 'Crédit'].map(h => (
                        <th key={h} className="text-left px-4 py-2.5 text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compte.lines.map((line, i) => (
                      <tr
                        key={i}
                        className="hover:bg-[#F0F4F9] transition-colors"
                        style={{ borderBottom: i < compte.lines.length - 1 ? '1px solid #F0F4F9' : 'none' }}
                      >
                        <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{line.date}</td>
                        <td className="px-4 py-3">
                          <span className="font-mono text-xs px-1.5 py-0.5 rounded" style={{ background: '#E3F0F9', color: '#1A3A5C' }}>
                            {line.ref}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm" style={{ color: '#1A1A2E' }}>{line.desc}</td>
                        <td className="px-4 py-3 font-semibold text-right" style={{ color: line.debit > 0 ? '#1D9E76' : '#5D6D7E' }}>
                          {line.debit > 0 ? formatTND(line.debit) : '—'}
                        </td>
                        <td className="px-4 py-3 font-semibold text-right" style={{ color: line.credit > 0 ? '#F0A600' : '#5D6D7E' }}>
                          {line.credit > 0 ? formatTND(line.credit) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
