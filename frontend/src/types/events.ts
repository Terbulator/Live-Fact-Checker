/**
 * Wire contracts for the Live Fact-Checker backend.
 *
 * These mirror `backend/schemas.py` exactly. The backend is the source of
 * truth; this file is a hand-maintained mirror and must not drift from it.
 *
 * Two contract details that drive the whole UI:
 *
 * 1. **Verdicts are uppercase on the wire.** `TRUE` / `FALSE` /
 *    `UNVERIFIABLE`. The lowercase `True` / `False` / `Unverifiable` values in
 *    `verification/models.py` are internal to the backend and are translated
 *    at `backend/adapters/verification.py`. The frontend only ever sees the
 *    uppercase forms.
 *
 * 2. **A `claim` event always precedes its `verification`.** The backend
 *    broadcasts the claim first (as a pending card) and the verdict once
 *    verification finishes, so claims are correlated on `claimId`.
 */

/** Verdict values allowed by `backend.schemas.Verdict`. */
export const VERDICTS = ['TRUE', 'FALSE', 'UNVERIFIABLE'] as const
export type Verdict = (typeof VERDICTS)[number]

/** Status values carried by a `session` event (`SessionEventStatus`). */
export const SESSION_EVENT_STATUSES = [
  'started',
  'connected',
  'stopped',
  'error',
] as const
export type SessionEventStatus = (typeof SESSION_EVENT_STATUSES)[number]

/**
 * Stable machine-readable error codes (`backend.schemas.ErrorCode`).
 *
 * The backend can also surface `INTERNAL_ERROR` for a WebSocket protocol
 * fault the browser raises itself, which has no backend counterpart.
 */
export const ERROR_CODES = [
  'SESSION_NOT_FOUND',
  'SESSION_STOPPED',
  'SESSION_ALREADY_STOPPED',
  'SCHEMA_VALIDATION_FAILED',
  'UNSUPPORTED_EVENT_TYPE',
  'MALFORMED_EVENT',
  'VERIFICATION_FAILED',
  'CLAIM_EXTRACTION_FAILED',
  'BROADCAST_FAILED',
  'INTERNAL_ERROR',
] as const
export type ErrorCode = (typeof ERROR_CODES)[number] | (string & {})

/** One speech-to-text segment. Interim segments have `isFinal: false`. */
export interface TranscriptEvent {
  type: 'transcript'
  eventId: string
  sessionId: string
  speaker: string | null
  text: string
  timestamp: number
  isFinal: boolean
}

/** A checkable claim extracted from a finalized transcript segment. */
export interface ClaimEvent {
  type: 'claim'
  eventId: string
  claimId: string
  sessionId: string
  speaker: string | null
  timestamp: number
  claim: string
  claimType: string
}

/**
 * One citable evidence source.
 *
 * Additive extension of `VerificationEvent`. The `source` string remains the
 * contract every consumer already depends on; this carries the supporting
 * citations beside it, ranked best-first by the backend.
 */
export interface EvidenceSource {
  url: string
  title: string | null
  snippet: string | null
}

/** Verdict, rationale and citation for a single claim. */
export interface VerificationEvent {
  type: 'verification'
  eventId: string
  claimId: string
  sessionId: string
  speaker: string | null
  timestamp: number
  verdict: Verdict
  reason: string
  /** Primary citation. Always present; unchanged by multi-source support. */
  source: string
  /**
   * Additional credible evidence, best first.
   *
   * Optional because an older backend, or a claim with no citable evidence,
   * sends no such field. The UI must treat its absence as "one source".
   */
  sources?: EvidenceSource[]
}

/** A structured failure the frontend is expected to surface, not crash on. */
export interface ErrorEvent {
  type: 'error'
  eventId: string
  sessionId: string | null
  code: ErrorCode
  message: string
  recoverable: boolean
  claimId?: string | null
  detail?: string | null
}

/** Session lifecycle notification. */
export interface SessionEvent {
  type: 'session'
  eventId: string
  sessionId: string
  status: SessionEventStatus
  detail?: string | null
}

/** Reply to a client `{"type":"ping"}`. */
export interface PongEvent {
  type: 'pong'
  sessionId: string
}

/** Every message the backend can push down the WebSocket. */
export type ServerEvent =
  | TranscriptEvent
  | ClaimEvent
  | VerificationEvent
  | ErrorEvent
  | SessionEvent
  | PongEvent

/** Every message the frontend may send. Only liveness is supported today. */
export type ClientEvent = { type: 'ping' }

/** Lifecycle of a session as reported by `GET /session/{session_id}`. */
export type SessionStatus = 'started' | 'connected' | 'stopped'

/** Snapshot returned by the session routes. */
export interface SessionState {
  sessionId: string
  status: SessionStatus
  createdAt: string
  updatedAt: string
  connectedClients: number
  transcriptCount: number
  claimCount: number
  verificationCount: number
  errorCount: number
  wsUrl: string | null
  /** Present on `POST /session/start` only. */
  type?: 'session'
}

/** Per-event-type tallies returned by the ingest routes. */
export interface PipelineCounts {
  claims: number
  verifications: number
  errors: number
}

/** `GET /health` response. Reports credential *presence*, never values. */
export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
  sessions: number
  websocketClients: number
  engines: Record<string, string>
  credentialsConfigured: Record<string, boolean>
  timestamp: string
}

/**
 * Type guard for the `type` discriminator on an untrusted WebSocket frame.
 *
 * The socket carries text, so every inbound message is unvalidated input
 * until this check passes.
 */
export function isServerEvent(value: unknown): value is ServerEvent {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { type?: unknown }).type === 'string'
  )
}
