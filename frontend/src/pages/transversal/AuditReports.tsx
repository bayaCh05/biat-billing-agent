import { useState, useEffect, useCallback } from 'react'
import { Bot, RefreshCw, ShieldAlert, AlertTriangle, Info, CheckCircle2 } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import Card, { KpiCard } from '../../components/ui/Card'
import { useAuth } from '../../context/AuthContext'
import { listAuditReports, getAuditReport, runAuditReport } from '../../api/endpoints'
import { formatTND, formatDate } from '../../utils/formatters'
import type {
  AuditGranularity, AuditReportSummary, AuditReportDetail, AuditAlert, AuditAlertSeverity,
} from '../../types'

const GRANULARITIES: { value: AuditGranularity; label: string }[] = [
  { value: 'DAILY', label: 'Quotidien' },
  { value: 'WEEKLY', label: 'Hebdomadaire' },
  { value: 'MONTHLY', label: 'Mensuel' },
]

const DOMAIN_LABELS: Record<string, string> = {
  invoices: 'Factures',
  journal: 'Comptabilité',
  budget: 'Budget',
  echeancier: 'Échéancier',
  risks: 'Risques',
  roadmap: 'Roadmap',
}

const SEVERITY_STYLES: Record<AuditAlertSeverity, { bg: string; color: string; icon: typeof AlertTriangle }> = {
  CRITICAL: { bg: '#FDECEA', color: '#C0391B', icon: ShieldAlert },
  WARNING:  { bg: '#FFF8E8', color: '#B07800', icon: AlertTriangle },
  INFO:     { bg: '#E3F0F9', color: '#1A3A5C', icon: Info },
}

const SEVERITY_ORDER: Record<AuditAlertSeverity, number> = { CRITICAL: 0, WARNING: 1, INFO: 2 }

function signedDelta(value: number | undefined, decimals = 1): string | undefined {
  if (value == null || value === 0) return undefined
  const rounded = Number(value.toFixed(decimals))
  return rounded > 0 ? `+${rounded}` : String(rounded)
}

function AlertRow({ alert }: { alert: AuditAlert }) {
  const s = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.INFO
  const Icon = s.icon
  return (
    <div
      className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg text-sm"
      style={{ background: s.bg, color: s.color }}
    >
      <Icon size={16} className="shrink-0 mt-0.5" />
      <div>
        <span className="font-semibold">[{DOMAIN_LABELS[alert.domain] ?? alert.domain}]</span> {alert.message}
      </div>
    </div>
  )
}

function ReportRow({ report, active, onClick }: { report: AuditReportSummary; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-lg border transition-colors mb-1.5"
      style={{
        background: active ? '#E3F0F9' : '#fff',
        borderColor: active ? '#5BA3C9' : '#D5E8F5',
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-800">{formatDate(report.period_start)}</span>
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold"
          style={report.status === 'OK'
            ? { background: '#E8F5F0', color: '#1D9E76' }
            : { background: '#FFF8E8', color: '#B07800' }}
        >
          {report.status}
        </span>
      </div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-[11px] text-gray-400">
          Généré {new Date(report.generated_at).toLocaleString('fr-TN', { hour12: false })}
        </span>
        {report.critical_count > 0 ? (
          <span className="text-[11px] font-semibold" style={{ color: '#C0391B' }}>
            {report.critical_count} critique{report.critical_count > 1 ? 's' : ''}
          </span>
        ) : report.alert_count > 0 ? (
          <span className="text-[11px] font-semibold" style={{ color: '#B07800' }}>
            {report.alert_count} alerte{report.alert_count > 1 ? 's' : ''}
          </span>
        ) : (
          <span className="text-[11px] text-gray-400">Aucune alerte</span>
        )}
      </div>
    </button>
  )
}

function ReconciliationSection({ report }: { report: AuditReportDetail }) {
  const r = report.reconciliation
  const items: { label: string; count: number }[] = []
  if (r.overdue_without_installment_plan && r.overdue_without_installment_plan.count > 0) {
    items.push({ label: 'Facture(s) en retard sans échéancier', count: r.overdue_without_installment_plan.count })
  }
  if (r.late_installment_not_flagged && r.late_installment_not_flagged.count > 0) {
    items.push({ label: 'Échéance(s) en retard non signalée(s)', count: r.late_installment_not_flagged.count })
  }
  if (r.journal_mismatch?.missing_entry_count) {
    items.push({ label: 'Facture(s) journalisée(s) sans écriture', count: r.journal_mismatch.missing_entry_count })
  }
  if (r.journal_mismatch?.duplicate_entry_count) {
    items.push({ label: 'Facture(s) avec écritures en double', count: r.journal_mismatch.duplicate_entry_count })
  }
  if (r.journal_mismatch?.amount_mismatch_count) {
    items.push({ label: 'Facture(s) avec montant incohérent', count: r.journal_mismatch.amount_mismatch_count })
  }
  const overruns = r.budget_overrun_attribution ?? []

  if (items.length === 0 && overruns.length === 0) return null

  return (
    <Card>
      <h3 className="text-sm font-semibold text-gray-800 mb-3">Rapprochement transversal</h3>
      <div className="space-y-1.5">
        {items.map(it => (
          <div key={it.label} className="flex items-center justify-between text-sm">
            <span className="text-gray-600">{it.label}</span>
            <span className="font-semibold" style={{ color: '#C0391B' }}>{it.count}</span>
          </div>
        ))}
        {overruns.map(o => (
          <div key={o.catalog_id} className="text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-600">Dépassement budget — {o.catalog_id}</span>
              <span className="font-semibold" style={{ color: '#C0391B' }}>
                {formatTND(o.actual_ytd, 0)} / {formatTND(o.budget_ytd, 0)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function AuditReportsPage() {
  const { role } = useAuth()
  const isAdmin = role === 'Admin'

  const [granularity, setGranularity] = useState<AuditGranularity>('DAILY')
  const [reports, setReports] = useState<AuditReportSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AuditReportDetail | null>(null)

  const [listLoading, setListLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadList = useCallback(async (g: AuditGranularity) => {
    setListLoading(true)
    setError(null)
    try {
      const data = await listAuditReports({ granularity: g, limit: 30 })
      setReports(data.items)
      if (data.items.length > 0) {
        setSelectedId(data.items[0].id)
      } else {
        setSelectedId(null)
        setDetail(null)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur de chargement des rapports')
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => { loadList(granularity) }, [granularity, loadList])

  useEffect(() => {
    if (!selectedId) return
    setDetailLoading(true)
    setError(null)
    getAuditReport(selectedId)
      .then(setDetail)
      .catch(e => setError(e instanceof Error ? e.message : 'Erreur de chargement du rapport'))
      .finally(() => setDetailLoading(false))
  }, [selectedId])

  const handleRun = async () => {
    setRunning(true)
    setError(null)
    try {
      const result = await runAuditReport(granularity)
      await loadList(granularity)
      setSelectedId(result.snapshot_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Échec de la génération du rapport')
    } finally {
      setRunning(false)
    }
  }

  const sortedAlerts = detail
    ? [...detail.alerts].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
    : []

  return (
    <div>
      <PageHeader title="📊 Rapports d'Audit">
        <button
          onClick={() => loadList(granularity)}
          disabled={listLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-300 hover:bg-gray-50 text-gray-600 disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${listLoading ? 'animate-spin' : ''}`} />
          Actualiser
        </button>
        {isAdmin && (
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg text-white disabled:opacity-50 transition-colors"
            style={{ background: running ? '#5D6D7E' : '#804CD7' }}
          >
            {running ? <RefreshCw size={12} className="animate-spin" /> : <Bot size={12} />}
            {running ? 'Génération en cours…' : 'Générer un rapport maintenant'}
          </button>
        )}
      </PageHeader>

      <div className="p-6 flex flex-col gap-5">
        {error && (
          <div className="px-4 py-3 rounded-xl text-sm font-medium" style={{ background: '#FDECEA', color: '#C0391B' }}>
            {error}
          </div>
        )}

        {/* Granularity selector */}
        <div className="flex items-center gap-2">
          {GRANULARITIES.map(g => (
            <button
              key={g.value}
              onClick={() => setGranularity(g.value)}
              className="px-3 py-1.5 text-sm rounded-lg border font-medium transition-colors"
              style={granularity === g.value
                ? { background: '#1A3A5C', color: '#fff', borderColor: '#1A3A5C' }
                : { background: '#fff', color: '#5D6D7E', borderColor: '#D5E8F5' }}
            >
              {g.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-[280px_1fr] gap-5 items-start">
          {/* Report list */}
          <div>
            {listLoading ? (
              <p className="text-sm text-gray-400 px-1">Chargement…</p>
            ) : reports.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
                <p className="text-sm text-gray-500">Aucun rapport {GRANULARITIES.find(g => g.value === granularity)?.label.toLowerCase()} généré pour l'instant.</p>
                {isAdmin && <p className="text-xs text-gray-400 mt-1">Utilisez « Générer un rapport maintenant » ci-dessus.</p>}
              </div>
            ) : (
              reports.map(r => (
                <ReportRow key={r.id} report={r} active={r.id === selectedId} onClick={() => setSelectedId(r.id)} />
              ))
            )}
          </div>

          {/* Detail */}
          <div className="flex flex-col gap-5">
            {detailLoading ? (
              <p className="text-sm text-gray-400">Chargement du rapport…</p>
            ) : !detail ? (
              <p className="text-sm text-gray-400">Sélectionnez un rapport dans la liste.</p>
            ) : (
              <>
                {detail.status === 'DEGRADED' && (
                  <div className="px-4 py-3 rounded-xl text-sm font-medium" style={{ background: '#FFF8E8', color: '#B07800' }}>
                    ⚠ Rapport partiel (DEGRADED) — Ollama ou ChromaDB indisponible au moment de la génération : narratif et/ou certaines métriques peuvent être incomplets.
                  </div>
                )}

                {/* Alerts */}
                {sortedAlerts.length > 0 ? (
                  <div className="space-y-1.5">
                    {sortedAlerts.map((a, i) => <AlertRow key={i} alert={a} />)}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium" style={{ background: '#E8F5F0', color: '#1D9E76' }}>
                    <CheckCircle2 size={16} /> Aucune alerte pour cette période.
                  </div>
                )}

                {/* Domain metrics */}
                <div className="grid grid-cols-3 gap-4">
                  <KpiCard
                    label="Factures — taux de rejet (30j)"
                    value={`${(detail.metrics.invoices?.rejection_rate as number ?? 0).toFixed(1)}%`}
                    delta={signedDelta(detail.trend.invoices?.rejection_rate)}
                    sub={`${detail.metrics.invoices?.pending_count ?? 0} en attente`}
                  />
                  <KpiCard
                    label="Comptabilité — score de cohérence"
                    value={`${((detail.metrics.journal?.consistency_score as number ?? 1) * 100).toFixed(1)}%`}
                    delta={signedDelta(detail.trend.journal?.consistency_score, 3)}
                    sub={`${(detail.metrics.journal?.issues as unknown[] | undefined)?.length ?? 0} type(s) d'anomalie`}
                  />
                  <KpiCard
                    label="Budget — écart global YTD"
                    value={`${(detail.metrics.budget?.variance_pct as number ?? 0) >= 0 ? '+' : ''}${detail.metrics.budget?.variance_pct ?? 0}%`}
                    delta={signedDelta(detail.trend.budget?.variance_pct)}
                    sub={`${detail.metrics.budget?.n_over_budget ?? 0}/${detail.metrics.budget?.n_total ?? 0} lignes en dépassement`}
                  />
                  <KpiCard
                    label="Échéancier — retards"
                    value={String(detail.metrics.echeancier?.n_late ?? 0)}
                    delta={signedDelta(detail.trend.echeancier?.n_late, 0)}
                    sub={`${formatTND(detail.metrics.echeancier?.total_penalty_amount as number ?? 0, 0)} de pénalités`}
                  />
                  <KpiCard
                    label="Risques critiques actifs"
                    value={String(detail.metrics.risks?.n_critique ?? 0)}
                    delta={signedDelta(detail.trend.risks?.n_critique, 0)}
                    sub={`${detail.metrics.risks?.n_overdue_mitigation ?? 0} mitigation(s) en retard`}
                  />
                  <KpiCard
                    label="Roadmap — jalons en retard"
                    value={String(detail.metrics.roadmap?.n_overdue_milestones ?? 0)}
                    delta={signedDelta(detail.trend.roadmap?.n_overdue_milestones, 0)}
                    sub={`${detail.metrics.roadmap?.pct_done ?? 0}% jalons terminés`}
                  />
                </div>

                <ReconciliationSection report={detail} />

                {/* Narrative */}
                {detail.narrative_summary && (
                  <div className="p-4 rounded-xl text-sm" style={{ background: '#F0EBF9', color: '#3D2166' }}>
                    <p className="text-xs font-semibold mb-1.5" style={{ color: '#804CD7' }}>🤖 Synthèse IA</p>
                    {detail.narrative_summary}
                  </div>
                )}

                {/* Similar incidents (RAG) */}
                {detail.similar_incidents.length > 0 && (
                  <Card>
                    <h3 className="text-sm font-semibold text-gray-800 mb-3">Incidents similaires (historique)</h3>
                    <div className="space-y-2">
                      {detail.similar_incidents.map((inc, i) => (
                        <div key={i} className="text-xs border-l-2 pl-2.5" style={{ borderColor: '#D5E8F5' }}>
                          <div className="flex items-center gap-2 text-gray-400 mb-0.5">
                            <span>{inc.date ? formatDate(inc.date) : '—'}</span>
                            <span>· similarité {(inc.similarity * 100).toFixed(0)}%</span>
                            <span>· lié à {inc.related_alert_code}</span>
                          </div>
                          <p className="text-gray-700">{inc.excerpt}</p>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
