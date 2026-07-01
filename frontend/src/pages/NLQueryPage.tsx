import { useState, useRef } from 'react'
import { Send, Sparkles, ChevronDown, ChevronUp, Database, AlertCircle } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import { nlQuery } from '../api/endpoints'
import type { NLQueryResult } from '../types'

const EXAMPLES = [
  'Combien de factures ont été traitées ce mois-ci ?',
  'Quel est le total des dépenses OPEX en 2026 ?',
  'Quels sont les 5 fournisseurs avec le plus grand montant TTC ?',
  'Factures en attente de validation',
  'Total TVA déductible du mois de juin 2026',
  'Valeur nette comptable des immobilisations actives',
]

function AnswerText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.*?)\*\*/g)
  return (
    <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
      {parts.map((part, i) =>
        i % 2 === 1
          ? <strong key={i} className="text-[#1A3A5C]">{part}</strong>
          : part
      )}
    </p>
  )
}

function SqlPanel({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-3 rounded-lg border border-gray-200 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-500 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Database size={12} />
          SQL généré
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <pre className="px-3 py-2 text-xs font-mono text-gray-700 bg-white overflow-x-auto leading-relaxed">
          {sql}
        </pre>
      )}
    </div>
  )
}

function ResultTable({ columns, rows }: { columns: string[]; rows: (string | number | null)[][] }) {
  if (!columns.length) return null
  return (
    <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            {columns.map(col => (
              <th key={col} className="px-3 py-2 text-left font-semibold text-gray-600">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {row.map((cell, ci) => (
                <td key={ci} className="px-3 py-2 text-gray-700">
                  {cell === null ? <span className="text-gray-400">—</span>
                    : typeof cell === 'number' ? cell.toLocaleString('fr-TN')
                    : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface QueryEntry {
  question: string
  result: NLQueryResult | null
  error: string
  loading: boolean
}

export default function NLQueryPage() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<QueryEntry[]>([])
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const submit = async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return

    const entry: QueryEntry = { question: trimmed, result: null, error: '', loading: true }
    setHistory(h => [entry, ...h])
    setQuestion('')

    try {
      const result = await nlQuery(trimmed)
      setHistory(h => h.map((e, i) => i === 0 ? { ...e, result, loading: false } : e))
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Erreur inconnue'
      setHistory(h => h.map((e, i) => i === 0 ? { ...e, error: msg, loading: false } : e))
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit(question)
    }
  }

  return (
    <div>
      <PageHeader title="Requête IA" badge="Ollama local">
        <span className="text-xs text-gray-400 flex items-center gap-1">
          <Sparkles size={12} className="text-purple-400" />
          Langage naturel → SQL local
        </span>
      </PageHeader>

      <div className="p-6 flex flex-col gap-5">
        {/* Input card */}
        <Card>
          <p className="text-xs text-gray-500 mb-3">
            Posez une question en français sur les factures, le budget, les immobilisations ou les projets.
            L'IA génère et exécute le SQL localement — aucune donnée n'est envoyée au cloud.
          </p>

          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ex : Quel est le total des factures payées en juin 2026 ?"
              rows={2}
              className="flex-1 resize-none text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 text-gray-800 placeholder-gray-400"
            />
            <button
              onClick={() => submit(question)}
              disabled={!question.trim()}
              className="shrink-0 flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg text-white transition-colors disabled:opacity-40"
              style={{ background: '#1A3A5C' }}
            >
              <Send size={13} />
              Envoyer
            </button>
          </div>

          {/* Example chips */}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {EXAMPLES.map(ex => (
              <button
                key={ex}
                onClick={() => submit(ex)}
                className="px-2.5 py-1 text-[11px] rounded-full border border-gray-200 text-gray-600 hover:bg-gray-100 hover:border-gray-300 transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
        </Card>

        {/* Results */}
        {history.map((entry, i) => (
          <Card key={i}>
            {/* Question */}
            <p className="text-xs font-semibold text-gray-500 mb-2">Question</p>
            <p className="text-sm font-medium text-[#1A3A5C] mb-3">{entry.question}</p>

            {entry.loading && (
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <Sparkles size={12} className="animate-pulse text-purple-400" />
                Analyse en cours…
              </div>
            )}

            {entry.error && (
              <div className="flex items-start gap-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                <AlertCircle size={13} className="shrink-0 mt-0.5" />
                {entry.error}
              </div>
            )}

            {entry.result && (
              <>
                {/* Error from backend (e.g. Ollama down) */}
                {entry.result.error && !entry.result.sql && (
                  <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2 mb-2">
                    <AlertCircle size={13} className="shrink-0 mt-0.5" />
                    {entry.result.error}
                  </div>
                )}

                {/* Answer */}
                {entry.result.answer && (
                  <div className="mb-2">
                    <p className="text-xs font-semibold text-gray-500 mb-1">Réponse</p>
                    <AnswerText text={entry.result.answer} />
                  </div>
                )}

                {/* Table */}
                {entry.result.columns.length > 0 && entry.result.rows.length > 0 && (
                  <div className="mb-1">
                    <p className="text-xs font-semibold text-gray-500 mb-1">
                      Résultats ({entry.result.row_count} ligne{entry.result.row_count !== 1 ? 's' : ''})
                    </p>
                    <ResultTable columns={entry.result.columns} rows={entry.result.rows} />
                  </div>
                )}

                {/* SQL toggle */}
                {entry.result.sql && <SqlPanel sql={entry.result.sql} />}
              </>
            )}
          </Card>
        ))}

        {history.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-gray-400">
            <Sparkles size={32} className="mb-3 opacity-40" />
            <p className="text-sm">Posez votre première question ci-dessus</p>
          </div>
        )}
      </div>
    </div>
  )
}
