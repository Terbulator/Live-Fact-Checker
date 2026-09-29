import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Vite configuration for the Live Fact-Checker frontend.
 *
 * Deliberate constraints (frontend owner: Rupan):
 *
 * - **No dev proxy.** The browser talks to the backend directly. The backend
 *   already whitelists the Vite dev origin in `CORS_ORIGINS`
 *   (`backend/config.py` and `.env.example`), so a proxy would be redundant
 *   infrastructure and would hide CORS mistakes until deployment.
 * - **Port 5173 is pinned with `strictPort`.** If 5173 is taken, Vite would
 *   silently fall back to 5174, which is *not* in the backend's CORS allowlist
 *   and would fail with confusing network errors. Failing loudly is better.
 * - The backend host is read from `VITE_BACKEND_URL` so no URL is hardcoded
 *   into the bundle. It defaults to the backend's documented dev address.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  preview: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
