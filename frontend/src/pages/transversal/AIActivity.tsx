import { useState, useEffect } from 'react'
import { Bot, RefreshCw, Wifi, WifiOff, TrendingUp, Clock } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import Card from '../../components/ui/Card'
import { getAIActivity, scanRoadmapRisks } from '../../api/endpoints'

interface OllamaStats {
  total_calls: number
  success_rate: number
  avg_duration_ms: number
}

interface AIActivity {
  ollama_stats: OllamaStats
  ollama_available: boolean
  model: string
}

function StatCard({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold" style={{ color }}>
        {value}
        {unit && <span className="text-sm font-normal ml-1 text-gray-400">{unit}</span>}
      </p>
    </div>
  )
}

export default function AIActivityPage() {
  const [data, setData] = useState<AIActivity | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<{ items_scanned: number; risks_created: number } | null>(null)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getAIActivity()
      setData(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }

  const handleScanRisks = async () => {
    setScanning(true)
    setScanResult(null)
    try {
      const result = await scanRoadmapRisks()
      setScanResult(result)
    } catch {
      setError('Erreur lors du scan des risques')
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => { queueMicrotask(load) }, [])

  const stats = data?.ollama_stats

  return (
    <div>
      <PageHeader title="🤖 Activité IA" badge="Admin">
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 hover:bg-gray-50 text-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          Actualiser
        </button>
      </PageHeader>

      <div className="p-6 flex flex-col gap-5">
        {error && (
          <div className="px-4 py-3 rounded-xl text-sm font-medium" style={{ background: '#FDECEA', color: '#C0391B' }}>
            {error}
          </div>
        )}
        {/* Status banner */}
        <div
          className="flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium"
          style={{
            background: data?.ollama_available ? '#E8F5F0' : '#FDECEA',
            color: data?.ollama_available ? '#1D9E76' : '#C0391B',
          }}
        >
          {data?.ollama_available
            ? <><Wifi size={16} /> Ollama disponible — modèle: <code className="font-mono text-xs ml-1">{data.model}</code></>
            : <><WifiOff size={16} /> Ollama non disponible — les agents fonctionnent en mode dégradé (règles seulement)</>
          }
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-3 gap-4">
          <StatCard
            label="Total appels Ollama"
            value={stats?.total_calls ?? 0}
            color="#2E86C1"
          />
          <StatCard
            label="Taux de succès"
            value={stats ? `${(stats.success_rate * 100).toFixed(1)}` : '0.0'}
            unit="%"
            color="#1D9E76"
          />
          <StatCard
            label="Durée moyenne"
            value={stats?.avg_duration_ms ? Math.round(stats.avg_duration_ms) : 0}
            unit="ms"
            color="#804CD7"
          />
        </div>

        {/* Pipeline info */}
        <div className="grid grid-cols-2 gap-5">
          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <TrendingUp size={16} className="text-blue-500" />
              Pipeline de traitement
            </h3>
            <div className="space-y-3">
              {[
                { step: '1', name: 'Extraction PDF', desc: 'PyMuPDF → Tesseract OCR → Ollama LLM', color: '#2E86C1' },
                { step: '2', name: 'Classification PCE', desc: 'Fuzzy → TF-IDF ML → RAG + Ollama', color: '#1D9E76' },
                { step: '3', name: 'Détection anomalies', desc: '8 contrôles + embedding sémantique', color: '#F0A500' },
                { step: '4', name: 'Écriture comptable', desc: 'PCE règles + explication Ollama', color: '#804CD7' },
              ].map(s => (
                <div key={s.step} className="flex items-start gap-3">
                  <span
                    className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0 mt-0.5"
                    style={{ background: s.color }}
                  >
                    {s.step}
                  </span>
                  <div>
                    <p className="text-sm font-medium text-gray-800">{s.name}</p>
                    <p className="text-xs text-gray-500">{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
              <Bot size={16} className="text-purple-500" />
              Actions manuelles
            </h3>
            <div className="space-y-3">
              <div className="p-3 rounded-lg bg-gray-50">
                <p className="text-xs font-semibold text-gray-700 mb-1">Scan risques roadmap</p>
                <p className="text-xs text-gray-500 mb-2">
                  Analyse les jalons en retard et crée automatiquement des risques IA.
                </p>
                <button
                  onClick={handleScanRisks}
                  disabled={scanning}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg text-white disabled:opacity-50 transition-colors"
                  style={{ background: scanning ? '#5D6D7E' : '#804CD7' }}
                >
                  {scanning ? <RefreshCw size={11} className="animate-spin" /> : <Bot size={11} />}
                  {scanning ? 'Scan en cours…' : 'Lancer le scan'}
                </button>
                {scanResult && (
                  <p className="text-xs text-green-700 mt-2">
                    ✅ {scanResult.items_scanned} jalons analysés — {scanResult.risks_created} risques créés
                  </p>
                )}
              </div>

              <div className="p-3 rounded-lg bg-gray-50">
                <p className="text-xs font-semibold text-gray-700 mb-1">Scheduler automatique</p>
                <div className="space-y-1 text-xs text-gray-500">
                  <div className="flex items-center gap-2">
                    <Clock size={10} />
                    <span>Scan risques: chaque jour à 08h00</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Clock size={10} />
                    <span>Recalcul pénalités: chaque nuit à 00h01</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Clock size={10} />
                    <span>Audit comptable: chaque lundi à 06h00</span>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <div className="p-3 rounded-lg text-xs" style={{ background: '#F0EBF9', color: '#804CD7' }}>
          🔒 Toute l'inférence IA est locale via Ollama — aucune donnée de facturation n'est transmise au cloud.
          Modèle: <code className="font-mono">{data?.model ?? 'qwen2.5:3b'}</code>
        </div>
      </div>
    </div>
  )
}
