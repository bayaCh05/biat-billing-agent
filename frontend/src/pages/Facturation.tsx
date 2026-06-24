import { useState, useEffect } from 'react'
import { Plus, X, CheckCircle } from 'lucide-react'
import type { Project, ProjectStatus, ClientTemplate, ClientInvoice } from '../types'
import { listProjects, listTemplates, generateInvoice, listClientInvoices } from '../api/endpoints'
import { formatTND } from '../utils/formatters'
import PageSpinner from '../components/ui/PageSpinner'

const MONTHS = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre']

const STATUS_MAP: Record<ProjectStatus, { label: string; bg: string; color: string }> = {
  ACTIVE:    { label: 'OUVERT',   bg: '#E8F5F0', color: '#1D9E76' },
  COMPLETED: { label: 'CLOS',     bg: '#EFF4FA', color: '#5BA3C9' },
  ON_HOLD:   { label: 'SUSPENDU', bg: '#FFF8E8', color: '#F0A600' },
  CANCELLED: { label: 'ANNULÉ',   bg: '#FDECEA', color: '#C0391B' },
}

const TABS = ['Projets & Chartes', 'Fiche Mensuelle', 'Historique']

function barColor(pct: number, status: ProjectStatus): string {
  if (status === 'COMPLETED' || pct >= 100) return '#C0391B'
  if (pct >= 80) return '#F0A600'
  return '#1D9E76'
}

function ProjectCard({ project }: { project: Project }) {
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

  // Modal state
  const [showModal, setShowModal] = useState(false)
  const [templates, setTemplates] = useState<ClientTemplate[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [invoiceYear, setInvoiceYear] = useState(new Date().getFullYear())
  const [invoiceMonth, setInvoiceMonth] = useState(new Date().getMonth() + 1)
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState<{ invoice_number: string; amount_ttc: number } | null>(null)
  const [generateError, setGenerateError] = useState('')

  useEffect(() => {
    Promise.all([listProjects(), listClientInvoices()])
      .then(([projs, cis]) => { setProjects(projs); setClientInvoices(cis) })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

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
      const result = await generateInvoice(selectedTemplate, invoiceYear, invoiceMonth)
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

      {/* Content */}
      {activeTab === 0 && (
        <div className="grid grid-cols-2 gap-4 p-6">
          {projects.length === 0 ? (
            <p className="col-span-2 text-center text-sm py-8" style={{ color: '#5D6D7E' }}>
              Aucun projet — démarrez l'API et rechargez la page.
            </p>
          ) : (
            projects.map(project => <ProjectCard key={project.id} project={project} />)
          )}
        </div>
      )}

      {activeTab === 1 && (
        <div className="p-6">
          <div className="bg-white rounded-xl border p-8 text-center" style={{ borderColor: '#D5E8F5' }}>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>Fiche mensuelle — sélectionnez un projet</p>
          </div>
        </div>
      )}

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

      {/* Modal — Nouvelle facture */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(10,20,35,0.45)' }}
          onClick={e => { if (e.target === e.currentTarget) setShowModal(false) }}
        >
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#D5E8F5' }}>
              <h2 className="text-base font-bold" style={{ color: '#1A1A2E' }}>Nouvelle facture client</h2>
              <button onClick={() => setShowModal(false)} className="opacity-50 hover:opacity-100 transition-opacity">
                <X size={18} style={{ color: '#1A1A2E' }} />
              </button>
            </div>

            <div className="px-6 py-5">
              {generated ? (
                /* Success state */
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
                /* Form */
                <div className="flex flex-col gap-4">
                  {/* Template selector */}
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

                  {/* Period */}
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
