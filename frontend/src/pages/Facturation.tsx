import { useState, useEffect } from 'react'
import { Plus, X, CheckCircle } from 'lucide-react'
import type { Project, ProjectStatus, ProjectPhase, ClientTemplate, ClientInvoice } from '../types'
import { listProjects, listTemplates, generateInvoice, listClientInvoices, listProjectPhases } from '../api/endpoints'
import { formatTND } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'

const MONTHS = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre']

const STATUS_MAP: Record<ProjectStatus, { label: string; bg: string; color: string }> = {
  ACTIVE:    { label: 'OUVERT',   bg: '#E8F5F0', color: '#1D9E76' },
  COMPLETED: { label: 'CLOS',     bg: '#EFF4FA', color: '#5BA3C9' },
  ON_HOLD:   { label: 'SUSPENDU', bg: '#FFF8E8', color: '#F0A600' },
  CANCELLED: { label: 'ANNULÉ',   bg: '#FDECEA', color: '#C0391B' },
}

const PHASE_STATUS: Record<string, { label: string; color: string }> = {
  OPEN:        { label: 'OUVERTE',  color: '#5D6D7E' },
  IN_PROGRESS: { label: 'EN COURS', color: '#F0A600' },
  CLOSED:      { label: 'CLÔTURÉE', color: '#1D9E76' },
}

const TABS = ['Projets & Chartes', 'Fiche Mensuelle', 'Historique']

function barColor(pct: number, status: ProjectStatus): string {
  if (status === 'COMPLETED' || pct >= 100) return '#C0391B'
  if (pct >= 80) return '#F0A600'
  return '#1D9E76'
}

function ProjectCard({ project, onFiche }: { project: Project; onFiche: (id: string) => void }) {
  const pct = project.budget_jh > 0 ? Math.round((project.consumed_jh / project.budget_jh) * 100) : 0
  const s = STATUS_MAP[project.status]
  const bar = barColor(pct, project.status)

  return (
    <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5', boxShadow: '0 1px 4px rgba(26,58,92,0.06)' }}>
      <div className="flex items-start justify-between gap-2 mb-0.5">
        <p className="font-semibold text-sm leading-snug" style={{ color: '#1A1A2E' }}>{project.name}</p>
        <span
          className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full"
          style={{ background: s.bg, color: s.color }}
        >
          {s.label}
        </span>
      </div>
      <p className="text-xs mb-3" style={{ color: '#5D6D7E' }}>{project.client}</p>

      <p className="text-sm font-semibold mb-1.5" style={{ color: '#1A1A2E' }}>
        {project.consumed_jh} JH / {project.budget_jh} JH
      </p>
      <div className="h-2 rounded-full mb-1 overflow-hidden" style={{ background: '#E8EFF7' }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, pct)}%`, background: bar }}
        />
      </div>
      <p className="text-xs mb-4" style={{ color: '#5D6D7E' }}>{pct}%</p>

      <div className="flex gap-2">
        <button
          onClick={() => onFiche(project.id)}
          className="flex items-center gap-1.5 text-xs font-semibold text-white px-3 py-1.5 rounded-lg"
          style={{ background: '#1A3A5C' }}
        >
          📋 Fiche mensuelle
        </button>
        <button
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg"
          style={{ background: '#EFF4FA', color: '#1A3A5C' }}
        >
          📄 Historique
        </button>
      </div>
    </div>
  )
}

export default function Facturation() {
  const [activeTab, setActiveTab] = useState(0)
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const [clientInvoices, setClientInvoices] = useState<ClientInvoice[]>([])

  // Fiche mensuelle state
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [ficheMonth, setFicheMonth] = useState(new Date().getMonth() + 1)
  const [ficheYear, setFicheYear] = useState(new Date().getFullYear())
  const [phases, setPhases] = useState<ProjectPhase[]>([])
  const [phasesLoading, setPhasesLoading] = useState(false)
  const [jhInputs, setJhInputs] = useState<Record<string, number>>({})

  // Modal state
  const [showModal, setShowModal] = useState(false)
  const [templates, setTemplates] = useState<ClientTemplate[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [invoiceYear, setInvoiceYear] = useState(new Date().getFullYear())
  const [invoiceMonth, setInvoiceMonth] = useState(new Date().getMonth() + 1)
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState<{ invoice_number: string; amount_ttc: number } | null>(null)
  const [generateError, setGenerateError] = useState('')
  // BCT export state
  const [isExport, setIsExport] = useState(false)
  const [exportCurrency, setExportCurrency] = useState('EUR')
  const [foreignAmount, setForeignAmount] = useState('')
  const [exchangeRate, setExchangeRate] = useState('')
  const [shipmentDate, setShipmentDate] = useState('')
  const [domicilBank, setDomicilBank] = useState('')
  const [domicilNumber, setDomicilNumber] = useState('')

  useEffect(() => {
    Promise.all([listProjects(), listClientInvoices()])
      .then(([projs, cis]) => { setProjects(projs); setClientInvoices(cis) })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!selectedProjectId) return
    setPhasesLoading(true)
    setPhases([])
    setJhInputs({})
    listProjectPhases(selectedProjectId)
      .then(ps => {
        setPhases(ps)
        const defaults: Record<string, number> = {}
        ps.forEach(p => { defaults[p.id] = 0 })
        setJhInputs(defaults)
      })
      .catch(() => {})
      .finally(() => setPhasesLoading(false))
  }, [selectedProjectId])

  const openFiche = (projectId: string) => {
    setSelectedProjectId(projectId)
    setActiveTab(1)
  }

  const openModal = async () => {
    setShowModal(true)
    setGenerated(null)
    setGenerateError('')
    if (templates.length === 0) {
      try {
        const t = await listTemplates()
        setTemplates(t)
        if (t.length) setSelectedTemplate(t[0].id)
      } catch {}
    }
  }

  const handleGenerate = async () => {
    if (!selectedTemplate) return
    setGenerating(true)
    setGenerateError('')
    try {
      const bct = isExport ? {
        is_export: true,
        currency: exportCurrency,
        foreign_currency_amount: foreignAmount ? parseFloat(foreignAmount) : null,
        exchange_rate: exchangeRate ? parseFloat(exchangeRate) : null,
        shipment_date: shipmentDate || null,
        domiciliation_bank: domicilBank || null,
        domiciliation_number: domicilNumber || null,
      } : undefined
      const result = await generateInvoice(selectedTemplate, invoiceYear, invoiceMonth, bct)
      setGenerated(result)
    } catch {
      setGenerateError("Erreur lors de la génération — vérifiez que l'API est démarrée.")
    } finally {
      setGenerating(false)
    }
  }

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  return (
    <div style={{ background: '#F0F4F9', minHeight: '100vh' }}>
      {/* Page header */}
      <div
        className="flex items-center gap-3 px-7 py-4 border-b sticky top-0 z-10"
        style={{ background: '#fff', borderColor: '#D5E8F5' }}
      >
        <h1 className="flex-1 text-lg font-bold" style={{ color: '#1A1A2E' }}>💳 Facturation Intra-groupe</h1>
        <span className="px-3 py-1 rounded-full text-xs font-semibold" style={{ background: '#FFF3DC', color: '#A0700A' }}>
          ● Chef de Projet
        </span>
        <button
          onClick={openModal}
          className="flex items-center gap-1.5 text-sm font-semibold text-white px-4 py-2 rounded-lg"
          style={{ background: '#F0A600' }}
        >
          <Plus size={14} />
          Nouvelle facture
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b bg-white" style={{ borderColor: '#D5E8F5' }}>
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className="px-5 py-3 text-sm font-medium transition-all border-b-2"
            style={
              activeTab === i
                ? { color: '#1A3A5C', borderColor: '#1A3A5C' }
                : { color: '#5D6D7E', borderColor: 'transparent' }
            }
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Tab 0: Projets & Chartes ─────────────────────────────────────── */}
      {activeTab === 0 && (
        <div className="grid grid-cols-2 gap-4 p-6">
          {projects.length === 0 ? (
            <p className="col-span-2 text-center text-sm py-8" style={{ color: '#5D6D7E' }}>
              Aucun projet — démarrez l'API et rechargez la page.
            </p>
          ) : (
            projects.map(project => (
              <ProjectCard key={project.id} project={project} onFiche={openFiche} />
            ))
          )}
        </div>
      )}

      {/* ── Tab 1: Fiche Mensuelle ────────────────────────────────────────── */}
      {activeTab === 1 && (
        <div className="p-6 space-y-4">
          {/* Controls row */}
          <div
            className="bg-white rounded-xl border p-4 flex items-end gap-4 flex-wrap"
            style={{ borderColor: '#D5E8F5' }}
          >
            <div className="flex flex-col gap-1 min-w-[240px]">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Projet</label>
              <select
                value={selectedProjectId ?? ''}
                onChange={e => setSelectedProjectId(e.target.value || null)}
                className="rounded-lg border px-3 py-2 text-sm outline-none"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
              >
                <option value="">— Sélectionner un projet —</option>
                {projects.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Mois</label>
              <select
                value={ficheMonth}
                onChange={e => setFicheMonth(Number(e.target.value))}
                className="rounded-lg border px-3 py-2 text-sm outline-none"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
              >
                {MONTHS.map((m, i) => (
                  <option key={i + 1} value={i + 1}>{m}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium" style={{ color: '#374151' }}>Année</label>
              <input
                type="number"
                value={ficheYear}
                onChange={e => setFicheYear(Number(e.target.value))}
                min={2020} max={2030}
                className="rounded-lg border px-3 py-2 text-sm outline-none w-24"
                style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
              />
            </div>
          </div>

          {/* Empty state */}
          {!selectedProjectId && (
            <div className="bg-white rounded-xl border p-12 text-center" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-2xl mb-2">📋</p>
              <p className="text-sm font-medium" style={{ color: '#1A1A2E' }}>Sélectionnez un projet</p>
              <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
                Choisissez un projet ci-dessus pour saisir les jours travaillés du mois.
              </p>
            </div>
          )}

          {/* Phases loading */}
          {selectedProjectId && phasesLoading && (
            <div className="bg-white rounded-xl border p-8 text-center" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-sm" style={{ color: '#5D6D7E' }}>Chargement des phases…</p>
            </div>
          )}

          {/* Fiche content */}
          {selectedProjectId && !phasesLoading && (() => {
            const proj = projects.find(p => p.id === selectedProjectId)!
            const tauxJH = proj.taux_jh
            const totalJH = phases.reduce((s, ph) => s + (jhInputs[ph.id] ?? 0), 0)
            const montantHT = totalJH * tauxJH
            const tva = montantHT * 0.19
            const montantTTC = montantHT + tva

            return (
              <div className="space-y-4">
                {/* Project header card */}
                <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5' }}>
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-semibold text-base" style={{ color: '#1A1A2E' }}>{proj.name}</p>
                      <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                        {proj.client} · Taux : {proj.taux_jh.toLocaleString('fr-TN')} TND / JH
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-[11px] font-medium mb-0.5" style={{ color: '#5D6D7E' }}>Budget global</p>
                      <p className="text-sm font-bold" style={{ color: '#1A3A5C' }}>
                        {proj.budget_jh} JH · {formatTND(proj.budget_tnd)}
                      </p>
                      <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                        Consommé : {proj.consumed_jh} JH ({formatTND(proj.spent_tnd)})
                      </p>
                    </div>
                  </div>
                </div>

                {/* Phases table */}
                <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
                  <div className="px-5 py-3 border-b" style={{ borderColor: '#D5E8F5', background: '#F7FAFD' }}>
                    <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#5D6D7E' }}>
                      Saisie des jours travaillés — {MONTHS[ficheMonth - 1]} {ficheYear}
                    </p>
                  </div>

                  {phases.length === 0 ? (
                    <p className="px-5 py-6 text-sm text-center" style={{ color: '#5D6D7E' }}>
                      Aucune phase trouvée pour ce projet.
                    </p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b" style={{ borderColor: '#D5E8F5', background: '#F0F4F9' }}>
                          {['Phase', 'Statut', 'Budget JH', 'Consommé YTD', 'Ce mois (JH)', 'Montant HT'].map(h => (
                            <th key={h} className="px-4 py-3 text-xs font-semibold uppercase text-left" style={{ color: '#5D6D7E' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {phases.map(ph => {
                          const jh = jhInputs[ph.id] ?? 0
                          const phMontantHT = jh * tauxJH
                          const ps = PHASE_STATUS[ph.status] ?? PHASE_STATUS.OPEN
                          const isClosed = ph.status === 'CLOSED'
                          return (
                            <tr
                              key={ph.id}
                              className="border-b"
                              style={{ borderColor: '#F0F4F9', opacity: isClosed ? 0.65 : 1 }}
                            >
                              <td className="px-4 py-3 font-medium" style={{ color: '#1A1A2E' }}>{ph.name}</td>
                              <td className="px-4 py-3">
                                <span
                                  className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                                  style={{ background: '#F0F4F9', color: ps.color }}
                                >
                                  {ps.label}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-sm" style={{ color: '#5D6D7E' }}>{ph.planned_jh} JH</td>
                              <td className="px-4 py-3 text-sm" style={{ color: '#5D6D7E' }}>{ph.consumed_jh} JH</td>
                              <td className="px-4 py-3">
                                <input
                                  type="number"
                                  min={0}
                                  step={0.5}
                                  value={jh === 0 ? '' : jh}
                                  placeholder="0"
                                  disabled={isClosed}
                                  onChange={e =>
                                    setJhInputs(prev => ({ ...prev, [ph.id]: Number(e.target.value) || 0 }))
                                  }
                                  className="w-20 rounded-lg border px-2 py-1.5 text-sm outline-none text-center disabled:opacity-40"
                                  style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                                />
                              </td>
                              <td className="px-4 py-3 text-sm font-medium" style={{ color: '#1A3A5C' }}>
                                {jh > 0 ? formatTND(phMontantHT) : '—'}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                      <tfoot>
                        <tr style={{ background: '#E8F5F0' }}>
                          <td colSpan={4} className="px-4 py-3 text-sm font-semibold" style={{ color: '#1D9E76' }}>
                            Total
                          </td>
                          <td className="px-4 py-3 text-sm font-bold" style={{ color: '#1A1A2E' }}>
                            {totalJH} JH
                          </td>
                          <td className="px-4 py-3 text-sm font-bold" style={{ color: '#1A3A5C' }}>
                            {formatTND(montantHT)}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  )}
                </div>

                {/* Billing summary + generate button */}
                <div className="bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5' }}>
                  <p className="text-sm font-semibold mb-4" style={{ color: '#1A1A2E' }}>
                    Récapitulatif de facturation
                  </p>
                  <div className="flex items-end justify-between gap-4">
                    <div className="space-y-2 min-w-[260px]">
                      <div className="flex justify-between">
                        <span className="text-sm" style={{ color: '#5D6D7E' }}>Montant HT</span>
                        <span className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>{formatTND(montantHT)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-sm" style={{ color: '#5D6D7E' }}>TVA (19%)</span>
                        <span className="text-sm font-semibold" style={{ color: '#1A1A2E' }}>{formatTND(tva)}</span>
                      </div>
                      <div
                        className="flex justify-between pt-2 border-t"
                        style={{ borderColor: '#D5E8F5' }}
                      >
                        <span className="text-sm font-bold" style={{ color: '#1A1A2E' }}>Montant TTC</span>
                        <span className="text-base font-bold" style={{ color: '#1A3A5C' }}>{formatTND(montantTTC)}</span>
                      </div>
                    </div>

                    <button
                      onClick={() => {
                        setInvoiceMonth(ficheMonth)
                        setInvoiceYear(ficheYear)
                        openModal()
                      }}
                      disabled={totalJH === 0}
                      className="flex items-center gap-1.5 text-sm font-semibold text-white px-5 py-2.5 rounded-xl disabled:opacity-40 transition-opacity"
                      style={{ background: '#F0A600' }}
                    >
                      <Plus size={14} />
                      Générer la facture
                    </button>
                  </div>

                  {totalJH === 0 && (
                    <p className="text-xs mt-3" style={{ color: '#5D6D7E' }}>
                      Saisissez les jours travaillés pour activer la génération.
                    </p>
                  )}
                </div>
              </div>
            )
          })()}
        </div>
      )}

      {/* ── Tab 2: Historique ─────────────────────────────────────────────── */}
      {activeTab === 2 && (
        <div className="p-6">
          {clientInvoices.length === 0 ? (
            <div className="bg-white rounded-xl border p-8 text-center" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-sm" style={{ color: '#5D6D7E' }}>Aucune facture émise.</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border overflow-hidden" style={{ borderColor: '#D5E8F5' }}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b" style={{ borderColor: '#D5E8F5', background: '#F0F4F9' }}>
                    {['N° Facture', 'Date', 'Client', 'Montant HT', 'TVA', 'Montant TTC', 'Statut'].map(h => (
                      <th key={h} className="px-4 py-3 text-xs font-semibold uppercase text-left" style={{ color: '#5D6D7E' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clientInvoices.map(inv => {
                    const STATUS_CI: Record<string, { label: string; bg: string; color: string }> = {
                      draft:     { label: 'BROUILLON', bg: '#F0F4F9', color: '#5D6D7E' },
                      sent:      { label: 'ENVOYÉE',   bg: '#FFF8E8', color: '#A0700A' },
                      paid:      { label: 'PAYÉE',     bg: '#E8F5F0', color: '#1D9E76' },
                      cancelled: { label: 'ANNULÉE',   bg: '#FDECEA', color: '#C0391B' },
                    }
                    const s = STATUS_CI[inv.status] ?? STATUS_CI.draft
                    const [y, m, d] = inv.invoice_date.split('-')
                    return (
                      <tr key={inv.invoice_number} className="border-b" style={{ borderColor: '#F0F4F9' }}>
                        <td className="px-4 py-3 font-mono text-xs font-semibold" style={{ color: '#1A3A5C' }}>{inv.invoice_number}</td>
                        <td className="px-4 py-3 text-xs" style={{ color: '#5D6D7E' }}>{d}/{m}/{y}</td>
                        <td className="px-4 py-3 text-sm" style={{ color: '#1A1A2E' }}>{inv.client_name}</td>
                        <td className="px-4 py-3 text-sm font-medium" style={{ color: '#1A1A2E' }}>{formatTND(inv.amount_ht)}</td>
                        <td className="px-4 py-3 text-sm" style={{ color: '#5D6D7E' }}>{formatTND(inv.tva_amount)}</td>
                        <td className="px-4 py-3 text-sm font-bold" style={{ color: '#1A3A5C' }}>{formatTND(inv.amount_ttc)}</td>
                        <td className="px-4 py-3">
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full" style={{ background: s.bg, color: s.color }}>
                            {s.label}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  <tr style={{ background: '#E8F5F0' }}>
                    <td colSpan={3} className="px-4 py-2.5 text-sm font-semibold" style={{ color: '#1D9E76' }}>
                      Total — {clientInvoices.length} facture{clientInvoices.length > 1 ? 's' : ''}
                    </td>
                    <td className="px-4 py-2.5 text-sm font-semibold" style={{ color: '#1A1A2E' }}>
                      {formatTND(clientInvoices.reduce((s, i) => s + i.amount_ht, 0))}
                    </td>
                    <td className="px-4 py-2.5 text-sm font-semibold" style={{ color: '#5D6D7E' }}>
                      {formatTND(clientInvoices.reduce((s, i) => s + i.tva_amount, 0))}
                    </td>
                    <td className="px-4 py-2.5 text-sm font-bold" style={{ color: '#1A3A5C' }}>
                      {formatTND(clientInvoices.reduce((s, i) => s + i.amount_ttc, 0))}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Modal — Nouvelle facture ──────────────────────────────────────── */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(10,20,35,0.45)' }}
          onClick={e => { if (e.target === e.currentTarget) setShowModal(false) }}
        >
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#D5E8F5' }}>
              <h2 className="text-base font-bold" style={{ color: '#1A1A2E' }}>Nouvelle facture client</h2>
              <button onClick={() => setShowModal(false)} className="opacity-50 hover:opacity-100 transition-opacity">
                <X size={18} style={{ color: '#1A1A2E' }} />
              </button>
            </div>

            <div className="px-6 py-5">
              {generated ? (
                <div className="flex flex-col items-center gap-4 py-4 text-center">
                  <CheckCircle size={40} style={{ color: '#1D9E76' }} />
                  <div>
                    <p className="text-base font-bold" style={{ color: '#1A1A2E' }}>Facture générée</p>
                    <p className="text-sm mt-1" style={{ color: '#5D6D7E' }}>N° {generated.invoice_number}</p>
                    <p className="text-lg font-bold mt-2" style={{ color: '#1A3A5C' }}>
                      {generated.amount_ttc.toLocaleString('fr-TN', { minimumFractionDigits: 3 })} TND TTC
                    </p>
                  </div>
                  <button
                    onClick={() => setShowModal(false)}
                    className="mt-2 px-6 py-2 rounded-xl text-sm font-semibold text-white"
                    style={{ background: '#1A3A5C' }}
                  >
                    Fermer
                  </button>
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs font-medium" style={{ color: '#374151' }}>Modèle de facturation</label>
                    {templates.length === 0 ? (
                      <p className="text-xs py-2" style={{ color: '#5D6D7E' }}>Chargement des modèles…</p>
                    ) : (
                      <select
                        value={selectedTemplate}
                        onChange={e => setSelectedTemplate(e.target.value)}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none w-full"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      >
                        {templates.map(t => (
                          <option key={t.id} value={t.id}>
                            {t.client_name} — {t.service_description.slice(0, 40)}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-medium" style={{ color: '#374151' }}>Mois</label>
                      <select
                        value={invoiceMonth}
                        onChange={e => setInvoiceMonth(Number(e.target.value))}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      >
                        {MONTHS.map((m, i) => (
                          <option key={i + 1} value={i + 1}>{m}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-xs font-medium" style={{ color: '#374151' }}>Année</label>
                      <input
                        type="number"
                        value={invoiceYear}
                        onChange={e => setInvoiceYear(Number(e.target.value))}
                        min={2020} max={2030}
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5', color: '#1A1A2E' }}
                      />
                    </div>
                  </div>

                  {/* BCT export toggle */}
                  <div style={{ borderTop: '1px solid #EFF4FA', paddingTop: 12 }}>
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isExport}
                        onChange={e => setIsExport(e.target.checked)}
                        style={{ width: 16, height: 16, accentColor: '#1A3A5C' }}
                      />
                      <span className="text-xs font-semibold" style={{ color: '#1A3A5C' }}>
                        Facture export (conformité BCT — Circulaire 2025-13)
                      </span>
                    </label>
                  </div>

                  {isExport && (
                    <div className="flex flex-col gap-3 p-4 rounded-xl" style={{ background: '#F0F4F9' }}>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-medium" style={{ color: '#374151' }}>Devise</label>
                          <select
                            value={exportCurrency}
                            onChange={e => setExportCurrency(e.target.value)}
                            className="rounded-lg border px-3 py-2 text-sm outline-none"
                            style={{ borderColor: '#D5E8F5' }}
                          >
                            {['EUR', 'USD', 'GBP', 'TND'].map(c => <option key={c}>{c}</option>)}
                          </select>
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-medium" style={{ color: '#374151' }}>Montant devise</label>
                          <input
                            type="number"
                            placeholder="0.000"
                            value={foreignAmount}
                            onChange={e => setForeignAmount(e.target.value)}
                            className="rounded-lg border px-3 py-2 text-sm outline-none"
                            style={{ borderColor: '#D5E8F5' }}
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-medium" style={{ color: '#374151' }}>Taux de change</label>
                          <input
                            type="number"
                            placeholder="3.300"
                            value={exchangeRate}
                            onChange={e => setExchangeRate(e.target.value)}
                            className="rounded-lg border px-3 py-2 text-sm outline-none"
                            style={{ borderColor: '#D5E8F5' }}
                          />
                        </div>
                        <div className="flex flex-col gap-1.5">
                          <label className="text-xs font-medium" style={{ color: '#374151' }}>Date d'envoi</label>
                          <input
                            type="date"
                            value={shipmentDate}
                            onChange={e => setShipmentDate(e.target.value)}
                            className="rounded-lg border px-3 py-2 text-sm outline-none"
                            style={{ borderColor: '#D5E8F5' }}
                          />
                        </div>
                      </div>
                      {shipmentDate && (
                        <div className="text-xs px-3 py-2 rounded-lg" style={{ background: '#E8F5F0', color: '#1D9E76' }}>
                          Échéance rapatriement BCT (120 j) :{' '}
                          <strong>
                            {new Date(new Date(shipmentDate).getTime() + 120 * 86400000).toLocaleDateString('fr-FR')}
                          </strong>
                        </div>
                      )}
                      <input
                        type="text"
                        placeholder="Banque domiciliataire (ex : BIAT Siège Tunis)"
                        value={domicilBank}
                        onChange={e => setDomicilBank(e.target.value)}
                        className="rounded-lg border px-3 py-2 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5' }}
                      />
                      <input
                        type="text"
                        placeholder="N° de domiciliation"
                        value={domicilNumber}
                        onChange={e => setDomicilNumber(e.target.value)}
                        className="rounded-lg border px-3 py-2 text-sm outline-none"
                        style={{ borderColor: '#D5E8F5' }}
                      />
                    </div>
                  )}

                  {generateError && (
                    <p className="text-xs py-2" style={{ color: '#C0391B' }}>{generateError}</p>
                  )}

                  <button
                    onClick={handleGenerate}
                    disabled={generating || !selectedTemplate}
                    className="w-full py-3 rounded-xl text-white text-sm font-semibold mt-1 disabled:opacity-50 transition-opacity"
                    style={{ background: '#F0A600' }}
                  >
                    {generating ? 'Génération…' : 'Générer la facture'}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
