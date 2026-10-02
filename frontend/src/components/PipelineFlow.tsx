/**
 * The pipeline, as one compact row of stages.
 *
 * Every marker reflects something the backend has actually done: a transcript
 * event means transcription is done, a claim event means extraction is done, a
 * verification carrying sources means evidence was found. Nothing is estimated,
 * and there is deliberately no percentage -- the backend reports no progress
 * figure, so a bar would be the interface inventing a measurement. The reader
 * is told which stage is running instead.
 *
 * The stage list is resolved here and passed upward, so the "processing details"
 * disclosure and this row can never disagree about what has happened.
 *
 * Horizontal on a desktop, a vertical timeline on a narrow screen -- the same
 * markup, turned by one breakpoint.
 */

import { Check, CircleAlert, LoaderCircle } from 'lucide-react'

import type { RunKind } from './dashboard/thread'

export type StageState = 'done' | 'active' | 'pending' | 'failed'

export interface Stage {
  id: string
  label: string
  state: StageState
}

export interface PipelineInput {
  kind: RunKind
  /** The submission was accepted and a session exists. */
  submitted: boolean
  /** Audio extraction, for a video file. */
  extracted: boolean
  /** A transcript exists, from the stream or the ingestion response. */
  transcribed: boolean
  /** Claims have been extracted. */
  claims: number
  /** At least one claim is awaiting its verdict. */
  checking: boolean
  /** A verification carried at least one citable source. */
  evidence: boolean
  /** Nothing is in flight and something was checked. */
  complete: boolean
  /** A failure the reader can see, which fails the first unfinished stage. */
  failed: boolean
  /** The microphone is open. */
  listening: boolean
}

interface Definition {
  id: string
  label: string
  /** What must be true for this stage to be done. */
  done: (input: PipelineInput) => boolean
  /** What must be true for it to be the running stage. */
  active: (input: PipelineInput) => boolean
}

const DEFINITIONS: Record<RunKind, Definition[]> = {
  video: [
    { id: 'received', label: 'Video received', done: (i) => i.submitted, active: () => false },
    { id: 'audio', label: 'Audio extracted', done: (i) => i.extracted, active: (i) => i.submitted && !i.extracted },
    { id: 'transcript', label: 'Transcript generated', done: (i) => i.transcribed, active: (i) => i.extracted && !i.transcribed },
    { id: 'claims', label: 'Claims extracted', done: (i) => i.claims > 0, active: (i) => i.transcribed && i.claims === 0 },
    { id: 'evidence', label: 'Evidence found', done: (i) => i.evidence, active: (i) => i.claims > 0 && !i.evidence && !i.checking },
    { id: 'verified', label: 'Claims verified', done: (i) => i.complete, active: (i) => i.evidence && !i.complete },
  ],
  audio: [
    { id: 'received', label: 'Audio received', done: (i) => i.submitted, active: () => false },
    { id: 'transcript', label: 'Transcript generated', done: (i) => i.transcribed, active: (i) => i.submitted && !i.transcribed },
    { id: 'claims', label: 'Claims extracted', done: (i) => i.claims > 0, active: (i) => i.transcribed && i.claims === 0 },
    { id: 'evidence', label: 'Evidence found', done: (i) => i.evidence, active: (i) => i.claims > 0 && !i.evidence && !i.checking },
    { id: 'verified', label: 'Claims verified', done: (i) => i.complete, active: (i) => i.evidence && !i.complete },
  ],
  url: [
    { id: 'received', label: 'Link received', done: (i) => i.submitted, active: () => false },
    { id: 'fetched', label: 'Video fetched', done: (i) => i.extracted, active: (i) => i.submitted && !i.extracted },
    { id: 'transcript', label: 'Transcript generated', done: (i) => i.transcribed, active: (i) => i.extracted && !i.transcribed },
    { id: 'claims', label: 'Claims extracted', done: (i) => i.claims > 0, active: (i) => i.transcribed && i.claims === 0 },
    { id: 'evidence', label: 'Evidence found', done: (i) => i.evidence, active: (i) => i.claims > 0 && !i.evidence && !i.checking },
    { id: 'verified', label: 'Claims verified', done: (i) => i.complete, active: (i) => i.evidence && !i.complete },
  ],
  voice: [
    { id: 'listening', label: 'Listening', done: (i) => !i.listening && i.submitted, active: (i) => i.listening },
    { id: 'transcript', label: 'Transcript generated', done: (i) => i.transcribed, active: (i) => !i.listening && i.submitted && !i.transcribed },
    { id: 'claims', label: 'Claims extracted', done: (i) => i.claims > 0, active: (i) => i.transcribed && i.claims === 0 },
    { id: 'evidence', label: 'Evidence found', done: (i) => i.evidence, active: (i) => i.claims > 0 && !i.evidence && !i.checking },
    { id: 'verified', label: 'Claims verified', done: (i) => i.complete, active: (i) => i.evidence && !i.complete },
  ],
  claim: [
    { id: 'received', label: 'Claim received', done: (i) => i.submitted, active: () => false },
    { id: 'checking', label: 'Checking claim', done: (i) => i.complete, active: (i) => i.submitted && !i.complete },
    { id: 'evidence', label: 'Evidence found', done: (i) => i.evidence, active: () => false },
    { id: 'verified', label: 'Verdict reached', done: (i) => i.complete && i.evidence, active: () => false },
  ],
}

/**
 * Resolve every stage to a state.
 *
 * Completed stages are marked from the back: the furthest thing that has
 * actually happened wins, so the row shows real progress instead of flickering
 * back to the start while a later stage is still running.
 */
export function resolveStages(input: PipelineInput): Stage[] {
  const definitions = DEFINITIONS[input.kind]
  const stages: Stage[] = definitions.map((definition) => ({
    id: definition.id,
    label: definition.label,
    state: definition.done(input) ? 'done' : 'pending',
  }))

  if (!stages.some((stage) => stage.state === 'done')) {
    // Nothing has happened yet: the first stage is the one about to.
    const first = stages[0]
    if (first !== undefined) first.state = input.failed ? 'failed' : 'active'
    return stages
  }

  const firstUnfinished = stages.findIndex((stage) => stage.state === 'pending')
  if (firstUnfinished !== -1) {
    const stage = stages[firstUnfinished]
    const definition = definitions[firstUnfinished]
    if (stage === undefined) return stages
    if (definition !== undefined && definition.active(input)) {
      stage.state = 'active'
    } else if (input.failed) {
      stage.state = 'failed'
    }
  }

  return stages
}

/** A single sentence describing where the pipeline is, for the live region. */
export function describeProgress(stages: Stage[]): string {
  const active = stages.find((stage) => stage.state === 'active')
  if (active !== undefined) return `${active.label}…`
  const failed = stages.find((stage) => stage.state === 'failed')
  if (failed !== undefined) return `${failed.label} failed.`
  const last = stages[stages.length - 1]
  if (last !== undefined && last.state === 'done') return 'Processing complete.'
  return 'Waiting to start.'
}

export function PipelineFlow({ stages }: { stages: Stage[] }) {
  return (
    <section className="pipe" aria-label="Fact-checking pipeline">
      <ol className="pipe__list">
        {stages.map((stage, index) => (
          <li
            key={stage.id}
            className={`pipe__step pipe__step--${stage.state}`}
            aria-current={stage.state === 'active' ? 'step' : undefined}
          >
            <span className="pipe__marker" aria-hidden="true">
              {stage.state === 'done' ? (
                <Check size={12} />
              ) : stage.state === 'active' ? (
                <LoaderCircle size={12} className="spin" />
              ) : stage.state === 'failed' ? (
                <CircleAlert size={12} />
              ) : null}
            </span>
            <span className="pipe__label">{stage.label}</span>
            {index < stages.length - 1 && <span className="pipe__link" aria-hidden="true" />}
          </li>
        ))}
      </ol>
      <p className="sr-only" aria-live="polite">
        {describeProgress(stages)}
      </p>
    </section>
  )
}
