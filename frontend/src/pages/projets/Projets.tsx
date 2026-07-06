import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { CreditCard, FolderKanban } from 'lucide-react'
import PageHeader from '../../components/ui/PageHeader'
import PageSpinner from '../../components/ui/PageSpinner'
import { listTemplates, listProjects } from '../../api/endpoints'
import { formatTND } from '../../utils/formatters'
import type { ClientTemplate, Project } from '../../types'

// ── Templates (billing services) ──────────────────────────────────────────────

interface ProjectCard {
  id: string; name: string; client: string; description: string
  unit_price_ht: number; tva_rate: number; status: 'ACTIVE' | 'ON_HOLD'
}

function templateToCard(t: ClientTemplate): ProjectCard {
  return {
    id: t.id,
    name: t.id.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' '),
    client: t.client_name,
    description: t.service_description.slice(0, 100),
    unit_price_ht: t.unit_price_ht,
    tva_rate: t.tva_rate,
    status: t.unit_price_ht > 0 ? 'ACTIVE' : 'ON_HOLD',
  }
}

const TEMPLATE_STATUS = {
  ACTIVE:  { label: 'Actif',     bg: '#E8F5F0', color: '#1D9E76' },
  ON_HOLD: { label: 'Sur devis', bg: '#FFF8E8', color: '#F0A600' },
}

const PROJECT_STATUS: Record<string, { label: string; bg: string; color: string }> = {
  ACTIVE:    { label: 'Actif',    bg: '#E8F5F0', color: '#1D9E76' },
  COMPLETED: { label: 'Terminé', bg: '#EFF4FA', color: '#1A3A5C' },
  ON_HOLD:   { label: 'En pause', bg: '#FFF8E8', color: '#F0A600' },
  CANCELLED: { label: 'Annulé',  bg: '#FEF0EE', color: '#C0391B' },
}

export default function Projets() {
  const navigate = useNavigate()
  const [cards, setCards] = useState<ProjectCard[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    Promise.all([listTemplates(), listProjects()])
      .then(([templates, projs]) => {
        setCards(templates.map(templateToCard))
        setProjects(projs)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  if (loading || error) return <PageSpinner loading={loading} error={error} />

  const totalMonthly = cards.reduce((s, c) => s + c.unit_price_ht, 0)
  const activeProjects = projects.filter(p => p.status === 'ACTIVE').length

  return (
    <div>
      <PageHeader title="Projets IT & Services" badge={`${projects.length} projets · ${cards.length} services`} />

      <div className="p-6 space-y-6">

        {/* ── KPI row ── */}
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Projets IT actifs',    value: String(activeProjects),     color: '#1D9E76' },
            { label: 'Services de facturation', value: String(cards.filter(c => c.status === 'ACTIVE').length), color: '#1A3A5C' },
            { label: 'Revenus mensuels HT',  value: formatTND(totalMonthly),    color: '#5BA3C9' },
            { label: 'Clients facturés',     value: String(new Set(cards.map(c => c.client)).size), color: '#804CD7' },
          ].map(s => (
            <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
              <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* ── CharteProjet list ── */}
        {projects.length > 0 && (
          <section>
            <h2 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: '#1A3A5C' }}>
              <FolderKanban size={16} /> Projets IT (Chartes)
            </h2>
            <div className="space-y-3">
              {projects.map(p => {
                const st = PROJECT_STATUS[p.status] ?? PROJECT_STATUS.ACTIVE
                const pct = p.budget_jh > 0 ? Math.round(p.consumed_jh / p.budget_jh * 100) : 0
                return (
                  <div
                    key={p.id}
                    className="bg-white rounded-xl border p-5 cursor-pointer hover:shadow-md transition-all"
                    style={{ borderColor: '#D5E8F5' }}
                    onClick={() => navigate(`/projets-it/${p.id}`)}
                  >
                    <div className="flex items-start justify-between gap-4 mb-3">
                      <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg" style={{ background: '#EFF4FA' }}>
                          <FolderKanban size={18} style={{ color: '#1A3A5C' }} />
                        </div>
                        <div>
                          <p className="font-semibold text-sm" style={{ color: '#1A1A2E' }}>{p.name}</p>
                          <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{p.client}</p>
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold shrink-0" style={{ background: st.bg, color: st.color }}>
                        {st.label}
                      </span>
                    </div>
                    <div className="flex items-center gap-6 mb-2">
                      {[
                        { label: 'Budget JH', value: `${p.budget_jh} JH` },
                        { label: 'Consommé',  value: `${p.consumed_jh} JH` },
                        { label: 'Taux JH',   value: `${formatTND(p.taux_jh)}/JH` },
                        { label: 'Budget TND', value: formatTND(p.budget_tnd) },
                      ].map(s => (
                        <div key={s.label}>
                          <p className="text-xs" style={{ color: '#5D6D7E' }}>{s.label}</p>
                          <p className="font-semibold text-sm" style={{ color: '#1A3A5C' }}>{s.value}</p>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 rounded-full h-1.5" style={{ background: '#E2EBF3' }}>
                        <div className="h-1.5 rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: pct > 100 ? '#C0391B' : pct >= 80 ? '#F0A500' : '#1D9E76' }} />
                      </div>
                      <span className="text-xs font-semibold shrink-0" style={{ color: '#5D6D7E' }}>{pct}%</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* ── Billing templates ── */}
        <section>
          <h2 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: '#1A3A5C' }}>
            <CreditCard size={16} /> Services de facturation
          </h2>
          <div className="space-y-3">
            {cards.map(card => {
              const st = TEMPLATE_STATUS[card.status]
              const ttc = card.unit_price_ht * (1 + card.tva_rate / 100)
              return (
                <div
                  key={card.id}
                  className="bg-white rounded-xl border p-5 cursor-pointer hover:shadow-md transition-all"
                  style={{ borderColor: '#D5E8F5' }}
                  onClick={() => navigate(`/projects/${card.id}`)}
                >
                  <div className="flex items-start justify-between gap-4 mb-2">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg" style={{ background: '#E3F0F9' }}>
                        <CreditCard size={18} style={{ color: '#1A3A5C' }} />
                      </div>
                      <div>
                        <p className="font-semibold text-sm" style={{ color: '#1A1A2E' }}>{card.name}</p>
                        <p className="text-xs mt-0.5" style={{ color: '#5D6D7E' }}>{card.client}</p>
                      </div>
                    </div>
                    <span className="px-2.5 py-1 rounded-full text-xs font-semibold shrink-0" style={{ background: st.bg, color: st.color }}>
                      {st.label}
                    </span>
                  </div>
                  <p className="text-xs mb-2" style={{ color: '#5D6D7E' }}>{card.description}{card.description.length >= 100 ? '…' : ''}</p>
                  <div className="flex items-center gap-6">
                    <div>
                      <p className="text-xs" style={{ color: '#5D6D7E' }}>Prix HT/mois</p>
                      <p className="font-bold text-sm" style={{ color: card.unit_price_ht > 0 ? '#1A3A5C' : '#5D6D7E' }}>
                        {card.unit_price_ht > 0 ? formatTND(card.unit_price_ht) : 'Sur devis'}
                      </p>
                    </div>
                    {card.unit_price_ht > 0 && (
                      <div>
                        <p className="text-xs" style={{ color: '#5D6D7E' }}>TTC/mois</p>
                        <p className="font-bold text-sm" style={{ color: '#5D6D7E' }}>{formatTND(ttc)}</p>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}
