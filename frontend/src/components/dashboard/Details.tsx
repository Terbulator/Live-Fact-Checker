/**
 * The collapsed half of the result.
 *
 * Four bodies behind four rows: the claims with their verdicts, every source
 * cited, the transcript with its timestamps and speakers, and what the pipeline
 * actually did. Each renders the components that already own that data, so the
 * evidence, the supporting statement and the provider confidence keep working
 * exactly as they did.
 *
 * Two result shapes arrive here -- the live claim stream and the ingestion
 * report -- and the claims body switches between the two components built for
 * them rather than reshaping either one's data.
 *
 * The counts in each row are real: a bucket the run measured and found empty
 * says so, and a section with nothing in it is disabled rather than opened onto
 * an empty list.
 */

import { ClaimCard } from '../ClaimCard'
import { TranscriptPanel } from '../TranscriptPanel'
import { VideoClaimList } from '../VideoClaimList'
import {
  displaySpeaker,
  formatClock,
  formatConfidence,
  hasConfidence,
  isLinkableSource,
  sourceDomain,
} from '../../lib/format'
import { formatBytes } from '../../lib/media'
import { Disclosure } from './Disclosure'
import { collectRunSources, formatDuration, transcriptDuration } from './thread'
import type { RunResults } from './thread'

/** Facts about the submitted file, when the turn carried one. */
export interface SubmittedMedia {
  label: string
  size: number | null
}

/** One processing stage, as the pipeline itself resolved it. */
export type StepState = 'done' | 'active' | 'pending' | 'failed'

export interface DetailsProps {
  run: RunResults | null
  /** Live transcript lines, which arrive on the session stream. */
  transcript: import('../../types/model').TranscriptLine[]
  steps: Array<{ id: string; label: string; state: StepState }>
  media: SubmittedMedia | null
  /** Transcript line to highlight, resolved from the selected claim. */
  activeKey: string | null
  selectedClaimId: string | null
  onSelectClaim: (claimId: string) => void
}

export function ClaimsSection({ run, selectedClaimId, onSelectClaim }: DetailsProps) {
  const claims =
    run === null
      ? 0
      : run.source === 'live'
        ? run.claims.length
        : (run.result.claims?.length ?? run.result.claims_extracted)

  if (run === null || claims === 0) {
    return (
      <Disclosure label="Claims" meta="none found" disabled>
        <p className="reveal__empty">No claims have been extracted yet.</p>
      </Disclosure>
    )
  }

  const checked =
    run.source === 'live'
      ? run.claims.filter((card) => card.verification !== null).length
      : (run.result.verifications_completed ?? claims)

  return (
    <Disclosure
      label="Claims"
      meta={`${claims} found · ${checked} checked`}
    >
      {run.source === 'live' ? (
        <ul className="cards">
          {run.claims.map((card) => (
            <ClaimCard
              key={card.claimId}
              card={card}
              selected={card.claimId === selectedClaimId}
              onSelect={onSelectClaim}
            />
          ))}
        </ul>
      ) : (
        <VideoClaimList results={run.result.claims ?? []} />
      )}
    </Disclosure>
  )
}

export function SourcesSection({ run }: { run: RunResults | null }) {
  const sources = collectRunSources(run)

  return (
    <Disclosure
      label="Sources"
      meta={sources.length === 0 ? null : `${sources.length} used`}
      disabled={sources.length === 0}
    >
      <ul className="sources">
        {sources.map((source) => (
          <li key={source.url} className="source">
            <p className="source__title">
              {isLinkableSource(source.url) ? (
                <a href={source.url} target="_blank" rel="noreferrer noopener">
                  {source.title ?? sourceDomain(source.url)}
                </a>
              ) : (
                (source.title ?? source.url)
              )}
              <span className="source__domain">{sourceDomain(source.url)}</span>
            </p>
            {source.snippet !== null && <p className="source__snippet">{source.snippet}</p>}
            {hasConfidence(source.confidence) && (
              <p className="source__score">
                Provider relevance {formatConfidence(source.confidence)}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Disclosure>
  )
}

export function TranscriptSection({
  transcript,
  run,
  activeKey,
}: {
  transcript: DetailsProps['transcript']
  run: RunResults | null
  activeKey: string | null
}) {
  const mediaSegments = run?.source === 'media' ? run.result.transcript_segments : undefined
  const duration = transcriptDuration(run)
  const segments = mediaSegments?.length ?? 0
  const total = transcript.length > 0 ? transcript.length : segments

  if (total === 0) {
    return (
      <Disclosure label="Transcript" meta="none yet" disabled>
        <p className="reveal__empty">No transcript has been produced yet.</p>
      </Disclosure>
    )
  }

  return (
    <Disclosure
      label="Transcript"
      meta={`${duration !== null ? `${formatDuration(duration)} · ` : ''}${total} ${total === 1 ? 'segment' : 'segments'}`}
    >
      {transcript.length > 0 ? (
        <TranscriptPanel lines={transcript} activeKey={activeKey} />
      ) : (
        <ol className="segments">
          {(mediaSegments ?? []).map((segment, index) => (
            <li key={`${segment.start}-${index}`} className="segment">
              <span className="segment__clock">{formatClock(segment.start)}</span>
              <span className="segment__speaker">{displaySpeaker(segment.speaker)}</span>
              <span className="segment__text">{segment.text}</span>
            </li>
          ))}
        </ol>
      )}
    </Disclosure>
  )
}

/** How each stage state is read aloud. */
const STEP_WORDS: Record<StepState, string> = {
  done: 'done',
  active: 'in progress',
  pending: 'not started',
  failed: 'failed',
}

export function ProcessingSection({ steps, media }: Pick<DetailsProps, 'steps' | 'media'>) {
  const done = steps.filter((step) => step.state === 'done').length

  return (
    <Disclosure
      label="Processing details"
      meta={`${done} of ${steps.length} stages`}
    >
      <ol className="steps">
          {steps.map((step) => (
            <li key={step.id} className={`step step--${step.state}`}>
              <span className="step__marker" aria-hidden="true" />
              <span className="step__label">{step.label}</span>
              {/* The marker carries the state visually, so the state is said
                  here: colour and a filled dot are not available to everyone. */}
              <span className="sr-only">{STEP_WORDS[step.state]}</span>
            </li>
          ))}
      </ol>
      {media !== null && (
        <p className="steps__media">
          {media.label}
          {media.size !== null && ` · ${formatBytes(media.size)}`}
        </p>
      )}
    </Disclosure>
  )
}
