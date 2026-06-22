import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import ApiToast from '../ui/ApiToast'

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto" style={{ background: '#F0F4F9' }}>
        <Outlet />
      </main>
      <ApiToast />
    </div>
  )
}
