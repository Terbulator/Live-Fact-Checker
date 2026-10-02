/**
 * The conversation thread.
 *
 * One list of what the reader sent, plus the results that came back for the run
 * in progress. Everything here is derived from data the backend actually
 * produced: the event stream for spoken and typed claims, and the ingestion
 * response for recorded media. Nothing in this file invents a claim, a verdict,
 * a source or a count.
 *
 * Two result shapes reach the same conversation -- the live `ClaimCard` list and
 * the ingestion report -- so the roll-ups the sidebar, the result summary and
 * the disclosure rows need are computed once, here, from either.
 */

import { tallyVerdicts } from '../../lib/format'
import type { IngestionResponse } from '../../lib/api'
import type { ClaimCard } from '../../types/model'
import type { Verdict } from '../../types/events'
import { urlLabel, type MediaKind } from '../../lib/media'

/** What the reader attached to a message, if anything. */
export interface Attachment {
  kind: MediaKind
  /** Filename, or the link that was submitted. */
  label: string
  /** Object URL for a local file, so the bubble can show it. Null for links. */
  previewUrl: string | null
  file: File | null
  /** Byte size of a local file, or the media duration when known. */
  size: number | null
}

/** How a run was started, which decides which stages it has. */
export type RunKind = 'claim' | 'url' | 'video' | 'audio' | 'voice'

/** One reader message. */
export interface UserTurn {
  id: string
  text: string
  attachment: Attachment | null
  at: number
  kind: RunKind
  /**
   * The result summary, captured when the run reached a verdict. Held per turn
   * so a completed message keeps its own answer after a later run replaces the
   * live session state.
   */
  outcome: TurnOutcome | null
}

/** The finished answer for one run, in the numbers the reader saw. */
export interface TurnOutcome {
  claims: number
  checked: number
  true: number
  false: number
  unverifiable: number
  ambiguous: number
  sources: number
  /** True when at least one claim could not be checked at all. */
  failed: boolean
  at: number
}

/** The results attached to the run currently in view. */
export type RunResults =
  | { source: 'live'; claims: ClaimCard[]; result: null }
  | { source: 'media'; claims: null; result: IngestionResponse }

function mintId(): string {
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

export function createTurn(input: {
  text: string
  attachment: Attachment | null
  kind: RunKind
  at?: number
}): UserTurn {
  return {
    id: mintId(),
    text: input.text.trim(),
    attachment: input.attachment,
    at: input.at ?? Date.now(),
    kind: input.kind,
    outcome: null,
  }
}

/**
 * Name a conversation after its first meaningful input.
 *
 * Never a session id: those are long, meaningless and would be the only handle
 * a reader had. A typed claim keeps its own words, a link is named by its source,
 * and a file by its filename.
 */
export function deriveTitle(input: { text: string; attachment: Attachment | null }): string {
  const text = input.text.trim()

  if (text !== '' && !/^https?:\/\//i.test(text)) {
    return truncate(text, 52)
  }

  const attachment = input.attachment
  if (attachment !== null) {
    if (attachment.kind === 'url') return `${urlLabel(attachment.label)} check`
    const stem = attachment.label.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim()
    if (stem !== '') return truncate(`${stem} check`, 52)
  }

  if (text !== '') return `${truncate(urlLabel(text), 40)} check`
  return 'New check'
}

function truncate(text: string, max: number): string {
  const collapsed = text.replace(/\s+/g, ' ').trim()
  if (collapsed.length <= max) return collapsed
  const cut = collapsed.slice(0, max)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`
}

/** One source across the whole run, with the provider's own score if it gave one. */
export interface RunSource {
  url: string
  title: string | null
  snippet: string | null
  /** The retrieval provider's relevance score, or null when it reported none. */
  confidence: number | null
}

function emptyToNull(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function scoreOrNull(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * Every source used across a run, de-duplicated, in the order first cited.
 *
 * Built from the raw events rather than from `collectSources` because the
 * provider's relevance score has to survive the roll-up: a reader checking a
 * citation wants to see what the search provider actually said about it.
 */
export function collectRunSources(run: RunResults | null): RunSource[] {
  if (run === null) return []
  const rows: RunSource[] = []
  const index = new Map<string, number>()

  const push = (source: {
    url: string | null | undefined
    title?: string | null
    snippet?: string | null
    confidence?: number | null
  }) => {
    const url = emptyToNull(source.url)
    if (url === null) return
    const confidence = scoreOrNull(source.confidence)
    const existing = index.get(url)
    if (existing !== undefined) {
      const row = rows[existing]
      if (row === undefined) return
      // Already cited by another claim, or the backend listed the same URL as
      // both the primary citation and an evidence row. Keep the first sighting
      // but take anything it was missing: a bare `source` string carries no
      // title, and the same URL in `sources` usually does.
      rows[existing] = {
        url: row.url,
        title: row.title ?? emptyToNull(source.title),
        snippet: row.snippet ?? emptyToNull(source.snippet),
        confidence: row.confidence ?? confidence,
      }
      return
    }
    index.set(url, rows.length)
    rows.push({
      url,
      title: emptyToNull(source.title),
      snippet: emptyToNull(source.snippet),
      confidence,
    })
  }

  const pushAll = (
    source: string | null | undefined,
    sources: ReadonlyArray<{
      url: string
      title?: string | null
      snippet?: string | null
      confidence?: number | null
    }> | null | undefined,
    confidence: number | null | undefined,
  ) => {
    push({ url: source, confidence })
    for (const entry of sources ?? []) {
      push({
        url: entry.url,
        title: entry.title,
        snippet: entry.snippet,
        confidence: entry.confidence,
      })
    }
  }

  if (run.source === 'live') {
    for (const card of run.claims) {
      const verification = card.verification
      if (verification === null) continue
      pushAll(verification.source, verification.sources, verification.confidence)
    }
    return rows
  }

  for (const claim of run.result.claims ?? []) {
    pushAll(claim.source, claim.sources, claim.confidence)
  }
  return rows
}

/** How many claims a run produced, whether resolved or not. */
export function runClaimCount(run: RunResults | null): number {
  if (run === null) return 0
  if (run.source === 'live') return run.claims.length
  if (run.result.claims !== undefined) return run.result.claims.length
  return run.result.claims_extracted
}

/**
 * The verdict counts for a run.
 *
 * A media run prefers the backend's own scorecard, which counts failures
 * separately; a live run counts the verdicts that have actually arrived.
 */
export function tallyRun(run: RunResults | null): TurnOutcome | null {
  if (run === null) return null

  if (run.source === 'media') {
    const { result } = run
    const scorecard = result.scorecard
    if (scorecard !== null && scorecard !== undefined) {
      return {
        claims: scorecard.total_claims,
        checked: scorecard.checked_claims,
        true: scorecard.true_claims,
        false: scorecard.false_claims,
        unverifiable: scorecard.unverifiable_claims,
        ambiguous: scorecard.ambiguous_claims,
        sources: countMediaSources(result),
        failed: scorecard.failed_claims > 0,
        at: Date.now(),
      }
    }
    const claims = result.claims ?? []
    if (claims.length === 0) {
      return {
        claims: result.claims_extracted,
        checked: result.verifications_completed,
        true: 0,
        false: 0,
        unverifiable: 0,
        ambiguous: 0,
        sources: 0,
        failed: result.verifications_completed < result.claims_extracted,
        at: Date.now(),
      }
    }
    return tallyClaims(
      claims.map((claim) => ({
        verification:
          claim.verdict === null
            ? null
            : { verdict: claim.verdict },
      })),
      claims.length,
      countMediaSources(result),
      claims.some((claim) => claim.status === 'failed'),
    )
  }

  if (run.claims.length === 0) return null
  return tallyClaims(run.claims, run.claims.length, collectRunSources(run).length, false)
}

/** The shape `tallyVerdicts` reads, so both run shapes can be counted by it. */
interface VerdictLike {
  verification: { verdict: Verdict } | null
}

function tallyClaims(
  claims: ReadonlyArray<VerdictLike>,
  total: number,
  sources: number,
  failed: boolean,
): TurnOutcome {
  const tally = tallyVerdicts(claims)
  return {
    claims: total,
    checked: tally.true + tally.false + tally.unverifiable + tally.ambiguous,
    true: tally.true,
    false: tally.false,
    unverifiable: tally.unverifiable,
    ambiguous: tally.ambiguous,
    sources,
    failed,
    at: Date.now(),
  }
}

function countMediaSources(result: IngestionResponse): number {
  return collectRunSources({ source: 'media', claims: null, result }).length
}

/** One-line description of the transcript, for a disclosure label. */
export function transcriptDuration(run: RunResults | null): number | null {
  if (run === null) return null
  if (run.source === 'media') {
    const segments = run.result.transcript_segments
    if (segments !== undefined && segments.length > 0) {
      return segments.reduce((latest, segment) => Math.max(latest, segment.end), 0)
    }
    return run.result.duration_seconds ?? null
  }
  if (run.claims.length === 0) return null
  return run.claims.reduce((latest, card) => Math.max(latest, card.timestamp), 0)
}

/** A compact clock for a duration, e.g. `04:32`. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  return `${minutes}:${String(total % 60).padStart(2, '0')}`
}

/** "just now", "4 min ago", "3 hr ago", then a date. */
export function formatRelative(at: number, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} hr ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`
  return new Date(at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
