/**
 * Idle product introduction.
 *
 * Shown until a session starts, in place of the live workspace. Before any
 * speech has been processed there is genuinely nothing to report, so filling
 * the screen with empty panels and "no claims yet" labels wastes the only
 * moment where the product gets to explain itself.
 *
 * This screen therefore does three jobs:
 *
 * 1. names the product and states what it does, in one sentence
 * 2. walks the audience through the six pipeline stages, so the shape of the
 *    system is understood before the first claim lands
 * 3. offers the two ways in, with Start Live as the obvious primary action and
 *    Demo Mode as the credential-free fallback for a stage or a broken mic
 *
 * It is intentionally not a marketing page: no illustrations, no scrolling
 * content, and no controls that do something other than start a session.
 */

import { displaySpeaker } from '../lib/format'
import { VERDICT_DESCRIPTORS } from '../lib/verdicts'

export interface EmptyStateProps {
  /** Starts an empty session for live microphone input. */
  onStartLive: () => void
  /** Starts the scripted mock pipeline, which needs no credentials. */
  onStartDemo: () => void
  /** True while a session is being created, so the actions can show progress. */
  isStarting: boolean
  /** A fault that prevented the last start attempt, surfaced here. */
  fault: string | null
}

const STAGES: { id: string; label: string; hint: string }[] = [
  { id: 'speaking', label: 'Speak', hint: 'Live debate audio' },
  { id: 'transcript', label: 'Transcribe', hint: 'Speech becomes text' },
  { id: 'claim', label: 'Detect claim', hint: 'Checkable statements' },
  { id: 'verify', label: 'Verify', hint: 'Cross-checked evidence' },
  { id: 'verdict', label: 'Verdict', hint: 'True, false or unclear' },
  { id: 'evidence', label: 'Evidence', hint: 'Reason and source' },
]

const VERDICT_LEGEND = [
  { key: 'TRUE', ...VERDICT_DESCRIPTORS.TRUE },
  { key: 'FALSE', ...VERDICT_DESCRIPTORS.FALSE },
  { key: 'UNVERIFIABLE', ...VERDICT_DESCRIPTORS.UNVERIFIABLE },
  { key: 'AMBIGUOUS', ...VERDICT_DESCRIPTORS.AMBIGUOUS },
] as const

export function EmptyState({
  onStartLive,
  onStartDemo,
  isStarting,
  fault,
}: EmptyStateProps) {
  return (
    <section className="intro" aria-label="Getting started">
      <div className="intro__head">
        <span className="intro__mark" aria-hidden="true" />
        <h1 className="intro__title">Live Fact-Checker</h1>
        <p className="intro__lede">
          A live debate is checked while it is still happening. Speak, and every
          checkable claim is transcribed, detected, verified and shown with its
          evidence before the audience moves on.
        </p>
      </div>

      <ol className="intro__stages">
        {STAGES.map((stage, index) => (
          <li className="intro__stage" key={stage.id}>
            <span className="intro__stageIndex" aria-hidden="true">
              {index + 1}
            </span>
            <span className="intro__stageText">
              <span className="intro__stageLabel">{stage.label}</span>
              <span className="intro__stageHint">{stage.hint}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="intro__actions">
        <button
          type="button"
          className="button button--primary button--lg"
          onClick={onStartLive}
          disabled={isStarting}
        >
          {isStarting ? 'Starting…' : 'Start live'}
          <span className="button__sub">Use the microphone</span>
        </button>
        <button
          type="button"
          className="button button--lg"
          onClick={onStartDemo}
          disabled={isStarting}
        >
          Run demo
          <span className="button__sub">Scripted, no credentials</span>
        </button>
      </div>

      <ul className="intro__legend">
        {VERDICT_LEGEND.map((verdict) => (
          <li className={`intro__legendItem intro__legendItem--${verdict.tone}`} key={verdict.key}>
            <span className="intro__legendGlyph" aria-hidden="true">
              {verdict.glyph}
            </span>
            <span className="intro__legendText">
              <strong className="intro__legendLabel">{verdict.short}</strong>
              <span className="intro__legendHint">{verdict.description}</span>
            </span>
          </li>
        ))}
      </ul>

      <p className="intro__note">
        The <code>voice/</code> module posts transcripts to the session this page
        starts, so the dashboard fills in as people talk. Speakers are shown as{' '}
        {displaySpeaker('Speaker 1')} and {displaySpeaker('Speaker 2')} and keep
        the same colour for the whole session.
      </p>

      {fault !== null && (
        <p className="intro__fault" role="alert">
          {fault}
        </p>
      )}
    </section>
  )
}
