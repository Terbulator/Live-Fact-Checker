/**
 * The pipeline, rendered as the six steps a judge should read in order.
 *
 * This is the product's argument in one row: speech becomes a transcript, the
 * transcript yields a claim, the claim is checked, the check produces a verdict,
 * and the verdict carries a reason and a source. Each step lights up as the
 * backend actually reaches it, so progress is observed rather than claimed.
 *
 * The row is numbered and connected by a progress track, because "which stage
 * are we at" is the question a viewer asks when nothing has resolved yet.
 *
 * The stages are derived purely from the view model. Nothing here polls or
 * invents state.
 */

import { displaySpeaker } from '../lib/format'
import type { LiveView } from '../types/model'

export type StageState = 'done' | 'active' | 'pending'

interface Stage {
  id: string
  label: string
  hint: string
}

const STAGES: Stage[] = [
  { id: 'speaking', label: 'Speak', hint: 'Microphone audio' },
  { id: 'transcript', label: 'Transcribe', hint: 'Speech to text' },
  { id: 'claim', label: 'Claim', hint: 'Factual statement' },
  { id: 'checking', label: 'Checking', hint: 'Gathering evidence' },
  { id: 'verdict', label: 'Verdict', hint: 'True / false / unclear' },
  { id: 'evidence', label: 'Evidence', hint: 'Reason and source' },
]

/** How recently speech must have arrived to still read as "talking". */
const SPEAKING_WINDOW_MS = 1800

export interface PipelineFlowProps {
  view: LiveView
  /** True while the session is active, false once stopped or never started. */
  isLive: boolean
  /** Current wall-clock, supplied by the parent tick so this stays pure. */
  now: number
}

/**
 * Determine which step the pipeline is on right now.
 *
 * Ordered from the end backwards: the most advanced thing that has actually
 * happened wins, so the row always shows the furthest point of progress rather
 * than flickering back to the start while a later stage is still running.
 */
function resolveStages(view: LiveView, isLive: boolean, now: number): Record<string, StageState> {
  const hasSpeech = view.transcripts.length > 0
  const hasClaim = view.claims.length > 0
  const pendingCheck = view.claims.some((card) => card.pending)
  const resolved = view.claims.filter((card) => card.verification !== null)
  const hasEvidence = resolved.some(
    (card) => card.verification?.source !== undefined && card.verification.source !== '',
  )

  const speakingNow =
    isLive &&
    view.lastSpeechAt !== null &&
    now - view.lastSpeechAt < SPEAKING_WINDOW_MS

  const state: Record<string, StageState> = {
    speaking: speakingNow ? 'active' : hasSpeech ? 'done' : 'pending',
    transcript: hasSpeech ? 'done' : 'pending',
    claim: hasClaim ? 'done' : 'pending',
    // "Checking" is the only stage that is genuinely in-flight rather than
    // reached, so it is active only while a claim is awaiting its verdict.
    checking: pendingCheck ? 'active' : resolved.length > 0 ? 'done' : 'pending',
    verdict: resolved.length > 0 ? 'done' : 'pending',
    evidence: hasEvidence ? 'done' : 'pending',
  }

  // A session that has not started yet should not imply motion.
  if (!isLive && !hasSpeech && !hasClaim) {
    for (const stage of STAGES) state[stage.id] = 'pending'
  }

  return state
}

export function PipelineFlow({ view, isLive, now }: PipelineFlowProps) {
  const states = resolveStages(view, isLive, now)
  const pendingCard = view.claims.find((card) => card.pending)
  const resolved = view.claims.filter((card) => card.verification !== null)
  const latest = resolved[resolved.length - 1]

  const latestVerification = latest?.verification ?? null

  // A single line of plain language saying what the pipeline is doing right now.
  let caption: string
  if (pendingCard !== undefined) {
    caption = `Checking a claim from ${displaySpeaker(pendingCard.speaker)}…`
  } else if (latestVerification !== null) {
    caption = `Latest verdict ${latestVerification.verdict} — ${latestVerification.reason}`
  } else if (states.speaking === 'active') {
    caption = `${displaySpeaker(view.lastSpeaker)} is speaking…`
  } else if (states.transcript === 'done') {
    caption = 'Listening for a checkable claim.'
  } else {
    caption = 'Start a session to begin fact-checking live speech.'
  }

  const doneCount = STAGES.filter((stage) => states[stage.id] === 'done').length
  const activeIndex = STAGES.findIndex((stage) => states[stage.id] === 'active')
  const progress = activeIndex >= 0 ? activeIndex / (STAGES.length - 1) : doneCount / STAGES.length

  return (
    <section className="flow" aria-label="Fact-checking pipeline">
      <ol className="flow__steps">
        {STAGES.map((stage, index) => (
          <li
            key={stage.id}
            className={`flow__step flow__step--${states[stage.id] ?? 'pending'}`}
            aria-current={states[stage.id] === 'active' ? 'step' : undefined}
          >
            <span className="flow__dot" aria-hidden="true">
              {states[stage.id] === 'done' ? '✓' : index + 1}
            </span>
            <span className="flow__text">
              <span className="flow__label">{stage.label}</span>
              <span className="flow__hint">{stage.hint}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="flow__aside">
        <div
          className="flow__track"
          role="progressbar"
          aria-label="Pipeline progress"
          aria-valuemin={0}
          aria-valuemax={STAGES.length}
          aria-valuenow={activeIndex >= 0 ? activeIndex + 1 : doneCount}
        >
          <span
            className="flow__trackFill"
            style={{ width: `${Math.round(progress * 100)}%` }}
          />
        </div>
        <p className="flow__caption" aria-live="polite">
          {caption}
        </p>
      </div>
    </section>
  )
}
