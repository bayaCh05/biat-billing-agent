import { NavLink, useNavigate } from 'react-router-dom'
import {
  Home, LayoutDashboard, ClipboardList, Files,
  Activity, BookOpen, BookMarked, CreditCard, BarChart2,
  Building2, TrendingUp, Gauge, MessageSquare, FolderKanban, LogOut,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

const NAV_BY_ROLE: Record<string, string[]> = {
  'Comptable':      ['/', '/dashboard', '/review', '/invoices', '/suivi', '/journal', '/grand-livre', '/billing', '/projects', '/budget', '/capex', '/kpi', '/requetes'],
  'Chef de Projet': ['/', '/dashboard', '/invoices', '/suivi', '/billing', '/projects', '/budget'],
  'Direction':      ['/', '/direction', '/kpi', '/budget', '/capex', '/requetes'],
}

const nav = [
  { path: '/',            icon: Home,            label: 'Accueil' },
  { path: '/dashboard',   icon: LayoutDashboard, label: 'Tableau de bord' },
  { path: '/review',      icon: ClipboardList,   label: 'File de révision' },
  { path: '/invoices',    icon: Files,           label: 'Factures' },
  { path: '/suivi',       icon: Activity,        label: 'Suivi' },
  { path: '/journal',     icon: BookOpen,        label: 'Journal' },
  { path: '/grand-livre', icon: BookMarked,      label: 'Grand Livre' },
  { path: '/billing',     icon: CreditCard,      label: 'Facturation' },
  { path: '/projects',    icon: FolderKanban,    label: 'Projets' },
  { path: '/budget',      icon: BarChart2,       label: 'Budget' },
  { path: '/capex',       icon: Building2,       label: 'Immobilisations' },
  { path: '/direction',   icon: TrendingUp,      label: 'Direction' },
  { path: '/kpi',         icon: Gauge,           label: 'KPI Dashboard' },
  { path: '/requetes',    icon: MessageSquare,   label: 'Requêtes' },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const { name, initials, role } = useAuth()

  const visibleNav = nav.filter(item => {
    const allowed = NAV_BY_ROLE[role]
    return !allowed || allowed.includes(item.path)
  })

  const avatarBg = role === 'Direction' ? '#804CD7' : role === 'Chef de Projet' ? '#F0A600' : '#1A3A5C'

  return (
    <aside
      className="flex flex-col h-screen shrink-0"
      style={{ width: 164, background: '#14293F' }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2.5 px-4 py-3"
        style={{ background: '#0F1E2E' }}
      >
        <div
          className="flex flex-col items-center justify-center gap-1 rounded-lg shrink-0"
          style={{ width: 32, height: 32, background: '#1A3A5C' }}
        >
          <div className="rounded-full" style={{ width: 16, height: 2, background: '#5BA3C9' }} />
          <div className="rounded-full" style={{ width: 12, height: 2, background: '#F0A600' }} />
        </div>
        <div>
          <p className="text-sm font-bold text-white leading-tight">BIAT IT</p>
          <p className="text-xs" style={{ color: '#5BA3C9' }}>Facturation</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {visibleNav.map(({ path, icon: Icon, label }) => (
          <NavLink
            key={path}
            to={path}
            end={path === '/'}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-2.5 py-2 text-xs rounded-lg mb-0.5 transition-all ${
                isActive ? 'font-semibold text-white' : 'font-normal text-white/70 hover:text-white hover:bg-white/5'
              }`
            }
            style={({ isActive }) =>
              isActive
                ? { background: '#1A3A5C', borderLeft: '3px solid #F0A600', paddingLeft: 7 }
                : {}
            }
          >
            <Icon size={14} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div
        className="flex items-center gap-2 px-3 py-3"
        style={{ background: '#0F1E2E' }}
      >
        <div
          className="flex items-center justify-center rounded-full shrink-0 text-white text-xs font-bold"
          style={{ width: 30, height: 30, background: avatarBg }}
        >
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-white truncate">{name}</p>
          <p className="text-xs truncate" style={{ color: '#5BA3C9' }}>{role}</p>
        </div>
        <button
          onClick={() => navigate('/login')}
          className="opacity-60 hover:opacity-100 transition-opacity shrink-0"
          title="Déconnexion"
        >
          <LogOut size={13} color="#fff" />
        </button>
      </div>
    </aside>
  )
}
