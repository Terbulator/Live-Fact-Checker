/**
 * Typed client for the backend's HTTP API.
 *
 * Only the endpoints the frontend actually needs are wrapped. In particular the
 * frontend does **not** post transcripts: that is the `voice/` module's job.
 * The frontend starts a session, watches the WebSocket, and stops the session.
 *
 * Error responses nest their machine-readable code under `detail` (see
 * `backend/routes/events.py` and `backend/routes/session.py`), which this
 * module unwraps into a thrown {@link ApiError}.
 */

import { BACKEND_URL } from './config'
import type { HealthResponse, SessionState } from '../types/events'

/** An HTTP failure carrying the backend's stable error code. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

// Re-export SessionState for consumers
export type { SessionState }

/** Unwrap `{"detail": {"code": ..., "message": ...}}` from an error body. */
function toApiError(status: number, body: unknown): ApiError {
  const detail =
    typeof body === 'object' && body !== null
      ? (body as { detail?: unknown }).detail
      : undefined

  if (typeof detail === 'object' && detail !== null) {
    const { code, message } = detail as { code?: unknown; message?: unknown }
    if (typeof code === 'string' && typeof message === 'string') {
      return new ApiError(status, code, message)
    }
  }
  if (typeof detail === 'string') {
    return new ApiError(status, 'INTERNAL_ERROR', detail)
  }
  return new ApiError(status, 'INTERNAL_ERROR', `Request failed with status ${status}.`)
}

/**
 * A request that never reached the backend.
 *
 * `fetch` rejects with a bare `TypeError: Failed to fetch` when the host is
 * down, the port is closed, or CORS blocks the response. None of that is
 * actionable to someone watching a demo, and the raw string is an
 * implementation detail, so it is translated into a sentence a judge can act
 * on. This code is a frontend UI concept only; it is never sent to the backend
 * and does not extend the backend's `ErrorCode` contract.
 */
function toUnreachableError(): ApiError {
  return new ApiError(
    0,
    'BACKEND_UNAVAILABLE',
    `Cannot reach the backend at ${BACKEND_URL}. Check that it is running, then try again.`,
  )
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (cause) {
    // An aborted request is a user action, not a fault; let it stay silent.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw toUnreachableError()
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      // Non-JSON error body (e.g. a proxy 502 page); fall through to the
      // status-only ApiError built by toApiError.
    }
    throw toApiError(response.status, body)
  }

  return (await response.json()) as T
}

/**
 * Create a session.
 *
 * @param startMockPipeline When true, the backend immediately replays its
 *   scripted transcript -> claim -> verification stream into the new session.
 *   This is how the demo runs with no AssemblyAI, LLM or search credentials.
 */
export function startSession(startMockPipeline = false): Promise<SessionState> {
  return request<SessionState>('/session/start', {
    method: 'POST',
    body: JSON.stringify({ startMockPipeline }),
  })
}

/** Fetch a session snapshot: status, counters and connected client count. */
export function getSession(sessionId: string): Promise<SessionState> {
  return request<SessionState>(`/session/${encodeURIComponent(sessionId)}`)
}

/** Stop a session. The backend also closes its WebSocket clients. */
export function stopSession(sessionId: string): Promise<SessionState> {
  return request<SessionState>(
    `/session/stop?sessionId=${encodeURIComponent(sessionId)}`,
    { method: 'POST' },
  )
}

/** Service health, wired engines and credential *presence* (never values). */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}
