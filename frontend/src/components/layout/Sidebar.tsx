import { NavLink, useNavigate } from 'react-router-dom'
import {
  Home, ClipboardList, Files,
  Activity, BookOpen, BookMarked, CreditCard, BarChart2,
  Building2, TrendingUp, Gauge, MessageSquare, FolderKanban,
  LogOut, Map, ShieldCheck, Users, Landmark, History,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { ROLE_PATHS } from '../../config/roles'

const ALL_NAV = [
  // Admin
  { path: '/admin/inscription',   icon: Users,         label: 'Inscription',    roles: ['Admin'] },
  { path: '/admin/habilitations', icon: ShieldCheck,   label: 'Habilitations',  roles: ['Admin'] },
  // Shared
  { path: '/upload',      icon: Home,            label: 'Accueil',        roles: ['Comptable', 'Chef de Projet'] },
  { path: '/kpi',         icon: Gauge,           label: 'KPI Dashboard',  roles: ['Comptable', 'Chef de Projet', 'Direction', 'Admin'] },
  { path: '/review',      icon: ClipboardList,   label: 'File de révision', roles: ['Comptable'] },
  { path: '/invoices',    icon: Files,           label: 'Factures',       roles: ['Comptable', 'Chef de Projet'] },
  { path: '/suivi',       icon: Activity,        label: 'Suivi',          roles: ['Comptable', 'Chef de Projet'] },
  { path: '/journal',     icon: BookOpen,        label: 'Journal',        roles: ['Comptable'] },
  { path: '/grand-livre', icon: BookMarked,      label: 'Grand Livre',    roles: ['Comptable'] },
  { path: '/billing',     icon: CreditCard,      label: 'Facturation',    roles: ['Comptable', 'Chef de Projet'] },
  { path: '/projects',    icon: FolderKanban,    label: 'Projets',        roles: ['Comptable', 'Chef de Projet'] },
  { path: '/budget',      icon: BarChart2,       label: 'Budget',         roles: ['Comptable', 'Chef de Projet', 'Direction'] },
  { path: '/capex',       icon: Building2,       label: 'Immobilisations', roles: ['Comptable', 'Direction'] },
  { path: '/direction',   icon: TrendingUp,      label: 'Direction',      roles: ['Direction'] },
  { path: '/roadmap',     icon: Map,             label: 'Feuille de Route', roles: ['Comptable', 'Chef de Projet', 'Direction'] },
  { path: '/requetes',    icon: MessageSquare,   label: 'Requêtes',       roles: ['Comptable', 'Direction'] },
  { path: '/bct-export',  icon: Landmark,        label: 'Conformité BCT', roles: ['Comptable', 'Direction'] },
  { path: '/audit',          icon: History,  label: 'Piste d\'Audit',  roles: ['Admin', 'Direction'] },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const { name, initials, role, logout } = useAuth()

  const visibleNav = ALL_NAV.filter(item => {
    const allowed = ROLE_PATHS[role]
    if (!allowed) return false
    // Check both explicit role list and ROLE_PATHS
    const baseAllowed = item.roles.includes(role)
    const pathAllowed = allowed.some(p => item.path === p || item.path.startsWith(p + '/'))
    return baseAllowed && pathAllowed
  })

  const avatarBg = role === 'Direction' ? '#804CD7' : role === 'Chef de Projet' ? '#F0A600' : role === 'Admin' ? '#C0391B' : '#1A3A5C'

  return (
    <aside
      className="flex flex-col h-screen shrink-0"
      style={{ width: 164, background: '#14293F' }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-center px-3"
        style={{ background: '#fff', borderBottom: '1px solid #D5E8F5', height: 44 }}
      >
        <img
          src="/biat-logo.jpeg"
          alt="BIAT Innovation & Technology"
          style={{ height: 30, width: 'auto' }}
        />
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {visibleNav.map(({ path, icon: Icon, label }) => (
          <NavLink
            key={path}
            to={path}
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
        <NavLink
          to="/profile"
          title="Mon profil"
          className="shrink-0 flex items-center justify-center rounded-full text-white text-xs font-bold hover:opacity-80 hover:ring-2 hover:ring-white/30 transition-all"
          style={{ width: 30, height: 30, background: avatarBg }}
        >
          {initials}
        </NavLink>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-white truncate">{name}</p>
          <p className="text-xs truncate" style={{ color: '#5BA3C9' }}>{role}</p>
        </div>
        <button
          onClick={() => { logout(); navigate('/login') }}
          className="opacity-60 hover:opacity-100 transition-opacity shrink-0"
          title="Déconnexion"
        >
          <LogOut size={13} color="#fff" />
        </button>
      </div>
    </aside>
  )
}
