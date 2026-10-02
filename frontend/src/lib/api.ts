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
import type {
  ClaimEvent,
  EvidenceSource,
  HealthResponse,
  PipelineCounts,
  SessionState,
  VerificationEvent,
  Verdict,
} from '../types/events'

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

/**
 * Outcome of checking one claim.
 *
 * Not a verdict. `verified` means a verdict was reached (and `UNVERIFIABLE` is
 * one of them); `failed` means the check itself did not complete, so there is no
 * verdict at all. The two are kept apart on purpose -- folding a retrieval
 * failure into `UNVERIFIABLE` would turn a broken integration into a statistic
 * about the video.
 */
export type ClaimCheckStatus = 'verified' | 'failed'

/** One claim from an ingested video, with its verdict and the evidence behind it. */
export interface VideoClaimResult {
  claim_id: string
  claim: string
  speaker: string | null
  /** Offset into the source video in seconds, so the moment can be located. */
  timestamp: number
  status: ClaimCheckStatus
  verdict: Verdict | null
  reason: string | null
  /** Evidence-grounded explanation; null when nothing citable was retrieved. */
  supporting_statement: string | null
  source: string | null
  sources: EvidenceSource[]
  /** Provider relevance score, or null when the provider reported none. */
  confidence: number | null
  from_cache: boolean
  /** Set only when `status` is `failed`, explaining the absent verdict. */
  error: string | null
}

/**
 * The deterministic summary of one video run.
 *
 * Every `*_ratio` is `null` when its denominator is zero. `null` means "not
 * measured" and must be rendered as such; substituting 0% would assert that
 * nothing was true, which is a finding this system did not produce.
 */
export interface VideoScorecard {
  total_claims: number
  checked_claims: number
  failed_claims: number
  true_claims: number
  false_claims: number
  ambiguous_claims: number
  unverifiable_claims: number
  true_ratio: number | null
  false_ratio: number | null
  ambiguous_ratio: number | null
  unverifiable_ratio: number | null
  coverage_ratio: number | null
}

/** Response from ingestion endpoints. */
export interface IngestionResponse {
  source_id: string
  status: string
  message: string
  transcript?: string
  transcript_segments?: Array<{
    speaker: string
    text: string
    start: number
    end: number
    confidence?: number
  }>
  claims_extracted: number
  verifications_completed: number
  /** Per-claim results, with evidence. Absent on an older backend. */
  claims?: VideoClaimResult[]
  /** Summary derived from `claims`. Absent on an older backend. */
  scorecard?: VideoScorecard | null
  duration_seconds?: number | null
}

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

async function requestFormData<T>(path: string, formData: FormData): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}${path}`, {
      method: 'POST',
      body: formData,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw toUnreachableError()
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
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

/** Upload an audio file for transcription and fact-checking. */
export function ingestAudio(
  sessionId: string,
  file: File
): Promise<IngestionResponse> {
  const formData = new FormData()
  formData.append('session_id', sessionId)
  formData.append('file', file)
  return requestFormData<IngestionResponse>('/ingestion/audio', formData)
}

/** Upload a video file for audio extraction, transcription and fact-checking. */
export function ingestVideo(
  sessionId: string,
  file: File
): Promise<IngestionResponse> {
  const formData = new FormData()
  formData.append('session_id', sessionId)
  formData.append('file', file)
  return requestFormData<IngestionResponse>('/ingestion/video', formData)
}

/** Process a video URL for transcription and fact-checking. */
export function ingestVideoUrl(
  sessionId: string,
  url: string
): Promise<IngestionResponse> {
  return request<IngestionResponse>('/ingestion/video-url', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, url }),
  })
}

/** Service health, wired engines and credential *presence* (never values). */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health')
}

/** What the caller supplies when posting a claim that was typed, not spoken. */
export interface ClaimSubmission {
  claimId: string
  sessionId: string
  claim: string
  /** Offset into the session, in seconds, used to place the claim in time. */
  timestamp: number
  /** Label shown as the speaker of the claim. Null when there is no speaker. */
  speaker?: string | null
}

/** Result of `POST /events/claim`. */
export interface ClaimAcceptedResponse {
  accepted: boolean
  sessionId: string
  claim: ClaimEvent
  counts: PipelineCounts
  verifications: VerificationEvent[]
  idempotent: boolean
}

/**
 * Post a claim that did not come from speech, and have it verified.
 *
 * This is the composer path for a typed claim: it uses the backend's existing
 * `POST /events/claim` ingress, which broadcasts the claim and runs the same
 * verification pipeline a spoken claim goes through. Nothing here re-implements
 * extraction or verification -- the only frontend responsibility is minting a
 * claim id, because the backend rejects a repeat within a session.
 */
export function submitClaim(submission: ClaimSubmission): Promise<ClaimAcceptedResponse> {
  return request<ClaimAcceptedResponse>('/events/claim', {
    method: 'POST',
    body: JSON.stringify({
      type: 'claim',
      claimId: submission.claimId,
      sessionId: submission.sessionId,
      speaker: submission.speaker ?? 'Speaker 1',
      timestamp: submission.timestamp,
      claim: submission.claim,
      claimType: 'unspecified',
    }),
  })
}
