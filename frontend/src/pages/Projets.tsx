import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { CreditCard } from 'lucide-react'
import PageHeader from '../components/ui/PageHeader'
import { listTemplates } from '../api/endpoints'
import { mockProjects } from '../data/mockProjects'
import { formatTND } from '../utils/formatters'
import type { ClientTemplate } from '../types'

interface ProjectCard {
  id: string
  name: string
  client: string
  description: string
  unit_price_ht: number
  tva_rate: number
  status: 'ACTIVE' | 'ON_HOLD'
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

const STATUS_MAP = {
  ACTIVE:  { label: 'Actif',      bg: '#E8F5F0', color: '#1D9E76' },
  ON_HOLD: { label: 'Sur devis',  bg: '#FFF8E8', color: '#F0A600' },
}

// Mock fallback shaped as ProjectCards
const mockCards: ProjectCard[] = mockProjects.slice(0, 3).map(p => ({
  id: p.id,
  name: p.name,
  client: p.client,
  description: 'Service informatique mensuel',
  unit_price_ht: p.budget_tnd / 12,
  tva_rate: 19,
  status: p.status === 'ACTIVE' ? 'ACTIVE' : 'ON_HOLD',
}))

export default function Projets() {
  const navigate = useNavigate()
  const [cards, setCards] = useState<ProjectCard[]>(mockCards)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listTemplates()
      .then(templates => {
        const mapped = templates.map(templateToCard)
        if (mapped.length > 0) setCards(mapped)
      })
      .catch(() => { /* keep mock */ })
      .finally(() => setLoading(false))
  }, [])

  const totalMonthly = cards.reduce((s, c) => s + c.unit_price_ht, 0)
  const uniqueClients = new Set(cards.map(c => c.client)).size
  const activeCount = cards.filter(c => c.status === 'ACTIVE').length

  return (
    <div>
      <PageHeader title="🗂️ Services & Facturation" badge={`${cards.length} services`} />

      <div className="p-6 space-y-6">
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Services actifs',      value: String(activeCount),            color: '#1D9E76' },
            { label: 'Revenus mensuels HT',  value: formatTND(totalMonthly),        color: '#1A3A5C' },
            { label: 'Clients facturés',     value: String(uniqueClients),          color: '#5BA3C9' },
          ].map(s => (
            <div key={s.label} className="bg-white rounded-xl border p-4" style={{ borderColor: '#D5E8F5' }}>
              <p className="text-xs font-medium mb-1" style={{ color: '#5D6D7E' }}>{s.label}</p>
              <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
            </div>
          ))}
        </div>

        {loading && (
          <p className="text-sm text-center py-4" style={{ color: '#5D6D7E' }}>Chargement…</p>
        )}

        <div className="space-y-3">
          {cards.map(card => {
            const st = STATUS_MAP[card.status]
            const ttc = card.unit_price_ht * (1 + card.tva_rate / 100)
            return (
              <div
                key={card.id}
                className="bg-white rounded-xl border p-5 cursor-pointer hover:shadow-md transition-all"
                style={{ borderColor: '#D5E8F5' }}
                onClick={() => navigate(`/projects/${card.id}`)}
              >
                <div className="flex items-start justify-between gap-4 mb-3">
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

                <p className="text-xs mb-3" style={{ color: '#5D6D7E' }}>{card.description}{card.description.length >= 100 ? '…' : ''}</p>

                <div className="flex items-center gap-6">
                  <div>
                    <p className="text-xs" style={{ color: '#5D6D7E' }}>Prix HT/mois</p>
                    <p className="font-bold text-sm" style={{ color: card.unit_price_ht > 0 ? '#1A3A5C' : '#5D6D7E' }}>
                      {card.unit_price_ht > 0 ? formatTND(card.unit_price_ht) : 'Sur devis'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs" style={{ color: '#5D6D7E' }}>TVA {card.tva_rate}%</p>
                    <p className="font-bold text-sm" style={{ color: '#5D6D7E' }}>
                      {card.unit_price_ht > 0 ? formatTND(ttc) + ' TTC' : '—'}
                    </p>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
