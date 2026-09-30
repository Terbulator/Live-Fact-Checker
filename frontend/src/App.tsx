/**
 * Application entry.
 *
 * Routing only:
 *   /            marketing landing page
 *   /dashboard   the live fact-checking application
 *   /login       account sign-in
 *   /signup      account creation
 *
 * There is no authentication backend in this repository, so /login and /signup
 * are presentation only and say so. /dashboard is intentionally open for the
 * same reason: gating it behind a check that cannot pass would make the working
 * application unreachable.
 */

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { LandingPage } from './components/landing'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/dashboard/*" element={<DashboardPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
