import { Search, Bell } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

interface Props {
  title: string
  badge?: string
}

export default function TopBar({ title, badge }: Props) {
  const { initials, notifCount } = useAuth()

  return (
    <header
      className="flex items-center gap-3 px-6 h-14 border-b shrink-0"
      style={{ background: '#fff', borderColor: '#D5E8F5' }}
    >
      <h1 className="text-xl font-bold" style={{ color: '#1A1A2E' }}>{title}</h1>

      {badge && (
        <span
          className="text-xs font-medium px-2.5 py-1 rounded-full"
          style={{ background: '#EFF4FA', color: '#1A3A5C' }}
        >
          ● {badge}
        </span>
      )}

      <div className="flex-1" />

      {/* Search */}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: '#9BAFBF' }} />
        <input
          type="text"
          placeholder="Rechercher..."
          className="pl-8 pr-3 py-1.5 text-sm rounded-lg border outline-none w-52 transition-all"
          style={{ borderColor: '#D5E8F5', color: '#1A1A2E', background: '#F8FAFC' }}
          onFocus={e => (e.target.style.borderColor = '#5BA3C9')}
          onBlur={e => (e.target.style.borderColor = '#D5E8F5')}
        />
      </div>

      {/* Bell */}
      <button className="relative p-1.5 rounded-lg hover:bg-gray-50 transition-colors">
        <Bell size={18} style={{ color: '#5D6D7E' }} />
        {notifCount > 0 && (
          <span
            className="absolute -top-1 -right-1 w-4 h-4 rounded-full text-white flex items-center justify-center font-bold"
            style={{ background: '#C0391B', fontSize: 10 }}
          >
            {notifCount}
          </span>
        )}
      </button>

      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full text-white text-xs font-bold shrink-0"
        style={{ width: 32, height: 32, background: '#1A3A5C' }}
      >
        {initials}
      </div>
    </header>
  )
}
