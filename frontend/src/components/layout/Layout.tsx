import { Outlet } from 'react-router-dom'
import { NavLink } from 'react-router-dom'
import Sidebar from './Sidebar'
import NotificationBell from './NotificationBell'
import ApiToast from '../ui/ApiToast'
import { useAuth } from '../../context/AuthContext'

const ROLE_COLOR: Record<string, string> = {
  'Direction':      '#804CD7',
  'Chef de Projet': '#F0A600',
  'Comptable':      '#1A3A5C',
}

export default function Layout() {
  const { initials, role, avatar } = useAuth()
  const avatarBg = ROLE_COLOR[role] ?? '#1A3A5C'

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ background: '#F0F4F9' }}>
        {/* Barre globale */}
        <header
          className="shrink-0 flex items-center justify-end px-5 gap-3"
          style={{ height: 44, background: '#F0F4F9', borderBottom: '1px solid #E2EBF3', zIndex: 40, position: 'relative' }}
        >
          <NotificationBell />

          <NavLink
            to="/profile"
            className="shrink-0 rounded-full transition-all hover:opacity-80 hover:ring-2 hover:ring-offset-1 overflow-hidden"
            style={{ width: 30, height: 30, '--tw-ring-color': avatarBg } as React.CSSProperties}
            title="Mon profil"
          >
            {avatar ? (
              <img src={avatar} alt="Profil" className="w-full h-full object-cover rounded-full" />
            ) : (
              <span
                className="flex items-center justify-center w-full h-full rounded-full text-white text-xs font-bold"
                style={{ background: avatarBg }}
              >
                {initials}
              </span>
            )}
          </NavLink>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <ApiToast />
    </div>
  )
}
