/**
 * Application shell: routes and the one auth provider.
 *
 * All application state lives in the components behind these routes. This file
 * exists to decide which one is on screen:
 *
 *   /           -> the marketing landing page
 *   /dashboard  -> the live fact-checker (the real pipeline UI)
 *   /login      -> account access, through Supabase Auth
 *   /signup     -> account creation, through Supabase Auth
 *
 * The router lives here rather than in `main.tsx` so the entry point stays a
 * plain "mount React" and the route table is readable in one place.
 *
 * `AuthProvider` wraps the router because the redirect-away-from-login depends
 * on session state, which the auth pages read. One provider means one Supabase
 * session subscription for the whole app: two would race each other over the
 * same stored token, and a stale one wins.
 *
 * There is no guard on `/dashboard`. The fact-checker is open, and making it
 * require an account would be a product decision rather than an auth one.
 */

import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { LandingPage } from './components/landing'
import { AuthProvider } from './hooks/useAuth'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'

export default function App() {
  return (
    <AuthProvider>
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
    </AuthProvider>
  )
}
