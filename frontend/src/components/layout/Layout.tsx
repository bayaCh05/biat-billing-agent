import { Outlet } from 'react-router-dom'
import { NavLink } from 'react-router-dom'
import { Bell } from 'lucide-react'
import Sidebar from './Sidebar'
import ApiToast from '../ui/ApiToast'
import { useAuth } from '../../context/AuthContext'

const ROLE_COLOR: Record<string, string> = {
  'Direction':      '#804CD7',
  'Chef de Projet': '#F0A600',
  'Comptable':      '#1A3A5C',
}

export default function Layout() {
  const { initials, role, notifCount } = useAuth()
  const avatarBg = ROLE_COLOR[role] ?? '#1A3A5C'

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ background: '#F0F4F9' }}>
        {/* Global top bar */}
        <header
          className="shrink-0 flex items-center justify-end px-5 gap-3"
          style={{ height: 44, background: '#F0F4F9', borderBottom: '1px solid #E2EBF3' }}
        >
          <NavLink to="/notifications" className="relative text-gray-400 hover:text-gray-600 transition-colors" title="Notifications">
            <Bell size={16} />
            {notifCount > 0 && (
              <span
                className="absolute -top-1.5 -right-1.5 flex items-center justify-center rounded-full bg-red-500 text-white font-bold"
                style={{ width: 15, height: 15, fontSize: 9 }}
              >
                {notifCount > 9 ? '9+' : notifCount}
              </span>
            )}
          </NavLink>
          <NavLink
            to="/profile"
            className="flex items-center justify-center rounded-full text-white text-xs font-bold transition-all hover:opacity-80 hover:ring-2 hover:ring-offset-1"
            style={{ width: 30, height: 30, background: avatarBg, '--tw-ring-color': avatarBg } as React.CSSProperties}
            title="Mon profil"
          >
            {initials}
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
