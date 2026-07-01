import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Plus, ChevronDown, ChevronRight, CheckCircle, X } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import Card from '../components/ui/Card'
import Button from '../components/ui/Button'
import { useAuth } from '../context/AuthContext'
import type { Project, ProjectPhase, LigneBudget, BudgetSynthese, Livrable, Risk, NiveauCriticite } from '../types'
import {
  getProject, listProjectPhases,
  listProjetBudget, createLigneBudget, deleteLigneBudget, getBudgetSynthese,
  listLivrables, createLivrable, updateLivrable, validerPhase,
  getRisksForProject,
} from '../api/endpoints'

const CRITICITE_COLOR: Record<NiveauCriticite, string> = {
  FAIBLE:   '#1D9E76',
  MOYENNE:  '#F0A500',
  ELEVEE:   '#E67E22',
  CRITIQUE: '#C0391B',
}
const CRITICITE_BG: Record<NiveauCriticite, string> = {
  FAIBLE:   '#E6F9F3',
  MOYENNE:  '#FEF9E7',
  ELEVEE:   '#FDF2E9',
  CRITIQUE: '#FDEDEC',
}
const STATUT_RISQUE_LABEL: Record<string, string> = {
  IDENTIFIE: 'Identifié', EN_SURVEILLANCE: 'Surveillance', EN_TRAITEMENT: 'Traitement',
  MAITRISE: 'Maîtrisé', SURVENU: 'Survenu', CLOTURE: 'Clôturé',
}
import { formatTND } from '../utils/formatters'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s: string | null) {
  if (!s) return '—'
  const d = new Date(s)
  return d.toLocaleDateString('fr-TN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

const LIVRABLE_BADGE: Record<string, { label: string; bg: string; color: string }> = {
  EN_ATTENTE: { label: 'En attente', bg: '#EFF4FA', color: '#1A3A5C' },
  EN_COURS:   { label: 'En cours',   bg: '#FFF8E8', color: '#B07800' },
  LIVRE:      { label: 'Livré',      bg: '#E3F0F9', color: '#2E86C1' },
  VALIDE:     { label: 'Validé',     bg: '#E8F5F0', color: '#0D6E52' },
  REJETE:     { label: 'Rejeté',     bg: '#FEF0EE', color: '#C0391B' },
}

const PHASE_BADGE: Record<string, { label: string; bg: string; color: string }> = {
  OPEN:       { label: 'Ouverte',   bg: '#EFF4FA', color: '#1A3A5C' },
  IN_PROGRESS:{ label: 'En cours',  bg: '#FFF8E8', color: '#B07800' },
  CLOSED:     { label: 'Fermée',    bg: '#F0F4F9', color: '#5D6D7E' },
  VALIDEE:    { label: 'Validée',   bg: '#E8F5F0', color: '#0D6E52' },
}

function ProgressBar({ pct }: { pct: number }) {
  const color = pct > 100 ? '#C0391B' : pct >= 80 ? '#F0A500' : '#1D9E76'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 rounded-full h-1.5" style={{ background: '#E2EBF3' }}>
        <div className="h-1.5 rounded-full transition-all" style={{ width: `${Math.min(100, pct)}%`, background: color }} />
      </div>
      <span className="text-xs font-semibold shrink-0" style={{ color }}>{pct.toFixed(0)}%</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ProjetDetailIT() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { role } = useAuth()
  const canEdit = ['Chef de Projet', 'Admin'].includes(role)

  const [tab, setTab] = useState<'phases' | 'budget' | 'risques'>('phases')
  const [project, setProject] = useState<Project | null>(null)
  const [phases, setPhases] = useState<ProjectPhase[]>([])
  const [budgetLines, setBudgetLines] = useState<LigneBudget[]>([])
  const [synthese, setSynthese] = useState<BudgetSynthese | null>(null)
  const [risks, setRisks] = useState<Risk[]>([])
  const [loading, setLoading] = useState(true)

  // Livrables per phase (keyed by phase id)
  const [livrables, setLivrables] = useState<Record<string, Livrable[]>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  // Budget modal
  const [showBudgetModal, setShowBudgetModal] = useState(false)
  const [budgetForm, setBudgetForm] = useState({ categorie: '', montant_prevu: '' })
  const [savingBudget, setSavingBudget] = useState(false)

  // Livrable modal
  const [livModal, setLivModal] = useState<{ phaseId: string; phaseName: string } | null>(null)
  const [livForm, setLivForm] = useState({ titre: '', description: '', date_livraison_prevue: '', statut: 'EN_ATTENTE' })
  const [savingLiv, setSavingLiv] = useState(false)

  // Validation
  const [validating, setValidating] = useState<string | null>(null)
  const [validationMsg, setValidationMsg] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!id) return
    setLoading(true)
    Promise.all([getProject(id), listProjectPhases(id), listProjetBudget(id), getBudgetSynthese(id), getRisksForProject(id).catch(() => [])])
      .then(([proj, ph, budget, syn, rs]) => {
        setProject(proj); setPhases(ph); setBudgetLines(budget); setSynthese(syn); setRisks(rs as Risk[])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  async function togglePhase(phaseId: string) {
    const next = new Set(expanded)
    if (next.has(phaseId)) { next.delete(phaseId) } else {
      next.add(phaseId)
      if (!livrables[phaseId]) {
        const lv = await listLivrables(phaseId).catch(() => [])
        setLivrables(prev => ({ ...prev, [phaseId]: lv }))
      }
    }
    setExpanded(next)
  }

  async function handleAddLivrable() {
    if (!livModal) return
    setSavingLiv(true)
    try {
      const lv = await createLivrable(livModal.phaseId, {
        titre: livForm.titre,
        description: livForm.description,
        date_livraison_prevue: livForm.date_livraison_prevue,
        statut: livForm.statut,
      })
      setLivrables(prev => ({ ...prev, [livModal.phaseId]: [...(prev[livModal.phaseId] ?? []), lv] }))
      setLivModal(null)
      setLivForm({ titre: '', description: '', date_livraison_prevue: '', statut: 'EN_ATTENTE' })
    } catch { /* ignore */ }
    setSavingLiv(false)
  }

  async function handleLivrableStatut(liv: Livrable, statut: string) {
    try {
      const updated = await updateLivrable(liv.id, { statut })
      setLivrables(prev => ({
        ...prev,
        [liv.phase_id]: prev[liv.phase_id].map(l => l.id === liv.id ? updated : l),
      }))
    } catch { /* ignore */ }
  }

  async function handleValiderPhase(phase: ProjectPhase) {
    setValidating(phase.id)
    try {
      const res = await validerPhase(phase.id)
      setPhases(prev => prev.map(p => p.id === phase.id ? { ...p, status: 'CLOSED' } : p))
      setValidationMsg(prev => ({ ...prev, [phase.id]: res.message }))
    } catch (err) {
      setValidationMsg(prev => ({ ...prev, [phase.id]: err instanceof Error ? err.message : 'Erreur de validation.' }))
    }
    setValidating(null)
  }

  async function handleAddBudgetLine() {
    if (!id) return
    setSavingBudget(true)
    try {
      const lb = await createLigneBudget(id, { categorie: budgetForm.categorie, montant_prevu: parseFloat(budgetForm.montant_prevu) })
      setBudgetLines(prev => [...prev, lb])
      const syn = await getBudgetSynthese(id)
      setSynthese(syn)
      setShowBudgetModal(false)
      setBudgetForm({ categorie: '', montant_prevu: '' })
    } catch { /* ignore */ }
    setSavingBudget(false)
  }

  async function handleDeleteBudgetLine(ligneId: string) {
    try {
      await deleteLigneBudget(ligneId)
      setBudgetLines(prev => prev.filter(l => l.id !== ligneId))
      if (id) { const syn = await getBudgetSynthese(id); setSynthese(syn) }
    } catch { /* ignore */ }
  }

  if (loading) return <div className="p-6 text-sm" style={{ color: '#5D6D7E' }}>Chargement…</div>
  if (!project) return <div className="p-6 text-sm" style={{ color: '#C0391B' }}>Projet non trouvé.</div>

  const inp = 'w-full border rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-400 transition-all'

  const budgetPct = project.budget_tnd > 0 ? Math.round(project.spent_tnd / project.budget_tnd * 100) : 0

  return (
    <div>
      <PageHeader title={project.name} badge={project.client}>
        <Button variant="secondary" icon={<ArrowLeft size={13} />} onClick={() => navigate('/projects')}>Retour</Button>
      </PageHeader>

      {/* Summary cards */}
      <div className="px-6 pt-5 grid grid-cols-4 gap-4">
        {[
          { label: 'Budget JH',      value: `${project.budget_jh} JH`,      color: '#1A3A5C' },
          { label: 'Consommé JH',    value: `${project.consumed_jh} JH`,     color: '#5BA3C9' },
          { label: 'Budget TND',     value: formatTND(project.budget_tnd),    color: '#1A3A5C' },
          { label: 'Dépensé TND',    value: formatTND(project.spent_tnd),     color: budgetPct > 100 ? '#C0391B' : '#1D9E76' },
        ].map(s => (
          <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
            <p className="text-xs mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
            <p className="text-lg font-bold" style={{ color: s.color }}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-0 px-6 pt-5 border-b" style={{ borderColor: '#E2EBF3' }}>
        {(['phases', 'budget', 'risques'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className="pb-3 px-4 text-sm font-semibold border-b-2 transition-all"
            style={{
              borderColor: tab === t ? '#1A3A5C' : 'transparent',
              color: tab === t ? '#1A3A5C' : '#5D6D7E',
            }}
          >
            {t === 'phases' ? 'Phases & Livrables' : t === 'budget' ? 'Budget' : `Risques${risks.length > 0 ? ` (${risks.length})` : ''}`}
          </button>
        ))}
      </div>

      <div className="p-6 space-y-4">

        {/* ── PHASES TAB ─────────────────────────────────────────────────────── */}
        {tab === 'phases' && (
          phases.length === 0 ? (
            <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>Aucune phase définie pour ce projet.</p>
          ) : (
            phases.map(phase => {
              const badge = PHASE_BADGE[phase.status] ?? PHASE_BADGE.OPEN
              const phaseLivs = livrables[phase.id] ?? []
              const isExpanded = expanded.has(phase.id)
              const allDone = phaseLivs.length > 0 && phaseLivs.every(l => ['LIVRE', 'VALIDE'].includes(l.statut))

              return (
                <Card key={phase.id}>
                  {/* Phase header */}
                  <div className="flex items-center gap-3">
                    <button onClick={() => togglePhase(phase.id)} className="flex items-center gap-2 flex-1 text-left">
                      {isExpanded ? <ChevronDown size={15} style={{ color: '#5D6D7E' }} /> : <ChevronRight size={15} style={{ color: '#5D6D7E' }} />}
                      <span className="font-semibold text-sm" style={{ color: '#1A1A2E' }}>{phase.name}</span>
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={{ background: badge.bg, color: badge.color }}>
                        {badge.label}
                      </span>
                    </button>
                    <div className="shrink-0 text-xs" style={{ color: '#5D6D7E' }}>
                      {phase.consumed_jh}/{phase.planned_jh} JH
                    </div>
                    {canEdit && phase.status !== 'CLOSED' && (phase.status as string) !== 'VALIDEE' && (
                      <button
                        onClick={() => { setLivModal({ phaseId: phase.id, phaseName: phase.name }); setLivForm({ titre: '', description: '', date_livraison_prevue: '', statut: 'EN_ATTENTE' }) }}
                        className="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded transition-colors hover:bg-blue-50"
                        style={{ color: '#2E86C1' }}
                      >
                        <Plus size={12} /> Livrable
                      </button>
                    )}
                    {canEdit && allDone && (phase.status as string) !== 'VALIDEE' && (
                      <button
                        disabled={validating === phase.id}
                        onClick={() => handleValiderPhase(phase)}
                        className="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded transition-colors hover:bg-green-50 disabled:opacity-50"
                        style={{ color: '#0D6E52' }}
                      >
                        <CheckCircle size={12} /> Valider la phase
                      </button>
                    )}
                  </div>

                  {/* Validation message */}
                  {validationMsg[phase.id] && (
                    <div className="mt-2 text-xs px-3 py-1.5 rounded" style={{ background: validationMsg[phase.id].includes('succès') ? '#E8F5F0' : '#FEF0EE', color: validationMsg[phase.id].includes('succès') ? '#0D6E52' : '#C0391B' }}>
                      {validationMsg[phase.id]}
                    </div>
                  )}

                  {/* Livrables */}
                  {isExpanded && (
                    <div className="mt-3 ml-5 space-y-2">
                      {phaseLivs.length === 0 ? (
                        <p className="text-xs" style={{ color: '#9BAFBF' }}>Aucun livrable — cliquez "+ Livrable" pour en ajouter.</p>
                      ) : (
                        phaseLivs.map(lv => {
                          const b = LIVRABLE_BADGE[lv.statut] ?? LIVRABLE_BADGE.EN_ATTENTE
                          return (
                            <div key={lv.id} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: '#F8FAFC', border: '1px solid #E2EBF3' }}>
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium truncate" style={{ color: '#1A1A2E' }}>{lv.titre}</p>
                                <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>
                                  Prévu : {fmtDate(lv.date_livraison_prevue)}
                                  {lv.date_livraison_reelle && ` · Livré : ${fmtDate(lv.date_livraison_reelle)}`}
                                </p>
                              </div>
                              <span className="px-2 py-0.5 rounded-full text-xs font-semibold shrink-0" style={{ background: b.bg, color: b.color }}>
                                {b.label}
                              </span>
                              {canEdit && (
                                <select
                                  className="border rounded px-1 py-0.5 text-xs shrink-0"
                                  style={{ borderColor: '#D5E8F5' }}
                                  value={lv.statut}
                                  onChange={e => handleLivrableStatut(lv, e.target.value)}
                                >
                                  {Object.keys(LIVRABLE_BADGE).map(k => <option key={k} value={k}>{k}</option>)}
                                </select>
                              )}
                            </div>
                          )
                        })
                      )}
                    </div>
                  )}
                </Card>
              )
            })
          )
        )}

        {/* ── BUDGET TAB ─────────────────────────────────────────────────────── */}
        {tab === 'budget' && (
          <>
            {/* Synthese */}
            {synthese && (
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: 'Total prévu',     value: formatTND(synthese.total_prevu),    color: '#1A3A5C' },
                  { label: 'Total consommé',  value: formatTND(synthese.total_consomme), color: '#5BA3C9' },
                  { label: 'Écart',           value: formatTND(synthese.ecart),          color: synthese.ecart >= 0 ? '#1D9E76' : '#C0391B' },
                  { label: 'Taux consommation', value: `${synthese.taux_consommation}%`, color: synthese.taux_consommation > 100 ? '#C0391B' : synthese.taux_consommation >= 80 ? '#F0A500' : '#1D9E76' },
                ].map(s => (
                  <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
                    <p className="text-xs mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
                    <p className="text-lg font-bold" style={{ color: s.color }}>{s.value}</p>
                  </div>
                ))}
              </div>
            )}

            <Card>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold" style={{ color: '#1A3A5C' }}>Lignes budgétaires</h3>
                {canEdit && (
                  <Button size="sm" icon={<Plus size={13} />} onClick={() => setShowBudgetModal(true)}>
                    Ajouter ligne
                  </Button>
                )}
              </div>

              {budgetLines.length === 0 ? (
                <p className="text-sm text-center py-8" style={{ color: '#5D6D7E' }}>
                  Aucune ligne budgétaire. {canEdit && 'Cliquez "Ajouter ligne" pour commencer.'}
                </p>
              ) : (
                <div className="space-y-3">
                  {budgetLines.map(lb => (
                    <div key={lb.id}>
                      <div className="flex items-center gap-3 mb-1.5">
                        <span className="text-sm font-medium flex-1" style={{ color: '#1A1A2E' }}>{lb.categorie}</span>
                        <span className="text-xs" style={{ color: '#5D6D7E' }}>
                          {formatTND(lb.montant_consomme)} / {formatTND(lb.montant_prevu)} {lb.devise}
                        </span>
                        {canEdit && (
                          <button onClick={() => handleDeleteBudgetLine(lb.id)} className="text-gray-300 hover:text-red-400 transition-colors">
                            <X size={13} />
                          </button>
                        )}
                      </div>
                      <ProgressBar pct={lb.taux_consommation} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )}

        {/* ── RISQUES TAB ────────────────────────────────────────────────────── */}
        {tab === 'risques' && (
          risks.length === 0 ? (
            <Card>
              <p className="text-sm text-center py-10" style={{ color: '#5D6D7E' }}>Aucun risque enregistré pour ce projet.</p>
            </Card>
          ) : (
            <div className="space-y-3">
              {risks.map(r => (
                <Card key={r.id}>
                  <div className="flex items-start gap-3">
                    <span
                      className="shrink-0 text-xs font-bold px-2 py-1 rounded-full mt-0.5"
                      style={{
                        color: CRITICITE_COLOR[r.niveau_criticite as NiveauCriticite],
                        background: CRITICITE_BG[r.niveau_criticite as NiveauCriticite],
                      }}
                    >
                      {r.niveau_criticite}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold" style={{ color: '#1A3A5C' }}>{r.titre}</p>
                      {r.description && <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{r.description}</p>}
                      <div className="flex items-center gap-3 mt-1.5 text-xs" style={{ color: '#5D6D7E' }}>
                        <span>P: {r.probabilite}</span>
                        <span>I: {r.impact}</span>
                        <span>{STATUT_RISQUE_LABEL[r.statut] ?? r.statut}</span>
                        {r.date_echeance_mitigation && <span>Échéance: {r.date_echeance_mitigation}</span>}
                      </div>
                      {r.plan_mitigation && (
                        <p className="text-xs mt-1.5 p-2 rounded" style={{ background: '#F5F8FC', color: '#374151' }}>
                          Mitigation: {r.plan_mitigation}
                        </p>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )
        )}
      </div>

      {/* Livrable modal */}
      {livModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-base" style={{ color: '#1A1A2E' }}>Ajouter un livrable</h3>
              <button onClick={() => setLivModal(null)}><X size={18} style={{ color: '#5D6D7E' }} /></button>
            </div>
            <p className="text-xs mb-4" style={{ color: '#5D6D7E' }}>Phase : {livModal.phaseName}</p>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Titre</label>
                <input className={inp} value={livForm.titre} onChange={e => setLivForm(f => ({ ...f, titre: e.target.value }))} placeholder="Ex : Document de spécifications" style={{ borderColor: '#D5E8F5' }} />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Description (optionnel)</label>
                <textarea className={inp} rows={2} value={livForm.description} onChange={e => setLivForm(f => ({ ...f, description: e.target.value }))} style={{ borderColor: '#D5E8F5', resize: 'none' }} />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Date de livraison prévue</label>
                <input type="date" className={inp} value={livForm.date_livraison_prevue} onChange={e => setLivForm(f => ({ ...f, date_livraison_prevue: e.target.value }))} style={{ borderColor: '#D5E8F5' }} />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <Button onClick={handleAddLivrable} disabled={savingLiv || !livForm.titre || !livForm.date_livraison_prevue}>
                {savingLiv ? 'Enregistrement…' : 'Ajouter'}
              </Button>
              <Button variant="secondary" onClick={() => setLivModal(null)}>Annuler</Button>
            </div>
          </div>
        </div>
      )}

      {/* Budget modal */}
      {showBudgetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.35)' }}>
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-base" style={{ color: '#1A1A2E' }}>Nouvelle ligne budgétaire</h3>
              <button onClick={() => setShowBudgetModal(false)}><X size={18} style={{ color: '#5D6D7E' }} /></button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Catégorie</label>
                <input className={inp} value={budgetForm.categorie} onChange={e => setBudgetForm(f => ({ ...f, categorie: e.target.value }))} placeholder="Ex : Ressources Humaines" style={{ borderColor: '#D5E8F5' }} />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: '#374151' }}>Montant prévu (TND)</label>
                <input type="number" min="0" step="0.001" className={inp} value={budgetForm.montant_prevu} onChange={e => setBudgetForm(f => ({ ...f, montant_prevu: e.target.value }))} placeholder="0.000" style={{ borderColor: '#D5E8F5' }} />
              </div>
            </div>
            <div className="flex gap-2 mt-5">
              <Button onClick={handleAddBudgetLine} disabled={savingBudget || !budgetForm.categorie || !budgetForm.montant_prevu}>
                {savingBudget ? 'Enregistrement…' : 'Ajouter'}
              </Button>
              <Button variant="secondary" onClick={() => setShowBudgetModal(false)}>Annuler</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
