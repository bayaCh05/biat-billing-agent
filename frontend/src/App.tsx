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
import ProjetDetailIT from './pages/ProjetDetailIT'
import Profile from './pages/Profile'
import ChangerMotDePassePage from './pages/ChangerMotDePassePage'
import RoadmapPage from './pages/RoadmapPage'
import RisksPage from './pages/RisksPage'
import AIActivityPage from './pages/AIActivityPage'
import SecurityPage from './pages/SecurityPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import InscriptionPage from './pages/admin/InscriptionPage'
import HabilitationsPage from './pages/admin/HabilitationsPage'
import AuditPage from './pages/AuditPage'
import EcheancierPage from './pages/EcheancierPage'
import NotificationsPage from './pages/NotificationsPage'
import { useAuth, roleHome } from './context/AuthContext'
import { ROLE_PATHS } from './config/roles'

function HomeRedirect() {
  const { role } = useAuth()
  return <Navigate to={roleHome(role)} replace />
}

function AuthGuard() {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  if (!isAuthenticated) return <Navigate to="/login" state={{ from: location }} replace />
  return <Outlet />
}

function PasswordChangeGuard() {
  const { forcePasswordChange } = useAuth()
  const location = useLocation()
  if (forcePasswordChange && location.pathname !== '/changer-mot-de-passe') {
    return <Navigate to="/changer-mot-de-passe" replace />
  }
  return <Outlet />
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
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/changer-mot-de-passe" element={<ChangerMotDePassePage />} />
        <Route element={<Layout />}>
          <Route element={<AuthGuard />}>
            <Route element={<PasswordChangeGuard />}>
              {/* Profile accessible to all roles */}
              <Route path="/profile" element={<Profile />} />
              <Route element={<RoleGuard />}>
                <Route path="/" element={<HomeRedirect />} />
                <Route path="/upload"         element={<InvoicePipeline />} />
                <Route path="/review"         element={<ReviewQueue />} />
                <Route path="/invoices"       element={<InvoiceDetail />} />
                <Route path="/suivi"          element={<Suivi />} />
                <Route path="/echeancier"    element={<EcheancierPage />} />
                <Route path="/journal"        element={<Journaux />} />
                <Route path="/grand-livre"    element={<GrandLivre />} />
                <Route path="/billing"        element={<Facturation />} />
                <Route path="/budget"         element={<Budget />} />
                <Route path="/capex"          element={<CAPEX />} />
                <Route path="/direction"      element={<Direction />} />
                <Route path="/kpi"            element={<KPIDashboard />} />
                <Route path="/requetes"       element={<Requetes />} />
                <Route path="/projects"       element={<Projets />} />
                <Route path="/projects/:id"   element={<ProjetDetail />} />
                <Route path="/projets-it/:id" element={<ProjetDetailIT />} />
                <Route path="/roadmap"        element={<RoadmapPage />} />
                <Route path="/risques"        element={<RisksPage />} />
                <Route path="/ai-activity"    element={<AIActivityPage />} />
                <Route path="/security"       element={<SecurityPage />} />
                <Route path="/audit"            element={<AuditPage />} />
                <Route path="/notifications"    element={<NotificationsPage />} />
                <Route path="/admin/inscription"   element={<InscriptionPage />} />
                <Route path="/admin/habilitations" element={<HabilitationsPage />} />
              </Route>
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<HomeRedirect />} />
      </Routes>
    </BrowserRouter>
  )
}
