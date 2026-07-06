import { useState, useEffect } from 'react'
import { Plus, CheckCircle } from 'lucide-react'
import type { Asset } from '../../types'
import { listAssets, createAsset } from '../../api/endpoints'
import { formatTND } from '../../utils/formatters'
import PageSpinner from '../../components/ui/PageSpinner'

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

const COMPTE_OPTIONS = [
  { value: '2183', label: 'Matériel informatique',  amort: '2893' },
  { value: '205',  label: 'Licences logicielles',   amort: '2805' },
  { value: '2184', label: 'Matériel réseau',         amort: '2894' },
]

const COMPTE_META: Record<string, { label: string; bg: string; color: string }> = {
  '2183': { label: 'Matériel informatique', bg: '#EFF4FA', color: '#1A3A5C' },
  '205':  { label: 'Licences logicielles',  bg: '#F3E5F5', color: '#804CD7' },
  '2184': { label: 'Matériel réseau',        bg: '#E8F5F0', color: '#1D9E76' },
}

const EMPTY_FORM = {
  designation: '',
  compte_immobilisation: '2183',
  acquisition_date: '',
  acquisition_cost_ht: '',
  useful_life_years: '5',
  depreciation_method: 'linear',
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

  // Add asset form state
  const [form, setForm] = useState(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)
  const [submitError, setSubmitError] = useState('')

  const loadAssets = () => listAssets().then(setAssets).catch(() => setError(true))

  useEffect(() => {
    loadAssets().finally(() => setLoading(false))
  }, [])

  const compteOpt = COMPTE_OPTIONS.find(c => c.value === form.compte_immobilisation) ?? COMPTE_OPTIONS[0]

  const handleSubmit = async () => {
    if (!form.designation.trim() || !form.acquisition_date || !form.acquisition_cost_ht) {
      setSubmitError('Remplissez tous les champs obligatoires.')
      return
    }
    setSubmitting(true)
    setSubmitError('')
    try {
      await createAsset({
        designation: form.designation.trim(),
        compte_immobilisation: form.compte_immobilisation,
        compte_amortissement: compteOpt.amort,
        acquisition_date: form.acquisition_date,
        acquisition_cost_ht: parseFloat(form.acquisition_cost_ht),
        useful_life_years: parseInt(form.useful_life_years, 10),
        depreciation_method: form.depreciation_method,
      })
      setSubmitSuccess(true)
      await loadAssets()
    } catch {
      setSubmitError("Erreur lors de l'enregistrement — vérifiez que l'API est démarrée.")
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
    setForm(EMPTY_FORM)
    setSubmitSuccess(false)
    setSubmitError('')
  }

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
          onClick={() => { setActiveTab(2); resetForm() }}
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
        <div className="px-6 pb-6 max-w-2xl">
          <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
            <div className="px-6 py-4 border-b" style={{ borderColor: '#D5E8F5', background: '#F7FAFD' }}>
              <p className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>Nouvelle immobilisation</p>
              <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                L'actif sera ajouté au registre et son plan d'amortissement calculé automatiquement.
              </p>
            </div>

            <div className="p-6">
              {submitSuccess ? (
                <div className="flex flex-col items-center gap-4 py-6 text-center">
                  <CheckCircle size={40} style={{ color: '#1D9E76' }} />
                  <div>
                    <p className="text-base font-bold" style={{ color: '#1A1A2E' }}>Actif enregistré</p>
                    <p className="text-sm mt-1" style={{ color: '#5D6D7E' }}>
                      {form.designation} a été ajouté au registre des immobilisations.
                    </p>
                  </div>
                  <div className="flex gap-3">
                    <button
                      onClick={resetForm}
                      className="px-5 py-2 rounded-xl text-sm font-semibold border"
                      style={{ borderColor: '#D5E8F5', color: '#1A3A5C' }}
                    >
                      Ajouter un autre
                    </button>
                    <button
                      onClick={() => setActiveTab(0)}
                      className="px-5 py-2 rounded-xl text-sm font-semibold text-white"
                      style={{ background: '#1A3A5C' }}
                    >
                      Voir le registre
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-5">
                  {/* Désignation */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                      Désignation <span style={{ color: '#C0391B' }}>*</span>
                    </label>
                    <input
                      type="text"
                      value={form.designation}
                      onChange={e => setForm(f => ({ ...f, designation: e.target.value }))}
                      placeholder="Ex : Serveur Dell PowerEdge R750"
                      className="rounded-lg border px-3 py-2.5 text-sm outline-none w-full"
                      style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                    />
                  </div>

                  {/* Catégorie */}
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                      Catégorie (compte PCE) <span style={{ color: '#C0391B' }}>*</span>
                    </label>
                    <select
                      value={form.compte_immobilisation}
                      onChange={e => setForm(f => ({ ...f, compte_immobilisation: e.target.value }))}
                      className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                      style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                    >
                      {COMPTE_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>
                          {opt.value} — {opt.label}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs" style={{ color: '#5D6D7E' }}>
                      Compte amortissement associé : <span className="font-mono">{compteOpt.amort}</span>
                    </p>
                  </div>

                  {/* Date + Coût */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                        Date d'acquisition <span style={{ color: '#C0391B' }}>*</span>
                      </label>
                      <input
                        type="date"
                        value={form.acquisition_date}
                        onChange={e => setForm(f => ({ ...f, acquisition_date: e.target.value }))}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                        Coût d'acquisition HT (TND) <span style={{ color: '#C0391B' }}>*</span>
                      </label>
                      <input
                        type="number"
                        min={0}
                        step={0.001}
                        value={form.acquisition_cost_ht}
                        onChange={e => setForm(f => ({ ...f, acquisition_cost_ht: e.target.value }))}
                        placeholder="0.000"
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      />
                    </div>
                  </div>

                  {/* Durée + Méthode */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                        Durée d'amortissement (années)
                      </label>
                      <select
                        value={form.useful_life_years}
                        onChange={e => setForm(f => ({ ...f, useful_life_years: e.target.value }))}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      >
                        {[1,2,3,4,5,6,7,8,10,12,15,20].map(n => (
                          <option key={n} value={n}>{n} an{n > 1 ? 's' : ''}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                        Méthode d'amortissement
                      </label>
                      <select
                        value={form.depreciation_method}
                        onChange={e => setForm(f => ({ ...f, depreciation_method: e.target.value }))}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      >
                        <option value="linear">Linéaire</option>
                        <option value="degressive">Dégressif</option>
                      </select>
                    </div>
                  </div>

                  {/* Preview */}
                  {form.acquisition_cost_ht && parseFloat(form.acquisition_cost_ht) > 0 && (
                    <div
                      className="rounded-lg p-4 text-sm"
                      style={{ background: '#F0F4F9', borderLeft: '3px solid #1A3A5C' }}
                    >
                      <p className="font-semibold mb-1" style={{ color: '#1A3A5C' }}>Aperçu</p>
                      <p style={{ color: '#5D6D7E' }}>
                        Annuité linéaire :{' '}
                        <span className="font-semibold" style={{ color: '#1A1A2E' }}>
                          {formatTND(parseFloat(form.acquisition_cost_ht) / parseInt(form.useful_life_years, 10))}
                        </span>
                        {' '}/ an sur {form.useful_life_years} ans
                      </p>
                    </div>
                  )}

                  {submitError && (
                    <p className="text-xs" style={{ color: '#C0391B' }}>{submitError}</p>
                  )}

                  <div className="flex justify-end gap-3 pt-2">
                    <button
                      onClick={resetForm}
                      className="px-4 py-2.5 rounded-xl text-sm font-medium border"
                      style={{ borderColor: '#D5E8F5', color: '#5D6D7E' }}
                    >
                      Réinitialiser
                    </button>
                    <button
                      onClick={handleSubmit}
                      disabled={submitting}
                      className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white disabled:opacity-50 transition-opacity"
                      style={{ background: '#F0A600' }}
                    >
                      {submitting ? 'Enregistrement…' : 'Enregistrer l\'actif'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
