/**
 * Application shell: routes only.
 *
 * All application state lives in the components behind these routes. This file
 * exists to decide which one is on screen:
 *
 *   /           -> the marketing landing page
 *   /dashboard  -> the live fact-checker (the real pipeline UI)
 *   /login      -> account access, which is not implemented
 *   /signup     -> account creation, which is not implemented
 *
 * The router lives here rather than in `main.tsx` so the entry point stays a
 * plain "mount React" and the route table is readable in one place.
 */

import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { LandingPage } from './components/landing'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        {/* Any other path is a stale or mistyped link, not a dead end. */}
        <Route path="*" element={<LandingPage />} />
      </Routes>
    </BrowserRouter>
  )
}
