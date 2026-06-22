import { useState, useEffect } from 'react'
import { Plus } from 'lucide-react'
import type { Asset } from '../types'
import { listAssets } from '../api/endpoints'
import { assetsMock } from '../data/mockInvoices'
import { formatTND } from '../utils/formatters'

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
  const [assets, setAssets] = useState<Asset[]>(assetsMock as unknown as Asset[])
  const [activeTab, setActiveTab] = useState(0)

  useEffect(() => {
    listAssets()
      .then(data => { if (data.length) setAssets(data) })
      .catch(() => setAssets(assetsMock as unknown as Asset[]))
  }, [])

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
        <div className="px-6 pb-6">
          <div className="bg-white rounded-xl border p-6" style={{ borderColor: '#D5E8F5' }}>
            <p className="text-sm text-center" style={{ color: '#5D6D7E' }}>Plan d'amortissement — à venir</p>
          </div>
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
