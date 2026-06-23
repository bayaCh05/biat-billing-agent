import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import { listTemplates, generateInvoice } from '../api/endpoints'
import { formatTND } from '../utils/formatters'
import type { ClientTemplate } from '../types'

function titleCase(id: string) {
  return id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export default function ProjetDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [template, setTemplate] = useState<ClientTemplate | null>(null)
  const [generating, setGenerating] = useState(false)
  const [genResult, setGenResult] = useState<{ ok: boolean; msg: string } | null>(null)

  useEffect(() => {
    if (!id) return
    listTemplates()
      .then(templates => {
        const found = templates.find(t => t.id === id)
        if (found) setTemplate(found)
      })
      .catch(() => {})
  }, [id])

  if (!template) {
    return (
      <div className="p-6">
        <p className="text-sm" style={{ color: '#5D6D7E' }}>Chargement…</p>
      </div>
    )
  }

  const ttc = template.unit_price_ht * (1 + template.tva_rate / 100)
  const name = titleCase(template.id)

  async function handleGenerate() {
    if (!id) return
    setGenerating(true)
    setGenResult(null)
    const now = new Date()
    try {
      const res = await generateInvoice(id, now.getFullYear(), now.getMonth() + 1)
      setGenResult({ ok: true, msg: `Facture ${res.invoice_number} générée — ${formatTND(res.amount_ttc)} TTC` })
    } catch (e: unknown) {
      setGenResult({ ok: false, msg: e instanceof Error ? e.message : 'Erreur lors de la génération' })
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div>
      <PageHeader title={name} badge={template.client_code}>
        <button
          onClick={() => navigate('/projects')}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all hover:bg-gray-50"
          style={{ borderColor: '#D5E8F5', color: '#1A3A5C' }}
        >
          <ArrowLeft size={13} />
          Retour
        </button>
      </PageHeader>

      <div className="p-6 space-y-5">
        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Client',        value: template.client_name,               color: '#1A3A5C' },
            { label: 'Prix HT/mois',  value: template.unit_price_ht > 0 ? formatTND(template.unit_price_ht) : 'Sur devis', color: '#1A3A5C' },
            { label: 'TVA',           value: `${template.tva_rate}%`,            color: '#5BA3C9' },
            { label: 'TTC/mois',      value: template.unit_price_ht > 0 ? formatTND(ttc) : '—',   color: '#804CD7' },
          ].map(s => (
            <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
              <p className="text-lg font-bold" style={{ color: s.color }}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* Description */}
        <Card>
          <h3 className="font-semibold text-sm mb-3" style={{ color: '#1A3A5C' }}>Description du service</h3>
          <p className="text-sm leading-relaxed" style={{ color: '#1A1A2E' }}>{template.service_description}</p>
        </Card>

        {/* Generate invoice */}
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold text-sm" style={{ color: '#1A3A5C' }}>Générer une facture mensuelle</h3>
              <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
                Crée une facture client pour {template.client_name} — mois en cours.
              </p>
            </div>
            <button
              onClick={handleGenerate}
              disabled={generating || template.unit_price_ht === 0}
              style={{
                background: template.unit_price_ht > 0 ? '#1A3A5C' : '#D5E8F5',
                color: template.unit_price_ht > 0 ? '#fff' : '#5D6D7E',
                border: 'none', borderRadius: 8, padding: '9px 18px',
                fontSize: 13, fontWeight: 600, cursor: template.unit_price_ht > 0 ? 'pointer' : 'not-allowed',
                fontFamily: 'Inter, sans-serif', whiteSpace: 'nowrap',
                opacity: generating ? 0.7 : 1,
              }}
            >
              {generating ? '⏳ Génération…' : '📄 Générer facture'}
            </button>
          </div>

          {genResult && (
            <div
              style={{
                marginTop: 12, padding: '10px 14px', borderRadius: 8,
                background: genResult.ok ? '#E8F5F0' : '#FEF0EE',
                color: genResult.ok ? '#1D9E76' : '#C0391B',
                fontSize: 13, fontWeight: 500,
              }}
            >
              {genResult.ok ? '✓' : '✗'} {genResult.msg}
            </div>
          )}

          {template.unit_price_ht === 0 && (
            <p className="text-xs mt-3" style={{ color: '#F0A600' }}>
              ⚠ Ce service est facturé sur devis — aucun prix unitaire défini.
            </p>
          )}
        </Card>

        <p className="text-xs" style={{ color: '#5D6D7E' }}>
          Code service : <span className="font-mono">{template.id}</span> · Client : {template.client_code}
        </p>
      </div>
    </div>
  )
}
