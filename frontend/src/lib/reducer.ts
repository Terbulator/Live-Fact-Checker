/**
 * Pure reduction of backend events into the view model the UI renders.
 *
 * Kept free of React so the ordering rules are testable on their own. The rules
 * encoded here mirror guarantees the backend actually provides:
 *
 * - Interim transcript segments (`isFinal: false`) are broadcast for live
 *   rendering and then superseded by the finalized line for that turn. Only
 *   the final line is claim-checked (`backend/router.py`).
 * - A `claim` event is always broadcast **before** its `verification`, so a
 *   claim card can render in a pending state and be filled in later. Claims
 *   correlate on `claimId`.
 * - `sessionId` and `claimId` are preserved end to end; the backend owns them.
 */

import type { ClaimCard, LiveView, TranscriptLine } from '../types/model'
import { initialLiveView } from '../types/model'
import type {
  ClaimEvent,
  ErrorEvent,
  ServerEvent,
  TranscriptEvent,
  VerificationEvent,
} from '../types/events'

/**
 * Bound the error list so a long demo cannot grow memory without limit.
 *
 * Errors are the newest-first thing a user needs to see, so the oldest are
 * dropped once the cap is reached.
 */
export const MAX_ERRORS = 50

/** Identity for a live transcript line. Interim lines are superseded in place. */
function transcriptKey(event: TranscriptEvent): string {
  return `${event.speaker ?? 'unknown'}@${event.timestamp.toFixed(2)}`
}

function toLine(event: TranscriptEvent, claimId: string | null): TranscriptLine {
  return {
    key: transcriptKey(event),
    speaker: event.speaker,
    text: event.text,
    timestamp: event.timestamp,
    isFinal: event.isFinal,
    claimId,
  }
}

/**
 * True when `last` is the still-unrevised version of the utterance that the
 * incoming segment supersedes.
 *
 * AssemblyAI streams one turn per speaker as a growing sequence of interim
 * segments, each of which should replace the previous one rather than stack.
 */
function supersedesInterim(last: TranscriptLine | undefined, incoming: TranscriptLine): boolean {
  return (
    last !== undefined && !last.isFinal && last.speaker === incoming.speaker
  )
}

/**
 * Find the transcript key a claim was extracted from.
 *
 * Uses the same rule as `attachClaimId`: the newest finalized line from the
 * same speaker. Kept as a separate function so the lookup used for linking is
 * literally the one used for annotating, rather than a second guess.
 */
function findLineKey(
  lines: TranscriptLine[],
  event: ClaimEvent,
): string | null {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]
    if (line === undefined) continue
    if (!line.isFinal || line.speaker !== event.speaker) continue
    return line.key
  }
  return null
}

/**
 * Attach a `claimId` to the most recent finalized line from the same speaker.
 *
 * The backend broadcasts the transcript, then the claim it produced, so the
 * newest finalized line for that speaker is the one under check. Matching on
 * speaker rather than an exact timestamp keeps this working when an upstream
 * claim engine rounds the timestamp.
 */
function attachClaimId(lines: TranscriptLine[], event: ClaimEvent): TranscriptLine[] {
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const line = lines[index]
    if (line === undefined) continue
    if (!line.isFinal || line.speaker !== event.speaker) continue
    if (line.claimId !== null) continue

    return [
      ...lines.slice(0, index),
      { ...line, claimId: event.claimId },
      ...lines.slice(index + 1),
    ]
  }
  return lines
}

/**
 * Attach a verification to its claim card.
 *
 * A verification for an unseen `claimId` still produces a card, so evidence
 * produced by another producer is never silently dropped.
 */
function upsertClaim(claims: ClaimCard[], verification: VerificationEvent): ClaimCard[] {
  const index = claims.findIndex((card) => card.claimId === verification.claimId)
  const existing = index >= 0 ? claims[index] : undefined

  if (existing === undefined) {
    return [
      ...claims,
      {
        claimId: verification.claimId,
        speaker: verification.speaker,
        timestamp: verification.timestamp,
        claim: '',
        claimType: 'unspecified',
        pending: false,
        verification,
        transcriptKey: null,
      },
    ]
  }

  return [
    ...claims.slice(0, index),
    { ...existing, pending: false, verification },
    ...claims.slice(index + 1),
  ]
}

/** Fold one server event into the next view model. */
export function applyEvent(view: LiveView, event: ServerEvent): LiveView {
  switch (event.type) {
    case 'transcript': {
      const incoming = toLine(event, null)
      const last = view.transcripts[view.transcripts.length - 1]
      // Any transcript segment, interim or final, means someone is speaking.
      const speech = { lastSpeechAt: Date.now(), lastSpeaker: event.speaker }

      if (supersedesInterim(last, incoming)) {
        return {
          ...view,
          ...speech,
          transcripts: [...view.transcripts.slice(0, -1), incoming],
        }
      }
      return {
        ...view,
        ...speech,
        transcripts: [...view.transcripts, incoming],
      }
    }

    case 'claim': {
      const card: ClaimCard = {
        claimId: event.claimId,
        speaker: event.speaker,
        timestamp: event.timestamp,
        claim: event.claim,
        claimType: event.claimType,
        pending: true,
        verification: null,
        // Captured now, while we know which line produced this claim.
        transcriptKey: findLineKey(view.transcripts, event),
      }
      return {
        ...view,
        claims: [...view.claims, card],
        transcripts: attachClaimId(view.transcripts, event),
      }
    }

    case 'verification':
      return { ...view, claims: upsertClaim(view.claims, event) }

    case 'error': {
      const errorEvent: ErrorEvent = event
      return {
        ...view,
        errors: [...view.errors, errorEvent].slice(-MAX_ERRORS),
      }
    }

    case 'session':
      return { ...view, status: event.status }

    case 'pong':
      return view

    default:
      return view
  }
}

/** Actions the view state accepts, beyond raw server events. */
export type LiveViewAction =
  | { type: 'event'; event: ServerEvent }
  | { type: 'clearErrors' }
  | { type: 'reset' }

/**
 * The reducer used with `useReducer`.
 *
 * Local UI actions are expressed here rather than through sentinel events, so
 * that resetting state does not depend on faking a backend payload.
 */
export function liveViewReducer(view: LiveView, action: LiveViewAction): LiveView {
  switch (action.type) {
    case 'event':
      return applyEvent(view, action.event)
    case 'clearErrors':
      return { ...view, errors: [] }
    case 'reset':
      // Starting a new session must not inherit the previous one's transcript,
      // claims or verdicts. Claim ids are minted by the backend and restart per
      // process, so two sessions can legitimately reuse the same id; carrying
      // cards across would merge unrelated results.
      return initialLiveView
    default:
      return view
  }
}

/** Fold a whole batch of events, preserving their arrival order. */
export function applyEvents(view: LiveView, events: ServerEvent[]): LiveView {
  return events.reduce(applyEvent, view)
}
