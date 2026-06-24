import { useState, useEffect } from 'react'
import { Plus } from 'lucide-react'
import type { Asset } from '../types'
import { listAssets } from '../api/endpoints'
import { formatTND } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'

const NOW = new Date('2026-06-22')

function computeDepreciation(asset: Asset) {
  const start = new Date(asset.acquisition_date)
  const yearsElapsed = Math.max(0, (NOW.getTime() - start.getTime()) / (365.25 * 24 * 3600 * 1000))
  const annual = asset.acquisition_cost_ht / asset.useful_life_years
  const cumul = Math.min(asset.acquisition_cost_ht, Math.round(annual * yearsElapsed))
  const vnc = asset.acquisition_cost_ht - cumul
  const pct = Math.round((cumul / asset.acquisition_cost_ht) * 100)
  return { annual: Math.round(annual), cumul, vnc, pct }
}

const COMPTE_META: Record<string, { label: string; bg: string; color: string }> = {
  '2183': { label: 'Matériel informatique', bg: '#EFF4FA', color: '#1A3A5C' },
  '205':  { label: 'Licences logicielles',  bg: '#F3E5F5', color: '#804CD7' },
  '2184': { label: 'Matériel réseau',        bg: '#E8F5F0', color: '#1D9E76' },
}

function compteMeta(compte: string) {
  return COMPTE_META[compte] ?? { label: 'Équipement technique', bg: '#FFF8E8', color: '#F0A600' }
}

function formatAcqDate(iso: string) {
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

const TABS = ['Registre des actifs', "Plan d'amortissement", 'Ajouter un actif']

export default function CAPEX() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    listAssets()
      .then(data => setAssets(data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const depreciations = assets.map(a => computeDepreciation(a))
  const totalBrut = assets.reduce((s, a) => s + a.acquisition_cost_ht, 0)
  const totalCumul = depreciations.reduce((s, d) => s + d.cumul, 0)
  const totalVNC = depreciations.reduce((s, d) => s + d.vnc, 0)

  const categories = Array.from(new Set(assets.map(a => compteMeta(a.compte_immobilisation).label)))

  return (
    <div style={{ background: '#F0F4F9', minHeight: '100vh' }}>
      {/* Page header */}
      <div
        className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}
      >
        <h1 className="flex-1 text-lg font-bold" style={{ color: '#1A1A2E' }}>🏗️ Registre des Immobilisations</h1>
        <span className="px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#E3F0F9', color: '#5BA3C9' }}>
          ● Comptable
        </span>
        <button
          className="flex items-center gap-1.5 text-sm font-semibold text-white px-4 py-2 rounded-lg"
          style={{ background: '#F0A600' }}
        >
          <Plus size={14} />
          Ajouter un actif
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 px-6 pt-4 border-b" style={{ borderColor: '#D5E8F5' }}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className="px-4 py-2 text-sm font-medium rounded-t-lg transition-all"
            style={
              activeTab === i
                ? { background: '#1A3A5C', color: '#fff' }
                : { color: '#5D6D7E', background: 'transparent' }
            }
          >
            {tab}
          </button>
        ))}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4 mx-6 my-4">
        {[
          { label: 'Total actifs', value: String(assets.length), sub: `${categories.length} catégories` },
          { label: 'Valeur brute', value: formatTND(totalBrut, 0), sub: 'Cumulé' },
          { label: 'Amort. cumulé', value: formatTND(totalCumul, 0), sub: 'Toutes catégories' },
          { label: 'Valeur nette (VNC)', value: formatTND(totalVNC, 0), sub: 'Au 18/06/2026' },
        ].map(card => (
          <div key={card.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
            <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{card.label}</p>
            <p className="text-xl font-bold" style={{ color: '#1A1A2E' }}>{card.value}</p>
            <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Asset grid */}
      {activeTab === 0 && (
        <div className="grid grid-cols-3 gap-4 px-6 pb-6">
          {assets.map((asset, i) => {
            const dep = depreciations[i]
            const meta = compteMeta(asset.compte_immobilisation)
            const barColor = dep.pct < 33 ? '#1D9E76' : dep.pct < 66 ? '#F0A600' : '#C0391B'

            return (
              <div
                key={asset.id}
                className="bg-white rounded-xl border p-4"
                style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}
              >
                <span
                  className="inline-block text-xs font-medium px-2 py-0.5 rounded-full mb-2"
                  style={{ background: meta.bg, color: meta.color }}
                >
                  {meta.label}
                </span>
                <p className="font-semibold text-sm mb-0.5" style={{ color: '#1A1A2E' }}>{asset.designation}</p>
                <p className="text-xs mb-3" style={{ color: '#5D6D7E' }}>
                  Linéaire {asset.useful_life_years} ans · Acquis {formatAcqDate(asset.acquisition_date)}
                </p>
                <div className="h-2 rounded-full mb-2 overflow-hidden" style={{ background: '#E8EFF7' }}>
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${dep.pct}%`, background: barColor }}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>
                    VNC: {formatTND(dep.vnc, 0)}
                  </span>
                  <span className="text-xs" style={{ color: '#5D6D7E' }}>{dep.pct}% amorti</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {activeTab === 1 && (
        <div className="px-6 pb-6 space-y-4">
          {assets.map(asset => {
            const acqYear = parseInt(asset.acquisition_date.slice(0, 4), 10)
            const annual = Math.round(asset.acquisition_cost_ht / asset.useful_life_years)
            const rows = Array.from({ length: asset.useful_life_years }, (_, i) => {
              const year = acqYear + i
              const cumul = Math.min(asset.acquisition_cost_ht, annual * (i + 1))
              const vnc = Math.max(0, asset.acquisition_cost_ht - cumul)
              const pct = Math.round((cumul / asset.acquisition_cost_ht) * 100)
              const isPast = year < NOW.getFullYear()
              const isCurrent = year === NOW.getFullYear()
              return { year, annuite: annual, cumul, vnc, pct, isPast, isCurrent }
            })
            const meta = compteMeta(asset.compte_immobilisation)
            return (
              <div key={asset.id} className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
                <div className="flex items-center gap-3 px-4 py-3" style={{ background: '#F0F4F9' }}>
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ background: meta.bg, color: meta.color }}>
                    {meta.label}
                  </span>
                  <span className="font-semibold text-sm flex-1" style={{ color: '#1A1A2E' }}>{asset.designation}</span>
                  <span className="text-xs" style={{ color: '#5D6D7E' }}>
                    {formatTND(asset.acquisition_cost_ht, 0)} · {asset.useful_life_years} ans · {formatAcqDate(asset.acquisition_date)}
                  </span>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b" style={{ borderColor: '#D5E8F5' }}>
                      {['Exercice', 'Annuité (TND)', 'Amort. cumulé (TND)', 'VNC (TND)', '% amorti'].map(h => (
                        <th key={h} className="px-4 py-2 text-xs font-semibold uppercase text-right first:text-left" style={{ color: '#5D6D7E' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(row => (
                      <tr
                        key={row.year}
                        className="border-b"
                        style={{
                          borderColor: '#F0F4F9',
                          background: row.isCurrent ? '#EFF8F3' : row.isPast ? 'transparent' : '#FAFBFC',
                          opacity: row.isPast ? 0.7 : 1,
                        }}
                      >
                        <td className="px-4 py-2 font-semibold text-sm" style={{ color: row.isCurrent ? '#1D9E76' : '#1A1A2E' }}>
                          {row.year}{row.isCurrent ? ' ← en cours' : ''}
                        </td>
                        <td className="px-4 py-2 text-right text-sm" style={{ color: '#1A1A2E' }}>
                          {row.annuite.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                        </td>
                        <td className="px-4 py-2 text-right text-sm" style={{ color: '#1A1A2E' }}>
                          {row.cumul.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                        </td>
                        <td className="px-4 py-2 text-right text-sm font-semibold" style={{ color: row.vnc === 0 ? '#C0391B' : '#1A3A5C' }}>
                          {row.vnc.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: '#E8EFF7' }}>
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${row.pct}%`,
                                  background: row.pct < 33 ? '#1D9E76' : row.pct < 66 ? '#F0A600' : '#C0391B',
                                }}
                              />
                            </div>
                            <span className="text-xs w-10 text-right" style={{ color: '#5D6D7E' }}>{row.pct}%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr style={{ background: '#E8F5F0' }}>
                      <td className="px-4 py-2 text-sm font-semibold" style={{ color: '#1D9E76' }}>Total</td>
                      <td className="px-4 py-2 text-right text-sm font-semibold" style={{ color: '#1A1A2E' }}>
                        {asset.acquisition_cost_ht.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                      </td>
                      <td className="px-4 py-2 text-right text-sm font-semibold" style={{ color: '#1A1A2E' }}>
                        {asset.acquisition_cost_ht.toLocaleString('fr-TN', { minimumFractionDigits: 3 })}
                      </td>
                      <td className="px-4 py-2 text-right text-sm font-semibold" style={{ color: '#C0391B' }}>0,000</td>
                      <td className="px-4 py-2 text-right text-xs font-semibold" style={{ color: '#1D9E76' }}>100%</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )
          })}
        </div>
      )}

      {activeTab === 2 && (
        <div className="px-6 pb-6">
          <div className="bg-white rounded-xl border p-6" style={{ borderColor: '#D5E8F5' }}>
            <p className="text-sm text-center" style={{ color: '#5D6D7E' }}>Formulaire d'ajout — à venir</p>
          </div>
        </div>
      )}
    </div>
  )
}
