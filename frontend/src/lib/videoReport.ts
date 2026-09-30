/**
 * Pure helpers for presenting an ingested video's fact-check results.
 *
 * The backend computes the scorecard; this module only reads it and turns it into
 * things a person can read. It deliberately contains no arithmetic of its own on
 * verdicts -- every number shown comes from the backend's scorecard, so the UI
 * cannot disagree with the result it is reporting.
 *
 * One rule runs through all of it: **a measurement that was not taken is shown
 * as unavailable, never as a number.** A video where nothing could be verified
 * has no accuracy figure, and rendering that as `0%` would state that nothing in
 * it was true. `null` in, "not available" out.
 */

import type { Verdict } from '../types/events'
import type { VideoClaimResult, VideoScorecard } from './api'

/**
 * Render a share of checked claims, e.g. `0.25` as `25%`.
 *
 * Returns `null` when the backend reported no ratio, which happens when nothing
 * was checked. Callers must render that absence as text rather than
 * substituting a default.
 */
export function formatShare(ratio: number | null | undefined): string | null {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return null
  return `${Math.round(ratio * 100)}%`
}

/** One row of the verdict distribution in the scorecard. */
export interface ScorecardRow {
  verdict: Verdict
  label: string
  count: number
  /** `null` when nothing was checked and no share exists. */
  share: string | null
  /** Whether this row should be called out as a failure to check. */
  isFailure: boolean
}

/**
 * Build the verdict distribution rows, in a fixed order.
 *
 * The order is fixed rather than sorted by size so the scorecard reads the same
 * way every time and a reviewer can find any verdict without hunting.
 */
export function scorecardRows(scorecard: VideoScorecard): ScorecardRow[] {
  return [
    {
      verdict: 'TRUE',
      label: 'True',
      count: scorecard.true_claims,
      share: formatShare(scorecard.true_ratio),
      isFailure: false,
    },
    {
      verdict: 'FALSE',
      label: 'False',
      count: scorecard.false_claims,
      share: formatShare(scorecard.false_ratio),
      isFailure: false,
    },
    {
      verdict: 'AMBIGUOUS',
      label: 'Ambiguous',
      count: scorecard.ambiguous_claims,
      share: formatShare(scorecard.ambiguous_ratio),
      isFailure: false,
    },
    {
      verdict: 'UNVERIFIABLE',
      label: 'Unverifiable',
      count: scorecard.unverifiable_claims,
      share: formatShare(scorecard.unverifiable_ratio),
      isFailure: false,
    },
    {
      verdict: 'UNVERIFIABLE',
      label: 'Not checked',
      count: scorecard.failed_claims,
      // Deliberately no share. A failed check is not a verdict, so it has no
      // place in the distribution of verdicts -- giving it one would invite the
      // reader to add it up to 100% and read a finding that was never measured.
      share: null,
      isFailure: true,
    },
  ]
}

/**
 * How much of the video was actually checked, as a sentence.
 *
 * Coverage is stated separately from the verdict distribution because "nothing
 * in this video was true" and "nothing in this video could be checked" are very
 * different findings, and only the first is a claim about the video.
 */
export function coverageSentence(scorecard: VideoScorecard): string {
  const share = formatShare(scorecard.coverage_ratio)
  if (scorecard.total_claims === 0) return 'No checkable claims were found in this video.'
  if (scorecard.checked_claims === 0) {
    return `None of the ${scorecard.total_claims} claims could be checked, so there is no verdict breakdown.`
  }
  const basis = share === null ? `${scorecard.checked_claims} of ${scorecard.total_claims}` : `${share} (${scorecard.checked_claims} of ${scorecard.total_claims})`
  return `Based on the ${basis} claims that produced a verdict.`
}

/** Whether a claim produced a verdict, as opposed to failing to be checked. */
export function isVerified(result: VideoClaimResult): boolean {
  return result.status === 'verified' && result.verdict !== null
}

/**
 * Sort results into the order a reviewer wants them: false claims first, then
 * everything else by position in the video.
 *
 * False claims lead because they are the reason to watch the result at all. The
 * rest stay in timestamp order so the list still reads as a walk through the
 * video.
 */
export function orderResultsForReview(
  results: ReadonlyArray<VideoClaimResult>,
): VideoClaimResult[] {
  return [...results].sort((a, b) => {
    const aFalse = a.verdict === 'FALSE' ? 0 : 1
    const bFalse = b.verdict === 'FALSE' ? 0 : 1
    if (aFalse !== bFalse) return aFalse - bFalse
    return a.timestamp - b.timestamp
  })
}

/** The claims the backend refuted, in video order. */
export function falseClaims(
  results: ReadonlyArray<VideoClaimResult>,
): VideoClaimResult[] {
  return results.filter((result) => result.verdict === 'FALSE')
}

/**
 * The one-line status for a claim row.
 *
 * A failed check says so in its own words, so it can never be misread as a
 * verdict that nothing was found.
 */
export function describeOutcome(result: VideoClaimResult): string {
  return isVerified(result) ? 'Verified' : 'Could not check'
}

/**
 * A completion message that reports only what happened.
 *
 * Deliberately includes the failed count when there is one. The tempting phrasing
 * -- "verified N of M claims" -- reads as a clean result even when the shortfall
 * is a broken retrieval rather than an absence of checkable claims, so a failure
 * is always surfaced in the sentence itself.
 */
export function completionMessage(result: {
  claims_extracted: number
  verifications_completed: number
  scorecard?: VideoScorecard | null
}): string {
  const checked = result.verifications_completed
  const total = result.claims_extracted
  const base = `Found ${total} claim${total === 1 ? '' : 's'}, verified ${checked}.`

  const failed = result.scorecard?.failed_claims ?? 0
  if (failed > 0) {
    return `${base} ${failed} could not be checked.`
  }
  return base
}
