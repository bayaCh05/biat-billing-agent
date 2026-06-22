import { useState } from 'react'
import { Plus } from 'lucide-react'
import type { Project, ProjectStatus } from '../types'
import { mockProjects } from '../data/mockProjects'

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
          {mockProjects.map(project => (
            <ProjectCard key={project.id} project={project} />
          ))}
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
          <div className="bg-white rounded-xl border p-8 text-center" style={{ borderColor: '#D5E8F5' }}>
            <p className="text-sm" style={{ color: '#5D6D7E' }}>Historique des factures — à venir</p>
          </div>
        </div>
      )}
    </div>
  )
}
