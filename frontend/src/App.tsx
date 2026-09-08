import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Login from './pages/auth/Login'
import InvoicePipeline from './pages/factures/InvoicePipeline'
import ReviewQueue from './pages/factures/ReviewQueue'
import InvoiceDetail from './pages/factures/InvoiceDetail'
import Journaux from './pages/comptabilite/Journaux'
import GrandLivre from './pages/comptabilite/GrandLivre'
import Facturation from './pages/comptabilite/Facturation'
import Budget from './pages/pilotage/Budget'
import CAPEX from './pages/pilotage/Capex'
import KPIDashboard from './pages/pilotage/KPIDashboard'
import Direction from './pages/pilotage/Direction'
import Requetes from './pages/transversal/Requetes'
import Suivi from './pages/comptabilite/Suivi'
import Projets from './pages/projets/Projets'
import FacturationClientDetail from './pages/projets/FacturationClientDetail'
import ProjetDetail from './pages/projets/ProjetDetail'
import Profile from './pages/auth/Profile'
import ChangerMotDePasse from './pages/auth/ChangerMotDePasse'
import Roadmap from './pages/transversal/Roadmap'
import Risques from './pages/transversal/Risques'
import AIActivity from './pages/transversal/AIActivity'
import Security from './pages/transversal/Security'
import ForgotPassword from './pages/auth/ForgotPassword'
import ResetPassword from './pages/auth/ResetPassword'
import InscriptionPage from './pages/admin/InscriptionPage'
import HabilitationsPage from './pages/admin/HabilitationsPage'
import Audit from './pages/transversal/Audit'
import AuditReports from './pages/transversal/AuditReports'
import Echeancier from './pages/comptabilite/Echeancier'
import PageSpinner from './components/ui/PageSpinner'
import { useAuth } from './context/AuthContext'
import { roleHome } from './config/navigation'
import { ROLE_PATHS } from './config/roles'

function HomeRedirect() {
  const { role } = useAuth()
  return <Navigate to={roleHome(role)} replace />
}

function AuthGuard() {
  const { isAuthenticated, isBootstrapping } = useAuth()
  const location = useLocation()
  // Wait for the session-restore attempt (refresh cookie) before deciding to
  // redirect — otherwise a hard reload always bounces to /login, since
  // isAuthenticated starts false until that async call resolves.
  if (isBootstrapping) return <PageSpinner loading error={false} />
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
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/changer-mot-de-passe" element={<ChangerMotDePasse />} />
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
                <Route path="/echeancier"    element={<Echeancier />} />
                <Route path="/journal"        element={<Journaux />} />
                <Route path="/grand-livre"    element={<GrandLivre />} />
                <Route path="/billing"        element={<Facturation />} />
                <Route path="/budget"         element={<Budget />} />
                <Route path="/capex"          element={<CAPEX />} />
                <Route path="/direction"      element={<Direction />} />
                <Route path="/kpi"            element={<KPIDashboard />} />
                <Route path="/requetes"       element={<Requetes />} />
                <Route path="/projects"       element={<Projets />} />
                <Route path="/projects/:id"   element={<FacturationClientDetail />} />
                <Route path="/projets-it/:id" element={<ProjetDetail />} />
                <Route path="/roadmap"        element={<Roadmap />} />
                <Route path="/risques"        element={<Risques />} />
                <Route path="/ai-activity"    element={<AIActivity />} />
                <Route path="/security"       element={<Security />} />
                <Route path="/audit"            element={<Audit />} />
                <Route path="/audit-reports"    element={<AuditReports />} />
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
