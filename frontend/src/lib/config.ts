/**
 * Backend connection settings.
 *
 * The frontend never proxies through Vite: the browser talks to the backend
 * directly, which is why the backend's `CORS_ORIGINS` already whitelists the
 * Vite dev origin (`http://localhost:5173` and `http://127.0.0.1:5173`).
 */

/** Backend HTTP base URL. Override with `VITE_BACKEND_URL`. */
export const BACKEND_URL: string = (
  import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000'
).replace(/\/+$/, '')

/** WebSocket path template, matching `backend.schemas.WS_PATH_TEMPLATE`. */
export const WS_PATH_TEMPLATE = '/ws/session/{session_id}'

/**
 * Build the WebSocket URL for a session.
 *
 * The backend already returns a ready-to-use `wsUrl` on the start response, so
 * prefer that. This fallback exists for the case where `wsUrl` is null or
 * malformed, and converts the HTTP origin to a WS origin correctly (including
 * the `https -> wss` case for a deployed backend).
 */
export function buildWsUrl(sessionId: string, baseUrl: string = BACKEND_URL): string {
  const url = new URL(baseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = WS_PATH_TEMPLATE.replace('{session_id}', encodeURIComponent(sessionId))
  url.search = ''
  url.hash = ''
  return url.toString()
}

/**
 * Choose the WebSocket URL to connect to.
 *
 * The backend's own `wsUrl` wins because it is derived from the URL it was
 * actually reached at, which matters behind a reverse proxy or tunnel. The
 * derived URL is the fallback.
 */
export function resolveWsUrl(sessionId: string, backendWsUrl?: string | null): string {
  if (backendWsUrl && /^wss?:\/\//i.test(backendWsUrl)) {
    return backendWsUrl
  }
  return buildWsUrl(sessionId)
}
