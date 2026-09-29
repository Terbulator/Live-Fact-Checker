/**
 * Verdict presentation helpers.
 *
 * The verdict itself arrives uppercase from the backend. This module owns
 * everything about how a verdict *looks*, keeping `TRUE` / `FALSE` /
 * `UNVERIFIABLE` as the only values the UI branches on.
 */

import type { Verdict } from '../types/events'

export interface VerdictDescriptor {
  label: string
  /** Short form for dense UI, e.g. the status pill. */
  short: string
  /** Semantic role; mapped to a colour in `index.css`. */
  tone: 'supported' | 'refuted' | 'unknown'
  /** Plain-language explanation shown in a legend or tooltip. */
  description: string
}

export const VERDICT_DESCRIPTORS: Record<Verdict, VerdictDescriptor> = {
  TRUE: {
    label: 'True',
    short: 'TRUE',
    tone: 'supported',
    description: 'Evidence corroborates the claim.',
  },
  FALSE: {
    label: 'False',
    short: 'FALSE',
    tone: 'refuted',
    description: 'Evidence contradicts the claim.',
  },
  UNVERIFIABLE: {
    label: 'Unverifiable',
    short: 'UNVERIFIABLE',
    tone: 'unknown',
    description: 'Evidence is missing, weak or conflicting.',
  },
}

const FALLBACK: VerdictDescriptor = {
  label: 'Unknown verdict',
  short: 'UNKNOWN',
  tone: 'unknown',
  description: 'The backend reported a verdict this build does not recognise.',
}

/**
 * Describe a verdict, degrading safely for a value this build does not know.
 *
 * The backend validates verdicts strictly, so an unknown value means the
 * backend and frontend builds disagree. Showing `UNKNOWN` is better than
 * crashing the live stream.
 */
export function describeVerdict(verdict: string): VerdictDescriptor {
  return VERDICT_DESCRIPTORS[verdict as Verdict] ?? FALLBACK
}

/**
 * Whether a verdict confirms a claim.
 *
 * `UNVERIFIABLE` is deliberately not treated as either: the verification
 * module's core principle is that missing evidence is never a pass.
 */
export function isSupported(verdict: string): boolean {
  return verdict === 'TRUE'
}
