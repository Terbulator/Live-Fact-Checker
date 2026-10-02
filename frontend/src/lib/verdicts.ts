/**
 * Verdict presentation helpers.
 *
 * The verdict itself arrives uppercase from the backend. This module owns
 * everything about how a verdict *looks*, keeping `TRUE` / `FALSE` /
 * `UNVERIFIABLE` as the only values the UI branches on.
 *
 * Every tone ships a glyph as well as a colour, because hue alone is not a
 * sufficient signal: a verdict must still be readable to someone who cannot
 * separate red from green, or on a washed-out projector.
 */

import type { Verdict } from '../types/events'

/**
 * Semantic tone, mapped to a colour and a set of styles in `dashboard.css`.
 *
 * `ambiguous` is separate from `unknown` on purpose. `UNVERIFIABLE` means the
 * evidence is missing or weak -- an attention state -- while `AMBIGUOUS` means
 * the evidence supports more than one reading of the claim, which is a finding
 * in its own right. Collapsing them into one colour told a reader that a
 * genuinely contested claim was simply unproven.
 */
export type VerdictTone = 'supported' | 'refuted' | 'unknown' | 'ambiguous' | 'checking'

export interface VerdictDescriptor {
  label: string
  /** Short form for dense UI, e.g. the status pill. */
  short: string
  /** Semantic role; mapped to a colour in `index.css`. */
  tone: VerdictTone
  /** Plain-language explanation shown in a legend or tooltip. */
  description: string
  /** Text glyph so the verdict is legible without relying on colour. */
  glyph: string
}

export const VERDICT_DESCRIPTORS: Record<Verdict, VerdictDescriptor> = {
  TRUE: {
    label: 'True',
    short: 'TRUE',
    tone: 'supported',
    description: 'Evidence corroborates the claim.',
    glyph: '✓',
  },
  FALSE: {
    label: 'False',
    short: 'FALSE',
    tone: 'refuted',
    description: 'Evidence contradicts the claim.',
    glyph: '✕',
  },
  UNVERIFIABLE: {
    label: 'Unverifiable',
    short: 'UNVERIFIABLE',
    tone: 'unknown',
    description: 'Evidence is missing, weak or conflicting.',
    glyph: '?',
  },
  AMBIGUOUS: {
    label: 'Ambiguous',
    short: 'AMBIGUOUS',
    tone: 'ambiguous',
    description: 'Evidence supports more than one reading of the claim.',
    glyph: '~',
  },
}

const FALLBACK: VerdictDescriptor = {
  label: 'Unknown verdict',
  short: 'UNKNOWN',
  tone: 'unknown',
  description: 'The backend reported a verdict this build does not recognise.',
  glyph: '?',
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
 * Describe a claim that has been detected but not yet verified.
 *
 * `CHECKING` is not a verdict and never appears on the wire; it only exists in
 * the view model between a `claim` event and its `verification`. It borrows the
 * verdict interface so cards, the result zone and the tally can treat it as one
 * more state instead of special-casing it in four places.
 */
export const CHECKING_DESCRIPTOR: VerdictDescriptor = {
  label: 'Checking',
  short: 'CHECKING',
  tone: 'checking',
  description: 'Evidence is being gathered for this claim.',
  glyph: '◐',
}

/** Describe either a pending claim or a resolved verdict. */
export function describeCard(card: {
  pending: boolean
  verification: { verdict: Verdict } | null
}): VerdictDescriptor {
  if (card.verification !== null) return describeVerdict(card.verification.verdict)
  return CHECKING_DESCRIPTOR
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
