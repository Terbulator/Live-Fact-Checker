/**
 * View model types.
 *
 * These are the frontend's own shapes, derived from the wire contracts in
 * `types/events.ts`. Keeping them separate means a contract addition does not
 * force a component rewrite.
 */

import type {
  ErrorEvent,
  SessionEventStatus,
  SessionStatus,
  VerificationEvent,
} from './events'

/** One rendered line of live speech. */
export interface TranscriptLine {
  /** Stable React key: speaker plus the segment's audio timestamp. */
  key: string
  speaker: string | null
  text: string
  timestamp: number
  /** False while AssemblyAI is still revising the utterance. */
  isFinal: boolean
  /** Set once a claim has been extracted from this line. */
  claimId: string | null
}

/** A claim under check, plus its verdict once verification completes. */
export interface ClaimCard {
  claimId: string
  speaker: string | null
  timestamp: number
  claim: string
  claimType: string
  /** True between the `claim` event and its `verification`. */
  pending: boolean
  verification: VerificationEvent | null
}

/** Everything the live view renders, reduced from the event stream. */
export interface LiveView {
  transcripts: TranscriptLine[]
  claims: ClaimCard[]
  errors: ErrorEvent[]
  status: SessionEventStatus | SessionStatus | 'idle'
}

/** The initial, empty view. */
export const initialLiveView: LiveView = {
  transcripts: [],
  claims: [],
  errors: [],
  status: 'idle',
}
