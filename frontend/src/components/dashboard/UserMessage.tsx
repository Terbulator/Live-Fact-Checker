/**
 * One reader message.
 *
 * Right-aligned and compact, because it is input rather than content: the reader
 * wrote it and does not need to read it back at length. What it carries is
 * stated in one line -- "YouTube URL", "Video", "Audio", "Voice" -- followed by
 * the text, and an attachment gets a small preview rather than a panel of its
 * own.
 *
 * A finished turn keeps the summary it produced, so the thread reads as a
 * conversation that has already been answered rather than a log that resets.
 */

import { FileAudio, Film, Link2, Mic } from 'lucide-react'

import { formatBytes, urlLabel } from '../../lib/media'
import { formatRelative } from './thread'
import type { RunKind, TurnOutcome, UserTurn } from './thread'

export interface UserMessageProps {
  turn: UserTurn
  /** Live clock, supplied by the parent so this component stays pure. */
  now: number
}

const KIND_LABEL: Record<RunKind, string> = {
  claim: 'Typed claim',
  url: 'YouTube URL',
  video: 'Video',
  audio: 'Audio',
  voice: 'Voice',
}

const KIND_ICON: Record<RunKind, typeof Link2> = {
  claim: Link2,
  url: Link2,
  video: Film,
  audio: FileAudio,
  voice: Mic,
}

export function UserMessage({ turn, now }: UserMessageProps) {
  const Icon = KIND_ICON[turn.kind]
  const attachment = turn.attachment

  return (
    <article className="turn turn--you" aria-label="Your message">
      <div className="bubble">
        <p className="bubble__kind">
          <Icon size={13} aria-hidden="true" />
          <span>{KIND_LABEL[turn.kind]}</span>
          <span className="bubble__time">{formatRelative(turn.at, now)}</span>
        </p>

        {turn.text !== '' && <p className="bubble__text">{turn.text}</p>}

        {attachment !== null && attachment.kind !== 'url' && (
          <span className="bubble__attach">
            {attachment.kind === 'video' && attachment.previewUrl !== null ? (
              <video className="bubble__thumb" src={attachment.previewUrl} muted />
            ) : (
              <span className="bubble__attachIcon" aria-hidden="true">
                <Icon size={14} />
              </span>
            )}
            <span className="bubble__attachBody">
              <span className="bubble__attachName">{attachment.label}</span>
              {attachment.size !== null && (
                <span className="bubble__attachMeta">{formatBytes(attachment.size)}</span>
              )}
            </span>
          </span>
        )}

        {attachment !== null && attachment.kind === 'url' && (
          <a
            className="bubble__link"
            href={attachment.label}
            target="_blank"
            rel="noreferrer noopener"
          >
            {urlLabel(attachment.label)}
          </a>
        )}
      </div>

      {turn.outcome !== null && <TurnSummary outcome={turn.outcome} />}
    </article>
  )
}

/** The answer a completed turn already gave, kept to a single line. */
function TurnSummary({ outcome }: { outcome: TurnOutcome }) {
  return (
    <p className="turn__outcome">
      <span className="turn__outcomeLabel">Fact-check complete</span>
      <span>
        {outcome.claims} {outcome.claims === 1 ? 'claim' : 'claims'}
        {outcome.checked > 0 && (
          <>
            {' · '}
            {outcome.true} true, {outcome.false} false, {outcome.unverifiable} unverifiable
            {outcome.ambiguous > 0 && `, ${outcome.ambiguous} ambiguous`}
          </>
        )}
      </span>
    </p>
  )
}
