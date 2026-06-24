import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import InvoicePipeline from './pages/InvoicePipeline'
import ReviewQueue from './pages/ReviewQueue'
import InvoiceDetail from './pages/InvoiceDetail'
import Journaux from './pages/Journaux'
import GrandLivre from './pages/GrandLivre'
import Facturation from './pages/Facturation'
import Budget from './pages/Budget'
import CAPEX from './pages/CAPEX'
import KPIDashboard from './pages/KPIDashboard'
import Direction from './pages/Direction'
import Requetes from './pages/Requetes'
import Suivi from './pages/Suivi'
import Projets from './pages/Projets'
import ProjetDetail from './pages/ProjetDetail'
import { useAuth, ROLE_PATHS, roleHome } from './context/AuthContext'

function HomeRedirect() {
  const { role } = useAuth()
  return <Navigate to={roleHome(role)} replace />
}

function RoleGuard() {
  const { role } = useAuth()
  const location = useLocation()
  const base = '/' + location.pathname.split('/')[1]
  const allowed = ROLE_PATHS[role] ?? []
  if (base !== '/' && !allowed.includes(base)) {
    return <Navigate to={roleHome(role)} replace />
  }
  return <Outlet />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Layout />}>
          <Route element={<RoleGuard />}>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="/upload"      element={<InvoicePipeline />} />
            <Route path="/review"      element={<ReviewQueue />} />
            <Route path="/invoices"    element={<InvoiceDetail />} />
            <Route path="/suivi"       element={<Suivi />} />
            <Route path="/journal"     element={<Journaux />} />
            <Route path="/grand-livre" element={<GrandLivre />} />
            <Route path="/billing"     element={<Facturation />} />
            <Route path="/budget"      element={<Budget />} />
            <Route path="/capex"       element={<CAPEX />} />
            <Route path="/direction"   element={<Direction />} />
            <Route path="/kpi"         element={<KPIDashboard />} />
            <Route path="/requetes"    element={<Requetes />} />
            <Route path="/projects"    element={<Projets />} />
            <Route path="/projects/:id" element={<ProjetDetail />} />
          </Route>
        </Route>
        <Route path="*" element={<HomeRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
