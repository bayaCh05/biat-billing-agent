import { useState, useRef, useEffect } from 'react'
import { Upload, FileText, CheckCircle, Loader2, X, ChevronRight, Wifi, WifiOff } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import StatusChip from '../components/ui/StatusChip'
import type { Invoice, InvoiceSummary } from '../types'
import { formatTND } from '../utils/formatters'
import { uploadInvoice, listInvoices } from '../api/endpoints'

type Stage = 'idle' | 'running' | 'done' | 'error'

function timeAgo(iso: string): string {
  const h = Math.floor((Date.now() - new Date(iso).getTime()) / 3_600_000)
  if (h < 1) return "À l'instant"
  if (h < 24) return `Il y a ${h}h`
  return `Il y a ${Math.floor(h / 24)}j`
}

export default function InvoicePipeline() {
  const [file, setFile] = useState<File | null>(null)
  const [stage, setStage] = useState<Stage>('idle')
  const [isDragging, setIsDragging] = useState(false)
  const [live, setLive] = useState(false)
  const [result, setResult] = useState<Invoice | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [recent, setRecent] = useState<InvoiceSummary[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    listInvoices().then(data => setRecent(data.slice(0, 5))).catch(() => {})
  }, [stage])

  const handleFile = (f: File) => {
    setFile(f)
    setStage('idle')
    setResult(null)
    setErrorMsg('')
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const runPipeline = async () => {
    if (!file) return
    setStage('running')
    setErrorMsg('')
    try {
      const invoice = await uploadInvoice(file, live)
      setResult(invoice)
      setStage('done')
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Erreur inattendue')
      setStage('error')
    }
  }

  const reset = () => {
    setFile(null)
    setStage('idle')
    setResult(null)
    setErrorMsg('')
  }

  return (
    <div>
      <PageHeader title="🧾 Traitement de Factures" badge="Upload & Pipeline">
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: '#5D6D7E' }}>Mode:</span>
          <button
            onClick={() => setLive(!live)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all"
            style={{
              background: live ? '#E8F5F0' : '#F0F4F9',
              color: live ? '#1D9E76' : '#5D6D7E',
              border: `1px solid ${live ? '#1D9E76' : '#D5E8F5'}`,
            }}
          >
            {live ? <Wifi size={12} /> : <WifiOff size={12} />}
            {live ? 'Ollama live' : 'Mock (démo)'}
          </button>
        </div>
      </PageHeader>

      <div className="p-6 grid grid-cols-2 gap-6">
        {/* Upload panel */}
        <div className="flex flex-col gap-4">
          <div
            className="relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all"
            style={{
              borderColor: isDragging ? '#5BA3C9' : '#D5E8F5',
              background: isDragging ? '#EBF5FB' : '#fff',
              transform: isDragging ? 'scale(1.01)' : 'scale(1)',
            }}
            onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.tiff"
              className="hidden"
              onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
            <div className="flex flex-col items-center gap-3">
              <div className="p-4 rounded-full" style={{ background: '#E3F0F9' }}>
                <Upload size={28} style={{ color: '#5BA3C9' }} />
              </div>
              {file ? (
                <div>
                  <p className="font-semibold text-sm" style={{ color: '#1A3A5C' }}>
                    <FileText size={14} className="inline mr-1" />
                    {file.name}
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                    {(file.size / 1024).toFixed(0)} KB
                  </p>
                </div>
              ) : (
                <div>
                  <p className="font-semibold text-sm" style={{ color: '#1A3A5C' }}>
                    Déposez une facture ici
                  </p>
                  <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                    PDF, PNG, JPG, TIFF — jusqu'à 20 Mo
                  </p>
                </div>
              )}
            </div>
            {file && (
              <button
                className="absolute top-3 right-3 p-1 rounded-full hover:bg-gray-100 transition-colors"
                onClick={e => { e.stopPropagation(); reset() }}
              >
                <X size={14} style={{ color: '#5D6D7E' }} />
              </button>
            )}
          </div>

          <div className="p-3 rounded-lg text-xs" style={{ background: '#E3F0F9', color: '#1A3A5C' }}>
            📎 Importez uniquement des factures fournisseurs. Relevés bancaires et contrats seront rejetés.
          </div>

          {file && stage === 'idle' && (
            <button
              onClick={runPipeline}
              className="flex items-center justify-center gap-2 w-full py-3 rounded-xl text-white font-semibold text-sm transition-all hover:opacity-90"
              style={{ background: '#1A3A5C' }}
            >
              <ChevronRight size={16} />
              Traiter la facture
            </button>
          )}
        </div>

        {/* Result panel */}
        <div>
          {stage === 'idle' && !file && (
            <Card>
              <h3 className="font-semibold text-sm mb-3" style={{ color: '#1A3A5C' }}>
                Ce que fait l'agent
              </h3>
              <div className="space-y-3">
                {[
                  ['🔍', 'Extraction', 'OCR + LLM Ollama local'],
                  ['🏷️', 'Classification', 'Code comptable PCE tunisien'],
                  ['✅', 'Validation', 'Montants, doublons, anomalies'],
                  ['📤', 'Export', 'JSON + écriture journal'],
                ].map(([icon, step, desc]) => (
                  <div key={step} className="flex items-center gap-3">
                    <span className="text-lg">{icon}</span>
                    <div>
                      <p className="text-sm font-medium" style={{ color: '#1A1A2E' }}>{step}</p>
                      <p className="text-xs" style={{ color: '#5D6D7E' }}>{desc}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-4 p-3 rounded-lg text-xs" style={{ background: '#F0EBF9', color: '#804CD7' }}>
                🔒 Traitement local uniquement · Aucune donnée envoyée au cloud
              </div>
            </Card>
          )}

          {stage === 'running' && (
            <Card className="flex flex-col items-center justify-center py-10 text-center">
              <Loader2 size={32} className="animate-spin mb-3" style={{ color: '#5BA3C9' }} />
              <p className="font-semibold text-sm" style={{ color: '#1A3A5C' }}>Pipeline en cours…</p>
              <p className="text-xs mt-1" style={{ color: '#5D6D7E' }}>
                {live ? 'Extraction OCR + LLM Ollama' : 'Mode démo — réponse instantanée'}
              </p>
            </Card>
          )}

          {stage === 'error' && (
            <Card>
              <p className="text-sm font-semibold mb-2" style={{ color: '#C0391B' }}>
                ❌ Erreur pipeline
              </p>
              <p className="text-xs p-3 rounded-lg" style={{ background: '#FDECEA', color: '#C0391B' }}>
                {errorMsg}
              </p>
              {errorMsg.includes('8000') || errorMsg.includes('fetch') ? (
                <p className="text-xs mt-2" style={{ color: '#5D6D7E' }}>
                  L'API FastAPI n'est pas démarrée. Lancez:{' '}
                  <code className="bg-gray-100 px-1 rounded">uvicorn api.main:app --reload</code>
                </p>
              ) : null}
              <button onClick={reset} className="mt-3 text-xs underline" style={{ color: '#5BA3C9' }}>
                Réessayer
              </button>
            </Card>
          )}

          {stage === 'done' && result && (
            <div className="space-y-4">
              <Card>
                <div className="flex items-center gap-2 mb-3">
                  <CheckCircle size={18} style={{ color: '#1D9E76' }} />
                  <span className="font-semibold text-sm" style={{ color: '#1D9E76' }}>Pipeline terminé</span>
                  <StatusChip status={result.status} />
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  {[
                    ['Fournisseur', result.issuer_name.value],
                    ['Matricule', result.issuer_tax_id.value],
                    ['Facture n°', result.invoice_number.value],
                    ['Date', result.invoice_date.value],
                    ['Montant HT', result.amount_ht.value != null ? formatTND(Number(result.amount_ht.value)) : '—'],
                    ['TVA', result.tva_amount.value != null ? formatTND(Number(result.tva_amount.value)) : '—'],
                    ['Montant TTC', result.amount_ttc.value != null ? formatTND(Number(result.amount_ttc.value)) : '—'],
                    ['Code comptable', result.accounting_compte ? `${result.accounting_compte} — ${result.accounting_label}` : '—'],
                  ].map(([k, v]) => (
                    <div key={k}>
                      <p className="text-xs font-medium" style={{ color: '#5D6D7E' }}>{k}</p>
                      <p className="text-sm font-medium truncate" style={{ color: '#1A1A2E' }}>{String(v ?? '—')}</p>
                    </div>
                  ))}
                </div>
                {result.flags.filter(f => !f.resolved).length > 0 && (
                  <div className="mt-3 space-y-1">
                    {result.flags.filter(f => !f.resolved).map((f, i) => (
                      <div key={i} className="text-xs p-2 rounded-lg"
                        style={{ background: f.severity === 'ERROR' ? '#FDECEA' : '#FFF8E8', color: f.severity === 'ERROR' ? '#C0391B' : '#F0A600' }}>
                        {f.flag_type}: {f.message}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
              <button
                onClick={reset}
                className="w-full py-2.5 rounded-xl border text-sm font-semibold transition-all hover:bg-gray-50"
                style={{ borderColor: '#D5E8F5', color: '#1A3A5C' }}
              >
                Traiter une autre facture
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Recent activity */}
      {recent.length > 0 && (
        <div className="mx-6 mb-6 bg-white rounded-xl border p-5" style={{ borderColor: '#D5E8F5' }}>
          <p className="font-semibold text-sm mb-3" style={{ color: '#1A3A5C' }}>Activité récente</p>
          <div className="space-y-3">
            {recent.map(inv => (
              <div key={inv.id} className="flex items-center gap-3">
                <span className="w-2 h-2 rounded-full shrink-0 mt-0.5" style={{
                  background: inv.has_errors ? '#C0391B' : inv.human_review_required ? '#F0A600' : '#1D9E76',
                }} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold truncate" style={{ color: '#1A1A2E' }}>
                    {inv.issuer_name ?? '—'}
                  </p>
                  <p className="text-[10px]" style={{ color: '#5D6D7E' }}>
                    {inv.amount_ttc != null ? formatTND(inv.amount_ttc, 0) : '—'}
                    {inv.invoice_number ? ` · ${inv.invoice_number}` : ''}
                  </p>
                </div>
                <div className="shrink-0 text-right flex flex-col items-end gap-0.5">
                  <StatusChip status={inv.status} />
                  <span className="text-[10px]" style={{ color: '#5D6D7E' }}>{timeAgo(inv.received_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
