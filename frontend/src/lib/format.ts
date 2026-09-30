/**
 * Display helpers shared by the transcript, claim cards and status bar.
 *
 * Kept in one place so a timestamp, speaker label or source domain looks
 * identical everywhere it appears.
 */

import type { EvidenceSource, VerificationEvent, Verdict } from '../types/events'

/** Format an audio offset in seconds as a debate-style clock, e.g. `1:23.4`. */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00.0'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  return `${minutes}:${remainder.toFixed(1).padStart(4, '0')}`
}

/** Normalise a speaker label for display, with a stable fallback. */
export function displaySpeaker(speaker: string | null | undefined): string {
  if (speaker === null || speaker === undefined) return 'Unknown speaker'
  const trimmed = speaker.trim()
  return trimmed === '' ? 'Unknown speaker' : trimmed
}

/** First letters of a speaker label, for the avatar chip. */
export function speakerInitials(speaker: string | null | undefined): string {
  const label = displaySpeaker(speaker)
  const words = label.split(/\s+/).filter(Boolean)
  const first = words[0]?.[0] ?? '?'
  const second = words.length > 1 ? (words[words.length - 1]?.[0] ?? '') : ''
  return (first + second).toUpperCase()
}

/** A short, stable numeric index for a speaker, for colour assignment. */
export function speakerIndex(speaker: string | null | undefined, order: string[]): number {
  const label = displaySpeaker(speaker)
  const at = order.indexOf(label)
  return at === -1 ? 0 : at
}

/**
 * Extract a display domain from a source reference.
 *
 * The backend's `source` is free text and may legitimately be a bare string
 * such as "No source available", so this never throws.
 */
export function sourceDomain(source: string): string {
  try {
    const url = new URL(source)
    return url.hostname.replace(/^www\./, '')
  } catch {
    return source
  }
}

/** Whether a source is a real URL and can therefore be linked. */
export function isLinkableSource(source: string): boolean {
  try {
    const parsed = new URL(source)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

/**
 * Render a provider relevance score, or state that none was reported.
 *
 * `confidence` is the search provider's own score for the lead source. It is
 * `null` whenever the provider supplied none, and this function's only options
 * are to show that number or to say so. Substituting a default here -- 1.0 for
 * "looks confident", 0.5 for "no idea" -- would publish a number no provider
 * ever returned, which is exactly what this project must never do.
 *
 * A reported score is shown verbatim: no rounding, no padding, no rescaling.
 * Rounding would be a small lie in both directions -- `0.999` displayed as
 * `1.00` reads as perfect confidence from a provider that never claimed it.
 */
export function formatConfidence(confidence: number | null | undefined): string {
  if (!hasConfidence(confidence)) return 'N/A'
  return String(confidence)
}

/** Whether a confidence score was actually reported, as opposed to absent. */
export function hasConfidence(confidence: number | null | undefined): boolean {
  return typeof confidence === 'number' && Number.isFinite(confidence)
}

/** One row of the evidence area on a claim card. */
export interface DisplaySource {
  url: string
  title: string | null
  snippet: string | null
  /** True for the citation in `VerificationEvent.source`. */
  primary: boolean
}

/**
 * Normalise a primary `source` plus a `sources` list into rows to render.
 *
 * The primary `source` string is always the first row, so a claim verified
 * against a backend that sends no `sources` field still renders exactly as it
 * did before. Anything the backend did not already put in `source` follows it,
 * de-duplicated by URL, and each entry carries its own title and snippet.
 *
 * Entries without a usable string URL are skipped rather than rendered as dead
 * text: a citation that cannot be opened or checked is not evidence.
 *
 * Takes the two fields separately rather than a whole event so the ingestion
 * report, whose results use a different field naming, can reuse this instead of
 * fabricating a wire event to pass in.
 */
export function collectSourceRows(
  source: string | null | undefined,
  sources: EvidenceSource[] | undefined,
): DisplaySource[] {
  const rows: DisplaySource[] = []
  const seen = new Set<string>()

  const push = (url: unknown, title: unknown, snippet: unknown, primary: boolean) => {
    if (typeof url !== 'string') return
    const trimmed = url.trim()
    if (trimmed === '' || seen.has(trimmed)) return
    seen.add(trimmed)
    rows.push({
      url: trimmed,
      title: typeof title === 'string' && title.trim() !== '' ? title.trim() : null,
      snippet: typeof snippet === 'string' && snippet.trim() !== '' ? snippet.trim() : null,
      primary,
    })
  }

  push(source, null, null, true)

  if (Array.isArray(sources)) {
    for (const entry of sources) {
      if (entry === null || typeof entry !== 'object') continue
      push(entry.url, entry.title, entry.snippet, false)
    }
  }

  return rows
}

/**
 * Collect the evidence rows for a verification event.
 *
 * A thin wrapper over {@link collectSourceRows} for the live claim cards.
 */
export function collectSources(verification: VerificationEvent): DisplaySource[] {
  return collectSourceRows(verification.source, verification.sources)
}

/** Counters summarising the verdicts resolved so far. */
export interface VerdictTally {
  true: number
  false: number
  unverifiable: number
  /** Sources support more than one reading, so neither branch is confirmed. */
  ambiguous: number
  /** Verdict of the most recently resolved claim, for the hero display. */
  latest: Verdict | null
}

export function tallyVerdicts(
  claims: ReadonlyArray<{ verification: { verdict: Verdict } | null }>,
): VerdictTally {
  const tally: VerdictTally = {
    true: 0,
    false: 0,
    unverifiable: 0,
    ambiguous: 0,
    latest: null,
  }

  for (const card of claims) {
    const verdict = card.verification?.verdict
    if (verdict === 'TRUE') tally.true += 1
    else if (verdict === 'FALSE') tally.false += 1
    else if (verdict === 'UNVERIFIABLE') tally.unverifiable += 1
    else if (verdict === 'AMBIGUOUS') tally.ambiguous += 1
    else continue
    tally.latest = verdict
  }

  return tally
}
